"""Phase 6A: UCITS ETF catalogue and comparison (etf_catalog.py, etf_catalog_build.py, etf_comparison.py).

Only made-up data: invented ISINs (with a valid check digit), fake exchange pages, a fake issuer list, fake volumes.
The real build is run offline on them; any network call fails the test."""
import json
import os
import time

import pytest

import etf_catalog as cat
import etf_catalog_build as build
import etf_comparison as cmp


def make_isin(body):
    """A syntactically valid ISIN from 11 characters (computes the check digit)."""
    for d in "0123456789":
        if cat.isin_valid(body + d):
            return body + d
    raise AssertionError(body)


WA, WB, WC = make_isin("ZZ000000001"), make_isin("ZZ000000002"), make_isin("ZZ000000003")   # world: acc, dist other fund, hedged class
BA, BB = make_isin("ZZ000000004"), make_isin("ZZ000000005")                                  # govt bonds 1-3y, two indices
TA = make_isin("ZZ000000006")                                                                # tech theme
GE, LV = make_isin("ZZ000000007"), make_isin("ZZ000000008")                                  # gold ETC, leveraged ETF
TODAY = time.strftime("%Y-%m-%d")


def je(name, index, rep="Physical", method="Full replication", ccy="USD Currency unhedged", dist="Accumulating", legal="ETF",
       ter=0.2, size=1000.0, mi=None, de=None, countries=None, sectors=None, count=500):
    return {"source": "x", "date": "2026-10-08", "name": name, "index": index, "ter": ter, "sizeEurM": size, "distribution": dist,
            "replication": rep, "replicationMethod": method, "legal": legal, "fundCurrency": ccy.split()[0], "hedge": " ".join(ccy.split()[1:]),
            "launch": "25 September 2009", "holdingsCount": count, "holdingsDate": "As of 31/08/2026",
            "countries": countries or [["United States", 70.0], ["Japan", 6.0], ["Other", 24.0]],
            "sectors": sectors or [["Technology", 30.0], ["Other", 70.0]], "tickerMI": mi, "tickerDE": de}


UNIVERSE = {"etfs": [
    {"isin": WA, "justetf": je("Alfa Core World UCITS ETF (Acc)", "MSCI World", method="Optimized sampling", mi="AWLD", de="AWLX")},
    {"isin": WB, "justetf": je("Beta World UCITS ETF Dist", "MSCI World", dist="Distributing", ter=0.12, size=20000.0, mi="BWLD")},
    {"isin": BA, "justetf": je("Alfa Euro Govt 1-3 UCITS ETF", "Bloomberg Euro Government Bond 1-3", method="Sampling",
                               ccy="EUR Currency unhedged", dist="Distributing", ter=0.1, mi="AGOV", count=16)},
    {"isin": BB, "justetf": je("Gamma Eurozone Govt 1-3 UCITS ETF 1C", "iBoxx EUR Eurozone 1-3", method="Sampling",
                               ccy="EUR Currency unhedged", ter=0.1, mi="GGOV", count=30)},
    {"isin": TA, "justetf": je("Delta AI Robots UCITS ETF", "Delta AI Index", ter=0.45, size=60.0, mi="DAIR")},
    {"isin": GE, "justetf": je("Epsilon Physical Gold ETC", "Gold", method="Physically backed", legal="ETC", mi="EGLD")},
    {"isin": LV, "justetf": je("Zeta Nasdaq 3x Leveraged UCITS ETF", "Nasdaq 100", rep="Synthetic", method="Unfunded swap", mi="ZLEV")},
]}
ISH = {"1": {"isin": WA, "fundName": "Alfa Core World UCITS ETF", "investorClassName": "- ", "useOfProfits": "Ad Accumulazione",
             "seriesBaseCurrencyCode": "USD", "domicile": "Irlanda", "ter_ocf": {"d": "0,20", "r": 0.2},
             "totalFundSizeInMillions": {"d": "", "r": 150000.0}, "totalFundSizeInMillionsAsOf": {"d": "", "r": 20261103},
             "totalNetAssets": {"d": "", "r": 140e9}, "inceptionDate": {"d": "", "r": 20090925}},
       "2": {"isin": WC, "fundName": "Alfa Core World UCITS ETF", "investorClassName": "Hedged", "useOfProfits": "Distribuzione",
             "seriesBaseCurrencyCode": "EUR", "domicile": "Irlanda", "ter_ocf": {"d": "0,30", "r": 0.3},
             "totalFundSizeInMillions": {"d": "", "r": 150000.0}, "totalFundSizeInMillionsAsOf": {"d": "", "r": 20261103},
             "totalNetAssets": {"d": "", "r": 4e9}, "inceptionDate": {"d": "", "r": 20200101}},
       "3": {"isin": BA, "fundName": "Alfa Euro Govt 1-3 UCITS ETF", "investorClassName": "- ", "useOfProfits": "Distribuzione",
             "seriesBaseCurrencyCode": "EUR", "domicile": "Irlanda", "ter_ocf": {"d": "0,10", "r": 0.1},
             "totalFundSizeInMillions": {"d": "", "r": 1700.0}, "totalFundSizeInMillionsAsOf": {"d": "", "r": 20261103},
             "effectiveDuration": {"d": "1,9", "r": 1.9}, "yieldToWorst": {"d": "2,1", "r": 2.1}, "distYield": {"d": "2", "r": 2.0},
             "navAmountAsOf": {"d": "", "r": 20261103}}}
