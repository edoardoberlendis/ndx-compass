"""Phase 7B: compatibility with the portfolio (portfolio_fit.py and POST /api/portfolio/fit).

Only made-up portfolios, a made-up ETF catalogue and made-up price series. The real portfolio is never read: the
conftest points portafoglio/ to an empty temporary folder, and the server's portfolio snapshot is replaced by a
synthetic one where the endpoint is exercised. No network."""
import copy
import json
import logging
import math
import os

import numpy as np
import pandas as pd
import pytest

import app_env
import investment_decision_engine as de
import portfolio
import portfolio_fit as pf

AS_OF = "2026-11-04"
FX = {"USD": {"rate": 1.10, "date": AS_OF, "source": "cambio finto"}, "GBP": {"rate": 0.85, "date": "2026-10-01", "source": "cambio finto vecchio"}}
META = {"AAA": {"sector": "Technology", "country": "United States", "currency": "USD"},
        "BBB": {"sector": "Health Care", "country": "United States", "currency": "USD"},
        "GOOGL": {"sector": "Technology", "country": "United States", "currency": "USD"},
        "GOOG": {"sector": "Technology", "country": "United States", "currency": "USD"},
        "TSM": {"sector": "Technology", "country": "Taiwan", "currency": "USD"}}


def V(v, asof="2026-10-01", src="finto"):
    return {"v": v, "src": src, "asOf": asof}


def item(isin, name, ac="azionario", exposure="esp", top=None, n=None, sectors=None, countries=None, ccy=None, hedged=False,
         base="USD", duration=None, issuer="Emittente A", listings=(("TKA.MI", "EUR"),), stale=(), fund_key=None, holdings_date="2026-10-01"):
    ex = {}
    if top is not None:
        ex["top10"] = V([{"name": a, "weight": w} for a, w in top], holdings_date)
        ex["top10Weight"] = V(sum(w for _, w in top), holdings_date)
    if n is not None:
        ex["holdingsCount"] = V(n)
    if sectors:
        ex["sectors"] = V([{"name": a, "weight": w} for a, w in sectors], "2026-08-31")
    if countries:
        ex["countries"] = V([{"name": a, "weight": w} for a, w in countries], "2026-08-31")
    if ccy:
        ex["currencyExposure"] = V([{"currency": a, "weight": w} for a, w in ccy], "2026-08-31")
    return {"isin": isin, "identity": {"name": V(name), "issuer": V(issuer), "domicile": V("Irlanda"), "fundKey": V(fund_key or name.lower())},
            "fund": {"baseCurrency": V(base), "hedged": V(hedged)}, "classification": {"assetClass": ac, "exposure": exposure},
            "exposure": ex, "bond": {"duration": V(duration, "2026-11-03")} if duration is not None else {},
            "listings": [{"ticker": t.split(".")[0], "yahoo": t, "currency": V(c)} for t, c in listings],
            "freshness": {"stale": list(stale)}}


def catalog():
    items = {
        "IE00WORLD001": item("IE00WORLD001", "Mondo Finto ETF", exposure="mondo", n=1500,
                             top=[("AAA Inc.", 0.05), ("Alphabet Inc. Class A", 0.03), ("Taiwan Semiconductor Manufacturing Co Ltd ADR", 0.02)],
                             sectors=[("Technology", 30), ("Finance", 20), ("Other", 50)],
                             countries=[("United States", 70), ("Japan", 10), ("Other", 20)],
                             ccy=[("USD", 70), ("JPY", 10), ("altre", 20)], listings=(("WRLD.MI", "EUR"), ("WRLD.DE", "EUR"))),
        "IE00TECH0001": item("IE00TECH0001", "Tecnologia Finta ETF", exposure="tech", n=60, issuer="Emittente B",
                             top=[("AAA INC", 0.20), ("ALPHABET CLASS C", 0.10), ("CCC CORP", 0.10)],
                             sectors=[("Technology", 100)], countries=[("United States", 90), ("Netherlands", 10)],
                             ccy=[("USD", 90), ("EUR", 10)], listings=(("TECH.MI", "EUR"),), stale=("holdings",), holdings_date="2025-12-31"),
        "IE00HEDG0001": item("IE00HEDG0001", "Mondo Finto ETF EUR Hedged", exposure="mondo", hedged=True, base="EUR", n=1500,
                             top=[("AAA Inc.", 0.05)], sectors=[("Technology", 30), ("Other", 70)],
                             countries=[("United States", 70), ("Other", 30)], ccy=[("USD", 70), ("altre", 30)],
                             listings=(("WRLH.MI", "EUR"),), fund_key="mondo finto etf"),
        "IE00EMER0001": item("IE00EMER0001", "Emergenti Finto ETF", exposure="emergenti", n=3000,
                             top=[("TAIWAN SEMICONDUCTOR MANUFACTURING", 0.08), ("DDD LTD", 0.04)],
                             sectors=[("Technology", 25), ("Finance", 25), ("Other", 50)],
                             countries=[("Taiwan", 25), ("India", 20), ("China", 20), ("Other", 35)],
                             ccy=[("TWD", 25), ("INR", 20), ("CNY/HKD", 20), ("altre", 35)], listings=(("EMER.MI", "EUR"),)),
        "IE00BOND0001": item("IE00BOND0001", "Stato Euro Finto 1-3", ac="obbligazionario", exposure="gov", base="EUR", duration=1.9,
                             countries=[("Italy", 25), ("France", 25), ("Germany", 20), ("Other", 30)], ccy=[("EUR", 100)],
                             listings=(("BOND.MI", "EUR"),)),
        "IE00BOND0002": item("IE00BOND0002", "Societarie Finte", ac="obbligazionario", exposure="corp", base="EUR",
                             listings=(("CORP.MI", "EUR"),)),
    }
    excluded = {"JE00GOLD0001": dict(item("JE00GOLD0001", "Oro Finto ETC", ac="materie_prime", listings=(("GOLD.MI", "EUR"),)), exclusion="etc")}
    return {"items": items, "excluded": excluded}


