"""Risk of my portfolio (plan phase 15): volatility, beta, index-drop scenario, historical drawdown, risk contribution
of each position and how much the positions move together.

Personal data: prices are downloaded by ticker (as for the live quotes) and everything stays in memory.

Method, to be read with its limits (LIMITS below, shown in the page):
- 2 years of daily closes, all converted to EUR (USD prices ÷ EUR/USD of the same day; QQQ too);
- the portfolio is simulated "as it is today": today's WEIGHTS held constant in the past. When a position has no
  price yet on a day, its weight is shared among the others;
- volatility and drawdown use daily returns; beta, risk contribution and correlation use WEEKLY returns, because
  Milan and Frankfurt close before New York and daily figures would understate how much things move together.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime

import numpy as np
import pandas as pd

import portfolio

log = logging.getLogger("ndx")
BENCH = "QQQ"
MIN_DAYS = 126            # about 6 months of prices, or the position is left out
MIN_WEEKS = 26
JUMP_UP, JUMP_DOWN = 1.5, -0.75   # a daily move beyond +150% / −75% is treated as a wrong price history (splits not adjusted...)
OVERWEIGHT = 1.5          # flag: share of risk at least 1.5 times the weight in EUR
SCENARIOS = (10, 20)

LIMITS = [
    ("Due anni sono pochi", "Coprono un solo tipo di mercato. In una crisi vera volatilità e correlazioni salgono: le perdite possono essere più grandi di quelle stimate qui."),
    ("Pesi di oggi nel passato", "Il portafoglio è simulato come se avessi sempre avuto i pesi di oggi: misura il rischio del portafoglio attuale, non quello che hai avuto davvero."),
    ("Borse con orari diversi", "Milano e Francoforte chiudono prima di New York. Per questo beta, contributo al rischio e correlazioni usano rendimenti settimanali; volatilità e massima perdita usano quelli giornalieri."),
    ("Posizioni fuori dal calcolo", "Restano fuori le posizioni con meno di circa 6 mesi di prezzi e quelle con prezzi storici anomali (salti di un giorno oltre +150% o −75%, tipici di dati sbagliati): il loro rischio non è contato e va guardato a parte. Per le posizioni con meno di 2 anni di storia, nei giorni senza prezzo il loro peso è ripartito sulle altre."),
    ("Scenario lineare", "Lo scenario moltiplica il beta per il calo dell'indice, a cambio EUR/USD fermo. Nei cali forti i prodotti a leva giornaliera non perdono esattamente il multiplo dell'indice e il cambio può muoversi."),
    ("Stime, non previsioni", "Sono misure del passato recente. Non dicono cosa succederà e non sono una consulenza finanziaria."),
]

_lock = threading.Lock()
_hist = {"day": None, "tickers": None, "closes": {}, "loading": False, "error": None}


# ---------------------------------------------------------------- prices (memory only)

def _load_history(tickers):
    from server import download   # local import: server imports this module's users
    try:
        t0 = time.time()
        data = download(tickers + [portfolio.FX, BENCH], period="2y", interval="1d")
        closes = {t: df["Close"].dropna() for t, df in data.items() if "Close" in df and len(df["Close"].dropna())}
        with _lock:
            _hist.update(day=datetime.now().date(), tickers=tuple(tickers), closes=closes, error=None)
        log.info("portfolio risk: %d price series in %.1fs", len(closes), time.time() - t0)
    except Exception as e:
        log.exception("portfolio risk history failed")
        with _lock:
            _hist["error"] = str(e)
    finally:
        with _lock:
            _hist["loading"] = False


def history(tickers):
    """{ticker: closes} for today, or None while the download runs in the background (once a day, or when positions change)."""
    tickers = sorted(set(tickers))
    with _lock:
        fresh = _hist["day"] == datetime.now().date() and _hist["tickers"] == tuple(tickers)
        if fresh:
            return _hist["closes"]
        if not _hist["loading"]:
            _hist["loading"] = True
            threading.Thread(target=_load_history, args=(tickers,), daemon=True).start()
    return None


def sma200():
    """{ticker: 200-day average of the closes} from the prices already in memory (empty until they are downloaded)."""
    with _lock:
        closes = dict(_hist["closes"])
    return {t: float(c.iloc[-200:].mean()) for t, c in closes.items() if len(c) >= 200}


# ---------------------------------------------------------------- the numbers

def _eur(close, currency, fx):
    """A price series in EUR (None for a currency other than EUR and USD)."""
    cur = currency.upper()
    if cur == "EUR":
        return close
    if cur != "USD" or fx is None:
        return None
    return close / fx.reindex(close.index, method="ffill")


def _drawdown(returns):
    """Deepest fall from a peak of the cumulated returns: (percent, peak date, trough date)."""
    v = (1 + returns.fillna(0)).cumprod()
    dd = v / v.cummax() - 1
    trough = dd.idxmin()
    peak = v.loc[:trough].idxmax()
    return float(dd.min() * 100), peak, trough


def compute(pf, closes):
    """Risk figures of a portfolio snapshot (portfolio.snapshot()) from daily closes by ticker."""
    positions = [p for p in pf.get("positions") or [] if p.get("value")]
    total = sum(p["value"] for p in positions)
    fx, q = closes.get(portfolio.FX), closes.get(BENCH)
    if not positions or not total or q is None:
        return {"status": "none"}
    series, used, left = {}, [], []
    for p in positions:
        c = closes.get(p.get("ticker") or "")
        e = _eur(c, p["currency"], fx) if c is not None else None
        moves = e.pct_change() if e is not None else None
        why = ("prezzi storici non disponibili" if c is None else "valuta diversa da euro e dollaro" if e is None
               else "meno di 6 mesi di prezzi" if len(e) < MIN_DAYS
               else "prezzi storici anomali (salti di un giorno non credibili)" if moves.max() > JUMP_UP or moves.min() < JUMP_DOWN else None)
        if why:
            left.append({**p, "why": why})
            continue
        key = p["isin"]
        series[key] = e if key not in series else series[key]
        used.append(p)
    if not used:
        return {"status": "none"}
    value = {}
    for p in used:
        value[p["isin"]] = value.get(p["isin"], 0) + p["value"]
    names = {p["isin"]: p.get("ticker") or p["name"] for p in used}
    long_names = {p["isin"]: p["name"] for p in used}
    covered = sum(value.values())
    w = pd.Series(value) / covered

    px = pd.DataFrame(series).sort_index()
    px.index = pd.to_datetime(px.index).tz_localize(None).normalize()
    px = px[~px.index.duplicated(keep="last")]
    q_eur = _eur(q, "USD", fx)
    q_eur.index = pd.to_datetime(q_eur.index).tz_localize(None).normalize()
    first = px.apply(lambda s: s.first_valid_index())
    px = px.ffill()                                       # a holiday on one exchange: same price, the move shows the day after
    daily, weekly = px.pct_change(), px.resample("W-FRI").last().pct_change()
    q_daily, q_weekly = q_eur.pct_change(), q_eur.resample("W-FRI").last().pct_change()

    def port(r):          # today's weights; a position without a price that day gives its weight to the others
        ok = r.notna()
        return (r.fillna(0) * w).sum(axis=1) / (ok * w).sum(axis=1).where(lambda x: x > 0)
    rp_d, rp_w = port(daily).dropna(), port(weekly).dropna()
    qd, qw = q_daily.reindex(rp_d.index), q_weekly.reindex(rp_w.index)

    vol = float(rp_d.std() * math.sqrt(252) * 100)
    q_vol = float(qd.std() * math.sqrt(252) * 100)
    q_var = float(qw.var())
    beta = float(rp_w.cov(qw) / q_var) if q_var else None
    dd, peak, trough = _drawdown(rp_d)
    q_same = float(((1 + qd.loc[peak:trough].iloc[1:]).prod() - 1) * 100)
    q_dd = _drawdown(qd)[0]

    cov = weekly.cov(min_periods=MIN_WEEKS)
    cov = cov.reindex(index=w.index, columns=w.index).fillna(0)
    marginal = cov.values @ w.values
    var_p = float(w.values @ marginal)
    rows = []
    for k, isin in enumerate(w.index):
        share = float(w.iloc[k] * marginal[k] / var_p * 100) if var_p > 0 else None
        weight = float(w.iloc[k] * 100)
        b = weekly[isin].cov(qw) / q_var if q_var else None
        rows.append({"name": names[isin], "fullName": long_names[isin], "weight": weight, "risk": share,
                     "ratio": share / weight if share is not None and weight else None,
                     "beta": None if b is None or pd.isna(b) else float(b),
                     "vol": float(daily[isin].std() * math.sqrt(252) * 100),
                     "since": str(first[isin].date()),
                     "flag": bool(share is not None and weight and share / weight >= OVERWEIGHT)})
    rows.sort(key=lambda r: -(r["risk"] or 0))

    corr = weekly.corr(min_periods=MIN_WEEKS)
    num = den = 0.0
    pairs = []
    ids = list(w.index)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            c = corr.loc[ids[i], ids[j]]
            if pd.isna(c):
                continue
            num += w[ids[i]] * w[ids[j]] * c
            den += w[ids[i]] * w[ids[j]]
            pairs.append({"a": names[ids[i]], "b": names[ids[j]], "corr": float(c)})
    avg = float(num / den) if den else None
    pairs.sort(key=lambda x: -x["corr"])

    return {
        "status": "ok", "from": str(rp_d.index[0].date()), "to": str(rp_d.index[-1].date()),
        "coverage": covered / total * 100, "covered": covered,
        "left": [{"name": p.get("ticker") or p["name"], "weight": p["value"] / total * 100, "why": p["why"]} for p in left],
        "vol": vol, "benchVol": q_vol, "beta": beta,
        "scenarios": [{"drop": d, "loss": -beta * d / 100 * covered if beta is not None else None,
                       "pct": -beta * d if beta is not None else None} for d in SCENARIOS],
        "drawdown": {"pct": dd, "peak": str(peak.date()), "trough": str(trough.date()), "benchSame": q_same, "benchMax": q_dd},
        "positions": rows,
        "correlation": {"avg": avg, "label": None if avg is None else "bassa" if avg < 0.3 else "media" if avg < 0.6 else "alta",
                        "pairs": pairs[:5]},
        "limits": [{"title": a, "text": b} for a, b in LIMITS],
    }


def snapshot(pf):
    """For /api/portfolio/risk: {"status": "loading" | "none" | "ok", ...}."""
    tickers = [p["ticker"] for p in pf.get("positions") or [] if p.get("ticker")]
    if not tickers:
        return {"status": "none"}
    closes = history(tickers)
    if closes is None:
        return {"status": "loading"}
    try:
        return compute(pf, closes)
    except Exception as e:
        log.exception("portfolio risk failed")
        return {"status": "error", "error": str(e)}
