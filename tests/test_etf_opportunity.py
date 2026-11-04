"""Phase 6B: exploratory scanner of ETF exposures (etf_opportunity.py), ETF price cache (etf_prices.py), its diary
(etf_opportunity_diary.py) and the new readings of the catalog builder (issuer pages, TER, tracking difference, bonds).

Only made-up data: invented catalog entries and invented price series. The benchmark ISINs are the real constants of
the scanner (they are only identifiers here: their prices are fake). Any network access fails the test."""
import json
import math
import os
import re
import socket
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

import etf_catalog as cat
import etf_catalog_build as build
import etf_opportunity as eo
import etf_opportunity_diary as ed
import etf_prices
import opportunity_diary as od

ROME = ZoneInfo("Europe/Rome")
END = pd.Timestamp("2026-11-03")


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    """No socket can be opened; the ETF price cache is never the real one."""
    def refuse(*a, **k):
        raise AssertionError("no network in the tests")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(etf_prices, "CACHE", str(tmp_path / "cache" / "etf_prices.pkl"))
    etf_prices._mem.update(mtime=None, data=None)


def make_isin(body):
    for d in "0123456789":
        if cat.isin_valid(body + d):
            return body + d
    raise AssertionError(body)


# ------------------------------------------------------------------ made-up catalog

VW, SW, SP, EU, EM = eo.B_WORLD_ALL, eo.B_WORLD_DEV, eo.B_US, eo.B_EU, eo.B_EM
SD = make_isin("ZZ100000001")     # world developed, another fund, distributing
SH = make_isin("ZZ100000002")     # world developed, hedged class of the SW fund
AI = make_isin("ZZ100000003")     # theme: artificial intelligence
HC = make_isin("ZZ100000004")     # US health care sector
G1 = make_isin("ZZ100000005")     # euro government 1-3 years
GL = make_isin("ZZ100000006")     # euro government long (duration 15)
IL = make_isin("ZZ100000007")     # inflation-linked
MM = make_isin("ZZ100000008")     # money market
NW = make_isin("ZZ100000009")     # recent launch: too short a history
F = lambda v, src="test", as_of="2026-10-31", note=None: cat.fv(v, src, as_of, note)


def entry(isin, label, exposure, ac="azionario", family="globale", index="Indice finto", fund=None, hedged=False, dist="accumulazione",
          ter=0.2, ter_res="riferimento dell'emittente", td=0.05, size=1000.0, turnover=500000.0, top10=0.2, theme=False,
          ccy_exp=(("USD", 60.0), ("EUR", 40.0)), bond=None, ticker=None, spread=None, launch="2015-01-01"):
    t = ticker or label[:4].upper()
    return {
        "isin": isin,
        "identity": {"name": F(f"{label} UCITS ETF"), "issuer": F("Emittente Finto"), "index": F(index), "domicile": F("Irlanda"),
                     "fundKey": F(fund or isin), "ucits": F(True)},
        "fund": {"hedged": F(hedged), "distribution": F(dist), "replication": F("fisica"), "baseCurrency": F("USD"),
                 "sizeFund": {"v": size, "src": "test", "asOf": "2026-10-31", "unit": "EUR"}, "launch": F(launch),
                 "distributionFrequency": F("semestrale" if dist == "distribuzione" else None)},
        "costs": {"ter": F(ter) if ter is not None else F(None, None, None, "fonti discordanti"), "terResolution": ter_res,
                  "terState": "verificato" if ter is not None else "discordante",
                  "trackingDifference": dict(F(td), avg=td) if td is not None else F(None, None, None, "non verificabile")},
        "exposure": {"top10Weight": F(top10), "top10": F([{"name": "X", "weight": top10}], note="emittente"), "holdingsCount": F(300),
                     "countries": F([{"name": "USA", "weight": 60.0}]), "sectors": F([{"name": "Tecnologia", "weight": 30.0}]),
                     "currencyExposure": F([{"currency": c, "weight": w} for c, w in ccy_exp])},
        "bond": bond or {},
        "classification": {"assetClass": ac, "family": family, "exposure": exposure, "label": label, "indexKey": index.lower(),
                           "theme": theme, "familyLabel": family},
        "listings": [{"ticker": t, "venue": "Borsa Italiana", "mic": "ETFP", "currency": F("EUR"), "yahoo": t + ".MI", "quoteAvailable": True,
                      "avgTurnover3m": F(turnover), "zeroVolumeDays": 0, "spread": spread},
                     {"ticker": t, "venue": "Xetra", "mic": "XETR", "currency": F("EUR"), "yahoo": t + ".DE", "quoteAvailable": True,
                      "avgTurnover3m": F(turnover / 2), "zeroVolumeDays": 0}],
        "valuation": {"priceEarnings": F(20.0)} if ac == "azionario" else {},
        "status": "attivo",
    }


def bond(duration, ytm, kind="titoli di Stato", ratings=((("AAA", 40.0), ("AA", 30.0), ("BBB", 30.0))), dist_yield=None, coupon=None):
    return {"duration": F(duration), "yield": F(ytm), "distYield": F(dist_yield), "coupon": F(coupon), "maturity": F(None),
            "ratings": F([{"name": n, "weight": w} for n, w in ratings]), "bondKind": F(kind), "credit": F("investment grade"),
            "currency": F("EUR")}


