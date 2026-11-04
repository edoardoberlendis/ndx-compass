"""Opportunità (phase O1): the two exploratory rankings of opportunity_scanner.py and /api/opportunities.
Only made-up prices and companies (tickers AAA, BBB, ...), never the files in portafoglio/."""
import json
import math
import os
import re
from datetime import date

import numpy as np
import pandas as pd
import pytest

import opportunity_scanner as o

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
END = "2026-10-30"
TODAY = date(2026, 11, 2)


def frame(closes, vol=None, end=END):
    idx = pd.bdate_range(end=end, periods=len(closes))
    c = pd.Series(np.asarray(closes, dtype=float), index=idx)
    v = np.asarray(vol, dtype=float) if vol is not None else np.full(len(c), 1e6)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": v}, index=idx)


def path(n, drift, wiggle=0.01, start=100.0):
    """Zigzag prices: up and down days alternate around a constant drift (RSI stays far from the extremes)."""
    r = np.array([drift + (wiggle if i % 2 == 0 else -wiggle) for i in range(n)])
    return start * np.cumprod(1 + r)


RISING_VOL = [1e6] * 280 + [1.5e6] * 20
QQQ = frame(path(300, 0.0005, 0.005))
GOOD = {"years": [{"fy": "2025-12-31", "revenue": 120.0, "operatingIncome": 30.0},
                  {"fy": "2024-12-31", "revenue": 100.0, "operatingIncome": 24.0}],
        "epsRev90": 2.0, "epsRev30": 1.0, "up30": 1, "down30": 0, "rec": "buy", "valLabel": "In linea", "valRatio": 1.0}
BAD = {"years": [{"fy": "2025-12-31", "revenue": 90.0, "operatingIncome": 9.0},
                 {"fy": "2024-12-31", "revenue": 100.0, "operatingIncome": 20.0}],
       "epsRev90": -10.0, "rec": "hold", "valLabel": "Cara", "valRatio": 1.6}


def stock(t, sector="Tecnologia"):
    return {"ticker": t, "name": f"Società {t}", "sector": sector}


def dip_path():
    """Slow rise for 280 sessions, then 20 sessions down: long trend intact, short term weak."""
    up = path(280, 0.001, 0.005)
    return np.concatenate([up, up[-1] * np.cumprod(np.full(20, 0.997))])


@pytest.fixture
def market():
    universe = [stock("AAA"), stock("BBB"), stock("CCC"), stock("DDD"), stock("FFF"), stock("GGG", "Finanza")]
    daily = {
        "AAA": frame(path(300, 0.004), RISING_VOL),       # strong, rising volumes
        "BBB": frame(path(300, 0.0025), RISING_VOL),      # strong, a bit less
        "CCC": frame(path(300, -0.003), RISING_VOL),      # falling
        "DDD": frame(path(300, 0.004), [0.0] * 300),      # strong but without volumes: T5 cannot be judged
        "FFF": frame(path(300, 0.004), RISING_VOL),       # strong prices, weak company
        "GGG": frame(dip_path(), RISING_VOL),             # good company, short-term dip
    }
    fund = {"FFF": BAD, "GGG": GOOD}
    return universe, daily, fund


def scan(market, **kw):
    universe, daily, fund = market
    return o.scan(universe, daily, QQQ, fund, today=TODAY, **kw)


def tickers(block):
    return [x["ticker"] for x in block["items"]]


# ---------------------------------------------------------------- selection and order

def test_trading_selection_and_order(market):
    r = scan(market)
    tr = r["trading"]
    assert r["asOf"] == END and r["evaluated"] == 6
    assert "CCC" not in tickers(tr)                                   # falling: not a candidate
    assert tickers(tr).index("AAA") < tickers(tr).index("BBB")        # same conditions: higher strength vs QQQ first
    by = {x["ticker"]: x for x in tr["items"]}
    assert by["AAA"]["ok"] == 5 and by["AAA"]["status"] == "Da approfondire" and by["AAA"]["rank"] == 1
    for a, b in zip(tr["items"], tr["items"][1:]):                    # the written order: conditions, then warnings
        assert (-a["ok"], len(a["warnings"])) <= (-b["ok"], len(b["warnings"]))
    assert [x["rank"] for x in tr["items"]] == list(range(1, len(tr["items"]) + 1))
    assert all(x["ok"] >= o.TRADING_MIN for x in tr["items"])
    assert re.match(r"\+[\d,]+ punti su QQQ a 1 mese · \+[\d,]+ punti su QQQ a 3 mesi$", by["AAA"]["main"])
    assert all(w.get("short") for x in tr["items"] for w in x["warnings"])
    assert len(tr["items"]) <= o.TOP


def test_top_ten_at_most():
    universe = [stock(f"S{i:02d}") for i in range(15)]
    daily = {u["ticker"]: frame(path(300, 0.002 + i * 0.0001), RISING_VOL) for i, u in enumerate(universe)}
    r = o.scan(universe, daily, QQQ, today=TODAY)
    assert r["trading"]["qualified"] == 15 and len(r["trading"]["items"]) == 10
    assert tickers(r["trading"])[0] == "S14"                           # the strongest against QQQ


