"""US macro events for the "Oggi" tab: Fed meetings (FOMC), CPI, PCE and the jobs report (Employment Situation).

Dates (New York time) are written below from the official calendars, checked on 2026-09-29:
  - FOMC:  https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm   (decision at 14:00, press conference 14:30)
  - CPI:   https://www.bls.gov/schedule/news_release/cpi.htm                  (08:30)
  - Jobs:  https://www.bls.gov/schedule/news_release/empsit.htm               (08:30)
  - PCE:   https://www.bea.gov/news/schedule  ("Personal Income and Outlays", 08:30)
None of them had published 2027 yet. Once a day the Fed page and BEA's calendar (.ics) are read again and any new
date is added automatically; if that check fails (page changed or unreachable) the dashboard shows a warning.
The BLS site blocks programs, so CPI and jobs dates must be added here by hand when BLS publishes the new year.

Values: BLS public API v1 (no key, max 25 requests a day: one request a day is used, a few more on release days).
PCE values would need a free BEA key (not used; if added one day it must live in a file excluded from Git).
There is no free, reliable source for the analysts' expected values (consensus), so no "surprise" is computed.
"""
from __future__ import annotations

import json
import logging
import os
import re
import html
import threading
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("ndx")
ET = ZoneInfo("America/New_York")
ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "cache")
AUTO_CACHE = os.path.join(CACHE_DIR, "macro_auto.json")     # dates found by the daily check (public data)
BLS_CACHE = os.path.join(CACHE_DIR, "macro_bls.json")       # BLS values (public data)
WARN_DAYS = 60
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"}
FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FED_RATE_URL = "https://www.federalreserve.gov/monetarypolicy/openmarket.htm"
BEA_ICS_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"

# (date, New York time, reference period, Fed projections) - "sep": the Fed also publishes its economic projections
FOMC = [("2026-01-28", "14:00", None, False), ("2026-03-18", "14:00", None, True), ("2026-04-29", "14:00", None, False),
        ("2026-06-17", "14:00", None, True), ("2026-07-29", "14:00", None, False), ("2026-09-16", "14:00", None, True),
        ("2026-10-28", "14:00", None, False), ("2026-12-09", "14:00", None, True)]
CPI = [("2026-01-13", "08:30", "2025-12"), ("2026-02-13", "08:30", "2026-01"), ("2026-03-11", "08:30", "2026-02"),
       ("2026-04-10", "08:30", "2026-03"), ("2026-05-12", "08:30", "2026-04"), ("2026-06-10", "08:30", "2026-05"),
       ("2026-07-14", "08:30", "2026-06"), ("2026-08-12", "08:30", "2026-07"), ("2026-09-11", "08:30", "2026-08"),
       ("2026-10-14", "08:30", "2026-09"), ("2026-11-10", "08:30", "2026-10"), ("2026-12-10", "08:30", "2026-11")]
JOBS = [("2026-01-09", "08:30", "2025-12"), ("2026-02-11", "08:30", "2026-01"), ("2026-03-06", "08:30", "2026-02"),
        ("2026-04-03", "08:30", "2026-03"), ("2026-05-08", "08:30", "2026-04"), ("2026-06-05", "08:30", "2026-05"),
        ("2026-07-02", "08:30", "2026-06"), ("2026-08-07", "08:30", "2026-07"), ("2026-09-04", "08:30", "2026-08"),
        ("2026-10-02", "08:30", "2026-09"), ("2026-11-06", "08:30", "2026-10"), ("2026-12-04", "08:30", "2026-11")]
PCE = [("2026-01-22", "10:00", "2025-11"), ("2026-02-20", "08:30", "2025-12"), ("2026-03-13", "08:30", "2026-01"),
       ("2026-04-09", "08:30", "2026-02"), ("2026-04-30", "08:30", "2026-03"), ("2026-05-28", "08:30", "2026-04"),
       ("2026-06-25", "08:30", "2026-05"), ("2026-07-30", "08:30", "2026-06"), ("2026-08-26", "08:30", "2026-07"),
       ("2026-09-30", "08:30", "2026-08"), ("2026-10-29", "08:30", "2026-09"), ("2026-11-25", "08:30", "2026-10"),
       ("2026-12-23", "08:30", "2026-11")]

