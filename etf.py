"""Ricerca → ETF (plan phase 24, step 3): the numbers of the ETF tab.

Public part, computed once a day in the background (prices of the 63 ETFs of etf_universe.json, exchange rates,
compositions and P/E of the US equivalents, a few news headlines) and kept in memory: returns in EUR, momentum,
trend, risk of having arrived late, the theme radar with its data-derived "why", the rotation map of the categories.
Personal part, computed at each request in memory: "Ha senso per il mio portafoglio?" (overlap, correlation,
concentration with 10% invested, cost and size), with the rules approved by the user.

Price history of each ETF: Borsa Italiana (.MI); if incomplete, Xetra (.DE); if still incomplete, the US equivalent
converted to EUR with the daily EUR/USD rate BEFORE computing returns, averages and momentum. The source is shown.

Nothing here says "favorevole" or "investi": the momentum rules M1 and M2 failed the test of etf_backtest.py, so
momentum is shown as "non verificato". Not investment advice.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from datetime import date, datetime

import numpy as np
import pandas as pd

log = logging.getLogger("ndx")
ROOT = os.path.dirname(os.path.abspath(__file__))
UNIVERSE = os.path.join(ROOT, "etf_universe.json")
TEST = os.path.join(ROOT, "reports", "etf_momentum.json")
STALE_DAYS = 183                 # data of justETF older than about 6 months: warning in the page
H = {"r1m": 21, "r3m": 63, "r6m": 126, "r1y": 252, "r3y": 756}
LATE_DAYS = 1260                 # history for the "arrived late" percentile: the last 5 years (or what is available)
LATE_HIGH, LATE_MID = 90, 70     # percentiles of the distance from the 200-day average (approved by the user)
YOUNG_YEARS = 5
MOVES_WITH = 0.70               # "si è mosso come" only with a correlation of at least 0.70 (approved)
MIN_SHARE = 10.0                 # the radar names the first two holdings only if they explain at least 10% of the move
FIT_SHARE = 0.10                 # "if I invested 10% of the portfolio"
OVERLAP_HIGH, OVERLAP_LOW = 25.0, 10.0      # points (approved)
CORR_HIGH, CORR_LOW = 0.85, 0.60
CONC_UP, CONC_DOWN, CONC_OTHER = 1.0, 1.0, 0.5
TER_HIGH, SIZE_SMALL = 0.50, 100.0          # %, millions of EUR
FX_PAIR = {"USD": "EURUSD=X", "JPY": "EURJPY=X", "GBP": "EURGBP=X", "CHF": "EURCHF=X", "KRW": "EURKRW=X",
           "TWD": "EURTWD=X", "BRL": "EURBRL=X", "MXN": "EURMXN=X", "INR": "EURINR=X", "HKD/CNY": "EURHKD=X"}
SECTOR_IT = {"Technology": "Tecnologia", "Telecommunication": "Telecomunicazioni", "Health Care": "Sanità", "Finance": "Finanza",
             "Industrials": "Industria", "Consumer Discretionary": "Consumi discrezionali", "Consumer Staples": "Beni di prima necessità",
             "Energy": "Energia", "Utilities": "Utility", "Basic Materials": "Materiali di base", "Real Estate": "Immobiliare"}
COUNTRY_IT = {"United States": "USA", "Japan": "Giappone", "United Kingdom": "Regno Unito", "Switzerland": "Svizzera", "Germany": "Germania",
              "France": "Francia", "China": "Cina", "Taiwan": "Taiwan", "South Korea": "Corea del Sud", "India": "India", "Brazil": "Brasile",
              "Mexico": "Messico", "Italy": "Italia", "Netherlands": "Paesi Bassi", "Canada": "Canada", "Spain": "Spagna"}

_lock = threading.Lock()
_state = {"day": None, "running": False, "data": None, "error": None}


def it(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def sgn(x, d=1):
    return f"{'+' if x > 0 else ''}{it(x, d)}%"


# ---------------------------------------------------------------- pure calculations (tested with made-up data)

def complete(s, days=365, min_obs=230, max_gap=10):
    """True if a daily series has no big holes in the last year and is not stale."""
    s = s.dropna()
    if len(s) < 60:
        return False
    last = s.index[-1]
    recent = s[s.index >= last - pd.Timedelta(days=days)]
    gaps = recent.index.to_series().diff().dt.days.max() if len(recent) > 1 else 999
    return len(recent) >= min_obs and (gaps or 0) <= max_gap and (pd.Timestamp.now().normalize() - last).days <= 7


def to_eur(usd, eurusd):
    """A USD price series in EUR with the exchange rate of the same day."""
    fx = eurusd.reindex(usd.index, method="ffill")
    return (usd / fx).dropna()


def pick_history(mi, de, proxy_eur, labels):
    """(series, source text): Borsa Italiana if complete, else Xetra, else the US equivalent in EUR."""
    for s, lab in ((mi, labels[0]), (de, labels[1])):
        if s is not None and complete(s):
            return s.dropna(), lab
    if proxy_eur is not None and len(proxy_eur.dropna()) > 260:
        return proxy_eur.dropna(), labels[2]
    for s, lab in ((mi, labels[0]), (de, labels[1])):
        if s is not None and len(s.dropna()) > 60:
            return s.dropna(), lab + " (storico incompleto)"
    return None, None


def launch_iso(text):
    """'24 October 2018' (justETF) -> '2018-10-24', or None."""
    try:
        return datetime.strptime(str(text).strip(), "%d %B %Y").date().isoformat()
    except (TypeError, ValueError):
        return None


def ret(s, n):
    s = s.dropna()
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) * 100 if len(s) > n else None


def momentum_12_1(s):
    s = s.dropna()
    return float(s.iloc[-22] / s.iloc[-253] - 1) * 100 if len(s) > 253 else None


def max_drawdown(s):
    s = s.dropna()
    return float((s / s.cummax() - 1).min() * 100) if len(s) > 20 else None


def late_risk(s):
    """Distance from the 200-day average today and its percentile among the days of the last 5 years (or available):
    alto above the 90th percentile, medio between 70th and 90th, basso below (approved by the user)."""
    s = s.dropna()
    if len(s) < 260:
        return None
    dist = (s / s.rolling(200).mean() - 1).dropna() * 100
    hist = dist.iloc[-LATE_DAYS:]
    today = float(dist.iloc[-1])
    pct = float((hist <= today).mean() * 100)
    return {"dist": today, "percentile": pct, "years": round(len(hist) / 252, 1),
            "level": "alto" if pct > LATE_HIGH else "medio" if pct >= LATE_MID else "basso"}


def fx_effect(fx_pair, n):
    """Part of the EUR return due to the exchange rate over n sessions, for a single-currency underlying:
    a EUR investor gains when the foreign currency strengthens, i.e. when EURxxx falls."""
    s = fx_pair.dropna()
    return float(s.iloc[-1 - n] / s.iloc[-1] - 1) * 100 if len(s) > n else None


def terciles(values):
    """{name: "forte" | "medio" | "debole"} from the 12-1 momentum of the categories of one date."""
    v = {k: x for k, x in values.items() if x is not None and not math.isnan(x)}
    if len(v) < 3:
        return {}
    hi, lo = np.quantile(list(v.values()), 2 / 3), np.quantile(list(v.values()), 1 / 3)
    return {k: "forte" if x >= hi else "debole" if x <= lo else "medio" for k, x in v.items()}


def months_in_tercile(history, name):
    """Consecutive months (newest first in history: [{name: tercile}]) in which a category kept today's tercile."""
    if not history or name not in history[0]:
        return 0
    now, n = history[0][name], 0
    for h in history:
        if h.get(name) != now:
            break
        n += 1
    return n