def test_the_two_rankings_use_different_criteria(market):
    r = scan(market)
    assert "FFF" in tickers(r["trading"]) and "FFF" not in tickers(r["invest"])     # strong price, weak company
    assert "GGG" in tickers(r["invest"]) and "GGG" not in tickers(r["trading"])     # good company, weak short term
    g = next(x for x in r["invest"]["items"] if x["ticker"] == "GGG")
    assert g["ok"] == 6 and g["status"] == "Da approfondire"
    assert any(w["id"] == "below50" for w in g["warnings"])                          # short-term weakness is a warning
    assert {c["id"] for c in r["trading"]["items"][0]["conditions"]} == {"T1", "T2", "T3", "T4", "T5"}
    assert {c["id"] for c in g["conditions"]} == {"I1", "I2", "I3", "I4", "I5", "I6"}
    assert [p["label"] for p in g["perf"]] == ["6 mesi", "1 anno"]
    assert [p["label"] for p in r["trading"]["items"][0]["perf"]] == ["1 mese", "3 mesi"]   # absolute returns (phase O2)


# ---------------------------------------------------------------- missing values

def test_missing_volume_is_not_a_condition_met(market):
    d = next(x for x in scan(market)["trading"]["items"] if x["ticker"] == "DDD")
    t5 = next(c for c in d["conditions"] if c["id"] == "T5")
    assert t5["state"] == "na" and d["ok"] == 4 and d["status"] == "Dati insufficienti"
    assert d["missing"][0]["name"] == "Volumi in aumento"
    assert tickers(scan(market)["trading"]).index("DDD") > tickers(scan(market)["trading"]).index("AAA")


def test_missing_fundamentals_never_count_as_met(market):
    r = scan(market)
    assert "AAA" not in tickers(r["invest"])           # no company data: five checks "na", only the trend is met
    universe, daily, fund = market
    partial = {**GOOD, "epsRev90": None}
    r = o.scan([stock("GGG")], {"GGG": daily["GGG"]}, QQQ, {"GGG": partial}, today=TODAY)
    g = r["invest"]["items"][0]
    assert g["ok"] == 5 and g["status"] == "Dati insufficienti"
    assert next(c for c in g["conditions"] if c["id"] == "I3")["state"] == "na"
    for x in r["invest"]["items"] + r["trading"]["items"]:
        assert x["ok"] == sum(c["state"] == "ok" for c in x["conditions"])


def test_short_history_is_not_evaluable():
    r = o.scan([stock("NEW")], {"NEW": frame(path(40, 0.01), [1e6] * 40)}, QQQ, {"NEW": GOOD}, today=TODAY)
    assert r["evaluated"] == 0 and r["notEvaluable"][0]["ticker"] == "NEW"
    assert r["trading"]["items"] == []
    inv = r["invest"]["items"]                          # the five company checks are met, the trend cannot be judged
    assert len(inv) == 1 and inv[0]["status"] == "Dati insufficienti" and inv[0]["ok"] == 5
    assert all(c["state"] == "na" for c in o.trading_conditions(None))


def test_no_data_at_all():
    for r in (o.scan([], {}, None, today=TODAY), o.scan([stock("AAA")], {}, None, today=TODAY)):
        assert r["trading"]["items"] == [] and r["invest"]["items"] == [] and r["asOf"] is None
        json.dumps(r, allow_nan=False)                   # valid JSON even when empty
    r = o.scan([stock("AAA")], {"AAA": frame(path(300, 0.004), RISING_VOL)}, None, today=TODAY)
    a = r["trading"]["items"]
    assert not a or a[0]["status"] == "Dati insufficienti"   # without QQQ the strength cannot be measured


# ---------------------------------------------------------------- no future information

def test_prices_after_as_of_are_never_read(market):
    universe, daily, fund = market
    cut_day = "2026-09-30"
    future = {}
    for t, df in daily.items():
        past = df[df.index <= cut_day]
        extra = frame(np.full(22, past["Close"].iloc[-1] * (0.3 if t == "AAA" else 3.0)), [9e9] * 22, end=END)
        future[t] = pd.concat([past, extra[extra.index > cut_day]])
    qqq_future = pd.concat([QQQ[QQQ.index <= cut_day], frame(np.full(22, 999.0), end=END).loc[lambda x: x.index > cut_day]])
    only_past = {t: df[df.index <= cut_day] for t, df in daily.items()}
    a = o.scan(universe, future, qqq_future, fund, as_of=cut_day, today=TODAY)
    b = o.scan(universe, only_past, QQQ[QQQ.index <= cut_day], fund, today=TODAY)
    assert a == b and a["asOf"] == cut_day


# ---------------------------------------------------------------- failed patterns and warnings

def test_failed_pattern_is_only_a_warning(market):
    base = next(x for x in scan(market)["trading"]["items"] if x["ticker"] == "AAA")
    r = scan(market, patterns={"AAA": ["leader", "golden"]}, failed={"leader": "Leader di momentum"})
    a = next(x for x in r["trading"]["items"] if x["ticker"] == "AAA")
    ws = [w for w in a["warnings"] if w["id"] == "pattern"]
    assert len(ws) == 1 and "Leader di momentum" in ws[0]["text"] and "non è un motivo per comprare" in ws[0]["text"]
    assert a["ok"] == base["ok"] and a["conditions"] == base["conditions"]   # never a reason, never a condition


