"""Decision Desk (phase 7A): investment_decision_engine.py, decision_diary.py and the /api/decisions endpoints.

Only made-up data: stocks are built by hand in the shape of the existing engines' results (F1, V2, Trading/Pagella);
ETF rows come from the real E2 scanner run on the made-up catalog and prices of test_etf_opportunity. Diaries are
temporary files; the real database is never opened for writing (conftest guard + sentinel folders)."""
import copy
import json
import os
import sqlite3
import time

import pytest

import app_env
import decision_diary as dd
import etf_opportunity as eo
import investment_decision_engine as de
import opportunity_diary as od
import test_etf_opportunity as t6

SESSION = "2026-11-03"
AS_OF = "2026-11-03T17:30:00-05:00"
REAL_DB = os.path.join(app_env.ROOT, "data", "opportunita.sqlite3")


# ------------------------------------------------------------------ made-up results of the existing engines

def inv_item(tk, q="Elevata", g="Forte", s="Solida", v="Contenuta", e="Stabili", t="Favorevole", comp="Completa",
             lag=None, acc="USD", price=100.0, pdate=SESSION, analysts=SESSION):
    dims = {"quality": q, "growth": g, "solidity": s, "valuation": v, "expectations": e, "trend": t}
    return {"ticker": tk, "name": f"{tk} Inc.", "price": price, "priceDate": pdate,
            "dims": {k: {"state": x, "reasons": [f"motivo misurato di {k}"]} for k, x in dims.items()},
            "completeness": {"state": comp}, "lagging": lag, "currency": {"accounts": acc, "price": "USD"},
            "dataDates": {"statements": "2026-11-03T10:00:00-05:00", "analysts": analysts, "latestQuarter": "2026-09-30"},
            "profile": {"label": "profilo finto"}, "view": "vista finta", "missing": [], "weaknesses": [], "monitor": [],
            "dataIssues": []}


def val_item(tk, status="adeguata", pos="prudente_base", blockers=(), price=100.0, reasons=()):
    labels = {"sotto_prudente": "Prezzo sotto lo scenario prudente", "prudente_base": "Prezzo tra scenario prudente e base",
              "base_favorevole": "Prezzo tra scenario base e favorevole", "sopra_favorevole": "Prezzo sopra anche lo scenario favorevole"}
    return {"ticker": tk, "name": f"{tk} Inc.", "status": status, "statusLabel": f"stato {status}",
            "position": {"id": pos, "label": labels.get(pos)} if pos else None, "display": [80, 110, 140],
            "price": {"value": price}, "blockers": list(blockers), "reasons": list(reasons), "risks": ["rischio finto della valutazione"],
            "monitor": ["Prossima trimestrale: confrontare ricavi e margine con le ipotesi."],
            "levels": [{"text": "Sotto circa 80 USD il prezzo sarebbe inferiore al valore dello scenario prudente: un livello per "
                                "una nuova analisi, non un prezzo di acquisto."}],
            "dataDates": {"prices": SESSION, "latestYear": "2025-12-31"}, "currency": {"accounts": "USD", "price": "USD"}}


def trade(tk, ok=5, warnings=(), status="Da approfondire", atr=2.0, flag=None, close=SESSION):
    names = ["Più forte del Nasdaq-100 a 1 mese", "Più forte del Nasdaq-100 a 3 mesi", "Sopra le medie 20 e 50", "Media 20 in salita", "Volumi in aumento"]
    conds = [{"id": f"T{i + 1}", "name": n, "state": "ok" if i < ok else "ko", "detail": "valore misurato"} for i, n in enumerate(names)]
    W = {"ext": "Tirato: +9% dalla media 20", "earn": "Trimestrale tra 3 giorni", "vol": "Volatilità alta: ATR 5% del prezzo",
         "below200": "Sotto la media 200"}
    return {"ticker": tk, "name": f"{tk} Inc.", "closeDate": close, "status": status, "ok": ok, "n": 5, "conditions": conds,
            "warnings": [{"id": w, "short": w, "text": W[w]} for w in warnings], "diag": {"flag": flag}, "metrics": {"atrPct": atr},
            "trend": "Rialzista", "main": "+3 punti su QQQ"}