def base(sym):
    """'ASML.AS' -> 'ASML', 'NVDA' -> 'NVDA': stocks compared by their symbol, an approximation for foreign listings."""
    return str(sym).split(".")[0].upper()


def overlap(etf_top, mine):
    """Over the ETF's first 10 holdings: sum of min(weight in the ETF, weight in my portfolio) in points (the rule), and
    the share of the ETF made of companies I already own (information only, approved as option (a)).
    etf_top: [{"key", "name", "weight" 0-1}]; mine: {company key: weight 0-1}.
    Returns (points, share %, [{"name", "etf" %, "mine" %}])."""
    pts, share, common = 0.0, 0.0, []
    for h in etf_top:
        m = mine.get(h["key"], 0.0)
        if m > 0:
            pts += min(h["weight"], m)
            share += h["weight"]
            common.append({"name": h["name"], "etf": h["weight"] * 100, "mine": m * 100})
    return pts * 100, share * 100, common


def moves_with_text(category, c):
    """The radar sentence on the most similar category of the last 6 months (threshold MOVES_WITH)."""
    if round(c, 2) >= MOVES_WITH:                 # compared as shown (0,698 is written 0,70)
        return f"negli ultimi 6 mesi si è mosso come {category} (correlazione {it(c, 2)})"
    return f"non si muove in modo simile a nessun'altra categoria (correlazione massima {it(c, 2)} con {category})"


