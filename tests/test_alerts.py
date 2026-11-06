"""Phase 8A: Alert e cambiamenti (alert_engine.py, /api/alerts, registro delle esclusioni).

Only SYNTHETIC diaries (tables built here with made-up tickers AAA, BBB and made-up ETF exposures), a made-up catalogue and
no network. The real diaries and the personal portfolio are never read: the conftest isolates every path."""
import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import alert_engine as ae
import app_env
import diary_exclusions as dx

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 10, 18, 0, tzinfo=ET)
TABLES = {
    "runs": "session, model_version, computed_at, source",
    "observations": "session, model_version, list, ticker",
    "inv_runs": "session, model_version, computed_at, source",
    "inv_observations": "session, model_version, ticker, name, completeness, dims, data_dates",
    "val_runs": "session, model_version, computed_at, source",
    "val_observations": "session, model_version, ticker, price, price_date, status, value_prudent, value_base, value_favourable, blockers, data_dates",
    "dec_runs": "session, model_version, computed_at, source",
    "dec_observations": "session, model_version, kind, instrument, horizon, name, state, rule, main, risks, data_quality, dates",
    "etf_runs": "session, model_version, computed_at, source",
    "etf_observations": "session, model_version, mode, exposure, state, risk, bond, indicators, data_status, reasons",
}


@pytest.fixture
def diary(tmp_path):
    p = str(tmp_path / "data_sintetici" / "diari.sqlite3")
    os.makedirs(os.path.dirname(p))
    con = sqlite3.connect(p)
    for t, cols in TABLES.items():
        con.execute(f"CREATE TABLE {t} ({cols})")
    con.commit()
    con.close()
    return p


def add(path, table, **row):
    con = sqlite3.connect(path)
    con.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()])
    con.commit()
    con.close()


def run_(path, table, session, version, at=None, source="dashboard"):
    add(path, table, session=session, model_version=version, computed_at=at or f"{session}T16:25:00-05:00", source=source)


def dec(path, session, ticker, state, version="D2", rule="A-W1", quality="completa", risks=(), kind="azione", horizon="lungo"):
    add(path, "dec_observations", session=session, model_version=version, kind=kind, instrument=ticker, horizon=horizon,
        name=f"{ticker} Inc. (finta)", state=state, rule=rule, main="motivo finto", risks=list(risks), data_quality=quality,
        dates={"prezzo": session})


def inv(path, session, ticker, quarter="2026-06-30", growth="Positiva", quality="Buona", statements=None, analysts=None,
        expectations="Stabili", completeness="Completa", version="F1"):
    add(path, "inv_observations", session=session, model_version=version, ticker=ticker, name=f"{ticker} Inc. (finta)",
        completeness={"state": completeness},
        dims={"growth": {"state": growth, "reasons": ["ricavi finti"]}, "quality": {"state": quality, "reasons": ["margine finto"]},
              "solidity": {"state": "Solida", "reasons": []}, "expectations": {"state": expectations, "reasons": ["stime finte"]}},
        data_dates={"statements": statements or f"{session}T12:00:00-05:00", "latestQuarter": quarter, "latestYear": "2025-12-31",
                    "analysts": analysts or session})


def val(path, session, ticker, price, base, status="adeguata", version="V2", statements=None):
    add(path, "val_observations", session=session, model_version=version, ticker=ticker, price=price, price_date=session,
        status=status, value_prudent=base * 0.7 if base else None, value_base=base, value_favourable=base * 1.3 if base else None,
        blockers=[], data_dates={"statements": statements or "2026-11-01T12:00:00-05:00", "latestQuarter": "2026-06-30"})


def etf(path, session, exposure, state, mode="lungo", level="medio", flags=(), bond=None, trend="Laterale", analysis="sufficiente", version="E2"):
    add(path, "etf_observations", session=session, model_version=version, mode=mode, exposure=exposure, state=state,
        risk={"level": level, "flags": [{"id": f, "text": f"segnale finto {f}", "high": f == "R2"} for f in flags]},
        bond=bond or {}, indicators={"trend": trend, "date": session}, data_status={"analysis": analysis, "conditions": "4 su 4"},
        reasons=["motivo finto"])