def P(i, name, kind, **k):
    return dict({"id": i, "name": name, "kind": kind, "priceDate": AS_OF}, **k)


def book(**over):
    b = {"asOf": AS_OF, "fx": copy.deepcopy(FX), "positions": [
        P("a1", "AAA Inc.", "azione", ticker="AAA", qty=10, price=110.0, priceCurrency="USD"),           # 1,000 EUR
        P("a2", "BBB Corp", "azione", ticker="BBB", qty=20, price=55.0, priceCurrency="USD"),            # 1,000 EUR
        P("a3", "Alphabet Inc. Class A", "azione", ticker="GOOGL", value=500.0, valueCurrency="EUR"),
        P("e1", "Mondo Finto", "etf", isin="IE00WORLD001", ticker="WRLD.MI", value=3000.0, valueCurrency="EUR"),
        P("e2", "Tecnologia Finta", "etf", isin="IE00TECH0001", ticker="TECH.MI", value=2000.0, valueCurrency="EUR"),
        P("b1", "Stato Euro Finto", "etf", isin="IE00BOND0001", value=1500.0, valueCurrency="EUR"),
        P("c1", "Conto in euro", "liquidita", value=1000.0, valueCurrency="EUR")]}
    b.update(over)
    return b


def run(b=None, limits=None, series=None):
    n = pf.normalize(b or book(), catalog())
    return n, pf.analyse(n, META, limits, series)


def pos(an, i):
    return next(p for p in an["positions"] if p["id"] == i)


# ------------------------------------------------------------------ 1-6. normalisation, identity, currencies, weights

def test_01_normalisation_fields_and_classes():
    n, an = run()
    a1 = pos(an, "a1")
    assert a1["class"] == "azione" and math.isclose(a1["valueEUR"], 1000.0) and a1["listings"][0]["basis"] == "quantità × prezzo"
    assert "EUR/USD 1,1000 del 2026-11-04 (cambio finto)" in a1["listings"][0]["conversion"]
    assert {p["id"]: p["class"] for p in an["positions"]} == {"a1": "azione", "a2": "azione", "a3": "azione", "e1": "etf",
                                                             "e2": "etf", "b1": "etf", "c1": "liquidita"}
    assert math.isclose(an["totalEUR"], 10000.0) and math.isclose(sum(p["weight"] for p in an["positions"]), 100.0)
    assert pos(an, "b1")["assetClass"] == "Obbligazioni" and pos(an, "c1")["assetClass"] == "Liquidità"


def test_02_stock_identity_never_invented():
    b = book()
    b["positions"].append(P("x1", "Prodotto Misterioso", "certificato", value=100.0, valueCurrency="EUR"))
    n, an = run(b)
    x = pos(an, "x1")
    assert x["class"] == "sconosciuto" and "nessuna corrispondenza inventata" in x["recognised"]
    assert any(r["label"] == pf.UNCLASSIFIED for r in an["breakdown"]["sector"])
    assert "x1" not in {c["key"] for c in an["lookthrough"]["companies"]}
    assert pf.company_key("AAA Inc.") == pf.company_key("AAA INC")