def test_earnings_and_extended_warnings():
    t = {"vs20": 9.5, "rsi": 60.0, "vs200": 5.0, "atrPct": 2.0}
    ts = pd.Timestamp("2026-11-05 21:00", tz="UTC").timestamp()
    ws = {w["id"] for w in o.trading_warnings(t, {"earningsTs": ts}, [], {}, TODAY)}
    assert ws == {"ext", "earn"}
    assert o.earnings_days(pd.Timestamp("2026-10-01", tz="UTC").timestamp(), TODAY) == (None, None)   # already past
    t2 = {"vs20": None, "rsi": 80.0, "vs200": -3.0, "atrPct": 5.0}
    assert {w["id"] for w in o.trading_warnings(t2, {}, [], {}, TODAY)} == {"ext", "below200", "vol"}
    inv = {w["id"] for w in o.invest_warnings(None, {"up30": 0, "down30": 2, "epsRev30": -5.0, "news": {"score": -30.0, "reasons": []}}, TODAY)}
    assert inv == {"down", "cut30", "news"}


def test_finite_turns_nan_into_none():
    assert o.finite({"a": [float("nan"), 1.0, math.inf], "b": "x"}) == {"a": [None, 1.0, None], "b": "x"}


# ---------------------------------------------------------------- API

@pytest.fixture
def api(monkeypatch, market):
    import server
    universe, daily, fund = market
    rows = [{**u, "price": float(daily[u["ticker"]]["Close"].iloc[-1]), "rec": (fund.get(u["ticker"]) or {}).get("rec"),
             "valLabel": (fund.get(u["ticker"]) or {}).get("valLabel"), "epsRev90": (fund.get(u["ticker"]) or {}).get("epsRev90")}
            for u in universe]
    st = server.store
    monkeypatch.setattr(st, "snapshot", {"asOf": "2026-11-02T10:00:00-05:00", "lastQuote": "2026-11-02T10:00:00-05:00", "stocks": rows})
    monkeypatch.setattr(st, "daily", {**daily, "QQQ": QQQ})
    monkeypatch.setattr(st, "analysts", {t: {"years": f["years"]} for t, f in fund.items()})
    monkeypatch.setattr(st, "infos", {})
    monkeypatch.setattr(st, "valuations", {})
    monkeypatch.setattr(st, "signals", {})
    monkeypatch.setattr(st, "ta", {"AAA": {"patterns": [{"key": "leader"}]}})
    monkeypatch.setattr(st, "news_all", None)
    monkeypatch.setattr(st, "error", None)
    monkeypatch.setattr(server, "patterns_test", lambda: {"favorable": ["golden"], "patterns": [
        {"key": "leader", "name": "Leader di momentum"}, {"key": "golden", "name": "Golden cross 50/200"}]})
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download for the rankings"))
    server._opps.update(key=None, data=None)
    return server


def test_api_returns_both_rankings(api):
    r = api.app.test_client().get("/api/opportunities")
    assert r.status_code == 200
    d = json.loads(r.data)
    assert d["asOf"] == END and d["newsReady"] is False
    assert "AAA" in tickers(d["trading"]) and "GGG" in tickers(d["invest"])
    a = next(x for x in d["trading"]["items"] if x["ticker"] == "AAA")
    assert a["priceTime"] == "2026-11-02T10:00:00-05:00" and a["closeDate"] == END
    assert any("Leader di momentum" in w["text"] for w in a["warnings"])
    for x in d["trading"]["items"] + d["invest"]["items"]:
        assert x["status"] in ("Da approfondire", "Dati insufficienti")
        assert not re.search(r"\b(compra|acquista)\b", json.dumps(x, ensure_ascii=False).lower())   # never "buy"


def test_api_while_loading(api, monkeypatch):
    monkeypatch.setattr(api.store, "snapshot", None)
    api._opps.update(key=None, data=None)
    r = api.app.test_client().get("/api/opportunities")
    assert r.status_code == 503 and json.loads(r.data)["error"] == "loading"


# ---------------------------------------------------------------- page: tab order and start page

def test_opportunita_is_the_first_tab_and_the_start_page():
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    html = open(os.path.join(ROOT, "static", "index.html")).read()
    block = re.search(r"const GROUPS = \[(.*?)\n\];", js, re.S).group(1)
    groups = re.findall(r'\{ id: "(\w+)", label:', block)
    assert groups[:3] == ["opportunita", "mercato", "portafoglio"]
    tabs = re.findall(r'class="tab" data-main="(\w+)"', html)
    assert tabs == groups
    assert 'setView(viewFromHash(h) || "opps")' in js and 'id="view-opps"' in html
    for old in ("overview", "sectors", "portfolio", "pfperf", "screener", "watch", "etf"):   # direct links unchanged
        assert f'["{old}",' in js