HOLD = {WA: {"label": "Alfa, file delle composizioni", "kind": "emittente", "asOf": "2026-10-08", "fetched": "2026-10-10", "source": "x",
             "top": [{"key": k, "name": k.upper(), "weight": w} for k, w in [("nvidia", .05), ("apple", .05), ("microsoft", .04), ("amazon", .03)]]},
        WB: {"label": "Beta, file delle composizioni", "kind": "emittente", "asOf": None, "fetched": "2026-10-10", "source": "x",
             "top": [{"key": k, "name": k.upper(), "weight": w} for k, w in [("nvidia", .05), ("apple", .05), ("tesla", .02)]]},
        TA: {"label": "Delta", "kind": "emittente", "asOf": "2026-10-01", "fetched": "2026-10-02", "source": "x",
             "top": [{"key": k, "name": k.upper(), "weight": w} for k, w in [("nvidia", .09), ("abb", .08)]]}}


def bi_html(isin, ticker, ter, ccy, dividends, typ="ETF"):
    cells = ["Tipo strumento", typ, "Classe", "Classe 2 Ind Azionario", "Codice Alfanumerico", ticker, "Codice Isin", isin, "MIC", "ETFP",
             "Lotto Minimo", "1,00", "Commissioni totali annue", ter, "Valuta di Denominazione", ccy, "Emittente", "ALFA III PLC",
             "Segmento", "ETF Indicizzati", "Benchmark", "MSCI TRN WORLD INDEX", "Stile Benchmark", "Sviluppati", "Area Benchmark", "EQUITY WORLD",
             "Dividendi", dividends, "Documenti", "Prospetto", "02/11/2026 - (", "KIID", "14/09/2026 - (", "Fine"]
    return "<html><body>" + "".join(f"<td>{c}</td>" for c in cells) + "</body></html>"


def book_html(isin, ticker, phase, bid="100,00", ask="100,10"):
    cells = ["Codice Isin", isin, "Codice Alfanumerico", ticker, "Fase di Mercato", phase, "Volume totale", "1.000", "Numero Contratti", "12",
             "Controvalore", "100.050,00", "Prezzo ufficiale", "100,02 - 03/11/26", "Numero Proposte", "Volume Acquisto", "Prezzo Acquisto",
             "Prezzo Vendita", "Volume Vendita", "Numero Proposte", "1", "2", "500", bid, ask, "400", "3", "2", "1", "100", "99,90", "100,20", "50", "1",
             "Legenda", "x"]
    return "<html><body>" + "".join(f"<td>{c}</td>" for c in cells) + "</body></html>"


YAHOO = {"AWLD.MI": {"currency": "EUR", "days": 60, "avgVolume": 90000.0, "avgTurnover": 9e6, "zeroDays": 0, "last": TODAY, "close": 100.0},
         "AWLX.DE": {"currency": "EUR", "days": 62, "avgVolume": 300000.0, "avgTurnover": 3e7, "zeroDays": 0, "last": TODAY, "close": 100.0},
         "BWLD.MI": {"currency": "EUR", "days": 60, "avgVolume": 200.0, "avgTurnover": 2e4, "zeroDays": 20, "last": TODAY, "close": 100.0},
         "AGOV.MI": {"currency": "EUR", "days": 60, "avgVolume": 5000.0, "avgTurnover": 6e5, "zeroDays": 0, "last": TODAY, "close": 120.0},
         "GGOV.MI": {"currency": "EUR", "days": 60, "avgVolume": 5000.0, "avgTurnover": 6e5, "zeroDays": 0, "last": TODAY, "close": 140.0},
         "DAIR.MI": None, "EGLD.MI": None, "ZLEV.MI": None}