def catalog():
    items = {
        VW: entry(VW, "Mondo tutto", "mondo_tutto", index="FTSE All-World", ticker="VWCE"),
        SW: entry(SW, "Mondo sviluppato", "mondo_sviluppati", index="MSCI World", fund="fondo-sw", ticker="SWDA"),
        SD: entry(SD, "Mondo sviluppato", "mondo_sviluppati", index="MSCI World", dist="distribuzione", ter=0.12, ticker="BWLD"),
        SH: entry(SH, "Mondo sviluppato", "mondo_sviluppati", index="MSCI World", fund="fondo-sw", hedged=True, ticker="SWDH"),
        SP: entry(SP, "USA grandi", "usa_large", family="usa", index="S&P 500", ticker="CSPX"),
        EU: entry(EU, "Europa", "europa", family="europa", index="MSCI Europe", ticker="SMEA"),
        EM: entry(EM, "Emergenti", "emergenti", family="emergenti", index="MSCI EM IMI", ticker="EIMI"),
        AI: entry(AI, "Intelligenza artificiale", "intelligenza_artificiale", family="tecnologia", theme=True, top10=0.62, ticker="ARTI",
                  td=None, turnover=40000.0, size=60.0),
        HC: entry(HC, "Sanità USA", "sanita_usa", family="sanita", index="S&P 500 Health Care", ticker="IUHC"),
        G1: entry(G1, "Stato euro 1-3", "gov_euro_1_3", ac="obbligazionario", family="governativi_euro", dist="distribuzione", ter=0.07,
                  bond=bond(1.9, 3.3, dist_yield=2.1, coupon=2.4), ticker="IBGS"),
        GL: entry(GL, "Stato euro lunghi", "gov_euro_lunghi", ac="obbligazionario", family="governativi_euro", ter=0.2,
                  bond=bond(15.0, 4.4), ticker="IBGL"),
        IL: entry(IL, "Inflazione euro", "inflazione_euro", ac="obbligazionario", family="governativi_euro", ter=0.09,
                  bond=bond(7.0, 1.9, kind="indicizzati all'inflazione"), ticker="IBCI"),
        MM: entry(MM, "Liquidità euro", "monetario_euro", ac="monetario", family="monetario_euro", ticker="XEON"),
        NW: entry(NW, "Europa piccole", "europa_small", family="europa", index="MSCI Europe Small", ticker="NEWS", launch="2026-08-01"),
    }
    return {"items": items, "builtAt": "2026-11-03T20:00:00"}


def series(daily, n=600, end=END, start=100.0, wobble=0.0, seed=0):
    """A made-up close series in EUR on business days: compound growth `daily` plus a deterministic wobble."""
    idx = pd.bdate_range(end=end, periods=n)
    rng = np.random.default_rng(seed)
    r = daily + wobble * rng.standard_normal(n)
    r[0] = 0.0
    return pd.Series(start * np.cumprod(1 + r), index=idx)


def prices(cat_=None, fetched="2026-11-03T22:40:00+01:00", overrides=None):
    s = {VW: series(0.0004, wobble=0.006, seed=1), SW: series(0.0004, wobble=0.006, seed=2), SD: series(0.0004, wobble=0.006, seed=3),
         SH: series(0.0003, wobble=0.005, seed=4), SP: series(0.0005, wobble=0.007, seed=5), EU: series(0.0002, wobble=0.006, seed=6),
         EM: series(0.0003, wobble=0.008, seed=7), AI: series(-0.0012, wobble=0.02, seed=8), HC: series(0.0015, wobble=0.005, seed=9),
         G1: series(0.0001, wobble=0.001, seed=10), GL: series(0.0, wobble=0.004, seed=11), IL: series(0.0001, wobble=0.002, seed=12),
         MM: series(0.0001, seed=13), NW: series(0.0005, n=60, wobble=0.006, seed=14)}
    s.update(overrides or {})
    meta = {i: {"symbol": i[:4], "first": str(v.index[0].date()), "last": str(v.index[-1].date()), "n": len(v), "series": "ok",
                "totalReturn": True, "dividends": 0} for i, v in s.items()}
    return {"fetched": fetched, "source": "test", "period": "3y", "closes": s, "meta": meta}


@pytest.fixture
def data():
    return catalog(), prices()


NOW = datetime(2026, 11, 3, 23, 0)


# ------------------------------------------------------------------ 1-3: exposures, same ISIN, share classes

def test_01_exposures_are_identified_and_grouped(data):
    c, _ = data
    X = eo.exposures(c)
    assert set(X["mondo_sviluppati"]["members"]) == {SW, SD, SH}          # three classes, one exposure
    assert X["mondo_sviluppati"]["family"] == "globale" and X["sanita_usa"]["family"] == "settori"
    assert X["intelligenza_artificiale"]["family"] == "temi" and X["gov_euro_1_3"]["family"] == "gov"
    assert eo.opp_family({"assetClass": "obbligazionario", "family": "societarie_euro"}) == "corp"
    assert eo.opp_family({"assetClass": "azionario", "family": "paese", "exposure": "india"}) == "emergenti"
    assert eo.opp_family({"assetClass": "azionario", "family": "paese", "exposure": "italia"}) == "europa"
    assert eo.opp_family({"assetClass": "materie_prime", "family": "metalli"}) == "altre"
    c["items"][AI]["exclusion"] = "a leva"
    assert "intelligenza_artificiale" not in eo.exposures(c)               # excluded products never become exposures


