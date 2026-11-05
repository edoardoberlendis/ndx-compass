"""Decision Desk D2: an ETF never reaches "Da approfondire" only because the (not validated) E2 trend conditions are met.

Only made-up data (the builders of test_decision_engine and the made-up ETF catalogue and prices of
test_etf_opportunity); diaries are temporary files, the real database is never opened (conftest guard)."""
import copy
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import app_env
import decision_diary as dd
import diaries_status as ds
import etf_opportunity as eo
import investment_decision_engine as de
import opportunity_diary as od
import test_decision_engine as t7
import test_etf_opportunity as t6

ET = ZoneInfo("America/New_York")
SESSION, NEXT = t7.SESSION, "2026-11-04"
DEEP_E2 = "Esposizione da approfondire"


@pytest.fixture(scope="module")
def etf_scans():
    c, p = t6.catalog(), t6.prices()
    return c, p, {m: eo.scan(c, p, m, now=t6.NOW) for m in eo.MODES}


def both(o, catalog, mode="lungo"):
    return t7.etf_decide(copy.deepcopy(o), catalog, mode, "D1"), t7.etf_decide(copy.deepcopy(o), catalog, mode, "D2")


def trend_only(s):
    """An equity exposure whose only favourable case is the E2 trend (all L conditions met, products documented)."""
    return t7.e2_row(s, "sanita_usa", state=DEEP_E2)


SAME = ("favourable", "contrary", "risks", "dates", "missing", "dataQuality", "validation", "context", "product", "e2State",
        "main", "mainRisk", "blocking")


# ------------------------------------------------------------------ 1. D1 stays reproducible

def test_d1_is_reproducible(etf_scans):
    c, _, s = etf_scans
    snap = t7.full_snapshot(etf_scans)
    snap["etf"] = dict(snap["etf"])                     # never change the shared fixture
    snap["etf"]["lungo"] = dict(snap["etf"]["lungo"], rows=[trend_only(s)] + [r for r in s["lungo"]["rows"] if r["key"] != "sanita_usa"])
    a, b = de.decide(copy.deepcopy(snap), "D1"), de.decide(copy.deepcopy(snap), "D1")
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)   # same input, same output
    assert a["version"] == "D1" and a["states"] == de.STATES_D1 and "E-A1" in a["rules"] and "E-M3" not in a["rules"]
    assert t7.row(a, "etf", "sanita_usa", "lungo")["state"] == "Da approfondire"
    assert de.S_MON_X not in a["counts"]["lungo"]["etf"]
    with pytest.raises(ValueError):
        de.decide(snap, "D9")


# ------------------------------------------------------------------ 2. the D2 change

def test_d2_trend_only_etf_is_monitored_with_everything_kept(etf_scans):
    c, _, s = etf_scans
    r1, r2 = both(trend_only(s), c)
    assert (r1["state"], r1["rule"]) == ("Da approfondire", "E-A1")
    assert (r2["state"], r2["rule"]) == ("Monitora — trend esplorativo", "E-M3")
    assert {k: r1[k] for k in SAME} == {k: r2[k] for k in SAME}        # evidence, risks, dates, explanation unchanged
    assert r2["favourable"] and r2["main"] == r2["favourable"][0]["text"]
    assert any("non sono validate come criterio predittivo" in n for n in r2["notes"])
    assert any("non basta soddisfare più condizioni di trend" in x["text"] for x in r2["change"] if x["dir"] == "migliora")
    txt = (r2["ruleText"] + " ".join(r2["notes"])).lower()
    assert "non è un giudizio negativo" in txt and "inutil" not in txt     # not useless: only not validated
    assert set(r1["notes"]) <= set(r2["notes"])