@pytest.fixture
def built(tmp_path, monkeypatch):
    """Runs the real build offline on the made-up inputs; any network access fails."""
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no network in the tests"))
    raw = tmp_path / "raw"
    raw.mkdir()
    (tmp_path / "universe.json").write_text(json.dumps(UNIVERSE))
    (tmp_path / "hold.json").write_text(json.dumps(HOLD))
    (raw / "ishares_list.json").write_text(json.dumps(ISH))
    (raw / "ishares_list.json.meta").write_text(json.dumps({"fetched": TODAY}))
    pages = {WA: ("AWLD", "0,20%", "USD", "CAPITALIZED", "ETF", "Closed"), WB: ("BWLD", "0,12%", "USD", "DISTRIBUTION", "ETF", "Continuous Trading"),
             BA: ("AGOV", "0,10%", "EUR", "DISTRIBUTION", "ETF", "Closed"), BB: ("GGOV", "0,15%", "EUR", "CAPITALIZED", "ETF", "Closed"),
             TA: ("DAIR", "0,45%", "USD", "CAPITALIZED", "ETF", "Closed"), LV: ("ZLEV", "0,60%", "USD", "CAPITALIZED", "ETF", "Closed")}
    for isin, (t, ter, ccy, div, typ, phase) in pages.items():
        for kind, html in (("scheda", bi_html(isin, t, ter, ccy, div, typ)), ("book", book_html(isin, t, phase))):
            (raw / f"bi_{kind}_{isin}.html").write_text(html)
            (raw / f"bi_{kind}_{isin}.html.json").write_text(json.dumps({"fetched": TODAY, "url": f"https://example.invalid/{isin}", "at": TODAY + "T15:00"}))
    C = {}
    for isins, ac, fam, exp, key in [((WA, WB, WC), "azionario", "globale", "mondo_sviluppati", "msci world"),
                                     ((BA,), "obbligazionario", "governativi_euro", "gov_euro_1_3", "bloomberg euro government 1-3"),
                                     ((BB,), "obbligazionario", "governativi_euro", "gov_euro_1_3", "iboxx eur eurozone 1-3"),
                                     ((TA,), "azionario", "tecnologia", "intelligenza_artificiale", "delta ai"),
                                     ((GE,), "materie_prime", "metalli", "oro", "oro"), ((LV,), "azionario", "usa", "usa_nasdaq100", "nasdaq 100")]:
        for i in isins:
            C[i] = {"assetClass": ac, "family": fam, "exposure": exp, "label": exp, "indexKey": key, "theme": fam == "tecnologia",
                    "bondKind": "titoli di Stato" if ac == "obbligazionario" else None, "credit": "investment grade" if ac == "obbligazionario" else None}
    monkeypatch.setattr(build, "C", C)
    monkeypatch.setattr(build, "ADDED", {WC: "classe coperta dello stesso fondo di AWLD"})
    monkeypatch.setattr(build, "UNIVERSE", str(tmp_path / "universe.json"))
    monkeypatch.setattr(build, "HOLDINGS", str(tmp_path / "hold.json"))
    monkeypatch.setattr(build, "RAW", str(raw))
    monkeypatch.setattr(build, "yahoo_listings", lambda syms, offline: ({s: YAHOO.get(s) for s in syms}, TODAY))
    out = tmp_path / "catalog"
    build.main(["--offline", "--out", str(out)])
    monkeypatch.setattr(cat, "DIR", str(out))
    cat._cache.update(key=None, data=None)
    return cat.load(str(out))


# 1-2: identifiers
def test_01_isin_identifies_the_share_class(built):
    assert set(built["items"]) == {WA, WB, WC, BA, BB, TA}
    a, c = built["items"][WA], built["items"][WC]
    assert cat.val(a["identity"]["fundKey"]) == cat.val(c["identity"]["fundKey"])       # same fund, two classes, two entries
    assert cat.find(built, "awld")["isin"] == WA and cat.find(built, WA.lower())["isin"] == WA


