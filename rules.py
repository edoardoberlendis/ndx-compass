"""My settings for the position size (plan phases 14, 21 and 22).

- tradeRisk: the maximum loss of one trade if the stop is hit, as a percentage of the portfolio (proposed 1%);
- settle: the currency in which I settle US stocks at Fineco, "EUR" (default: Fineco converts and applies its
  exchange spread, 0.0033 on EUR/USD, when buying and when selling) or "USD" (no spread).

The weight limits of phase 14 were removed in phase 21. Personal data: portafoglio/regole.json (outside Git), edited
from the stock detail. Older files may still contain the removed limits: they are ignored, never deleted.
"""
from __future__ import annotations

import json
import os

import portfolio

FILE = os.path.join(portfolio.PORTFOLIO_DIR, "regole.json")
DEFAULT_RISK = 1.0          # % of the portfolio lost at most if the stop of one trade is hit
RISK_RANGE = (0.1, 10.0)
SETTLE = ("EUR", "USD")
FX_SPREAD = 0.0033          # Fineco's exchange spread on EUR/USD when settling a US stock in euro


def _read():
    try:
        with open(FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def load():
    """{"tradeRisk", "settle", "spread", "default", "confirmed"}: confirmed is False until a risk value is saved."""
    saved = _read()
    v = (saved.get("limits") or {}).get("tradeRisk")
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and RISK_RANGE[0] <= v <= RISK_RANGE[1]
    settle = saved.get("settle") if saved.get("settle") in SETTLE else "EUR"
    return {"tradeRisk": float(v) if ok else DEFAULT_RISK, "settle": settle, "spread": FX_SPREAD if settle == "EUR" else 0.0,
            "default": DEFAULT_RISK, "confirmed": bool(ok)}


def _write(data):
    os.makedirs(portfolio.PORTFOLIO_DIR, exist_ok=True)
    with open(FILE + ".tmp", "w") as f:
        json.dump(data, f, indent=1)
    os.replace(FILE + ".tmp", FILE)


def save_trade_risk(value):
    """Write the risk per trade in portafoglio/regole.json, keeping whatever else the file holds. Raises ValueError."""
    lo, hi = RISK_RANGE
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not lo <= value <= hi:
        raise ValueError("Il rischio per operazione deve essere un numero tra 0,1 e 10 (% del portafoglio).")
    data = _read()
    data.setdefault("limits", {})["tradeRisk"] = round(float(value), 2)
    _write(data)
    return load()


def save_settle(value):
    """Write the settlement currency of US stocks ("EUR" or "USD"). Raises ValueError."""
    if value not in SETTLE:
        raise ValueError("La valuta di regolamento deve essere EUR o USD.")
    data = _read()
    data["settle"] = value
    _write(data)
    return load()
