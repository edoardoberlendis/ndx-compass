"""Nasdaq-100 live dashboard — data server.

Pulls constituents from Wikipedia, prices/fundamentals from Yahoo Finance
(via yfinance), keeps everything cached in memory, refreshes in the background,
and serves a JSON API plus the static frontend.

Run:  python3 server.py   ->  http://localhost:8100
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import resource
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf
from flask import Flask, jsonify, request, send_from_directory

import macro_calendar
import market_calendar
import portfolio

warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
log = logging.getLogger("ndx")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "cache")
STATIC_DIR = os.path.join(ROOT, "static")
WATCHLIST = os.path.join(ROOT, "watchlist.json")   # "I miei titoli", saved by the page
os.makedirs(CACHE_DIR, exist_ok=True)

ET = ZoneInfo("America/New_York")
INDEX = "^NDX"
BENCHMARKS = {"^NDX": "Nasdaq-100", "^GSPC": "S&P 500", "^DJI": "Dow Jones", "^RUT": "Russell 2000",
              "^VIX": "VIX", "^VXN": "VXN", "^TNX": "Treasury 10 anni", "DX-Y.NYB": "Dollaro", "BTC-USD": "Bitcoin",
              "GC=F": "Oro", "CL=F": "Petrolio"}

# Italian display names for Wikipedia's ICB sectors / subsectors (unknown names pass through unchanged)
SECTOR_IT = {
    "Basic Materials": "Materiali di base", "Consumer Discretionary": "Consumi discrezionali",
    "Consumer Staples": "Beni di prima necessità", "Energy": "Energia", "Health Care": "Sanità",
    "Industrials": "Industria", "Technology": "Tecnologia", "Telecommunications": "Telecomunicazioni",
    "Utilities": "Utility", "Financials": "Finanza", "Real Estate": "Immobiliare",
}
INDUSTRY_IT = {
    "Aerospace": "Aerospazio", "Automobiles & Parts": "Auto e componenti", "Biotechnology": "Biotecnologie",
    "Cable & Other Pay Television Services": "TV via cavo e a pagamento",
    "Catalog/Specialty Distribution": "Distribuzione specializzata", "Clothing/Shoe/Accessory Stores": "Negozi di abbigliamento e accessori",
    "Communication Equipment": "Apparati di comunicazione", "Computer Communications Equipment": "Apparati di rete",
    "Computer Hardware": "Hardware", "Computer Peripheral Equipment": "Periferiche per computer",
    "Computer Services": "Servizi informatici", "Computer Software": "Software", "Construction & Materials": "Costruzioni e materiali",
    "Consumer Electronics": "Elettronica di consumo", "Conventional Electricity": "Elettricità tradizionale",
    "Department/Specialty Retail Stores": "Grandi magazzini e negozi specializzati", "Diversified Commercial Services": "Servizi commerciali diversificati",
    "Diversified Industrials": "Industria diversificata", "EDP Services": "Servizi di elaborazione dati",
    "Electric Utilities": "Utility elettriche", "Electronic Components": "Componenti elettronici", "Entertainment": "Intrattenimento",
    "Garments & Clothing": "Abbigliamento", "Hotels/Resorts": "Hotel e resort", "Industrial Machinery": "Macchinari industriali",
    "Industrial Specialties": "Specialità industriali", "Major Chemicals": "Chimica", "Medical Electronics": "Elettronica medicale",
    "Medical/Dental Instruments": "Strumenti medici e dentali", "Military, Government, Technical": "Difesa e servizi governativi",
    "Miscellaneous Amusement & Recreation Services": "Svago e tempo libero", "Motor Vehicles": "Veicoli",
    "Oil & Gas Production": "Produzione di petrolio e gas", "Oil Equipment & Services": "Servizi petroliferi",
    "Ordnance & Accessories": "Armamenti", "Packaged Foods": "Alimenti confezionati", "Power Generation": "Produzione di energia",
    "Railroads": "Ferrovie", "Restaurants": "Ristorazione", "Retail": "Commercio al dettaglio", "Semiconductors": "Semiconduttori",
    "Soft Drinks": "Bevande", "Software": "Software", "Specialty Retailers": "Negozi specializzati",
    "Telecommunications Services": "Servizi di telecomunicazione", "Transportation Services": "Servizi di trasporto", "Trucking": "Autotrasporti",
}
QUOTE_REFRESH_S = 60        # intraday prices: the only thing refreshed every minute
DAILY_AFTER_CLOSE = (16, 15)  # daily history is re-downloaded once per ET day, and once more after this ET time
DL_THREADS = 8              # parallel Yahoo connections per download
NEWS_ALL_S = 2 * 3600       # headlines for all 100 stocks (news part of the final signal)
SIGNAL_BENCH = "QQQ"        # relative-strength benchmark of the technical score, as in signals.py
INFO_THREADS = 6            # parallel fundamentals requests (kept low to avoid Yahoo rate limits)
UA = {"User-Agent": "Mozilla/5.0 (Nasdaq100 dashboard; personal use)"}

# macOS gives each process only 256 open files by default; ~110 parallel downloads plus
# yfinance's caches can exhaust that ("Too many open files"). Raise the soft limit.
try:
    _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(4096, _hard), _hard))
except (ValueError, OSError):
    pass


# ---------------------------------------------------------------- helpers

def clean(v):
    """Make a value JSON-safe (NaN/inf -> None, numpy -> python)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return None if math.isnan(f) or math.isinf(f) else f


def pct(a, b):
    a, b = clean(a), clean(b)
    if a is None or b in (None, 0):
        return None
    return (a / b - 1) * 100


def read_cache(name, ttl):
    p = os.path.join(CACHE_DIR, name)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < ttl:
        with open(p) as f:
            return json.load(f)
    return None


def write_cache(name, data):
    with open(os.path.join(CACHE_DIR, name), "w") as f:
        json.dump(data, f)


def today_et():
    return datetime.now(ET).date().isoformat()


def read_daily_cache(name):
    """Data cached today (ET date), or None. File format: {"date": "YYYY-MM-DD", "data": ...}."""
    c = read_cache(name, 7 * 86400)
    if isinstance(c, dict) and c.get("date") == today_et():
        return c["data"]
    return None


def write_daily_cache(name, data):
    write_cache(name, {"date": today_et(), "data": data})


def open_fds():
    try:
        return len(os.listdir("/dev/fd"))
    except OSError:
        return -1


def market_status(now=None):
    """open / pre / post / closed, or "holiday" on NYSE holidays (market_calendar.py); early-close days end at 13:00."""
    now = now or datetime.now(ET)
    if now.weekday() >= 5:
        return "closed"
    if market_calendar.holiday(now):
        return "holiday"
    t = now.hour * 60 + now.minute
    close = market_calendar.close_minute(now)          # 16:00, or 13:00 on early-close days
    if 4 * 60 <= t < 9 * 60 + 30:
        return "pre"
    if 9 * 60 + 30 <= t < close:
        return "open"
    if close <= t < close + 4 * 60:                    # after-hours: until 20:00, or 17:00 on early-close days
        return "post"
    return "closed"


def market_note(now=None):
    """Extra facts for the status line: holiday name + reopening day, early close, calendar running out."""
    now = now or datetime.now(ET)
    hol, early = market_calendar.holiday(now), market_calendar.early_close(now)
    return {
        "holiday": hol,
        "reopen": market_calendar.next_trading_day(now).isoformat() if hol else None,
        "earlyClose": early,
        "calWarnings": calendar_warnings(now),
    }


def calendar_warnings(now):
    """Small ⚠ next to the update time (phase 21): calendars that run out within 30 days, failed date checks, and
    NYSE sessions missing from the signal diary or without an evening report."""
    out = []
    w = market_calendar.coverage_warning(now.date())
    if w:
        out.append(w)
    out += macro_calendar.coverage_warnings(now.date())
    out += [f"Controllo automatico delle date macro non riuscito: {v}. Uso le date scritte nel codice."
            for v in (macro_calendar._auto.get("errors") or {}).values()]
    try:
        import diary
        last = last_closed_session(now)
        if last:
            miss = diary.missing(last)
            if miss:
                out.append(f"Diario dei segnali: {'manca' if len(miss) == 1 else 'mancano'} {len(miss)} {'seduta' if len(miss) == 1 else 'sedute'} "
                           f"({', '.join(d[8:] + '/' + d[5:7] for d in miss[-5:])}{' e altre' if len(miss) > 5 else ''}): la dashboard o il job serale non erano attivi dopo la chiusura.")
            first = (diary.days() or [None])[0]
            if first:
                import signals
                have = {r.split("_")[0] for r in signals.list_reports() if r.endswith("_close")}
                no_rep = [d for d in sessions_between(first, last) if d not in have]
                if no_rep:
                    out.append(f"Report della sera: {'manca' if len(no_rep) == 1 else 'mancano'} {len(no_rep)} {'seduta' if len(no_rep) == 1 else 'sedute'} dal {first[8:]}/{first[5:7]} "
                               "(il job serale si installa con ./schedule.sh install).")
    except Exception:
        log.exception("calendar warnings")
    return out


def sessions_between(first, last):
    """NYSE sessions from first to last (ISO dates, both included)."""
    d, end, out = date.fromisoformat(first), date.fromisoformat(last), []
    while d <= end:
        if market_calendar.is_trading_day(d):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def last_closed_session(now=None):
    """The last NYSE session whose close is at least 20 minutes old (ISO date)."""
    now = now or datetime.now(ET)
    d = now.date()
    if market_calendar.is_trading_day(d) and now.hour * 60 + now.minute >= market_calendar.close_minute(now) + 20:
        return d.isoformat()
    d -= timedelta(days=1)
    while not market_calendar.is_trading_day(d):
        d -= timedelta(days=1)
    return d.isoformat()


# ---------------------------------------------------------------- constituents