@pytest.fixture(scope="module")
def etf_scans():
    c, p = t6.catalog(), t6.prices()
    return c, p, {m: eo.scan(c, p, m, now=t6.NOW) for m in eo.MODES}


def snapshot(inv=(), val=(), trades=(), etf=None, catalog=None, as_of=AS_OF):
    return {"asOf": as_of, "session": SESSION,
            "opportunities": {"asOf": SESSION, "model": {"version": "O2.1"},
                              "market": {"qqq1m": -2.0, "qqqTrend": "Laterale", "above200": 55.0, "date": SESSION},
                              "trading": {"min": 4, "all": list(trades)},
                              "invest": {"all": [{"ticker": x["ticker"], "ok": 5, "n": 6, "status": "Da approfondire"} for x in inv]}},
            "investment": {"model": {"version": "F1"}, "items": list(inv), "dataDates": {}} if inv else None,
            "valuation": {"model": {"version": "V2"}, "items": list(val), "dataDates": {}} if val else None,
            "etf": etf or {}, "catalog": catalog}


def row(res, kind, key, horizon):
    return next(r for r in res["rows"] if r["kind"] == kind and r["key"] == key and r["horizon"] == horizon)


def one_stock(inv, val=None, **kw):
    res = de.decide(snapshot([inv], [val] if val else [], **kw))
    return row(res, "azione", inv["ticker"], "lungo")


# ------------------------------------------------------------------ 1. stocks, medium-long term

def test_stock_deep_only_with_everything_aligned():
    r = one_stock(inv_item("AAA"), val_item("AAA"))
    assert r["state"] == "Da approfondire" and r["rule"] == "A-A1" and r["contrary"] == []
    assert r["dataQuality"] == "completa" and r["dates"]["price"] == SESSION
    assert any(c["dir"] == "migliora" and "non un prezzo di acquisto" in c["text"] for c in r["change"])   # DCF level = reassessment
    assert r["validation"].startswith("Esplorativo")


def test_quality_with_price_above_the_dcf_scenarios_waits():
    r = one_stock(inv_item("BBB"), val_item("BBB", pos="sopra_favorevole", price=200))
    assert r["state"] == "Attendi condizioni migliori" and r["rule"] == "A-W1"
    assert "sopra anche lo scenario favorevole" in r["main"] and "ma" in r["main"]       # the contrary is in the main reason
    assert any("sopra anche lo scenario favorevole" in c["text"] for c in r["contrary"])


def test_cheap_valuation_does_not_cancel_financial_fragility():
    r = one_stock(inv_item("CCC", s="Fragile", v="Contenuta"), val_item("CCC", pos="sotto_prudente"))
    assert r["state"] == "Rischio elevato" and r["rule"] == "A-R1" and r["blocking"] == 1
    assert any("Contenuta" in f["text"] for f in r["favourable"])                         # shown, but it does not win
    assert "Fragile" in r["mainRisk"]


def test_positive_trend_with_worsening_fundamentals_is_contradictory():
    r = one_stock(inv_item("DDD", q="Buona", g="In calo", t="Favorevole"), val_item("DDD"))
    assert r["state"] == "Condizioni contrastanti" and r["rule"] == "A-C1"
    assert any("In calo" in c["text"] for c in r["contrary"]) and any("Favorevole" in f["text"] for f in r["favourable"])


def test_uncertain_dcf_never_deep():
    r = one_stock(inv_item("EEE"), val_item("EEE", status="sensibile", reasons=["±1 punto di tasso sposta il valore del 40%"]))
    assert r["state"] == "Condizioni contrastanti" and any("molto sensibile" in c["text"] for c in r["contrary"])
    r = one_stock(inv_item("EEF"), val_item("EEF", blockers=["dati in ritardo di 2 trimestri"]))
    assert r["state"] != "Da approfondire" and any("criticità della valutazione" in c["text"] for c in r["contrary"])
    r = one_stock(inv_item("EEG"), val_item("EEG", status="non_affidabile", pos=None))
    assert r["state"] == "Monitora" and any("DCF V2" in m for m in r["missing"])          # no DCF: never "Da approfondire"


