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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf
from flask import Flask, jsonify, request, send_from_directory

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
    now = now or datetime.now(ET)
    if now.weekday() >= 5:
        return "closed"
    t = now.hour * 60 + now.minute
    if 4 * 60 <= t < 9 * 60 + 30:
        return "pre"
    if 9 * 60 + 30 <= t < 16 * 60:
        return "open"
    if 16 * 60 <= t < 20 * 60:
        return "post"
    return "closed"


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


# ---------------------------------------------------------------- store

class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.constituents = []
        self.infos = {}
        self.daily = {}         # ticker -> DataFrame (2y daily)
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

    def daily_due(self):
        """Once per ET day, plus once after the close so perf windows include the final bar."""
        if not self.last_daily:
            return True
        now = datetime.now(ET)
        last = datetime.fromtimestamp(self.last_daily, ET)
        cutoff = now.replace(hour=DAILY_AFTER_CLOSE[0], minute=DAILY_AFTER_CLOSE[1], second=0, microsecond=0)
        return last.date() != now.date() or last < cutoff <= now

    def refresh_daily(self):
        tickers = [c["ticker"] for c in self.constituents] + list(BENCHMARKS) + [SIGNAL_BENCH]
        t0 = time.time()
        d = download(tickers, period="2y", interval="1d")
        if d:
            tech = self.technicals(d)
            with self.lock:
                self.daily = d
                self.tech = tech
                self.last_daily = time.time()
            log.info("daily history: %d series in %.1fs", len(d), time.time() - t0)

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
        for r in rows:
            r["weight"] = (r["mcap"] or 0) / total * 100 if total else None

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
                "lastQuote": datetime.fromtimestamp(self.last_quote, ET).isoformat(timespec="seconds") if self.last_quote else None,
                "stocks": rows,
                "indices": idx,
                "breadth": breadth,
                "totalMcap": total,
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


def worker():
    try:
        store.constituents = load_constituents()
        tickers = [c["ticker"] for c in store.constituents]
        store.infos = load_infos(tickers)
        import analysts  # local import: analysts imports this module
        store.analysts = analysts.cached_data()                  # yesterday's copy is fine until the refresh lands
        store.refresh_daily()
        store.refresh_intraday()
        store.build()
        store.ready.set()
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
            if not analysts.is_fresh():
                store.refresh_analysts(tickers)
            store.refresh_news_all(tickers)
            store.refresh_intraday()
            store.build()
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
    }, default=clean, allow_nan=False), mimetype="application/json")


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
_report_job = {"running": False, "error": None, "started": None}


@app.route("/api/reports")
def api_reports():
    os.makedirs(REPORT_DIR, exist_ok=True)
    ids = sorted((f[:-5] for f in os.listdir(REPORT_DIR) if f.endswith(".json") and f != "latest.json"), reverse=True)
    return jsonify({"reports": ids, "job": _report_job})


@app.route("/api/report/<rid>")
def api_report(rid):
    if rid != "latest" and rid not in {f[:-5] for f in os.listdir(REPORT_DIR)}:
        return jsonify({"error": "not found"}), 404
    return send_from_directory(REPORT_DIR, rid + ".json", max_age=0)


@app.route("/api/backtest")
def api_backtest():
    """Last backtest of the technical score (backtest.py, run by hand)."""
    if not os.path.exists(os.path.join(REPORT_DIR, "backtest.json")):
        return jsonify({"error": "missing"}), 404
    return send_from_directory(REPORT_DIR, "backtest.json", max_age=0)


@app.route("/api/report/run", methods=["POST"])
def api_report_run():
    if _report_job["running"]:
        return jsonify(_report_job), 409

    def job():
        import signals  # local import: signals imports this module
        try:
            signals.run(notify_user=False)
            _report_job["error"] = None
        except Exception as e:
            log.exception("report failed")
            _report_job["error"] = str(e)
        finally:
            _report_job["running"] = False

    _report_job.update(running=True, error=None, started=datetime.now(ET).isoformat(timespec="seconds"))
    threading.Thread(target=job, daemon=True).start()
    return jsonify(_report_job), 202


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    port = int(os.environ.get("PORT", 8100))
    log.info("Nasdaq-100 dashboard on http://localhost:%d  (first load takes ~30s)", port)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
