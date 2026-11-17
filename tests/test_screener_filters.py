"""Screener (Azioni) filters of 17 Nov 2026, with the criteria of the STOCKS (not those of the ETF tab):
«Tendenza» = the arrows of the stock's Analisi box (technical.trends) and «Ha senso comprare?» = the buy verdict of the
Decisione sheet grouped by the rule that decided it, computed with an EMPTY portfolio. Only made-up data."""
import os
import re

import pandas as pd

import server
import technical

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()


def test_01_tendenza_uses_the_thresholds_of_the_analisi_box():
    """+1.5% in a week is ▲ (threshold 1%), +1.5% in a month is = (threshold 2%): the same arrows as the stock's box."""
    closes = pd.Series([100.0] * 70 + [101.5])
    arrows = {t["days"]: t["arrow"] for t in technical.trends(closes)}
    assert arrows == {5: "▲", 21: "=", 63: "="}
    assert technical.TREND == {"5": 1.0, "21": 2.0, "63": 4.0}
    assert "SCR_PERIODS = [[5, \"1 settimana\"], [21, \"1 mese\"], [63, \"3 mesi\"]]" in JS
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    assert 'r["trends"] = [{"days": x["days"], "arrow": x["arrow"], "pct": x["pct"]}' in src
    assert "trendWord" not in JS.split("// Tendenza: the arrows")[1].split("async function loadBuyVerdicts")[0]


def test_02_verdict_groups_follow_the_rule_that_decided():
    g = server.buy_group
    assert g({"category": "Entra ora", "decidedBy": "tutte"}) == "Entra ora"
    assert g({"category": "Entra su ritracciamento", "decidedBy": "D5"}) == "Entra su ritracciamento"
    assert g({"category": "Entra su ritracciamento", "decidedBy": "D7"}) == "Entra su ritracciamento"
    assert g({"category": "Attendi", "label": "Attendi: trimestrale il 20/11", "decidedBy": "D2"}) == "Attendi: trimestrale in arrivo"
    assert g({"category": "Attendi", "decidedBy": "D4"}) == "Attendi: sotto la media 200"
    assert g({"category": "Attendi", "decidedBy": "D6"}) == "Attendi: a ridosso del massimo"
    assert g({"category": "Attendi", "decidedBy": "dati"}) == "Attendi: dati insufficienti"
    assert g({"category": "Evita", "decidedBy": "D1"}) == "Evita"
    assert g(None) is None


def test_03_every_rule_of_decision_has_a_group_in_the_page():
    src = open(os.path.join(ROOT, "decision.py"), encoding="utf-8").read()
    rules = set(re.findall(r'buy = v\(f?"[^"]+",.*?"(D\d|dati|tutte)"', src, re.S))
    assert rules == set(server.BUY_GROUPS)
    listed = set(re.findall(r'"([^"]+)"', re.search(r"SCR_BUY = \[([^\]]+)\]", JS).group(1)))
    assert set(server.BUY_GROUPS.values()) == listed


def test_04_verdicts_without_portfolio_and_computed_once_per_snapshot(monkeypatch):
    calls = []

    def fake(ticker, pf=None, capital=None, details=True):
        calls.append((ticker, pf, details))
        if ticker == "CCC":
            return None
        return {"buyVerdict": {"category": "Attendi", "label": "Attendi: trimestrale il 20/11", "decidedBy": "D2"}}

    monkeypatch.setattr(server, "stock_decision", fake)
    monkeypatch.setitem(server._buy, "key", None)
    snap = {"asOf": "2026-11-17T10:00:00-05:00", "stocks": [{"ticker": "AAA"}, {"ticker": "CCC"}]}
    monkeypatch.setattr(server.store, "snapshot", snap)
    d = server.buy_verdicts()
    assert d["verdicts"] == {"AAA": {"group": "Attendi: trimestrale in arrivo", "label": "Attendi: trimestrale il 20/11", "by": "D2"},
                             "CCC": None}
    assert all(pf == {} and details is False for _, pf, details in calls)    # never the portfolio, no extra download
    server.buy_verdicts()
    assert len(calls) == 2                                                   # same snapshot: not recomputed
    monkeypatch.setattr(server.store, "snapshot", dict(snap, asOf="2026-11-17T10:01:00-05:00"))
    server.buy_verdicts()
    assert len(calls) == 4


def test_05_page_elements():
    assert 'id="scrFilters"' in open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read()
    assert '"/api/stocks/buy"' in JS and "data-scrclear" in JS and 'data-scrf="ft"' in JS and 'data-scrf="fb"' in JS
