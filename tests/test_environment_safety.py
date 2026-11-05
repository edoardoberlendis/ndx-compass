"""Phase 6C: separation of production, test and preview; protection of the real diaries; test records excluded from the
official statistics; atomic and idempotent records; timing of the ETF data; state of the four diaries; phone navigation.

Only made-up data. The real database is NEVER opened for writing here: "production" is played by sentinel folders
(temporary folders registered as production with app_env.protect) and by checks of the configuration. Scenarios that
need a real production or preview process run in a separate Python process (without pytest)."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import app_env
import diaries_status as ds
import etf_catalog as cat
import etf_opportunity as eo
import etf_opportunity_diary as ed
import etf_prices
import opportunity_diary as od
import test_etf_opportunity as t6

ROOT = app_env.ROOT
ROME, ET = ZoneInfo("Europe/Rome"), ZoneInfo("America/New_York")
REAL_DB = os.path.join(ROOT, "data", "opportunita.sqlite3")


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest() if os.path.exists(path) else None


def start_diary(path):
    """Creates a diary file at `path` (a temporary folder, allowed in the test environment)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    od.connect(path).close()


def etf_session(path, session="2026-11-03", source="dashboard"):
    c, p = t6.catalog(), t6.prices()
    res = {m: eo.scan(c, p, m, as_of=session, now=t6.NOW) for m in eo.MODES}
    return ed.record(res, session, "2026-11-03T23:00:00+01:00", source, path=path), res


@pytest.fixture
def sentinel(tmp_path):
    """A fake production folder with a diary that already holds one official session: registered as production AFTER
    it is built, so every later write must be refused and the file must stay byte-identical."""
    prod = tmp_path / "produzione_sentinella"
    db = str(prod / "data" / "opportunita.sqlite3")
    start_diary(db)
    assert etf_session(db)[0][0]
    app_env.protect(str(prod))
    yield db
    app_env.unprotect(str(prod))


def run_py(code, env_extra=None):
    """Runs `code` in a new Python process (no pytest: the environment is decided by NDX_ENV only)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST")}
    env.pop("NDX_ENV", None)
    env.update(env_extra or {})
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "", r.stderr


# ------------------------------------------------------------------ 1. isolation of the production databases

def test_01_test_environment_is_detected_and_cannot_write_production(monkeypatch):
    monkeypatch.setenv("NDX_ENV", "produzione")
    assert app_env.env() == "test"                                    # pytest loaded: never production, whatever the variable says
    assert app_env.guard_active() == "test"
    assert app_env.is_protected(REAL_DB) and app_env.is_protected(os.path.join(ROOT, "portafoglio", "x.json"))
    assert od.DB != REAL_DB and not app_env.is_protected(od.DB)        # conftest points the diary to a temporary file
    with pytest.raises(app_env.ProductionWriteBlocked):
        app_env.check_diary_write(REAL_DB, "dashboard")                # refused before any file is opened
    with pytest.raises(app_env.ProductionWriteBlocked):
        app_env.authorize("server")                                    # a test can never become a production writer
    probe = os.path.join(ROOT, "data", "sentinella_6c_non_deve_esistere.txt")
    with pytest.raises(PermissionError):
        open(probe, "w")
    assert not os.path.exists(probe)
    with pytest.raises(PermissionError):
        sqlite3.connect(os.path.join(ROOT, "data", "sentinella_6c.sqlite3"))
    sqlite3.connect(f"file:{os.path.join(ROOT, 'requirements.txt')}?mode=ro", uri=True).close()   # read-only stays allowed


def test_01b_network_is_blocked_in_tests():
    import socket
    s = socket.socket()
    try:
        with pytest.raises(PermissionError):
            s.connect(("query1.finance.yahoo.com", 443))
    finally:
        s.close()


def test_01c_isolation_covers_every_private_path():
    import portfolio
    for mod, attr in [("portfolio", "PORTFOLIO_DIR"), ("portfolio", "OVERRIDES"), ("portfolio", "CLASS_FILE"), ("pillars", "FILE"),
                      ("history", "DIR"), ("diary", "DIR"), ("etf_buy", "DIR"), ("pos_diary", "DIR"), ("rules", "FILE"),
                      ("opportunity_diary", "DB"), ("etf_prices", "CACHE"), ("fundamentals", "CACHE")]:
        v = getattr(__import__(mod), attr)
        assert not app_env.is_protected(v), (mod, attr, v)
    assert not portfolio.OVERRIDES.startswith(ROOT) and not portfolio.CLASS_FILE.startswith(ROOT)   # were left on the real folder before 6C


# ------------------------------------------------------------------ 2. production and preview processes (sentinels)

def test_02_production_requires_an_authorized_process_and_an_official_origin(tmp_path):
    db = str(tmp_path / "prod" / "data" / "opportunita.sqlite3")
    start_diary(db)
    before = sha(db)
    code = f"""
