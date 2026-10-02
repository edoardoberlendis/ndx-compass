"""My investment rules (plan phase 14): a few limits, like the mandate of a private bank, checked against the portfolio.

The rules are personal data: they live in portafoglio/regole.json (outside Git) and are edited from the dashboard.
Until the user saves them, the proposed starting values below are used and marked as "not confirmed".

How weights are measured:
- single stock / ETF: share of the portfolio VALUE in EUR;
- theme, sector, country: share of the EFFECTIVE EXPOSURE (a 3x product counts three times), as in the concentration
  table of the Portafoglio tab; ETFs on the Nasdaq-100 are split among the index sectors there;
- leveraged products: both the share of the value and the share of the effective exposure.
Leveraged products are judged only by the two leverage limits, not by the single-position ones.
"""
from __future__ import annotations

import json
import os

import portfolio

FILE = os.path.join(portfolio.PORTFOLIO_DIR, "regole.json")

# proposed starting values (percent), shown in the rules page next to each field
DEFAULTS = {
    "stock": 10,          # one stock, % of value
    "etfBroad": 35,       # one broad ETF (Nasdaq-100, world...), % of value
    "etfOther": 15,       # one thematic / sector ETF or ETC, % of value
    "theme": 25,          # one theme, % of effective exposure
    "sector": 50,         # one sector, % of effective exposure
    "country": 80,        # one country, % of effective exposure
    "levValue": 5,        # leveraged products, % of value
    "levExposure": 15,    # leveraged products, % of effective exposure
    "tradeRisk": 1,       # maximum loss of one trade if the stop is hit, % of the portfolio (used for the position size)
    "near": 90,           # "close to the limit" from this % of the limit
}
RANGE = {"tradeRisk": (0.1, 10), "near": (50, 100)}       # every other limit: 1–100
SKIP = {"Senza tema", "Non classificato", portfolio.LOOK_THROUGH_NDX}
DIMS = (("theme", "Tema"), ("sector", "Settore"), ("country", "Paese"))


def load():
    """{"limits", "broad": ISINs marked as broad ETFs (None = not chosen yet), "confirmed"}."""
    try:
        with open(FILE) as f:
            saved = json.load(f)
    except FileNotFoundError:
        saved = None
    except Exception:
        saved = None                      # unreadable file: fall back to the proposed values, shown as not confirmed
    limits = dict(DEFAULTS)
    if saved:
        limits.update({k: v for k, v in (saved.get("limits") or {}).items() if k in DEFAULTS and isinstance(v, (int, float))})
    return {"limits": limits, "broad": saved.get("broad") if saved else None, "confirmed": bool(saved)}


def save(limits, broad):
    """Validate and write portafoglio/regole.json. Raises ValueError with an Italian message."""
    out = {}
    for k in DEFAULTS:
        v = (limits or {}).get(k)
        lo, hi = RANGE.get(k, (1, 100))
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
            raise ValueError(f"Valore non valido per «{k}»: deve essere un numero tra {lo} e {hi}.")
        out[k] = round(float(v), 2)
    broad = sorted({str(x) for x in (broad or []) if isinstance(x, str) and len(x) <= 20})
    os.makedirs(portfolio.PORTFOLIO_DIR, exist_ok=True)
    with open(FILE + ".tmp", "w") as f:
        json.dump({"limits": out, "broad": broad}, f, indent=1)
    os.replace(FILE + ".tmp", FILE)
    return load()


def is_broad(p, broad):
    """Broad ETF: the user's choice if saved, otherwise a guess (unleveraged fund split like the Nasdaq-100 or without a theme)."""
    if not portfolio.is_fund(p["kind"]) or (p.get("leverage") or 1) > 1:
        return False
    if broad is not None:
        return p["isin"] in broad
    return p.get("sector") == portfolio.LOOK_THROUGH_NDX or p.get("themes") == ["Senza tema"]


def evaluate(pf):
    """Rules + the checks on a portfolio snapshot (portfolio.snapshot()). Without positions: only the rules."""
    r = load()
    L = r["limits"]
    out = {"limits": L, "defaults": DEFAULTS, "confirmed": r["confirmed"], "etfs": [], "checks": [],
           "over": 0, "near": 0, "ok": 0}
    positions = pf.get("positions") or []
    total = (pf.get("totals") or {}).get("value") or 0
    exposure = (pf.get("totals") or {}).get("exposure") or 0
    if not positions or not total:
        return out

    def add(kind, label, value, limit_key, basis):
        limit = L[limit_key]
        status = "over" if value > limit + 1e-9 else "near" if value >= limit * L["near"] / 100 else "ok"
        out["checks"].append({"kind": kind, "label": label, "value": value, "limit": limit, "limitKey": limit_key,
                              "basis": basis, "status": status, "excess": value - limit})
        out[status] += 1

    lev = [p for p in positions if (p.get("leverage") or 1) > 1]
    add("lev", "Prodotti a leva", sum(p["value"] for p in lev) / total * 100, "levValue", "del valore")
    if exposure:
        add("lev", "Prodotti a leva", sum(p["exposure"] for p in lev) / exposure * 100, "levExposure", "dell'esposizione effettiva")
    for p in positions:
        fund = portfolio.is_fund(p["kind"])
        if fund and (p.get("leverage") or 1) <= 1:
            out["etfs"].append({"isin": p["isin"], "name": p["name"], "broad": is_broad(p, r["broad"])})
        if (p.get("leverage") or 1) > 1:
            continue
        w = p["value"] / total * 100
        name = p.get("ticker") or p["name"]
        if not fund:
            add("stock", f"Titolo {name}", w, "stock", "del valore")
        elif is_broad(p, r["broad"]):
            add("etf", f"ETF ampio {p['name']}", w, "etfBroad", "del valore")
        else:
            add("etf", f"ETF/ETC {p['name']}", w, "etfOther", "del valore")
    for dim, word in DIMS:
        for row in (pf.get("concentration") or {}).get(dim, []):
            if row["name"] not in SKIP and row.get("expPct") is not None:
                add(dim, f"{word} {row['name']}", row["expPct"], dim, "dell'esposizione effettiva")
    order = {"over": 0, "near": 1, "ok": 2}
    out["checks"].sort(key=lambda c: (order[c["status"]], -c["value"] / c["limit"]))
    return out
