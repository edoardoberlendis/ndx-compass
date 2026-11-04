"""Pagella del titolo (phase 26): the same automatic checks for every position, nothing written or chosen by me
(the thesis was removed on 4 November 2026: portafoglio/tesi.json is no longer read, never deleted).

Checks and thresholds approved by the user on 4 November 2026 (change them only on request):
  ricavi       revenue of the last annual report up at least 10% on the year before (12 months each: Yahoo gives
               only 5 quarters, not the 8 needed for "last 12 months vs the 12 before")
  stime        next year's EPS estimate not cut more than 3% in 90 days
  consenso     analysts' consensus at least "Acquisto" (Yahoo recommendationKey buy or strong_buy)
  margine      operating margin of the last annual report stable or rising: at most 1 point below the year before
  valutazione  the dashboard's valuation judgment (sector and own history, analysts.valuation) is not "Cara"
  trend        price above the 200-day average
  diversifica  (ETF and ETC) weekly correlation in EUR over 2 years with the rest of the portfolio below 0.60,
               the threshold already used in the ETF tab (etf.CORR_LOW)
A check that cannot be computed is "?": it never counts as fallen (actions.py).

Every switch true <-> false is written with its date in portafoglio/pagella.json (the log). Positions outside the
Nasdaq-100 and outside the ETF list get their data once a day in portafoglio/dati_titoli.json (the list of tickers
says what I own): analyst data and price ratios for the stocks, daily prices for all of them (decision rules and
automatic stop, server.position_market).
"""
import json
import logging
import os
import threading
import time
from datetime import date, datetime

import pandas as pd

import portfolio

log = logging.getLogger("pillars")

FILE = os.path.join(portfolio.PORTFOLIO_DIR, "dati_titoli.json")
LOG = os.path.join(portfolio.PORTFOLIO_DIR, "pagella.json")      # {isin: {"last": {id: {state, since, initial}}, "log": [...]}}
REV_MIN = 10.0          # ricavi: growth of the last annual revenue, percent
EPS_CUT_90 = -3.0       # stime: next year's EPS estimate change in 90 days, percent
MARGIN_DROP = 1.0       # margine: at most 1 percentage point lower than the year before = "stable"
CORR_MAX = 0.60         # diversifica: same threshold as etf.CORR_LOW
MIN_WEEKS = 30          # diversifica: at least 30 common weeks, as in the ETF tab
RETRY_MIN = 15
BUY_KEYS = ("buy", "strong_buy")
REC_IT = {"strong_buy": "Forte acquisto", "buy": "Acquisto", "hold": "Mantenere", "underperform": "Sottoperformance", "sell": "Vendita"}
MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]

# id, short name, the rule as shown in the panel
STOCK = [
    ("ricavi", "Ricavi in crescita", "Ricavi dell'ultimo bilancio annuale in crescita di almeno il 10% sull'anno prima"),
    ("stime", "Stime di utile non tagliate", "Stima di utile del prossimo anno non tagliata più del 3% in 90 giorni"),
    ("consenso", "Consenso degli analisti", "Consenso degli analisti almeno «Acquisto»"),
    ("margine", "Margine operativo stabile o in crescita", "Margine operativo dell'ultimo bilancio annuale non sceso più di 1 punto rispetto all'anno prima"),
    ("valutazione", "Valutazione non cara", "Giudizio di valutazione della dashboard (confronto con settore e storia) diverso da «Cara»"),
    ("trend", "Trend di fondo positivo", "Prezzo sopra la media a 200 giorni"),
]
FUND = [
    ("trend", "Trend di fondo positivo", "Prezzo sopra la media a 200 giorni"),
    ("diversifica", "Diversifica il portafoglio", "Correlazione settimanale con il resto del portafoglio (2 anni, in euro) sotto 0,60"),
]


def it(x, d=1):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".").replace("-", "−")


def sgn(x, d=1):
    return ("+" if x > 0 else "") + it(x, d)


def catalog(kind):
    """Pillars that can be chosen for a position: ETF and ETC have their own short list."""
    return FUND if kind in ("ETF", "ETC") else STOCK


def month_it(iso):
    d = date.fromisoformat(iso[:10])
    return f"{MONTHS[d.month - 1]} {d.year}"


