"""Pillars of the thesis (pillars.py) and their saving in the thesis (actions.py). Made-up data only."""
from datetime import date

import pytest

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


DATA = {"years": [Y("2024-12-31", 100, 20), Y("2025-12-31", 115, 24)], "epsRev90": -5.0, "rec": "buy", "valLabel": "Cara", "sma200": 90}


def test_pagella_is_the_same_for_every_stock():
    ev = pillars.evaluate({"kind": "Azione", "price": 100}, DATA)
    assert [x["id"] for x in ev["list"]] == ["ricavi", "stime", "consenso", "margine", "valutazione", "trend"]
    assert ev["score"] == {"n": 6, "ok": 4, "ko": 2, "na": 0}


def test_funds_have_their_own_list():
    ev = pillars.evaluate({"kind": "ETF", "price": 100}, {"sma200": 95, "corr": 0.4, "weeks": 100})
    assert [x["id"] for x in ev["list"]] == ["trend", "diversifica"] and ev["score"]["ok"] == 2


def test_changes_log_only_true_false_switches():
    ev = lambda st: {"list": [{"id": "trend", "name": "Trend", "state": st, "detail": "d"}]}
    e, last = pillars.changes(ev("ok"), {}, date(2026, 11, 1))
    assert e == [] and last == {"trend": {"state": "ok", "since": "2026-11-01", "initial": True}}   # first check: starting state
    e, last = pillars.changes(ev("na"), last, date(2026, 11, 2))
    assert e == [] and last["trend"]["state"] == "ok"                                      # a missing figure is not news
    e, last = pillars.changes(ev("ko"), last, date(2026, 11, 3))
    assert [(x["pillar"], x["from"], x["to"]) for x in e] == [("trend", "ok", "ko")]
    assert last["trend"] == {"state": "ko", "since": "2026-11-03", "initial": False}


def test_log_file_round_trip():
    pillars.record({"XX01": ([{"date": "2026-11-03", "pillar": "trend", "name": "Trend", "from": "ok", "to": "ko"}], {"trend": {"state": "ko"}})})
    pillars.record({"XX01": ([], {"trend": {"state": "ko"}})})                            # nothing new: nothing written twice
    assert len(pillars.load_log()["XX01"]["log"]) == 1


# ---------------------------------------------------------------- automatic stop (stop_auto.py)

import stop_auto  # noqa: E402

LV = {"atr": 2.0, "sma50": 95.0, "low": {"v": 94.0, "date": "2026-10-20"}}


def test_automatic_stop_only_rises():
    d1, d2, d3 = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)
    s1 = stop_auto.trail(None, (90.0, "x", 2.0), d1)
    s2 = stop_auto.trail(s1, (85.0, "y", 2.0), d2)                   # lower: kept at 90
    s3 = stop_auto.trail(s2, (93.0, "z", 2.0), d3)                   # higher: raised
    assert (s1["stop"], s2["stop"], s3["stop"]) == (90.0, 90.0, 93.0) and s3["raised"] == 1 and s3["since"] == "2026-11-02"


def test_automatic_stop_uses_the_purchase_plan_rule():
    v, label, atr = stop_auto.computed(100.0, LV)
    assert v < 100 and atr == 2.0 and label


def test_automatic_stop_restarts_after_a_sale_and_keeps_all_when_the_file_is_missing():
    p = {"isin": "XX01", "price": 100.0, "currency": "USD"}
    stop_auto.update([p], {"XX01": (100.0, LV, None)})
    assert "XX01" in stop_auto.load()
    assert stop_auto.update([], {}) == stop_auto.load()               # portfolio not loaded: nothing dropped
    stop_auto.update([{"isin": "XX02", "price": 50.0, "currency": "USD"}], {})
    assert "XX01" not in stop_auto.load()                             # sold: a new purchase starts from zero


def test_sessions_below_the_200_day_average(monkeypatch):
    import pandas as pd

    import risk
    up = pd.Series([100.0 + i * 0.1 for i in range(250)])
    down = pd.concat([up, pd.Series([90.0] * 4)], ignore_index=True)       # last 4 closes well below the average
    monkeypatch.setitem(risk._hist, "closes", {"UP": up, "DN": down, "SHORT": up[:100]})
    assert risk.below200_sessions() == {"UP": 0, "DN": 4}


def test_stop_below_zero_is_not_calculable():
    lv = {"atr": 0.08, "sma50": 0.2, "low": {"v": 0.2, "date": "2026-10-20"}}      # price 0.10, very volatile
    assert stop_auto.computed(0.10, lv) == stop_auto.NO_STOP
    out = stop_auto.update([{"isin": "XX03", "price": 0.10, "currency": "USD"}], {"XX03": (0.10, lv, None)})
    assert out["XX03"]["stop"] is None and "sotto zero" in out["XX03"]["why"] and "XX03" not in stop_auto.load()