def test_missing_data():
    r = one_stock(inv_item("FFF", comp="Insufficiente"), val_item("FFF"))
    assert r["state"] == "Dati insufficienti" and r["dataQuality"] == "insufficiente"
    r = one_stock(inv_item("FFG", q="Non valutabile", g="Non valutabile"), val_item("FFG"))
    assert r["state"] == "Dati insufficienti" and len([m for m in r["missing"] if "non valutabile" in m]) == 2
    res = de.decide(snapshot(trades=[trade("FFH")]))                                     # no F1 at all
    assert any(x["what"] == "Azioni, medio-lungo periodo" for x in res["notAnalysed"])


def test_stale_and_misaligned_data_reduce_the_judgement():
    r = one_stock(inv_item("GGG", lag="2026-10-30"), val_item("GGG"))
    assert r["state"] != "Da approfondire" and any("fermi al 2026-10-30" in c["text"] for c in r["contrary"])
    r = one_stock(inv_item("GGH", analysts="2026-10-20"), val_item("GGH"))
    assert r["state"] != "Da approfondire" and any("stime degli analisti del 2026-10-20" in c["text"] for c in r["contrary"])
    r = one_stock(inv_item("GGI", pdate="2026-11-02"), val_item("GGI"))
    assert r["state"] != "Da approfondire" and any("sedute diverse" in c["text"] for c in r["contrary"])


def test_information_after_the_snapshot_is_never_used():
    r = one_stock(inv_item("HHH", pdate="2026-11-04"), val_item("HHH"))
    assert r["state"] == "Dati insufficienti" and any("successivi al momento dell'analisi" in m for m in r["missing"])


def test_currency_and_country_risk_outside_the_model():
    r = one_stock(inv_item("III", acc="CNY"), val_item("III"))
    assert r["state"] != "Da approfondire"
    assert any("bilanci in CNY" in c["text"] and "rischio paese" in c["text"] for c in r["contrary"])


# ------------------------------------------------------------------ 2. stocks, short term

def test_short_term_stocks_never_above_monitor():
    res = de.decide(snapshot(trades=[trade("S1"), trade("S2", warnings=["ext"]), trade("S3", warnings=["vol"]), trade("S4", ok=2),
                                     trade("S5", ok=2, warnings=["vol"]), trade("S6", status="Dati insufficienti", ok=0)]))
    st = {r["key"]: (r["state"], r["rule"]) for r in res["rows"] if r["horizon"] == "breve"}
    assert st == {"S1": ("Monitora", "B-M1"), "S2": ("Condizioni contrastanti", "B-C1"), "S3": ("Rischio elevato", "B-R1"),
                  "S4": ("Nessuna opportunità convincente", "B-N1"), "S5": ("Nessuna opportunità convincente", "B-N1"),
                  "S6": ("Dati insufficienti", "B-D1")}
    s1 = row(res, "azione", "S1", "breve")
    assert "nessun vantaggio" in s1["validation"] and any("contesto: QQQ" in n for n in s1["notes"])
    assert not any(k in json.dumps(s1).lower() for k in ("ingresso a", "entry", "stop loss"))     # no entry levels


# ------------------------------------------------------------------ 3. ETF exposures

def e2_row(scans, key, mode="lungo", **over):
    o = copy.deepcopy(eo.detail(scans[mode], key))
    o.update(over)
    return o


def etf_decide(o, catalog, mode="lungo"):
    snap = snapshot(etf={mode: {"rows": [o], "version": "E2", "session": SESSION, "pricesFetched": "2026-11-03T22:40:00+01:00"}},
                    catalog=catalog)
    return row(de.decide(snap), "etf", o["key"], mode)


