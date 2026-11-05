"""ETF model E2 (5 Nov 2026, decision of the user): the bond condition O1 "yield ÷ duration ≥ 1" is no longer used.

What is checked, with made-up data only (catalog and prices of test_etf_opportunity, temporary diaries):
- O1 is out of every E2 decision; the ratio stays as a plain figure without threshold;
- yield, duration, credit, hedging and the ±1 point rate scenarios are shown apart, never added together;
- missing duration or yield;
- no automatic promotion: in E2 no bond exposure reaches "Esposizione da approfondire";
- E1 is reproduced unchanged; E2 is identified in scans, API and diary;
- a session recorded with E1 is never recorded again with E2 and the E1 rows never change;
- nothing is written to the real diary while these tests run."""
import hashlib
import json
import os
import sqlite3

import pytest

import app_env
import etf_catalog as cat
import etf_opportunity as eo
import etf_opportunity_diary as ed
import etf_prices
import opportunity_diary as od
import test_etf_opportunity as t6

F, G1, GL, IL, NOW = t6.F, t6.G1, t6.GL, t6.IL, t6.NOW
REAL_DB = os.path.join(app_env.ROOT, "data", "opportunita.sqlite3")
BONDS = ("gov_euro_1_3", "gov_euro_lunghi", "inflazione_euro")


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest() if os.path.exists(path) else None


@pytest.fixture
def data():
    return t6.catalog(), t6.prices()


def bond_row(c, p, key, version=eo.VERSION, mode="lungo"):
    return eo.detail(eo.scan(c, p, mode, now=NOW, version=version), key)


# ------------------------------------------------------------------ 1. O1 out of the decisions

def test_e2_has_no_o1_condition_and_no_o1_threshold(data):
    c, p = data
    for key in BONDS:
        o = bond_row(c, p, key)
        ids = {x["id"] for x in o["conditions"]["fav"] + o["conditions"]["con"]}
        assert ids == {"O2", "O3", "P1", "P2"}, key
        assert not any("O1" in w for w in o["why"])
    r = eo.scan(c, p, "lungo", now=NOW)
    assert "bond_cushion" not in r["params"] and r["version"] == "E2"
    assert eo.scan(c, p, "lungo", now=NOW, version="E1")["params"]["bond_cushion"] == 1.0   # E1 keeps it


def test_e2_state_does_not_depend_on_the_yield_duration_ratio(data):
    c, p = data
    states = set()
    for ytm in (0.8, 1.9, 3.3, 9.0):                    # ratio from 0.42 to 4.7: the old O1 would flip
        c["items"][G1]["bond"]["yield"] = F(ytm)
        o = bond_row(c, p, "gov_euro_1_3")
        assert o["conditions"]["fav"][1]["ok"] is True   # O3 (costs) still satisfied for every yield used
        states.add(o["state"])
    assert states == {eo.INSUFFICIENT}


# ------------------------------------------------------------------ 2. descriptive ratio kept

def test_ratio_is_kept_as_a_plain_figure(data):
    c, p = data
    b = bond_row(c, p, "gov_euro_1_3")["bond"]
    assert b["ratio"] == pytest.approx(3.3 / 1.9) and b["cushion"] == b["ratio"]
    assert "nessuna soglia" in b["ratioNote"] and "E1" in b["ratioNote"]
    il = bond_row(c, p, "inflazione_euro")["bond"]
    assert il["ratio"] == pytest.approx(1.9 / 7.0) and "reale" in il["ratioNote"]   # real yield, said so


# ------------------------------------------------------------------ 3. rate sensitivity