def test_02_same_isin_on_two_exchanges_counts_once(data):
    c, p = data
    X = eo.exposures(c)
    assert X["usa_large"]["members"] == [SP]                                # two listings (Milan, Xetra) = one member
    assert sum(len(x["members"]) for x in X.values()) == len(c["items"])
    pr = eo.product(c["items"][SP], p, NOW)
    assert pr["tickers"] == ["CSPX"]                                        # same ticker on two venues shown once
    pl = etf_prices.plan(c)
    assert len(pl) == len(c["items"]) and [x[0] for x in pl[SP]["candidates"]] == ["CSPX.MI", "CSPX.DE"]   # Milan first, one series per ISIN
    r = eo.scan(c, p, "lungo", now=NOW)
    assert r["overview"]["products"] == len(c["items"]) and len({o["key"] for o in r["rows"]}) == len(r["rows"])


def test_03_share_classes_are_kept_distinct(data):
    c, p = data
    x = eo.exposures(c)["mondo_sviluppati"]
    assert eo.reference(x, c, p) == SW                                     # unhedged accumulating class measures the exposure
    p2 = prices(overrides={})
    del p2["closes"][SW]
    assert eo.reference(x, c, p2) == SD                                    # then the unhedged distributing one, never the hedged first
    o = eo.analyze_exposure(x, c, p, "lungo", now=NOW)
    lv = {pr["isin"]: pr["level"] for pr in o["products"]["products"]}
    assert lv[SH] == 2 and lv[SD] == 1 and lv[SW] is None                  # hedged class: same index but level 2
    assert "non è una preferenza" in o["referenceWhy"]


# ------------------------------------------------------------------ 4: fresh and stale data

def test_04_fresh_and_stale_data():
    at = "2026-11-03T15:00:00"
    s = {"v": 0.08, "at": at, "representative": True, "delayMin": 15}
    assert cat.spread_state(s, datetime(2026, 11, 3, 16))[0] == "rappresentativo"
    assert cat.spread_state(s, datetime(2026, 11, 5, 16))[0] == "datato"                         # older than a day: never shown as current
    assert cat.spread_state(dict(s, representative=False), datetime(2026, 11, 3, 16))[0] == "non rappresentativo"   # book after the close
    assert cat.spread_state(None)[0] == "mancante" and cat.spread_state({"v": None})[0] == "mancante"             # never invented
    # price cache: due until it contains the last final session (weekday 18:00 Rome)
    assert etf_prices.close_mark(datetime(2026, 11, 3, 17, 0, tzinfo=ROME)).date().isoformat() == "2026-11-02"
    assert etf_prices.close_mark(datetime(2026, 11, 3, 19, 0, tzinfo=ROME)).date().isoformat() == "2026-11-03"
    assert etf_prices.close_mark(datetime(2026, 11, 8, 12, 0, tzinfo=ROME)).date().isoformat() == "2026-11-06"   # Sunday → Friday
    assert etf_prices.due({"fetched": "2026-11-03T17:00:00+01:00"}, datetime(2026, 11, 3, 19, 0, tzinfo=ROME))
    assert not etf_prices.due({"fetched": "2026-11-03T18:30:00+01:00"}, datetime(2026, 11, 3, 23, 0, tzinfo=ROME))
    assert etf_prices.due(None, datetime(2026, 11, 3, 23, 0, tzinfo=ROME))
    # diary: intraday prices never recorded as the closes of the session
    assert ed.check_final("2026-11-03", "2026-11-03T15:00:00+01:00")
    assert ed.check_final("2026-11-03", "2026-11-03T18:30:00+01:00") is None
    assert ed.check_final("2026-11-03", "2026-11-03T18:30:00")                                    # no time zone: refused


# ------------------------------------------------------------------ 5-7: performance and currency

def test_05_absolute_performance():
    s = pd.Series([100.0, 110.0, 121.0], index=pd.bdate_range("2026-01-01", periods=3))
    assert eo.ret(s, 2) == pytest.approx(21.0) and eo.ret(s, 1) == pytest.approx(10.0)
    assert eo.ret(s, 3) is None                                             # not enough data: missing, never zero
    assert eo.fmt(-3.25) == "−3,2" and eo.fmt(None) == "n.d."


def test_06_relative_performance_with_coherent_benchmark(data):
    a = pd.Series([100.0, 110.0], index=pd.bdate_range("2026-01-01", periods=2))
    b = pd.Series([100.0, 104.0], index=pd.bdate_range("2026-01-01", periods=2))
    assert eo.rel(a, b, 1) == pytest.approx(6.0)
    b2 = b.copy()
    b2.index = pd.bdate_range("2026-01-02", periods=2)
    a3, b3 = eo.align(a, b2)
    assert len(a3) == 1                                                     # only common dates, never a forward-filled holiday
    c, _ = data
    X = eo.exposures(c)
    assert eo.benchmark_for(X["sanita_usa"])[0] == SP                      # US sector against the S&P 500
    assert eo.benchmark_for(X["intelligenza_artificiale"])[0] == SW        # global theme against the world
    assert eo.benchmark_for(X["europa_small"])[0] == EU
    assert eo.benchmark_for(X["usa_large"])[0] == VW                       # the benchmark itself is measured against the world
    assert eo.benchmark_for(X["mondo_tutto"])[0] is None
    assert eo.benchmark_for(X["gov_euro_1_3"])[0] is None                   # bonds: no equity benchmark
    assert set(eo.BENCH_NAME) == {VW, SW, SP, EU, EM} and not any("QQQ" in n for n in eo.BENCH_NAME.values())   # never QQQ for everything


