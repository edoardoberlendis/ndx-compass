"""My investment rule (plan phases 14 and 21): the maximum risk of one trade, as a percentage of the portfolio.

The weight limits of phase 14 (single stock, ETF, theme, sector, country, leverage) were removed in phase 21 at the
user's request, together with the "Rispetto delle regole" box. What is left is used to compute how many shares to buy
in the "Decisione" section of the stock detail: if the stop is hit, the loss is at most this share of the portfolio.

Personal data: portafoglio/regole.json (outside Git), edited from the stock detail. Older files may still contain the
removed limits: they are ignored, never deleted.
"""
from __future__ import annotations

import json
import os

import portfolio

FILE = os.path.join(portfolio.PORTFOLIO_DIR, "regole.json")
DEFAULT_RISK = 1.0          # % of the portfolio lost at most if the stop of one trade is hit
RISK_RANGE = (0.1, 10.0)


def load():
    """{"tradeRisk", "confirmed"}: confirmed is False until the user saves a value."""
    try:
        with open(FILE) as f:
            saved = json.load(f)
    except Exception:
        saved = None
    v = ((saved or {}).get("limits") or {}).get("tradeRisk")
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and RISK_RANGE[0] <= v <= RISK_RANGE[1]
    return {"tradeRisk": float(v) if ok else DEFAULT_RISK, "default": DEFAULT_RISK, "confirmed": bool(ok)}


def save_trade_risk(value):
    """Write the risk per trade in portafoglio/regole.json, keeping whatever else the file holds. Raises ValueError."""
    lo, hi = RISK_RANGE
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not lo <= value <= hi:
        raise ValueError(f"Il rischio per operazione deve essere un numero tra {lo:g} e {hi:g} (% del portafoglio).".replace(".", ",", 1))
    try:
        with open(FILE) as f:
            data = json.load(f)
    except Exception:
        data = {}
    data.setdefault("limits", {})["tradeRisk"] = round(float(value), 2)
    os.makedirs(portfolio.PORTFOLIO_DIR, exist_ok=True)
    with open(FILE + ".tmp", "w") as f:
        json.dump(data, f, indent=1)
    os.replace(FILE + ".tmp", FILE)
    return load()
