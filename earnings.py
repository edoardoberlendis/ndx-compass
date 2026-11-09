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


def reports(tickers):
    """{ticker: last reports} from today's cache, downloading the missing ones (one Yahoo request each)."""
    from server import read_daily_cache, write_daily_cache   # local import: server imports this module's users
    with _lock:
        cached = read_daily_cache(CACHE) or {}
    todo = [t for t in tickers if t not in cached]
    for t in todo:
        cached[t] = {"reports": _dates(t)}
    if todo:
        with _lock:
            fresh = read_daily_cache(CACHE) or {}
            fresh.update({t: cached[t] for t in todo})
            write_daily_cache(CACHE, fresh)
    return {t: (cached.get(t) or {}).get("reports") or [] for t in tickers}


def usual_move(reps, closes):
    """Mean absolute move on the reaction day of the last reports (None with fewer than 4)."""
    moves = reaction_moves(reps, closes)
    return sum(abs(m["move"]) for m in moves) / len(moves) if len(moves) >= 4 else None


def _et_date(ts):
    return pd.Timestamp(ts, unit="s", tz="UTC").tz_convert("America/New_York").date() if isinstance(ts, (int, float)) \
        else pd.Timestamp(ts).tz_convert("America/New_York").date()


def _period(fund, report_date):
    """Accounting quarter of a report from the statements: (end, revenue) when a quarter's results were announced on
    that day (fundamentals.announced), otherwise the likely quarter end from the statements' cadence, without revenue."""
    import fundamentals
    if not fund:
        return None, None, False
    for q in fund.get("Q") or []:
        a = fundamentals.announced(q["end"], fund.get("earnings"))
        if a and abs((pd.Timestamp(a).date() - report_date).days) <= 1:
            return q["end"], q.get("revenue"), True
    qs = sorted(q["end"] for q in fund.get("Q") or [])
    if qs:
        nxt = pd.Timestamp(qs[-1]) + pd.DateOffset(months=3)
        while nxt.date() < report_date - timedelta(days=100):
            nxt += pd.DateOffset(months=3)
        if nxt.date() < report_date:
            return nxt.strftime("%Y-%m"), None, False                        # month only: an estimate
    return None, None, False


def details(tickers, daily, analysts, announce=None, infos=None, fund=None, fetched=None, analysts_date=None, now=None):
    """{ticker: {...}} for the companies of the earnings list (phase 8B.1: also the ones of the last 7 days).

    status: "pubblicata" when Yahoo already has the reported EPS of that announcement (same day ±1), "attesa dati" when
    the date has passed but the source has no results yet, otherwise "da pubblicare". For a published report the
    expected EPS is the estimate Yahoo recorded for THAT report, never the current quarter's ("0q" moves to the next
    quarter after the report); the expected revenue is used only if the analysts' data were downloaded before the day
    of the report. dateConfirmed: Yahoo's isEarningsDateEstimate (None when the source does not say)."""
    allrep = reports(tickers)
    now_ts = (now or time.time())
    announce, infos, fund = announce or {}, infos or {}, fund or {}
    out = {}
    for t in tickers:
        reps = allrep.get(t) or []
        closes = daily[t]["Close"] if t in daily and "Close" in daily[t] else None
        moves = reaction_moves(reps, closes)
        q = ((analysts.get(t) or {}).get("eps") or {}).get("0q") or {}
        rv = ((analysts.get(t) or {}).get("rev") or {}).get("0q") or {}
        ts = announce.get(t)
        day = _et_date(ts) if ts else None
        last = reps[0] if reps else None
        same = bool(last and day and abs((_et_date(last["ts"]) - day).days) <= 1)
        status = "pubblicata" if same else ("attesa dati" if ts and ts <= now_ts else "da pubblicare")
        est = (infos.get(t) or {}).get("isEarningsDateEstimate")
        period, rev_actual, exact = _period(fund.get(t), day) if day else (None, None, False)
        x = {
            "status": status, "announceTs": ts, "dateConfirmed": None if est is None else not est,
            "period": period, "periodExact": exact, "fetched": fetched, "analystsDate": analysts_date,
            "website": (infos.get(t) or {}).get("website"),
            "last": last, "moves": moves, "usualMove": sum(abs(m["move"]) for m in moves) / len(moves) if len(moves) >= 4 else None,
        }
        if status == "pubblicata":
            before = bool(analysts_date and day and analysts_date < day.isoformat())
            x.update(epsExpected=last.get("eps"), epsActual=last.get("reported"), epsSurprise=last.get("surprise"),
                     epsAnalysts=None, revExpected=rv.get("avg") if before else None,
                     revAnalysts=rv.get("numberOfAnalysts") if before else None,
                     revActual=rev_actual if exact else None,
                     prev=reps[1] if len(reps) > 1 else None)
        else:
            x.update(epsExpected=q.get("avg"), epsAnalysts=q.get("numberOfAnalysts"), epsActual=None, epsSurprise=None,
                     revExpected=rv.get("avg"), revAnalysts=rv.get("numberOfAnalysts"), revActual=None, prev=None)
        if isinstance(x.get("revActual"), (int, float)) and isinstance(x.get("revExpected"), (int, float)) and x["revExpected"]:
            x["revSurprise"] = (x["revActual"] / x["revExpected"] - 1) * 100
        else:
            x["revSurprise"] = None
        out[t] = x
    return out


def details_async(tickers, daily, analysts, done, **extra):
    """Compute in the background (one Yahoo request per company): done(result) when ready."""
    with _lock:
        if _state["running"]:
            return
        _state["running"] = True

    def job():
        try:
            done(details(tickers, daily, analysts, **extra))
        except Exception:
            log.exception("earnings details failed")
        finally:
            with _lock:
                _state["running"] = False
    threading.Thread(target=job, daemon=True).start()
