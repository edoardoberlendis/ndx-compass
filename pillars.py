"""Pillars of the thesis (phase 26, step 1): 2-4 measurable reasons per position, checked automatically every day.

The user picks the pillars from a list (only measurable ones, so the dashboard can check them) plus at most one
written in words, which they confirm by hand. Thresholds approved by the user on 4 November 2026 (change them only
on request):
  ricavi       revenue of the last annual report up at least 10% on the year before (12 months each: Yahoo gives
               only 5 quarters, not the 8 needed for "last 12 months vs the 12 before"); per-position threshold allowed
  stime        next year's EPS estimate not cut more than 3% in 90 days
  consenso     analysts' consensus at least "Acquisto" (Yahoo recommendationKey buy or strong_buy)
  margine      operating margin of the last annual report stable or rising: at most 1 point below the year before
  valutazione  the dashboard's valuation judgment (sector and own history, analysts.valuation) is not "Cara"
  trend        price above the 200-day average
  diversifica  (ETF and ETC) weekly correlation in EUR over 2 years with the rest of the portfolio below 0.60,
               the threshold already used in the ETF tab (etf.CORR_LOW)

Stocks outside the Nasdaq-100 have no analyst data in analysts.py: this module downloads it once a day for them
(same fetch, plus the price ratios from Yahoo) into portafoglio/dati_titoli.json, because the list of tickers says
what I own. A pillar changing state (true <-> false) is written with its date in the thesis' log (portafoglio/tesi.json).
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
REV_MIN = 10.0          # ricavi: growth of the last annual revenue, percent
EPS_CUT_90 = -3.0       # stime: next year's EPS estimate change in 90 days, percent
MARGIN_DROP = 1.0       # margine: at most 1 percentage point lower than the year before = "stable"
CORR_MAX = 0.60         # diversifica: same threshold as etf.CORR_LOW
MIN_WEEKS = 30          # diversifica: at least 30 common weeks, as in the ETF tab
MANUAL_DAYS = 92        # the pillar written in words is confirmed by hand every 3 months
RETRY_MIN = 15
BUY_KEYS = ("buy", "strong_buy")
REC_IT = {"strong_buy": "Forte acquisto", "buy": "Acquisto", "hold": "Mantenere", "underperform": "Sottoperformance", "sell": "Vendita"}
MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]

# id, short name, the rule as shown in the panel
STOCK = [
    ("ricavi", "Ricavi in crescita", "Ricavi dell'ultimo bilancio annuale in crescita di almeno il {rev}% sull'anno prima"),
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


def manual(m, today=None):
    """The pillar written in words: {"text", "state": ok|ko, "date"} confirmed by hand every 3 months."""
    if not m or not m.get("text"):
        return None
    today = today or date.today()
    if not m.get("date"):
        return "na", "da confermare: premi «Vale ancora» o «È caduto»"
    days = (today - date.fromisoformat(m["date"])).days
    if m.get("state") == "ko":
        return "ko", f"segnato come caduto il {date.fromisoformat(m['date']).strftime('%d/%m/%Y')}"
    if days > MANUAL_DAYS:
        return "na", f"confermato l'ultima volta {days} giorni fa: va riconfermato ogni 3 mesi"
    return "ok", f"confermato il {date.fromisoformat(m['date']).strftime('%d/%m/%Y')}"


# ---------------------------------------------------------------- all the pillars of a position

def evaluate(p, th, d):
    """Every pillar of the position's list, with its state today and whether I chose it.
    p: position; th: its thesis (or {}); d: {"years", "epsRev90", "rec", "valLabel", "valWhy", "sma200", "corr", "weeks"}.
    Returns {"list": [{"id", "name", "rule", "state", "detail", "chosen"}], "draft": bool, "manual": {...} | None}."""
    rev_min = (th.get("pillarOpts") or {}).get("ricavi") or REV_MIN
    calc = {
        "ricavi": lambda: revenue_growth(d.get("years"), rev_min),
        "stime": lambda: estimates(d.get("epsRev90")),
        "consenso": lambda: consensus(d.get("rec")),
        "margine": lambda: operating_margin(d.get("years")),
        "valutazione": lambda: valuation(d.get("valLabel"), d.get("valWhy") or ""),
        "trend": lambda: trend(p.get("price"), d.get("sma200")),
        "diversifica": lambda: diversification(d.get("corr"), d.get("weeks") or 0),
    }
    chosen = th.get("pillars")
    draft = chosen is None                     # no choice saved yet: propose the pillars that hold today
    out = []
    for pid, name, rule in catalog(p.get("kind")):
        state, detail = calc[pid]()
        out.append({"id": pid, "name": name, "rule": rule.format(rev=it(rev_min, 0)), "state": state, "detail": detail,
                    "chosen": (state == "ok") if draft else pid in chosen})
    m = th.get("manual") or {}
    ms = manual(m)
    return {"list": out, "draft": draft, "revMin": rev_min,
            "manual": {"text": m["text"], "state": ms[0], "detail": ms[1]} if ms else None}


def score(ev):
    """Counts of the chosen pillars (the manual one included): {"n", "ok", "ko", "na"}."""
    xs = [x["state"] for x in ev["list"] if x["chosen"]] + ([ev["manual"]["state"]] if ev.get("manual") else [])
    return {"n": len(xs), "ok": xs.count("ok"), "ko": xs.count("ko"), "na": xs.count("na")}


def changes(ev, last, today=None):
    """Log entries for the chosen pillars that turned true <-> false since the last check, and the new "last" states.
    "Not computable" does not change anything (a missing figure is not news)."""
    today = (today or date.today()).isoformat()
    last = dict(last or {})
    entries = []
    for x in ev["list"]:
        if not x["chosen"] or x["state"] == "na":
            continue
        prev = (last.get(x["id"]) or {}).get("state")
        if prev != x["state"]:
            if prev:                                               # the first check only records the starting state
                entries.append({"date": today, "pillar": x["id"], "name": x["name"], "from": prev, "to": x["state"], "detail": x["detail"]})
            last[x["id"]] = {"state": x["state"], "since": today}
    return entries, last


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


def _fetch(tickers):
    import analysts
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.time()
    with ThreadPoolExecutor(analysts.THREADS) as ex:
        data = dict(ex.map(analysts.fetch_one, tickers))
    analysts.add_year_end_prices(data)
    out = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info or {}
        except Exception:
            info = {}
        row = {k: next((info.get(s) for s in src if info.get(s) is not None), None) for k, src in INFO_KEYS.items()}
        out[t] = {"a": data.get(t) or {}, "row": row}
    log.info("pillars: data of %d stocks outside the Nasdaq-100 in %.1fs", len(out), time.time() - t0)
    return out


def _load(tickers):
    try:
        data = _fetch(tickers)
        ok = sum(1 for x in data.values() if x["a"].get("years") or x["row"].get("rec"))
        if tickers and not ok:
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


def extra(tickers):
    """{ticker: {"a": analyst data, "row": price ratios}} for stocks outside the Nasdaq-100. Returns what is saved
    (also yesterday's) at once and starts the daily download in the background when needed."""
    c = read()
    tickers = sorted(set(tickers))
    if not tickers:
        return {}
    stale = c.get("date") != _today() or any(t not in c["data"] for t in tickers)
    with _lock:
        if stale and not _state["loading"] and time.time() - _state["failedAt"] > RETRY_MIN * 60:
            _state["loading"] = True
            threading.Thread(target=_load, args=(tickers,), daemon=True).start()
    return c["data"]


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