# sectors (dashboard names) and themes (themes.json) most sensitive to each event
IMPACT = {
    "fomc": {"sectors": ["Tecnologia", "Consumi discrezionali", "Immobiliare", "Utility", "Finanza"],
             "themes": ["Chip e calcolo AI", "Software e dati AI", "Cloud e hyperscaler AI", "Legati alle cripto",
                        "Biotech e medtech", "Energia e utility per l'AI"]},
    "cpi": {"sectors": ["Tecnologia", "Consumi discrezionali", "Immobiliare"],
            "themes": ["Chip e calcolo AI", "Software e dati AI", "Cloud e hyperscaler AI", "Internet e consumi", "Legati alle cripto"]},
    "pce": {"sectors": ["Tecnologia", "Consumi discrezionali", "Immobiliare"],
            "themes": ["Chip e calcolo AI", "Software e dati AI", "Cloud e hyperscaler AI", "Internet e consumi", "Legati alle cripto"]},
    "jobs": {"sectors": ["Consumi discrezionali", "Industria", "Finanza", "Materiali di base", "Tecnologia"],
             "themes": ["Internet e consumi", "Auto elettriche e guida autonoma", "Chip e calcolo AI"]},
}
KINDS = {"fomc": FOMC, "cpi": CPI, "pce": PCE, "jobs": JOBS}
MANUAL = {"cpi", "jobs"}          # no automatic check possible (BLS blocks programs)

_lock = threading.Lock()
_auto = {"fomc": [], "pce": [], "rate": None, "checked": None, "errors": {}}
_bls = {"data": None, "at": 0}


# ---------------------------------------------------------------- automatic date check (Fed page, BEA calendar)

MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}


def parse_fed(page):
    """[(date, "14:00", None, sep)] from the Fed's FOMC calendar page (decision = last day of each meeting)."""
    out = []
    for m in re.finditer(r">(\d{4}) FOMC Meetings<", page):
        year = int(m.group(1))
        end = page.find("FOMC Meetings<", m.end())
        blk = page[m.end(): end if end > 0 else len(page)]
        months = re.findall(r'fomc-meeting__month[^>]*><strong>([^<]+)</strong>', blk)
        days = [html.unescape(d).strip() for d in re.findall(r'fomc-meeting__date[^>]*>([^<]+)<', blk)]
        for mo, dd in zip(months, days):
            last_month = mo.split("/")[-1].strip()
            nums = re.findall(r"\d+", dd)
            if last_month not in MONTHS or not nums or "notation" in dd.lower() or "unscheduled" in dd.lower():
                continue
            out.append((date(year, MONTHS[last_month], int(nums[-1])).isoformat(), "14:00", None, "*" in dd))
    return out


def parse_bea(ics):
    """[(date, NY time, reference month)] of "Personal Income and Outlays" in BEA's calendar."""
    out = []
    for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ics, re.S):
        s, d = re.search(r"SUMMARY:(.*)", ev), re.search(r"DTSTART[^:]*:(\d{8}T\d{4,6})(Z?)", ev)
        if not (s and d and "Personal Income and Outlays" in s.group(1)):
            continue
        t = datetime.strptime(d.group(1)[:13], "%Y%m%dT%H%M")
        t = (t.replace(tzinfo=timezone.utc) if d.group(2) else t.replace(tzinfo=ET)).astimezone(ET)
        ref = re.findall(r"(January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})",
                         s.group(1).replace("\\,", ","))
        month, year = ref[-1] if ref else (None, None)
        out.append((t.date().isoformat(), t.strftime("%H:%M"), f"{year}-{MONTHS[month]:02d}" if month else None))
    return out


def parse_rate(page):
    """Current Fed funds target range ("3.75-4.00") from the Fed's open market page (first row of the latest year)."""
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 4 and re.fullmatch(r"\d+(\.\d+)?-\d+(\.\d+)?", cells[3]):
            return cells[3]
    return None