def test_02_identifier_validation():
    assert cat.isin_valid("IE00B4L5Y983") and cat.isin_valid("US0378331005") and cat.isin_valid(WA)
    for bad in ("IE00B4L5Y984", "IE00B4L5Y98", "ie00b4l5y983", "1E00B4L5Y983", None, 12345, "IE00B4L5Y98X"):
        assert not cat.isin_valid(bad)
    assert cat.domicile_from_isin("LU0290356871") == "Lussemburgo"


# 3-4: listings and currencies
def test_03_many_tickers_one_entry(built):
    a = built["items"][WA]
    assert [(l["mic"], l["ticker"]) for l in a["listings"]] == [("ETFP", "AWLD"), ("XETR", "AWLX")]
    assert {"AWLD", "AWLX"} <= set(cat.tickers(a)) and cat.find(built, "AWLX")["isin"] == WA
    assert len(cat.search(built, "AWLX")) == 1


def test_04_trading_currency_is_not_the_exposure(built):
    a = built["items"][WA]
    assert cat.val(a["fund"]["baseCurrency"]) == "USD"                                  # NAV of the class
    assert {cat.val(l["currency"]) for l in a["listings"]} == {"EUR"}                    # what I pay
    fx = cat.val(a["exposure"]["currencyExposure"])
    assert fx[0]["currency"] == "USD" and "stima" in a["exposure"]["currencyExposure"]["note"]


# 5-6: share class features
def test_05_acc_and_dist(built):
    assert cat.val(built["items"][WA]["fund"]["distribution"]) == "accumulazione"
    assert cat.val(built["items"][WB]["fund"]["distribution"]) == "distribuzione"
    lv, why = cmp.pair_level(built["items"][WA], built["items"][WB])
    assert lv == 1 and any("non sono confrontabili direttamente" in w for w in why)


def test_06_hedged_and_unhedged(built):
    assert cat.val(built["items"][WA]["fund"]["hedged"]) is False                      # "Currency unhedged" is NOT hedged
    c = built["items"][WC]
    assert cat.val(c["fund"]["hedged"]) is True and cat.val(c["exposure"]["currencyExposure"])[0]["currency"].startswith("EUR")
    lv, why = cmp.pair_level(built["items"][WA], c)
    assert lv == 2 and any("copertura del cambio" in w for w in why)
    assert cat.index_id("S&P 500 (EUR Hedged)") == ("s&p 500", True) and cat.index_id("MSCI World Currency unhedged")[1] is False


# 7-8: missing data and dates
def test_07_missing_data_stays_missing(built):
    t = built["items"][TA]
    assert t["costs"]["trackingDifference"]["v"] is None and "non verificabile" in t["costs"]["trackingDifference"]["note"]
    assert t["costs"]["brokerAvailability"] == "non verificata"
    assert cat.val(t["fund"]["distributionFrequency"]) is None
    assert not t["listings"][0]["quoteAvailable"] and t["listings"][0]["avgVolume3m"]["v"] is None   # never 0


def test_08_update_dates_and_staleness(built):
    a = built["items"][WA]
    assert a["costs"]["ter"]["asOf"] == "2026-11-03" and a["exposure"]["countries"]["asOf"] == "2026-08-31"
    assert a["fund"]["kidDate"]["v"] == "2026-09-14"
    old = {"v": 1, "asOf": "2020-01-01"}
    assert cat.fresh(old, "ter") == "datato" and cat.fresh({"v": None}, "ter") == "mancante" and cat.fresh({"v": 1}, "ter") == "senza data"
    b = built["items"][WB]
    assert b["exposure"]["top10"]["dateKind"] == "download" and "download" in b["exposure"]["top10"]["note"]


# 9-11: costs, tracking, liquidity
def test_09_ter_sources_and_disagreement(built):
    a, bb = built["items"][WA], built["items"][BB]
    assert a["costs"]["ter"]["v"] == 0.2 and a["costs"]["terState"] == "verificato"     # issuer = exchange = justETF
    assert bb["costs"]["terState"] == "discordante" and {c["v"] for c in bb["costs"]["terChecks"]} == {0.15, 0.1}
    probs = json.load(open(os.path.join(cat.DIR, "controlli.json")))["problems"]
    assert any(p.get("isin") == BB and "TER" in p["problema"] for p in probs)