def test_d2_blocking_risk_contrast_and_missing_data_unchanged(etf_scans):
    c, _, s = etf_scans
    cases = {"Rischio elevato": ("Rischio elevato", "E-R1"), "Condizioni contrastanti": ("Condizioni contrastanti", "E-C1"),
             "Dati insufficienti": ("Dati insufficienti", "E-D1"), "Trend favorevole da monitorare": ("Monitora", "E-M1"),
             "Nessuna opportunità convincente": ("Nessuna opportunità convincente", "E-N1")}
    for e2, want in cases.items():
        r1, r2 = both(t7.e2_row(s, "sanita_usa", state=e2), c)
        assert (r1["state"], r1["rule"]) == (r2["state"], r2["rule"]) == want, e2
    o = trend_only(s)                                   # undocumented products: still contradictory (E-C2) in both
    for p in o["products"]["products"]:
        p["ter"], p["terResolution"] = None, "non risolto"
    r1, r2 = both(o, c)
    assert r1["rule"] == r2["rule"] == "E-C2" and r1["contrary"] == r2["contrary"]
    o = trend_only(s)                                   # misaligned benchmark: "Monitora" E-M2 in both
    o["completeness"] = dict(o["completeness"], notes=["benchmark aggiornato al 2026-10-31, ETF al 2026-11-03"])
    assert [r["rule"] for r in both(o, c)] == ["E-M2", "E-M2"]
    o = trend_only(s)                                   # a date after the analysis: no judgement in both
    o["dates"] = dict(o["dates"], price="2026-11-09")
    assert [r["state"] for r in both(o, c)] == ["Dati insufficienti"] * 2


def test_d2_bonds_of_e2_unchanged(etf_scans):
    c, _, s = etf_scans
    a, b = de.decide(t7.snapshot(etf=s, catalog=c), "D1"), de.decide(t7.snapshot(etf=s, catalog=c), "D2")
    bonds = [r["id"] for r in a["rows"] if r.get("assetClass") == "obbligazionario"]
    assert bonds and all(t7.row(a, "etf", i.split(":")[1], "lungo")["rule"] == t7.row(b, "etf", i.split(":")[1], "lungo")["rule"]
                         for i in bonds)
    g = t7.row(b, "etf", "gov_euro_1_3", "lungo")
    assert g["rule"] == "E-N2" and g["state"] == "Nessuna opportunità convincente" and "evidenza insufficiente" in g["main"]
    assert t7.row(b, "etf", "gov_euro_lunghi", "lungo")["rule"] == "E-R1"
    assert a["notAnalysed"] == b["notAnalysed"]                        # still no short-term bond signal


def test_no_automatic_promotion_or_demotion(etf_scans):
    c, _, s = etf_scans
    snap = t7.full_snapshot(etf_scans)
    snap["etf"] = dict(snap["etf"])                     # never change the shared fixture
    variants = []
    for st in eo.STATES + [DEEP_E2]:                     # every E2 state on every exposure, both horizons
        for mode in eo.MODES:
            for o in s[mode]["rows"]:
                if o.get("state") != "Riferimento di mercato":
                    variants.append((mode, dict(copy.deepcopy(o), state=st)))
    for mode in eo.MODES:
        snap["etf"][mode] = dict(snap["etf"][mode], rows=[v for m, v in variants if m == mode][:400])
    # unique keys per row inside one scan are not required by decide: compare row by row
    a, b = de.decide(copy.deepcopy(snap), "D1"), de.decide(copy.deepcopy(snap), "D2")
    assert len(a["rows"]) == len(b["rows"])
    changed = 0
    for x, y in zip(sorted(a["rows"], key=lambda r: (r["id"], r.get("e2State") or "", r["rule"])),
                    sorted(b["rows"], key=lambda r: (r["id"], r.get("e2State") or "", r["rule"].replace("E-M3", "E-A1")))):
        assert x["id"] == y["id"]
        if x["rule"] == "E-A1":
            assert y["rule"] == "E-M3"
            changed += 1
        else:
            assert (x["state"], x["rule"]) == (y["state"], y["rule"])     # nothing else moves, up or down
    assert changed
    assert not [r for r in b["rows"] if r["kind"] == "etf" and r["state"] == "Da approfondire"]     # no ETF can reach it
    assert all(r["state"] != "Da approfondire" for r in b["rows"] if r["horizon"] == "breve")      # no new short-term state
    stocks = lambda res: {(r["id"], r["state"], r["rule"]) for r in res["rows"] if r["kind"] == "azione"}
    assert stocks(a) == stocks(b) and ("azione:AAA:lungo", "Da approfondire", "A-A1") in stocks(b)   # stocks untouched


# ------------------------------------------------------------------ 3. counts and coverage