def chain(path, session, version_dec="D2", **kw):
    for t, v in (("runs", "O2.1"), ("inv_runs", "F1"), ("val_runs", "V2"), ("dec_runs", version_dec)):
        run_(path, t, session, v)


def gen(diary, reg, catalog=None, status=None, now=NOW, **kw):
    return ae.generate(now, "test", diary, catalog=catalog, status=status, path=reg, **kw)


@pytest.fixture
def reg(tmp_path):
    return str(tmp_path / "registro" / "alert.sqlite3")


def alerts(reg):
    return {a["rule"]: a for a in ae.read(reg)["alerts"]}


def by_rule(reg, rule):
    return [a for a in ae.read(reg)["alerts"] if a["rule"] == rule]


def two_sessions(diary, a="2026-11-04", b="2026-11-05"):
    chain(diary, a)
    chain(diary, b)


# ------------------------------------------------------------------ baseline, D2, fundamentals

def test_01_first_observation_is_only_a_baseline(diary, reg):
    chain(diary, "2026-11-04")
    dec(diary, "2026-11-04", "AAA", "Monitora")
    dec(diary, "2026-11-04", "BBB", "Monitora", quality="insufficiente")
    inv(diary, "2026-11-04", "AAA")
    val(diary, "2026-11-04", "AAA", 100, 80)
    r = gen(diary, reg)
    assert r["created"] and r["new"] == 0 and r["baseline"] == 1                 # BBB's data problem: the starting point
    d = ae.read(reg)
    assert d["counts"]["new"] == 0 and all(a["kind"] == "condizione" for a in d["alerts"])
    assert d["lastRun"]["inputs"]["diaries"]["decision"]["comparison"] == "baseline"


def test_02_d2_state_change(diary, reg):
    two_sessions(diary)
    dec(diary, "2026-11-04", "AAA", "Attendi condizioni migliori")
    dec(diary, "2026-11-05", "AAA", "Rischio elevato", rule="A-R2")
    dec(diary, "2026-11-04", "BBB", "Monitora")
    dec(diary, "2026-11-05", "BBB", "Da approfondire", rule="A-D1")
    gen(diary, reg)
    ch = {a["instrument"]: a for a in by_rule(reg, "AZ-D2-STATO")}
    assert ch["AAA"]["priority"] == "importante" and ch["AAA"]["previous"]["state"] == "Attendi condizioni migliori"
    assert ch["AAA"]["current"] == {"state": "Rischio elevato", "rule": "A-R2"} and "A-R2" in ch["AAA"]["reason"]
    assert ch["BBB"]["priority"] == "ordinaria"                                   # an improvement is never a buy signal
    text = json.dumps(ae.read(reg), ensure_ascii=False).lower()
    assert "compra" not in text and "acquista" not in text and "vendi " not in text


def test_03_fundamentals_need_a_new_identifiable_period(diary, reg):
    two_sessions(diary)
    inv(diary, "2026-11-04", "AAA", quarter="2026-06-30", growth="Forte")
    inv(diary, "2026-11-05", "AAA", quarter="2026-09-30", growth="In calo")                  # new quarter, new judgement
    inv(diary, "2026-11-04", "BBB", quarter="2026-06-30")
    inv(diary, "2026-11-05", "BBB", quarter="2026-06-30", statements="2026-11-05T15:00:00-05:00")  # only the cache date
    gen(diary, reg)
    p = by_rule(reg, "AZ-FOND-PERIODO")
    assert [a["instrument"] for a in p] == ["AAA"] and p[0]["priority"] == "importante"
    assert "crescita da «Forte» a «In calo»" in p[0]["reason"] and "2026-09-30" in p[0]["current"]["periodo"]
    assert not by_rule(reg, "AZ-FOND-RIVISTI")                                    # same judgements: no alert for BBB