def test_03_isin_listings_and_multiple_tickers():
    b = book()
    b["positions"].append(P("e1b", "Mondo Finto (Xetra)", "etf", isin="IE00WORLD001", ticker="WRLD.DE", value=1000.0, valueCurrency="EUR"))
    b["positions"].append(P("e3", "senza ISIN", "etf", ticker="EMER.MI", value=500.0, valueCurrency="EUR"))
    b["positions"].append(P("a4", "Alphabet Inc. Class C", "azione", ticker="GOOG", value=500.0, valueCurrency="EUR"))
    n, an = run(b)
    w = [p for p in an["positions"] if p["isin"] == "IE00WORLD001"]
    assert len(w) == 1 and len(w[0]["listings"]) == 2 and math.isclose(w[0]["valueEUR"], 4000.0)   # one fund, two listings
    assert any("2 quotazioni dello stesso ISIN" in x for x in an["notes"])
    e3 = pos(an, "e3")
    assert e3["isin"] == "IE00EMER0001" and "dal ticker EMER.MI" in e3["recognised"]
    alph = next(c for c in an["lookthrough"]["companies"] if c["key"] == "alphabet")
    assert math.isclose(alph["directEUR"], 1000.0)                                      # GOOGL + GOOG: one company
    tsm = [c for c in an["lookthrough"]["companies"] if c["key"] == "taiwan semiconductor"]
    assert len(tsm) == 1 and len(tsm[0]["via"]) == 2                                     # ADR (world) = local share (emerging)


def test_04_currencies_never_added_without_a_rate():
    b = book()
    b["positions"].append(P("g1", "Azione inglese", "azione", qty=100, price=850.0, priceCurrency="GBp"))   # pence
    b["positions"].append(P("j1", "Azione giapponese", "azione", qty=10, price=1000.0, priceCurrency="JPY"))
    n, an = run(b)
    g = pos(an, "g1")
    assert math.isclose(g["valueEUR"], 850 / 0.85) and g["indicative"]                  # 8.5 GBP / 0.85, old rate
    j = pos(an, "j1")
    assert j["valueEUR"] is None and j["weight"] is None
    assert math.isclose(an["totalEUR"], 10000.0 + 1000.0)                                # JPY left out, never added raw
    assert any("cambio EUR/JPY non disponibile" in m for m in an["missing"])
    assert any("indicativo" in m and "Azione inglese" in m for m in an["missing"])


def test_05_weights_and_concentration_numbers_without_judgement():
    n, an = run()
    c = an["concentration"]
    ws = sorted((p["weight"] for p in an["positions"]), reverse=True)
    assert math.isclose(c["top5"], sum(ws[:5])) and math.isclose(c["effective"], 1 / sum((w / 100) ** 2 for w in ws))
    assert an["limits"]["configured"] is False and {r["state"] for r in an["limits"]["rows"]} == {"non configurato"}
    assert "eccessiv" not in json.dumps(an, ensure_ascii=False).lower()
    n, an2 = run(limits={"position": 25, "sector": 90})
    st = {r["key"]: r["state"] for r in an2["limits"]["rows"]}
    assert st["position"] == "oltre il limite" and st["sector"] == "entro il limite" and st["country"] == "non configurato"


def test_06_cash_and_unknown_instruments():
    b = book(positions=[p for p in book()["positions"] if p["kind"] != "liquidita"])
    n, an = run(b)
    assert any("liquidità non nota" in m for m in an["missing"])
    n, an = run()
    c = pos(an, "c1")
    assert c["class"] == "liquidita" and c["lookthrough"] == "non applicabile"
    assert next(r for r in an["breakdown"]["currency"] if r["label"] == "EUR")["pct"] > 10


# ------------------------------------------------------------------ 7-11. look-through

def test_07_overlap_between_etfs():
    n, an = run()
    pair = an["lookthrough"]["fundPairs"][0]
    assert {pair["a"], pair["b"]} == {"Mondo Finto", "Tecnologia Finta"}
    assert set(pair["common"]) == {"aaa", "alphabet"} and math.isclose(pair["overlapKnown"], 5 + 3)   # Σ min of known weights


def test_08_overlap_between_stocks_and_etfs():
    n, an = run()
    aaa = next(c for c in an["lookthrough"]["companies"] if c["key"] == "aaa")
    assert math.isclose(aaa["directEUR"], 1000.0)
    assert math.isclose(aaa["indirectEUR"], 3000 * 0.05 + 2000 * 0.20) and aaa["sources"] == 3
    assert aaa["kind"] == "limite inferiore" and math.isclose(aaa["pct"], (1000 + 150 + 400) / 100)
    assert aaa in an["lookthrough"]["overlaps"]


def test_09_partial_holdings_are_never_complete():
    n, an = run()
    cov = an["lookthrough"]["coverage"]
    beyond = 3000 * (1 - 0.10) + 2000 * (1 - 0.40)
    assert math.isclose(cov["beyondKnown"], beyond / 100)
    assert pos(an, "e1")["lookthrough"] == "parziale (primi 10 titoli)"
    assert any("Mondo Finto: noti solo i titoli che pesano 10,0% del fondo" in m for m in an["missing"])


