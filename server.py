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

import app_env
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
    """Atomic (Phase 7C): written to a temporary file of this process, then renamed. A reader in the other process (server
    and evening job at the same time) sees the old file or the new one, never half a file."""
    p = os.path.join(CACHE_DIR, name)
    tmp = f"{p}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


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
        tmp = f"{DAILY_CACHE}.{os.getpid()}.tmp"           # one temporary file per process (server and job together)
        pd.to_pickle({"v": 1, "saved": time.time(), "data": data}, tmp)
        os.replace(tmp, DAILY_CACHE)
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
    if app_env.market_only():
        return 0                       # MARKET-ONLY: the signal diary is personal (portafoglio/diario), never listed
    try:
        import diary
        return len(diary.days())
    except Exception:
        return 0


_earn = {"data": {}, "key": None}


def run_daily_job(market_only=False):
    """The evening job (daily_job.py, launchd at 22:45 Mon-Fri; phase 21): with the dashboard closed it does what the
    open dashboard does after the close - report, signal diary and the day's picture of my portfolio. It writes only
    what is missing, so it does not clash with a dashboard that is also open.

    market_only=True (phase 8B, `daily_job.py --market-only`): ONLY the public part - prices, public analyses, the five
    prospective diaries (opportunities, fundamentals, valuations, ETF scanner, decisions), the alerts and the public evening
    report. Never the portfolio, its picture, flussi.json, the signal/ETF/positions diaries in portafoglio/. The caller
    turns on app_env.enable_market_only() first, so any access to portafoglio/ is blocked before it happens.
    Every run is recorded in job_status (steps and outcome only, never personal data)."""
    import analysts
    import job_status
    import signals
    if market_only and not app_env.market_only():
        raise RuntimeError("market-only senza la protezione del portafoglio: chiamare prima app_env.enable_market_only()")
    authorize_writer("job serale")
    t0 = time.time()
    run = job_status.Run("market-only" if market_only else "completo", datetime.now(ET))
    try:
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
        run.step("prezzi", note=_bars_note())
        try:
            macro_calendar.refresh()
            run.step("calendario macro")
        except Exception as e:
            log.exception("macro calendar not refreshed by the evening job")
            run.step("calendario macro", "errore", error=e)
        try:                                                 # Phase 7C: statements as the open dashboard would have them
            import fundamentals                              # (same rules: only the stocks that need it; synchronous here)
            fundamentals.refresh(tickers)
            _inv_invalidate()
            run.step("bilanci")
        except Exception as e:
            log.exception("fundamentals not updated by the evening job: the diary uses the statements already on disk")
            run.step("bilanci", "errore", error=e)
        if not market_only:
            try:                                             # Phase 8A: the personal part can never stop the five diaries
                import history
                portfolio.refresh()
                for _ in range(180):                         # my positions: tickers are matched in the background
                    if not portfolio._state["resolving"]:
                        break
                    time.sleep(1)
                portfolio.refresh_quotes()
                with store.lock:
                    snap, infos = store.snapshot, dict(store.infos)
                history.record(portfolio.snapshot(snap, infos))
                run.step("fotografia del portafoglio")
            except Exception as e:                           # only the kind of error: never positions or values in the log
                log.error("evening job: portfolio picture not saved (%s); the public diaries go on", type(e).__name__)
                run.step("fotografia del portafoglio", "errore", error=e)
            save_signal_diary()
            run.step("diario dei segnali")
        try:                                                 # phase 6B: ETF closes (in this process: no thread) and scan diary
            import etf_catalog
            import etf_prices
            if etf_prices.due(etf_prices.load(), datetime.now(ROME_TZ)):
                etf_prices.save(etf_prices.build(download, etf_catalog.load()))
            run.step("prezzi ETF")
        except Exception as e:
            log.exception("ETF prices not updated by the evening job")
            run.step("prezzi ETF", "errore", error=e)
        save_etf_scan_diary(source="job serale")
        # Phase 7C: the opportunity chain AFTER the ETF closes of the day: its last step (decision diary) records the ETF
        # rows only with the ETF scanner on the same session; before, with the dashboard closed, they were always missing.
        msg = save_opportunity_diary(source="job serale")
        log.info("job serale: %s", msg)
        run.step("catena dei diari", note=msg)
        save_etf_scan_diary(source="job serale")            # idempotent: only if the diary file did not exist before
        run.step("diario scanner ETF")
        msg = save_alerts(source="job serale")              # phase 8A: after the five diaries
        log.info("job serale: %s", msg)
        run.step("alert", "errore" if "non riuscito" in str(msg) else "ok", note=msg)
        if not market_only:
            save_etf_diary(wait=True)
            for _ in range(60):                              # positions diary: wait for the 2 years of prices (risk.py)
                import pos_diary
                save_pos_diary()
                if pos_diary.exists(last_closed_session()) or last_closed_session() != datetime.now(ET).date().isoformat():
                    break
                time.sleep(5)
            run.step("diari personali (ETF e posizioni)")
        now = datetime.now(ET)
        rid = f"{now:%Y-%m-%d}_close"
        after_close = now.hour * 60 + now.minute >= market_calendar.close_minute(now)
        if market_calendar.is_trading_day(now.date()) and after_close and rid not in signals.list_reports():
            signals.run(notify_user=False)                   # the evening report, only once the session is closed
            run.step("report della sera")
        blocked = app_env.private_blocked() if market_only else {}
        if blocked:                                          # a bug: some code tried to reach portafoglio/ (and was stopped)
            log.error("market-only: %d accessi al portafoglio bloccati (%s)", sum(blocked.values()), ", ".join(sorted(blocked)))
            run.problem(f"{sum(blocked.values())} accessi al portafoglio bloccati dalla protezione MARKET-ONLY")
        run.finish(datetime.now(ET), session=last_closed_session())
    except BaseException as e:
        run.abort(datetime.now(ET), e)
        raise
    log.info("daily job done in %.0fs%s", time.time() - t0, " (market-only)" if market_only else "")


def _bars_note():
    """Last daily bar of the benchmark (QQQ), for the job registry: a date, no personal data."""
    try:
        with store.lock:
            bench = store.daily.get(SIGNAL_BENCH)
        return f"ultima barra QQQ {bench['Close'].dropna().index[-1].date()}" if bench is not None and len(bench) else "storico QQQ assente"
    except Exception:
        return None


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
        refresh_fundamentals(tickers)                            # statements for the fundamental engine, in background
    except Exception as e:
        store.error = str(e)
        log.exception("startup failed")
        store.ready.set()
        return
    save_alerts()                                                # phase 8A: one check at start (idempotent)
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
            save_opportunity_diary()                             # opportunity diary (phase O2): never stops the loop
            refresh_etf_prices()                                 # phase 6B: ETF closes once after each Borsa Italiana close
            save_etf_scan_diary()                                # phase 6B: scanner of the ETF exposures, once per session
            save_alerts()                                        # phase 8A: after the diaries; idempotent, cheap when nothing changed
            refresh_fundamentals(tickers)                        # at most every 30 minutes, only stocks that need it
            save_etf_diary()
            save_pos_diary()
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
DASHBOARD_VERSION = "2026-11-06c"


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
        "accountsCurrency": accounts_currency(ticker),          # currency of the statements (Yahoo info figures use it)
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
    """My positions with their "Pagella del titolo", market verdict, automatic stop and proposed level (personal data:
    only served to this Mac, never cached). Since phase 26 nothing written or chosen by me is used (no thesis)."""
    import actions
    import analysts
    import history
    import pillars
    import pos_diary
    import risk
    import rules  # local imports: keep the personal-data modules together
    import stop_auto
    with store.lock:
        snap, infos = store.snapshot, dict(store.infos)
    pf = portfolio.snapshot(snap, infos)
    pf["rules"] = rules.load()                # my risk per trade (the weight limits were removed in phase 21)
    pf["fiscal"] = actions.load_fiscal()      # my capital losses carried forward (zainetto fiscale), for the tax estimate
    positions = pf.get("positions") or []
    tickers = [p["ticker"] for p in positions if p.get("ticker")]
    if tickers:
        risk.history(tickers)                 # starts the daily download of 2 years of prices if needed (for the 200-day average)
    rows = {r["ticker"]: r for r in snap["stocks"]} if snap else {}
    market = position_market(pf, rows)        # as when I decide whether to buy: verdict, trend, levels, earnings
    pils = add_pillars(pf, rows, tickers)     # the "Pagella del titolo" and its log
    # the stop starts from the price of the same series as its levels (never the old price of the Fineco file)
    stops = stop_auto.update(positions, {p["isin"]: (market[p["isin"]]["levelPrice"], market[p["isin"]]["levels"], market[p["isin"]]["money"])
                                         for p in positions if (market.get(p["isin"]) or {}).get("levels")
                                         and market[p["isin"]].get("levelPrice")}) if positions else {}
    an = {t: analysts.analyst_summary(store.analysts.get(t)) for t in tickers if store.analysts.get(t)}
    extra = pillars.read()["data"]
    an.update({t: analysts.analyst_summary(x["a"]) for t, x in extra.items() if t in tickers and t not in an and x.get("a")})
    pf["actions"] = actions.evaluate(pf, {                    # proposed level of every position (actions.py)
        "rows": rows, "sma200": risk.sma200(), "below200": risk.below200_sessions(), "firstSeen": history.first_seen(),
        "analysts": an, "pillars": pils, "market": market, "stops": stops})
    for p in positions:                                       # for the page: market verdict and automatic stop
        m = market.get(p["isin"]) or {}
        p["market"] = {k: m.get(k) for k in ("verdict", "label", "why", "by", "source", "skipped", "trendBase")}
        p["stopAuto"] = stops.get(p["isin"])
    pf["posDiary"] = pos_diary.test_line()                    # the fixed test of the levels (3 months, at least 30 cases)
    return pf