def test_10_tracking_difference_and_error_are_separate(built):
    c = built["items"][WA]["costs"]
    assert set(c) >= {"trackingDifference", "trackingError"} and c["trackingDifference"]["note"] != c["trackingError"]["note"]
    d = cmp.compare(built, [WA, WB])
    keys = [r["key"] for dm in d["dimensions"] for r in dm["rows"]]
    assert "td" in keys and "te" in keys


def test_11_liquidity_and_spread(built):
    a, b = built["items"][WA], built["items"][WB]
    assert a["listings"][0]["spread"]["representative"] is False and "mercato chiuso" in a["listings"][0]["spread"]["note"]
    sp = b["listings"][0]["spread"]
    assert sp["representative"] and sp["v"] == pytest.approx(0.1 / 100.05 * 100, abs=1e-3)
    assert "non rappresentativo" in cmp.spread_text(a) and "%" not in cmp.spread_text(a).split(":")[0]
    assert cat.val(b["listings"][0]["avgTurnover3m"]) == 20000 and b["listings"][0]["zeroVolumeDays"] == 20
    assert not any("volume" in r or "scambi" in r for r in cmp.risks(b))                # no automatic penalty for low volume


# 12-14: equity vs bonds, comparability
def test_12_equity_and_bond_models(built):
    ba = built["items"][BA]
    assert ba["bond"]["duration"]["v"] == 1.9 and ba["bond"]["yield"]["v"] == 2.1 and "non è una previsione" in ba["bond"]["yield"]["note"]
    assert built["items"][BB]["completeness"]["state"] == "parziale" and "duration" in built["items"][BB]["completeness"]["missing"]
    assert "top10" in cat.REQUIRED["azionario"] and "duration" in cat.REQUIRED["obbligazionario"]
    d = cmp.compare(built, [BA, BB])
    assert any(r["key"] == "duration" for r in d["dimensions"][1]["rows"]) and d["overlap"]["available"] is False
    assert cmp.compare(built, [WA, BA])["level"] == 4


def test_13_index_comparability_levels(built):
    I = built["items"]
    assert cmp.pair_level(I[WA], I[WB])[0] == 1
    assert cmp.pair_level(I[BA], I[BB])[0] == 2
    assert cmp.pair_level(I[WA], I[TA])[0] == 4
    assert set(cmp.LEVELS) == {1, 2, 3, 4}


def test_14_similar_products_and_no_winner(built, monkeypatch):
    d = cmp.compare(built, [WA, WB])
    assert d["level"] == 1 and d["differences"] and "TER" in d["differences"][0]
    text = json.dumps(d, ensure_ascii=False).lower()
    for word in ("migliore scelta", "vincitore", "entra ora", "da comprare", "da vendere", "evita", "punteggio", "score", "consigliato"):
        assert word not in text
    assert "non rende un etf automaticamente migliore" in d["disclaimer"].lower()


# 15-16: holdings
def test_15_common_holdings_only_partial(built):
    o = cmp.compare(built, [WA, WB])["overlap"]
    assert o["available"] and o["partial"] and o["count"] == 2 and {r["name"] for r in o["common"]} == {"Nvidia", "Apple"}
    assert "percent" not in json.dumps(o) and "non si può calcolare" in o["note"]
    assert any("download" in w for w in o["warnings"])


def test_16_partial_data(built):
    c = built["items"][WC]
    assert c["completeness"]["state"] in ("completa", "parziale")
    assert "dalla classe" in (c["identity"]["index"].get("note") or "") and c["identity"]["twin"] == WA
    assert cmp.compare(built, [WC, WA])["overlap"]["sameFund"] is True


# 17-18: duplicates and excluded products
def test_17_duplicates_are_refused(built):
    assert "stesso ETF" in cmp.compare(built, [WA, "AWLX"])["error"]
    assert "almeno 2" in cmp.compare(built, [WA, WA.lower()])["error"]
    assert "Al massimo" in cmp.compare(built, [WA, WB, BA, BB, TA])["error"]
    assert len({e["isin"] for e in built["items"].values()}) == len(built["items"])


