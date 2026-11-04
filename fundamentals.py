"""Bilanci delle società del Nasdaq-100 per il motore di analisi fondamentale (phase 5A).

Same source and library as the rest of the dashboard (Yahoo Finance through yfinance): annual and quarterly income
statement, cash flow and balance sheet, plus the earnings calendar (dates on which results were announced). Cached in
cache/fundamentals.json and downloaded again for a stock only when needed (REFRESH rules below), always in the
background or from the terminal, never when a page is opened.

What a figure carries (nothing is invented or filled in):
  - the currency of the accounts (financialCurrency), which can differ from the price currency (ADR: PDD in CNY,
    ASML in EUR, prices in USD);
  - the period end (fiscal date) and the kind of period (FY = annual report, Q = quarter);
  - the date it was downloaded (fetchedAt) and the first download in which the period appeared (firstSeen): the figure
    was certainly public by then, maybe earlier. "initial" marks the periods already present at the very first
    download, whose real availability date is unknown;
  - the announcement date of the results, when the earnings calendar has one within ANNOUNCE_MAX_DAYS after the period
    end. It is the date of the results release, not of the SEC filing. Without it: "non verificabile".
A missing row stays missing (None), never zero.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache", "fundamentals.json")
ET = ZoneInfo("America/New_York")
log = logging.getLogger("ndx")

SCHEMA = 1                  # fields of a cached stock: a different number means "download again"
FIELDS = 3                  # phase 5B (2): rows added for the valuation (shares, D&A, working capital, minorities, preferred);
                            # phase 5C (3): lease obligations and long-term investments (bridge EV -> equity).
                            # Kept apart from SCHEMA so that a server still running the phase 5A code does not download
                            # everything again; an entry with an older "fields" is downloaded again by the new code only
THREADS = 4                 # parallel stocks (each one makes ~8 small Yahoo requests)
REFRESH_DAYS = 7            # a stock is downloaded again at most every 7 days...
AFTER_EARNINGS_DAYS = 2     # ...or 2 days after results are announced (Yahoo needs time to load the statements)...
LAG_RETRY_DAYS = 14         # ...and once a day for 14 days while announced results are still missing from the statements
ANNOUNCE_MAX_DAYS = 100     # an announcement more than 100 days after the period end does not belong to that period
RETRY_MIN = 30              # after a failed download, wait 30 minutes
SOURCE = "Yahoo Finance (yfinance): bilanci annuali e trimestrali"

ROWS = {
    "income": {"revenue": ("Total Revenue", "Operating Revenue"), "grossProfit": ("Gross Profit",),
               "operatingIncome": ("Operating Income",), "ebit": ("EBIT",), "ebitda": ("EBITDA", "Normalized EBITDA"),
               "netIncome": ("Net Income Common Stockholders", "Net Income"), "dilutedEps": ("Diluted EPS",),
               "pretaxIncome": ("Pretax Income",), "taxProvision": ("Tax Provision",),
               "interestExpense": ("Interest Expense", "Interest Expense Non Operating"),
               "dilutedShares": ("Diluted Average Shares",)},
    "cash": {"ocf": ("Operating Cash Flow",), "capex": ("Capital Expenditure",), "fcf": ("Free Cash Flow",),
             "sbc": ("Stock Based Compensation",),
             "da": ("Depreciation And Amortization", "Depreciation Amortization Depletion"),
             "wcChange": ("Change In Working Capital",)},
    "balance": {"totalDebt": ("Total Debt",),
                "cash": ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"),
                "equity": ("Stockholders Equity",), "totalAssets": ("Total Assets",),
                "investedCapital": ("Invested Capital",),
                "minority": ("Minority Interest",), "preferred": ("Preferred Stock Equity", "Preferred Stock"),
                "leases": ("Capital Lease Obligations",), "ltInvest": ("Investments And Advances",)},
}
STATEMENTS = {"FY": {"income": "income_stmt", "cash": "cash_flow", "balance": "balance_sheet"},
              "Q": {"income": "quarterly_income_stmt", "cash": "quarterly_cash_flow", "balance": "quarterly_balance_sheet"}}
INFO_KEYS = ("currency", "financialCurrency", "sector", "industry", "quoteType", "country")


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def now_et():
    return datetime.now(ET)


# ---------------------------------------------------------------- one stock (pure helpers, tested with fake frames)

def periods_from(frames, kind):
    """frames: {"income": DataFrame, "cash": ..., "balance": ...} as yfinance gives them (rows = items, columns = period
    ends). Returns [{"end", "kind", <field>: value or None}] newest first, one entry per period end."""
    out = {}
    for part, rows in ROWS.items():
        df = frames.get(part)
        if df is None or getattr(df, "empty", True):
            continue
        for col in df.columns:
            end = str(col.date()) if hasattr(col, "date") else str(col)[:10]
            p = out.setdefault(end, {"end": end, "kind": kind})
            for field, names in rows.items():
                if p.get(field) is not None:
                    continue
                val = next((_num(df.loc[n, col]) for n in names if n in df.index and _num(df.loc[n, col]) is not None), None)
                p[field] = val
    for p in out.values():
        for rows in ROWS.values():
            for field in rows:
                p.setdefault(field, None)
        if p["fcf"] is None and p["ocf"] is not None and p["capex"] is not None:
            p["fcf"] = p["ocf"] + p["capex"]           # capex is negative in Yahoo's cash flow
            p["fcfComputed"] = True
    # a period with no figure at all (an empty column Yahoo sometimes adds) is dropped
    keep = [p for p in out.values() if any(p.get(f) is not None for rows in ROWS.values() for f in rows)]
    return sorted(keep, key=lambda p: p["end"], reverse=True)


def earnings_list(df, now=None):
    """Earnings calendar (yfinance get_earnings_dates) -> [{"date": ISO ET, "past": bool}] newest first."""
    now = now or now_et()
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for ts in df.index:
        t = ts.tz_convert(ET) if getattr(ts, "tzinfo", None) else ts.tz_localize(ET)
        out.append({"date": t.isoformat(), "past": t <= now})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def announced(end, earnings):
    """First announcement of results after the period end (within ANNOUNCE_MAX_DAYS), or None."""
    e = datetime.fromisoformat(end).replace(tzinfo=ET)
    dates = sorted(datetime.fromisoformat(x["date"]) for x in earnings or [])
    for d in dates:
        if e < d <= e + timedelta(days=ANNOUNCE_MAX_DAYS):
            return d.date().isoformat()
    return None


def fetch_one(ticker):
    import yfinance as yf
    t = yf.Ticker(ticker)

    def get(name, call=False):
        for attempt in range(2):
            try:
                x = getattr(t, name)
                return x(limit=16) if call else x
            except Exception:
                time.sleep(1 + attempt)
        return None
    info = get("info") or {}
    out = {"schema": SCHEMA, "fields": FIELDS, "fetchedAt": now_et().isoformat(timespec="seconds"), "source": SOURCE,
           "info": {k: info.get(k) for k in INFO_KEYS}}
    for kind, names in STATEMENTS.items():
        out[kind] = periods_from({part: get(attr) for part, attr in names.items()}, kind)
    out["earnings"] = earnings_list(get("get_earnings_dates", call=True))
    return ticker, out


# ---------------------------------------------------------------- cache and refresh rules

def read(path=None):
    try:
        with open(path or CACHE) as f:
            c = json.load(f)
        return c if isinstance(c, dict) and "data" in c else {"data": {}, "fx": {}, "firstSeen": {}}
    except (OSError, ValueError):
        return {"data": {}, "fx": {}, "firstSeen": {}}


def latest_announcement(entry, now):
    past = [datetime.fromisoformat(x["date"]) for x in entry.get("earnings") or [] if datetime.fromisoformat(x["date"]) <= now]
    return max(past) if past else None


def lagging(entry, now):
    """True when results were announced after the newest quarter in the statements had been announced: the source has
    not loaded the latest quarter yet (e.g. results out on 30 October, statements still at June)."""
    qs = entry.get("Q") or []
    last = latest_announcement(entry, now)
    if not qs or last is None:
        return False
    pub = announced(qs[0]["end"], entry.get("earnings"))
    return pub is not None and last.date().isoformat() > pub


def needs_refresh(entry, now=None):
    now = now or now_et()
    if not entry or entry.get("schema") != SCHEMA or entry.get("fields", 1) < FIELDS:
        return True
    fetched = datetime.fromisoformat(entry["fetchedAt"])
    if now - fetched >= timedelta(days=REFRESH_DAYS):
        return True
    last = latest_announcement(entry, now)
    if last is not None:
        ready = last + timedelta(days=AFTER_EARNINGS_DAYS)
        if fetched < ready <= now:
            return True
        if lagging(entry, now) and now - fetched >= timedelta(days=1) and now - last <= timedelta(days=LAG_RETRY_DAYS):
            return True
    return False


def first_seen(old, data, today):
    """{ticker: {"FY|end": {"date", "initial"}}}: when each period appeared for the first time in a download."""
    out = {t: dict(v) for t, v in (old or {}).items()}
    for t, e in data.items():
        have = out.setdefault(t, {})
        initial = not have
        for kind in ("FY", "Q"):
            for p in e.get(kind) or []:
                have.setdefault(f"{kind}|{p['end']}", {"date": today, "initial": initial})
    return out


def fx_rates(currencies):
    """{currency: {"rate": USD per unit, "date"}} from the daily FX closes (one small download)."""
    from server import download
    cur = sorted({c for c in currencies if c and c.upper() != "USD"})
    if not cur:
        return {}
    syms = {c: f"{c.upper()}USD=X" for c in cur}
    px = download(list(syms.values()), period="5d", interval="1d")
    out = {}
    for c, s in syms.items():
        close = px.get(s, None)
        close = close.get("Close").dropna() if close is not None and "Close" in close else None
        if close is not None and len(close):
            rate = float(close.iloc[-1]) * (0.01 if c[-1].islower() else 1)     # GBp / ZAc: hundredths
            out[c] = {"rate": rate, "date": str(close.index[-1].date()), "symbol": s}
    return out


RF_SYMBOL = "^TNX"           # yield of the 10-year US Treasury (CBOE index, in percent): the risk-free rate of the valuation


def risk_free():
    """{"rate": decimal, "date", "symbol", "source"} from the last daily close of ^TNX (one small download), or {}."""
    from server import download
    px = download([RF_SYMBOL], period="10d", interval="1d")
    close = px.get(RF_SYMBOL)
    close = close.get("Close").dropna() if close is not None and "Close" in close else None
    if close is None or not len(close):
        return {}
    rate = float(close.iloc[-1]) / 100
    if not 0.0 < rate < 0.15:                 # an implausible yield is not used
        return {}
    return {"rate": rate, "date": str(close.index[-1].date()), "symbol": RF_SYMBOL,
            "source": "Yahoo Finance: rendimento del Treasury USA a 10 anni (^TNX), chiusura giornaliera"}


def rates_stale(c, now):
    r = (c.get("rates") or {}).get("rf")
    return not r or (now.date() - datetime.fromisoformat(r["date"]).date()).days > 7


def refresh(tickers, force=False, now=None, path=None):
    """Downloads the stocks that need it (all with force) and writes the cache. Returns a short summary."""
    now = now or now_et()
    c = read(path)
    todo = [t for t in tickers if force or needs_refresh(c["data"].get(t), now)]
    if not todo and not rates_stale(c, now):
        return {"downloaded": 0, "total": len(tickers)}
    t0 = time.time()
    new = {}
    if todo:
        with ThreadPoolExecutor(THREADS) as ex:
            new = dict(ex.map(fetch_one, todo))
    new = {t: e for t, e in new.items() if e.get("FY") or e.get("Q")}       # an empty answer keeps the old copy
    data = {**c["data"], **new}
    fx = c.get("fx") or {}
    try:
        fx = {**fx, **fx_rates((e.get("info") or {}).get("financialCurrency") for e in data.values())}
    except Exception:
        log.exception("fundamentals: FX rates not updated")
    rates = dict(c.get("rates") or {})
    try:
        rf = risk_free()
        if rf:
            rates["rf"] = rf
    except Exception:
        log.exception("fundamentals: risk-free rate not updated")
    out = {"schema": SCHEMA, "savedAt": now.isoformat(timespec="seconds"), "data": data, "fx": fx, "rates": rates,
           "firstSeen": first_seen(c.get("firstSeen"), new, now.date().isoformat())}
    path = path or CACHE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(out, f, default=str)
    os.replace(path + ".tmp", path)
    log.info("fundamentals: %d of %d stocks downloaded in %.1fs", len(new), len(tickers), time.time() - t0)
    return {"downloaded": len(new), "requested": len(todo), "total": len(tickers), "seconds": round(time.time() - t0, 1)}


_state = {"running": False, "failedAt": 0.0}
_lock = threading.Lock()


def refresh_async(tickers, on_done=None):
    """Starts refresh() in a background thread if some stock needs it (never blocks the caller)."""
    c = read()
    now = now_et()
    if not any(needs_refresh(c["data"].get(t), now) for t in tickers) and not rates_stale(c, now):
        return False
    with _lock:
        if _state["running"] or time.time() - _state["failedAt"] < RETRY_MIN * 60:
            return False
        _state["running"] = True

    def job():
        try:
            refresh(tickers)
            if on_done:
                on_done()
        except Exception:
            log.exception("fundamentals refresh failed")
            _state["failedAt"] = time.time()
        finally:
            _state["running"] = False
    threading.Thread(target=job, daemon=True).start()
    return True


def status():
    return {"running": _state["running"]}