def test_03b_observable_analyst_revision_and_grouped_new_statements(diary, reg):
    two_sessions(diary)
    inv(diary, "2026-11-04", "AAA", expectations="Stabili", analysts="2026-11-04")
    inv(diary, "2026-11-05", "AAA", expectations="In peggioramento", analysts="2026-11-05")
    inv(diary, "2026-11-04", "BBB", quarter="2026-06-30")
    inv(diary, "2026-11-05", "BBB", quarter="2026-09-30")                         # new statements, same judgements
    gen(diary, reg)
    assert by_rule(reg, "AZ-FOND-STIME")[0]["current"] == {"aspettative": "In peggioramento"}
    g = by_rule(reg, "AZ-FOND-PERIODO")
    assert len(g) == 1 and g[0]["instrument"] == "gruppo" and g[0]["current"]["società"] == ["BBB"] and g[0]["priority"] == "ordinaria"


# ------------------------------------------------------------------ DCF thresholds, hysteresis, causes

def test_04_dcf_threshold_crossing_with_hysteresis(diary, reg):
    for s in ("2026-11-02", "2026-11-03", "2026-11-04"):
        chain(diary, s)
    val(diary, "2026-11-02", "AAA", 90, 100)          # below the base value
    val(diary, "2026-11-03", "AAA", 101, 100)         # inside the 3% band: still "below"
    val(diary, "2026-11-04", "AAA", 104, 100)         # beyond the band: crossed
    val(diary, "2026-11-02", "BBB", 99, 100)
    val(diary, "2026-11-03", "BBB", 99, 100)
    val(diary, "2026-11-04", "BBB", 101.5, 100)       # oscillation near the threshold: no alert
    gen(diary, reg)
    s = by_rule(reg, "AZ-DCF-SOGLIA")
    base = [a for a in s if a["extra"]["scenario"] == "base"]
    assert [a["instrument"] for a in base] == ["AAA"] and base[0]["priority"] == "importante"
    assert base[0]["previous"]["lato"] == "sotto" and base[0]["current"]["lato"] == "sopra"
    assert "non è un ordine" in " ".join(base[0]["limits"])
    assert ae.DCF_BAND == 0.03                                                      # documented, not optimised


def test_05_price_change_and_assumption_change_shown_separately(diary, reg):
    two_sessions(diary)
    val(diary, "2026-11-04", "AAA", 100, 120)
    val(diary, "2026-11-05", "AAA", 100, 90, statements="2026-11-05T10:00:00-05:00")   # same price, new value
    gen(diary, reg)
    a = by_rule(reg, "AZ-DCF-SOGLIA")
    base = next(x for x in a if x["extra"]["scenario"] == "base")
    c = base["extra"]["causes"]
    assert "effetto sulla distanza 0,0 punti" in c["prezzo"] and "120,00 → 90,00" in c["ipotesi e bilanci"]
    assert "bilanci della fonte riscaricati, stesso periodo" in c["ipotesi e bilanci"]    # 8B: a new download is not new statements


def test_05b_unusable_valuation_and_incomplete_data(diary, reg):
    two_sessions(diary)
    val(diary, "2026-11-04", "AAA", 100, 120)
    val(diary, "2026-11-05", "AAA", 100, 120, status="non_affidabile")
    val(diary, "2026-11-04", "BBB", 100, None)                                     # incomplete: no value
    val(diary, "2026-11-05", "BBB", 150, None)
    gen(diary, reg)
    assert by_rule(reg, "AZ-DCF-AFFIDABILITA")[0]["instrument"] == "AAA"
    assert not [a for a in ae.read(reg)["alerts"] if a["instrument"] == "BBB"]   # missing data: never a crossing


# ------------------------------------------------------------------ ETF: states, risk, bonds, catalogue