def test_counts_and_coverage_are_coherent(etf_scans):
    c, _, s = etf_scans
    res = de.decide(t7.full_snapshot(etf_scans))
    cov = res["coverage"]
    for mode in eo.MODES:
        x = cov[mode]
        assert x["scanner"] == len(s[mode]["rows"]) and x["balanced"]
        assert x["classified"] == sum(res["counts"][mode]["etf"].values())
        assert x["classified"] + len(x["references"]) + len(x["notAnalysable"]) == x["scanner"]
        assert x["insufficient"] == res["counts"][mode]["etf"]["Dati insufficienti"]
        assert len([n for n in res["notAnalysed"] if n["horizon"] == mode]) == len(x["references"]) + len(x["notAnalysable"])
    assert not cov["lungo"]["notAnalysable"] and set(cov["breve"]["notAnalysable"]) == \
        {o["key"] for o in s["breve"]["rows"] if o.get("kind") == "bond" and o.get("state") != "Riferimento di mercato"}
    assert cov["catalog"]["products"] == len(c["items"])
    assert sum(sum(k.values()) for h in res["counts"].values() for k in h.values()) == len(res["rows"])


# ------------------------------------------------------------------ 4. diary: versions, immutability

def test_diary_keeps_versions_and_never_rewrites_a_session(etf_scans, tmp_path):
    t7.start_diaries(tmp_path)
    t7.start_diaries(tmp_path, NEXT)
    snap = t7.full_snapshot(etf_scans)
    d1, d2 = de.decide(copy.deepcopy(snap), "D1"), de.decide(copy.deepcopy(snap), "D2")
    assert dd.record(d1, SESSION, "2026-11-03T17:30:00-05:00", "dashboard", "O2.1")[0]
    ok, msg = dd.record(d2, SESSION, "2026-11-03T18:00:00-05:00", "dashboard", "O2.1")
    assert not ok and "Decision Desk D1" in msg and "seduta successiva" in msg          # D1 day preserved, never redone
    assert dd.runs_of_session(SESSION) == [("D1", "dashboard")]
    d2n = dict(copy.deepcopy(d2), session=NEXT)
    ok, msg = dd.record(d2n, NEXT, "2026-11-04T17:30:00-05:00", "dashboard", "O2.1")
    assert ok, msg
    con = sqlite3.connect(od.DB)
    v = dict(con.execute("SELECT session, model_version FROM dec_runs").fetchall())
    assert v == {SESSION: "D1", NEXT: "D2"}
    assert {r[0] for r in con.execute("SELECT DISTINCT model_version FROM dec_observations WHERE session=?", (NEXT,))} == {"D2"}
    old = con.execute("SELECT state, rule FROM dec_observations WHERE session=? AND instrument='AAA' AND horizon='lungo'",
                      (SESSION,)).fetchone()
    assert old == ("Da approfondire", "A-A1")
    for sql in ("UPDATE dec_observations SET state='Monitora' WHERE model_version='D1'", "DELETE FROM dec_observations WHERE model_version='D2'",
                "UPDATE dec_runs SET model_version='D2'", "DELETE FROM dec_runs WHERE model_version='D1'"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(sql)
    con.close()                                         # release the failed write transaction
    assert dd.stats()["versions"] == ["D1", "D2"]
    assert dd.record(d2n, NEXT, "2026-11-04T18:00:00-05:00", "dashboard", "O2.1") == \
        (False, "seduta già registrata con questa versione del Decision Desk")


def test_d2_record_in_production_folder_is_blocked_from_tests(etf_scans, tmp_path):
    t7.start_diaries(tmp_path)
    res = de.decide(t7.full_snapshot(etf_scans))
    assert app_env.env() == "test" and od.DB != t7.REAL_DB
    app_env.protect(os.path.dirname(od.DB))                                     # the temporary folder plays "production"
    try:
        before = open(od.DB, "rb").read()
        with pytest.raises(PermissionError):
            dd.record(res, SESSION, "2026-11-03T17:30:00-05:00", "dashboard", "O2.1")
        assert open(od.DB, "rb").read() == before
    finally:
        app_env.unprotect(os.path.dirname(od.DB))


# ------------------------------------------------------------------ 5. state of the five diaries

def test_state_of_the_five_diaries_is_read_only(etf_scans, tmp_path):
    t7.start_diaries(tmp_path)
    t7.start_diaries(tmp_path, NEXT)
    snap = t7.full_snapshot(etf_scans)
    assert dd.record(de.decide(copy.deepcopy(snap), "D1"), SESSION, "2026-11-03T17:30:00-05:00", "prova", "O2.1")[0]
    d2 = dict(de.decide(copy.deepcopy(snap), "D2"), session=NEXT)
    assert dd.record(d2, NEXT, "2026-11-04T17:30:00-05:00", "dashboard", "O2.1")[0]
    before = hashlib.sha256(open(od.DB, "rb").read()).hexdigest()
    with app_env.record_writes() as seen:
        st = ds.status(now=datetime(2026, 11, 5, 9, 0, tzinfo=ET))
        text = ds.text(st)
    assert [w for w in seen if "opportunita" in w[1]] == [] and hashlib.sha256(open(od.DB, "rb").read()).hexdigest() == before
    by = {d["key"]: d for d in st["diaries"]}
    assert list(by) == ["opportunity", "investment", "valuation", "etf", "decision"]
    dec = by["decision"]
    assert dec["version"] == de.VERSION and dec["versionsRecorded"] == ["D1", "D2"]
    stocks_only = sum(1 for r in d2["rows"] if r["kind"] == "azione")      # ETF rows of another session are not recorded
    assert dec["official"] == {"runs": 1, "observations": stocks_only}
    assert dec["excluded"]["runs"] == 1 and dec["excluded"]["items"][0]["version"] == "D1"
    assert dec["last"]["session"] == NEXT and dec["last"]["version"] == "D2" and dec["errors"] == []
    assert "Diario delle decisioni" in text and "versioni presenti: D1, D2" in text


# ------------------------------------------------------------------ 6. API and page: version visible, read only

@pytest.fixture
def api(monkeypatch, etf_scans):
    import server
    c, _, s = etf_scans
    snap = t7.full_snapshot(etf_scans)
    snap["etf"] = dict(snap["etf"])                     # never change the shared fixture
    snap["etf"]["lungo"] = dict(snap["etf"]["lungo"], rows=[trend_only(s)] + [r for r in s["lungo"]["rows"] if r["key"] != "sanita_usa"])
    monkeypatch.setattr(server.store, "snapshot", {"stocks": []})
    monkeypatch.setattr(server.store, "error", None)
    monkeypatch.setattr(server, "investment_analysis", lambda *a, **k: snap["investment"])
    monkeypatch.setattr(server, "valuation_analysis", lambda *a, **k: snap["valuation"])
    monkeypatch.setattr(server, "decision_snapshot", lambda *a, **k: snap)
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download"))
    server._dec.update(key=None, data=None)
    return server.app.test_client()


def test_api_shows_the_version_and_never_writes(api):
    with app_env.record_writes() as seen:
        d = json.loads(api.get("/api/decisions").data)
        one = json.loads(api.get("/api/decisions/etf:sanita_usa:lungo").data)
    assert [w for w in seen if w[1].startswith(app_env.ROOT) and "__pycache__" not in w[1]] == []
    assert not os.path.exists(od.DB)
    assert d["version"] == "D2" and "E-M3" in d["rules"] and "E-A1" not in d["rules"] and de.S_MON_X in d["states"]
    assert one["version"] == "D2" and one["state"] == de.S_MON_X and one["rule"] == "E-M3" and one["favourable"]
    assert d["coverage"]["lungo"]["balanced"] and d["counts"]["lungo"]["etf"]["Da approfondire"] == 0


def test_page_shows_the_new_state_and_the_version():
    js = open(os.path.join(app_env.ROOT, "static", "app.js")).read()
    desk = js[js.index("// ------------------------------------------------------------ Decision Desk"):js.index("function renderOpps")]
    assert '"Monitora — trend esplorativo": "mon"' in desk and 'by("Monitora — trend esplorativo")' in desk
    assert "versione ${esc(DK.data.version)}" in desk and "Decision Desk ${esc(o.version)}" in desk
    assert "Copertura ETF" in desk and "versioni ${esc((D.diary.versions" in desk
