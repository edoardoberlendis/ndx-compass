"""Evening job (plan phase 21): report, signal diary and portfolio picture of the day, with the dashboard closed.

    .venv/bin/python daily_job.py          # what launchd runs Mon-Fri at 22:45 local time (./schedule.sh install)

It uses the same code as the dashboard (server.run_daily_job) and writes only what is missing: if the dashboard is
also open, the first one to save a day wins and the other skips it. Weekends and US market holidays: nothing to do.
If the Mac is asleep at 22:45, macOS runs the job when it wakes up; if it is switched off, the day is skipped (the
diary of a missed day cannot be rebuilt honestly afterwards) and the dashboard shows it with the ⚠ next to the time.
"""
import logging
import sys
from datetime import datetime

import market_calendar
import server

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    now = datetime.now(server.ET)
    if not market_calendar.is_trading_day(now.date()) and server.last_closed_session(now) in __import__("diary").days():
        print(f"{now:%Y-%m-%d %H:%M} ET: no session today and the last one is already saved: nothing to do")
        sys.exit(0)
    server.run_daily_job()