def test_06_etf_state_risk_and_trend_exploratory(diary, reg):
    for s in ("2026-11-03", "2026-11-04", "2026-11-05"):
        run_(diary, "etf_runs", s, "E2", at=f"{s}T18:05:00+01:00")
    etf(diary, "2026-11-03", "mondo", "Esposizione da approfondire", trend="Laterale")
    etf(diary, "2026-11-04", "mondo", "Esposizione da approfondire", trend="Rialzista", flags=["R6"])
    etf(diary, "2026-11-05", "mondo", "Trend favorevole da monitorare", trend="Rialzista", level="elevato", flags=["R6", "R2"])
    gen(diary, reg)
    st = by_rule(reg, "ETF-E2-STATO")[0]
    assert st["exploratory"] and any("solo esplorativo" in x for x in st["limits"])
    rk = by_rule(reg, "ETF-RISCHIO")[0]
    assert rk["priority"] == "importante" and rk["current"]["livello"] == "elevato" and "R2" in rk["current"]["nuovi segnali"][0]
    tr = by_rule(reg, "ETF-TREND")[0]                                             # Laterale → Rialzista held 2 sessions
    assert tr["exploratory"] and tr["previous"] == {"trend": "Laterale"} and "non è un'indicazione" in tr["limits"][0]


def test_07_bond_changes_only_with_newer_fund_data(diary, reg):
    for s in ("2026-11-04", "2026-11-05"):
        run_(diary, "etf_runs", s, "E2", at=f"{s}T18:05:00+01:00")
    b0 = {"duration": 6.0, "durationAsOf": "2026-10-31", "yield": 3.0, "aOrBetter": 80.0, "credit": "investment grade"}
    etf(diary, "2026-11-04", "obbl", "Da approfondire", bond=b0)
    etf(diary, "2026-11-05", "obbl", "Da approfondire", bond={**b0, "duration": 6.8, "durationAsOf": "2026-11-04", "credit": "misto"})
    etf(diary, "2026-11-04", "obbl2", "Da approfondire", bond=b0)
    etf(diary, "2026-11-05", "obbl2", "Da approfondire", bond={**b0, "duration": 7.5})   # same date: not a documented change
    gen(diary, reg)
    b = by_rule(reg, "ETF-OBBLIGAZIONI")
    assert [a["instrument"] for a in b] == ["obbl"] and b[0]["priority"] == "importante"
    assert b[0]["current"]["duration (anni)"] == 6.8 and b[0]["current"]["credito"] == "misto"


def cat_item(isin, ter=0.2, top=0.30, stale=()):
    return {"isin": isin, "identity": {"name": {"v": f"Fondo finto {isin}"}, "domicile": {"v": "IE"}},
            "fund": {"replication": {"v": "fisica"}, "distribution": {"v": "accumulazione"}, "hedged": {"v": False}, "baseCurrency": {"v": "USD"}},
            "costs": {"ter": {"v": ter}}, "classification": {"indexKey": "indice finto", "label": "Finto"},
            "exposure": {"top10Weight": {"v": top, "asOf": "2026-10-31"}}, "freshness": {"stale": list(stale)},
            "listings": [{"quoteAvailable": True}]}


def catalog(built, *items):
    return {"builtAt": built, "items": {i["isin"]: i for i in items}}


def test_08_product_and_concentration_changes_from_the_catalogue(diary, reg):
    chain(diary, "2026-11-04")
    assert gen(diary, reg, catalog=catalog("2026-11-04T22:00", cat_item("IE00FINTO001"), cat_item("IE00FINTO002")))["new"] == 0
    r = gen(diary, reg, catalog=catalog("2026-11-20T22:00", cat_item("IE00FINTO001", ter=0.35), cat_item("IE00FINTO002", top=0.41)))
    assert r["created"]
    p = by_rule(reg, "ETF-PRODOTTO")[0]
    assert p["instrument"] == "IE00FINTO001" and p["previous"] == {"TER (%)": 0.2} and p["current"] == {"TER (%)": 0.35}
    c = by_rule(reg, "ETF-CONCENTRAZIONE")[0]
    assert c["instrument"] == "IE00FINTO002" and c["priority"] == "importante" and "non del prodotto" in c["reason"]


# ------------------------------------------------------------------ stale data, dedup, repetition, lifecycle

