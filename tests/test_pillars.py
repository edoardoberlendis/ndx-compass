"""Pillars of the thesis (pillars.py) and their saving in the thesis (actions.py). Made-up data only."""
from datetime import date

import pytest

import actions
import pillars

Y = lambda fy, rev, oi=None: {"fy": fy, "revenue": rev, "operatingIncome": oi}


def test_revenue_uses_the_last_two_annual_reports():
    years = [Y("2024-12-31", 100), Y("2025-12-31", 112), Y("2023-12-31", 90)]
    st, why = pillars.revenue_growth(years)
    assert st == "ok" and "+12,0%" in why and "dic 2025" in why
    assert pillars.revenue_growth([Y("2024-12-31", 100), Y("2025-12-31", 109)])[0] == "ko"
    assert pillars.revenue_growth([Y("2025-12-31", 109)])[0] == "na"
    assert pillars.revenue_growth([Y("2024-12-31", 100), Y("2025-12-31", 106)], threshold=5)[0] == "ok"   # per-position threshold


def test_margin_stable_means_at_most_one_point_lower():
    assert pillars.operating_margin([Y("2024-12-31", 100, 20), Y("2025-12-31", 100, 19.2)])[0] == "ok"     # −0.8 points
    assert pillars.operating_margin([Y("2024-12-31", 100, 20), Y("2025-12-31", 100, 18.5)])[0] == "ko"     # −1.5 points
    assert pillars.operating_margin([Y("2024-12-31", 100, 3), Y("2025-12-31", 110, 3.6)])[0] == "ok"       # low margins are fine if rising
    assert pillars.operating_margin([Y("2024-12-31", 100), Y("2025-12-31", 110)])[0] == "na"


def test_estimates_consensus_valuation_trend():
    assert pillars.estimates(-2.9)[0] == "ok" and pillars.estimates(-3.1)[0] == "ko" and pillars.estimates(None)[0] == "na"
    assert pillars.consensus("buy")[0] == "ok" and pillars.consensus("strong_buy")[0] == "ok"
    assert pillars.consensus("hold")[0] == "ko" and pillars.consensus(None)[0] == "na"
    assert pillars.valuation("In linea")[0] == "ok" and pillars.valuation("Economica")[0] == "ok"
    assert pillars.valuation("Cara")[0] == "ko" and pillars.valuation(None)[0] == "na"
    assert pillars.trend(101, 100)[0] == "ok" and pillars.trend(99, 100)[0] == "ko" and pillars.trend(99, None)[0] == "na"


def test_diversification_threshold_and_minimum_weeks():
    assert pillars.diversification(0.59, 100)[0] == "ok"
    assert pillars.diversification(0.60, 100)[0] == "ko"
    assert pillars.diversification(0.2, 20)[0] == "na"


def test_manual_pillar_must_be_confirmed_every_three_months():
    today = date(2026, 11, 4)
    assert pillars.manual({"text": "x", "state": None, "date": None}, today)[0] == "na"
    assert pillars.manual({"text": "x", "state": "ok", "date": "2026-10-01"}, today)[0] == "ok"
    assert pillars.manual({"text": "x", "state": "ok", "date": "2026-07-01"}, today)[0] == "na"
    assert pillars.manual({"text": "x", "state": "ko", "date": "2026-10-01"}, today)[0] == "ko"
    assert pillars.manual({}, today) is None


DATA = {"years": [Y("2024-12-31", 100, 20), Y("2025-12-31", 115, 24)], "epsRev90": -5.0, "rec": "buy", "valLabel": "Cara", "sma200": 90}


def test_draft_proposes_the_pillars_true_today():
    ev = pillars.evaluate({"kind": "Azione", "price": 100}, {}, DATA)
    chosen = {x["id"] for x in ev["list"] if x["chosen"]}
    assert ev["draft"] and chosen == {"ricavi", "consenso", "margine", "trend"}


def test_saved_choice_and_score():
    ev = pillars.evaluate({"kind": "Azione", "price": 100}, {"pillars": ["ricavi", "stime", "valutazione"]}, DATA)
    assert not ev["draft"]
    assert pillars.score(ev) == {"n": 3, "ok": 1, "ko": 2, "na": 0}


def test_funds_have_their_own_list():
    ev = pillars.evaluate({"kind": "ETF", "price": 100}, {}, {"sma200": 95, "corr": 0.4, "weeks": 100})
    assert [x["id"] for x in ev["list"]] == ["trend", "diversifica"]


def test_changes_log_only_true_false_switches():
    ev = lambda st: {"list": [{"id": "trend", "name": "Trend", "state": st, "detail": "d", "chosen": True},
                              {"id": "stime", "name": "Stime", "state": "ko", "detail": "d", "chosen": False}]}
    e, last = pillars.changes(ev("ok"), {}, date(2026, 11, 1))
    assert e == [] and last == {"trend": {"state": "ok", "since": "2026-11-01"}}          # first check: starting state only
    e, last = pillars.changes(ev("na"), last, date(2026, 11, 2))
    assert e == [] and last["trend"]["state"] == "ok"                                      # a missing figure is not news
    e, last = pillars.changes(ev("ko"), last, date(2026, 11, 3))
    assert [(x["pillar"], x["from"], x["to"]) for x in e] == [("trend", "ok", "ko")] and last["trend"]["since"] == "2026-11-03"


def test_save_keeps_log_reviews_and_manual_state():
    actions.save("XX0000000001", {"why": "motivo", "pillars": ["trend", "ricavi"], "manual": "prodotto nuovo", "revMin": 5})
    actions.mark_manual("XX0000000001", "ok")
    actions.add_note("XX0000000001", "trimestrale buona")
    actions.record_pillars({"XX0000000001": ([], {"trend": {"state": "ok", "since": "2026-11-01"}})})
    actions.save("XX0000000001", {"why": "motivo cambiato", "manual": "prodotto nuovo"})       # pillars not sent: kept
    th = actions.load()["XX0000000001"]
    assert th["pillars"] == ["ricavi", "trend"] and th["pillarOpts"] == {"ricavi": 5.0} and th["manual"]["state"] == "ok"
    assert [x.get("note") for x in th["log"]] == [None, "trimestrale buona"] and th["last"]["trend"]["state"] == "ok"


def test_save_rejects_too_many_or_unknown_pillars():
    with pytest.raises(ValueError):
        actions.save("XX0000000001", {"pillars": ["trend", "ricavi", "stime", "consenso", "margine"]})
    with pytest.raises(ValueError):
        actions.save("XX0000000001", {"pillars": ["fortuna"]})
    with pytest.raises(ValueError):
        actions.add_note("XX0000000002", "nessuna tesi")