def _future_ts(*ts):
    now = time.time() - 86400
    xs = [t for t in ts if t and t >= now]
    return min(xs) if xs else None


def position_market(pf, rows):
    """The market side of every position, as when I decide whether to buy (phase 26): the verdict of the "Decisione"
    section for the stocks (also outside the Nasdaq-100, with the same rules on their own daily prices), the "solo
    mercato" verdict for ETF and ETC (also outside the ETF list: the rules that need justETF data are skipped and
    named), the long-term trend (price above the 200-day average and 50 above 200), levels for the automatic stop on
    the position's own listing, and the next earnings date. {isin: {...}}."""
    import analysts
    import decision
    import etf
    import etf_buy
    import pillars
    import technical
    positions = pf.get("positions") or []
    if not positions:
        return {}
    stub = {"positions": [], "rules": pf.get("rules")}         # no position: the verdict is the one for buying
    pub = etf.public() or {}
    erows = {r["isin"]: r for r in pub.get("rows") or []}
    stocks_out = [p["ticker"] for p in positions if p.get("ticker") and p["kind"] == "Azione" and p["ticker"] not in rows]
    funds = [p["ticker"] for p in positions if p.get("ticker") and p["kind"] in ("ETF", "ETC")]
    extra = pillars.extra(stocks_out, funds)
    fx = pf.get("fx") or cached(("fx",), 900, eurusd)
    eur = etf_buy.eur
    out = {}
    for p in positions:
        tk = p.get("ticker")
        m = {"verdict": None, "levels": None, "money": None, "trendBase": None, "earningsTs": None, "source": None}
        try:
            if p["kind"] == "Azione" and tk in rows:
                d = stock_decision(tk, pf=stub, details=False)
                if d:
                    _from_decision(m, d)
                    m["source"] = "Decisione (Nasdaq-100)"
                m["earningsTs"] = rows[tk].get("earningsTs")
            elif p["kind"] == "Azione" and tk in extra:
                x = extra[tk]
                df = pillars.frame(x)
                ta = technical.levels(df)
                srow = series_stats(df, None) if df is not None else None
                info = x.get("info") or {}
                m["earningsTs"] = _future_ts(info.get("earningsTimestamp"), info.get("earningsTimestampStart"))
                if ta and srow:
                    ta.update(patterns=[], groups=[])
                    row = {**srow, "ticker": tk, "earningsTs": m["earningsTs"], "weight": 0, "sector": p.get("sector")}
                    label, _ = pillars.extra_valuation(x)
                    d = decision.decide(tk, row, info, {"label": label} if label else None, analysts.analyst_summary(x.get("a")) or None,
                                        ta, patterns_test(), macro_calendar.upcoming(7)["events"], stub, fx)
                    _from_decision(m, d)
                    m["levelPrice"] = srow.get("price")
                    m["source"] = "Decisione, stesse regole sui prezzi del titolo (fuori dal Nasdaq-100)"
            elif p["kind"] in ("ETF", "ETC"):
                df = pillars.frame(extra.get(tk))
                lv = etf.plan_levels(df) if df is not None else None
                c = df["Close"].dropna() if df is not None else None
                s50 = float(c.iloc[-50:].mean()) if c is not None and len(c) >= 50 else None
                s200 = float(c.iloc[-200:].mean()) if c is not None and len(c) >= 200 else None
                price = p.get("price")
                if price and s50 and s200:
                    m["trendBase"] = price > s200 and s50 > s200
                    m["trendWord"] = etf.trend_word(price, s50, s200)
                if lv and c is not None and len(c):
                    m["levels"], m["money"], m["levelPrice"] = lv, eur, float(c.iloc[-1])
                r = erows.get(p["isin"])
                if r:
                    b = etf_buy.decide(r, None)["market"]
                    m.update(verdict=b["verdict"], by=b["by"], why=[b["why"]], label=b["verdict"], source="«Ha senso comprare?», solo mercato")
                elif c is not None:
                    row = {"trend": m.get("trendWord"), "late": etf.late_risk(c), "leverage": p.get("leverage") or 1}
                    cks = [k for k in etf_buy.checks(row, None) if k["id"] not in ("E4", "A2")]
                    v, by, why = etf_buy.verdict(cks, personal=False)
                    m.update(verdict=v, by=by, why=[why], label=v, skipped=["E4 patrimonio", "A2 costo"],
                             source="«Ha senso comprare?», solo mercato, sui prezzi del fondo (fuori dall'elenco ETF)")
        except Exception:
            log.exception("market view failed for %s", tk)
        out[p["isin"]] = m
    return out


def _from_decision(m, d):
    """Verdict, long-term trend and stop levels from a "Decisione" sheet (decision.decide)."""
    b = d.get("buyVerdict") or {}
    lv = (d.get("timing") or {}).get("levels") or {}
    m.update(verdict=b.get("category"), label=b.get("label"), why=b.get("why"), by=b.get("decidedBy") or b.get("by"))
    price, s50, s200 = d.get("price"), lv.get("sma50"), lv.get("sma200")
    if price and s50 and s200:
        m["trendBase"] = price > s200 and s50 > s200
    if lv.get("atr") and lv.get("low") and price:
        m["levels"], m["levelPrice"] = {"atr": lv["atr"], "sma50": s50, "low": lv["low"]}, price
        import decision
        m["money"] = decision.usd


def add_pillars(pf, rows, tickers):
    """The "Pagella del titolo" of every position (pillars.py), with the data the dashboard already has; changes
    true <-> false go in the log (portafoglio/pagella.json)."""
    import analysts
    import pillars
    import risk
    positions = pf.get("positions") or []
    if not positions:
        return {}
    with store.lock:
        anl, vals = dict(store.analysts), dict(store.valuations)
    extra = pillars.read()["data"]
    sma = risk.sma200()
    closes = risk.history(tickers) if tickers else None
    logs, updates = pillars.load_log(), {}
    for p in positions:
        tk = p.get("ticker")
        d = {"sma200": sma.get(tk)}
        if p["kind"] in ("ETF", "ETC"):
            d["corr"], d["weeks"] = pillars.fund_correlation(pf, p, closes)
        elif tk in rows:
            v = vals.get(tk) or {}
            d.update(years=(anl.get(tk) or {}).get("years"), epsRev90=analysts.analyst_summary(anl.get(tk)).get("epsRev90"),
                     rec=rows[tk].get("rec"), valLabel=v.get("label"))
        elif tk in extra and extra[tk].get("row"):
            x = extra[tk]
            d.update(years=(x.get("a") or {}).get("years"), epsRev90=analysts.analyst_summary(x.get("a")).get("epsRev90"),
                     rec=x["row"].get("rec"))
            d["valLabel"], d["valWhy"] = pillars.extra_valuation(x)
        ev = pillars.evaluate(p, d)
        prev = logs.get(p["isin"]) or {}
        e, last = pillars.changes(ev, prev.get("last"))
        if p.get("live"):                                        # the old price of the Fineco file never goes in the log
            updates[p["isin"]] = (e, last)
        else:
            e, last = [], prev.get("last") or {}
        ev["last"] = last                                        # the day each check took its state (rule T1)
        ev["log"] = ((prev.get("log") or []) + e)[-12:][::-1]   # newest first
        p["pillars"] = ev
    pillars.record(updates)
    return {p["isin"]: p["pillars"] for p in positions}


