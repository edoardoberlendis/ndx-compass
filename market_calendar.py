"""US stock market (NYSE / Nasdaq) holidays and 1:00 p.m. early closes, New York time.

Source: NYSE "Holidays & Trading Hours", https://www.nyse.com/markets/hours-calendars (checked 2026-09-29).
Nasdaq follows the same calendar. Update the two tables below when NYSE publishes a new year:
the dashboard warns from WARN_DAYS before the last covered date (see coverage_warning()).
No external library on purpose: two small tables are easier to check than a dependency.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

HOLIDAYS = {
    # 2026
    date(2026, 1, 1): "Capodanno",
    date(2026, 1, 19): "Martin Luther King Jr. Day",
    date(2026, 2, 16): "Presidents' Day",
    date(2026, 4, 3): "Venerdì Santo",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3): "Festa dell'Indipendenza (osservata)",
    date(2026, 9, 7): "Labor Day",
    date(2026, 11, 26): "Thanksgiving",
    date(2026, 12, 25): "Natale",
    # 2027
    date(2027, 1, 1): "Capodanno",
    date(2027, 1, 18): "Martin Luther King Jr. Day",
    date(2027, 2, 15): "Presidents' Day",
    date(2027, 3, 26): "Venerdì Santo",
    date(2027, 5, 31): "Memorial Day",
    date(2027, 6, 18): "Juneteenth (osservato)",
    date(2027, 7, 5): "Festa dell'Indipendenza (osservata)",
    date(2027, 9, 6): "Labor Day",
    date(2027, 11, 25): "Thanksgiving",
    date(2027, 12, 24): "Natale (osservato)",
    # 2028 (1 January falls on a Saturday and is not observed)
    date(2028, 1, 17): "Martin Luther King Jr. Day",
    date(2028, 2, 21): "Presidents' Day",
    date(2028, 4, 14): "Venerdì Santo",
    date(2028, 5, 29): "Memorial Day",
    date(2028, 6, 19): "Juneteenth",
    date(2028, 7, 4): "Festa dell'Indipendenza",
    date(2028, 9, 4): "Labor Day",
    date(2028, 11, 23): "Thanksgiving",
    date(2028, 12, 25): "Natale",
}

# regular session ends at 13:00 New York time (extended hours at 17:00)
EARLY_CLOSES = {
    date(2026, 11, 27): "giorno dopo Thanksgiving",
    date(2026, 12, 24): "vigilia di Natale",
    date(2027, 11, 26): "giorno dopo Thanksgiving",
    date(2028, 7, 3): "vigilia della Festa dell'Indipendenza",
    date(2028, 11, 24): "giorno dopo Thanksgiving",
}

COVERED_UNTIL = date(2028, 12, 31)   # last day the tables above are complete for
WARN_DAYS = 90


def _d(day) -> date:
    return day.date() if isinstance(day, datetime) else day


def holiday(day) -> str | None:
    """Name of the market holiday on this (New York) date, or None."""
    return HOLIDAYS.get(_d(day))


def early_close(day) -> str | None:
    """Reason for a 13:00 close on this date, or None."""
    return EARLY_CLOSES.get(_d(day))


def is_trading_day(day) -> bool:
    d = _d(day)
    return d.weekday() < 5 and d not in HOLIDAYS


def next_trading_day(day) -> date:
    """First trading day strictly after this date."""
    d = _d(day) + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def close_minute(day) -> int:
    """Regular-session close as minutes after midnight, New York time."""
    return 13 * 60 if early_close(day) else 16 * 60


def coverage_warning(today=None) -> str | None:
    """Italian warning when the holiday list is about to run out (or already has)."""
    d = _d(today or date.today())
    if d > COVERED_UNTIL:
        return (f"L'elenco delle festività della borsa USA finisce il {COVERED_UNTIL:%d/%m/%Y}: "
                "aggiorna market_calendar.py, altrimenti i giorni festivi risultano aperti.")
    if (COVERED_UNTIL - d).days <= WARN_DAYS:
        return (f"L'elenco delle festività della borsa USA finisce il {COVERED_UNTIL:%d/%m/%Y}: "
                "aggiungi l'anno successivo in market_calendar.py (date su nyse.com).")
    return None