def load_constituents():
    return [{**r, "sector": SECTOR_IT.get(r["sector"], r["sector"]), "industry": INDUSTRY_IT.get(r["industry"], r["industry"])}
            for r in _load_constituents()]


def _load_constituents():
    cached = read_cache("constituents.json", 24 * 3600)
    if cached:
        return cached
    try:
        r = requests.get("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies", headers=UA, timeout=20)
        r.raise_for_status()
        table = next(t for t in pd.read_html(io.StringIO(r.text)) if "Ticker" in t.columns)
        cols = {c: c.split("[")[0].strip() for c in table.columns}
        table = table.rename(columns=cols)
        rows = [{"ticker": str(x["Ticker"]).strip().replace(".", "-"),
                 "name": str(x["Company"]).strip(),
                 "sector": str(x["ICB Industry"]).strip(),
                 "industry": str(x["ICB Subsector"]).strip()} for _, x in table.iterrows()]
        write_cache("constituents.json", rows)
        log.info("constituents: %d from Wikipedia", len(rows))
        return rows
    except Exception as e:  # stale cache is better than nothing
        log.warning("constituents fetch failed: %s", e)
        p = os.path.join(CACHE_DIR, "constituents.json")
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
        raise


# ---------------------------------------------------------------- fundamentals

INFO_FIELDS = ["longName", "shortName", "sharesOutstanding", "marketCap", "trailingPE", "forwardPE",
               "pegRatio", "priceToBook", "priceToSalesTrailing12Months", "enterpriseToEbitda",
               "dividendYield", "beta", "trailingEps", "forwardEps", "profitMargins", "operatingMargins",
               "grossMargins", "revenueGrowth", "earningsGrowth", "returnOnEquity", "totalRevenue",
               "freeCashflow", "totalCash", "totalDebt", "fullTimeEmployees", "targetMeanPrice",
               "targetHighPrice", "targetLowPrice", "recommendationKey", "recommendationMean",
               "numberOfAnalystOpinions", "averageVolume", "averageVolume10days", "fiftyTwoWeekHigh",
               "fiftyTwoWeekLow", "shortPercentOfFloat", "heldPercentInstitutions", "website", "city",
               "state", "country", "longBusinessSummary", "earningsTimestamp", "exDividendDate"]


def fetch_info(ticker):
    for attempt in range(3):
        try:
            info = yf.Ticker(ticker).info or {}
            return ticker, {k: info.get(k) for k in INFO_FIELDS}
        except Exception:
            time.sleep(1 + attempt)
    return ticker, {}


def infos_fresh():
    return read_daily_cache("infos.json") is not None


def load_infos(tickers):
    """Fundamentals + analyst targets, downloaded at most once per ET day (cached in cache/infos.json)."""
    infos = read_daily_cache("infos.json") or {}
    missing = [t for t in tickers if t not in infos]
    if not missing:
        return infos
    t0 = time.time()
    with ThreadPoolExecutor(INFO_THREADS) as ex:
        infos.update(ex.map(fetch_info, missing))
    write_daily_cache("infos.json", infos)
    log.info("fundamentals: %d tickers in %.1fs", len(missing), time.time() - t0)
    return infos


# ---------------------------------------------------------------- price history

def split_download(df, tickers):
    """yf.download(group_by='ticker') -> {ticker: DataFrame}."""
    out = {}
    if df is None or df.empty:
        return out
    if isinstance(df.columns, pd.MultiIndex):
        lv0 = set(df.columns.get_level_values(0))
        for t in tickers:
            if t in lv0:
                sub = df[t].dropna(how="all")
                if not sub.empty:
                    out[t] = sub
    elif len(tickers) == 1:
        out[tickers[0]] = df.dropna(how="all")
    return out


def download(tickers, **kw):
    for attempt in range(3):
        try:
            df = yf.download(tickers, group_by="ticker", progress=False, threads=DL_THREADS, auto_adjust=True, **kw)
            return split_download(df, tickers)
        except Exception as e:
            log.warning("download failed (%s), retry %d", e, attempt + 1)
            time.sleep(2 + attempt * 2)
    return {}


# ---------------------------------------------------------------- index weights: top 10 from the QQQ fund
# The Nasdaq-100 caps its largest members, so pure market-cap weights overstate the giants (NVDA ~13.5% instead of ~8%).
# No free source without login gives all the weights; Nasdaq.com shows the real weights of QQQ's top 10 holdings.
# That endpoint belongs to the nasdaq.com site (not an official API): if it fails or looks wrong, weights stay estimated.
QQQ_TOP_URL = "https://api.nasdaq.com/api/company/QQQ/holdings?assetclass=etf"
QQQ_TOP_CACHE = "qqq_top_weights.json"


def fetch_qqq_top():
    """{ticker: weight %} of QQQ's 10 largest holdings, or None if unavailable or implausible."""
    try:
        r = requests.get(QQQ_TOP_URL, timeout=10, headers={**UA, "Accept": "application/json"})
        r.raise_for_status()
        rows = r.json()["data"]["holdings"]["rows"]
        w = {x["symbol"].strip().upper(): float(str(x["weighting"]).rstrip("%")) for x in rows}
    except Exception as e:
        log.warning("QQQ top weights unavailable (%s): weights estimated from market cap", e)
        return None
    if not (5 <= len(w) <= 15 and 20 <= sum(w.values()) <= 80 and all(0 < v < 20 for v in w.values())):
        log.warning("QQQ top weights look wrong (%s): weights estimated from market cap", w)
        return None
    return w


def split_weights(caps, total_w, cap=None):
    """Share total_w among stocks in proportion to market cap; a stock outside the top 10 cannot weigh more than the
    10th largest real weight (cap), so its excess goes to the others, repeated until nobody is above the cap."""
    out, free, left = {}, dict(caps), total_w
    while free:
        s = sum(free.values())
        if not s:
            break
        share = {t: c / s * left for t, c in free.items()}
        over = [t for t, w in share.items() if cap is not None and w > cap]
        if not over:
            out.update(share)
            break
        for t in over:
            out[t] = cap
            left -= cap
            del free[t]
    return out


def qqq_top_weights():
    """Today's top-10 weights (downloaded at most once a day); yesterday's copy (up to 7 days) if today's fails."""
    w = read_daily_cache(QQQ_TOP_CACHE)
    if w:
        return w
    w = fetch_qqq_top()
    if w:
        write_daily_cache(QQQ_TOP_CACHE, w)
        return w
    old = read_cache(QQQ_TOP_CACHE, 7 * 86400)
    return old.get("data") if isinstance(old, dict) else None


# ---------------------------------------------------------------- daily history cache (faster start)
# The 2-year daily history is saved in cache/daily.pkl. At start (and at each daily refresh) only the last days are
# downloaded again. Yahoo adjusts past prices for dividends and splits, so a stock whose older overlapping closes
# changed is downloaded again in full; a damaged or too old cache means a full download, as before.
DAILY_CACHE = os.path.join(CACHE_DIR, "daily.pkl")
DAILY_CACHE_MAX_AGE_D = 10     # older than this: download everything again
DAILY_OVERLAP_D = 7            # calendar days downloaded again before the last cached bar
DAILY_ADJ_TOL = 0.001          # 0.1%: a larger change in an old close means an adjustment -> full download of that stock


def load_daily_cache():
    try:
        c = pd.read_pickle(DAILY_CACHE)
        if not (isinstance(c, dict) and c.get("v") == 1 and isinstance(c.get("data"), dict) and c["data"]):
            return None
        if time.time() - c["saved"] > DAILY_CACHE_MAX_AGE_D * 86400:
            log.info("daily cache older than %d days: full download", DAILY_CACHE_MAX_AGE_D)
            return None
        return c["data"], c["saved"]
    except FileNotFoundError:
        return None
    except Exception as e:
        log.warning("daily cache unreadable (%s): full download", e)
        return None


def save_daily_cache(data):
    try:
        pd.to_pickle({"v": 1, "saved": time.time(), "data": data}, DAILY_CACHE + ".tmp")
        os.replace(DAILY_CACHE + ".tmp", DAILY_CACHE)
    except Exception as e:
        log.warning("daily cache not saved (%s)", e)


def merge_daily(old, new, tickers):
    """Append the freshly downloaded days to the cached history. Returns (merged, tickers to download in full)."""
    merged, redo = {}, []
    for t in tickers:
        o, n = old.get(t), new.get(t)
        if o is None or o.empty or n is None or n.empty:
            redo.append(t)
            continue
        common = o.index[:-1].intersection(n.index)          # the last cached bar may have been a partial session
        if len(common):
            a, b = o.loc[common, "Close"], n.loc[common, "Close"]
            if ((a - b).abs() / b.abs()).max() > DAILY_ADJ_TOL:
                redo.append(t)
                continue
        m = pd.concat([o[o.index < n.index.min()], n])
        merged[t] = m[m.index >= m.index.max() - pd.Timedelta(days=2 * 365 + 7)]   # keep ~2 years, as period="2y"
    return merged, redo


# ---------------------------------------------------------------- store