def test_09_stale_data_reported_once_then_persistent_then_resolved(diary, reg):
    chain(diary, "2026-11-04")
    gen(diary, reg, catalog=catalog("2026-11-04T22:00", cat_item("IE00FINTO001")))
    gen(diary, reg, catalog=catalog("2026-11-11T22:00", cat_item("IE00FINTO001", stale=["ter"])))
    a = by_rule(reg, "ETF-DATI")[0]
    assert a["status"] == "nuovo" and "non aggiornati: ter" in a["current"]["problema"]
    gen(diary, reg, catalog=catalog("2026-11-12T22:00", cat_item("IE00FINTO001", stale=["ter"])))
    b = by_rule(reg, "ETF-DATI")
    assert len(b) == 1 and b[0]["id"] == a["id"] and b[0]["status"] == "persistente"     # never repeated every day
    gen(diary, reg, catalog=catalog("2026-11-13T22:00", cat_item("IE00FINTO001")))
    c = by_rule(reg, "ETF-DATI")
    assert len(c) == 1 and c[0]["status"] == "risolto" and not c[0]["active"]


def test_10_idempotent_and_deduplicated(diary, reg):
    two_sessions(diary)
    dec(diary, "2026-11-04", "AAA", "Monitora")
    dec(diary, "2026-11-05", "AAA", "Rischio elevato")
    assert gen(diary, reg)["created"]
    again = gen(diary, reg)
    assert not again["created"] and "invariati" in again["why"]
    con = sqlite3.connect(reg)
    assert con.execute("SELECT COUNT(*) FROM alert_runs").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM alert_events WHERE rule='AZ-D2-STATO'").fetchone()[0] == 1


def test_11_repeated_event_is_not_a_new_alert(diary, reg):
    two_sessions(diary)
    dec(diary, "2026-11-04", "AAA", "Monitora")
    dec(diary, "2026-11-05", "AAA", "Rischio elevato")
    gen(diary, reg)
    run_(diary, "etf_runs", "2026-11-05", "E2", at="2026-11-05T18:05:00+01:00")     # other inputs change later the same evening
    etf(diary, "2026-11-05", "mondo", "Esposizione da approfondire")
    assert gen(diary, reg)["created"]
    a = by_rule(reg, "AZ-D2-STATO")
    assert len(a) == 1 and a[0]["status"] == "persistente"
    chain(diary, "2026-11-06")
    dec(diary, "2026-11-06", "AAA", "Rischio elevato")                             # nothing new: the old event is superseded
    gen(diary, reg)
    assert by_rule(reg, "AZ-D2-STATO")[0]["status"] == "superato"


def test_12_missing_diary_and_missing_sessions(diary, reg, tmp_path):
    r = ae.generate(NOW, "test", str(tmp_path / "assente.sqlite3"), path=reg)
    assert r["created"] and r["alerts"] == 0                                     # no diary: nothing invented
    chain(diary, "2026-11-04")
    st = {"diaries": [{"key": "decision", "name": "Diario delle decisioni", "missing": ["2026-11-05"], "errors": [], "late": []}]}
    gen(diary, reg, status=st)
    op = by_rule(reg, "OP-SEDUTA")[0]
    assert op["priority"] == "critica" and op["current"] == {"seduta mancante": "2026-11-05"} and "non verrà ricostruita" in op["reason"]


def test_13_different_model_versions_are_never_compared(diary, reg):
    chain(diary, "2026-11-04")
    chain(diary, "2026-11-05", version_dec="D3")
    dec(diary, "2026-11-04", "AAA", "Monitora", version="D2")
    dec(diary, "2026-11-05", "AAA", "Rischio elevato", version="D3")
    gen(diary, reg)
    assert not by_rule(reg, "AZ-D2-STATO")
    v = by_rule(reg, "OP-VERSIONE")[0]
    assert v["instrument"] == "decision" and v["previous"] == {"versione": "D2"} and "metodologico" in v["reason"]