import app_env, opportunity_diary as od
app_env.protect({str(tmp_path / 'prod')!r})
assert app_env.env() == "produzione"
out = []
try:
    od.connect({db!r}, "prova"); out.append("scritto senza autorizzazione")
except app_env.ProductionWriteBlocked:
    out.append("bloccato")
app_env.authorize("server")
try:
    od.connect({db!r}, "prova"); out.append("prova ammessa")
except app_env.ProductionWriteBlocked:
    out.append("prova rifiutata")
od.connect({db!r}, "dashboard").close(); out.append("dashboard ammessa")
print("|".join(out))
"""
    rc, last, err = run_py(code)
    assert rc == 0, err
    assert last == "bloccato|prova rifiutata|dashboard ammessa"
    assert sha(db) == before                                           # the allowed connection only re-ran CREATE IF NOT EXISTS


def test_02b_the_4_november_incident_is_now_refused(tmp_path):
    """The exact pattern of 4 Nov 2026: a script imports the diary code in the project folder and records with origin
    'prova' without being the server. Here the diary is a sentinel production folder."""
    db = str(tmp_path / "prod" / "data" / "opportunita.sqlite3")
    start_diary(db)
    before = sha(db)
    code = f"""
import app_env, opportunity_diary as od, etf_opportunity_diary as ed
app_env.protect({str(tmp_path / 'prod')!r})
try:
    ed.connect({db!r}, "prova"); print("SCRITTO")
except app_env.ProductionWriteBlocked as e:
    print("BLOCCATO")
"""
    rc, last, err = run_py(code)
    assert rc == 0, err
    assert last == "BLOCCATO" and sha(db) == before


def test_02c_preview_is_isolated(tmp_path):
    src = str(tmp_path / "prod" / "data" / "opportunita.sqlite3")
    start_diary(src)
    assert etf_session(src)[0][0]
    before = sha(src)
    base = str(tmp_path / "anteprima")
    code = f"""
import os, app_env, opportunity_diary as od
assert app_env.env() == "anteprima"
app_env.install_guard()
app_env.protect({str(tmp_path / 'prod')!r})
app_env.isolate({base!r}, public_reads=True)
import portfolio
assert portfolio.PORTFOLIO_DIR.startswith({base!r})
assert app_env.copy_diary({src!r}, od.DB)
res = []
try:
    od.connect({src!r}, "dashboard"); res.append("prod scritto")
except app_env.ProductionWriteBlocked:
    res.append("prod bloccato")
try:
    open(os.path.join(app_env.ROOT, "data", "x_anteprima.txt"), "w"); res.append("progetto scritto")
except PermissionError:
    res.append("progetto bloccato")
try:
    app_env.authorize("server"); res.append("autorizzato")
except app_env.ProductionWriteBlocked:
    res.append("non autorizzabile")