def test_18_non_ucits_and_excluded_products(built):
    ex = built["excluded"]
    assert ex[GE]["exclusion"] == "etc" and ex[LV]["exclusion"] == "leva" and GE not in built["items"]
    assert cat.exclusion("Foo S&P 500 Short UCITS ETF") == "inverso" and cat.exclusion("Bar ETN") == "etn"
    assert cat.exclusion("Fondo Qualsiasi", ucits=False) == "non_ucits" and cat.exclusion("iShares Core MSCI World UCITS ETF") is None
    assert cmp.compare(built, [WA, LV])["level"] == 4


# 19-20: API and the existing ETF tab
def test_19_api(built, monkeypatch):
    import server
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download"))
    c = server.app.test_client()
    d = json.loads(c.get("/api/etf/catalog").data)
    assert d["status"] == "ok" and d["summary"]["etfs"] == 6 and len(d["excluded"]) == 2 and "families" in d
    assert [r["isin"] for r in json.loads(c.get("/api/etf/catalog?q=awlx").data)["rows"]] == [WA]
    assert {r["isin"] for r in json.loads(c.get("/api/etf/catalog?assetClass=obbligazionario").data)["rows"]} == {BA, BB}
    one = json.loads(c.get("/api/etf/catalog/AWLD").data)
    assert one["isin"] == WA and one["risks"] and one["sources"] and any(s["isin"] == WB and s["level"] == 1 for s in one["similar"])
    assert c.get("/api/etf/catalog/NONE").status_code == 404
    cm = c.get(f"/api/etf/compare?isins={WA},{WB}")
    assert cm.status_code == 200 and json.loads(cm.data)["level"] == 1
    assert c.get(f"/api/etf/compare?isins={WA}").status_code == 400


def test_20_existing_etf_tab_untouched():
    root = cat.ROOT
    u = json.load(open(os.path.join(root, "etf_universe.json")))
    assert len(u["etfs"]) == 63 and u["approved"] == "2026-10-08"                         # the phase-24 universe is unchanged
    import server
    rules = [r.rule for r in server.app.url_map.iter_rules()]
    assert {"/api/etf", "/api/etf/why/<isin>", "/api/etf/diary"} <= set(rules)
    js = open(os.path.join(root, "static", "app.js")).read()
    assert "function renderEtf()" in js and "BUY_INFO" in js and "data-etfmode" in js and 'etf: "ETF · esposizioni e prodotti"' in js  # label renamed in phase 6B


# 21-23: no regressions, performance, no network
def test_21_no_personal_data_and_versions_aligned():
    import re
    src = "".join(open(os.path.join(cat.ROOT, f)).read() for f in ("etf_catalog.py", "etf_comparison.py", "etf_catalog_build.py"))
    assert "portafoglio/" not in src.replace("Nothing here reads portafoglio/", "") and "fineco" not in src.lower().replace("(fineco)", "").replace("(es. fineco)", "")
    sv = re.search(r'DASHBOARD_VERSION = "([^"]+)"', open(os.path.join(cat.ROOT, "server.py")).read()).group(1)
    pv = re.search(r'PAGE_VERSION = "([^"]+)"', open(os.path.join(cat.ROOT, "static", "app.js")).read()).group(1)
    assert sv == pv


def test_22_performance_and_cache(built, tmp_path):
    t0 = time.perf_counter()
    for _ in range(50):
        assert cat.load(cat.DIR) is built                                                 # same object: read once, kept in memory
    assert time.perf_counter() - t0 < 0.5
    big = {"instruments": {"items": {}}, "listings": {"items": {}}, "exposure": {"items": {}}, "sources": {"items": {}}}
    base = built["items"][WA]
    for n in range(600):
        e = json.loads(json.dumps({k: v for k, v in base.items() if k not in ("listings", "exposure", "completeness", "freshness")}))
        e["isin"] = make_isin(f"ZY{n:09d}")
        big["instruments"]["items"][e["isin"]] = e
    t0 = time.perf_counter()
    data = cat.assemble(big)
    rows = cat.search(data, "alfa world")
    assert len(rows) == 600 and time.perf_counter() - t0 < 2.0


def test_23_no_external_calls(built, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network"))
    cat._cache.update(key=None, data=None)
    data = cat.load(cat.DIR)
    cmp.compare(data, [WA, WB, BA])
    cat.summary(data)
    assert build.parse_scheda(build.page_text(bi_html(WA, "AWLD", "0,20%", "USD", "CAPITALIZED")))["ter"] == 0.2