def test_rate_scenarios_use_duration_and_are_not_added_to_the_yield(data):
    c, p = data
    b = bond_row(c, p, "gov_euro_lunghi")["bond"]
    assert b["durationKind"] == "effettiva" and b["durationUsed"] == 15.0
    assert b["rateScenarios"] == [{"shift": 1.0, "priceChange": -15.0}, {"shift": -1.0, "priceChange": 15.0}]
    notes = " ".join(b["scenarioNotes"])
    assert "non è una previsione" in notes and "convessità" in notes and "non si somma" in notes
    assert "duration modificata non pubblicata" in notes
    assert b["yield"] == 4.4                              # yield shown apart, untouched by the scenarios
    flat = json.dumps(b)
    assert "total" not in flat.lower() and "expected" not in flat.lower()   # no "certain" return built from the two


def test_modified_duration_is_preferred_when_published(data):
    c, p = data
    c["items"][G1]["bond"]["modifiedDuration"] = F(1.8)
    b = bond_row(c, p, "gov_euro_1_3")["bond"]
    assert b["durationKind"] == "modificata" and b["durationUsed"] == 1.8 and b["duration"] == 1.9
    assert b["rateScenarios"][0]["priceChange"] == pytest.approx(-1.8)
    assert not any("non pubblicata" in n for n in b["scenarioNotes"])


def test_credit_hedging_and_currency_shown_apart(data):
    c, p = data
    c["items"][G1]["fund"]["hedged"] = F(True)
    b = bond_row(c, p, "gov_euro_1_3")["bond"]
    assert b["aOrBetter"] == 70.0 and b["credit"] == "investment grade" and b["currency"] == "EUR"
    assert b["hedged"] is True and "coperta" in b["hedgedText"]
    c["items"][G1]["fund"]["hedged"] = F(None)
    assert bond_row(c, p, "gov_euro_1_3")["bond"]["hedgedText"] == "n.d."           # missing stays missing


# ------------------------------------------------------------------ 4. missing duration or yield

def test_missing_duration(data):
    c, p = data
    c["items"][G1]["bond"]["duration"] = F(None)
    o = bond_row(c, p, "gov_euro_1_3")
    b = o["bond"]
    assert o["state"] == "Dati insufficienti" and b["rateScenarios"] is None and b["ratio"] is None
    assert b["durationKind"] is None and any("non calcolabile" in n for n in b["scenarioNotes"])


def test_missing_yield(data):
    c, p = data
    c["items"][G1]["bond"]["yield"] = F(None)
    o = bond_row(c, p, "gov_euro_1_3")
    b = o["bond"]
    assert o["state"] == "Dati insufficienti" and b["ratio"] is None and b["ratioNote"] is None
    assert b["rateScenarios"][0]["priceChange"] == pytest.approx(-1.9)               # duration alone still gives the sensitivity
    assert any(x["id"] == "O3" and x["ok"] is None for x in o["missing"])             # cost share not evaluable, never "ok"


# ------------------------------------------------------------------ 5. no unjustified promotion

def test_no_bond_is_promoted_in_e2(data):
    c, p = data
    for mode in eo.MODES:
        e1 = {o["key"]: o for o in eo.scan(c, p, mode, now=NOW, version="E1")["rows"]}
        r = eo.scan(c, p, mode, now=NOW)
        for o in r["rows"]:
            if o["kind"] != "bond":
                continue
            assert o["state"] != "Esposizione da approfondire" and o["key"] not in r["selected"]
            if e1[o["key"]]["state"] == "Condizioni contrastanti":                     # penalised by O1 in E1
                assert o["state"] in (eo.INSUFFICIENT, "Condizioni contrastanti")
    g = bond_row(c, p, "gov_euro_1_3")
    assert bond_row(c, p, "gov_euro_1_3", "E1")["state"] == "Esposizione da approfondire"
    assert g["state"] == eo.INSUFFICIENT and any("non un'opportunità" in w for w in g["why"])
    il = bond_row(c, p, "inflazione_euro")
    assert bond_row(c, p, "inflazione_euro", "E1")["state"] == "Condizioni contrastanti" and il["state"] == eo.INSUFFICIENT