def test_07_currency_conversion():
    idx = pd.bdate_range("2026-01-01", periods=4)
    usd = pd.Series([110.0, 112.2, 110.0, 121.0], index=idx)
    fx = {"EURUSD=X": pd.Series([1.10, 1.10, 1.00, 1.10], index=idx)}
    eur = etf_prices.to_eur(usd, "USD", fx)
    assert list(eur.round(4)) == [100.0, 102.0, 110.0, 110.0]                 # each day with the rate of the same day
    assert etf_prices.to_eur(usd, "EUR", fx) is usd
    assert etf_prices.to_eur(usd, "GBP", fx) is None                          # missing rate: no series, never a guess
    p = {"ZZ": {"symbol": "AAA.L", "currency": "GBP", "venue": "LSE", "launch": None, "distribution": "accumulazione",
                "candidates": [("AAA.L", "GBP", "LSE")]}}
    out = etf_prices.assemble({"AAA.L": pd.DataFrame({"Close": usd})}, p, datetime(2026, 1, 9, tzinfo=ROME))
    assert "ZZ" not in out["closes"] and "cambio" in out["meta"]["ZZ"]["missing"]


# ------------------------------------------------------------------ 8: accumulating and distributing

def test_08_acc_dist_and_total_return():
    idx = pd.bdate_range("2024-01-01", periods=600)
    close = pd.Series(np.linspace(100, 120, 600), index=idx)
    divs = pd.Series(0.0, index=idx)
    p = {"D": {"symbol": "D.MI", "currency": "EUR", "venue": "BI", "launch": "2024-02-01", "distribution": "distribuzione",
               "candidates": [("D.MI", "EUR", "BI")]},
         "A": {"symbol": "A.MI", "currency": "EUR", "venue": "BI", "launch": None, "distribution": "accumulazione",
               "candidates": [("A.MI", "EUR", "BI")]}}
    out = etf_prices.assemble({"D.MI": pd.DataFrame({"Close": close, "Dividends": divs}), "A.MI": pd.DataFrame({"Close": close})}, p,
                              datetime(2026, 1, 9, tzinfo=ROME))
    assert out["meta"]["D"]["totalReturn"] is False                       # distributing without recorded dividends: price only
    assert out["meta"]["A"]["totalReturn"] is True
    assert out["closes"]["D"].index[0] >= pd.Timestamp("2024-02-01")      # nothing before the launch of the class
    divs.iloc[100] = 1.2
    out = etf_prices.assemble({"D.MI": pd.DataFrame({"Close": close, "Dividends": divs})}, {"D": p["D"]}, datetime(2026, 1, 9, tzinfo=ROME))
    assert out["meta"]["D"]["totalReturn"] is True and out["meta"]["D"]["dividends"] == 1


def test_08b_longest_listing_when_milan_is_short():
    long_ = pd.Series(np.linspace(100, 110, 700), index=pd.bdate_range(end="2026-11-03", periods=700))
    short = long_.iloc[-100:]
    p = {"X": {"symbol": "X.MI", "currency": "EUR", "venue": "BI", "launch": None, "distribution": "accumulazione",
               "candidates": [("X.MI", "EUR", "BI"), ("X.DE", "EUR", "Xetra")]}}
    out = etf_prices.assemble({"X.MI": pd.DataFrame({"Close": short}), "X.DE": pd.DataFrame({"Close": long_})}, p, datetime(2026, 11, 3, 22, tzinfo=ROME))
    assert out["meta"]["X"]["symbol"] == "X.DE" and "più lunga" in out["meta"]["X"]["choice"] and out["meta"]["X"]["n"] == 700


# ------------------------------------------------------------------ 9-11: trend, volatility, drawdown

def test_09_trend():
    assert eo.trend_word(110, 105, 100) == "Rialzista" and eo.trend_word(90, 95, 100) == "Ribassista"
    assert eo.trend_word(100, 105, 100) == "Laterale" and eo.trend_word(None, 1, 1) is None
    up = series(0.001, n=300)
    m = eo.equity_measures(up, None, "lungo")
    assert m["trend"] == "Rialzista" and m["returns"]["12m"] > 0 and "rel" not in m


def test_10_volatility():
    idx = pd.bdate_range("2025-01-01", periods=300)
    s = pd.Series(100 * np.cumprod([1.0] + [1.01 if i % 2 else 0.99 for i in range(299)]), index=idx)
    v = eo.vol(s, 252)
    assert v == pytest.approx(0.01 * math.sqrt(252) * 100, rel=0.01)
    assert eo.vol(s.iloc[:10], 252) is None                                 # too few returns: missing


def test_11_drawdown():
    s = pd.Series([100.0, 120.0, 90.0, 96.0], index=pd.bdate_range("2026-01-01", periods=4))
    assert eo.drawdown(s, 4) == pytest.approx(-20.0)


# ------------------------------------------------------------------ 12-14: bonds

def test_12_equity_and_bond_use_separate_models(data):
    c, p = data
    r = eo.scan(c, p, "lungo", now=NOW)
    g = eo.detail(r, "gov_euro_1_3")
    assert g["kind"] == "bond" and {x["id"] for x in g["conditions"]["fav"] + g["conditions"]["con"]} == {"O1", "O2", "O3", "P1", "P2"}
    assert "rel" not in (g.get("measures") or {}) and g["trends"] == []      # no momentum on bonds
    e = eo.detail(r, "sanita_usa")
    assert e["kind"] == "equity" and {x["id"] for x in e["conditions"]["fav"]} == {"L1", "L2", "L3", "L4"}
    assert eo.detail(r, "monetario_euro")["state"] == "Riferimento di mercato"
    assert eo.detail(r, "mondo_tutto")["state"] == "Riferimento di mercato"