# ---------------------------------------------------------------- the single pillars (pure functions, tested)

def revenue_growth(years, threshold=REV_MIN):
    """years: [{"fy", "revenue", ...}] from analysts.fetch_one. -> (state, detail)."""
    ys = sorted((y for y in years or [] if y.get("revenue") and y["revenue"] > 0), key=lambda y: y["fy"], reverse=True)
    if len(ys) < 2:
        return "na", "servono due bilanci annuali con i ricavi"
    g = (ys[0]["revenue"] / ys[1]["revenue"] - 1) * 100
    return ("ok" if g >= threshold else "ko"), f"bilancio chiuso a {month_it(ys[0]['fy'])}: {sgn(g)}% sull'anno prima (soglia +{it(threshold, 0)}%)"


def operating_margin(years):
    ys = sorted((y for y in years or [] if y.get("revenue") and y["revenue"] > 0 and y.get("operatingIncome") is not None),
                key=lambda y: y["fy"], reverse=True)
    if len(ys) < 2:
        return "na", "servono due bilanci annuali con ricavi e utile operativo (dato aggiunto dal 4 novembre 2026: arriva con l'aggiornamento giornaliero)"
    m0, m1 = (ys[i]["operatingIncome"] / ys[i]["revenue"] * 100 for i in (0, 1))
    return ("ok" if m0 - m1 >= -MARGIN_DROP else "ko"), (f"bilancio chiuso a {month_it(ys[0]['fy'])}: {it(m0)}% contro {it(m1)}% l'anno prima "
                                                          f"({sgn(m0 - m1)} punti; soglia −{it(MARGIN_DROP, 0)} punto)")


def estimates(eps_rev90):
    if eps_rev90 is None:
        return "na", "stime degli analisti non disponibili"
    return ("ok" if eps_rev90 >= EPS_CUT_90 else "ko"), f"stima di utile del prossimo anno {sgn(eps_rev90)}% in 90 giorni (soglia −3%)"


def consensus(key):
    if not key or key == "none":
        return "na", "consenso degli analisti non disponibile"
    return ("ok" if key in BUY_KEYS else "ko"), f"consenso «{REC_IT.get(key, key)}»"


def valuation(label, why=""):
    if not label:
        return "na", why or "giudizio di valutazione non calcolabile (mancano il confronto con il settore e lo storico)"
    return ("ko" if label == "Cara" else "ok"), f"valutazione «{label}»" + (f" ({why})" if why else "")


def trend(price, sma):
    if not price or not sma:
        return "na", "meno di 200 sedute di prezzi, o prezzi storici non ancora caricati"
    d = (price / sma - 1) * 100
    return ("ok" if d >= 0 else "ko"), f"prezzo {'sopra' if d >= 0 else 'sotto'} la media 200 del {it(abs(d))}%"


def diversification(corr, weeks):
    if corr is None or weeks < MIN_WEEKS:
        return "na", f"servono almeno {MIN_WEEKS} settimane di prezzi in comune con il resto del portafoglio"
    return ("ok" if corr < CORR_MAX else "ko"), f"correlazione {it(corr, 2)} su {weeks} settimane (soglia 0,60)"


# ---------------------------------------------------------------- all the pillars of a position

def evaluate(p, d):
    """Every check of the position's list with its state today.
    d: {"years", "epsRev90", "rec", "valLabel", "valWhy", "sma200", "corr", "weeks"}.
    Returns {"list": [{"id", "name", "rule", "state", "detail"}], "score": {"n", "ok", "ko", "na"}}."""
    calc = {
        "ricavi": lambda: revenue_growth(d.get("years")),
        "stime": lambda: estimates(d.get("epsRev90")),
        "consenso": lambda: consensus(d.get("rec")),
        "margine": lambda: operating_margin(d.get("years")),
        "valutazione": lambda: valuation(d.get("valLabel"), d.get("valWhy") or ""),
        "trend": lambda: trend(p.get("price"), d.get("sma200")),
        "diversifica": lambda: diversification(d.get("corr"), d.get("weeks") or 0),
    }
    out = []
    for pid, name, rule in catalog(p.get("kind")):
        state, detail = calc[pid]()
        out.append({"id": pid, "name": name, "rule": rule, "state": state, "detail": detail})
    st = [x["state"] for x in out]
    return {"list": out, "score": {"n": len(st), "ok": st.count("ok"), "ko": st.count("ko"), "na": st.count("na")}}