@app.route("/api/portfolio")
def api_portfolio():
    """My positions from the newest export in portafoglio/."""
    return app.response_class(json.dumps(portfolio_view(), default=clean), mimetype="application/json")


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


LOCAL_HOSTS = ("localhost", "127.0.0.1")


@app.before_request
def only_local_host():
    """Phase 7C: every answer only to a request addressed to localhost / 127.0.0.1. Against DNS rebinding: a site whose
    name is made to point to 127.0.0.1 would otherwise read the GET answers (e.g. /api/portfolio) as its own; its
    requests carry its own name in the Host header and are refused here."""
    if (request.host or "").rsplit(":", 1)[0] not in LOCAL_HOSTS:
        return jsonify(error="solo da http://localhost o http://127.0.0.1 su questo Mac"), 403


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


@app.route("/api/etf/catalog")
def api_etf_catalog():
    """Catalogo ETF UCITS (phase 6A, etf_catalog.py): compact rows, filters and coverage. Public data only, read
    from etf_catalog/ (rebuilt by hand with etf_catalog_build.py); never touches the portfolio."""
    import etf_catalog
    data = etf_catalog.load()
    if not data:
        return jsonify(status="missing", error="Catalogo non ancora costruito: .venv/bin/python etf_catalog_build.py")
    a = request.args
    filters = {k: a.get(k) for k in ("assetClass", "family", "issuer", "distribution", "replication", "hedged") if a.get(k)}
    rows = etf_catalog.search(data, a.get("q", ""), filters)
    excluded = [dict(etf_catalog.row(e), reason=e.get("exclusionReason")) for e in data["excluded"].values()]
    return app.response_class(json.dumps({"status": "ok", "rows": rows, "facets": etf_catalog.facets(data), "summary": etf_catalog.summary(data),
                                          "excluded": excluded, "notes": data["notes"],
                                          "families": {r["family"]: r["familyLabel"] for r in etf_catalog.search(data, "")}},
                                         default=clean), mimetype="application/json")