def test_13_duration_and_rate_sensitivity(data):
    c, p = data
    bm = eo.bond_measures(c["items"][G1])
    assert bm["sensitivity"] == -1.9 and bm["cushion"] == pytest.approx(3.3 / 1.9) and bm["aOrBetter"] == 70.0
    r = eo.scan(c, p, "lungo", now=NOW)
    assert eo.detail(r, "gov_euro_1_3")["state"] == "Esposizione da approfondire"
    long_ = eo.detail(r, "gov_euro_lunghi")
    assert long_["state"] == "Rischio elevato" and any(x["id"] == "P1" for x in long_["contrary"])
    assert "15,0%" in long_["invalidate"][0]                                 # 1 point of rates ≈ duration %
    assert "stabilizzazione" in eo.bond_role({"family": "gov"}, bm) and "scommessa" in eo.bond_role({"family": "gov"}, eo.bond_measures(c["items"][GL]))
    c["items"][G1]["bond"]["duration"] = F(None)
    assert eo.bond_state(eo.bond_measures(c["items"][G1]), [], []) == "Dati insufficienti"


def test_14_ytm_is_not_coupon_nor_distribution_yield(data):
    c, _ = data
    bm = eo.bond_measures(c["items"][G1])
    assert (bm["yield"], bm["coupon"], bm["distYield"]) == (3.3, 2.4, 2.1)   # three separate values
    assert bm["yieldAfterTer"] == pytest.approx(3.3 - 0.07)
    il = eo.bond_measures(c["items"][IL])
    o1 = eo.bond_conditions(il)[0][0]
    assert il["inflationLinked"] and o1["ok"] is None and "reale" in o1["why"]   # real yield not compared with nominal ones
    src = open(build.__file__).read()
    assert "non è una previsione né un rendimento netto garantito" in src


# ------------------------------------------------------------------ 15-18: products, missing data, costs, liquidity

def test_15_product_comparison_without_a_winner(data):
    c, p = data
    r = eo.scan(c, p, "lungo", now=NOW)
    pb = eo.detail(r, "mondo_sviluppati")["products"]
    assert {x["isin"] for x in pb["products"]} == {SW, SD, SH} and pb["compare"][:3] == [SW, SD, SH]
    assert "vincitore" in pb["verdict"] or "nessun prodotto" in pb["verdict"]
    assert any("TER da" in d for d in pb["differences"])                    # differences described, not ranked
    assert eo.detail(r, "sanita_usa")["products"]["verdict"].startswith("un solo ETF")
    c["items"][SD]["costs"]["trackingDifference"] = F(None, None, None, "non verificabile")
    pb2 = eo.analyze_exposure(eo.exposures(c)["mondo_sviluppati"], c, p, "lungo", now=NOW)["products"]
    assert "nessun prodotto indicato come preferibile" in pb2["verdict"]
    dump = json.dumps(eo.page(r), ensure_ascii=False, default=str).lower()
    assert "migliore" not in dump and "vincitore:" not in dump


def test_16_missing_data_is_never_satisfied(data):
    c, p = data
    del p["closes"][HC]
    o = eo.analyze_exposure(eo.exposures(c)["sanita_usa"], c, p, "lungo", now=NOW)
    assert o["state"] == "Dati insufficienti" and o["completeness"]["analysis"] == "insufficiente"
    assert "nessuna serie" in o["completeness"]["notes"][0]
    short = eo.analyze_exposure(eo.exposures(c)["europa_small"], c, p, "lungo", now=NOW)
    assert short["state"] == "Dati insufficienti" and "sedute" in short["completeness"]["notes"][0]
    fav = [eo.cond("A", "a", None), eo.cond("B", "b", True)]
    assert eo.state_of(fav, [], "medio") != "Esposizione da approfondire"     # a non-evaluable condition never counts
    m = {"price": 1.0, "trend": None}
    fav, con = eo.equity_conditions(m, "lungo", has_bench=False)
    assert all(x["ok"] is None for x in fav) and fav[1]["why"] == "nessun benchmark coerente"


def test_17_costs_ter_reference_and_conflicts():
    verif = {"ter": {"M": {"v": 0.14, "asOf": "2026-09-30", "definition": "OCF", "document": "factsheet"}},
             "terUnresolved": {"U": {"note": "documento non letto"}}}
    r = build.ter_reference("I", 0.2, "ishares", "2026-11-03", None, None, None, 0.25, "borsa", 0.2, "justetf", "2026-10-08", verif)
    assert r[0] == 0.2 and r[4] == "riferimento dell'emittente"
    r = build.ter_reference("M", None, None, None, None, None, None, 0.19, "borsa", 0.14, "justetf", "2026-10-08", verif)
    assert r[0] == 0.14 and r[4] == "documento dell'emittente verificato a mano" and r[2] == "2026-09-30"
    r = build.ter_reference("U", None, None, None, None, None, None, 0.27, "borsa", 0.30, "justetf", "2026-10-08", verif)
    assert r[0] is None and r[4] == "non risolto" and r[6] == "discordante" and "documento non letto" in r[3]   # never the lowest
    assert {x["v"] for x in r[5]} == {0.27, 0.30}                            # every reading stays visible
    real = json.load(open(os.path.join(cat.ROOT, "etf_catalog_verifiche.json")))
    for isin, t in real["ter"].items():
        assert {"v", "definition", "asOf", "document", "url"} <= set(t) and cat.isin_valid(isin)