def test_equity_etf_deep_and_product_kept_apart(etf_scans):
    c, _, s = etf_scans
    r = etf_decide(e2_row(s, "sanita_usa", state="Esposizione da approfondire"), c)
    assert r["state"] == "Da approfondire" and r["rule"] == "E-A1" and r["product"]["documented"]
    assert r["validation"].startswith("Esplorativo") and "Fase 24" in r["validation"]


def test_equity_etf_with_undocumented_products_is_contradictory(etf_scans):
    c, _, s = etf_scans
    o = e2_row(s, "sanita_usa", state="Esposizione da approfondire")
    for p in o["products"]["products"]:
        p["ter"], p["terResolution"] = None, "non risolto"
    r = etf_decide(o, c)
    assert r["state"] == "Condizioni contrastanti" and r["rule"] == "E-C2"
    assert any("TER discordante" in x["text"] for x in r["contrary"])


def test_equity_etf_with_misaligned_benchmark_only_monitored(etf_scans):
    c, _, s = etf_scans
    o = e2_row(s, "sanita_usa", state="Esposizione da approfondire")
    o["completeness"] = dict(o["completeness"], notes=["benchmark aggiornato al 2026-10-31, ETF al 2026-11-03"])
    r = etf_decide(o, c)
    assert r["state"] == "Monitora" and r["rule"] == "E-M2" and r["dataQuality"] == "parziale"


def test_strong_trend_with_high_concentration_is_said(etf_scans):
    c, _, s = etf_scans
    o = e2_row(s, "intelligenza_artificiale", state="Trend favorevole da monitorare",
               favourable=[{"id": "L1", "text": "trend rialzista", "value": "Rialzista"}])
    r = etf_decide(o, c)
    assert any("concentrazione elevata" in x["text"] for x in r["contrary"])


def test_bond_with_insufficient_evidence_is_not_promoted(etf_scans):
    c, _, s = etf_scans
    for mode in eo.MODES:
        res = de.decide(snapshot(etf=s, catalog=c))
        for r in res["rows"]:
            if r.get("assetClass") == "obbligazionario":
                assert r["state"] != "Da approfondire" and r["horizon"] == "lungo"
    g = row(res, "etf", "gov_euro_1_3", "lungo")
    assert g["e2State"] == eo.INSUFFICIENT and g["state"] == "Nessuna opportunità convincente" and g["rule"] == "E-N2"
    assert "evidenza insufficiente" in g["main"] and "prodotto" in g["main"]
    assert all(f["text"].startswith("caratteristica del prodotto") for f in g["favourable"])     # O2/O3: product, not timing
    assert any("non sono, da soli, una ragione per investire oggi" in n for n in g["notes"])
    assert any("criterio nuovo" in x["text"] for x in g["change"] if x["dir"] == "migliora")
    assert g["context"]["ratio"] and "O1" not in g["ruleText"]
    assert any("obbligazioni: solo informazioni strutturali" in x["why"] for x in res["notAnalysed"])  # no short-term bond signal


def test_bond_with_high_duration_is_a_risk_with_its_contradiction(etf_scans):
    c, _, s = etf_scans
    r = row(de.decide(snapshot(etf=s, catalog=c)), "etf", "gov_euro_lunghi", "lungo")
    assert r["state"] == "Rischio elevato" and r["rule"] == "E-R1"
    assert any("ma duration 15,0 anni" in x["text"] for x in r["contrary"])


def test_short_term_etf_never_above_monitor(etf_scans):
    c, _, s = etf_scans
    o = e2_row(s, "sanita_usa", "breve", state="Esposizione da approfondire")
    r = etf_decide(o, c, "breve")
    assert r["state"] == "Monitora" and r["rule"] == "F-M1"