class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.constituents = []
        self.infos = {}
        self.daily = {}         # ticker -> DataFrame (2y daily)
        self.top_weights = None  # ticker -> real weight % of QQQ's top 10 holdings (Nasdaq.com), refreshed daily
        self.intraday = {}      # ticker -> DataFrame (today, 5m)
        self.snapshot = None
        self.last_quote = 0.0
        self.last_daily = 0.0
        self.ready = threading.Event()
        self.error = None
        self.analysts = {}      # ticker -> analyst data + fiscal-year history (analysts.py, daily)
        self.valuations = {}    # ticker -> valuation detail, rebuilt with every snapshot
        self.analysts_running = False
        self.tech = {}          # ticker -> signals.metrics() (20/40/60 trend score), recomputed with the daily history
        self.news_all = None    # ticker -> recent headlines for the news part of the signal (every NEWS_ALL_S)
        self.news_at = 0.0
        self.news_running = False
        self.signals = {}       # ticker -> final signal detail (score.py), rebuilt with every snapshot
        self.ta = {}            # ticker -> levels, patterns and groups for the detail's "Analisi tecnica" (technical.py)

    # -- refreshers
    def refresh_analysts(self, tickers):
        """Once a day, in the background: ~15 s of small Yahoo requests that must not delay prices."""
        import analysts  # local import: analysts imports this module
        if self.analysts_running:
            return
        self.analysts_running = True

        def job():
            try:
                self.analysts = analysts.load(tickers)
                self.build()
            except Exception:
                log.exception("analyst refresh failed")
            finally:
                self.analysts_running = False
        threading.Thread(target=job, daemon=True).start()

    def daily_due(self, last_ts=None):
        """Once per ET day, plus once after the close so perf windows include the final bar."""
        last_ts = last_ts or self.last_daily
        if not last_ts:
            return True
        now = datetime.now(ET)
        last = datetime.fromtimestamp(last_ts, ET)
        cutoff = now.replace(hour=DAILY_AFTER_CLOSE[0], minute=DAILY_AFTER_CLOSE[1], second=0, microsecond=0)
        return last.date() != now.date() or last < cutoff <= now

    def refresh_daily(self):
        tickers = [c["ticker"] for c in self.constituents] + list(BENCHMARKS) + [SIGNAL_BENCH]
        t0 = time.time()
        old, d, how = self.daily, None, "full download"
        if not old:                                   # first run after start: in-memory history still empty
            cached_daily = load_daily_cache()
            if cached_daily and not self.daily_due(cached_daily[1]) and all(t in cached_daily[0] for t in tickers):
                # saved today (and after the close, if it is evening): same as a server that stayed on, nothing to download
                d, how = cached_daily[0], "cache already up to date"
                saved_at = cached_daily[1]
            elif cached_daily:
                old = cached_daily[0]
        if old and d is None:
            last = max(df.index.max() for df in old.values())
            start = (last - pd.Timedelta(days=DAILY_OVERLAP_D)).strftime("%Y-%m-%d")
            new = download(tickers, start=start, interval="1d")
            if new:
                d, redo = merge_daily(old, new, tickers)
                if redo:
                    d.update(download(redo, period="2y", interval="1d"))
                how = f"cache + days since {start}, {len(redo)} downloaded in full"
        if not d:
            d = download(tickers, period="2y", interval="1d")
        if d:
            tech = self.technicals(d)
            try:
                import technical  # local import: technical imports this module
                ta = technical.build(d, self.constituents, tech)
            except Exception:
                log.exception("technical analysis failed")     # prices must not depend on it
                ta = {}
            fresh = how != "cache already up to date"
            with self.lock:
                self.daily = d
                self.tech = tech
                self.ta = ta
                self.last_daily = time.time() if fresh else saved_at
            if fresh:
                save_daily_cache(d)
            log.info("daily history: %d series in %.1fs (%s)", len(d), time.time() - t0, how)

    def technicals(self, daily):
        """Same trend score as the report (signals.metrics), on completed daily bars."""
        import signals  # local import: signals imports this module
        if SIGNAL_BENCH not in daily:
            return {}
        bench = daily[SIGNAL_BENCH]["Close"].dropna()
        out = {}
        for c in self.constituents:
            df = daily.get(c["ticker"])
            m = signals.metrics(df, bench) if df is not None else None
            if m:
                m.pop("_chart", None)
                out[c["ticker"]] = m
        return out

    def refresh_news_all(self, tickers):
        """Headlines for every stock, in the background, at most every NEWS_ALL_S (news part of the signal)."""
        if self.news_running or time.time() - self.news_at < NEWS_ALL_S:
            return
        self.news_running = True

        def job():
            try:
                t0 = time.time()
                with ThreadPoolExecutor(4) as ex:
                    items = dict(zip(tickers, ex.map(lambda t: news(t, 40), tickers)))
                self.news_all, self.news_at = items, time.time()
                log.info("news for signals: %d tickers in %.1fs", len(items), time.time() - t0)
                self.build()
            except Exception:
                log.exception("news refresh failed")
            finally:
                self.news_running = False
        threading.Thread(target=job, daemon=True).start()

    def refresh_intraday(self):
        tickers = [c["ticker"] for c in self.constituents] + list(BENCHMARKS)
        t0 = time.time()
        d = download(tickers, period="1d", interval="5m", prepost=False)
        if d:
            with self.lock:
                self.intraday = d
                self.last_quote = time.time()
            log.info("intraday: %d series in %.1fs (open files: %d)", len(d), time.time() - t0, open_fds())

    # -- snapshot assembly
    def build(self):
        with self.lock:
            daily, intra, infos = self.daily, self.intraday, self.infos
        now_et = datetime.now(ET)
        rows = []
        for c in self.constituents:
            t = c["ticker"]
            info = infos.get(t, {})
            row = dict(c)
            row["name"] = info.get("shortName") or c["name"]
            dd, ii = daily.get(t), intra.get(t)
            s = series_stats(dd, ii)
            if s is None:
                continue
            row.update(s)
            shares = clean(info.get("sharesOutstanding"))
            row["mcap"] = shares * row["price"] if shares and row["price"] else clean(info.get("marketCap"))
            avgvol = clean(info.get("averageVolume")) or s.get("avgVol")
            row["relVol"] = (row["volume"] / avgvol) / max(s["sessionFrac"], 0.05) if avgvol and row.get("volume") else None
            for k_out, k_in in [("pe", "trailingPE"), ("fpe", "forwardPE"), ("divYield", "dividendYield"),
                                ("beta", "beta"), ("target", "targetMeanPrice"), ("rec", "recommendationKey"),
                                ("recMean", "recommendationMean"), ("short", "shortPercentOfFloat"),
                                ("revGrowth", "revenueGrowth"), ("margin", "profitMargins"),
                                ("earningsTs", "earningsTimestamp"), ("ps", "priceToSalesTrailing12Months"),
                                ("evEbitda", "enterpriseToEbitda")]:
                row[k_out] = clean(info.get(k_in))
            row["upside"] = pct(row["target"], row["price"])
            rows.append(row)

        total = sum(r["mcap"] or 0 for r in rows)
        # weights: real QQQ weights for its top 10 holdings, the rest of the index split by market cap
        top = {t: w for t, w in (self.top_weights or {}).items() if any(r["ticker"] == t for r in rows)}
        est = split_weights({r["ticker"]: r["mcap"] or 0 for r in rows if r["ticker"] not in top},
                            100 - sum(top.values()), min(top.values()) if top else None)
        for r in rows:
            r["weight"], r["weightSrc"] = (top[r["ticker"]], "qqq") if r["ticker"] in top else (est.get(r["ticker"]), "est")

        # analyst expectations + valuation (vs sector peers and vs the stock's own history)
        import analysts  # local import: analysts imports this module
        import score     # local import: score imports this module
        medians, valuations, sigs = analysts.peer_medians(rows), {}, {}
        news_all = self.news_all
        for r in rows:
            t = r["ticker"]
            a = self.analysts.get(t)
            v = valuations[t] = analysts.valuation(r, a, medians)
            r.update(valLabel=v["label"], valRatio=v["ratio"], peg=v["peg"], **analysts.analyst_summary(a))
            r.pop("recNow", None), r.pop("rec3m", None)             # detail-only fields, served by /api/stock
            # final signal; the news part waits for the first background news download
            sig = sigs[t] = score.for_stock(r, self.tech.get(t), v, news_all.get(t) if news_all is not None else None)
            r["sigScore"], r["signal"] = (sig["score"], sig["signal"]) if sig else (None, None)
            r["trend"] = sig["trend"]["score"] if sig and sig["trend"] else None   # technical score, shown apart as "Trend"

        # index + benchmarks
        idx = {}
        for sym, label in BENCHMARKS.items():
            s = series_stats(daily.get(sym), intra.get(sym))
            if s:
                idx[sym] = {"symbol": sym, "label": label, **{k: s[k] for k in
                            ("price", "prevClose", "chg", "chgPct", "spark", "sparkT", "open", "high", "low",
                             "perf1W", "perf1M", "perfYTD", "perf1Y")}}

        # contributions in index points (cap-weight approximation of the modified cap weighting)
        ndx = idx.get(INDEX)
        if ndx and ndx.get("prevClose"):
            for r in rows:
                r["contrib"] = (r["weight"] or 0) / 100 * (r["chgPct"] or 0) / 100 * ndx["prevClose"]

        # intraday breadth: % of names above previous close at each bar
        breadth = intraday_breadth(rows, intra)

        with self.lock:
            self.valuations = valuations
            self.signals = sigs
            self.snapshot = {
                "asOf": now_et.isoformat(timespec="seconds"),
                "session": rows[0]["session"] if rows else None,
                "status": market_status(now_et),
                "marketNote": market_note(now_et),
                "lastQuote": datetime.fromtimestamp(self.last_quote, ET).isoformat(timespec="seconds") if self.last_quote else None,
                "stocks": rows,
                "indices": idx,
                "breadth": breadth,
                "totalMcap": total,
                "diaryDays": diary_days(),
                "weightsTop": len(top),                          # how many weights are real QQQ weights (0 = all estimated)
            }