def test_10_no_double_counting():
    n, an = run()
    cov = an["lookthrough"]["coverage"]
    assert math.isclose(cov["check"], 100.0)
    comp = sum(c["totalEUR"] for c in an["lookthrough"]["companies"])
    assert math.isclose(comp + (cov["beyondKnown"] + cov["noData"] + cov["nonEquity"]) * an["totalEUR"] / 100, an["totalEUR"])
    for dim in ("assetClass", "sector", "country", "currency"):
        assert math.isclose(sum(r["pct"] for r in an["breakdown"][dim]), 100.0)


def test_11_dates_of_the_compositions():
    n, an = run()
    e2 = pos(an, "e2")
    assert e2["dates"]["holdings"] == "2025-12-31" and any("datati secondo le regole del catalogo" in x for x in e2["notes"])
    assert an["dates"]["composizioni ETF (più vecchia)"] == "2025-12-31"
    assert any("Tecnologia Finta: dato «holdings» datato" in m for m in an["missing"])


# ------------------------------------------------------------------ 12-14. sectors, geography, currencies

def test_12_sectors_mapped_with_unclassified_kept():
    n, an = run()
    sec = {r["label"]: r["pct"] for r in an["breakdown"]["sector"]}
    assert math.isclose(sec["Tecnologia"], (1000 + 500 + 3000 * 0.30 + 2000) / 100)
    assert math.isclose(sec["Sanità"], 10.0) and math.isclose(sec[pf.OTHER_SECTORS], 15.0)
    assert sec["Obbligazioni"] == 15.0 and sec["Liquidità"] == 10.0


def test_13_geography_with_other_countries_kept():
    n, an = run()
    cou = {r["label"]: r["pct"] for r in an["breakdown"]["country"]}
    assert math.isclose(cou["USA"], (1000 + 1000 + 500 + 2100 + 1800) / 100)
    assert math.isclose(cou[pf.OTHER_COUNTRIES], (600 + 1500 * 0.30) / 100) and "Italia" in cou


def test_14_economic_currency_and_hedging():
    b = book()
    b["positions"].append(P("h1", "Mondo coperto", "etf", isin="IE00HEDG0001", value=1000.0, valueCurrency="EUR"))
    n, an = run(b)
    h, w = pos(an, "h1"), pos(an, "e1")
    assert h["hedged"] and w["trading"] == ["EUR"] and not w["hedged"]
    cur = {r["label"]: r for r in an["breakdown"]["currency"]}
    assert math.isclose(cur["USD"]["valueEUR"], 1000 + 1000 + 500 + 3000 * 0.7 + 2000 * 0.9)   # EUR-traded ETF is still USD
    assert math.isclose(cur["EUR"]["valueEUR"], 2000 * 0.1 + 1500 + 1000 + 1000)               # hedged class counted as EUR
    assert "stima" in cur["USD"]["quality"] and any("copertura del cambio" in x for x in h["notes"])


# ------------------------------------------------------------------ 15-17. risk

def series(n=300, seed=1, vol=0.01, start="2025-08-01"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    return pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, vol, n)), index=idx)


def test_15_volatility_and_correlations_when_computable():
    s = {"a1": series(seed=1), "a2": series(seed=2), "e1": series(seed=3, vol=0.008), "e2": series(seed=4, vol=0.015),
         "b1": series(seed=5, vol=0.002), "a3": series(seed=6)}
    n, an = run(series=s)
    r = an["risk"]
    assert r["state"] == "calcolato" and r["coveragePct"] == 100.0 and r["sessions"] >= pf.MIN_DAYS
    assert 5 < r["vol"] < 40 and r["maxDrawdown"] < 0 and r["correlations"] and all(c["weeks"] >= pf.MIN_WEEKS for c in r["correlations"])
    assert any("non sono stabili né garantite" in x for x in r["limits"]) and "liquidità è esclusa" in r["cashNote"]
    assert "VaR" not in json.dumps(r) and "probabilit" not in json.dumps(r, ensure_ascii=False)


def test_16_incomplete_series():
    n, an = run(series={"a1": series(n=60)})
    assert an["risk"]["state"] == "non calcolabile" and "affidabilità sufficiente" in an["risk"]["why"]
    bad = series(seed=7)
    bad.iloc[150] = bad.iloc[149] * 3
    n, an = run(series={"a1": series(seed=1), "a2": bad, "e1": series(seed=3)})
    left = {x["name"]: x["why"] for x in an["risk"]["left"]}
    assert "salti di un giorno" in left["BBB Corp"] and "non disponibile" in left["Tecnologia Finta"]
    assert an["risk"]["state"] == "calcolato" and an["risk"]["coveragePct"] < 100
    n, an = run(series={"a1": series(seed=1, start="2025-01-01"), "e1": series(seed=2, start="2026-03-01")})
    assert an["risk"]["state"] == "non calcolabile" and "sedute in comune" in an["risk"]["why"]   # not aligned


