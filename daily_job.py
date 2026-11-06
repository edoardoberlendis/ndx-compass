"""Evening job (plan phase 21): report, signal diary and portfolio picture of the day, with the dashboard closed.

    .venv/bin/python daily_job.py                # full job: what launchd runs Mon-Fri at 22:45 (./schedule.sh install)
    .venv/bin/python daily_job.py --market-only  # phase 8B: public market data only (./schedule.sh install-market)

It uses the same code as the dashboard (server.run_daily_job) and writes only what is missing: if the dashboard is
also open, the first one to save a day wins and the other skips it. Weekends and US market holidays: nothing to do.
If the Mac is asleep at the scheduled time, macOS runs the job when it wakes up; if it is switched off, the run is
skipped. A session can still be recorded only until 04:00 New York time of the next session (Phase 7C): after that it
is lost for good (a late record would not be honest) and the dashboard says so.

--market-only: prices, public analyses, the five prospective diaries, the alerts and the public evening report. The
protection of the portfolio (app_env.enable_market_only) is turned on BEFORE any other import: from then on every open,
listing or change of a file in portafoglio/ is blocked before it happens. No portfolio, no picture, no flussi.json, no
signal/ETF/positions diary, no personal data in the log.
"""
import logging
import sys
from datetime import datetime

MARKET_ONLY = "--market-only" in sys.argv[1:]
if MARKET_ONLY:
    import app_env
    app_env.enable_market_only()                      # first: covers the side effects of every import below

import market_calendar
import server


def nothing_to_do(now):
    """True on a day without a NYSE session when the last closed session is already done (no download needed)."""
    if market_calendar.is_trading_day(now.date()):
        return False
    last = server.last_closed_session(now)
    if MARKET_ONLY:
        import investment_decision_engine as de
        import opportunity_diary as od
        import opportunity_scanner as sc
        return bool(last) and od.exists(last, sc.MODEL_VERSION) and _decision_done(last, de.VERSION)
    return last in __import__("diary").days()


def _decision_done(session, version):
    try:
        import decision_diary
        return decision_diary.exists(session, version)
    except Exception:
        return False


if __name__ == "__main__":
    unknown = [a for a in sys.argv[1:] if a != "--market-only"]
    if unknown:
        print(f"opzione sconosciuta: {' '.join(unknown)} (ammessa solo --market-only)")
        sys.exit(2)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    now = datetime.now(server.ET)
    if nothing_to_do(now):
        print(f"{now:%Y-%m-%d %H:%M} ET: no session today and the last one is already saved: nothing to do")
        sys.exit(0)
    server.run_daily_job(market_only=MARKET_ONLY)