res.append(od.label("dashboard"))
import etf_opportunity_diary as ed
res.append(str(ed.stats()["excluded"]["runs"] == 0 and ed.stats()["days"] == 1))
print("|".join(res))
"""
    rc, last, err = run_py(code, {"NDX_ENV": "anteprima"})
    assert rc == 0, err
    assert last == "prod bloccato|progetto bloccato|non autorizzabile|anteprima|True"
    assert sha(src) == before and not os.path.exists(os.path.join(ROOT, "data", "x_anteprima.txt"))


def test_02d_unknown_environment_is_never_production(monkeypatch):
    code = "import app_env; print(app_env.env())"
    assert run_py(code, {"NDX_ENV": "produzoine"})[1] == "anteprima"         # a typo never becomes production
    assert run_py(code, {"NDX_ENV": "production"})[1] == "produzione"
    assert run_py(code)[1] == "produzione"


# ------------------------------------------------------------------ 3-6. API on a sentinel production diary

def test_03_api_and_save_functions_cannot_modify_a_production_diary(sentinel, monkeypatch):
    import server
    c, p = t6.catalog(), t6.prices()
    monkeypatch.setattr(od, "DB", sentinel)
    monkeypatch.setattr(etf_prices, "load", lambda path=None: p)
    monkeypatch.setattr(cat, "load", lambda *a, **k: c)
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download"))
    p2 = t6.prices()                                                   # a NEW session, not yet recorded
    p2["closes"] = {k: v.copy() for k, v in p["closes"].items()}
    before = sha(sentinel)
    server._eopp.update(key=None, data={})
    cl = server.app.test_client()
    for u in ("/api/etf/opportunities?mode=lungo", "/api/etf/opportunities/sanita_usa", "/api/etf/opportunities/diary",
              "/api/diaries/status", "/api/opportunities/diary"):
        assert cl.get(u).status_code == 200, u
    msg = server.save_etf_scan_diary()                                 # the save itself: refused, logged, nothing written
    assert "già registrata" in msg or "errore" in msg
    nxt = pd.Timestamp("2026-11-04")
    p["closes"] = {k: pd.concat([v, pd.Series([v.iloc[-1]], index=[nxt])]) for k, v in p["closes"].items()}
    p["fetched"] = "2026-11-04T22:00:00+01:00"
    assert "errore" in server.save_etf_scan_diary()                    # new session: blocked by the gate
    assert sha(sentinel) == before


def test_04_real_http_server_on_a_temporary_port_cannot_write(sentinel, monkeypatch):
    import server
    from werkzeug.serving import make_server
    c, p = t6.catalog(), t6.prices()
    monkeypatch.setattr(od, "DB", sentinel)
    monkeypatch.setattr(etf_prices, "load", lambda path=None: p)
    monkeypatch.setattr(cat, "load", lambda *a, **k: c)
    server._eopp.update(key=None, data={})
    before = sha(sentinel)
    srv = make_server("127.0.0.1", 0, server.app, threaded=True)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        base = f"http://127.0.0.1:{srv.server_port}"
        for u in ("/api/etf/opportunities?mode=breve", "/api/etf/opportunities/diary", "/api/diaries/status", "/api/opportunities/diary"):
            with urllib.request.urlopen(base + u, timeout=30) as r:
                assert r.status == 200
                json.loads(r.read())
    finally:
        srv.shutdown()
    assert sha(sentinel) == before


def test_05_read_only_endpoints_write_nothing(tmp_path, monkeypatch):
    import server
    c, p = t6.catalog(), t6.prices()
    start_diary(od.DB)
    assert etf_session(od.DB)[0][0]
    monkeypatch.setattr(etf_prices, "load", lambda path=None: p)
    monkeypatch.setattr(cat, "load", lambda *a, **k: c)
    server._eopp.update(key=None, data={})
    cl = server.app.test_client()
    with app_env.record_writes() as seen:
        for u in ("/api/etf/opportunities?mode=lungo", "/api/etf/opportunities/sanita_usa?mode=breve", "/api/etf/opportunities/diary",
                  "/api/diaries/status", "/api/opportunities/diary"):
            assert cl.get(u).status_code == 200
        od.stats(), od.exists("2026-11-03", "x"), ed.stats(), ed.previous(), ds.status()
    diary_writes = [w for w in seen if "opportunita.sqlite3" in w[1]]
    assert diary_writes == []                                          # never a write connection, not even CREATE IF NOT EXISTS


def test_06_no_unexpected_writes_from_reads_of_a_missing_diary(tmp_path):
    missing = str(tmp_path / "nessuno" / "opportunita.sqlite3")
    with app_env.record_writes() as seen:
        assert od.stats(missing)["started"] is False and od.exists("2026-11-03", "O2.1", missing) is False
        assert ed.stats(missing)["started"] is False and ed.previous(path=missing) == {} and od.observations("2026-11-03", "trading", missing) == []
    assert not os.path.exists(missing) and seen == []                  # a read never creates the diary


# ------------------------------------------------------------------ 7-9. test records: recognised, kept, excluded

def test_07_test_records_are_recognised_and_excluded_from_statistics():
    start_diary(od.DB)
    (ok, _), res = etf_session(od.DB, "2026-11-03", source="prova")
    assert ok
    assert app_env.classify("prova") == "prova" and app_env.classify("anteprima") == "anteprima"
    assert app_env.classify("dashboard") == "produzione" and app_env.classify("qualcosa") == "esclusa"
    st = ed.stats()
    assert st["started"] is False and st["excluded"]["runs"] == 1 and st["excluded"]["observations"] == 2 * len(res["lungo"]["rows"])
    assert st["excluded"]["items"][0]["class"] == "prova"
    assert ed.previous(before="2026-11-04") == {}                       # never used as the previous reading
    # the same session cannot be recorded again as production: idempotency is not bypassed
    (ok2, why), _ = etf_session(od.DB, "2026-11-03", source="dashboard")
    assert not ok2 and "già registrata" in why
    assert ed.run_of("2026-11-03", eo.VERSION)["class"] == "prova"
    # the next session is official and is the only one counted
    c = t6.catalog()
    p = t6.prices(overrides={k: pd.concat([v, pd.Series([v.iloc[-1]], index=[pd.Timestamp("2026-11-04")])])
                             for k, v in t6.prices()["closes"].items()}, fetched="2026-11-04T22:00:00+01:00")
    res2 = {m: eo.scan(c, p, m, as_of="2026-11-04", now=t6.NOW) for m in eo.MODES}
    assert ed.record(res2, "2026-11-04", "2026-11-04T23:00:00+01:00", "dashboard")[0]
    st = ed.stats()
    assert st["days"] == 1 and st["first"] == "2026-11-04" and st["excluded"]["runs"] == 1
    assert ed.previous(before="2026-11-05")["gov_euro_1_3"]["session"] == "2026-11-04"


def test_08_test_records_stay_immutable():
    start_diary(od.DB)
    assert etf_session(od.DB, source="prova")[0][0]
    con = sqlite3.connect(od.DB)
    for q in ("UPDATE etf_runs SET source='dashboard'", "DELETE FROM etf_observations", "UPDATE etf_observations SET state='x'"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(q)
    assert con.execute("SELECT source FROM etf_runs").fetchone()[0] == "prova"


def test_08b_opportunity_statistics_exclude_test_runs():
    start_diary(od.DB)
    con = sqlite3.connect(od.DB)
    with con:
        con.execute("INSERT INTO runs VALUES ('2026-11-03','O2.1','2026-11-03T17:00:00-05:00','prova','x','[]',NULL,1,1,NULL,NULL)")
        con.execute("INSERT INTO observations (session, model_version, list, ticker, in_top) VALUES ('2026-11-03','O2.1','trading','AAA',0)")
    st = od.stats()
    assert st["started"] is False and st["excluded"]["runs"] == 1 and st["excluded"]["observations"] == 1
    assert od.dataset("trading", 5) == []


# ------------------------------------------------------------------ 10-12. concurrency, incomplete transactions, idempotency

def test_10_concurrent_records_of_the_same_session():
    start_diary(od.DB)
    c, p = t6.catalog(), t6.prices()
    res = {m: eo.scan(c, p, m, as_of="2026-11-03", now=t6.NOW) for m in eo.MODES}
    out, errors = [], []
    barrier = threading.Barrier(4)

    def go(src):
        try:
            barrier.wait()
            out.append(ed.record(res, "2026-11-03", "2026-11-03T23:00:00+01:00", src))
        except Exception as e:                                         # an error would mean a clash, not handled
            errors.append(repr(e))
    ts = [threading.Thread(target=go, args=(s,)) for s in ("dashboard", "job serale", "dashboard", "job serale")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == [] and sum(1 for ok, _ in out if ok) == 1
    assert all("già registrata" in why for ok, why in out if not ok)
    con = sqlite3.connect(od.DB)
    assert con.execute("SELECT COUNT(*) FROM etf_runs").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM etf_observations").fetchone()[0] == 2 * len(res["lungo"]["rows"])


def test_11_failed_record_leaves_nothing(monkeypatch):
    start_diary(od.DB)
    c, p = t6.catalog(), t6.prices()
    res = {m: eo.scan(c, p, m, as_of="2026-11-03", now=t6.NOW) for m in eo.MODES}
    res["breve"]["rows"][-1]["key"] = None                             # NOT NULL fails on the last observation
    with pytest.raises(sqlite3.IntegrityError):
        ed.record(res, "2026-11-03", "2026-11-03T23:00:00+01:00", "dashboard")
    con = sqlite3.connect(od.DB)
    assert con.execute("SELECT COUNT(*) FROM etf_runs").fetchone()[0] == 0              # no day saved half and looking complete
    assert con.execute("SELECT COUNT(*) FROM etf_observations").fetchone()[0] == 0
    res["breve"]["rows"][-1]["key"] = "ripristinata"
    assert ed.record(res, "2026-11-03", "2026-11-03T23:00:00+01:00", "dashboard")[0]     # a later attempt can still record


def test_12_repeated_job_creates_no_duplicates():
    start_diary(od.DB)
    assert etf_session(od.DB)[0][0]
    for _ in range(3):
        assert etf_session(od.DB)[0] == (False, "seduta già registrata con questa versione dello scanner ETF")
    assert sqlite3.connect(od.DB).execute("SELECT COUNT(*) FROM etf_runs").fetchone()[0] == 1


# ------------------------------------------------------------------ 13-15. sessions, time zones, misaligned dates

def test_13_last_completed_session():
    assert etf_prices.close_mark(datetime(2026, 11, 6, 17, 59, tzinfo=ROME)).date().isoformat() == "2026-11-05"
    assert etf_prices.close_mark(datetime(2026, 11, 6, 18, 0, tzinfo=ROME)).date().isoformat() == "2026-11-06"
    assert ds.last_nyse_session(datetime(2026, 11, 5, 16, 19, tzinfo=ET)) == "2026-11-04"
    assert ds.last_nyse_session(datetime(2026, 11, 5, 16, 20, tzinfo=ET)) == "2026-11-05"
    assert ds.last_nyse_session(datetime(2026, 11, 27, 13, 30, tzinfo=ET)) == "2026-11-27"   # early close (day after Thanksgiving)
    assert ds.last_nyse_session(datetime(2026, 11, 26, 18, 0, tzinfo=ET)) == "2026-11-25"    # Thanksgiving: market closed
    import server
    assert server.last_closed_session(datetime(2026, 11, 5, 16, 20, tzinfo=ET)) == ds.last_nyse_session(datetime(2026, 11, 5, 16, 20, tzinfo=ET))


def test_14_time_zones_and_exchange_closes():
    # Milan / Xetra: 17:30 local + 30 minutes; a US listing closes at 16:00 New York (22:00 or 21:00 in Rome)
    assert etf_prices.final_at("ABC.MI", "2026-11-05").astimezone(ROME).strftime("%H:%M") == "18:00"
    assert etf_prices.final_at("ABC.DE", "2026-11-05").astimezone(ROME).strftime("%H:%M") == "18:00"
    assert etf_prices.final_at("SPY", "2026-11-05").astimezone(ROME).strftime("%H:%M") == "22:30"
    assert etf_prices.final_at("SPY", "2026-10-28").astimezone(ROME).strftime("%H:%M") == "21:30"   # Europe already on winter time, US not yet
    assert etf_prices.venue_info("ABC.MI")[:3] == ("ETFP", "Borsa Italiana (ETFplus)", "Europe/Rome")
    idx = pd.bdate_range(end="2026-11-05", periods=30)
    s = pd.DataFrame({"Close": range(100, 130)}, index=idx)
    p = {"US": {"symbol": "SPY", "currency": "EUR", "venue": "US", "launch": None, "distribution": "accumulazione", "candidates": [("SPY", "EUR", "US")]},
         "MI": {"symbol": "ABC.MI", "currency": "EUR", "venue": "BI", "launch": None, "distribution": "accumulazione", "candidates": [("ABC.MI", "EUR", "BI")]}}
    out = etf_prices.assemble({"SPY": s, "ABC.MI": s}, p, datetime(2026, 11, 5, 19, 0, tzinfo=ROME))   # "after 18:00" is not enough for the US
    assert out["meta"]["US"]["last"] == "2026-11-04" and out["meta"]["US"]["droppedPartial"] == "2026-11-05"
    assert out["meta"]["MI"]["last"] == "2026-11-05" and out["meta"]["MI"]["droppedPartial"] is None
    m = out["meta"]["MI"]
    assert m["tz"] == "Europe/Rome" and m["closeLocal"] == "17:30" and m["fetched"].startswith("2026-11-05T19:00") and m["delay"]
    usd = etf_prices.assemble({"ABC.MI": s, "EURUSD=X": pd.DataFrame({"Close": [1.1] * 30}, index=idx)},
                              {"MI": dict(p["MI"], currency="USD", candidates=[("ABC.MI", "USD", "BI")])}, datetime(2026, 11, 5, 23, tzinfo=ROME))
    assert "provvisorio" in usd["meta"]["MI"]["fxNote"]


def test_15_etf_and_benchmark_on_different_sessions_are_declared():
    c = t6.catalog()
    p = t6.prices()
    p["closes"][t6.SP] = p["closes"][t6.SP].iloc[:-1]                  # benchmark of the US sector one session behind
    p["closes"][t6.EM] = p["closes"][t6.EM].iloc[:-3]                  # one series stopped three sessions ago
    base = eo.scan(c, t6.prices(), "lungo", now=t6.NOW)
    r = eo.scan(c, p, "lungo", now=t6.NOW)
    hc = eo.detail(r, "sanita_usa")
    assert hc["dates"]["price"] == "2026-11-03" and hc["dates"]["benchmark"] == "2026-11-02" and hc["dates"]["common"] == "2026-11-02"
    assert any("benchmark aggiornato al 2026-11-02" in n for n in hc["completeness"]["notes"])
    assert any("prezzi fermi al" in n for n in eo.detail(r, "emergenti")["completeness"]["notes"])
    assert not any("benchmark aggiornato" in n for n in eo.detail(base, "sanita_usa")["completeness"]["notes"])


def test_15b_bond_dates_kept_apart_and_o1_declared_experimental():
    c = t6.catalog()
    c["items"][t6.G1]["bond"]["duration"]["asOf"] = "2026-10-31"
    r = eo.scan(c, t6.prices(), "lungo", now=t6.NOW, version="E1")          # O1 exists only in model E1
    g = eo.detail(r, "gov_euro_1_3")
    assert g["dates"]["price"] == "2026-11-03" and g["dates"]["duration"] == "2026-10-31"
    assert any("caratteristiche del fondo" in n and "prezzo al 2026-11-03" in n for n in g["completeness"]["notes"])
    o1 = next(x for x in g["conditions"]["fav"] if x["id"] == "O1")
    assert "euristica sperimentale" in o1["text"] and eo.P["bond_cushion"] == 1.0 and r["version"] == "E1"   # wording only
    assert g["bond"]["duration"] == 1.9 and g["bond"]["yield"] == 3.3                                       # shown apart


# ------------------------------------------------------------------ 16. state of the diaries (five since D2)

def test_16_state_of_the_diaries_is_read_only(tmp_path):
    start_diary(od.DB)
    assert etf_session(od.DB, "2026-11-03", source="prova")[0][0]
    con = sqlite3.connect(od.DB)
    with con:
        for s in ("2026-11-02", "2026-11-04"):
            con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)", (s, "O2.1", s + "T16:30:00-05:00", "dashboard", "x", "[]", None, 1, 1, None, None))
            con.execute("INSERT INTO observations (session, model_version, list, ticker, in_top) VALUES (?,?,?,?,?)", (s, "O2.1", "trading", "AAA", 0))
    before = sha(od.DB)
    with app_env.record_writes() as seen:
        st = ds.status(now=datetime(2026, 11, 5, 20, 0, tzinfo=ET))
    assert [w for w in seen if "opportunita" in w[1]] == [] and sha(od.DB) == before
    by = {d["key"]: d for d in st["diaries"]}
    assert set(by) == {"opportunity", "investment", "valuation", "etf", "decision"}     # decision diary since phase 7A (D2)
    assert by["opportunity"]["official"] == {"runs": 2, "observations": 2}
    assert by["opportunity"]["missing"] == ["2026-11-03", "2026-11-05"]          # NYSE sessions without an official record
    assert by["etf"]["official"]["runs"] == 0 and by["etf"]["excluded"]["observations"] > 0
    assert any("occupata da una registrazione di prova" in n for n in by["etf"]["notes"])
    assert st["summary"]["excludedObservations"] == by["etf"]["excluded"]["observations"]
    assert "BEGIN IMMEDIATE" in st["duplicates"] and "Diario dello scanner ETF" in ds.text(st)


def test_16b_status_command_runs_without_a_diary(tmp_path):
    st = ds.status(path=str(tmp_path / "nessuno.sqlite3"))
    assert "diario delle opportunità non ancora avviato" in st["problems"]
    assert all(d["official"]["runs"] == 0 for d in st["diaries"])


# ------------------------------------------------------------------ 17. phone navigation

def test_17_phone_navigation_scrolls_the_tab_row_not_the_page():
    css = open(os.path.join(ROOT, "static", "styles.css")).read()
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    html = open(os.path.join(ROOT, "static", "index.html")).read()
    block = css[css.index("phase 6C: tab row on narrow phones"):]
    assert "overflow-x: auto" in block and "min-width: 0" in block and "flex: 0 0 auto" in block
    assert "display: none" not in block.split(".tablist::-webkit-scrollbar")[0]           # no tab hidden
    tabs = __import__("re").findall(r'data-main="(\w+)"', html.split('<div class="tablist"')[1].split("</div>")[0])
    assert tabs == ["opportunita", "mercato", "portafoglio", "azioni", "etf"]               # same tabs, same order
    set_view = js[js.index("function setView"):js.index("function setView") + 900]
    assert "keepTabVisible()" in set_view and "function keepTabVisible" in js
    assert 'addEventListener("hashchange"' in js                                          # direct links and Back unchanged


# ------------------------------------------------------------------ 18. wiring of the authorized writers

def test_18_only_the_real_entry_points_authorize_writes():
    src = open(os.path.join(ROOT, "server.py")).read()
    main = src[src.index('if __name__ == "__main__":'):]
    assert 'authorize_writer("server")' in main
    assert 'authorize_writer("job serale")' in src[src.index("def run_daily_job"):src.index("def save_signal_diary")]
    assert 'authorize_writer("comando manuale")' in src[src.index("def update_opportunity_diary_offline"):src.index('@app.route("/api/opportunities")')]
    assert src.count("authorize_writer(") == 4                                             # definition + three entry points
    for f in ("opportunity_diary.py", "investment_diary.py", "valuation_diary.py", "etf_opportunity_diary.py"):
        s = open(os.path.join(ROOT, f)).read()
        assert 'con.execute("BEGIN IMMEDIATE")' in s, f
    pv = open(os.path.join(ROOT, "preview.py")).read()
    assert 'os.environ["NDX_ENV"] = "anteprima"' in pv and "install_guard()" in pv and "authorize" not in pv.replace("Non autorizza", "")
    assert open(os.path.join(ROOT, "tests", "conftest.py")).read().count("app_env.install_guard()") == 1