def fit_verdict(ov, corr, before, after):
    """'si sovrappone' / 'diversifica' / 'neutro' and the rule that decided (rules approved by the user).
    before/after: {"tech", "usa", "usd"} in % of my portfolio, before and after investing 10% in the ETF."""
    diff = {k: after[k] - before[k] for k in before if before.get(k) is not None and after.get(k) is not None}
    top = max(before, key=lambda k: before[k] if before[k] is not None else -1)
    if ov is not None and ov >= OVERLAP_HIGH:
        return "si sovrappone", f"sovrapposizione {it(ov)} punti (soglia {it(OVERLAP_HIGH, 0)})"
    if corr is not None and corr >= CORR_HIGH:
        return "si sovrappone", f"correlazione {it(corr, 2)} (soglia {it(CORR_HIGH, 2)})"
    if diff.get(top, 0) >= CONC_UP:
        return "si sovrappone", f"farebbe salire la tua concentrazione più alta ({top}) di {it(diff[top])} punti"
    lowers = [k for k, d in diff.items() if d <= -CONC_DOWN]
    if (ov is not None and ov < OVERLAP_LOW and corr is not None and corr < CORR_LOW and lowers
            and all(d <= CONC_OTHER for d in diff.values())):
        return "diversifica", (f"sovrapposizione {it(ov)} punti, correlazione {it(corr, 2)}, "
                               f"riduce {', '.join(lowers)} di almeno {it(CONC_DOWN, 0)} punto")
    ov_t = f"sovrapposizione {it(ov)} punti" if ov is not None else "sovrapposizione non calcolabile"
    corr_t = f"correlazione {it(corr, 2)}" if corr is not None else "correlazione non calcolabile"
    return "neutro", f"{ov_t}, {corr_t}: non valgono del tutto né «si sovrappone» né «diversifica»"


# ---------------------------------------------------------------- public data, once a day

def _universe():
    with open(UNIVERSE) as f:
        return json.load(f)["etfs"]


def _proxy_info(sym):
    """Top holdings {symbol: weight}, P/E and the long price history of a US equivalent (Yahoo)."""
    import yfinance as yf
    out = {"top": {}, "names": {}, "pe": None}
    try:
        t = yf.Ticker(sym)
        h = t.funds_data.top_holdings
        out["top"] = {str(k): float(v) for k, v in h["Holding Percent"].items()}
        if "Name" in h:
            out["names"] = {str(k): str(v) for k, v in h["Name"].items()}
        out["pe"] = (t.info or {}).get("trailingPE")
    except Exception:
        pass
    return out