def test_17_bond_duration_only_on_the_bond_part():
    b = book()
    b["positions"].append(P("b2", "Societarie Finte", "etf", isin="IE00BOND0002", value=500.0, valueCurrency="EUR"))
    n, an = run(b)
    d = an["duration"]
    assert math.isclose(d["duration"], 1.9) and math.isclose(d["coveredPct"], 1500 / 2000 * 100)
    assert d["unknown"] == ["Societarie Finte"] and "non si applica alle azioni" in d["note"]
    rates = next(s for s in an["stress"] if "rendimenti" in s["scenario"])
    assert math.isclose(rates["impactEUR"], -1500 * 1.9 / 100) and "senza duration" in rates["note"]
    eq = next(s for s in an["stress"] if "−10%" in s["scenario"] or "-10%" in s["scenario"])
    assert "non una previsione" in eq["kind"]


# ------------------------------------------------------------------ 18-19. compatibility and what-if

def test_18_compatibility_is_separate_from_the_decision_desk():
    n, an = run()
    d2 = {"state": "Da approfondire", "rule": "A-A1", "version": "D2"}
    c = pf.compatibility(an, n, {"kind": "azione", "ticker": "AAA", "name": "AAA Inc."}, catalog(), META, d2)
    codes = {t["code"] for t in c["tags"]}
    assert c["d2"] == d2 and c["present"]["direct"] and "C-P1" in codes and "C-I1" in codes and "C-S1" in codes
    assert not any(k in c for k in ("score", "punteggio")) and "non un punteggio" in c["rule"]
    c2 = pf.compatibility(an, n, {"kind": "etf", "isin": "IE00EMER0001"}, catalog(), META,
                          {"state": "Nessuna opportunità convincente", "rule": "E-N1", "version": "D2"})
    codes2 = {t["code"] for t in c2["tags"]}
    assert "C-N1" in codes2 and c2["d2"]["state"] == "Nessuna opportunità convincente"        # diversifies, state unchanged
    assert {x["label"] for x in c2["new"]["country"]} >= {"Taiwan", "India", "Cina"}
    c3 = pf.compatibility(an, n, {"kind": "etf", "isin": "IE00HEDG0001"}, catalog(), META)
    assert "C-P2" in {t["code"] for t in c3["tags"]} and c3["equivalent"][0]["how"] == "stesso fondo, altra classe"
    c4 = pf.compatibility(an, n, {"kind": "azione", "ticker": "ZZZ", "name": "Zeta Sconosciuta"}, catalog(), {})
    assert c4["insufficient"] and "C-D1" in {t["code"] for t in c4["tags"]}


def test_18b_the_desk_state_is_never_changed():
    import test_decision_engine as t7
    snap = t7.snapshot([t7.inv_item("AAA")], [t7.val_item("AAA")])
    before = json.dumps(de.decide(copy.deepcopy(snap)), sort_keys=True, default=str)
    n, an = run()
    pf.compatibility(an, n, {"kind": "azione", "ticker": "AAA", "name": "AAA Inc."}, catalog(), META, {"state": "Da approfondire"})
    assert json.dumps(de.decide(copy.deepcopy(snap)), sort_keys=True, default=str) == before
    import inspect
    assert list(inspect.signature(de.decide).parameters) == ["snap", "version"]          # no portfolio input to the desk


