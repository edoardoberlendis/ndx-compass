"""Screener (Azioni) filters of 17 Nov 2026: Trend in words with the rule of the ETF tab, and «Ha senso comprare?» = the
market verdict of the Decisione sheet, computed with an EMPTY portfolio. Only made-up data."""
import os
import re

import etf
import server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()


def test_01_trend_word_is_the_rule_of_the_etf_tab():
    for args in [(110, 100, 90), (80, 90, 100), (95, 100, 90), (100, None, 90)]:
        assert server.etf_trend_word(*args) == etf.trend_word(*args)
    assert server.etf_trend_word(110, 100, 90) == "Rialzista"
    assert server.etf_trend_word(80, 90, 100) == "Ribassista"
    assert server.etf_trend_word(95, 100, 90) == "Laterale"
    assert server.etf_trend_word(100, None, 90) is None


def test_02_verdicts_without_portfolio_and_computed_once_per_snapshot(monkeypatch):
    calls = []

    def fake(ticker, pf=None, capital=None, details=True):
        calls.append((ticker, pf, details))
        return {"buyVerdict": {"category": "Attendi" if ticker == "AAA" else "Entra ora"}} if ticker != "CCC" else None

    monkeypatch.setattr(server, "stock_decision", fake)
    monkeypatch.setitem(server._buy, "key", None)
    snap = {"asOf": "2026-11-17T10:00:00-05:00", "stocks": [{"ticker": "AAA"}, {"ticker": "BBB"}, {"ticker": "CCC"}]}
    monkeypatch.setattr(server.store, "snapshot", snap)
    d = server.buy_verdicts()
    assert d["verdicts"] == {"AAA": "Attendi", "BBB": "Entra ora", "CCC": None}
    assert all(pf == {} and details is False for _, pf, details in calls)    # never the portfolio, no extra download
    server.buy_verdicts()
    assert len(calls) == 3                                                   # same snapshot: not recomputed
    monkeypatch.setattr(server.store, "snapshot", dict(snap, asOf="2026-11-17T10:01:00-05:00"))
    server.buy_verdicts()
    assert len(calls) == 6


def test_03_filters_cover_every_verdict_and_trend():
    src = open(os.path.join(ROOT, "decision.py"), encoding="utf-8").read()
    cats = {m.split(":")[0] for m in re.findall(r'buy = v\(f?"([^"]+)"', src)}
    listed = set(re.findall(r'"([^"]+)"', re.search(r"SCR_BUY = \[([^\]]+)\]", JS).group(1)))
    assert cats and cats <= listed
    assert 'SCR_TRENDS = ["Rialzista", "Laterale", "Ribassista"]' in JS
    assert 'id="scrFilters"' in open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read()
    assert '"/api/stocks/buy"' in JS and "data-scrclear" in JS