def test_18_liquidity_and_spread_checks(data):
    c, p = data
    q = {x["id"]: x for x in eo.product(c["items"][AI], p, NOW)["checks"]}
    assert q["Q4"]["ok"] is False and q["Q2"]["ok"] is False and q["Q3"]["ok"] is False
    assert q["Q5"]["ok"] is None                                             # no book read: not evaluable, never invented
    c["items"][SP]["listings"][0]["spread"] = {"v": 0.05, "at": "2026-11-03T15:00:00", "representative": True, "delayMin": 15}
    q = {x["id"]: x for x in eo.product(c["items"][SP], p, datetime(2026, 11, 3, 16))["checks"]}
    assert q["Q4"]["ok"] is True and q["Q5"]["ok"] is True and q["Q6"]["ok"] is True
    q = {x["id"]: x for x in eo.product(c["items"][SP], p, datetime(2026, 11, 6, 16))["checks"]}
    assert q["Q5"]["ok"] is False                                            # stale spread is never shown as current


# ------------------------------------------------------------------ 19-21: rankings, no look-ahead, no Buy/Sell

def test_19_rankings_and_reasons(data):
    c, p = data
    r = eo.scan(c, p, "lungo", now=NOW)
    assert len(r["selected"]) <= eo.P["max_selected"]
    sel = [eo.detail(r, k) for k in r["selected"]]
    assert all(o["state"] == "Esposizione da approfondire" for o in sel)
    assert [o["rank"] for o in sel] == list(range(1, len(sel) + 1))
    assert sorted(sel, key=lambda o: eo.order_key(o, "lungo")) == sel
    for o in r["rows"]:
        assert o["state"] in eo.STATES and o["why"]                         # every state with its reasons
        for line in o["why"]:
            if line.startswith(("✓", "✕")):
                assert "(" in line                                          # each reason shows the measured value
    assert "Non è una previsione" in r["orderRule"]
    assert sum(r["overview"]["counts"].values()) == len(r["rows"])
    a = eo.detail(r, "intelligenza_artificiale")
    assert a["risk"]["level"] == "elevato" and any(f["id"] == "R2" for f in a["risk"]["flags"])   # 62% in the top 10
    assert eo.state_of([eo.cond("L", "", True)] * 4, [], "elevato") == "Rischio elevato"
    assert eo.state_of([eo.cond("L", "", True)] * 2 + [eo.cond("L", "", False)] * 2, [], "medio") == "Trend favorevole da monitorare"
    assert eo.state_of([eo.cond("L", "", True)], [eo.cond("M", "", True)], "medio") == "Condizioni contrastanti"


def test_20_no_look_ahead(data):
    c, p = data
    as_of = "2026-09-30"
    a = eo.scan(c, p, "lungo", as_of=as_of, now=NOW)
    changed = prices(overrides={k: v.where(v.index <= as_of, v * 3) for k, v in p["closes"].items()})   # the future changes
    b = eo.scan(c, changed, "lungo", as_of=as_of, now=NOW)
    strip = lambda r: json.dumps([{k: o.get(k) for k in ("key", "state", "measures", "why")} for o in r["rows"]], default=str, sort_keys=True)
    assert strip(a) == strip(b) and a["session"] <= as_of
    m = eo.equity_measures(eo.cut(p["closes"][HC], as_of), eo.cut(p["closes"][SP], as_of), "lungo")
    assert m["date"] <= as_of
    s = p["closes"][HC]
    full = eo.align(s, p["closes"][SP])
    assert eo.rel_before(*full, 126, 21) == pytest.approx(eo.rel(full[0].iloc[:-21], full[1].iloc[:-21], 126))   # previous reading from past data only


def test_21_no_buy_sell_signals_or_probabilities(data):
    c, p = data
    for mode in eo.MODES:
        r = eo.scan(c, p, mode, now=NOW)
        text = json.dumps(eo.page(r), ensure_ascii=False, default=str)
        for w in ("Compra", "Vendi", "Acquista", "probabilità", "rendimento atteso", "prezzo obiettivo"):
            assert w not in text
        assert r["disclaimer"].startswith("Screening esplorativo, non consulenza finanziaria")
        assert all(o["state"] in eo.STATES for o in r["rows"])
        assert not any("score" in k.lower() or "punteggio" == k.lower() for o in r["rows"] for k in o)   # no single score
    with pytest.raises(ValueError):
        eo.scan(c, p, "intraday")


# ------------------------------------------------------------------ 22-23: prospective diary

def _start_diary(tmp_path):
    os.makedirs(os.path.dirname(od.DB), exist_ok=True)
    od.connect().close()                                                     # the opportunity diary is started by its own module
    assert str(tmp_path) in od.DB


def _session_scan(c, p, session="2026-11-03"):
    return {m: eo.scan(c, p, m, as_of=session, now=NOW) for m in eo.MODES}