def test_19_what_if_simulations():
    b, cat = book(), catalog()
    original = copy.deepcopy(b)
    s = pf.simulate(b, cat, {"kind": "azione", "ticker": "CCC", "name": "CCC Corp"}, 1000, funding="nuova", stock_meta=META)
    assert s["ok"] and math.isclose(s["after"]["totalEUR"], 11000.0) and "non è un ordine" in s["note"]
    ccc = next(c for c in s["companies"] if c["name"] == "CCC Corp")
    assert math.isclose(ccc["before"], 2.0) and math.isclose(ccc["after"], (200 + 1000) / 110)        # already indirect via the tech ETF
    s2 = pf.simulate(b, cat, {"kind": "etf", "isin": "IE00TECH0001"}, 1000, funding="liquidita", stock_meta=META)
    assert s2["ok"] and math.isclose(s2["after"]["totalEUR"], 10000.0)
    assert any("Tecnologia" in r for r in s2["risks"])
    s3 = pf.simulate(b, cat, {"kind": "etf", "isin": "IE00EMER0001"}, 1000, funding="riduzione", reduce_id="e2", stock_meta=META)
    assert s3["ok"] and s3["after"]["effective"] > s3["before"]["effective"]
    assert any(r["label"] == "Taiwan" and r["before"] == 0 for r in s3["delta"]["country"])
    assert pf.simulate(b, cat, {"kind": "etf", "isin": "IE00EMER0001"}, 5000, funding="liquidita")["why"].startswith("liquidità nota")
    nocash = book(positions=[p for p in b["positions"] if p["kind"] != "liquidita"])
    assert "liquidità non nota" in pf.simulate(nocash, cat, {"kind": "etf", "isin": "IE00EMER0001"}, 100, funding="liquidita")["why"]
    assert "meno dell'importo" in pf.simulate(b, cat, {"kind": "etf", "isin": "IE00EMER0001"}, 9000, funding="riduzione", reduce_id="b1")["why"]
    usd = pf.simulate(b, cat, {"kind": "etf", "isin": "IE00EMER0001"}, 1100, "USD", "nuova")
    assert usd["ok"] and math.isclose(usd["amountEUR"], 1000.0) and "EUR/USD" in usd["conversion"]
    assert "non disponibile" in pf.simulate(b, cat, {"kind": "etf", "isin": "IE00EMER0001"}, 100, "CHF", "nuova")["why"]
    lim = pf.simulate(b, cat, {"kind": "etf", "isin": "IE00TECH0001"}, 3000, funding="nuova", stock_meta=META, limits={"sector": 55})
    assert any("supererebbe il limite personale per singolo settore" in r for r in lim["risks"])
    assert b == original                                                                  # the portfolio given is never changed


# ------------------------------------------------------------------ 20-26. privacy, explicit activation, API

@pytest.fixture
def server_fit(monkeypatch):
    import etf_catalog
    import server
    calls = {"snapshot": 0}
    fake_pf = {"file": "finto.xls", "fileTime": 1793800000.0, "quotesAt": 1793850000.0, "fx": 1.10, "error": None, "resolving": False,
               "positions": [{"name": "AAA Inc.", "isin": "US0000000AAA", "ticker": "AAA", "kind": "Azione", "currency": "USD",
                              "value": 1000.0, "live": True, "sector": "Tecnologia", "country": "USA"},
                             {"name": "Mondo Finto", "isin": "IE00WORLD001", "ticker": "WRLD.MI", "kind": "ETF", "currency": "EUR",
                              "value": 3000.0, "live": False, "sector": "Non classificato", "country": "Non classificato"}]}

    def snapshot(*a, **k):
        calls["snapshot"] += 1
        return copy.deepcopy(fake_pf)
    monkeypatch.setattr(portfolio, "snapshot", snapshot)
    monkeypatch.setattr(portfolio, "refresh", lambda *a, **k: pytest.fail("no export read"))
    monkeypatch.setattr(portfolio, "read_export", lambda *a, **k: pytest.fail("no export read"))
    monkeypatch.setattr(etf_catalog, "load", lambda *a, **k: catalog())
    monkeypatch.setattr(server.store, "snapshot", {"stocks": [{"ticker": "AAA", "name": "AAA Inc.", "sector": "Tecnologia"},
                                                              {"ticker": "BBB", "name": "BBB Corp", "sector": "Sanità"}]})
    monkeypatch.setattr(server.store, "infos", {"AAA": {"country": "United States"}})
    monkeypatch.setattr(server.store, "error", None)
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download"))
    monkeypatch.setattr(server, "decisions", lambda: None)
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no network"))
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("no network"))
    return server.app.test_client(), calls


H = {"X-Requested-With": "ndx-dashboard"}
LOCAL = {"REMOTE_ADDR": "127.0.0.1"}


def post(client, body, headers=H):
    return client.post("/api/portfolio/fit", json=body, headers=headers, environ_base=LOCAL, base_url="http://127.0.0.1:8100")


def test_20_real_portfolio_never_modified_and_nothing_written(server_fit):
    client, calls = server_fit
    with app_env.record_writes() as seen:
        r = post(client, {"consent": True, "source": "mio", "candidate": "BBB", "whatif": {"amount": 500, "funding": "nuova"}})
    assert r.status_code == 200, r.data
    assert [w for w in seen if w[1].startswith(app_env.ROOT) and "__pycache__" not in w[1]] == []
    d = r.get_json()
    assert d["available"] and d["whatif"]["ok"] and math.isclose(d["analysis"]["totalEUR"], 4000.0)
    assert portfolio.PORTFOLIO_DIR != os.path.join(app_env.ROOT, "portafoglio")          # tests never see the real folder