def build_public():
    """Everything public of the ETF tab (a few minutes the first time each day)."""
    from server import download, news           # local import: server imports this module's users
    U = _universe()
    t0 = time.time()
    mi = [e["justetf"]["tickerMI"] + ".MI" for e in U if e["justetf"].get("tickerMI")]
    de = [e["justetf"]["tickerDE"] + ".DE" for e in U if e["justetf"].get("tickerDE")]
    proxies = sorted({e["usProxy"] for e in U if e.get("usProxy")})
    fxs = sorted(set(FX_PAIR.values()))
    data = download(mi + de + proxies + fxs, period="7y", interval="1d")
    close = {t: df["Close"].dropna() for t, df in data.items() if "Close" in df and len(df["Close"].dropna())}
    for s in close.values():
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    eurusd = close.get("EURUSD=X")
    import etf_holdings
    try:
        hold = etf_holdings.public(U)
    except Exception:
        log.exception("ETF holdings failed")
        hold = {}
    pinfo = {}
    for p in proxies:
        pinfo[p] = _proxy_info(p)
        time.sleep(0.3)
    rows, series = [], {}
    for e in U:
        j = e["justetf"]
        s_mi = close.get(j["tickerMI"] + ".MI") if j.get("tickerMI") else None
        s_de = close.get(j["tickerDE"] + ".DE") if j.get("tickerDE") else None
        prox = close.get(e["usProxy"]) if e.get("usProxy") else None
        prox_eur = to_eur(prox, eurusd) if prox is not None and eurusd is not None else None
        s, src = pick_history(s_mi, s_de, prox_eur, (f"Borsa Italiana ({j.get('tickerMI')}.MI)", f"Xetra ({j.get('tickerDE')}.DE)",
                                                     f"ETF americano {e.get('usProxy')} convertito in euro con il cambio giornaliero"))
        longest = max([x for x in (s, prox_eur) if x is not None], key=len, default=None)
        long_src = (f"ETF americano {e.get('usProxy')} in euro" if longest is prox_eur and longest is not s else src)
        r = {"isin": e["isin"], "name": j.get("name"), "category": e["category"], "group": e["group"], "yahoo": e.get("yahoo"),
             "historySource": src, "usProxy": e.get("usProxy"), "underlyingCurrency": e["underlyingCurrency"], "note": e.get("note"),
             "ter": j.get("ter"), "sizeEurM": j.get("sizeEurM"), "distribution": j.get("distribution"), "replication": j.get("replication"),
             "hedge": j.get("hedge"), "launch": j.get("launch"), "legal": j.get("legal"), "provider": j.get("provider"), "index": j.get("index"),
             "justetf": {"source": j.get("source"), "date": j.get("date"), "holdingsDate": j.get("holdingsDate"), "replicationMethod": j.get("replicationMethod"),
                         "top10": j.get("top10"), "countries": j.get("countries"), "sectors": j.get("sectors")},
             "stale": (date.today() - date.fromisoformat(j["date"])).days > STALE_DAYS if j.get("date") else True,
             "pe": (pinfo.get(e.get("usProxy")) or {}).get("pe"),
             "historyYears": round(len(s) / 252, 1) if s is not None else None,               # this ETF (or its fallback)
             "fallback": bool(src) and not src.startswith("Borsa Italiana") or "incompleto" in (src or ""),
             "launchIso": launch_iso(j.get("launch")),
             "longYears": round(len(longest) / 252, 1) if longest is not None else None, "longSource": long_src}
        if s is not None:
            r.update({k: ret(s, n) for k, n in H.items()})
            r["mom12_1"] = momentum_12_1(s)
            last3 = s.iloc[-756:]
            r["vol"] = float(s.pct_change().iloc[-252:].std() * math.sqrt(252) * 100) if len(s) > 60 else None
            r["maxDD3y"] = max_drawdown(last3)
            r["maxDDhist"] = max_drawdown(longest) if longest is not None else None
            sma50, sma200 = s.rolling(50).mean().iloc[-1], s.rolling(200).mean().iloc[-1]
            r["vs50"] = float(s.iloc[-1] / sma50 - 1) * 100 if not math.isnan(sma50) else None
            r["vs200"] = float(s.iloc[-1] / sma200 - 1) * 100 if not math.isnan(sma200) else None
            r["late"] = late_risk(s)
            cur = e["underlyingCurrency"]
            pair = close.get(FX_PAIR.get(cur, ""))
            r["fx"] = {k: fx_effect(pair, n) for k, n in H.items()} if pair is not None and "hedged" not in cur else None
            r["fxNote"] = ("cambio coperto (hedged): effetto cambio circa zero" if "hedged" in cur
                           else "sottostante in più valute: effetto cambio non separabile" if r["fx"] is None else f"effetto cambio EUR/{cur}")
            series[e["isin"]] = s
        tech = next((p for n, p in j.get("sectors") or [] if n == "Technology"), 0.0)
        usa = next((p for n, p in j.get("countries") or [] if n == "United States"), 0.0)
        r["mix"] = {"tech": tech, "usa": usa, "usd": 0.0 if "hedged" in e["underlyingCurrency"] else (100.0 if e["underlyingCurrency"] == "USD" else usa)}
        h = hold.get(e["isin"]) or {}
        r["holdings"] = {k: h.get(k) for k in ("label", "source", "asOf", "fetched", "none", "top")}
        r["top"] = (pinfo.get(e.get("usProxy")) or {}).get("top") or {}     # US equivalent: only for the radar's "why"
        r["topNames"] = (pinfo.get(e.get("usProxy")) or {}).get("names") or {}
        rows.append(r)
    # ---- categories: the first ETF of each category represents it
    rep = {}
    for r in rows:
        if r["isin"] in series:
            rep.setdefault(r["category"], r)
    cats = list(rep)
    px = pd.DataFrame({c: series[rep[c]["isin"]] for c in cats}).sort_index().ffill()
    # momentum terciles month by month (for "da quanti mesi"), newest first
    months = px.index.to_series().groupby([px.index.year, px.index.month]).last().values[-37:]
    hist = []
    for d in reversed(months):
        sub = px.loc[:d]
        hist.append(terciles({c: momentum_12_1(sub[c]) for c in cats}))
    corr = px.pct_change().iloc[-126:].corr()
    vwce = next((r for r in rows if r["isin"] == "IE00BK5BQT80"), None)
    rot = []
    for c in cats:
        r = rep[c]
        r1w = ret(series[r["isin"]], 5)
        b1m, b1w = (vwce or {}).get("r1m"), ret(series[vwce["isin"]], 5) if vwce else None
        if r.get("r1m") is not None and r1w is not None and b1m is not None and b1w is not None:
            x, y = r["r1m"] - b1m, r1w - b1w
            rot.append({"name": c, "kind": "category", "n": 1, "rs1m": x, "rs1w": y,
                        "quadrant": ("Leading" if y >= 0 else "Weakening") if x >= 0 else ("Improving" if y >= 0 else "Lagging")})
    for r in rows:                                       # tercile and months for every ETF, from its category
        r["momTercile"] = hist[0].get(r["category"]) if hist else None
        r["momMonths"] = months_in_tercile(hist, r["category"])
    # ---- radar: 5 strongest and 5 weakest categories on the 3-month return in EUR, with the computed "why"
    ranked = sorted((c for c in cats if rep[c].get("r3m") is not None), key=lambda c: -rep[c]["r3m"])
    radar = {"strong": [], "weak": []}
    for side, names in (("strong", ranked[:5]), ("weak", ranked[-5:][::-1])):
        for c in names:
            radar[side].append(_radar_item(c, rep[c], corr, close, news))
    out = {"generated": datetime.now().isoformat(timespec="seconds"), "rows": rows, "radar": radar, "rotation": rot,
           "test": _test_summary(), "universeDate": max((r["justetf"]["date"] or "") for r in rows), "elapsed": round(time.time() - t0, 1),
           "_weekly": weekly_eur(series), "_holdings": hold}               # kept in memory for the correlation with my portfolio (not sent)
    return out


