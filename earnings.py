"""Details of the upcoming earnings reports (plan phase 21, Mercato → Oggi): the last report (expected EPS, reported
EPS, surprise) and how much the stock usually moved on the reaction day of its last 8 reports.

The expected EPS and revenue of the quarter come from the analyst data already downloaded every day (analysts.py,
"0q"). The earnings dates come from Yahoo (one request per company, only for the companies of the list, once a day,
cached in cache/earnings.json: public data). The reaction move is computed from the daily closes: the same session if
the report came out before the open, the next one if it came out after the close. Missing data is simply not shown.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

import pandas as pd
import yfinance as yf

log = logging.getLogger("ndx")
CACHE = "earnings.json"
LAST_REPORTS = 8

_lock = threading.Lock()
_state = {"running": False}


def _dates(ticker):
    """[{"ts", "eps", "reported", "surprise"}] of the last reports, newest first (empty if Yahoo has nothing)."""
    for attempt in range(2):
        try:
            df = yf.Ticker(ticker).get_earnings_dates(limit=LAST_REPORTS + 6)
            break
        except Exception:
            time.sleep(1 + attempt)
    else:
        return []
    if df is None or df.empty:
        return []
    out = []
    for ts, r in df.iterrows():
        rep = r.get("Reported EPS")
        if rep is None or pd.isna(rep):
            continue                                        # a future date: not reported yet
        num = lambda v: None if v is None or pd.isna(v) else float(v)
        out.append({"ts": pd.Timestamp(ts).tz_convert("America/New_York").isoformat(), "eps": num(r.get("EPS Estimate")),
                    "reported": num(rep), "surprise": num(r.get("Surprise(%)"))})
    return out[:LAST_REPORTS]


def reaction_moves(reports, closes):
    """% change on the reaction day of each report: before the open -> that session, after the close -> the next one."""
    if closes is None or closes.empty:
        return []
    c = closes.dropna()
    idx = pd.to_datetime(c.index).tz_localize(None).normalize() if getattr(c.index, "tz", None) is not None else pd.to_datetime(c.index).normalize()
    c = pd.Series(c.to_numpy(), index=idx)
    out = []
    for r in reports:
        ts = pd.Timestamp(r["ts"])
        day = pd.Timestamp(ts.date())
        after_close = ts.hour >= 12                       # Yahoo dates: ~16:00 = after the close, ~07:00-09:00 = before the open
        pos = c.index.searchsorted(day + (timedelta(days=1) if after_close else timedelta(0)))
        if pos <= 0 or pos >= len(c):
            continue
        out.append({"date": str(c.index[pos].date()), "move": float(c.iloc[pos] / c.iloc[pos - 1] - 1) * 100})
    return out


def details(tickers, daily, analysts):
    """{ticker: {...}} for the companies of the earnings list, from the cache of today or computed now."""
    from server import read_daily_cache, write_daily_cache   # local import: server imports this module's users
    cached = read_daily_cache(CACHE) or {}
    todo = [t for t in tickers if t not in cached]
    for t in todo:
        cached[t] = {"reports": _dates(t)}
    if todo:
        write_daily_cache(CACHE, cached)
    out = {}
    for t in tickers:
        reps = (cached.get(t) or {}).get("reports") or []
        closes = daily[t]["Close"] if t in daily and "Close" in daily[t] else None
        moves = reaction_moves(reps, closes)
        q = ((analysts.get(t) or {}).get("eps") or {}).get("0q") or {}
        rv = ((analysts.get(t) or {}).get("rev") or {}).get("0q") or {}
        out[t] = {
            "epsExpected": q.get("avg"), "epsAnalysts": q.get("numberOfAnalysts"),
            "revExpected": rv.get("avg"), "revAnalysts": rv.get("numberOfAnalysts"),
            "last": reps[0] if reps else None,
            "moves": moves, "usualMove": sum(abs(m["move"]) for m in moves) / len(moves) if len(moves) >= 4 else None,
        }
    return out


def details_async(tickers, daily, analysts, done):
    """Compute in the background (one Yahoo request per company): done(result) when ready."""
    with _lock:
        if _state["running"]:
            return
        _state["running"] = True

    def job():
        try:
            done(details(tickers, daily, analysts))
        except Exception:
            log.exception("earnings details failed")
        finally:
            with _lock:
                _state["running"] = False
    threading.Thread(target=job, daemon=True).start()