def test_14_late_records_in_the_registry_are_left_out(diary, reg, tmp_path, monkeypatch):
    two_sessions(diary)
    con = sqlite3.connect(diary)
    con.execute("UPDATE dec_runs SET computed_at='2026-11-06T16:00:47-05:00' WHERE session='2026-11-05'")  # synthetic setup
    con.commit()
    con.close()
    dec(diary, "2026-11-04", "AAA", "Monitora")
    dec(diary, "2026-11-05", "AAA", "Rischio elevato")
    f = tmp_path / "esclusioni.json"
    f.write_text(json.dumps({"items": [{"id": "decision:2026-11-05:D2:x", "diary": "decision", "session": "2026-11-05", "version": "D2",
                                        "computedAt": "2026-11-06T16:00:47-05:00", "reason": "tardiva (finta)",
                                        "decidedAt": "2026-11-10", "decisionVersion": "test"}]}))
    monkeypatch.setattr(dx, "FILE", str(f))
    monkeypatch.setattr(dx, "_cache", {"mtime": None, "data": None})
    before = hashlib.sha256(open(diary, "rb").read()).hexdigest()
    gen(diary, reg)
    assert not by_rule(reg, "AZ-D2-STATO")                                        # the late session is not a source
    assert ae.read(reg)["lastRun"]["inputs"]["diaries"]["decision"]["comparison"] == "baseline"
    assert hashlib.sha256(open(diary, "rb").read()).hexdigest() == before        # the diary is never changed


def test_15_test_records_are_never_a_source(diary, reg):
    run_(diary, "etf_runs", "2026-11-04", "E2", source="prova")                  # like the 110 test observations of 4 Nov
    run_(diary, "etf_runs", "2026-11-05", "E2")
    etf(diary, "2026-11-04", "mondo", "Rischio elevato")
    etf(diary, "2026-11-05", "mondo", "Esposizione da approfondire")
    gen(diary, reg)
    assert not by_rule(reg, "ETF-E2-STATO")
    assert ae.read(reg)["lastRun"]["inputs"]["diaries"]["etf"]["comparison"] == "baseline"


def test_16_no_future_information(diary, reg):
    for s in ("2026-11-04", "2026-11-05", "2026-11-06"):
        chain(diary, s)
    dec(diary, "2026-11-04", "AAA", "Monitora")
    dec(diary, "2026-11-05", "AAA", "Monitora")
    dec(diary, "2026-11-06", "AAA", "Rischio elevato")                            # later than the cut-off
    gen(diary, reg, as_of="2026-11-05")
    assert not by_rule(reg, "AZ-D2-STATO")
    assert ae.read(reg)["lastRun"]["inputs"]["diaries"]["decision"]["last"]["session"] == "2026-11-05"


# ------------------------------------------------------------------ registry, read API, isolation, privacy

