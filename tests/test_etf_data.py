"""ETF tab, missing data (corrections of 10 Oct 2026): with prices, trend and verdict are never empty; without prices the
computation says so and waits before trying again; the page and the server run the same version. Made-up data only."""
import os
import re
import time

import numpy as np
import pandas as pd
import pytest

import etf
import etf_buy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = {"isin": "IE00FINTO001", "category": "Finta", "group": "Aree e paesi", "yahoo": "FINT.MI", "underlyingCurrency": "EUR",
        "usProxy": None, "note": None,
        "justetf": {"tickerMI": "FINT", "tickerDE": None, "name": "ETF finto", "ter": 0.20, "sizeEurM": 900.0, "date": "2026-10-01",
                    "sectors": [["Technology", 10.0]], "countries": [["United States", 20.0]]}}
# every field of a row the page reads (static/app.js, renderEtf / openEtf / buySection)
PAGE_FIELDS = ["isin", "category", "group", "name", "yahoo", "ter", "sizeEurM", "noPrices", "fallback", "historySource", "launchIso",
               "r1w", "r2w", "r1m", "r3m", "r6m", "r1y", "r3y", "mom12_1", "vol", "maxDD3y", "vs50", "vs200", "trend", "spark", "late",
               "planLevels", "mix", "holdings", "justetf", "longYears", "longSource"]


def prices(n=400, end=None):
    idx = pd.bdate_range(end=end or pd.Timestamp.now().normalize(), periods=n)
    c = pd.Series(np.linspace(80, 120, n) * (1 + 0.01 * np.sin(np.arange(n) / 5)), index=idx)
    return pd.DataFrame({"Close": c, "High": c * 1.01, "Low": c * 0.99})


def test_with_prices_trend_and_verdict_are_never_empty():
    df = prices()
    r, s, ps = etf.make_row(FAKE, {"FINT.MI": df}, {"FINT.MI": df["Close"]}, None)
    assert not r["noPrices"] and s is not None and ps is not None
    assert r["trend"] in ("Rialzista", "Laterale", "Ribassista")
    assert all(r[k] is not None for k in ("r1w", "r1m", "r3m", "r1y")) and r["planLevels"]["price"] > 0
    d = etf_buy.decide(r, {"verdict": "diversifica"}, 10000, 1.0)
    assert d["verdict"] and d["market"]["verdict"] and len(d["checks"]) == 9
    assert d["verdict"] != "Attendi" or d["by"] != "A0"                 # "trend non calcolabile" must not happen with prices
    missing = [k for k in PAGE_FIELDS if k not in r]
    assert not missing, f"campi usati dalla pagina che mancano: {missing}"


def test_without_prices_the_row_says_so():
    r, s, ps = etf.make_row(FAKE, {}, {}, None)
    assert r["noPrices"] and s is None and r.get("trend") is None and r["planLevels"] is None
    d = etf_buy.decide(r, None)
    assert d["market"]["by"] == "A0"                                   # the verdict says why (trend not computable), never empty


def test_no_prices_from_yahoo_is_a_clear_error(monkeypatch):
    import server
    monkeypatch.setattr(server, "download", lambda *a, **k: {})
    monkeypatch.setattr(etf, "_universe", lambda: [FAKE])
    with pytest.raises(etf.PricesMissing, match="0 ETF su 1"):
        etf.build_public()


def test_after_a_failure_wait_before_trying_again(monkeypatch):
    started = []
    monkeypatch.setattr(etf.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: started.append(1)})())
    monkeypatch.setattr(etf, "_state", {"day": None, "running": False, "data": None, "error": "prezzi non disponibili", "failedAt": time.time()})
    assert etf.public() is None and not started                       # failed 0 minutes ago: no new try yet
    st = etf.status()
    assert st["error"] and st["retryAt"] and not st["today"]
    etf._state["failedAt"] = time.time() - (etf.RETRY_MIN + 1) * 60
    etf.public()
    assert started == [1]


def test_page_and_server_versions_match():
    import server
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    page = re.search(r'const PAGE_VERSION = "([^"]+)"', js).group(1)
    assert page == server.DASHBOARD_VERSION


def test_market_etf_filters_cover_every_trend_and_verdict():
    """Mercato ETF (17 nov 2026): the two filters Trend and «Ha senso comprare?» offer every value the server can give;
    a new verdict in etf_buy.py would otherwise disappear from the filter."""
    js = open(os.path.join(ROOT, "static", "app.js"), encoding="utf-8").read()
    assert 'data-etff="${k}"' in js and "data-etfclear" in js
    order = re.search(r"const BUY_ORDER = \{([^}]+)\}", js).group(1)
    verdicts = set(etf_buy.VERDICT_OF.values()) | {"Entra ora"}
    assert verdicts <= set(re.findall(r'"([^"]+)":', order))
    src = open(os.path.join(ROOT, "etf.py"), encoding="utf-8").read()
    trends = set(re.findall(r'return "(Rialzista|Laterale|Ribassista|[A-Z][a-z]+ista)"', src))
    assert trends and trends <= {"Rialzista", "Laterale", "Ribassista"}
    assert '["Rialzista", "Laterale", "Ribassista"]' in js
