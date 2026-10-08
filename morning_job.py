"""Morning summary (plan phase 23): launchd runs it Mon-Fri at 08:30 local time (./schedule.sh install).

It replaces the old morning report (the Report page no longer exists). If something is relevant today it shows a
window with: US macro events of today (Italian time), earnings of my stocks (favourites and portfolio) in the next
5 days, how many positions are in "Rivedi la tesi", sessions missing from the signal diary. Two buttons: "Chiudi" and
"Apri la pagina Oggi" (the dashboard, started with the app if it is closed). With nothing relevant: no window.
A macOS notification cannot open a web page when clicked (it opens Script Editor), hence a window; it closes by
itself after 30 minutes, so the job never stays blocked.

    .venv/bin/python morning_job.py            # build the summary and show the window
    .venv/bin/python morning_job.py --print    # only print the summary (no window)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import server

ROME = ZoneInfo("Europe/Rome")
EARNINGS_DAYS = 5
WINDOW_SECONDS = 30 * 60
URL = "http://localhost:8100/#overview"
APP = os.path.join(server.ROOT, "Nasdaq-100 Monitor.app")
DAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
MACRO_TITLE = {"fomc": "Riunione della Fed (FOMC)", "cpi": "Inflazione CPI", "pce": "Inflazione PCE", "jobs": "Rapporto sull'occupazione"}

log = logging.getLogger("ndx")


def day_it(d):
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def when_it(ts_et):
    """'prima dell'apertura' / 'dopo la chiusura' from the New York hour (Yahoo gives 00:00 when the time is unknown)."""
    h = ts_et.hour
    return "prima dell'apertura" if 0 < h < 12 else "dopo la chiusura" if h >= 16 else ""


def summary_text(today, macro, earnings, review, missing):
    """The window text (None when nothing is relevant). macro: [(title, "14:30")]; earnings: [(ticker, date, when, where)];
    review: number of positions in "Rivedi la tesi"; missing: ISO dates of sessions without diary."""
    parts = []
    if macro:
        parts.append("Eventi macro di oggi\n" + "\n".join(f"· {t} alle {hm} ora italiana" for t, hm in macro))
    if earnings:
        parts.append(f"Trimestrali dei tuoi titoli nei prossimi {EARNINGS_DAYS} giorni\n"
                     + "\n".join(f"· {t} {day_it(d)}{', ' + w if w else ''} ({where})" for t, d, w, where in earnings))
    if review:
        parts.append(f"Posizioni in «Rivedi la tesi»: {review}")
    if missing:
        ds = ", ".join(f"{int(d[8:])} {MONTHS[int(d[5:7]) - 1]}" for d in missing[-5:])
        parts.append(f"Diario dei segnali: {'manca' if len(missing) == 1 else 'mancano'} {len(missing)} "
                     f"{'seduta' if len(missing) == 1 else 'sedute'} ({ds}{' e altre' if len(missing) > 5 else ''})")
    if not parts:
        return None
    return f"Nasdaq-100 Monitor · {day_it(today)}\n\n" + "\n\n".join(parts) + "\n\nScreening automatico, non è una consulenza finanziaria."


def collect():
    """Everything the summary needs, computed with the dashboard's own code (no window, nothing written)."""
    import analysts
    import diary
    import macro_calendar
    import portfolio
    import risk
    import yfinance as yf
    store = server.store
    store.constituents = server.load_constituents()
    tickers = [c["ticker"] for c in store.constituents]
    store.infos = server.load_infos(tickers)
    store.analysts = analysts.load(tickers) if not analysts.is_fresh() else analysts.cached_data()
    store.refresh_daily()
    store.refresh_intraday()
    store.build()
    macro_calendar.refresh()
    portfolio.refresh()
    for _ in range(180):
        if not portfolio._state["resolving"]:
            break
        time.sleep(1)
    portfolio.refresh_quotes()
    mine = [p["ticker"] for p in portfolio.snapshot().get("positions") or [] if p.get("ticker")]
    if mine:                                             # the 200-day average of every position (rule V3) needs 2 years of prices
        for _ in range(120):
            if risk.history(mine) is not None:
                break
            time.sleep(1)
    pf = server.portfolio_view()
    today = datetime.now(ROME).date()
    # macro events of today, Italian time
    macro = [(MACRO_TITLE.get(e["kind"], e["kind"]) + (f" ({e['ref'][5:7]}/{e['ref'][:4]})" if e.get("ref") else ""),
              datetime.fromtimestamp(e["ts"], ROME).strftime("%H:%M")) for e in macro_calendar.upcoming(0)["events"]]
    # earnings of my stocks: favourites and portfolio
    try:
        with open(server.WATCHLIST) as f:
            watch = json.load(f).get("tickers", [])
    except Exception:
        watch = []
    held = {p["ticker"]: p for p in pf.get("positions") or [] if p.get("ticker")}
    rows = {r["ticker"]: r for r in store.snapshot["stocks"]}
    last = today + timedelta(days=EARNINGS_DAYS)
    earn = []
    for t in sorted(set(watch) | set(held)):
        where = "in portafoglio" if t in held else "preferito"
        if t in rows and rows[t].get("earningsTs"):
            ts = datetime.fromtimestamp(rows[t]["earningsTs"], server.ET)
            d, w = ts.date(), when_it(ts)
        elif t in held and not portfolio.is_fund(held[t]["kind"]):
            try:                                         # a stock outside the Nasdaq-100: one Yahoo request
                dates = (yf.Ticker(t).calendar or {}).get("Earnings Date") or []
                d, w = (dates[0], "") if dates else (None, "")
            except Exception:
                d, w = None, ""
        else:
            d = None
        if d and today <= d <= last:
            earn.append((t, d, w, where))
    earn.sort(key=lambda x: (x[1], x[0]))
    review = sum(1 for p in pf.get("positions") or [] if (p.get("action") or {}).get("action") == "Rivedi la tesi")
    missing = diary.missing(server.last_closed_session())
    return today, macro, earn, review, missing


def show(text):
    """The window: 'Chiudi' or 'Apri la pagina Oggi' (closes by itself after 30 minutes). Text passed as argv."""
    script = ('on run argv\n'
              f'set r to display dialog (item 1 of argv) with title "Nasdaq-100 Monitor" buttons {{"Chiudi", "Apri la pagina Oggi"}} '
              f'default button "Apri la pagina Oggi" giving up after {WINDOW_SECONDS}\n'
              'if gave up of r then return ""\n'
              'return button returned of r\n'
              'end run')
    out = subprocess.run(["osascript", "-e", script, text], capture_output=True, text=True).stdout.strip()
    if out != "Apri la pagina Oggi":
        return
    up = subprocess.run(["curl", "-s", "-o", "/dev/null", "--max-time", "1", URL]).returncode == 0
    if up:
        subprocess.run(["open", URL])
    else:                                                # dashboard closed: the app starts it and opens Oggi
        subprocess.run(["open", "-a", APP, "--args", "overview"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    text = summary_text(*collect())
    print(text or "Niente di rilevante oggi: nessuna finestra.")
    if text and "--print" not in sys.argv:
        show(text)