@app.route("/api/etf/catalog/<key>")
def api_etf_catalog_item(key):
    """One catalogue entry (by ISIN or ticker) with its listings, exposure, sources, risks and similar ETFs."""
    import etf_catalog
    import etf_comparison
    data = etf_catalog.load()
    e = etf_catalog.find(data, key) or (data or {}).get("excluded", {}).get(key.upper()) if data else None
    if not e:
        return jsonify(error="ETF non trovato nel catalogo"), 404
    similar = []
    for other in data["items"].values():
        if other["isin"] != e["isin"]:
            lv, why = etf_comparison.pair_level(e, other)
            if lv <= 3:
                similar.append({"isin": other["isin"], "name": etf_catalog.val(other["identity"].get("name")), "level": lv,
                                "label": etf_comparison.LEVELS[lv], "reasons": why, "tickers": etf_catalog.tickers(other)})
    similar.sort(key=lambda s: (s["level"], s["name"] or ""))
    used = set()

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("src"), str):
                used.add(x["src"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(e)
    out = dict(e, risks=etf_comparison.risks(e), similar=similar[:12],
               sources={s: data["sources"].get(s) for s in sorted(used) if data["sources"].get(s)}, disclaimer=etf_comparison.DISCLAIMER)
    return app.response_class(json.dumps(out, default=clean), mimetype="application/json")


@app.route("/api/etf/compare")
def api_etf_compare():
    """Comparison of 2-4 ETFs from the catalogue (etf_comparison.py): separate dimensions, no winner, no score."""
    import etf_catalog
    import etf_comparison
    keys = [k for k in (request.args.get("isins") or "").split(",") if k.strip()]
    out = etf_comparison.compare(etf_catalog.load(), keys)
    if out.get("error"):
        return jsonify(out), 400
    return app.response_class(json.dumps(out, default=clean), mimetype="application/json")


# ---------------------------------------------------------------- phase 6B: scanner of the ETF exposures

_eopp = {"key": None, "data": {}}


def etf_scan(mode="lungo"):
    """Scan of the ETF exposures (etf_opportunity.py) from data already on disk (catalog + cache/etf_prices.pkl): no
    download, cached in memory until the prices, the catalog or the diary change. None without prices."""
    import etf_catalog
    import etf_opportunity as eo
    import etf_opportunity_diary as ed
    import etf_prices
    prices, catalog = etf_prices.load(), etf_catalog.load()
    if not prices or not catalog:
        return None
    st = ed.stats()
    key = (prices.get("fetched"), catalog.get("builtAt"), st.get("last"), date.today().isoformat())
    if _eopp["key"] != key:
        _eopp.update(key=key, data={})
    if mode not in _eopp["data"]:
        _eopp["data"][mode] = eo.scan(catalog, prices, mode, previous=ed.previous(), now=datetime.now())
    return _eopp["data"][mode]


def _json(obj, status=200):
    import etf_opportunity_diary as ed
    return app.response_class(json.dumps(ed._clean(obj), default=clean, ensure_ascii=False), status=status, mimetype="application/json")


@app.route("/api/etf/opportunities")
def api_etf_opportunities():
    """Opportunità → ETF (phase 6B): overview, every exposure (compact) and the short selection, for one mode."""
    import etf_opportunity as eo
    import etf_opportunity_diary as ed
    import etf_prices
    mode = request.args.get("mode", "lungo")
    if mode not in eo.MODES:
        return jsonify(error="modo sconosciuto"), 400
    r = etf_scan(mode)
    if r is None:
        return _json({"status": "missing", "prices": etf_prices.status(), "diary": ed.stats(),
                      "error": "Prezzi degli ETF non ancora scaricati: arrivano in background dopo la chiusura di Borsa Italiana "
                               "(oppure `.venv/bin/python etf_prices.py aggiorna`)."})
    return _json(dict(eo.page(r), status="ok", prices=etf_prices.status(), diary=ed.stats()))


@app.route("/api/diaries/status")
def api_diaries_status():
    """Phase 6C: read-only state of the four diaries (diaries_status.py): official and excluded records, last session,
    missing sessions, next update. Opens the database only in read-only mode."""
    import diaries_status
    return _json(diaries_status.status())


@app.route("/api/etf/opportunities/diary")
def api_etf_opportunities_diary():
    import etf_opportunity_diary as ed
    return _json(ed.stats())


@app.route("/api/etf/opportunities/<key>")
def api_etf_opportunity(key):
    """One exposure in full: measures, conditions, trends, risks and its products (links to the 6A comparator)."""
    import etf_opportunity as eo
    mode = request.args.get("mode", "lungo")
    if mode not in eo.MODES:
        return jsonify(error="modo sconosciuto"), 400
    r = etf_scan(mode)
    o = eo.detail(r, key) if r else None
    if not o:
        return jsonify(error="esposizione non trovata"), 404
    return _json(dict(o, disclaimer=eo.DISCLAIMER, params=eo.P, version=eo.VERSION, mode=mode))


def refresh_etf_prices():
    """Background download of the ETF closes once after each close of Borsa Italiana (etf_prices.refresh_async):
    never at page opening, never blocks the loop."""
    try:
        import etf_catalog
        import etf_prices
        return etf_prices.refresh_async(download, etf_catalog.load)
    except Exception:
        log.exception("ETF prices refresh not started")
        return False


def save_etf_scan_diary(source="dashboard"):
    """Records the scan of the last closed Borsa Italiana session (etf_opportunity_diary.py), both modes, once per
    session and model version, only with closes downloaded after the close. Never stops the loop."""
    try:
        import etf_catalog
        import etf_opportunity as eo
        import etf_opportunity_diary as ed
        import etf_prices
        prices = etf_prices.load()
        if not prices or not prices.get("closes"):
            return "scanner ETF: prezzi non ancora in cache"
        bench = prices["closes"].get(eo.B_WORLD_ALL)
        if bench is None or not len(bench):
            return "scanner ETF: manca la serie di riferimento"
        session = str(bench.index[-1].date())
        run = ed.run_of(session, eo.VERSION)
        if run:
            if run["class"] != "produzione":
                return (f"scanner ETF: seduta {session} già occupata da una registrazione «{run['source']}» (esclusa dalle "
                        "statistiche): non si registra due volte, il diario ufficiale riparte dalla seduta successiva")
            return "scanner ETF: seduta già registrata"
        other = ed.runs_of_session(session)
        if other:                                   # E1 → E2 (5 Nov 2026): a new version starts from the next session
            o = other[0]
            return (f"scanner ETF: seduta {session} già registrata con il modello {o['version']} (origine «{o['source']}»): "
                    f"il modello {eo.VERSION} si registra dalla seduta successiva")
        why = ed.check_final(session, prices.get("fetched"))
        if why:
            return "scanner ETF: " + why
        catalog = etf_catalog.load()
        prev = ed.previous(before=session)
        res = {m: eo.scan(catalog, prices, m, as_of=session, previous=prev, now=datetime.now()) for m in eo.MODES}
        saved, msg = ed.record(res, session, datetime.now(ROME_TZ).isoformat(timespec="seconds"), source)
        if saved:
            log.info("ETF scan diary: %s for %s (%s)", msg, session, source)
        return "scanner ETF: " + msg
    except Exception:
        log.exception("ETF scan diary not saved")
        return "scanner ETF: errore, vedi cache/server.log"


ROME_TZ = ZoneInfo("Europe/Rome")


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


def save_pos_diary():
    """The same evening as the NYSE close (at least 20 minutes after it): the level of each of my positions in
    portafoglio/diario_posizioni/ (pos_diary.py), once per session and never rewritten. Not the next morning: the
    prices would no longer be those of the session. Waits for the 2 years of prices (200-day average)."""
    try:
        import pos_diary
        import risk
        day = last_closed_session()
        if day != datetime.now(ET).date().isoformat() or pos_diary.exists(day):
            return
        pf = portfolio_view()
        if pf.get("resolving") or not pf.get("positions") or not pf.get("quotesAt"):
            return                                          # wait for today's quotes, never the prices of the Fineco file
        if any(p.get("ticker") for p in pf["positions"]) and not risk.sma200():
            log.info("positions diary: prices for the 200-day average not ready yet, retry later")
            return
        if pos_diary.save(day, pf["positions"]):
            log.info("positions diary saved for %s", day)
    except Exception:
        log.exception("positions diary failed")


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


# ------------------------------------------------------------ phase 7B: compatibility with the portfolio (portfolio_fit.py)
# Personal data are used ONLY after an explicit action in the page (POST with "consent": true, from this Mac): opening the
# Decision Desk or the Compatibilità page never reads the portfolio. Source "mio" = the snapshot portfolio.py already keeps in
# memory for the Portafoglio tab (no new file read, no copy saved); source "esempio" = a made-up portfolio. Nothing is
# written, nothing is downloaded, no position is logged or sent outside.
FIT_KINDS = {"azione": "azione", "azioni": "azione", "etf": "etf", "etc": "etc", "etn": "etn"}


def fit_stock_meta(snap, infos):
    """Public data of the Nasdaq-100 stocks (sector, country, listing currency) for the composition of a stock."""
    return {r["ticker"]: {"sector": r.get("sector"), "country": (infos.get(r["ticker"]) or {}).get("country"), "currency": "USD",
                          "name": r.get("name")} for r in (snap or {}).get("stocks", [])}


def fit_book(source, snap, infos):
    """(book, reason): the positions to analyse. "mio" reads only the in-memory snapshot of portfolio.py."""
    import portfolio_fit as pfit
    as_of = today_et()
    if source == "esempio":
        return pfit.demo_book(as_of), None
    pf = portfolio.snapshot(snap, infos)
    if not pf.get("file"):
        return None, "nessun export del portafoglio in portafoglio/: il Decision Desk resta utilizzabile senza questa analisi"
    if pf.get("error"):
        return None, "export del portafoglio non leggibile: controlla la scheda Portafoglio"
    if pf.get("resolving"):
        return None, "posizioni ancora in caricamento: riprova tra poco"
    if not pf.get("positions"):
        return None, "portafoglio vuoto"
    quoted = datetime.fromtimestamp(pf["quotesAt"], ET).date().isoformat() if pf.get("quotesAt") else None
    filed = datetime.fromtimestamp(pf["fileTime"], ET).date().isoformat() if pf.get("fileTime") else None
    out = []
    for i, p in enumerate(pf["positions"], 1):
        kind = (p.get("kind") or "").strip().lower()
        raw = {"id": f"p{i}", "name": p.get("name"), "isin": p.get("isin"), "ticker": p.get("ticker"),
               "kind": FIT_KINDS.get(kind, "azione" if kind.startswith("azion") else kind), "value": p.get("value"),
               "valueCurrency": "EUR", "priceDate": quoted if p.get("live") else filed,
               "conversionNote": (f"valore in euro di portfolio.py ({'prezzo e cambio di Yahoo' if p.get('live') else 'prezzo e cambio del file Fineco'})"
                                  if (p.get("currency") or "EUR").upper() != "EUR" else None)}
        if kind.startswith("azion"):
            for k in ("sector", "country"):
                if p.get(k) and p[k] not in ("Non disponibile", "Non classificato", portfolio.LOOK_THROUGH_NDX):
                    raw[k] = p[k]
            raw["currency"] = (p.get("currency") or "").upper() or None
        out.append(raw)
    fx = {"USD": {"rate": pf["fx"], "date": quoted, "source": "Yahoo EURUSD=X (quotazioni del portafoglio)"}} if pf.get("fx") else {}
    return {"asOf": as_of, "fx": fx, "positions": out, "source": "mio"}, None


def fit_series(norm, daily):
    """EUR price series already in memory or in the public cache (never a download): ETFs from cache/etf_prices.pkl,
    stocks only when the 2-year EUR/USD series of the Rischio page is already loaded today."""
    import etf_prices
    import risk
    closes = (etf_prices.load() or {}).get("closes") or {}
    with risk._lock:
        fresh = risk._hist["day"] == datetime.now().date()
        usd = (risk._hist["closes"] or {}).get(portfolio.FX) if fresh else None
    out = {}
    for x in norm["positions"]:
        if x["isin"] and x["isin"] in closes:
            out[x["id"]] = closes[x["isin"]]
        elif x["class"] == "azione" and x.get("ticker") in daily and usd is not None:
            c = daily[x["ticker"]]["Close"].dropna()
            c.index = c.index.tz_localize(None) if getattr(c.index, "tz", None) else c.index
            u = usd.copy()
            u.index = u.index.tz_localize(None) if getattr(u.index, "tz", None) else u.index
            out[x["id"]] = (c / u.reindex(c.index, method="ffill")).dropna()
    return out


def fit_candidate(ref, snap, catalog):
    """A candidate from a Decision Desk row id ("azione:ADBE:lungo", "etf:sanita_mondo:lungo"), a ticker or an ISIN,
    with its D2 state (read only, never changed)."""
    import investment_decision_engine as de
    d2 = None
    try:
        data = decisions()
        row = de.detail(data, ref) if data and isinstance(ref, str) else None
    except Exception:
        row = None
    if row:
        d2 = {"state": row["state"], "rule": row["rule"], "version": data["version"], "horizon": row["horizonLabel"]}
    kind, key = (ref.split(":")[:2] + [None])[:2] if isinstance(ref, str) and ":" in ref else (None, ref)
    names = {r["ticker"]: r.get("name") for r in (snap or {}).get("stocks", [])}
    items = (catalog or {}).get("items") or {}
    if kind == "azione" or (kind is None and key in names):
        return {"kind": "azione", "ticker": key, "name": names.get(key) or key}, d2
    if kind == "etf":
        isin = (row or {}).get("code") if row and row.get("code") in items else next(
            (i for i, e in items.items() if (e.get("classification") or {}).get("exposure") == key), None)
        return ({"kind": "etf", "isin": isin} if isin else None), d2
    if key in items:
        return {"kind": "etf", "isin": key}, d2
    return None, d2


def fit_choices(snap, catalog):
    stocks = [{"ref": r["ticker"], "label": f"{r['ticker']} · {r.get('name') or ''}"} for r in sorted((snap or {}).get("stocks", []), key=lambda r: r["ticker"])]
    etfs = [{"ref": i, "label": f"{(e['identity'].get('name') or {}).get('v') or i} · {i}"} for i, e in sorted(((catalog or {}).get("items") or {}).items(),
            key=lambda kv: ((kv[1]['identity'].get('name') or {}).get('v') or ""))]
    return stocks + etfs


@app.route("/api/portfolio/fit", methods=["POST"])
def api_portfolio_fit():
    """Compatibilità con il portafoglio (phase 7B). Only after an explicit action in the page; read only; personal data
    never cached, logged or sent anywhere."""
    import etf_catalog
    import portfolio_fit as pfit
    if not local_request():
        return jsonify({"error": "solo dalla dashboard su questo Mac"}), 403
    body = request.get_json(silent=True) or {}
    if body.get("consent") is not True:
        return jsonify({"error": "serve un'azione esplicita: «Analizza compatibilità con il mio portafoglio»"}), 400
    source = body.get("source") if body.get("source") in ("mio", "esempio") else None
    if not source:
        return jsonify({"error": "fonte non valida (mio o esempio)"}), 400
    try:
        with store.lock:
            snap, infos, daily = store.snapshot, dict(store.infos), store.daily
        catalog = etf_catalog.load()
        out = {"version": pfit.VERSION, "source": source,
               "sourceLabel": "il mio portafoglio (solo in memoria, sola lettura)" if source == "mio" else
                              "portafoglio di esempio (valori inventati, nessun dato personale)",
               "disclaimer": pfit.DISCLAIMER, "choices": fit_choices(snap, catalog)}
        book, why = fit_book(source, snap, infos)
        if book is None:
            resp = _json(dict(out, available=False, why=why))
        else:
            meta = fit_stock_meta(snap, infos)
            limits = body.get("limits") if isinstance(body.get("limits"), dict) else None
            norm = pfit.normalize(book, catalog)
            an = pfit.analyse(norm, meta, limits, fit_series(norm, daily))
            out.update(available=True, analysis=an,
                       positions=[{"id": p["id"], "name": p["name"]} for p in an["positions"]])
            if body.get("candidate"):
                cand, d2 = fit_candidate(body["candidate"], snap, catalog)
                if cand is None:
                    out["compatError"] = "candidato non riconosciuto (né titolo del Nasdaq-100 né ETF del catalogo)"
                else:
                    out["compat"] = pfit.compatibility(an, norm, cand, catalog, meta, d2)
                    w = body.get("whatif")
                    if isinstance(w, dict) and w.get("amount") is not None:
                        try:
                            amount = float(w["amount"])
                        except (TypeError, ValueError):
                            amount = None
                        out["whatif"] = pfit.simulate(book, catalog, cand, amount, w.get("currency") or "EUR",
                                                      w.get("funding") or "nuova", w.get("reduce"), meta, limits) if amount else \
                            {"ok": False, "why": "importo ipotetico non valido"}
            resp = _json(out)
    except Exception as e:                      # never the content in the log: only the kind of error
        log.error("portfolio fit failed (%s)", type(e).__name__)
        resp = _json({"error": "analisi di compatibilità non calcolabile"}, 500)
    resp.headers["Cache-Control"] = "no-store"
    return resp


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
    only; the Host/Origin check and the custom header also stop another site open in the browser from posting here
    (the custom header forces a CORS preflight that this server never approves). Phase 7C: the Origin, when the
    browser sends it, must be exactly the dashboard's own (same host and port), not any local port."""
    host = (request.host or "").rsplit(":", 1)[0]
    origin = request.headers.get("Origin")
    return (request.remote_addr in ("127.0.0.1", "::1") and host in LOCAL_HOSTS
            and (origin is None or origin == f"http://{request.host}")
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


_opps = {"key": None, "data": None}
OPPS_TTL_S = 600     # the valuation follows the live price: rankings rebuilt at most every 10 minutes (or with new data)


def opportunities(keep_all=False, now=None):
    """Both rankings of the "Opportunità" tab (opportunity_scanner.py) from the data already in memory: no download.
    Prices on closed sessions only; live price and time are added for display. None while the first data load runs.
    keep_all=True (opportunity diary): every stock with its figures, computed fresh and never cached."""
    import opportunity_scanner
    import technical  # local import: technical imports this module
    with store.lock:
        snap, daily, ta = store.snapshot, store.daily, store.ta
    if snap is None or not daily:
        return None
    key = (id(daily), id(store.analysts), id(store.news_all), id(store.infos), int(time.time() // OPPS_TTL_S))
    if _opps["key"] == key and not keep_all:
        return _opps["data"]
    now = now or datetime.now(ET)
    rows = {r["ticker"]: r for r in snap["stocks"]}
    universe = [{"ticker": t, "name": r.get("name"), "sector": r.get("sector")} for t, r in rows.items()]
    closed = technical.closed_sessions({t: daily[t] for t in [*rows, SIGNAL_BENCH] if t in daily}, now)
    quote_time = snap.get("lastQuote") or snap.get("asOf")
    fund = {}
    for t, r in rows.items():
        info, sig = store.infos.get(t) or {}, store.signals.get(t) or {}
        nws = next((c for c in sig.get("components") or [] if c["key"] == "news" and c["used"]), None)
        fund[t] = {"years": (store.analysts.get(t) or {}).get("years"), "epsRev90": r.get("epsRev90"), "epsRev30": r.get("epsRev30"),
                   "up30": r.get("up30"), "down30": r.get("down30"), "rec": r.get("rec"), "valLabel": r.get("valLabel"),
                   "valRatio": r.get("valRatio"), "valNotes": (store.valuations.get(t) or {}).get("notes"),
                   "earningsTs": r.get("earningsTs"), "epsGrowth": clean(info.get("earningsGrowth")), "margin": r.get("margin"),
                   "news": {"score": nws["score"], "reasons": nws["reasons"]} if nws else None}
    ptest = patterns_test() or {}
    favorable = set(ptest.get("favorable") or [])
    failed = {p["key"]: p["name"] for p in ptest.get("patterns", []) if p["key"] not in favorable}
    data = opportunity_scanner.scan(
        universe, closed, closed.get(SIGNAL_BENCH), fund,
        patterns={t: [p["key"] for p in (ta.get(t) or {}).get("patterns", [])] for t in rows}, failed=failed,
        quotes={t: {"price": r.get("price"), "time": quote_time} for t, r in rows.items()}, today=now.date(), keep_all=keep_all)
    data["generated"] = now.isoformat(timespec="seconds")
    data["newsReady"] = store.news_all is not None
    data["analystsReady"] = bool(store.analysts)
    if not keep_all:
        _opps.update(key=key, data=data)
    return data


_inv = {"key": None, "data": None}
INV_REFRESH_S = 30 * 60      # how often the worker checks whether some company's statements need a new download
_inv_check = {"at": 0.0}


def _inv_invalidate():
    _inv.update(key=None, data=None)


def investment_analysis(now=None, fresh=False):
    """Fundamental analysis engine (investment_engine.py, phase 5A) on the data already on disk / in memory: no download.
    Statements from cache/fundamentals.json, today's Yahoo info, analysts, trend on closed sessions, the unchanged
    Pagella (Investimento ranking) only shown next to it. None while the first data load runs or without statements.
    Cached like the rankings (10 minutes, or as soon as one of its inputs changes); fresh=True for the diary."""
    import fundamentals
    import investment_engine as ie
    import opportunity_scanner
    import technical  # local import: technical imports this module
    with store.lock:
        snap, daily = store.snapshot, store.daily
    if snap is None or not daily:
        return None
    try:
        fmtime = os.path.getmtime(fundamentals.CACHE)
    except OSError:
        return None
    key = (id(daily), id(store.analysts), id(store.infos), fmtime, int(time.time() // OPPS_TTL_S))
    if _inv["key"] == key and not fresh:
        return _inv["data"]
    now = now or datetime.now(ET)
    fund = fundamentals.read()
    if not fund.get("data"):
        return None
    rows = {r["ticker"]: r for r in snap["stocks"]}
    universe = [{"ticker": t, "name": r.get("name"), "sector": r.get("sector")} for t, r in rows.items()]
    closed = technical.closed_sessions({t: daily[t] for t in [*rows, SIGNAL_BENCH] if t in daily}, now)
    bench = closed.get(SIGNAL_BENCH)
    bclose = bench["Close"].dropna() if bench is not None else None
    techs = {t: opportunity_scanner.tech(closed.get(t), bclose) for t in rows}
    q252 = float(bclose.iloc[-1] / bclose.iloc[-253] - 1) * 100 if bclose is not None and len(bclose) > 253 else None
    opp = opportunities(keep_all=True, now=now) or {}
    pagella = {e["ticker"]: {"ok": e["ok"], "n": e["n"], "status": e["status"], "rank": e.get("rank"),
                             "conditions": [{"id": c["id"], "name": c["name"], "state": c["state"]} for c in e["conditions"]]}
               for e in (opp.get("invest") or {}).get("all") or []}
    import analysts
    infos_file = read_cache("infos.json", 400 * 86400) or {}
    data = ie.analyze_all(universe, fund, store.infos, store.analysts, techs, now, q252=q252, pagella=pagella,
                          infos_date=infos_file.get("date"), analysts_date=(analysts.read_cache() or {}).get("date"))
    if not fresh:
        _inv.update(key=key, data=data)
    return data


def refresh_fundamentals(tickers, force=False):
    """Background download of the statements that need it (fundamentals.py rules), at most every INV_REFRESH_S."""
    import fundamentals
    if not force and time.time() - _inv_check["at"] < INV_REFRESH_S:
        return False
    _inv_check["at"] = time.time()
    return fundamentals.refresh_async(tickers, on_done=_inv_invalidate)


def save_investment_diary(day, now, source):
    """Judgements of the fundamental engine for a session the opportunity diary has already recorded (same file, new
    tables: investment_diary.py). Never the first record of a diary, never twice; a failure never stops the loop."""
    try:
        import investment_diary as invd
        import investment_engine as ie
        import opportunity_diary as od
        import opportunity_scanner
        if not od.exists(day, opportunity_scanner.MODEL_VERSION):
            return "analisi fondamentale: diario delle opportunità non registrato per questa seduta"
        if invd.exists(day, ie.VERSION):
            return "analisi fondamentale già registrata"
        if _inv_check.get("diaryDay") == day and time.time() - _inv_check.get("diaryAt", 0) < INV_REFRESH_S:
            return "analisi fondamentale: nuovo tentativo tra poco"
        _inv_check.update(diaryDay=day, diaryAt=time.time())
        data = investment_analysis(now=now, fresh=True)
        if not data:
            return "analisi fondamentale non calcolabile (bilanci non ancora scaricati)"
        saved, why = invd.record(data, day, now.isoformat(timespec="seconds"), source, opportunity_scanner.MODEL_VERSION)
        if saved:
            log.info("investment diary: %s for %s (%s)", why, day, source)
        return "analisi fondamentale: " + why
    except Exception:
        log.exception("investment diary not saved")
        return "analisi fondamentale: errore, vedi cache/server.log"


_val = {"key": None, "data": None}


def valuation_analysis(now=None, fresh=False, closing=False):
    """Valuation and scenarios (investment_valuation.py, phase 5B) on top of the phase 5A analysis, from the data already
    on disk / in memory: no download. Page: current quote with its time; closing=True (diary): the closing prices of
    the last closed session. Cached together with the 5A analysis (same key)."""
    import fundamentals
    import investment_valuation as iv
    inv = investment_analysis(now=now, fresh=fresh)
    if not inv:
        return None
    key = (id(inv), int(time.time() // OPPS_TTL_S))
    if _val["key"] == key and not fresh and not closing:
        return _val["data"]
    now = now or datetime.now(ET)
    with store.lock:
        snap = store.snapshot
    closes = {x["ticker"]: {"close": x["price"], "date": x["priceDate"]} for x in inv["items"]}
    quotes = None
    if not closing and snap:
        qt = snap.get("lastQuote") or snap.get("asOf")
        quotes = {r["ticker"]: {"price": r.get("price"), "time": qt} for r in snap["stocks"]}
    data = iv.analyze_all(inv, fundamentals.read(), store.infos, store.analysts, now, quotes=quotes, closes=closes)
    if not fresh and not closing:
        _val.update(key=key, data=data)
    return data


def save_valuation_diary(day, now, source):
    """Valuations of a session the opportunity diary has already recorded (valuation_diary.py), with the closing
    prices of that session. Never the first record of a diary, never twice; a failure never stops the loop."""
    try:
        import investment_valuation as iv
        import opportunity_diary as od
        import opportunity_scanner
        import valuation_diary as vd
        if not od.exists(day, opportunity_scanner.MODEL_VERSION):
            return "valutazioni: diario delle opportunità non registrato per questa seduta"
        if vd.exists(day, iv.VERSION):
            return "valutazioni già registrate"
        if _val.get("diaryDay") == day and time.time() - _val.get("diaryAt", 0) < INV_REFRESH_S:
            return "valutazioni: nuovo tentativo tra poco"
        _val.update(diaryDay=day, diaryAt=time.time())
        data = valuation_analysis(now=now, fresh=True, closing=True)
        if not data:
            return "valutazioni non calcolabili (bilanci non ancora scaricati)"
        saved, why = vd.record(data, day, now.isoformat(timespec="seconds"), source, opportunity_scanner.MODEL_VERSION)
        if saved:
            log.info("valuation diary: %s for %s (%s)", why, day, source)
        return "valutazioni: " + why
    except Exception:
        log.exception("valuation diary not saved")
        return "valutazioni: errore, vedi cache/server.log"


_acc = {"mtime": None, "map": {}}


def accounts_currency(ticker):
    """Currency of the company's statements (fundamentals cache), so the page never labels CNY or EUR figures with "$".
    None when not known."""
    import fundamentals
    try:
        mt = os.path.getmtime(fundamentals.CACHE)
    except OSError:
        return None
    if _acc["mtime"] != mt:
        _acc.update(mtime=mt, map={t: (e.get("info") or {}).get("financialCurrency")
                                   for t, e in (fundamentals.read().get("data") or {}).items()})
    return _acc["map"].get(ticker)


_od = {"measured": None}     # last session for which the matured results were measured (once per new closed session)


def save_opportunity_diary(source="dashboard"):
    """Opportunity diary (opportunity_diary.py, phase O2): after the close, both rankings of the last closed session for
    every stock, once per session and model version; then the results that have matured. Public market data only
    (data/opportunita.sqlite3), never portafoglio/. Any failure is logged and never stops the price refresh.
    Returns a short text of what happened (for the manual command and the log)."""
    try:
        import diaries_status
        import opportunity_diary as od
        import opportunity_scanner
        import technical  # local import: technical imports this module
        now = datetime.now(ET)
        if market_status(now) in ("open", "pre"):
            return "mercato aperto o pre-apertura: si registra dopo la chiusura"
        day = last_closed_session(now)
        with store.lock:
            bench, last_daily, daily = store.daily.get(SIGNAL_BENCH), store.last_daily, store.daily
        if bench is None or not len(bench):
            return "storico dei prezzi non ancora caricato"
        msg = "seduta già registrata"
        until = diaries_status.recordable_until(day)
        if until is not None and now >= until:
            # Phase 7C: between the next close and close + 20 minutes `day` is still the last closed session, but its
            # window ended at the pre-market: no diary of the chain records it any more (on 5 Nov 2026 16:00 ET the
            # decisions of 4 Nov had been recorded with the statements of 5 Nov). Matured results are still measured.
            msg = (f"seduta {day}: finestra di registrazione chiusa alle {until:%H:%M} di New York del {until.date()}: "
                   "nessuna registrazione retroattiva")
        elif not od.exists(day, opportunity_scanner.MODEL_VERSION):
            last_bar = str(bench["Close"].dropna().index[-1].date())
            if last_bar != day:
                return f"lo storico dei prezzi arriva al {last_bar}, non ancora alla seduta {day}: nuovo tentativo più tardi"
            if not last_daily or datetime.fromtimestamp(last_daily, ET) < od.session_closed_at(day):
                return f"storico dei prezzi aggiornato prima della chiusura del {day}: nuovo tentativo dopo il prossimo aggiornamento"
            data = opportunities(keep_all=True, now=now)
            if not data:
                return "classifiche non calcolabili"
            saved, msg = od.record(data, day, now.isoformat(timespec="seconds"), source)
            if saved:
                log.info("opportunity diary: %s for %s (%s)", msg, day, source)
        if until is None or now < until:
            msg += "; " + save_investment_diary(day, now, source)
            msg += "; " + save_valuation_diary(day, now, source)
            msg += "; " + save_decision_diary(day, now, source)
        if _od["measured"] != day:
            closed = technical.closed_sessions(daily, now)
            new = od.update_outcomes({t: od.as_map(df["Close"]) for t, df in closed.items() if t != SIGNAL_BENCH},
                                     od.as_map(closed[SIGNAL_BENCH]["Close"]) if SIGNAL_BENCH in closed else {}, now)
            _od["measured"] = day
            msg += f"; risultati maturati misurati: {new} nuovi"
        return msg
    except Exception:
        log.exception("opportunity diary not saved")
        return "errore: vedi cache/server.log"


_alerts_check = {"at": None, "msg": None}


def save_alerts(source="dashboard"):
    """Phase 8A: one check of the alerts (alert_engine.py) AFTER the diaries, only from the authorized writers (server
    loop, evening job). Never on a partial chain: while the last NYSE session is still recordable and one of its four
    diaries is missing, it waits. Public data only (diaries, ETF catalog, state of the diaries): never the portfolio.
    A failure is logged as an operational problem, never turned into a market change. Returns a short text."""
    try:
        import alert_engine as ae
        import diaries_status
        import etf_catalog
        import opportunity_diary as od
        now = datetime.now(ET)
        if not os.path.exists(od.DB):
            msg = "alert: diari non ancora avviati"
        else:
            st = diaries_status.status(now)
            by = {d["key"]: d for d in st["diaries"]}
            last = (by["opportunity"].get("last") or {}).get("session")
            until = diaries_status.recordable_until(last) if last else None
            waiting = [k for k in ("investment", "valuation", "decision") if last and (by[k].get("last") or {}).get("session") != last]
            if waiting and until is not None and now < until:
                msg = f"alert: in attesa della catena della seduta {last} ({', '.join(waiting)})"
            else:
                r = ae.generate(now, source, od.DB, catalog=etf_catalog.load(), status=st)
                msg = (f"alert: controllo {r['run']}: {r['alerts']} attivi, {r['new']} nuovi, {r['resolved']} risolti ({r['ms']} ms)"
                       if r["created"] else "alert: " + r["why"])
                if r["created"]:
                    log.info(msg)
    except Exception as e:
        log.exception("alert check failed")
        msg = f"alert: controllo non riuscito ({type(e).__name__}): nessun cambiamento registrato"
    _alerts_check.update(at=datetime.now(ROME_TZ).isoformat(timespec="seconds"), msg=msg)
    return msg


@app.route("/api/alerts")
def api_alerts():
    """Alert e cambiamenti (Phase 8A): read only from the alert registry (mode=ro). Never generates alerts, never writes,
    never downloads, never reads the portfolio."""
    import alert_engine as ae
    import opportunity_diary as od
    out = ae.read(diary_path=od.DB)
    out["lastCheck"] = dict(_alerts_check)
    resp = _json(out)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def brief_feeds():
    """Dates of the updates known to this process (phase 8B): memory and file times only, never a download."""
    out = {"prices": datetime.fromtimestamp(store.last_daily, ET).isoformat(timespec="seconds") if store.last_daily else None,
           "fundamentals": None, "etfPrices": None, "alertCheck": dict(_alerts_check)}
    if not out["prices"]:
        try:
            out["prices"] = datetime.fromtimestamp(os.path.getmtime(DAILY_CACHE), ET).isoformat(timespec="seconds")
        except OSError:
            pass
    try:
        import daily_brief
        out["fundamentals"] = daily_brief.fundamentals_date()
    except Exception:
        pass
    try:
        import etf_prices
        out["etfPrices"] = (etf_prices.load() or {}).get("fetched")
    except Exception:
        pass
    return out


@app.route("/api/brief")
def api_brief():
    """Riepilogo del giorno + stato del sistema (Phase 8B): read only (alert registry, diaries, job registry). Never
    generates alerts, never writes, never downloads, never reads the portfolio; no consent needed."""
    import alert_engine as ae
    import daily_brief
    import diaries_status
    import job_status
    now = datetime.now(ET)
    import opportunity_diary as od
    out = daily_brief.build(now, ae.read(diary_path=od.DB), diaries_status.status(now), job_status.read(), brief_feeds())
    resp = _json(out)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def update_opportunity_diary_offline():
    """The manual command (opportunity_diary.py update): the same save, with the data already in cache/ and no
    download. The private folder is never read: the count of the signal diary is not needed here."""
    import analysts
    import technical
    global diary_days
    authorize_writer("comando manuale")
    counter, diary_days = diary_days, (lambda: 0)          # build() would only count the files of portafoglio/diario
    cons = read_cache("constituents.json", 30 * 86400)
    if not cons:
        return "elenco dei titoli non in cache: apri prima la dashboard"
    store.constituents = [{**r, "sector": SECTOR_IT.get(r["sector"], r["sector"]), "industry": INDUSTRY_IT.get(r["industry"], r["industry"])} for r in cons]
    infos = read_cache("infos.json", 30 * 86400)
    store.infos = infos.get("data", {}) if isinstance(infos, dict) else {}
    store.analysts = analysts.cached_data()
    cached_daily = load_daily_cache()
    if not cached_daily:
        return "storico dei prezzi non in cache: apri prima la dashboard"
    store.daily, store.last_daily = cached_daily
    store.tech = store.technicals(store.daily)
    store.ta = technical.build(store.daily, store.constituents, store.tech)
    try:
        store.build()
    finally:
        diary_days = counter
    return save_opportunity_diary(source="comando manuale")


@app.route("/api/opportunities")
def api_opportunities():
    """The two exploratory rankings of the "Opportunità" tab (screening, never a buy signal)."""
    if store.error:
        return jsonify({"error": store.error}), 500
    try:
        data = opportunities()
    except Exception:
        log.exception("opportunity scan failed")
        return jsonify({"error": "calcolo delle classifiche non riuscito"}), 500
    if data is None:
        return jsonify({"error": "loading"}), 503
    return app.response_class(json.dumps(data, default=clean, allow_nan=False), mimetype="application/json")


@app.route("/api/opportunities/diary")
def api_opportunities_diary():
    """The opportunity diary: what is recorded and the results matured so far (never a validated backtest)."""
    import opportunity_diary
    try:
        return app.response_class(json.dumps(opportunity_diary.stats(), default=clean, allow_nan=False), mimetype="application/json")
    except Exception:
        log.exception("opportunity diary stats failed")
        return jsonify({"error": "diario delle opportunità non leggibile"}), 500


@app.route("/api/investment")
def api_investment():
    """Fundamental analysis engine (phase 5A, experimental): one compact row per company, model, coverage, groups.
    Analytic profiles, never buy/sell signals. Without statements yet: available=false with the reason (the worker
    downloads them in background; nothing is downloaded by this request)."""
    import fundamentals
    import investment_diary
    import investment_engine as ie
    if store.error:
        return jsonify({"error": store.error}), 500
    try:
        data = investment_analysis()
    except Exception:
        log.exception("investment analysis failed")
        return jsonify({"error": "analisi fondamentale non riuscita"}), 500
    try:
        diary = investment_diary.stats()
    except Exception:
        log.exception("investment diary stats failed")
        diary = None
    if data is None:
        why = ("dati di mercato in caricamento" if store.snapshot is None else
               "bilanci non ancora scaricati: il download parte in background (qualche minuto)")
        if store.snapshot is not None and store.constituents:
            refresh_fundamentals([c["ticker"] for c in store.constituents], force=True)
        out = {"available": False, "reason": why, "fundamentals": fundamentals.status(), "diary": diary,
               "model": {"version": ie.VERSION}}
    else:
        out = {"available": True, "model": data["model"], "generated": data["generated"], "coverage": data["coverage"],
               "groups": data["groups"], "fx": data["fx"], "dataDates": data["dataDates"],
               "items": [ie.compact(x) for x in data["items"]], "fundamentals": fundamentals.status(), "diary": diary}
    return app.response_class(json.dumps(out, default=clean, allow_nan=False), mimetype="application/json")


@app.route("/api/investment/<ticker>")
def api_investment_one(ticker):
    """Full analysis of one company (indicators with periods and sources, peers, limits, things to monitor)."""
    try:
        data = investment_analysis()
    except Exception:
        log.exception("investment analysis failed")
        return jsonify({"error": "analisi fondamentale non riuscita"}), 500
    if data is None:
        return jsonify({"error": "analisi non ancora disponibile"}), 503
    item = next((x for x in data["items"] if x["ticker"] == ticker.upper()), None)
    if item is None:
        return jsonify({"error": f"{ticker.upper()} non è nell'universo analizzato"}), 404
    out = {**item, "engineVersion": data["model"]["version"], "generated": data["generated"]}
    return app.response_class(json.dumps(out, default=clean, allow_nan=False), mimetype="application/json")


@app.route("/api/valuation")
def api_valuation():
    """Valuation and scenarios (phase 5B, experimental): one compact row per company, model and parameters. Ranges of
    values conditional on explicit assumptions: never a target price, a buy/sell signal or a probability."""
    import investment_valuation as iv
    import valuation_diary
    if store.error:
        return jsonify({"error": store.error}), 500
    try:
        data = valuation_analysis()
    except Exception:
        log.exception("valuation failed")
        return jsonify({"error": "valutazione non riuscita"}), 500
    try:
        diary = valuation_diary.stats()
    except Exception:
        log.exception("valuation diary stats failed")
        diary = None
    if data is None:
        out = {"available": False, "reason": "analisi fondamentale non ancora disponibile (dati in caricamento o bilanci "
                                             "non ancora scaricati)", "model": {"version": iv.VERSION}, "diary": diary}
    else:
        out = {"available": True, "model": data["model"], "generated": data["generated"], "rates": data["rates"],
               "fx": data["fx"], "counts": data["counts"], "dataDates": data["dataDates"],
               "items": [iv.compact(x) for x in data["items"]], "diary": diary}
    return app.response_class(json.dumps(out, default=clean, allow_nan=False), mimetype="application/json")


@app.route("/api/valuation/<ticker>")
def api_valuation_one(ticker):
    """Full valuation of one company: scenarios with assumptions, sensitivity, implied expectations, data and limits."""
    try:
        data = valuation_analysis()
    except Exception:
        log.exception("valuation failed")
        return jsonify({"error": "valutazione non riuscita"}), 500
    if data is None:
        return jsonify({"error": "valutazione non ancora disponibile"}), 503
    item = next((x for x in data["items"] if x["ticker"] == ticker.upper()), None)
    if item is None:
        return jsonify({"error": f"{ticker.upper()} non è nell'universo analizzato"}), 404
    out = {**item, "modelVersion": data["model"]["version"], "generated": data["generated"],
           "params": data["model"]["params"], "groups": data["model"]["groups"]}
    return app.response_class(json.dumps(out, default=clean, allow_nan=False), mimetype="application/json")


# ---------------------------------------------------------------- Decision Desk (phase 7A)

_dec = {"key": None, "data": None}


def decision_snapshot(now=None, fresh=False, closing=False):
    """The results of the existing engines, as they are, for investment_decision_engine.decide: Trading T1–T5 and
    Pagella (opportunities, keep_all), fundamentals F1, valuation V2, ETF scanner E2 in both modes, the ETF catalog.
    Data already in memory or on disk only: never a download, never the personal portfolio. None while loading."""
    import etf_catalog
    with store.lock:
        snap = store.snapshot
    if snap is None:
        return None
    now = now or datetime.now(ET)
    inv = investment_analysis(now=now, fresh=fresh)
    val = valuation_analysis(now=now, fresh=fresh, closing=closing) if inv else None
    opp = opportunities(keep_all=True, now=now)
    if not opp:
        return None
    etf = {}
    for m in ("lungo", "breve"):
        try:
            etf[m] = etf_scan(m)
        except Exception:
            log.exception("ETF scan for the decision desk failed")
            etf[m] = None
    try:
        catalog = etf_catalog.load()
    except Exception:
        catalog = None
    return {"asOf": now.isoformat(timespec="seconds"), "session": opp.get("asOf"), "opportunities": opp,
            "investment": inv, "valuation": val, "etf": etf, "catalog": catalog}


def decisions():
    """Decision Desk of the page, cached like the rankings (10 minutes, or as soon as one engine's result changes)."""
    import investment_decision_engine as de
    with store.lock:
        snap = store.snapshot
    if snap is None:
        return None
    inv = investment_analysis()
    val = valuation_analysis() if inv else None
    key = (id(store.daily), id(inv), id(val), id(_eopp.get("data", {}).get("lungo")), id(_eopp.get("data", {}).get("breve")),
           int(time.time() // OPPS_TTL_S))
    if _dec["key"] == key and _dec["data"] is not None:
        return _dec["data"]
    s = decision_snapshot()
    if s is None:
        return None
    data = de.decide(s)
    _dec.update(key=(id(store.daily), id(inv), id(val), id(_eopp.get("data", {}).get("lungo")),
                     id(_eopp.get("data", {}).get("breve")), int(time.time() // OPPS_TTL_S)), data=data)
    return data


@app.route("/api/decisions")
def api_decisions():
    """Decision Desk (phase 7A): every stock and ETF exposure, both horizons, with a transparent state. Read only: it
    never writes a diary and never downloads."""
    import decision_diary
    import investment_decision_engine as de
    if store.error:
        return jsonify({"error": store.error}), 500
    try:
        data = decisions()
    except Exception:
        log.exception("decision desk failed")
        return jsonify({"error": "Decision Desk non calcolabile"}), 500
    if data is None:
        return jsonify({"error": "loading"}), 503
    try:
        diary = decision_diary.stats()
    except Exception:
        log.exception("decision diary stats failed")
        diary = None
    return _json(dict(de.page(data), diary=diary))


@app.route("/api/decisions/<path:rid>")
def api_decision_one(rid):
    """One decision in full: evidence, risks, conditions of change, missing data, dates, validation, links."""
    import investment_decision_engine as de
    try:
        data = decisions()
    except Exception:
        log.exception("decision desk failed")
        return jsonify({"error": "Decision Desk non calcolabile"}), 500
    if data is None:
        return jsonify({"error": "loading"}), 503
    r = de.detail(data, rid)
    if r is None:
        return jsonify({"error": "decisione non trovata"}), 404
    return _json(dict(r, version=data["version"], disclaimer=data["disclaimer"]))


def save_decision_diary(day, now, source):
    """Decision snapshot of a session the opportunity diary has already recorded (decision_diary.py), with the closing
    prices of that session. Never the first record of a diary, never twice; a failure never stops the loop."""
    try:
        import decision_diary as dd
        import investment_decision_engine as de
        import opportunity_diary as od
        import opportunity_scanner
        if not od.exists(day, opportunity_scanner.MODEL_VERSION):
            return "decisioni: diario delle opportunità non registrato per questa seduta"
        if dd.exists(day, de.VERSION):
            return "decisioni già registrate"
        done = dd.runs_of_session(day)
        if done:                       # another desk version already holds this session: never a second record
            return f"decisioni già registrate con il Decision Desk {done[0][0]}"
        if _dec.get("diaryDay") == day and time.time() - _dec.get("diaryAt", 0) < INV_REFRESH_S:
            return "decisioni: nuovo tentativo tra poco"
        _dec.update(diaryDay=day, diaryAt=time.time())
        s = decision_snapshot(now=now, fresh=True, closing=True)
        if s is None:
            return "decisioni: dati non ancora disponibili"
        saved, msg = dd.record(de.decide(s), day, now.isoformat(timespec="seconds"), source, opportunity_scanner.MODEL_VERSION)
        if saved:
            log.info("decision diary: %s for %s (%s)", msg, day, source)
        return "decisioni: " + msg
    except Exception:
        log.exception("decision diary not saved")
        return "decisioni: errore, vedi cache/server.log"


@app.route("/api/opportunities/validation")
def api_opportunities_validation():
    """Summary of the latest study of the validation lab (phase O3): only read from data/validazione/riepilogo.json,
    written by `opportunity_validation.py run`. Never computed here, so the dashboard is not slowed down."""
    import opportunity_diary
    import opportunity_validation
    x = opportunity_validation.read_summary()
    recheck = opportunity_validation.read_recheck()
    try:
        diary = opportunity_diary.stats()          # read only: an absent diary is not created
    except Exception:
        log.exception("opportunity diary stats failed")
        diary = None
    out = {"available": False} if x is None else {"available": True, **x}
    out["recheck"] = recheck
    out["diary"] = {"started": bool(diary and diary.get("started")), "days": (diary or {}).get("days", 0),
                    "first": (diary or {}).get("first"), "last": (diary or {}).get("last")} if diary is not None else None
    out["reliability"] = opportunity_validation.reliability(x, recheck, diary)
    return app.response_class(json.dumps(out, default=clean, allow_nan=False), mimetype="application/json")


@app.route("/api/opportunities/strategies")
def api_opportunities_strategies():
    """Summary of the experimental strategies of phase 4B: only read from data/strategie/riepilogo.json, written by
    `opportunity_strategies.py run`. Never computed here (no slowdown, no influence on the scanner)."""
    import opportunity_strategies
    x = opportunity_strategies.read_summary()
    out = {"available": False} if x is None else {"available": True, "summary": x}
    return app.response_class(json.dumps(out, default=clean, allow_nan=False), mimetype="application/json")


@app.route("/api/patterns")
def api_patterns():
    """Last test of the technical patterns (backtest.py --patterns, run by hand)."""
    if not os.path.exists(os.path.join(REPORT_DIR, "patterns.json")):
        return jsonify({"error": "missing"}), 404
    return send_from_directory(REPORT_DIR, "patterns.json", max_age=0)


def authorize_writer(who):
    """Phase 6C: only the real entry points may write the production diaries (app_env). In test or preview it does
    nothing: there the diaries are temporary copies and the guard blocks every production path."""
    import app_env
    if app_env.is_production():
        app_env.authorize(who)


if __name__ == "__main__":
    authorize_writer("server")
    threading.Thread(target=worker, daemon=True).start()
    port = int(os.environ.get("PORT", 8100))
    log.info("Nasdaq-100 dashboard on http://localhost:%d  (first load takes ~30s)", port)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