def test_e1_and_e2_versions_and_o1_never_decides(etf_scans):
    c, p, s = etf_scans
    e1 = {m: eo.scan(c, p, m, now=t6.NOW, version="E1") for m in eo.MODES}
    res1, res2 = de.decide(snapshot(etf=e1, catalog=c)), de.decide(snapshot(etf=s, catalog=c))
    g1, g2 = row(res1, "etf", "gov_euro_1_3", "lungo"), row(res2, "etf", "gov_euro_1_3", "lungo")
    assert g1["e2Version"] == "E1" and g2["e2Version"] == "E2"
    assert g1["e2State"] == "Esposizione da approfondire" and g1["state"] != "Da approfondire"   # O1 passed in E1: no effect here
    assert res2["sources"]["etf_lungo"]["model"] == "E2" and res1["sources"]["etf_lungo"]["model"] == "E1"
    assert eo.detail(eo.scan(c, p, "lungo", now=t6.NOW, version="E1"), "gov_euro_1_3")["state"] == "Esposizione da approfondire"


# ------------------------------------------------------------------ 4. no score, no probability, no buy/sell, order

def full_snapshot(etf_scans):
    c, _, s = etf_scans
    inv = [inv_item("AAA"), inv_item("BBB"), inv_item("CCC", s="Fragile"), inv_item("DDD", g="In calo"), inv_item("FFF", comp="Insufficiente")]
    val = [val_item("AAA"), val_item("BBB", pos="sopra_favorevole"), val_item("CCC"), val_item("DDD"), val_item("FFF")]
    return snapshot(inv, val, [trade("AAA"), trade("BBB", ok=2)], etf=s, catalog=c)


def test_no_probability_score_or_buy_sell(etf_scans):
    res = de.decide(full_snapshot(etf_scans))
    assert de.check_no_forbidden(res) is None
    keys = {k for r in res["rows"] for k in r}
    assert not keys & {"score", "probability", "expectedReturn", "target", "entry", "rank"}
    assert de.check_no_forbidden({"rows": [{"main": "Compra ora"}]}) is not None               # the check itself works


def test_declared_order_not_by_returns_or_dcf_discount(etf_scans):
    res = de.decide(full_snapshot(etf_scans))
    idx = [de.STATES.index(r["state"]) for r in res["rows"]]
    assert idx == sorted(idx)
    a = de.stock_long("ZZB", inv_item("ZZB"), val_item("ZZB", pos="sotto_prudente", price=10), None, None, SESSION, AS_OF)
    b = de.stock_long("ZZA", inv_item("ZZA"), val_item("ZZA", pos="prudente_base", price=99), None, None, SESSION, AS_OF)
    assert sorted([a, b], key=de.order_key)[0]["key"] == "ZZA"                   # deeper DCF discount does not go first
    assert "rendimenti recenti" in res["orderRule"] and "sconto teorico" in res["orderRule"]


def test_none_convincing_is_a_valid_answer():
    res = de.decide(snapshot([inv_item("NNN", q="Modesta", g="Modesta")], [val_item("NNN")], [trade("NNN", ok=1)]))
    assert not [r for r in res["rows"] if r["state"] == "Da approfondire"] and "nessuna opportunità" in res["noneText"]


def test_desk_does_not_change_the_engines_results(etf_scans):
    snap = full_snapshot(etf_scans)
    before = json.dumps(snap, default=str, sort_keys=True)
    de.decide(snap)
    assert json.dumps(snap, default=str, sort_keys=True) == before


def test_performance(etf_scans):
    c, _, s = etf_scans
    inv = [inv_item(f"T{i:03d}", q=("Elevata", "Buona", "Modesta")[i % 3]) for i in range(110)]
    val = [val_item(f"T{i:03d}", pos=("prudente_base", "sopra_favorevole")[i % 2]) for i in range(110)]
    snap = snapshot(inv, val, [trade(f"T{i:03d}", ok=i % 6) for i in range(110)], etf=s, catalog=c)
    t0 = time.perf_counter()
    res = de.decide(snap)
    assert time.perf_counter() - t0 < 1.0 and len(res["rows"]) >= 220
    page = de.page(res)
    assert len(json.dumps(page, default=str)) < len(json.dumps(res, default=str)) / 2     # the list is compact


# ------------------------------------------------------------------ 5. API: read only, no download

