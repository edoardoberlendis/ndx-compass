"""Analyst expectations and valuation for the Nasdaq-100 dashboard.

Downloaded at most once per ET day and cached in cache/analysts.json (Yahoo rate limits):
rating changes, recommendation counts, EPS / revenue estimates and their revisions, and the last
~4 fiscal years of net income and revenue, used to rebuild the stock's own valuation history.

Valuation compares each stock two ways:
  - with its sector peers inside the Nasdaq-100 (forward P/E, P/S, EV/EBITDA). Comparing a utility
    with the tech-heavy index would make it look cheap, so sectors with fewer than MIN_PEERS usable
    values get no sector comparison and rely on the stock's history;
  - with its own history: trailing P/E and P/S today vs the median at the last fiscal year-ends.
Yahoo has no history of forward P/E, so the history uses realised earnings. Past market caps are
estimated as today's market cap scaled by the (split-adjusted) price change, which ignores changes
in the share count (buybacks / dilution: usually a few % a year).
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd
import yfinance as yf

from server import CACHE_DIR, ET, clean, download

log = logging.getLogger("ndx")
CACHE = os.path.join(CACHE_DIR, "analysts.json")
THREADS = 4                    # parallel tickers; each makes ~6 small Yahoo requests
MIN_PEERS = 3                  # below this the sector comparison is skipped (history only)
FEW_PEERS = 5                  # below this the note says the sector has few stocks
CHEAP, RICH = 0.85, 1.18       # combined valuation ratio thresholds
SECTOR_METRICS = [("fpe", "P/E atteso"), ("ps", "P/S"), ("evEbitda", "EV/EBITDA")]

ACTIONS_IT = {"up": "Upgrade", "down": "Downgrade", "init": "Avvio copertura", "main": "Conferma", "reit": "Conferma"}
PT_IT = {"Raises": "alza il target", "Lowers": "abbassa il target", "Announces": "fissa il target", "Sets": "fissa il target"}


# ---------------------------------------------------------------- download (once a day)

def _est(df):
    if df is None or getattr(df, "empty", True):
        return {}
    keys = ("avg", "low", "high", "growth", "numberOfAnalysts", "yearAgoEps", "yearAgoRevenue")
    return {p: {k: clean(df.loc[p].get(k)) for k in keys} for p in ("0q", "+1q", "0y", "+1y") if p in df.index}


def _rows(df, periods, keys):
    if df is None or getattr(df, "empty", True):
        return {}
    return {p: {k: clean(df.loc[p].get(k)) for k in keys} for p in periods if p in df.index}


def fetch_one(ticker):
    t = yf.Ticker(ticker)

    def get(name):
        for attempt in range(2):
            try:
                return getattr(t, name)
            except Exception:
                time.sleep(1 + attempt)
        return None

    out = {}
    ud = get("upgrades_downgrades")
    if ud is not None and not ud.empty:
        ud = ud.sort_index(ascending=False)
        ud = ud[ud.index >= pd.Timestamp.now() - pd.Timedelta(days=180)]
        out["actions"] = [{"date": ts.strftime("%Y-%m-%d"), "firm": r.get("Firm"), "action": r.get("Action"),
                           "from": r.get("FromGrade") or None, "to": r.get("ToGrade") or None,
                           "ptAction": r.get("priceTargetAction"), "pt": clean(r.get("currentPriceTarget")),
                           "ptPrior": clean(r.get("priorPriceTarget"))} for ts, r in ud.iterrows()]
    rec = get("recommendations")
    if rec is not None and not rec.empty:
        out["recTrend"] = [{"period": str(r["period"]), **{k: int(r[k]) for k in ("strongBuy", "buy", "hold", "sell", "strongSell") if k in r}}
                           for _, r in rec.iterrows()]
    out["eps"] = _est(get("earnings_estimate"))
    out["rev"] = _est(get("revenue_estimate"))
    out["revisions"] = _rows(get("eps_revisions"), ("0y", "+1y"), ("upLast7days", "upLast30days", "downLast30days", "downLast7Days"))
    out["epsTrend"] = _rows(get("eps_trend"), ("0y", "+1y"), ("current", "7daysAgo", "30daysAgo", "60daysAgo", "90daysAgo"))
    inc = get("income_stmt")
    years = []
    if inc is not None and not inc.empty:
        for col in inc.columns:
            ni = clean(inc.loc["Net Income", col]) if "Net Income" in inc.index else None
            rev = clean(inc.loc["Total Revenue", col]) if "Total Revenue" in inc.index else None
            if ni is not None or rev is not None:
                years.append({"fy": pd.Timestamp(col).strftime("%Y-%m-%d"), "netIncome": ni, "revenue": rev})
    out["years"] = years
    return ticker, out


def add_year_end_prices(data):
    """Split-adjusted weekly close at each fiscal year-end (one batch download for all tickers)."""
    tickers = [t for t, a in data.items() if a.get("years")]
    prices = download(tickers, period="5y", interval="1wk")
    for t in tickers:
        close = prices.get(t, pd.DataFrame()).get("Close")
        if close is None or close.dropna().empty:
            continue
        close = close.dropna()
        close.index = close.index.tz_localize(None) if close.index.tz is not None else close.index
        for y in data[t]["years"]:
            fy = pd.Timestamp(y["fy"])
            before = close[(close.index <= fy + pd.Timedelta(days=3)) & (close.index >= fy - pd.Timedelta(days=12))]
            y["price"] = float(before.iloc[-1]) if len(before) else None


def today_et():
    return datetime.now(ET).date().isoformat()


def read_cache():
    try:
        with open(CACHE) as f:
            c = json.load(f)
        return c if isinstance(c, dict) and "data" in c else None
    except (OSError, ValueError):
        return None


def load(tickers, force=False):
    """{ticker: analyst data}. Downloads only if the cache is not from today (ET) or misses tickers."""
    c = read_cache()
    if c and not force and c.get("date") == today_et() and all(t in c["data"] for t in tickers):
        return c["data"]
    t0 = time.time()
    with ThreadPoolExecutor(THREADS) as ex:
        data = dict(ex.map(fetch_one, tickers))
    add_year_end_prices(data)
    with open(CACHE, "w") as f:
        json.dump({"date": today_et(), "data": data}, f, default=clean)
    log.info("analysts & valuation history: %d tickers in %.1fs", len(data), time.time() - t0)
    return data


def cached_data():
    """Whatever is cached (even if not from today), for a fast server start."""
    c = read_cache()
    return (c or {}).get("data") or {}


def is_fresh():
    c = read_cache()
    return bool(c and c.get("date") == today_et())


# ---------------------------------------------------------------- analyst summary

def analyst_summary(a, price=None):
    """Compact numbers for the screener / signal: last-30-day actions, estimate revisions."""
    if not a:
        return {}
    cutoff = (pd.Timestamp.now() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    recent = [x for x in a.get("actions", []) if x["date"] >= cutoff]
    tr = (a.get("epsTrend") or {}).get("+1y") or {}
    rev30 = pct(tr.get("current"), tr.get("30daysAgo"))
    rev90 = pct(tr.get("current"), tr.get("90daysAgo"))
    rt = a.get("recTrend") or []
    return {
        "up30": sum(x["action"] == "up" for x in recent), "down30": sum(x["action"] == "down" for x in recent),
        "init30": sum(x["action"] == "init" for x in recent),
        "ptUp30": sum(x["ptAction"] == "Raises" for x in recent), "ptDown30": sum(x["ptAction"] == "Lowers" for x in recent),
        "epsRev30": rev30, "epsRev90": rev90,
        "epsGrowthNextY": ((a.get("eps") or {}).get("+1y") or {}).get("growth"),
        "recNow": rt[0] if rt else None, "rec3m": rt[3] if len(rt) > 3 else None,
    }


def pct(a, b):
    return (a / b - 1) * 100 if a is not None and b not in (None, 0) else None


# ---------------------------------------------------------------- valuation

def _valid(v, hi=500):
    return v is not None and 0 < v < hi


def peer_medians(rows):
    """Median forward P/E, P/S, EV/EBITDA per sector: {sector: {metric: (median, n)}}."""
    def med(rs, k):
        vals = [r[k] for r in rs if _valid(r.get(k))]
        return (float(pd.Series(vals).median()), len(vals)) if vals else (None, 0)
    out = {}
    for sec in {r["sector"] for r in rows}:
        rs = [r for r in rows if r["sector"] == sec]
        out[sec] = {k: med(rs, k) for k, _ in SECTOR_METRICS}
    return out


def history(row, a):
    """Trailing P/E and P/S at past fiscal year-ends (see module docstring for the approximation)."""
    price, mcap = row.get("price"), row.get("mcap")
    out = {"pe": [], "ps": []}
    if not (a and price and mcap):
        return out
    for y in a.get("years", []):
        if not y.get("price"):
            continue
        mcap_fy = mcap * y["price"] / price
        if y.get("netIncome") and y["netIncome"] > 0:
            out["pe"].append({"fy": y["fy"], "v": mcap_fy / y["netIncome"]})
        if y.get("revenue") and y["revenue"] > 0:
            out["ps"].append({"fy": y["fy"], "v": mcap_fy / y["revenue"]})
    return out


def valuation(row, a, medians):
    """Compare with sector peers and with the stock's own history -> label + Italian notes."""
    sec_meds = medians.get(row["sector"], {})
    vs_sector, sector_logs = {}, []
    for k, label in SECTOR_METRICS:
        v = row.get(k)
        med, n = sec_meds.get(k, (None, 0))
        if _valid(v) and med and n >= MIN_PEERS:
            vs_sector[k] = {"label": label, "value": v, "median": med, "n": n, "group": row["sector"], "ratio": v / med}
            sector_logs.append(math.log(v / med))

    hist = history(row, a)
    vs_hist, hist_logs = {}, []
    for k, label, now in (("pe", "P/E (ultimi 12 mesi)", row.get("pe")), ("ps", "P/S", row.get("ps"))):
        vals = [x["v"] for x in hist[k] if _valid(x["v"], 1000)]
        if len(vals) >= 2 and _valid(now, 1000):
            med = float(pd.Series(vals).median())
            vs_hist[k] = {"label": label, "value": now, "median": med, "ratio": now / med, "years": hist[k]}
            hist_logs.append(math.log(now / med))

    parts = [sum(x) / len(x) for x in (sector_logs, hist_logs) if x]
    ratio = math.exp(sum(parts) / len(parts)) if parts else None
    label = None if ratio is None else "Economica" if ratio <= CHEAP else "Cara" if ratio >= RICH else "In linea"

    growth = ((a or {}).get("eps") or {}).get("+1y", {}).get("growth")
    peg = row["fpe"] / (growth * 100) if _valid(row.get("fpe")) and growth and growth > 0 else None

    notes = []
    for x in vs_sector.values():
        few = f", solo {x['n']} titoli" if x["n"] < FEW_PEERS else ""
        notes.append(f"{x['label']} {x['value']:.1f} contro una mediana di {x['median']:.1f} ({x['group']}{few}): {_diff(x['ratio'])}")
    if not vs_sector:
        notes.append("Confronto con il settore non possibile: nel Nasdaq-100 ci sono troppo pochi titoli simili")
    for x in vs_hist.values():
        yrs = len(x["years"])
        notes.append(f"{x['label']} {x['value']:.1f} contro una mediana di {x['median']:.1f} negli ultimi {yrs} bilanci annuali: {_diff(x['ratio'])}")
    if peg is not None:
        notes.append(f"PEG {peg:.2f} (P/E atteso diviso crescita attesa degli utili): "
                     + ("crescita a buon prezzo" if peg < 1 else "prezzo alto rispetto alla crescita" if peg > 2 else "prezzo in linea con la crescita"))
    if not vs_hist:
        notes.append("Storico non disponibile (utili negativi, dati mancanti o titolo quotato da poco)")
    return {"label": label, "ratio": ratio, "peg": peg, "vsSector": vs_sector, "vsHistory": vs_hist,
            "notes": [_it(n) for n in notes]}


def _diff(r):
    d = (r - 1) * 100
    return f"{abs(d):.0f}% {'più cara' if d > 0 else 'più economica'}" if abs(d) >= 3 else "in linea"


def _it(s):
    """Italian decimal comma for the numbers in a note (only digits.digits patterns)."""
    return re.sub(r"(\d)\.(\d)", r"\1,\2", s)