def test_21_no_automatic_read_of_personal_data(server_fit, monkeypatch):
    client, calls = server_fit
    import server
    monkeypatch.setattr(server, "decisions", lambda: de.decide({"asOf": "2026-11-03T17:30:00-05:00", "session": "2026-11-03"}))
    assert client.get("/api/decisions").status_code in (200, 503)
    client.get("/api/decisions/azione:AAA:lungo")
    assert client.get("/api/portfolio/fit").status_code == 405                          # never a GET
    assert post(client, {"source": "mio"}).status_code == 400                            # no consent, no read
    assert post(client, {"consent": "yes", "source": "mio"}).status_code == 400
    assert calls["snapshot"] == 0
    js = open(os.path.join(app_env.ROOT, "static", "app.js")).read()
    assert 'if (PF_SUBS.includes(state.view) && state.view !== "pffit") loadPortfolio();' in js


def test_22_explicit_activation(server_fit):
    client, calls = server_fit
    d = post(client, {"consent": True, "source": "esempio"}).get_json()
    assert d["available"] and d["source"] == "esempio" and calls["snapshot"] == 0          # the example never reads mine
    d = post(client, {"consent": True, "source": "mio"}).get_json()
    assert calls["snapshot"] == 1 and d["source"] == "mio" and "sola lettura" in d["sourceLabel"]
    js = open(os.path.join(app_env.ROOT, "static", "app.js")).read()
    assert "Analizza compatibilità con il mio portafoglio" in js and "consent: true" in js


def test_23_no_transmission_and_no_personal_data_in_logs(server_fit, monkeypatch, caplog):
    client, calls = server_fit
    import portfolio_fit
    monkeypatch.setattr(portfolio_fit, "analyse", lambda *a, **k: (_ for _ in ()).throw(ValueError("AAA Inc. 1000 euro")))
    with caplog.at_level(logging.INFO, logger="ndx"):
        r = post(client, {"consent": True, "source": "mio"})
    assert r.status_code == 500 and "AAA" not in r.get_data(as_text=True)
    assert "AAA" not in caplog.text and "1000" not in caplog.text and "ValueError" in caplog.text
    src = open(portfolio_fit.__file__).read()
    assert "requests" not in src and "yfinance" not in src and "open(" not in src          # no network, no file in the engine


def test_24_api_read_only_local_and_never_cached(server_fit):
    client, calls = server_fit
    assert post(client, {"consent": True, "source": "mio"}, headers={}).status_code == 403     # only from the dashboard
    r = post(client, {"consent": True, "source": "mio"})
    assert r.headers["Cache-Control"] == "no-store"
    assert post(client, {"consent": True, "source": "altro"}).status_code == 400


def test_25_isolation_test_preview_production():
    import server
    assert app_env.env() == "test"
    assert not portfolio.PORTFOLIO_DIR.startswith(os.path.join(app_env.ROOT, "portafoglio"))
    book_, why = server.fit_book("mio", {"stocks": []}, {})                                # the isolated folder is empty
    assert book_ is None and "nessun export" in why
    pv = open(os.path.join(app_env.ROOT, "preview.py")).read()
    assert "app_env.isolate(BASE" in pv and "VUOTA" in pv                               # preview: empty private folder


def test_26_other_sections_unchanged():
    js = open(os.path.join(app_env.ROOT, "static", "app.js")).read()
    assert '["pfrisk", "Rischio"], ["pffit", "Compatibilità"]' in js and "dkFitHTML(o)" in js
    import server
    src = open(server.__file__).read()
    api = src[src.index("def api_decisions"):src.index("def save_decision_diary")]
    assert "portfolio" not in api                                                         # the desk API never reads the portfolio
    assert server.DASHBOARD_VERSION in js


def test_27_demo_book_has_the_required_parts():
    b = pf.demo_book(AS_OF)
    kinds = [p["kind"] for p in b["positions"]]
    assert kinds.count("azione") >= 3 and kinds.count("etf") >= 3 and "liquidita" in kinds and b["source"] == "esempio"
    assert any(p.get("isin") == "IE00B14X4Q57" for p in b["positions"])                   # a bond ETF


# ------------------------------------------------------------------ Phase 7C: origin of the requests, logs, risk coverage

def test_7c_01_requests_from_other_sites_are_refused(server_fit):
    client, calls = server_fit
    body = {"consent": True, "source": "mio"}
    ok = client.post("/api/portfolio/fit", json=body, headers={**H, "Origin": "http://127.0.0.1:8100"}, environ_base=LOCAL,
                     base_url="http://127.0.0.1:8100")
    assert ok.status_code == 200                                                         # the dashboard's own origin
    for origin in ("http://127.0.0.1:3000", "http://localhost:8100", "null", "https://sito-esterno.example"):
        r = client.post("/api/portfolio/fit", json=body, headers={**H, "Origin": origin}, environ_base=LOCAL,
                        base_url="http://127.0.0.1:8100")
        assert r.status_code == 403, origin                                              # not even another local port
    # DNS rebinding: a foreign name pointed to 127.0.0.1 carries its own Host header
    r = client.post("/api/portfolio/fit", json=body, headers=H, environ_base=LOCAL, base_url="http://sito-esterno.example:8100")
    assert r.status_code == 403
    assert client.get("/api/portfolio", environ_base=LOCAL, base_url="http://sito-esterno.example:8100").status_code == 403
    assert client.get("/api/portfolio/risk", environ_base=LOCAL, base_url="http://sito-esterno.example:8100").status_code == 403
    r = client.post("/api/portfolio/fit", json=body, headers=H, environ_base={"REMOTE_ADDR": "192.168.1.20"},
                    base_url="http://127.0.0.1:8100")
    assert r.status_code == 403                                                          # another computer
    assert calls["snapshot"] == 1                                                        # only the allowed request read it


