"""Proposed actions on my positions (actions.py) and the indicative tax estimate, on made-up positions."""
from datetime import date, datetime, timedelta

import actions


def pos(name="AAA", kind="Azione", value=1000.0, price=50.0, cost_price=40.0, lev=1, ticker=None):
    return {"name": name, "isin": ("IT" + name * 4)[:12], "ticker": ticker or name, "kind": kind, "value": value,
            "cost": value * cost_price / price, "price": price, "costPrice": cost_price, "leverage": lev, "exposure": value * lev,
            "sector": "Tecnologia", "themes": [], "country": "USA", "currency": "USD"}


def run(positions, rows=None, sma=None, an=None, first=None):
    pf = {"positions": positions, "totals": {"value": sum(p["value"] for p in positions)}}
    summary = actions.evaluate(pf, {"rows": rows or {}, "sma200": sma or {}, "analysts": an or {}, "firstSeen": first or {}})
    return summary, {p["name"]: p["action"] for p in positions}


def test_nothing_fired_is_mantieni():
    _, a = run([pos()])
    assert a["AAA"]["action"] == "Mantieni"
    assert "R1" not in [r["id"] for r in a["AAA"]["rules"]] and "A3" not in [r["id"] for r in a["AAA"]["rules"]]


def test_stop_broken_is_rivedi():
    p = pos(price=50)
    actions.save(p["isin"], {"why": "x", "stop": 55})
    _, a = run([p])
    assert a["AAA"]["action"] == "Rivedi la tesi" and any("stop rotto" in r for r in a["AAA"]["reasons"])


def test_target_reached_has_its_label_and_tax():
    p = pos(price=50, cost_price=40)
    actions.save(p["isin"], {"why": "x", "target": 48})
    _, a = run([p])
    assert a["AAA"]["label"] == "Rivedi · target raggiunto"
    assert a["AAA"]["tax"]["gain"] > 0 and abs(a["AAA"]["tax"]["tax"] - a["AAA"]["tax"]["gain"] * 0.26) < 1e-6


def test_v6_wording_does_not_suggest_selling():
    p = pos(price=20, cost_price=40)
    _, a = run([p])
    v6 = [r for r in a["AAA"]["reasons"] if "prezzo di carico" in r][0]
    assert "la tesi è ancora valida? Decidi in base alle prospettive, non al prezzo pagato" in v6
    assert "vend" not in v6.lower()


def test_accumula_needs_target_weight_and_no_earnings():
    p = pos(value=100)
    q = pos(name="BBB", value=9900)
    actions.save(p["isin"], {"why": "x", "weight": 5})
    _, a = run([p, q])
    assert a["AAA"]["action"] == "Accumula"
    soon = (datetime.now() + timedelta(days=2)).timestamp()
    _, a = run([pos(value=100), pos(name="BBB", value=9900)], rows={"AAA": {"earningsTs": soon}})
    assert a["AAA"]["action"] == "Mantieni" and any(n.startswith("Accumula dopo la trimestrale") for n in a["AAA"]["notes"])


def test_review_silences_until_a_new_reason():
    p = pos(price=50)
    actions.save(p["isin"], {"why": "x", "stop": 55})
    actions.review(p["isin"], "il calo è del settore", ["V1"])
    s, a = run([p])
    assert a["AAA"]["action"] == "Mantieni" and a["AAA"]["silenced"] and s["silenced"] == 1
    _, a = run([p], sma={"AAA": 60})                       # a new reason (below the 200-day average) brings it back
    assert a["AAA"]["action"] == "Rivedi la tesi" and not a["AAA"]["silenced"]


# ---------------------------------------------------------------- tax estimate

def test_tax_on_a_share_gain_without_zainetto():
    t = actions.tax_estimate(pos(value=1000, price=50, cost_price=40), 1000, True)
    assert round(t["gain"], 2) == 200 and round(t["tax"], 2) == 52 and "zainetto" in t["text"]


def test_zainetto_reduces_the_tax_on_shares_and_etc():
    fiscal = {"losses": 150.0, "expiry": "2027-12-31"}
    for kind in ("Azione", "ETC"):
        t = actions.tax_estimate(pos(kind=kind, value=1000, price=50, cost_price=40), 1000, True, fiscal)
        assert round(t["lossesUsed"], 2) == 150 and round(t["tax"], 2) == 13      # (200 - 150) x 26%


def test_zainetto_never_used_for_etf_gains():
    t = actions.tax_estimate(pos(kind="ETF", value=1000, price=50, cost_price=40), 1000, True, {"losses": 150.0, "expiry": None})
    assert t["lossesUsed"] == 0 and round(t["tax"], 2) == 52 and "reddito di capitale" in t["text"]


def test_a_loss_pays_no_tax():
    t = actions.tax_estimate(pos(value=1000, price=40, cost_price=50), 1000, True)
    assert t["gain"] < 0 and t["tax"] == 0


def test_fiscal_file_round_trip(private_folder):
    actions.save_fiscal(1200.5, "2028-12-31")
    assert actions.load_fiscal() == {"losses": 1200.5, "expiry": "2028-12-31"}
    actions.save_fiscal(None, None)
    assert actions.load_fiscal()["losses"] is None