def check_official():
    """Read the Fed page and BEA's calendar again (once a day). Errors are kept and shown on the page."""
    this_year = datetime.now(ET).year
    errors, fomc, pce, rate = {}, [], [], None
    try:
        r = requests.get(FED_URL, headers=BROWSER_UA, timeout=20)
        r.raise_for_status()
        fomc = parse_fed(r.text)
        if sum(1 for d, *_ in fomc if d.startswith(str(this_year))) < 6:
            errors["fomc"] = "la pagina del calendario Fed sembra cambiata (trovate meno di 6 riunioni quest'anno)"
            fomc = []
    except Exception as e:
        errors["fomc"] = f"pagina del calendario Fed non raggiungibile ({type(e).__name__})"
    try:
        r = requests.get(BEA_ICS_URL, headers=BROWSER_UA, timeout=20)
        r.raise_for_status()
        pce = parse_bea(r.text)
        if not any(d.startswith(str(this_year)) for d, *_ in pce):
            errors["pce"] = "il calendario BEA sembra cambiato (nessuna data del PCE quest'anno)"
            pce = []
    except Exception as e:
        errors["pce"] = f"calendario BEA non raggiungibile ({type(e).__name__})"
    try:
        r = requests.get(FED_RATE_URL, headers=BROWSER_UA, timeout=20)
        r.raise_for_status()
        rate = parse_rate(r.text)
    except Exception:
        rate = None
    with _lock:
        _auto.update(fomc=fomc or _auto["fomc"], pce=pce or _auto["pce"], rate=rate or _auto["rate"],
                     checked=datetime.now(ET).date().isoformat(), errors=errors)
        snap = dict(_auto)
    try:
        with open(AUTO_CACHE, "w") as f:
            json.dump(snap, f)
    except Exception:
        pass
    for k, v in errors.items():
        log.warning("macro calendar: %s", v)


def refresh():
    """Called by the server's worker: the official check once a day, BLS values when needed."""
    if not _auto["checked"]:
        try:
            with open(AUTO_CACHE) as f:
                _auto.update(json.load(f))
        except Exception:
            pass
    if _auto["checked"] != datetime.now(ET).date().isoformat():
        check_official()
    refresh_bls()


# ---------------------------------------------------------------- events

def all_events():
    """Written dates + dates found by the daily check, without duplicates."""
    out = {}
    for kind, rows in KINDS.items():
        for row in rows + [tuple(x) for x in _auto.get(kind, [])]:
            d, t, ref = row[0], row[1], row[2]
            out.setdefault((kind, d), {"kind": kind, "date": d, "time": t, "ref": ref,
                                       "sep": bool(row[3]) if len(row) > 3 else False})
    return sorted(out.values(), key=lambda e: (e["date"], e["time"]))


def _ts(d, t):
    y, m, dd = map(int, d.split("-"))
    hh, mm = map(int, t.split(":"))
    return datetime(y, m, dd, hh, mm, tzinfo=ET).timestamp()


def coverage_warnings(today=None):
    """Warn when a kind's known dates end within WARN_DAYS (or already ended)."""
    today = today or datetime.now(ET).date()
    ev, out = all_events(), []
    names = {"fomc": "riunioni Fed", "cpi": "CPI", "pce": "PCE", "jobs": "occupazione"}
    for kind in KINDS:
        last = max((e["date"] for e in ev if e["kind"] == kind), default=None)
        if last and (date.fromisoformat(last) - today).days <= WARN_DAYS:
            how = ("aggiungi le nuove date in macro_calendar.py (fonte: bls.gov/schedule)" if kind in MANUAL
                   else "il controllo automatico non ha ancora trovato date nuove")
            out.append(f"Date {names[kind]} note fino al {date.fromisoformat(last):%d/%m/%Y}: {how}.")
    return out


# ---------------------------------------------------------------- BLS values (CPI and jobs)

SERIES = {"cpi": "CUSR0000SA0", "cpiNsa": "CUUR0000SA0", "core": "CUSR0000SA0L1E", "coreNsa": "CUUR0000SA0L1E",
          "payrolls": "CES0000000001", "unemp": "LNS14000000", "wages": "CES0500000003"}