def changes(ev, last, today=None):
    """Log entries for the checks that turned true <-> false since the last check, and the new "last" states.
    "Not computable" does not change anything (a missing figure is not news). The first check only records the
    starting state, marked "initial" (it is not a fall: rule T1 of actions.py ignores it)."""
    today = (today or date.today()).isoformat()
    last = dict(last or {})
    entries = []
    for x in ev["list"]:
        if x["state"] == "na":
            continue
        prev = (last.get(x["id"]) or {}).get("state")
        if prev != x["state"]:
            if prev:
                entries.append({"date": today, "pillar": x["id"], "name": x["name"], "from": prev, "to": x["state"], "detail": x["detail"]})
            last[x["id"]] = {"state": x["state"], "since": today, "initial": not prev}
    return entries, last


def load_log():
    try:
        with open(LOG) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def record(updates):
    """{isin: (entries, last)}: append the changes to the log and keep the new states. Writes only on changes."""
    all_ = load_log()
    dirty = False
    for isin, (entries, last) in updates.items():
        cur = all_.setdefault(isin, {"last": {}, "log": []})
        if not entries and cur.get("last") == last:
            continue
        cur["log"] = (cur.get("log") or []) + entries
        cur["last"] = last
        dirty = True
    if dirty:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG + ".tmp", "w") as f:
            json.dump(all_, f, indent=1, ensure_ascii=False)
        os.replace(LOG + ".tmp", LOG)


# ---------------------------------------------------------------- data of the stocks outside the Nasdaq-100 (daily)

INFO_KEYS = {"price": ("currentPrice", "regularMarketPrice"), "mcap": ("marketCap",), "fpe": ("forwardPE",), "pe": ("trailingPE",),
             "ps": ("priceToSalesTrailing12Months",), "evEbitda": ("enterpriseToEbitda",), "rec": ("recommendationKey",),
             "currency": ("currency",), "financialCurrency": ("financialCurrency",), "sector": ("sector",)}
_lock = threading.Lock()
_state = {"loading": False, "failedAt": 0}


def _today():
    return datetime.now().date().isoformat()


def read():
    try:
        with open(FILE) as f:
            c = json.load(f)
        return c if isinstance(c, dict) and "data" in c else {"date": None, "data": {}}
    except (OSError, ValueError):
        return {"date": None, "data": {}}


COMPANY_KEYS = ("revenueGrowth", "earningsGrowth", "profitMargins", "freeCashflow", "totalRevenue", "totalDebt", "totalCash",
                "earningsTimestamp", "earningsTimestampStart", "targetMeanPrice", "numberOfAnalystOpinions")
STOCK_YEARS, FUND_YEARS = "2y", "5y"       # daily prices: 200-day average and 52 weeks; 5 years for "arrivati tardi"


def _daily(df):
    """Daily OHLCV as compact lists (JSON), or None."""
    if df is None or df.empty or "Close" not in df:
        return None
    df = df.dropna(subset=["Close"])
    idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
    col = lambda k: [None if v != v else round(float(v), 6) for v in df[k]] if k in df else None
    return {"d": [str(x.date()) for x in idx], "o": col("Open"), "h": col("High"), "l": col("Low"), "c": col("Close"), "v": col("Volume")}


def frame(x):
    """The daily prices saved by _daily, back as a DataFrame (None if missing)."""
    d = (x or {}).get("daily")
    if not d or not d.get("c"):
        return None
    df = pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["d"]))
    return df.astype(float)