def test_17_registry_rows_are_immutable(diary, reg):
    two_sessions(diary)
    dec(diary, "2026-11-04", "AAA", "Monitora")
    dec(diary, "2026-11-05", "AAA", "Rischio elevato")
    gen(diary, reg)
    con = sqlite3.connect(reg)
    for q in ("UPDATE alert_events SET priority='ordinaria'", "DELETE FROM alert_events", "UPDATE alert_runs SET status='x'",
              "DELETE FROM alert_lifecycle"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(q)


def test_18_read_api_never_writes(diary, reg, monkeypatch):
    import server
    client = server.app.test_client()
    with app_env.record_writes() as seen:
        r = client.get("/api/alerts")
    assert r.status_code == 200 and r.get_json()["started"] is False and not os.path.exists(ae.DB)
    assert [w for w in seen if "alert" in w[1]] == []
    two_sessions(diary)
    dec(diary, "2026-11-04", "AAA", "Monitora")
    dec(diary, "2026-11-05", "AAA", "Rischio elevato")
    gen(diary, reg)
    monkeypatch.setattr(ae, "DB", reg)
    before = hashlib.sha256(open(reg, "rb").read()).hexdigest()
    with app_env.record_writes() as seen:
        d = client.get("/api/alerts").get_json()
    assert d["started"] and d["counts"]["new"] == 1 and r.headers["Cache-Control"] == "no-store"
    assert hashlib.sha256(open(reg, "rb").read()).hexdigest() == before and [w for w in seen if "alert" in w[1]] == []


def test_19_isolation_and_authorized_writers_only(diary):
    assert app_env.env() == "test" and not ae.DB.startswith(os.path.join(app_env.ROOT, "data"))
    with pytest.raises(app_env.ProductionWriteBlocked):
        ae.connect(os.path.join(app_env.ROOT, "data", "alert.sqlite3"), "test")     # the real registry: never from a test
    import server
    src = open(server.__file__).read()
    loop = src[src.index("def worker"):src.index("# ---------------------------------------------------------------- per-stock detail")]
    job = src[src.index("def run_daily_job"):src.index("def save_signal_diary")]
    assert "save_alerts()" in loop and job.index('save_opportunity_diary(source="job serale")') < job.index('save_alerts(source="job serale")')
    api = src[src.index("def api_alerts"):src.index("def update_opportunity_diary_offline")]
    assert "ae.generate" not in api and "save_alerts" not in api and "ae.read(diary_path=od.DB)" in api


def test_20_no_personal_portfolio_and_no_external_notification(diary, reg, monkeypatch):
    import portfolio
    monkeypatch.setattr(portfolio, "snapshot", lambda *a, **k: pytest.fail("portfolio read by the alerts"))
    monkeypatch.setattr(portfolio, "refresh", lambda *a, **k: pytest.fail("portfolio read by the alerts"))
    two_sessions(diary)
    dec(diary, "2026-11-04", "AAA", "Monitora")
    dec(diary, "2026-11-05", "AAA", "Rischio elevato")
    gen(diary, reg)
    src = open(ae.__file__).read()
    for word in ("import portfolio", "portafoglio/", "requests", "urllib", "smtplib", "osascript", "notify", "yfinance", "download("):
        assert word not in src, word
    payload = sqlite3.connect(reg).execute("SELECT group_concat(payload) FROM alert_events").fetchone()[0]
    assert "quantity" not in payload and "valueEUR" not in payload


def test_21_save_alerts_waits_for_the_whole_chain_and_logs_failures(monkeypatch, caplog):
    import diaries_status
    import server
    import opportunity_diary as od
    os.makedirs(os.path.dirname(od.DB), exist_ok=True)
    od.connect(od.DB, "test").close()
    st = {"diaries": [{"key": "opportunity", "last": {"session": "2026-11-05"}}, {"key": "investment", "last": {"session": "2026-11-05"}},
                      {"key": "valuation", "last": {"session": "2026-11-04"}}, {"key": "decision", "last": {"session": "2026-11-04"}},
                      {"key": "etf", "last": None}]}
    monkeypatch.setattr(diaries_status, "status", lambda now=None: st)

    class Evening(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 5, 16, 30, tzinfo=ET).astimezone(tz)
    monkeypatch.setattr(server, "datetime", Evening)
    monkeypatch.setattr(ae, "generate", lambda *a, **k: pytest.fail("generated on a partial chain"))
    assert "in attesa della catena" in server.save_alerts(source="test")
    monkeypatch.setattr(diaries_status, "status", lambda now=None: (_ for _ in ()).throw(RuntimeError("guasto finto")))
    msg = server.save_alerts(source="test")
    assert "non riuscito (RuntimeError)" in msg and "nessun cambiamento" in msg


def test_22_rules_can_be_disabled_without_touching_models(diary, reg):
    two_sessions(diary)
    dec(diary, "2026-11-04", "AAA", "Monitora")
    dec(diary, "2026-11-05", "AAA", "Rischio elevato")
    gen(diary, reg, disabled=["AZ-D2-STATO"])
    assert not by_rule(reg, "AZ-D2-STATO")
    assert all(r["id"] and r["when"] and r["priority"] for r in ae.RULES)            # every rule documented
    assert json.load(open(ae.RULES_FILE))["disabled"] == []


def test_23_performance(diary, reg):
    two_sessions(diary)
    for i in range(110):
        t = f"T{i:03d}"
        dec(diary, "2026-11-04", t, "Monitora")
        dec(diary, "2026-11-05", t, "Rischio elevato" if i % 5 == 0 else "Monitora")
        inv(diary, "2026-11-04", t)
        inv(diary, "2026-11-05", t, quarter="2026-09-30", growth="In calo" if i % 7 == 0 else "Positiva")
        val(diary, "2026-11-04", t, 100, 90 + i % 20)
        val(diary, "2026-11-05", t, 103, 90 + i % 20)
    t0 = time.perf_counter()
    r = gen(diary, reg)
    t1 = time.perf_counter()
    d = ae.read(reg)
    t2 = time.perf_counter()
    assert r["created"] and r["alerts"] > 20 and t1 - t0 < 2.0 and t2 - t1 < 1.0


# ------------------------------------------------------------------ Part B: the exclusion registry

def test_24_exclusion_registry_is_additive_and_applied_everywhere():
    ids = {i["id"] for i in dx.items()}
    assert {"opportunity:2026-11-03:O2.1:2026-11-04T16:00:00-05:00", "decision:2026-11-04:D2:2026-11-05T16:00:47-05:00"} <= ids
    for i in dx.items():
        assert i["reason"] and i["decidedAt"] and i["decisionVersion"] and i["evidence"]
    assert dx.is_excluded("decision", "2026-11-04", "D2", "2026-11-05T16:00:47-05:00")
    assert not dx.is_excluded("decision", "2026-11-04", "D2", "2026-11-04T16:25:00-05:00")     # same date, other record
    assert not dx.is_excluded("investment", "2026-11-04", "D2", "2026-11-05T16:00:47-05:00")   # other diary
    import opportunity_diary as od
    assert "NOT IN" in od._official("r.source", "decision") and "NOT IN" in od._official("r.source")
    for mod, d in (("decision_diary", "decision"), ("investment_diary", "investment"), ("valuation_diary", "valuation"),
                   ("etf_opportunity_diary", "etf")):
        src = open(os.path.join(app_env.ROOT, mod + ".py")).read()
        assert 'od._official("r.source")' not in src and f'od._official("r.source", "{d}")' in src


def test_25_excluded_records_left_out_of_statistics_counts_kept_apart(monkeypatch, tmp_path):
    import diaries_status as ds
    import opportunity_diary as od
    os.makedirs(os.path.dirname(od.DB), exist_ok=True)
    con = od.connect(od.DB, "test")
    with con:
        for s, at in (("2026-11-03", "2026-11-04T16:00:00-05:00"), ("2026-11-04", "2026-11-04T16:20:59-05:00")):
            con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)", (s, "O2.1", at, "dashboard", "x", "[]", None, 1, 1, None, None))
            con.execute("INSERT INTO observations (session, model_version, list, ticker, in_top) VALUES (?,?,?,?,?)", (s, "O2.1", "trading", "AAA", 0))
    con.close()
    st = od.stats()
    assert st["days"] == 1 and st["first"] == "2026-11-04"                              # 3 Nov out of the statistics
    s = ds.status(now=datetime(2026, 11, 5, 20, 0, tzinfo=ET))
    o = next(d for d in s["diaries"] if d["key"] == "opportunity")
    assert o["official"] == {"runs": 2, "observations": 2} and o["admissible"]["runs"] == 1     # recorded vs admissible
    assert o["registryExcluded"][0]["id"].startswith("opportunity:2026-11-03") and "esclusa dalle statistiche" in o["notes"][0]
    assert sqlite3.connect(od.DB).execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2    # nothing deleted


def test_26_evening_job_keeps_the_diaries_independent_of_the_portfolio_picture():
    import server
    src = open(server.__file__).read()
    job = src[src.index("def run_daily_job"):src.index("def save_signal_diary")]
    personal = job[job.index("portfolio.refresh()") - 200:job.index("history.record(")]
    assert "try:" in personal and "the personal part can never stop the five diaries" in personal
    assert 'log.error("evening job: portfolio picture not saved (%s); the public diaries go on", type(e).__name__)' in job