@pytest.fixture
def api(monkeypatch, etf_scans):
    import server
    snap = full_snapshot(etf_scans)
    monkeypatch.setattr(server.store, "snapshot", {"stocks": []})
    monkeypatch.setattr(server.store, "error", None)
    monkeypatch.setattr(server, "investment_analysis", lambda *a, **k: snap["investment"])
    monkeypatch.setattr(server, "valuation_analysis", lambda *a, **k: snap["valuation"])
    monkeypatch.setattr(server, "decision_snapshot", lambda *a, **k: snap)
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download"))
    monkeypatch.setattr(server, "refresh_fundamentals", lambda *a, **k: pytest.fail("no download"))
    server._dec.update(key=None, data=None)
    return server.app.test_client()


def test_api_is_read_only_and_never_downloads(api):
    with app_env.record_writes() as seen:
        d = json.loads(api.get("/api/decisions").data)
        one = json.loads(api.get("/api/decisions/" + d["rows"][0]["id"]).data)
        assert api.get("/api/decisions/azione:NOPE:lungo").status_code == 404
    assert [w for w in seen if w[1].startswith(app_env.ROOT) and "__pycache__" not in w[1]] == []
    assert not os.path.exists(od.DB)                                            # not even an empty diary created
    assert d["version"] == de.VERSION and d["rows"][0]["state"] == "Da approfondire" and "favourable" not in d["rows"][0]
    assert one["favourable"] and one["disclaimer"] and d["diary"]["started"] is False


# ------------------------------------------------------------------ 6. decision diary

def start_diaries(tmp_path, session=SESSION):
    os.makedirs(os.path.dirname(od.DB), exist_ok=True)
    con = od.connect(od.DB, "dashboard")
    with con:
        con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (session, "O2.1", session + "T16:30:00-05:00", "dashboard", "x", "[]", None, 1, 1, None, None))
    con.close()
    assert str(tmp_path) in od.DB


