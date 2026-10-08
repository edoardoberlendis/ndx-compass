"""Verdict of the "Decisione" section (decision.py) and the quantity to buy, on made-up stocks."""
from datetime import datetime, timedelta

import decision

STRONG = {"revenueGrowth": 0.20, "earningsGrowth": 0.25, "profitMargins": 0.30, "freeCashflow": 30, "totalRevenue": 100,
          "totalDebt": 10, "totalCash": 50}
WEAK = {"revenueGrowth": -0.05, "earningsGrowth": -0.20, "profitMargins": 0.02, "freeCashflow": -5, "totalRevenue": 100,
        "totalDebt": 80, "totalCash": 5}
AN = {"epsRev30": 0.5, "up30": 1, "down30": 0}


def row(price=100.0, vs20=2.0, vs200=15.0, rsi=55.0, earnings_in=None, **kw):
    r = {"price": price, "vsSma20": vs20, "vsSma200": vs200, "rsi": rsi, "sma20": price / (1 + vs20 / 100),
         "sma200": price / (1 + vs200 / 100), "weight": 1.0, "sector": "Tecnologia",
         "earningsTs": (datetime.now() + timedelta(days=earnings_in)).timestamp() if earnings_in is not None else None}
    r.update(kw)
    return r


def ta(price=100.0, high=130.0):
    return {"atr": 2.0, "sma50": price * 0.95, "low": {"v": price * 0.93, "date": "2026-09-20"},
            "high52": {"v": high, "date": "2026-07-01"}, "range": {"hi": price * 1.2, "lo": price * 0.8, "width": 50.0, "days": 30},
            "patterns": [], "groups": []}


def verdict(r, info=STRONG, t=None, pf=None, valuation=None):
    return decision.decide("TEST", r, info, valuation or {"label": "In linea"}, AN, t if t is not None else ta(r["price"]),
                           None, [], pf, 1.10, capital=10000)


def test_all_rules_satisfied_gives_entra_ora():
    d = verdict(row())
    assert d["verdict"]["label"] == "Entra ora"
    assert d["verdict"]["decidedBy"] == "tutte"
    assert d["company"]["summary"] == "solida"


def test_weak_company_gives_evita():
    d = verdict(row(), info=WEAK, valuation={"label": "Cara"})
    assert d["verdict"]["label"] == "Evita" and d["verdict"]["decidedBy"] == "D1"


def test_earnings_within_5_days_gives_attendi():
    d = verdict(row(earnings_in=3))
    assert d["verdict"]["label"].startswith("Attendi: trimestrale il") and d["verdict"]["decidedBy"] == "D2"


def test_below_200_day_average_gives_attendi():
    d = verdict(row(vs200=-5.0))
    assert d["verdict"]["label"] == "Attendi" and d["verdict"]["decidedBy"] == "D4"


def test_extended_stock_gives_pullback_order():
    d = verdict(row(vs20=12.0))
    assert d["verdict"]["label"] == "Entra su ritracciamento" and d["verdict"]["decidedBy"] == "D5"
    assert d["plans"]["pullback"]["entry"] < 100


def test_near_52_week_high_is_attendi_not_breakout():
    """Phase 21: the breakout failed the pattern test, so near the high the verdict is Attendi, never 'Entra su rottura'."""
    d = verdict(row(), t=ta(high=101.5))
    assert d["verdict"]["label"] == "Attendi: a ridosso del massimo" and d["verdict"]["decidedBy"] == "D6"
    assert d["plans"]["breakouts"], "the breakout level stays visible as information"


def test_no_weight_limit_rule_any_more():
    d = verdict(row())
    assert "D3" not in [c["id"] for c in d["checks"]]


def test_owned_stock_takes_the_position_action():
    pf = {"positions": [{"ticker": "TEST", "isin": "XX0000000001", "value": 1000, "exposure": 1000, "sector": "Tecnologia",
                         "action": {"action": "Mantieni", "label": "Mantieni", "reasons": []}}],
          "totals": {"value": 10000, "exposure": 10000}, "rules": {"tradeRisk": 1.0}, "fx": 1.10}
    d = verdict(row(), pf=pf)
    assert d["verdict"]["owned"] and d["verdict"]["label"] == "Mantieni" and d["verdict"]["decidedBy"] == "posizione"


def test_quantity_without_spread_settling_in_dollars():
    # 10,000 EUR x 1% = 100 EUR; entry 100 $, stop 95 $, fx 1.10 -> 5 $ = 4.545 EUR per share -> 22 shares
    q = decision.quantity_eur(100, 100, 95, 1.10, 0.0)
    assert q["qty"] == 22 and abs(q["perShareEur"] - 5 / 1.10) < 1e-9
    assert decision.quantity_eur(100, 100, 100, 1.10)["qty"] == 0          # no risk: no quantity
    assert decision.quantity_eur(10_000, 100, 99.9, 1.10)["qty"] > 100_000  # a very tight stop: huge quantity, no cap any more


def test_quantity_with_fineco_exchange_spread():
    # settling in euro: bought at fx - 0.0033, sold at fx + 0.0033 -> a bigger loss per share, fewer shares
    q = decision.quantity_eur(500, 352.07, 323.27, 1.1202, 0.0033)
    per = 352.07 / (1.1202 - 0.0033) - 323.27 / (1.1202 + 0.0033)
    assert abs(q["perShareEur"] - per) < 1e-9 and q["qty"] == int(500 // per) == 18
    assert decision.quantity_eur(500, 352.07, 323.27, 1.1202, 0.0)["qty"] == 19
    assert q["lossEur"] <= 500


def test_plan_quantity_uses_trade_risk_and_spread():
    d = verdict(row())
    p = d["plans"]["now"]
    st = next(o for o in p["opts"] if o["id"] == p["def"])
    assert p["qty"] == st["qty"] == decision.quantity_eur(10000 * 1.0 / 100, p["entry"], p["stop"], 1.10, 0.0033)["qty"]