def refresh_bls():
    """Once a day; on CPI / jobs release days again every 2 hours after 08:30 New York, to get the new value."""
    now = datetime.now(ET)
    today = now.date().isoformat()
    release_today = any(e["date"] == today and e["kind"] in ("cpi", "jobs") for e in all_events())
    if _bls["data"] is None:
        try:
            with open(BLS_CACHE) as f:
                c = json.load(f)
            _bls.update(data=c["data"], at=c["at"])
        except Exception:
            pass
    age = time.time() - _bls["at"]
    fresh_day = datetime.fromtimestamp(_bls["at"], ET).date().isoformat() == today if _bls["at"] else False
    if fresh_day and not (release_today and now.hour * 60 + now.minute >= 8 * 60 + 35 and age > 2 * 3600):
        return
    try:
        r = requests.post(BLS_API, json={"seriesid": list(SERIES.values())}, timeout=30)
        d = r.json()
        if d.get("status") != "REQUEST_SUCCEEDED":
            raise ValueError(d.get("message"))
        data = {}
        for s in d["Results"]["series"]:
            key = next(k for k, v in SERIES.items() if v == s["seriesID"])
            # months without data are "-" (e.g. October 2025, when the US government shutdown stopped the surveys)
            data[key] = {f"{x['year']}-{x['period'][1:]}": float(x["value"]) for x in s["data"] if x["period"].startswith("M")
                         and x["period"] != "M13" and re.fullmatch(r"-?\d+(\.\d+)?", x["value"].strip())}
        _bls.update(data=data, at=time.time())
        with open(BLS_CACHE, "w") as f:
            json.dump({"data": data, "at": _bls["at"]}, f)
    except Exception as e:
        log.warning("BLS values unavailable (%s)", e)


def _prev_month(p, n=1):
    y, m = map(int, p.split("-"))
    m -= n
    while m <= 0:
        m, y = m + 12, y - 1
    return f"{y}-{m:02d}"


def _pct(series, p, back=1):
    a, b = series.get(p), series.get(_prev_month(p, back))
    return round((a / b - 1) * 100, 1) if a and b else None


def bls_values(kind, ref):
    """{"period", "released", figures..., "prev": the month before}: the event's own month if already out, otherwise
    the latest (previous) one."""
    D = _bls["data"]
    if not D or kind not in ("cpi", "jobs"):
        return None
    key = "cpi" if kind == "cpi" else "payrolls"
    months = sorted(D.get(key, {}))
    if not months:
        return None
    released = bool(ref and ref in D[key])
    p = ref if released else months[-1]

    def figures(p):
        if kind == "cpi":
            return {"period": p, "mom": _pct(D["cpi"], p), "yoy": _pct(D["cpiNsa"], p, 12),
                    "coreMom": _pct(D["core"], p), "coreYoy": _pct(D["coreNsa"], p, 12)}
        pay, prev = D["payrolls"].get(p), D["payrolls"].get(_prev_month(p))
        return {"period": p, "payrolls": round(pay - prev) if pay and prev else None,
                "unemp": D["unemp"].get(p), "wagesMom": _pct(D["wages"], p)}
    return {**figures(p), "released": released, "prev": figures(_prev_month(p))}


# ---------------------------------------------------------------- for the page

def upcoming(days=7, relevance=None):
    """Events from today to today + days (New York dates), with values, impact and relevance for my stocks."""
    today = datetime.now(ET).date()
    last = today + timedelta(days=days)
    out = []
    for e in all_events():
        d = date.fromisoformat(e["date"])
        if today <= d <= last:
            x = dict(e, ts=_ts(e["date"], e["time"]), impact=IMPACT[e["kind"]], values=bls_values(e["kind"], e["ref"]))
            if relevance:
                x["relevance"] = relevance(IMPACT[e["kind"]])
            out.append(x)
    errs = _auto.get("errors") or {}
    warnings = [f"Controllo automatico delle date non riuscito: {v}. Uso le date scritte nel codice." for v in errs.values()]
    return {"events": out, "rate": _auto.get("rate"), "checked": _auto.get("checked"),
            "warnings": warnings + coverage_warnings(today)}