def _radar_item(cat, r, corr, close, news):
    """The data-derived sentence of one radar category: return, contribution of the first holdings of the US
    equivalent, the category it moved with in the last 6 months, headlines on the first two holdings."""
    from server import download
    item = {"category": cat, "isin": r["isin"], "r3m": r["r3m"], "mom12_1": r.get("mom12_1"), "momTercile": r.get("momTercile"),
            "momMonths": r.get("momMonths"), "late": r.get("late"), "maxDDhist": r.get("maxDDhist"),
            "young": (r.get("longYears") or 0) < YOUNG_YEARS, "longYears": r.get("longYears"), "longSource": r.get("longSource"),
            "fallback": r.get("fallback"), "group": r["group"]}
    parts = [f"{cat}: {sgn(r['r3m'])} in 3 mesi"]
    if r.get("mom12_1") is not None:
        parts[0] += f" (12-1 mesi: {sgn(r['mom12_1'])})"
    top = r.get("top") or {}
    if top and r.get("usProxy"):
        syms = list(top)[:10]
        try:
            d = download(syms + [r["usProxy"]], period="6mo", interval="1d")
            pr = {s: ret(d[s]["Close"].dropna(), 63) for s in syms + [r["usProxy"]] if s in d}
            p_all = pr.get(r["usProxy"])
            contrib = {s: top[s] * pr[s] for s in syms if pr.get(s) is not None}
            two = sorted(contrib, key=lambda s: -contrib[s] if (p_all or 0) > 0 else contrib[s])[:2] if contrib else []
            share = sum(contrib[s] for s in two) / p_all * 100 if p_all and abs(p_all) > 1 and two else 0
            if share >= MIN_SHARE:                       # below 10% the first holdings do not explain the move (e.g. T-bills)
                names = r.get("topNames") or {}
                label = lambda s: f"{names.get(s, base(s))} ({base(s)})"
                item["contrib"] = {"symbols": two, "names": [names.get(x, base(x)) for x in two], "share": share, "proxy": r["usProxy"], "proxyR3m": p_all}
                parts.append(f"{' e '.join(label(x) for x in two)} spiegano il {it(share, 0)}% del {'rialzo' if p_all > 0 else 'ribasso'} "
                             f"(calcolato sull'ETF americano equivalente {r['usProxy']})")
                heads = []
                for s in two:
                    for n in (news(s, 3) or [])[:1]:
                        if n.get("title"):
                            heads.append({"symbol": base(s), "title": n["title"], "publisher": n.get("publisher"), "url": n.get("url")})
                item["news"] = heads
        except Exception:
            log.exception("radar contribution for %s", cat)
    if cat in corr:
        others = corr[cat].drop(cat).dropna().sort_values(ascending=False)
        if len(others):
            item["movesWith"] = {"category": others.index[0], "corr": float(others.iloc[0])}
            parts.append(moves_with_text(others.index[0], float(others.iloc[0])))
    item["sentence"] = ". ".join(p[:1].upper() + p[1:] for p in parts) + "."
    return item