def test_other_bond_rules_unchanged_in_e2(data):
    c, p = data
    assert bond_row(c, p, "gov_euro_lunghi")["state"] == "Rischio elevato"           # P1 duration ≥ 10
    c["items"][G1]["bond"]["ratings"] = F([{"name": "BBB", "weight": 100.0}])
    assert bond_row(c, p, "gov_euro_1_3")["state"] == "Condizioni contrastanti"      # O2 not met, O3 met
    c["items"][G1]["bond"]["bondKind"] = F("BTP (un solo emittente)")
    assert bond_row(c, p, "gov_euro_1_3")["state"] == "Rischio elevato"              # P2 single issuer


# ------------------------------------------------------------------ 6. E1 reproducible, E2 identified

def test_e1_reproducible_and_equities_identical(data):
    c, p = data
    for mode in eo.MODES:
        a, b = eo.scan(c, p, mode, now=NOW, version="E1"), eo.scan(c, p, mode, now=NOW, version="E1")
        assert json.dumps(a, default=str, sort_keys=True) == json.dumps(b, default=str, sort_keys=True)
        assert a["states"] == eo.STATES_E1 and eo.INSUFFICIENT not in a["overview"]["counts"]
        g = eo.detail(a, "gov_euro_1_3")
        assert "rateScenarios" not in g["bond"] and [x["id"] for x in g["conditions"]["fav"]] == ["O1", "O2", "O3"]
        e2 = {o["key"]: o for o in eo.scan(c, p, mode, now=NOW)["rows"]}
        for o in a["rows"]:
            if o["kind"] == "equity":                    # equity model untouched by E2
                x = dict(e2[o["key"]], version="E1")
                assert json.dumps(o, default=str, sort_keys=True) == json.dumps(x, default=str, sort_keys=True), o["key"]
        assert [k for k in a["selected"] if eo.detail(a, k)["kind"] == "equity"] == \
               [k for k in eo.scan(c, p, mode, now=NOW)["selected"]]


def test_e2_identified(data, monkeypatch):
    import server
    c, p = data
    assert eo.VERSION == "E2" and eo.VERSIONS == ("E1", "E2")
    r = eo.scan(c, p, "lungo", now=NOW)
    assert r["version"] == "E2" and r["states"] == eo.STATES and all(o["version"] == "E2" for o in r["rows"])
    with pytest.raises(ValueError):
        eo.scan(c, p, "lungo", now=NOW, version="E3")
    monkeypatch.setattr(etf_prices, "load", lambda path=None: p)
    monkeypatch.setattr(cat, "load", lambda *a, **k: c)
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download"))
    server._eopp.update(key=None, data={})
    cl = server.app.test_client()
    d = json.loads(cl.get("/api/etf/opportunities?mode=lungo").data)
    assert d["version"] == "E2" and eo.INSUFFICIENT in d["overview"]["counts"]
    g = json.loads(cl.get("/api/etf/opportunities/gov_euro_1_3?mode=lungo").data)
    assert g["version"] == "E2" and g["state"] == eo.INSUFFICIENT and g["bond"]["rateScenarios"]


# ------------------------------------------------------------------ 7. diary: version recorded, E1 never touched

def _scans(c, p, version, session="2026-11-03"):
    return {m: eo.scan(c, p, m, as_of=session, now=NOW, version=version) for m in eo.MODES}


def test_diary_records_e2_with_its_version(data, tmp_path):
    c, p = data
    t6._start_diary(tmp_path)
    ok, msg = ed.record(_scans(c, p, "E2"), "2026-11-03", "2026-11-03T23:00:00+01:00", "dashboard")
    assert ok, msg
    con = sqlite3.connect(od.DB)
    run = con.execute("SELECT model_version, params FROM etf_runs").fetchone()
    assert run[0] == "E2" and "bond_cushion" not in json.loads(run[1])
    st, bond = con.execute("SELECT state, bond FROM etf_observations WHERE exposure='gov_euro_1_3' AND mode='lungo'").fetchone()
    assert st == eo.INSUFFICIENT and json.loads(bond)["rateScenarios"][0]["shift"] == 1.0
    assert set(con.execute("SELECT DISTINCT model_version FROM etf_observations").fetchall()) == {("E2",)}