def test_22_diary_records_a_closed_session(data, tmp_path):
    c, p = data
    res = _session_scan(c, p)
    assert ed.record(res, "2026-11-03", "2026-11-03T23:00:00+01:00", "test") == (False, "diario delle opportunità non ancora avviato: nessuna registrazione degli ETF")
    _start_diary(tmp_path)
    before = {r[0] for r in sqlite3.connect(od.DB).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    ok, msg = ed.record(res, "2026-11-03", "2026-11-03T23:00:00+01:00", "test")
    assert ok, msg
    con = sqlite3.connect(od.DB)
    con.row_factory = sqlite3.Row
    run = con.execute("SELECT * FROM etf_runs").fetchone()
    assert run["model_version"] == eo.VERSION and run["prices_fetched"] == p["fetched"] and json.loads(run["params"])["rs_long"] == 2.0
    obs = con.execute("SELECT * FROM etf_observations WHERE mode='lungo' AND exposure='sanita_usa'").fetchone()
    assert obs["reference_isin"] == HC and json.loads(obs["prices"])[HC]["date"] == "2026-11-03"
    assert json.loads(obs["indicators"])["rel"]["6m"] is not None and obs["benchmark"] and obs["state"] in eo.STATES
    assert json.loads(obs["reasons"]) and json.loads(obs["data_status"])["analysis"] in ("sufficiente", "insufficiente")
    n = con.execute("SELECT COUNT(*) FROM etf_observations").fetchone()[0]
    assert n == 2 * len(res["lungo"]["rows"])                               # both modes, every exposure
    after = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert after - before == {"etf_runs", "etf_observations"}               # existing tables untouched, only new ones
    st = ed.stats()
    assert st["started"] and st["days"] == 1 and st["observations"] == n
    prev = ed.previous(before="2026-11-04")
    assert prev["gov_euro_1_3"]["bond"]["yield"] == 3.3 and ed.previous(before="2026-11-03") == {}


def test_22b_diary_refuses_intraday_or_mismatched_prices(data, tmp_path):
    c, p = data
    _start_diary(tmp_path)
    intraday = prices(fetched="2026-11-03T15:00:00+01:00")
    ok, why = ed.record(_session_scan(c, intraday), "2026-11-03", "2026-11-03T15:01:00+01:00", "test")
    assert not ok and "non era ancora chiusa" in why
    ok, why = ed.record(_session_scan(c, p, "2026-10-30"), "2026-11-03", "2026-11-03T23:00:00+01:00", "test")
    assert not ok and "non della seduta" in why                              # no retroactive rows
    assert not ed.exists("2026-11-03", eo.VERSION)


def test_23_diary_is_idempotent_and_immutable(data, tmp_path):
    c, p = data
    _start_diary(tmp_path)
    res = _session_scan(c, p)
    assert ed.record(res, "2026-11-03", "2026-11-03T23:00:00+01:00", "test")[0]
    again = ed.record(res, "2026-11-03", "2026-11-03T23:30:00+01:00", "test")
    assert again == (False, "seduta già registrata con questa versione dello scanner ETF")
    con = sqlite3.connect(od.DB)
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE etf_observations SET state='x'")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM etf_runs")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM etf_observations")
    assert con.execute("SELECT COUNT(*) FROM etf_runs").fetchone()[0] == 1
    assert ed._clean({"a": float("nan"), "b": [float("inf"), 1.0]}) == {"a": None, "b": [None, 1.0]}   # missing stays missing


def test_23b_diary_only_from_the_server_loop_not_from_the_page(data, tmp_path, monkeypatch):
    import server
    c, p = data
    _start_diary(tmp_path)
    p["closes"][VW] = p["closes"][VW]
    monkeypatch.setattr(etf_prices, "load", lambda path=None: p)
    monkeypatch.setattr(cat, "load", lambda *a, **k: c)
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download"))
    server._eopp.update(key=None, data={})
    cl = server.app.test_client()
    assert cl.get("/api/etf/opportunities?mode=lungo").status_code == 200
    assert not ed.exists("2026-11-03", eo.VERSION)                           # opening the page records nothing
    msg = server.save_etf_scan_diary(source="test")
    assert "salvate" in msg and ed.exists("2026-11-03", eo.VERSION)
    assert "già registrata" in server.save_etf_scan_diary(source="test")
    src = open(server.__file__).read()
    assert "save_etf_scan_diary()" in src and 'save_etf_scan_diary(source="job serale")' in src


# ------------------------------------------------------------------ 24: API

def test_24_api_compatibility(data, monkeypatch):
    import server
    c, p = data
    monkeypatch.setattr(etf_prices, "load", lambda path=None: p)
    monkeypatch.setattr(cat, "load", lambda *a, **k: c)
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download"))
    server._eopp.update(key=None, data={})
    cl = server.app.test_client()
    t0 = time.perf_counter()
    d = json.loads(cl.get("/api/etf/opportunities?mode=lungo").data)
    assert time.perf_counter() - t0 < 3
    assert d["status"] == "ok" and d["version"] == eo.VERSION and d["mode"] == "lungo"
    assert {"overview", "rows", "selected", "selectedRows", "disclaimer", "params", "diary", "prices"} <= set(d)
    assert "products" in d["rows"][0] and "measures" not in d["rows"][0]     # compact list; detail on demand
    b = json.loads(cl.get("/api/etf/opportunities?mode=breve").data)
    assert b["mode"] == "breve" and b["orderRule"].endswith("Non è una previsione né un punteggio.")
    one = json.loads(cl.get("/api/etf/opportunities/sanita_usa?mode=lungo").data)
    assert one["key"] == "sanita_usa" and one["disclaimer"] == eo.DISCLAIMER and one["products"]["products"]
    assert cl.get("/api/etf/opportunities?mode=x").status_code == 400
    assert cl.get("/api/etf/opportunities/sanita_usa?mode=x").status_code == 400
    assert cl.get("/api/etf/opportunities/nessuna?mode=lungo").status_code == 404
    assert json.loads(cl.get("/api/etf/opportunities/diary").data)["started"] is False
    assert "NaN" not in cl.get("/api/etf/opportunities?mode=lungo").get_data(as_text=True)
    monkeypatch.setattr(etf_prices, "load", lambda path=None: None)
    server._eopp.update(key=None, data={})
    m = json.loads(cl.get("/api/etf/opportunities?mode=lungo").data)
    assert m["status"] == "missing" and "background" in m["error"]           # no download at page opening
    rules = {r.rule for r in server.app.url_map.iter_rules()}
    assert {"/api/etf", "/api/etf/catalog", "/api/etf/compare", "/api/opportunities"} <= rules