def test_diary_records_once_and_never_changes(etf_scans, tmp_path):
    start_diaries(tmp_path)
    res = de.decide(full_snapshot(etf_scans))
    ok, msg = dd.record(res, SESSION, "2026-11-03T17:30:00-05:00", "dashboard", "O2.1")
    assert ok, msg
    con = sqlite3.connect(od.DB)
    run = con.execute("SELECT model_version, source, etf_note, rows FROM dec_runs").fetchone()
    assert run[0] == "D1" and run[1] == "dashboard" and run[2] is None and run[3] == len(res["rows"])
    obs = con.execute("SELECT state, rule, favourable, dates, validation FROM dec_observations WHERE instrument='AAA' AND horizon='lungo'").fetchone()
    assert obs[0] == "Da approfondire" and obs[1] == "A-A1" and json.loads(obs[2]) and json.loads(obs[3])["price"] == SESSION
    sources = json.loads(con.execute("SELECT sources FROM dec_runs").fetchone()[0])
    assert {sources[k]["model"] for k in ("trading", "fundamentals", "valuation", "etf_lungo")} == {"O2.1", "F1", "V2", "E2"}
    assert dd.record(res, SESSION, "2026-11-03T18:00:00-05:00", "dashboard", "O2.1") == \
        (False, "seduta già registrata con questa versione del Decision Desk")
    for sql in ("UPDATE dec_observations SET state='Da approfondire'", "DELETE FROM dec_observations", "DELETE FROM dec_runs",
                "UPDATE dec_runs SET source='x'"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(sql)
    st = dd.stats()
    assert st["started"] and st["observations"] == len(res["rows"]) and st["versions"] == ["D1"]


def test_diary_refuses_what_would_not_be_prospective(etf_scans, tmp_path):
    res = de.decide(full_snapshot(etf_scans))
    assert dd.record(res, SESSION, "2026-11-03T17:30:00-05:00", "dashboard", "O2.1")[0] is False   # no diary file
    os.makedirs(os.path.dirname(od.DB), exist_ok=True)
    od.connect(od.DB, "dashboard").close()
    ok, why = dd.record(res, SESSION, "2026-11-03T17:30:00-05:00", "dashboard", "O2.1")
    assert not ok and "non ha registrato la seduta" in why                       # opportunity diary first
    start_diaries(tmp_path)
    ok, why = dd.record(res, SESSION, "2026-11-03T14:00:00-05:00", "dashboard", "O2.1")
    assert not ok and "non era ancora chiusa" in why                             # never during the session
    ok, why = dd.record(dict(res, session="2026-11-02"), SESSION, "2026-11-03T17:30:00-05:00", "dashboard", "O2.1")
    assert not ok and "non " + SESSION in why
    assert not dd.exists(SESSION, de.VERSION)


def test_diary_skips_etf_rows_of_another_session(etf_scans, tmp_path):
    start_diaries(tmp_path)
    res = de.decide(full_snapshot(etf_scans))
    res["sources"]["etf_lungo"] = dict(res["sources"]["etf_lungo"], session="2026-10-31")
    ok, msg = dd.record(res, SESSION, "2026-11-03T17:30:00-05:00", "dashboard", "O2.1")
    assert ok and "righe ETF non registrate" in msg
    con = sqlite3.connect(od.DB)
    assert con.execute("SELECT COUNT(*) FROM dec_observations WHERE kind='etf'").fetchone()[0] == 0
    assert "2026-10-31" in con.execute("SELECT etf_note FROM dec_runs").fetchone()[0]


def test_diary_is_atomic(etf_scans, tmp_path):
    start_diaries(tmp_path)
    res = de.decide(full_snapshot(etf_scans))
    res["rows"].append(copy.deepcopy(res["rows"][0]))                            # same key twice: the insert fails half-way
    with pytest.raises(sqlite3.IntegrityError):
        dd.record(res, SESSION, "2026-11-03T17:30:00-05:00", "dashboard", "O2.1")
    con = sqlite3.connect(od.DB)
    assert con.execute("SELECT COUNT(*) FROM dec_runs").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM dec_observations").fetchone()[0] == 0


def test_diary_never_writes_production_from_tests(etf_scans, tmp_path):
    start_diaries(tmp_path)
    res = de.decide(full_snapshot(etf_scans))
    app_env.protect(os.path.dirname(od.DB))                                     # the temporary folder plays "production"
    try:
        before = open(od.DB, "rb").read()
        with pytest.raises(PermissionError):
            dd.record(res, SESSION, "2026-11-03T17:30:00-05:00", "dashboard", "O2.1")
        assert open(od.DB, "rb").read() == before
    finally:
        app_env.unprotect(os.path.dirname(od.DB))
    assert od.DB != REAL_DB and str(tmp_path) in od.DB


def test_test_records_are_excluded_from_the_diary_statistics(etf_scans, tmp_path):
    start_diaries(tmp_path)
    res = de.decide(full_snapshot(etf_scans))
    assert dd.record(res, SESSION, "2026-11-03T17:30:00-05:00", "prova", "O2.1")[0]
    st = dd.stats()
    assert st["started"] is False and st["excluded"]["runs"] == 1


def test_server_saves_the_diary_only_in_the_evening_chain():
    import server
    src = open(server.__file__).read()
    assert 'msg += "; " + save_decision_diary(day, now, source)' in src
    api = src[src.index('def api_decisions'):src.index('def save_decision_diary')]
    assert "record(" not in api and "connect(" not in api                      # the endpoints never write


# ------------------------------------------------------------------ 7. page

def test_page_has_the_desk_first_without_buy_sell_words():
    root = app_env.ROOT
    js = open(os.path.join(root, "static", "app.js")).read()
    assert 'const OPP_MODES = { desk: "Decision Desk' in js and 'LS.get("opp.view", "desk")' in js
    for mode in ("trading:", "invest:", "etf:"):
        assert mode in js[js.index("const OPP_MODES"):js.index("const OPP_LIMITS")]       # the old modes stay
    block = js[js.index("// ------------------------------------------------------------ Decision Desk"):js.index("function renderOpps()")]
    import re
    assert not re.search(r"\b(Compra|Vendi)\b", block) and "non consulenza finanziaria" in block
    assert "Nessuna opportunità convincente" in block and "data-dkopen" in block and "data-dketf" in block