def test_7c_02_consent_alone_is_not_enough(server_fit):
    client, calls = server_fit
    assert post(client, {"consent": True, "source": "mio"}, headers={}).status_code == 403       # consent without the header
    assert post(client, {"consent": True, "source": "mio"}, headers={"X-Requested-With": "XMLHttpRequest"}).status_code == 403
    assert post(client, {"consent": "true", "source": "mio"}).status_code == 400                 # header without real consent
    assert post(client, {"consent": 1, "source": "mio"}).status_code == 400
    assert calls["snapshot"] == 0
    r = client.options("/api/portfolio/fit", headers={"Origin": "https://sito-esterno.example",
                                                      "Access-Control-Request-Method": "POST",
                                                      "Access-Control-Request-Headers": "x-requested-with"},
                       environ_base=LOCAL, base_url="http://127.0.0.1:8100")
    assert "Access-Control-Allow-Origin" not in r.headers                                # a CORS preflight is never approved


def test_7c_03_no_personal_data_in_logs_on_success(server_fit, caplog):
    client, calls = server_fit
    with caplog.at_level(logging.DEBUG):
        r = post(client, {"consent": True, "source": "mio", "candidate": "BBB", "whatif": {"amount": 777, "funding": "nuova"}})
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    for secret in ("AAA Inc.", "Mondo Finto", "US0000000AAA", "1000", "3000", "777", "finto.xls"):
        assert secret not in caplog.text, secret


def _scope_sum(r):
    return r["coverageTotalPct"] + r["uncoveredTotalPct"] + r["cashPct"]


def test_7c_04_partial_coverage_is_never_the_whole_portfolio():
    n, an = run(series={"e1": series(seed=1), "e2": series(seed=2), "b1": series(seed=3, vol=0.002)})
    r = an["risk"]
    assert r["state"] == "calcolato" and r["scope"] == "parziale"
    assert math.isclose(r["coveragePct"], 6500 / 9000 * 100)                             # of the invested part
    assert math.isclose(r["coverageTotalPct"], 6500 / 10000 * 100)                       # of the whole portfolio
    assert math.isclose(r["cashPct"], 10.0) and math.isclose(_scope_sum(r), 100.0)
    assert "NON rappresentano il rischio complessivo" in r["scopeText"] and "liquidità (10,0%) è esclusa" in r["scopeText"]
    assert "pesi di oggi" in r["weightsNote"] and "pesi di oggi" in r["method"]
    assert any("65,0% del portafoglio" in x for x in r["limits"])


def test_7c_05_full_coverage_still_says_cash_is_left_out():
    s = {i: series(seed=k) for k, i in enumerate(("a1", "a2", "a3", "e1", "e2", "b1"), 1)}
    r = run(series=s)[1]["risk"]
    assert r["scope"] == "parte investita" and math.isclose(r["coveragePct"], 100.0)
    assert math.isclose(r["coverageTotalPct"], 90.0) and "non sono il rischio dell'intero portafoglio" in r["scopeText"]
    r = run(series={})[1]["risk"]
    assert r["state"] == "non calcolabile" and r["scope"] == "nessuna" and "Nessuna parte" in r["scopeText"]
    b = book()
    b["positions"].append(P("x1", "Senza Cambio", "azione", ticker="TSM", value=100.0, valueCurrency="CHF"))
    r = run(b, series=s)[1]["risk"]
    assert r["unvaluedCount"] == 1 and r["scope"] == "parziale" and "senza valore in euro" in r["scopeText"]


def test_7c_06_page_labels_the_risk_by_what_it_covers():
    js = open(os.path.join(app_env.ROOT, "static", "app.js")).read()
    card = js[js.index("<h3>Rischio (descrittivo)</h3>"):js.index("Ipotesi deterministiche")]
    assert card.index("R.scopeText") < card.index("volatilità annua")                     # coverage before the figures
    assert "Rischio parziale" in card and "Della sola parte coperta" in card and "R.weightsNote" in card
    assert "non coperto" in card and "liquidità esclusa" in card