def _fetch(stocks, funds):
    import analysts
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor

    from server import download
    t0 = time.time()
    with ThreadPoolExecutor(analysts.THREADS) as ex:
        data = dict(ex.map(analysts.fetch_one, stocks)) if stocks else {}
    if stocks:
        analysts.add_year_end_prices(data)
    out = {}
    for t in stocks:
        try:
            info = yf.Ticker(t).info or {}
        except Exception:
            info = {}
        row = {k: next((info.get(s) for s in src if info.get(s) is not None), None) for k, src in INFO_KEYS.items()}
        out[t] = {"a": data.get(t) or {}, "row": row, "info": {k: info.get(k) for k in COMPANY_KEYS}}
    for tickers, period in ((stocks, STOCK_YEARS), (funds, FUND_YEARS)):
        if tickers:
            px = download(list(tickers), period=period, interval="1d")
            for t in tickers:
                out.setdefault(t, {})["daily"] = _daily(px.get(t))
    log.info("pillars: data of %d stocks and %d funds outside the lists in %.1fs", len(stocks), len(funds), time.time() - t0)
    return out


def _load(stocks, funds):
    try:
        data = _fetch(stocks, funds)
        ok = sum(1 for x in data.values() if (x.get("a") or {}).get("years") or (x.get("row") or {}).get("rec") or x.get("daily"))
        if data and not ok:
            raise RuntimeError("Yahoo non ha dato dati")
        os.makedirs(os.path.dirname(FILE), exist_ok=True)
        with open(FILE + ".tmp", "w") as f:
            json.dump({"date": _today(), "data": data}, f, default=str)
        os.replace(FILE + ".tmp", FILE)
        _state["failedAt"] = 0
    except Exception:
        log.exception("pillars: download failed")
        _state["failedAt"] = time.time()
    finally:
        _state["loading"] = False


def extra(stocks, funds=()):
    """{ticker: {"a", "row", "info", "daily"}} for stocks outside the Nasdaq-100 and {ticker: {"daily"}} for funds
    outside the ETF list. Returns what is saved (also yesterday's) at once and starts the daily download in the
    background when needed."""
    c = read()
    stocks, funds = sorted(set(stocks)), sorted(set(funds))
    if not stocks and not funds:
        return {}
    have = c["data"]
    stale = (c.get("date") != _today() or any(t not in have or "daily" not in have[t] for t in stocks + funds)
             or any("info" not in have[t] for t in stocks if t in have))
    with _lock:
        if stale and not _state["loading"] and time.time() - _state["failedAt"] > RETRY_MIN * 60:
            _state["loading"] = True
            threading.Thread(target=_load, args=(stocks, funds), daemon=True).start()
    return have


def extra_valuation(x):
    """Valuation judgment of a stock outside the Nasdaq-100: only against its own history (its sector has no peers in
    the Nasdaq-100 list), and only if prices and accounts are in the same currency."""
    import analysts
    row = dict(x.get("row") or {})
    if not row.get("price") or not row.get("mcap"):
        return None, "prezzo o capitalizzazione non disponibili"
    if row.get("financialCurrency") and row.get("currency") and row["financialCurrency"] != row["currency"]:
        return None, f"bilanci in {row['financialCurrency']} e prezzo in {row['currency']}: confronto con la storia non affidabile"
    row["sector"] = "__fuori_nasdaq__"
    v = analysts.valuation(row, x.get("a"), {})
    return v["label"], "solo contro la sua storia: nel Nasdaq-100 non ci sono abbastanza titoli dello stesso settore" if v["label"] else ""


# ---------------------------------------------------------------- correlation of a fund with the rest of the portfolio

def fund_correlation(pf, p, closes):
    """Weekly correlation in EUR (2 years of prices) between one ETF/ETC and the rest of the portfolio (without it)."""
    import risk
    if not closes or not p.get("ticker") or closes.get(p["ticker"]) is None:
        return None, 0
    rest = {**pf, "positions": [q for q in pf.get("positions") or [] if q["isin"] != p["isin"]]}
    port = risk.portfolio_weekly(rest, closes)
    e = risk._eur(closes[p["ticker"]], p["currency"], closes.get(portfolio.FX))
    if e is None or port.empty:
        return None, 0
    e = e.copy()
    e.index = pd.to_datetime(e.index).tz_localize(None).normalize()
    w = e[~e.index.duplicated(keep="last")].resample("W-FRI").last().pct_change().dropna()
    both = pd.concat([w, port], axis=1, join="inner").dropna()
    if len(both) < MIN_WEEKS:
        return None, len(both)
    return float(both.iloc[:, 0].corr(both.iloc[:, 1])), len(both)