def _test_summary():
    try:
        with open(TEST) as f:
            t = json.load(f)
    except Exception:
        return None
    return {"from": t["from"], "to": t["to"], "conditions": t["conditions"], "control": t["control"],
            "rules": {k: {x: v[x] for x in ("n", "mean3", "median3", "mean6", "checks", "pass", "yearsPositive", "yearsCounted", "firstHalf", "secondHalf", "beatAll")}
                      for k, v in t["rules"].items()},
            "m2Protection": {k: t["m2Protection"][k] for k in ("n", "ddCutCount", "volLowerCount", "verified", "rule")}}


def public():
    """Today's public data, or None while it is being computed in the background (status in _state)."""
    with _lock:
        if _state["day"] == date.today().isoformat() and _state["data"]:
            return _state["data"]
        if not _state["running"]:
            _state["running"] = True
            threading.Thread(target=_job, daemon=True).start()
        return _state["data"]                      # yesterday's copy while today's is computed


def _job():
    try:
        d = build_public()
        with _lock:
            _state.update(day=date.today().isoformat(), data=d, error=None)
        log.info("ETF tab: %d ETFs in %.0fs", len(d["rows"]), d["elapsed"])
    except Exception as e:
        log.exception("ETF tab data failed")
        with _lock:
            _state["error"] = str(e)
    finally:
        with _lock:
            _state["running"] = False


# ---------------------------------------------------------------- personal part: "Ha senso per il mio portafoglio?"

def my_lookthrough(pf, index, holdings):
    """({company key: weight 0-1}, [ISIN of my funds without a composition]) of my portfolio looking inside the funds:
    direct stocks (by ISIN when an ETF lists the same ISIN, otherwise by name); ETFs on the Nasdaq-100 with the index
    weights; every other fund through its first 10 holdings (etf_holdings.py). Leverage counted.
    index: {ticker: (name, weight %)}; holdings: {isin: entry of etf_holdings}."""
    import portfolio
    from etf_holdings import company_key
    total = (pf.get("totals") or {}).get("value") or 0
    out, missing = {}, []
    if not total:
        return out, missing
    by_isin = {i: h["key"] for e in holdings.values() for h in e.get("top") or [] for i in h.get("isins") or []}
    add = lambda k, v: out.__setitem__(k, out.get(k, 0) + v) if k else None
    for p in pf.get("positions") or []:
        w = p["value"] / total * (p.get("leverage") or 1)
        if p.get("sector") == portfolio.LOOK_THROUGH_NDX:
            for name, iw in index.values():
                add(company_key(name), w * iw / 100)
        elif portfolio.is_fund(p["kind"]):
            top = (holdings.get(p.get("isin")) or {}).get("top")
            if top:
                for h in top:
                    add(h["key"], w * h["weight"])
            elif not (holdings.get(p.get("isin")) or {}).get("none", "").startswith("nessuna azione"):
                missing.append(p.get("isin"))
        else:
            add(by_isin.get(p.get("isin")) or company_key(p.get("name") or p.get("ticker")), w)
    return out, missing