def series_stats(dd: pd.DataFrame | None, ii: pd.DataFrame | None):
    """Price, change and performance windows from daily + intraday frames."""
    if dd is None or dd.empty or "Close" not in dd:
        return None
    dc = dd["Close"].dropna()
    if dc.empty:
        return None
    di = dd.index.tz_localize(None) if dd.index.tz is not None else dd.index
    dc.index = di[: len(dc)] if len(di) == len(dc) else dc.index

    if ii is not None and not ii.empty and ii["Close"].notna().any():
        ic = ii["Close"].dropna()
        idx_et = ic.index.tz_convert(ET)
        session = idx_et[-1].date()
        price = float(ic.iloc[-1])
        prev = dc[dc.index.date < session]
        prev_close = float(prev.iloc[-1]) if len(prev) else float(ic.iloc[0])
        spark = [round(float(x), 4) for x in ic.values]
        spark_t = [int(x.timestamp()) for x in idx_et]
        o = float(ii["Open"].dropna().iloc[0])
        h = float(ii["High"].max())
        lo = float(ii["Low"].min())
        vol = float(ii["Volume"].sum()) if "Volume" in ii else None
        first, last = idx_et[0], idx_et[-1]
        frac = min(1.0, max(0.0, ((last - first).total_seconds() + 300) / (390 * 60)))
    else:
        session = dc.index[-1].date()
        price = float(dc.iloc[-1])
        prev_close = float(dc.iloc[-2]) if len(dc) > 1 else price
        spark, spark_t = [], []
        o, h, lo = (float(dd[k].iloc[-1]) for k in ("Open", "High", "Low"))
        vol = float(dd["Volume"].iloc[-1]) if "Volume" in dd else None
        frac = 1.0

    hist = dc[dc.index.date < session]  # completed sessions before today

    def back(n):
        return float(hist.iloc[-n]) if len(hist) >= n else None

    ytd_base = hist[hist.index.year < session.year]
    last_1y = dc[dc.index >= pd.Timestamp(session) - pd.Timedelta(days=365)]
    hi52 = max(float(last_1y.max()), price) if len(last_1y) else price
    lo52 = min(float(last_1y.min()), price) if len(last_1y) else price
    avg_vol = float(dd["Volume"].iloc[-21:-1].mean()) if "Volume" in dd and len(dd) > 21 else None

    # technicals on completed sessions + live price
    closes = pd.concat([hist, pd.Series([price])], ignore_index=True)
    sma = {n: float(closes.iloc[-n:].mean()) if len(closes) >= n else None for n in (20, 40, 60, 50, 200)}
    sma50, sma200 = sma[50], sma[200]
    delta = closes.diff().iloc[-15:]
    gain, loss = delta.clip(lower=0).mean(), (-delta.clip(upper=0)).mean()
    rsi = float(100 - 100 / (1 + gain / loss)) if loss else 100.0

    # 30-day daily closes for the table sparkline
    d30 = [round(float(x), 4) for x in list(hist.iloc[-29:].values) + [price]]

    return {
        "session": session.isoformat(),
        "price": price,
        "prevClose": prev_close,
        "chg": price - prev_close,
        "chgPct": pct(price, prev_close),
        "open": o, "high": h, "low": lo,
        "volume": vol,
        "avgVol": avg_vol,
        "sessionFrac": frac,
        "gapPct": pct(o, prev_close),
        "perf1W": pct(price, back(5)),
        "perf1M": pct(price, back(21)),
        "perf3M": pct(price, back(63)),
        "perf6M": pct(price, back(126)),
        "perfYTD": pct(price, float(ytd_base.iloc[-1])) if len(ytd_base) else None,
        "perf1Y": pct(price, back(252)),
        "hi52": hi52, "lo52": lo52,
        "fromHi52": pct(price, hi52),
        "fromLo52": pct(price, lo52),
        "range52": (price - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else None,
        "vol20": float(hist.pct_change().iloc[-20:].std() * math.sqrt(252) * 100) if len(hist) > 21 else None,
        "sma20": sma[20], "sma40": sma[40], "sma60": sma[60], "sma50": sma50, "sma200": sma200,
        "vsSma20": pct(price, sma[20]), "vsSma40": pct(price, sma[40]), "vsSma60": pct(price, sma[60]),
        "vsSma50": pct(price, sma50), "vsSma200": pct(price, sma200),
        "rsi": rsi,
        "spark": spark,
        "sparkT": spark_t,
        "d30": d30,
    }


def intraday_breadth(rows, intra):
    frames = {}
    for r in rows:
        ii = intra.get(r["ticker"])
        if ii is not None and not ii.empty and r.get("prevClose"):
            frames[r["ticker"]] = ii["Close"] / r["prevClose"] - 1
    if not frames:
        return []
    df = pd.DataFrame(frames).ffill()
    out = []
    for ts, row in df.iterrows():
        v = row.dropna()
        if len(v) < 10:
            continue
        out.append({"t": int(ts.timestamp()), "adv": int((v > 0).sum()), "dec": int((v < 0).sum()),
                    "median": clean(v.median() * 100)})
    return out


store = Store()


def diary_days():
    """Number of sessions in the signal diary (the Diario page is shown from diary.READY_SESSIONS on)."""
    try:
        import diary
        return len(diary.days())
    except Exception:
        return 0


_earn = {"data": {}, "key": None}


def run_daily_job():
    """The evening job (daily_job.py, launchd at 22:45 Mon-Fri; phase 21): with the dashboard closed it does what the
    open dashboard does after the close - report, signal diary and the day's picture of my portfolio. It writes only
    what is missing, so it does not clash with a dashboard that is also open."""
    import analysts
    import history
    import signals
    t0 = time.time()
    store.constituents = load_constituents()
    tickers = [c["ticker"] for c in store.constituents]
    store.infos = load_infos(tickers)
    store.analysts = analysts.load(tickers) if not analysts.is_fresh() else analysts.cached_data()
    store.top_weights = qqq_top_weights()
    store.refresh_daily()
    store.refresh_intraday()
    with ThreadPoolExecutor(4) as ex:                    # headlines for the news part of the signal, as the dashboard does
        store.news_all = dict(zip(tickers, ex.map(lambda t: news(t, 40), tickers)))
    store.news_at = time.time()
    store.build()
    macro_calendar.refresh()
    portfolio.refresh()
    for _ in range(180):                                 # my positions: tickers are matched in the background
        if not portfolio._state["resolving"]:
            break
        time.sleep(1)
    portfolio.refresh_quotes()
    with store.lock:
        snap, infos = store.snapshot, dict(store.infos)
    history.record(portfolio.snapshot(snap, infos))
    save_signal_diary()
    save_etf_diary(wait=True)
    now = datetime.now(ET)
    rid = f"{now:%Y-%m-%d}_close"
    after_close = now.hour * 60 + now.minute >= market_calendar.close_minute(now)
    if market_calendar.is_trading_day(now.date()) and after_close and rid not in signals.list_reports():
        signals.run(notify_user=False)                   # the evening report, only once the session is closed
    log.info("daily job done in %.0fs", time.time() - t0)


def save_signal_diary():
    """After the close (and until the next open, if the dashboard was off): the day's verdicts in portafoglio/diario/
    (diary.py). A day is written once and never rewritten; nothing here may stop the price refresh."""
    try:
        import diary
        if market_status() in ("open", "pre"):
            return
        with store.lock:
            snap, bench = store.snapshot, store.daily.get(SIGNAL_BENCH)
        if not snap or bench is None or not len(bench):
            return
        now = datetime.now(ET)
        day = last_closed_session(now)                                   # the session the closing prices belong to
        if diary.exists(day) or not store.ta:
            return
        # Phase 21 fix: the daily history must contain that session's final bar, otherwise levels and the date would
        # belong to the previous session (this is how 2026-10-01 was saved with the prices of 2 October).
        last_bar = str(bench["Close"].dropna().index[-1].date())
        fresh_after_close = store.last_daily and datetime.fromtimestamp(store.last_daily, ET) >= now.replace(
            hour=DAILY_AFTER_CLOSE[0], minute=DAILY_AFTER_CLOSE[1], second=0, microsecond=0)
        if last_bar != day or (day == str(now.date()) and not fresh_after_close):
            store.refresh_daily()
            store.build()
            with store.lock:
                snap, bench = store.snapshot, store.daily.get(SIGNAL_BENCH)
            if bench is None or str(bench["Close"].dropna().index[-1].date()) != day:
                log.warning("signal diary: daily history without the session %s yet, retry later", day)
                return
        pf = portfolio_view()
        if pf.get("resolving"):
            return                                                       # my positions are still being matched: next round
        mine = {p["ticker"]: p for p in pf.get("positions") or [] if p.get("ticker")}
        entries = []
        for r in snap["stocks"]:
            d = stock_decision(r["ticker"], pf, details=False)
            if d:
                entries.append(diary.entry(d, mine.get(r["ticker"])))
        index = {e["ticker"] for e in entries}
        entries += [diary.entry(position=p) for p in pf.get("positions") or [] if (p.get("ticker") or p["isin"]) not in index and p.get("action")]
        if diary.save(day, entries):
            log.info("signal diary: %d verdicts saved for %s", len(entries), day)
    except Exception:
        log.exception("signal diary not saved")


def save_portfolio_history():
    """Today's picture of my portfolio in portafoglio/storico/ (history.py); never stops the price refresh."""
    try:
        import history
        with store.lock:
            snap, infos = store.snapshot, dict(store.infos)
        history.record(portfolio.snapshot(snap, infos))
    except Exception:
        log.exception("portfolio history not saved")


def worker():
    try:
        store.constituents = load_constituents()
        tickers = [c["ticker"] for c in store.constituents]
        store.infos = load_infos(tickers)
        import analysts  # local import: analysts imports this module
        store.analysts = analysts.cached_data()                  # yesterday's copy is fine until the refresh lands
        store.top_weights = qqq_top_weights()
        store.refresh_daily()
        store.refresh_intraday()
        store.build()
        store.ready.set()
        portfolio.on_quotes = save_portfolio_history             # today's picture after every price refresh
        portfolio.refresh()                                      # my positions (portafoglio/), if an export is there
        macro_calendar.refresh()                                 # US macro events: official dates + BLS values
        if not analysts.is_fresh():
            store.refresh_analysts(tickers)
        store.refresh_news_all(tickers)
    except Exception as e:
        store.error = str(e)
        log.exception("startup failed")
        store.ready.set()
        return
    while True:
        time.sleep(QUOTE_REFRESH_S if market_status() in ("open", "pre", "post") else 5 * 60)
        try:
            if store.daily_due():
                store.refresh_daily()
            if not infos_fresh():
                store.infos = load_infos(tickers)
            if read_daily_cache(QQQ_TOP_CACHE) is None:           # new day: real top-10 weights again
                store.top_weights = qqq_top_weights() or store.top_weights
            if not analysts.is_fresh():
                store.refresh_analysts(tickers)
            store.refresh_news_all(tickers)
            store.refresh_intraday()
            store.build()
            portfolio.refresh()
            save_signal_diary()
            save_etf_diary()
            macro_calendar.refresh()                             # does real work at most once a day (more on release days)
        except Exception:
            log.exception("refresh failed")


# ---------------------------------------------------------------- per-stock detail

_detail_cache: dict[tuple, tuple[float, object]] = {}

RANGES = {"1D": ("1d", "5m"), "5D": ("5d", "15m"), "1M": ("1mo", "1h"), "6M": ("6mo", "1d"),
          "YTD": ("ytd", "1d"), "1Y": ("1y", "1d"), "2Y": ("2y", "1d"), "5Y": ("5y", "1wk"), "MAX": ("max", "1mo")}


def cached(key, ttl, fn):
    hit = _detail_cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    _detail_cache[key] = (time.time(), v)
    return v


def history(ticker, rng):
    period, interval = RANGES.get(rng, RANGES["1Y"])
    df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        return []
    return [{"t": int(ts.timestamp()), "o": clean(r.Open), "h": clean(r.High), "l": clean(r.Low),
             "c": clean(r.Close), "v": clean(r.Volume)} for ts, r in df.iterrows()]


def news(ticker, count=12):
    try:
        items = yf.Ticker(ticker).get_news(count=count) or []
    except Exception:
        return []
    out = []
    for n in items[:count]:
        c = n.get("content", n)
        url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or n.get("link")
        out.append({"title": c.get("title"), "publisher": (c.get("provider") or {}).get("displayName") or n.get("publisher"),
                    "time": c.get("pubDate") or n.get("providerPublishTime"), "url": url,
                    "summary": c.get("summary")})
    return [o for o in out if o["title"]]


# ---------------------------------------------------------------- why did it move? (rule-based)
# Headlines are English, so the keywords are English; labels shown in the UI are Italian.
# Order = priority when a headline matches several categories.
NEWS_CATS = [
    ("earnings", "Conti trimestrali", r"earnings|quarterly|\bq[1-4]\b|\beps\b|results|beats?\b|miss(es|ed)?\b|reports? (first|second|third|fourth)"),
    ("guidance", "Previsioni (guidance)", r"guidance|outlook|forecast"),
    ("analyst", "Giudizio degli analisti", r"upgrade|downgrade|price target|initiat|outperform|underperform|overweight|underweight|(buy|sell|neutral|hold) rating|reiterat"),
    ("deal", "Acquisizione / accordo", r"acqui[rs]|merger|takeover|buyout|to buy\b|stake\b|spin-?off"),
    ("legal", "Regolatori / cause legali", r"antitrust|\bftc\b|\bdoj\b|\bsec\b|probe|investigat|lawsuit|sued\b|court|jury|verdict|regulat|\bfined?\b|\bban\b|tariff|export (control|curb|restriction)|sanction"),
    ("product", "Prodotto / contratto", r"launch|unveil|introduc|new (line|product|model|version)|rolls? out|revamp|overhaul|contract|partnership|partners with|agreement|licen[cs]e|\border\b|approval|\bfda\b|\bwins?\b|award|copilot"),
    ("capital", "Operazioni sul capitale", r"buyback|repurchase|(raises?|hikes?|cuts?|boosts?) (its |the )?dividend|dividend (hike|increase|cut)|share offering|stock offering|stock split"),
    ("people", "Cambio al vertice", r"steps down|resign|appoint|names? (a )?new (ceo|cfo|chief)|to succeed|retire"),
    ("macro", "Macro / mercato", r"\bfed\b|inflation|rate cut|interest rate|\bcpi\b|jobs report|recession|treasur|yields?\b|oil prices?"),
    ("sector", "Movimento di settore", r"(chip|semiconductor|software|cyber ?security|neocloud|tech|ai) (stocks|names|shares|sector)|sector|peers"),
]
# "Shares Are Falling, What You Need To Know" style articles written to explain a move
MOVE_EXPLAINER = (r"shares? (are |is )?(up|down|fall|falling|rise|rising|plummet|plunge|soar|skyrocket|jump|sink|slip|trade (higher|lower))"
                  r"|stock (is )?(up|down|jumps?|jumped|fell|falls|slips|soared|sank|sinks|rocket)|why .{0,40}(stock|shares)|what you need to know")
# Automatic daily recaps ("Axon (AXON) Stock Sinks As Market Gains: What You Should Know") explain nothing
DAILY_RECAP = r"as (the )?(broader )?market (gains|rises|climbs|falls|dips|slides|drops)|what you should know"
# In explainer summaries the cause usually follows "after/as/following/amid": "...jumped 5.7% after the company announced..."
REASON_CLAUSE = r"\b(after|as|following|amid|on (?:news|reports?|the news))\b\s+(.+?)(?:\.\s|\.$|$)"
TONE_POS = r"upgrade|beats?\b|raise[sd]?\b|surge|soar|skyrocket|jump|rall(y|ies)|record|strong|outperform|approval|\bwins?\b|boost|higher|gains?\b|\bup\b|rocket"
TONE_NEG = r"downgrade|miss(es|ed)?\b|\bcuts?\b|plunge|plummet|tumble|slump|\bsinks?\b|fall|drops?\b|weak|probe|lawsuit|warn|lower|underperform|\bban\b|slide|slips?\b|loss|\bdown\b"
ALIASES = {"GOOGL": ["Alphabet", "Google"], "GOOG": ["Alphabet", "Google"], "META": ["Meta", "Facebook"],
           "AMZN": ["Amazon"], "AAPL": ["Apple"], "MSFT": ["Microsoft"], "NVDA": ["Nvidia", "NVIDIA"], "TSLA": ["Tesla"]}
NAME_NOISE = {"inc", "inc.", "corp", "corp.", "corporation", "co", "co.", "company", "holdings", "plc", "ltd", "the", "group", "n.v.", "class"}


def news_time(n):
    """News timestamp (ISO string or epoch seconds) -> aware datetime, or None."""
    t = n.get("time")
    try:
        if isinstance(t, (int, float)):
            return datetime.fromtimestamp(t, ET)
        return datetime.fromisoformat(str(t).replace("Z", "+00:00")).astimezone(ET)
    except (TypeError, ValueError):
        return None


def news_window(session_iso, now=None):
    """Headlines that can explain a session's move: from the previous close (−2h, for after-hours news)
    to the next morning (explainer articles are often written after the close)."""
    now = now or datetime.now(ET)
    day = datetime.fromisoformat(session_iso).replace(tzinfo=ET)
    prev = day - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev.replace(hour=14), min(now, (day + timedelta(days=1)).replace(hour=12))


def name_words(ticker, name):
    words = [w.strip(",.") for w in (name or "").split() if w.lower().strip(",") not in NAME_NOISE]
    return ALIASES.get(ticker, []) + [w for w in words[:1] if len(w) >= 3]


def mentions(text, ticker, names):
    text = text or ""
    return bool(re.search(rf"\b{re.escape(ticker)}\b", text) or any(re.search(rf"\b{re.escape(w)}\b", text) for w in names))


def classify_headline(title, summary=""):
    """Categories + tone from the headline. For move-explainer articles the 'after …' clause of the summary
    is added (summaries of ordinary articles are too noisy to use)."""
    title_l = title.lower()
    explainer = bool(re.search(MOVE_EXPLAINER, title_l)) and not re.search(DAILY_RECAP, title_l)
    clause = None
    if explainer and summary:
        first = re.split(r"(?<=\.)\s", summary.strip())[0]
        m = re.search(REASON_CLAUSE, first, re.I)
        clause = m.group(2).strip() if m else None
    if explainer and not clause:
        m = re.search(REASON_CLAUSE, title, re.I)
        clause = m.group(2).strip() if m else None
    text = f"{clause or ''} {title_l}".lower() if explainer else title_l
    cats = [(k, lab) for k, lab, rx in NEWS_CATS if re.search(rx, text)]
    tone = len(re.findall(TONE_POS, title_l)) - len(re.findall(TONE_NEG, title_l))
    return {"cats": cats, "tone": (tone > 0) - (tone < 0), "explainer": explainer, "clause": clause}


def explain_move(row, items, sector_ctx, now=None):
    """Rule-based reason for one stock's move. Returns a dict the dashboard shows as-is.
    Kept separate from news fetching so an AI summary (plan phase 7) can plug in later."""
    start, end = news_window(row["session"], now)
    open_ = datetime.fromisoformat(row["session"]).replace(hour=9, minute=30, tzinfo=ET)
    names = name_words(row["ticker"], row.get("name"))
    direction = 1 if (row.get("chgPct") or 0) >= 0 else -1
    scored = []
    for n in items:
        t = news_time(n)
        if not t or not (start <= t <= end):
            continue
        in_title, in_summary = mentions(n["title"], row["ticker"], names), mentions(n.get("summary"), row["ticker"], names)
        if not (in_title or in_summary):
            continue                                                   # generic market piece, not about this stock
        c = classify_headline(n["title"], n.get("summary"))
        if c["explainer"] and (t < open_ or c["tone"] * direction < 0):
            continue                                                   # explains an earlier session, or the opposite move
        if re.search(DAILY_RECAP, n["title"].lower()):
            continue                                                   # automatic recap: says nothing about the cause
        score = (3 if in_title else 1) + (3 if c["explainer"] else 0) + (1 if c["cats"] else 0) + c["tone"] * direction
        scored.append((score, t.timestamp(), n, c))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    reasons, tone, best = [], 0, None
    if scored:
        _, _, n, c = scored[0]
        best = {"title": n["title"], "url": n.get("url"), "publisher": n.get("publisher"), "time": n.get("time"),
                "clause": c["clause"], "explainer": c["explainer"]}
        reasons, tone = [lab for _, lab in c["cats"]][:2], c["tone"]   # from the chosen headline only
    earn = clean(row.get("earningsTs"))
    if earn and start.timestamp() <= earn <= end.timestamp() and "Conti trimestrali" not in reasons:
        reasons.insert(0, "Conti trimestrali")

    sec = sector_ctx.get(row["sector"]) or {}
    with_sector = sec.get("chg") is not None and abs(sec["chg"]) >= 0.75 and sec["chg"] * direction > 0 and sec.get("same", 0) >= 0.6
    if reasons:
        summary = "Probabile motivo: " + " + ".join(r.lower() if i else r for i, r in enumerate(reasons))
        if tone:
            summary += " (notizia " + ("positiva" if tone > 0 else "negativa") + ")"
    elif best and best["explainer"]:
        summary = "Un articolo spiega il movimento, ma le parole chiave non riconoscono il motivo: leggilo qui sotto"
    elif with_sector:
        summary = f"Nessun motivo specifico nelle notizie: si è mosso insieme al settore {row['sector']}"
    elif best:
        summary = "Ci sono notizie sul titolo, ma le parole chiave non indicano un motivo chiaro: leggi il titolo qui sotto"
    else:
        summary = "Nessuna notizia specifica trovata per questa seduta"
    return {"ticker": row["ticker"], "name": row.get("name"), "chgPct": row.get("chgPct"), "sector": row["sector"],
            "sectorChg": sec.get("chg"), "withSector": with_sector, "reasons": reasons, "tone": tone, "summary": summary,
            "news": best, "more": [{"title": n["title"], "url": n.get("url"), "publisher": n.get("publisher"), "time": n.get("time")}
                                   for _, _, n, _ in scored[1:3]],
            "source": "regole"}


def movers_why(n=8):
    with store.lock:
        snap = store.snapshot
    if not snap:
        return None
    rows = [r for r in snap["stocks"] if r.get("chgPct") is not None]
    ranked = sorted(rows, key=lambda r: r["chgPct"], reverse=True)
    top, flop = ranked[:n], ranked[-n:][::-1]
    sector_ctx = {}                                                    # cap-weighted sector move + share moving the same way
    for sec in {r["sector"] for r in rows}:
        rs = [r for r in rows if r["sector"] == sec]
        w = sum(r.get("mcap") or 0 for r in rs)
        chg = sum((r.get("mcap") or 0) * r["chgPct"] for r in rs) / w if w else None
        same = sum((r["chgPct"] > 0) == (chg > 0) for r in rs) / len(rs) if chg is not None else 0
        sector_ctx[sec] = {"chg": chg, "same": same}
    tickers = [r["ticker"] for r in top + flop]
    with ThreadPoolExecutor(4) as ex:
        # 40 headlines: with only the latest 10, weekend articles push out the ones about Friday's session
        items = dict(zip(tickers, ex.map(lambda t: cached(("n40", t), 600, lambda: news(t, 40)), tickers)))
    return {"session": snap["session"], "asOf": datetime.now(ET).isoformat(timespec="seconds"),
            "top": [explain_move(r, items[r["ticker"]], sector_ctx) for r in top],
            "flop": [explain_move(r, items[r["ticker"]], sector_ctx) for r in flop]}


# ---------------------------------------------------------------- web

app = Flask(__name__, static_folder=None)
# version of the code that serves the page: change it together with PAGE_VERSION in static/app.js whenever the data
# sent to the page changes, so that a server left running with old code is noticed (the page asks to restart it)
DASHBOARD_VERSION = "2026-11-04"


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/static/<path:p>")
def static_files(p):
    return send_from_directory(STATIC_DIR, p)


@app.route("/api/snapshot")
def api_snapshot():
    store.ready.wait(timeout=180)
    if store.error:
        return jsonify({"error": store.error}), 500
    with store.lock:
        snap = store.snapshot
    if snap is None:
        return jsonify({"error": "loading"}), 503
    return app.response_class(json.dumps(snap, default=clean, allow_nan=False).replace("NaN", "null"),
                              mimetype="application/json")


@app.route("/api/history/<ticker>/<rng>")
def api_history(ticker, rng):
    ttl = 60 if rng in ("1D", "5D") else 1800
    return jsonify(cached(("h", ticker, rng), ttl, lambda: history(ticker, rng)))


@app.route("/api/stock/<ticker>")
def api_stock(ticker):
    info = store.infos.get(ticker) or cached(("i", ticker), 86400, lambda: fetch_info(ticker)[1])
    return app.response_class(json.dumps({
        "info": {k: clean(v) if not isinstance(v, str) else v for k, v in info.items()},
        "news": cached(("n", ticker), 600, lambda: news(ticker)),
        "analysts": store.analysts.get(ticker),                 # raw daily data (actions, estimates, revisions)
        "valuation": store.valuations.get(ticker),
        "signal": store.signals.get(ticker),
        # a few trend figures of the technical score, for the detail's Trend section
        "tech": {k: (store.tech.get(ticker) or {}).get(k) for k in ("slope20", "slope40", "slope60", "volRatio")},
        # raw numbers of the "Analisi tecnica" section (index stocks only) and the EUR/USD rate for the position size
        "ta": store.ta.get(ticker),
        "fx": cached(("fx",), 900, eurusd) if ticker in store.ta else None,
        "decision": stock_decision(ticker, capital=request.args.get("capital", type=float)),
    }, default=clean, allow_nan=False), mimetype="application/json")


_ptest = {"mtime": None, "data": None}


def patterns_test():
    """reports/patterns.json (the phase 11 test), reloaded when the file changes; None if it was never run."""
    path = os.path.join(REPORT_DIR, "patterns.json")
    try:
        m = os.path.getmtime(path)
        if _ptest["mtime"] != m:
            with open(path) as f:
                _ptest.update(mtime=m, data=json.load(f))
        return _ptest["data"]
    except Exception:
        return None


def stock_decision(ticker, pf=None, capital=None, details=True):
    """The "Decisione" sheet of one Nasdaq-100 stock (decision.py), or None for anything else.
    details=False (signal diary, 100 stocks at once): no Yahoo request for the last earnings report."""
    import analysts
    import decision
    import diary
    import earnings
    with store.lock:
        snap = store.snapshot
    row = next((r for r in snap["stocks"] if r["ticker"] == ticker), None) if snap else None
    if not row or not row.get("price"):
        return None
    try:
        pf = pf if pf is not None else portfolio_view()
        a = store.analysts.get(ticker)
        info = store.infos.get(ticker) or {}
        extra = {"recTrend": ((a or {}).get("recTrend") or [None])[0], "target": info.get("targetMeanPrice"),
                 "targetN": info.get("numberOfAnalystOpinions")}
        if details:
            reps = earnings.reports([ticker]).get(ticker) or []
            daily = store.daily.get(ticker)
            extra.update(reports=reps, usualMove=earnings.usual_move(reps, daily["Close"] if daily is not None else None))
        d = decision.decide(ticker, row, info, store.valuations.get(ticker), analysts.analyst_summary(a) if a else None,
                            store.ta.get(ticker), patterns_test(), macro_calendar.upcoming(7)["events"], pf,
                            pf.get("fx") or cached(("fx",), 900, eurusd), capital, extra)
        if details and d.get("analysis"):                 # since when the verdict is the same, from the signal diary
            ds = [x for x in diary.days() if x not in diary.excluded()]
            sig = d["analysis"]["signal"]
            sig["since"] = diary.since(d["verdict"]["label"], row["price"], datetime.now(ET).date().isoformat(),
                                       diary.verdict_history(ticker), ds[0] if ds else None)
            sig["sinceChg"] = (row["price"] / sig["since"]["price"] - 1) * 100 if sig["since"]["price"] else None
            sig["diaryDays"] = len(ds)
            prev = next((lab for day, lab, _ in diary.verdict_history(ticker) if lab != d["verdict"]["label"]), None)
            sig["prevLabel"] = prev if sig["since"]["today"] else None
        return d
    except Exception:
        log.exception("decision failed for %s", ticker)
        return None


def eurusd():
    """USD per 1 EUR (last Yahoo quote), or None."""
    try:
        return float(download(["EURUSD=X"], period="5d", interval="1d")["EURUSD=X"]["Close"].dropna().iloc[-1])
    except Exception:
        return None


def recent_news(ticker, name, k=5):
    """Newest k headlines already downloaded for the signal that name the stock (no extra Yahoo requests).
    More than one, so the page can skip opinion pieces when the user hides them."""
    items = (store.news_all or {}).get(ticker) or []
    names = name_words(ticker, name)
    hits = [n for n in items if news_time(n) and mentions(f"{n.get('title')} {n.get('summary') or ''}", ticker, names)]
    return sorted(hits, key=news_time, reverse=True)[:k]


@app.route("/api/watchlist", methods=["GET", "POST"])
def api_watchlist():
    if request.method == "POST":
        raw = (request.get_json(silent=True) or {}).get("tickers") or []
        tickers = list(dict.fromkeys(t.upper() for t in raw if isinstance(t, str) and re.fullmatch(r"[A-Za-z0-9.^=-]{1,12}", t)))
        with open(WATCHLIST + ".tmp", "w") as f:
            json.dump({"tickers": tickers}, f, indent=1)
        os.replace(WATCHLIST + ".tmp", WATCHLIST)
        return jsonify(exists=True, tickers=tickers)
    if not os.path.exists(WATCHLIST):
        return jsonify(exists=False, tickers=[], news={})
    with open(WATCHLIST) as f:
        tickers = json.load(f).get("tickers", [])
    with store.lock:
        snap = store.snapshot
    names = {r["ticker"]: r.get("name") for r in snap["stocks"]} if snap else {}
    news_by = {}
    for t in tickers:
        items = recent_news(t, names.get(t))
        if items:
            news_by[t] = [{k: n.get(k) for k in ("title", "url", "publisher", "time")} for n in items]
    return app.response_class(json.dumps({"exists": True, "tickers": tickers, "news": news_by}, default=clean),
                              mimetype="application/json")


def portfolio_view():
    """My positions with rules, theses and proposed actions (personal data: only served to this Mac, never cached)."""
    import actions
    import analysts
    import history
    import risk
    import rules  # local imports: keep the personal-data modules together
    with store.lock:
        snap, infos = store.snapshot, dict(store.infos)
    pf = portfolio.snapshot(snap, infos)
    pf["rules"] = rules.load()                # my risk per trade (the weight limits were removed in phase 21)
    pf["fiscal"] = actions.load_fiscal()      # my capital losses carried forward (zainetto fiscale), for the tax estimate
    tickers = [p["ticker"] for p in pf.get("positions") or [] if p.get("ticker")]
    if tickers:
        risk.history(tickers)                 # starts the daily download of 2 years of prices if needed (for the 200-day average)
    rows = {r["ticker"]: r for r in snap["stocks"]} if snap else {}
    pf["actions"] = actions.evaluate(pf, {                    # thesis and proposed action of every position (actions.py)
        "rows": rows, "sma200": risk.sma200(), "firstSeen": history.first_seen(),
        "analysts": {t: analysts.analyst_summary(store.analysts.get(t)) for t in tickers if store.analysts.get(t)}})
    add_pillars(pf, rows, tickers)
    return pf


def add_pillars(pf, rows, tickers):
    """Pillars of every position's thesis (pillars.py), checked with the data the dashboard already has; the stocks
    outside the Nasdaq-100 get their analyst data once a day. Changes of the chosen pillars go in the thesis' log."""
    import actions
    import analysts
    import pillars
    import risk
    positions = pf.get("positions") or []
    if not positions:
        return
    with store.lock:
        anl, vals = dict(store.analysts), dict(store.valuations)
    extra = pillars.extra([p["ticker"] for p in positions if p.get("ticker") and p["kind"] == "Azione" and p["ticker"] not in rows])
    sma = risk.sma200()
    closes = risk.history(tickers) if tickers else None
    theses, updates = actions.load(), {}
    for p in positions:
        tk, th = p.get("ticker"), theses.get(p["isin"]) or {}
        d = {"sma200": sma.get(tk)}
        if p["kind"] in ("ETF", "ETC"):
            d["corr"], d["weeks"] = pillars.fund_correlation(pf, p, closes)
        elif tk in rows:
            v = vals.get(tk) or {}
            d.update(years=(anl.get(tk) or {}).get("years"), epsRev90=analysts.analyst_summary(anl.get(tk)).get("epsRev90"),
                     rec=rows[tk].get("rec"), valLabel=v.get("label"))
        elif tk in extra:
            x = extra[tk]
            d.update(years=x["a"].get("years"), epsRev90=analysts.analyst_summary(x["a"]).get("epsRev90"), rec=x["row"].get("rec"))
            d["valLabel"], d["valWhy"] = pillars.extra_valuation(x)
        ev = pillars.evaluate(p, th, d)
        ev["score"] = pillars.score(ev)
        ev["log"] = (th.get("log") or [])[-12:][::-1]           # newest first
        p["pillars"] = ev
        if not ev["draft"]:
            updates[p["isin"]] = pillars.changes(ev, th.get("last"))
    if updates:
        actions.record_pillars(updates)


@app.route("/api/portfolio")
def api_portfolio():
    """My positions from the newest export in portafoglio/."""
    return app.response_class(json.dumps(portfolio_view(), default=clean), mimetype="application/json")


@app.route("/api/thesis/review", methods=["POST"])
def api_thesis_review():
    """"Ho rivisto la tesi": save my reason; the review rules that fired stay silent for 30 days unless a new one fires."""
    import actions
    if not local_request():
        return jsonify(error="La tesi si modifica solo dalla dashboard aperta su questo Mac."), 403
    body = request.get_json(silent=True) or {}
    p = next((x for x in portfolio_view().get("positions") or [] if x["isin"] == body.get("isin")), None)
    if not p:
        return jsonify(error="Posizione non trovata."), 404
    fired = [r["id"] for r in p["action"]["rules"] if r["group"] == "Rivedi la tesi" and r["state"] == "on"]
    try:
        actions.review(p["isin"], body.get("note"), fired)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/thesis/log", methods=["POST"])
def api_thesis_log():
    """A dated note in the thesis' log, or the pillar written in words marked as still valid / fallen."""
    import actions
    if not local_request():
        return jsonify(error="La tesi si modifica solo dalla dashboard aperta su questo Mac."), 403
    body = request.get_json(silent=True) or {}
    try:
        if body.get("manual"):
            actions.mark_manual(body.get("isin"), body["manual"])
        else:
            actions.add_note(body.get("isin"), body.get("note"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/thesis", methods=["POST"])
def api_thesis():
    """Save the thesis of one position in portafoglio/tesi.json (only from the dashboard open on this Mac)."""
    import actions
    if not local_request():
        return jsonify(error="La tesi si modifica solo dalla dashboard aperta su questo Mac."), 403
    body = request.get_json(silent=True) or {}
    try:
        actions.save(body.get("isin"), body)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/earnings")
def api_earnings():
    """Details of the earnings of the next 7 days (earnings.py): estimates, last report, usual move on the reaction day."""
    import earnings
    with store.lock:
        snap, daily, anl = store.snapshot, store.daily, store.analysts
    now = time.time()
    tickers = sorted(r["ticker"] for r in (snap or {}).get("stocks", []) if r.get("earningsTs") and 0 <= r["earningsTs"] - now + 86400 <= 8 * 86400)
    key = (today_et(), tuple(tickers))
    if _earn["key"] == key:
        return jsonify(loading=False, data=_earn["data"])
    earnings.details_async(tickers, daily, anl, lambda d: _earn.update(data=d, key=key))
    return jsonify(loading=True, data=_earn["data"])


@app.after_request
def version_header(resp):
    """Every answer says which version of the code the server runs: the page compares it with its own and asks to
    restart the server when they differ (a server left running with old code: 10 Oct 2026)."""
    resp.headers["X-Dashboard-Version"] = DASHBOARD_VERSION
    return resp


@app.route("/api/etf/diary")
def api_etf_diary():
    """The ETF diary (etf_buy.py): how each verdict did after 1, 3 and 6 months. Personal data, local only."""
    import etf
    import etf_buy
    e = etf._state.get("data") or {}
    return app.response_class(json.dumps({"days": len(etf_buy.days()), "personal": etf_buy.stats(e.get("_close") or {}, "verdict"),
                                          "market": etf_buy.stats(e.get("_close") or {}, "market")}, default=clean), mimetype="application/json")


@app.route("/api/etf/why/<isin>")
def api_etf_why(isin):
    """"Perché si muove" of one ETF (etf.why), computed when its panel is opened."""
    import etf
    w = etf.why(isin)
    return (jsonify(w) if w is not None else (jsonify(error="ETF non trovato"), 404))


@app.route("/api/etf")
def api_etf():
    """Ricerca → ETF (etf.py): public data of the day, plus "Ha senso per il mio portafoglio?" and "Ha senso comprare?"
    computed now in memory."""
    import etf
    d = etf.public()
    st = etf.status()
    if not d:
        return jsonify(status="error" if st["error"] else "loading", **st)
    out = {k: v for k, v in d.items() if not k.startswith("_")}
    out.update(etf_personal(d, portfolio_view()))
    out["status"] = "ok"
    out["dataStatus"] = st
    return app.response_class(json.dumps(out, default=clean), mimetype="application/json")


def etf_personal(d, pf):
    """The personal part of the ETF tab (memory only): fit, diversify, buy verdicts with plan and quantity."""
    import etf
    import etf_buy
    import etf_holdings
    import risk
    out = {"portfolioLoaded": bool(pf.get("positions"))}
    fits = {}
    total = (pf.get("totals") or {}).get("value")
    if pf.get("positions") and not pf.get("error"):
        with store.lock:
            snap = store.snapshot
        idx = {r["ticker"]: (r.get("name") or r["ticker"], r.get("weight") or 0) for r in (snap or {}).get("stocks", [])}
        tickers = [p["ticker"] for p in pf["positions"] if p.get("ticker")]
        closes = risk.history(tickers)                    # may still be downloading: correlation then shown as "in calcolo"
        port_w = risk.portfolio_weekly(pf, closes) if closes else pd.Series(dtype=float)
        listed = {r["isin"] for r in d["rows"]}
        my_funds = [p["isin"] for p in pf["positions"] if portfolio.is_fund(p["kind"])
                    and p.get("sector") != portfolio.LOOK_THROUGH_NDX and p.get("isin") not in listed]
        holdings = {**d["_holdings"], **etf_holdings.held(my_funds)}   # my funds outside the list: portafoglio/, background
        fits, out["fitMissing"] = etf.fit(d["rows"], pf, idx, port_w, d["_weekly"], holdings)
        out["fit"] = fits
        out["diversify"] = etf.diversify(d["rows"], fits)
        out["corrReady"] = closes is not None
        out["pricesMissing"] = closes is not None and len(port_w) <= 30   # downloaded but unusable: correlation not computed
        out["pricesRetryAt"] = risk.retry_at()
    import rules
    risk_pct = rules.load().get("tradeRisk") or 1.0
    usable = out.get("corrReady") and not out.get("pricesMissing")       # without correlation the fit is not complete
    out["buy"] = {r["isin"]: etf_buy.decide(r, fits.get(r["isin"]) if usable else None, total, risk_pct) for r in d["rows"]}
    out["fitComplete"] = bool(usable)
    return out


def save_etf_diary(wait=False):
    """After the close of Borsa Italiana: both verdicts of every ETF in portafoglio/diario_etf/ (etf_buy.py), once per
    session and never rewritten. Only with final closes and a complete "per il mio portafoglio" (correlation included);
    otherwise it tries again at the next round. wait=True (evening job): build the data now and wait for the prices."""
    try:
        import etf
        import etf_buy
        d = etf.public()
        if wait:
            for _ in range(60):
                d = etf.public()
                if d and (d.get("session") or {}).get("closed") and not etf._state["running"]:
                    break
                time.sleep(5)
        if not d or not (d.get("session") or {}).get("closed"):
            return
        day = d["session"]["day"]
        if etf_buy.exists(day):
            return
        pf = portfolio_view()
        if pf.get("resolving"):
            return
        for _ in range(36 if wait else 1):
            p = etf_personal(d, pf)
            if p.get("fitComplete") or not p["portfolioLoaded"]:
                break
            time.sleep(5)
        if p["portfolioLoaded"] and not p.get("fitComplete"):
            log.info("ETF diary: correlation with my portfolio not ready yet, retry later")
            return
        entries = [etf_buy.entry(r, p["buy"][r["isin"]]) for r in d["rows"] if r.get("planLevels")]
        if etf_buy.save(day, entries):
            log.info("ETF diary: %d ETFs saved for %s", len(entries), day)
    except Exception:
        log.exception("ETF diary not saved")


@app.route("/api/diary")
def api_diary():
    """Signal diary: how each kind of verdict did after 1, 3 and 6 months (diary.py). Personal data, local only."""
    import diary
    with store.lock:
        daily = store.daily
    bench = daily.get(SIGNAL_BENCH)
    if bench is None:
        return jsonify(error="dati non pronti"), 503
    tickers = [c["ticker"] for c in store.constituents]
    closes = {t: daily[t]["Close"].dropna() for t in tickers if t in daily}
    res = diary.results(closes, bench["Close"].dropna())
    res["missing"] = diary.missing(last_closed_session())
    return app.response_class(json.dumps(res, default=clean), mimetype="application/json")


@app.route("/api/portfolio/history")
def api_portfolio_history():
    """Value over time and time-weighted performance vs QQQ and a global ETF (history.py): personal data, local only."""
    import history
    return app.response_class(json.dumps(history.performance(), default=clean), mimetype="application/json")


@app.route("/api/portfolio/risk")
def api_portfolio_risk():
    """Risk of my portfolio (risk.py): personal data, computed in memory, never cached on disk."""
    import risk
    with store.lock:
        snap, infos = store.snapshot, dict(store.infos)
    return app.response_class(json.dumps(risk.snapshot(portfolio.snapshot(snap, infos)), default=clean), mimetype="application/json")


@app.route("/api/rules", methods=["POST"])
def api_rules():
    """Save my risk per trade in portafoglio/regole.json (only from the dashboard open on this Mac)."""
    import rules
    if not local_request():
        return jsonify(error="Si modifica solo dalla dashboard aperta su questo Mac."), 403
    body = request.get_json(silent=True) or {}
    try:
        if "settle" in body:
            rules.save_settle(body.get("settle"))           # "regolo in EUR / USD" (phase 22)
        else:
            rules.save_trade_risk(body.get("tradeRisk"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


def local_request():
    """True only for a request made on this Mac by the dashboard's own page. The server already listens on 127.0.0.1
    only; the Host/Origin check and the custom header also stop another site open in the browser from posting here."""
    host = (request.host or "").rsplit(":", 1)[0]
    origin = request.headers.get("Origin")
    return (request.remote_addr in ("127.0.0.1", "::1") and host in ("localhost", "127.0.0.1")
            and (origin is None or re.fullmatch(r"http://(localhost|127\.0\.0\.1)(:\d+)?", origin) is not None)
            and request.headers.get("X-Requested-With") == "ndx-dashboard")


@app.route("/api/fiscal", methods=["POST"])
def api_fiscal():
    """Save my capital losses carried forward (zainetto fiscale) in portafoglio/fiscale.json (only from this Mac)."""
    import actions
    if not local_request():
        return jsonify(error="Si modifica solo dalla dashboard aperta su questo Mac."), 403
    body = request.get_json(silent=True) or {}
    try:
        actions.save_fiscal(body.get("losses"), body.get("expiry"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/rotation")
def api_rotation():
    """Rotation map of sectors and themes against QQQ (Mercato → Settori), from the latest daily history: the same
    signals.group_stats as the old report, so it no longer depends on a saved report."""
    import signals
    with store.lock:
        tech, cons = dict(store.tech), list(store.constituents)
    with open(os.path.join(ROOT, "themes.json")) as f:
        theme_def = json.load(f)
    rows = {t: {**m, "ticker": t} for t, m in tech.items()}
    sectors = [g for sec in sorted({c["sector"] for c in cons})
               if (g := signals.group_stats(sec, [rows.get(c["ticker"]) for c in cons if c["sector"] == sec], "sector"))]
    themes = [g for name, tks in theme_def.items() if (g := signals.group_stats(name, [rows.get(t) for t in tks], "theme"))]
    return jsonify(sectors=sorted(sectors, key=lambda g: -g["score"]), themes=sorted(themes, key=lambda g: -g["score"]))


@app.route("/api/portfolio/upload", methods=["POST"])
def api_portfolio_upload():
    """Step 1: receive a Fineco export and return the preview (new, sold, changed positions). Nothing is replaced."""
    if not local_request():
        return jsonify(error="Il caricamento funziona solo dalla dashboard aperta su questo Mac."), 403
    if (request.content_length or 0) > portfolio.MAX_UPLOAD:
        return jsonify(error="Il file è troppo grande (massimo 5 MB)."), 413
    try:
        name = requests.utils.unquote(request.headers.get("X-Filename", ""))
        return jsonify(portfolio.preview_upload(request.get_data(cache=False), name))
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/portfolio/upload/<step>", methods=["POST"])
def api_portfolio_upload_step(step):
    """Step 2: "confirm" saves the previewed file in portafoglio/ (older files stay there), "cancel" discards it."""
    if not local_request():
        return jsonify(error="Il caricamento funziona solo dalla dashboard aperta su questo Mac."), 403
    if step == "cancel":
        portfolio.cancel_upload()
        return jsonify(ok=True)
    if step != "confirm":
        return jsonify(error="not found"), 404
    try:
        return jsonify(ok=True, file=portfolio.confirm_upload((request.get_json(silent=True) or {}).get("token")))
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.route("/api/macro")
def api_macro():
    """US macro events of the next 7 days, with how much of my portfolio and favourites each one touches."""
    with store.lock:
        snap, infos = store.snapshot, dict(store.infos)
    pf = portfolio.snapshot(snap, infos)
    rows = {r["ticker"]: r for r in snap["stocks"]} if snap else {}
    themes = portfolio._themes_by_ticker()
    try:
        with open(WATCHLIST) as f:
            watch = json.load(f).get("tickers", [])
    except Exception:
        watch = []

    def relevance(impact):
        S, T = set(impact["sectors"]), set(impact["themes"])
        hit = lambda sector, ths: sector in S or (sector == portfolio.LOOK_THROUGH_NDX and "Tecnologia" in S) or bool(T & set(ths))
        pos = [x for x in pf.get("positions", []) if hit(x["sector"], x["themes"])]
        total = (pf.get("totals") or {}).get("value") or 0
        w = [t for t in watch if hit((rows.get(t) or {}).get("sector"), themes.get(t, []))]
        return {"pfShare": sum(x["value"] for x in pos) / total * 100 if total else None,
                "pfItems": [x["ticker"] or x["symbol"] for x in pos], "watchItems": w, "watchTotal": len(watch)}
    return app.response_class(json.dumps(macro_calendar.upcoming(7, relevance), default=clean), mimetype="application/json")


@app.route("/api/movers-why")
def api_movers_why():
    store.ready.wait(timeout=180)
    with store.lock:
        key = ("why", store.snapshot and store.snapshot["session"], store.last_quote // 600)   # recompute at most every 10 min
    out = cached(key, 600, movers_why)
    if out is None:
        _detail_cache.pop(key, None)
        return jsonify({"error": "loading"}), 503
    return app.response_class(json.dumps(out, default=clean, allow_nan=False), mimetype="application/json")


@app.route("/api/news")
def api_market_news():
    def top():
        seen, out = set(), []
        for t in ("QQQ", "NVDA", "AAPL", "MSFT", "AMZN"):
            for n in news(t):
                if n["title"] not in seen:
                    seen.add(n["title"]); n["ticker"] = t; out.append(n)
        return sorted(out, key=lambda n: str(n["time"]), reverse=True)[:20]
    return jsonify(cached(("mn",), 600, top))


# ---------------------------------------------------------------- trend reports (signals.py)

REPORT_DIR = os.path.join(ROOT, "reports")


@app.route("/api/patterns")
def api_patterns():
    """Last test of the technical patterns (backtest.py --patterns, run by hand)."""
    if not os.path.exists(os.path.join(REPORT_DIR, "patterns.json")):
        return jsonify({"error": "missing"}), 404
    return send_from_directory(REPORT_DIR, "patterns.json", max_age=0)


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    port = int(os.environ.get("PORT", 8100))
    log.info("Nasdaq-100 dashboard on http://localhost:%d  (first load takes ~30s)", port)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