def test_session_recorded_with_e1_is_not_recorded_again_with_e2(data, tmp_path, monkeypatch):
    import server
    c, p = data
    t6._start_diary(tmp_path)
    assert ed.record(_scans(c, p, "E1"), "2026-11-03", "2026-11-03T23:00:00+01:00", "dashboard")[0]
    before = sha(od.DB)
    rows_before = sqlite3.connect(od.DB).execute("SELECT * FROM etf_observations ORDER BY mode, exposure").fetchall()
    ok, why = ed.record(_scans(c, p, "E2"), "2026-11-03", "2026-11-04T09:00:00+01:00", "dashboard")
    assert not ok and "modello E1" in why and "seduta successiva" in why          # directly on the diary
    monkeypatch.setattr(etf_prices, "load", lambda path=None: p)
    monkeypatch.setattr(cat, "load", lambda *a, **k: c)
    msg = server.save_etf_scan_diary()                                            # and through the server
    assert "modello E1" in msg and "E2 si registra dalla seduta successiva" in msg
    assert ed.runs_of_session("2026-11-03") == [{"version": "E1", "source": "dashboard", "class": "produzione"}]
    con = sqlite3.connect(od.DB)
    assert con.execute("SELECT * FROM etf_observations ORDER BY mode, exposure").fetchall() == rows_before
    assert sha(od.DB) == before
    assert con.execute("SELECT state FROM etf_observations WHERE exposure='gov_euro_1_3' AND mode='lungo'").fetchone()[0] == \
        "Esposizione da approfondire"                                             # the E1 row keeps its E1 state
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE etf_observations SET state=?, model_version='E2'", (eo.INSUFFICIENT,))
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM etf_runs WHERE model_version='E1'")


def test_test_record_of_e1_also_blocks_e2_for_that_session(data, tmp_path):
    c, p = data
    t6._start_diary(tmp_path)
    assert ed.record(_scans(c, p, "E1"), "2026-11-03", "2026-11-03T23:00:00+01:00", "prova")[0]   # like 4 Nov 2026
    ok, why = ed.record(_scans(c, p, "E2"), "2026-11-03", "2026-11-04T09:00:00+01:00", "dashboard")
    assert not ok and "«prova»" in why
    assert ed.stats()["started"] is False and ed.stats()["excluded"]["runs"] == 1     # still excluded, not replaced


# ------------------------------------------------------------------ 8. no real writes

def test_no_real_write_during_e2_work(data, tmp_path, monkeypatch):
    import server
    c, p = data
    real_before = sha(REAL_DB)
    assert od.DB != REAL_DB and str(tmp_path) in od.DB                            # conftest isolation
    t6._start_diary(tmp_path)
    monkeypatch.setattr(etf_prices, "load", lambda path=None: p)
    monkeypatch.setattr(cat, "load", lambda *a, **k: c)
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download"))
    server._eopp.update(key=None, data={})
    with app_env.record_writes() as seen:
        for v in eo.VERSIONS:
            eo.scan(c, p, "lungo", now=NOW, version=v)
        server.app.test_client().get("/api/etf/opportunities/gov_euro_1_3?mode=lungo")
        server.save_etf_scan_diary()
    assert [w for w in seen if os.path.realpath(REAL_DB) in os.path.realpath(w[1])] == []
    assert [w for w in seen if w[1].startswith(app_env.ROOT) and "__pycache__" not in w[1]] == []   # nothing in the project
    assert sha(REAL_DB) == real_before
    assert ed.runs_of_session("2026-11-03")[0]["version"] == "E2"                  # it went to the temporary diary