def fit(rows, pf, index, port_weekly, etf_weekly, holdings):
    """{isin: {...}} "Ha senso per il mio portafoglio?" for every ETF, and the ISINs of my funds without a composition."""
    conc = (pf.get("concentration") or {})
    pick = lambda dim, name: next((r.get("expPct") or 0 for r in conc.get(dim, []) if r["name"] == name), 0.0)
    before = {"tecnologia": pick("sector", "Tecnologia"), "USA": pick("country", "USA")}
    before["dollaro (stima)"] = before["USA"]            # approximation: the dollar share follows the US share
    mine, missing = my_lookthrough(pf, index, holdings)
    held = {p["isin"]: p for p in pf.get("positions") or []}
    out = {}
    for r in rows:
        top = (holdings.get(r["isin"]) or {}).get("top")
        ov, share, common = overlap(top, mine) if top else (None, None, [])
        c = None
        w = etf_weekly.get(r["isin"])
        if w is not None and len(port_weekly) > 30:
            j = pd.concat([port_weekly, w], axis=1, join="inner").dropna().iloc[-104:]
            if len(j) > 30:
                c = float(j.iloc[:, 0].corr(j.iloc[:, 1]))
        mix = r["mix"]
        after = {"tecnologia": (1 - FIT_SHARE) * before["tecnologia"] + FIT_SHARE * mix["tech"],
                 "USA": (1 - FIT_SHARE) * before["USA"] + FIT_SHARE * mix["usa"],
                 "dollaro (stima)": (1 - FIT_SHARE) * before["dollaro (stima)"] + FIT_SHARE * mix["usd"]}
        verdict, why = fit_verdict(ov, c, before, after)
        notes = []
        if (r.get("ter") or 0) > TER_HIGH:
            notes.append(f"costoso: TER {it(r['ter'], 2)}%, sopra lo {it(TER_HIGH, 2)}%")
        if r.get("sizeEurM") is not None and r["sizeEurM"] < SIZE_SMALL:
            notes.append("patrimonio sotto i 100 milioni: rischio di chiusura e spread più alti")
        out[r["isin"]] = {"verdict": verdict, "why": why, "overlap": ov, "share": share, "common": common, "corr": c,
                          "before": before, "after": after, "notes": notes, "held": r["isin"] in held,
                          "heldWeight": held[r["isin"]]["value"] / ((pf.get("totals") or {}).get("value") or 1) * 100 if r["isin"] in held else None}
    return out, missing


EQUITY_GROUPS = ("Globali", "Aree e paesi", "Settori", "Stili e fattori")
DEFENSIVE = lambda r: r["group"] == "Obbligazionari" or r["category"].startswith("Oro")
DIVERSIFY_N = 3


def diversify(rows, fits):
    """"Cosa diversifica di più il tuo portafoglio" (rules approved by the user): investing 10% of the portfolio, the ETFs
    that lower most the highest of tecnologia / USA / dollaro. Left out: themes, leveraged products, and every ETF that
    would raise any of the three. Same effect on the highest (to 0.1 points) -> the one lowering more the other two,
    then the lower TER. One ETF per category. Two lists: 3 equity ETFs, 3 bond or defensive ones (gold included).
    An effect on the portfolio, not a forecast of returns."""
    cands = []
    for r in rows:
        f = fits.get(r["isin"])
        if not f or r["group"] == "Temi" or (r.get("leverage") or 1) != 1:
            continue
        d = {k: f["after"][k] - f["before"][k] for k in f["before"]}
        if any(v > 0 for v in d.values()):
            continue
        top = max(f["before"], key=f["before"].get)
        cands.append((round(d[top], 1), round(sum(v for k, v in d.items() if k != top), 1), r.get("ter") or 9, r, d, top, f))
    cands.sort(key=lambda c: c[:3])
    out = {"equity": [], "defensive": []}
    seen = set()
    for _, _, _, r, d, top, f in cands:
        side = "equity" if r["group"] in EQUITY_GROUPS else "defensive" if DEFENSIVE(r) else None
        if not side or r["category"] in seen or len(out[side]) >= DIVERSIFY_N:
            continue
        seen.add(r["category"])
        parts = [f"{k} da {it(f['before'][k])}% a {it(f['after'][k])}%" for k in f["before"]]
        out[side].append({"isin": r["isin"], "category": r["category"], "name": r.get("name"), "delta": d, "top": top,
                          "ter": r.get("ter"), "sizeEurM": r.get("sizeEurM"),
                          "sentence": f"Con il 10% del portafoglio in questo ETF: {', '.join(parts)}."})
    return out


def weekly_eur(rows_series):
    return {k: s.resample("W-FRI").last().pct_change().dropna() for k, s in rows_series.items()}