# ------------------------------------------------------------------ 25: issuer pages and tracking difference

ISH_PAGE = """<html><head><meta property="og:title" content="iShares Finto UCITS ETF"></head><body>
<script>productShareClass: "Acc", portfolioId: "123"</script>
<select><option data-link-event="share class USD (Acc)" value="/it/prodotti/123/finto"></option></select>
<div class="product-data-item col-isin "><div class="caption">ISIN</div></div><div class="data">ZZ0000000001</div>
<div class="product-data-item col-effectiveDuration "><div class="caption">Duration effettiva<div class="as-of-date"> al 03/11/2026</div></div></div><div class="data">1,87</div>
<table id="listingsTable"><tbody><tr><td>Borsa Italiana</td><td>FINT</td><td>EUR</td><td>01/02/2015</td></tr></tbody></table>
<script>var returnsCalChartCategories = ["2021","2022","2023","2024","2025"];
var returnsCalChartData = [{name: 'Rendimento totale (%)', data: [{y: 5.0},{y: -10.0},{y: 8.0},{y: 3.0},{y: 2.0}]},
{name: 'Benchmark (%)', data: [{y: 5.2},{y: -9.8},{y: 8.1},{y: 3.2},{y: 2.05}]}];</script>
<span>Rendimento totale (%) EUR</span><span>Benchmark (%) EUR</span>
<a title="Indice: Indice Finto<br>dettagli">x</a></body></html>"""


def test_25_issuer_page_and_tracking_difference():
    pg = build.parse_ishares_page(ISH_PAGE)
    assert pg["isin"] == "ZZ0000000001" and pg["hedged"] is False and pg["classLabel"] == "USD (Acc)"
    assert build.fact(pg, "effectiveDuration") == (1.87, "2026-11-03")
    assert pg["listings"][0]["ticker"] == "FINT" and pg["benchmarkName"] == "Indice Finto"
    assert len(pg["calendar"]) == 5 and pg["returnCurrency"] == {"fund": "EUR", "benchmark": "EUR"}
    td = build.tracking_difference(pg["calendar"], launch_year=2021)
    assert [r["year"] for r in td["years"]] == [2022, 2023, 2024, 2025]       # the launch year is never a full year
    assert td["last"]["td"] == pytest.approx(-0.05) and td["n"] == 4
    f = build.td_field(pg, "2021-03-01", "ishares_pagina:x", None)
    assert f["v"] == pytest.approx(-0.05) and "tracking error" in f["definition"]    # TD, never confused with TE
    assert build.td_comparable(pg, hedged=True)                                # hedged class vs unhedged index: blocked
    usd = dict(pg, returnCurrency={"fund": "EUR", "benchmark": "USD"})
    assert "valute diverse" in build.td_comparable(usd, hedged=False)
    assert build.td_field(usd, "2015-01-01", "x", None)["v"] is None
    assert build.parse_ishares_page("<html>nessun fondo</html>") is None
    assert build.page_num("EUR 1.804.995.637") == 1804995637 and build.page_num("3,34%") == 3.34


# ------------------------------------------------------------------ 26: no regressions

def test_26_no_regressions():
    root = cat.ROOT
    sv = re.search(r'DASHBOARD_VERSION = "([^"]+)"', open(os.path.join(root, "server.py")).read()).group(1)
    js = open(os.path.join(root, "static", "app.js")).read()
    assert sv == re.search(r'PAGE_VERSION = "([^"]+)"', js).group(1)
    for f in ("etf_opportunity.py", "etf_prices.py", "etf_opportunity_diary.py"):
        src = open(os.path.join(root, f)).read()
        assert not re.search(r"[\"']portafoglio|import portfolio|PORTFOLIO_DIR", src)        # no personal data read
        assert "usProxy" not in src                                                     # real fund prices, never index proxies
        assert "anthropic" not in src.lower() and "claude -p" not in src                # no AI integration
    assert "function oppEtfHTML" in js and "data-eomode" in js and 'etf: "ETF · esposizioni e prodotti"' in js
    u = json.load(open(os.path.join(root, "etf_universe.json")))
    assert len(u["etfs"]) == 63                                                         # phase-24 universe unchanged
    sched = open(os.path.join(root, "schedule.sh")).read()
    assert "etf_prices" not in sched and "etf_opportunity" not in sched                 # no new scheduler


def test_26b_scan_is_fast_and_pure(data):
    c, p = data
    before = json.dumps(c, sort_keys=True, default=str)
    t0 = time.perf_counter()
    r = eo.scan(c, p, "lungo", now=NOW)
    assert time.perf_counter() - t0 < 2
    assert json.dumps(c, sort_keys=True, default=str) == before                          # inputs never modified
    pg = eo.page(r)
    assert len(pg["rows"]) == len(r["rows"]) and all(k in r["selected"] for k in (o["key"] for o in pg["selectedRows"]))
