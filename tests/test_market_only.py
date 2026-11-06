"""Phase 8B: MARKET-ONLY mode, job registry, schedule, temporal reading of the alerts, Riepilogo del giorno, stato del sistema.

Only SYNTHETIC data (made-up tickers AAA, BBB, made-up ETF exposures), temporary folders and SENTINEL portfolio folders.
The real portfolio is never opened: the market-only protection is turned on before any access, so an access to the real
portafoglio/ (in the subprocess of the import test) is blocked before it happens. No network, no launchctl."""
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import app_env

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ET = ZoneInfo("America/New_York")
ROME = ZoneInfo("Europe/Rome")
PY = sys.executable


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def sentinel(tmp_path):
    """A fake portfolio folder with made-up files, written BEFORE the protection is turned on."""
    import portfolio
    d = tmp_path / "portafoglio"                                    # = portfolio.PORTFOLIO_DIR (conftest isolation)
    assert os.path.realpath(portfolio.PORTFOLIO_DIR) == os.path.realpath(str(d))
    for sub in ("diario", "storico", "diario_etf", "diario_posizioni"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    (d / "Fineco_finto.xlsx").write_bytes(b"SEGRETO-FINTO")
    (d / "storico" / "flussi.json").write_text('{"flussi": "SEGRETO-FINTO"}')
    (d / "storico" / "2026-11-05.json").write_text('{"value": 12345.67}')
    (d / "diario" / "2026-11-05.json").write_text("[]")
    return d


def snapshot_of(folder):
    out = {}
    for base, _, files in os.walk(folder):
        for f in files:
            p = os.path.join(base, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, folder)] = (fh.read(), os.path.getmtime(p))
    return out


@pytest.fixture
def market_only(sentinel):
    before = snapshot_of(sentinel)
    app_env.enable_market_only([str(sentinel)])
    yield sentinel
    app_env._end_market_only_for_tests()
    assert snapshot_of(sentinel) == before, "market-only changed the sentinel portfolio"


# ------------------------------------------------------------------ 1. the protection itself

def test_01_protection_blocks_every_kind_of_access_to_the_portfolio(market_only, tmp_path):
    s = str(market_only)
    attempts = [lambda: open(os.path.join(s, "Fineco_finto.xlsx"), "rb").read(),
                lambda: open(os.path.join(s, "nuovo.json"), "w"),
                lambda: os.listdir(s), lambda: list(os.scandir(os.path.join(s, "storico"))),
                lambda: __import__("glob").glob(os.path.join(s, "*.xlsx")),
                lambda: __import__("pathlib").Path(s, "storico", "flussi.json").read_text(),
                lambda: sqlite3.connect(os.path.join(s, "x.sqlite3")),
                lambda: os.mkdir(os.path.join(s, "nuova")),
                lambda: os.remove(os.path.join(s, "diario", "2026-11-05.json")),
                lambda: os.rename(os.path.join(s, "diario", "2026-11-05.json"), str(tmp_path / "fuori.json"))]
    for f in attempts:
        with pytest.raises(app_env.PrivateAccessBlocked):
            f()
    n = sum(app_env.private_blocked().values())
    assert list(os.walk(s)) == [] and sum(app_env.private_blocked().values()) == n + 1   # os.walk swallows the error: empty
    cwd = os.getcwd()
    try:                                                             # a relative path is resolved before the check
        os.chdir(str(tmp_path))
        with pytest.raises(app_env.PrivateAccessBlocked):
            open(os.path.join("portafoglio", "storico", "flussi.json")).read()
    finally:
        os.chdir(cwd)
    blocked = app_env.private_blocked()
    assert sum(blocked.values()) >= len(attempts) and all(not os.sep in k for k in blocked)   # kinds only, no file names
    other = tmp_path / "pubblico.json"                              # outside the portfolio everything works as before
    other.write_text("{}")
    assert json.loads(other.read_text()) == {}


def test_02_protection_is_an_oserror_and_cannot_be_turned_off_outside_tests(monkeypatch):
    assert issubclass(app_env.PrivateAccessBlocked, OSError)
    monkeypatch.setattr(app_env, "env", lambda: "produzione")
    with pytest.raises(RuntimeError):
        app_env._end_market_only_for_tests()


def test_03_imports_have_no_side_effects_on_the_portfolio(tmp_path):
    """Every module of the project imported with the protection on the REAL portafoglio/: any access would be blocked
    before it happens (so nothing is read) and counted. Zero accesses allowed."""
    code = (
        "import glob, importlib, json, os, sys\n"
        f"sys.path.insert(0, {ROOT!r}); os.chdir({ROOT!r})\n"
        "import app_env\n"
        "app_env.enable_market_only()\n"
        "app_env.install_guard()\n"
        "skip = {'preview.py', 'morning_job.py', 'daily_job.py'}\n"
        "mods = sorted(os.path.basename(f)[:-3] for f in glob.glob('*.py') if os.path.basename(f) not in skip)\n"
        "err = {}\n"
        "for m in mods:\n"
        "    try: importlib.import_module(m)\n"
        "    except Exception as e: err[m] = type(e).__name__\n"
        "print(json.dumps({'n': len(mods), 'blocked': app_env.private_blocked(), 'err': err, 'mo': app_env.market_only()}))\n")
    env = {**os.environ, "NDX_ENV": "anteprima", "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=240, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr[-2000:]
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["mo"] and r["n"] > 40 and r["err"] == {}
    assert r["blocked"] == {}, f"imports touched portafoglio/: {r['blocked']}"


def test_04_daily_job_turns_the_protection_on_before_importing_the_server(tmp_path):
    src = open(os.path.join(ROOT, "daily_job.py")).read()
    assert src.index("app_env.enable_market_only()") < src.index("import server")
    assert src.index("app_env.enable_market_only()") < src.index("import market_calendar")
    code = (
        "import sys, json, os\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        "seen = {}\n"
        "class Spy:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name in ('server', 'portfolio') and name not in seen:\n"
        "            import app_env; seen[name] = app_env.market_only()\n"
        "        return None\n"
        "sys.meta_path.insert(0, Spy())\n"
        "sys.argv = ['daily_job.py', '--market-only']\n"
        "import daily_job, app_env\n"
        "print(json.dumps({'seen': seen, 'flag': daily_job.MARKET_ONLY, 'blocked': app_env.private_blocked()}))\n")
    env = {**os.environ, "NDX_ENV": "anteprima", "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=240, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr[-2000:]
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["flag"] is True and r["seen"] == {"server": True, "portfolio": True} and r["blocked"] == {}


def test_05_daily_job_refuses_unknown_options_and_full_mode_is_unchanged(tmp_path):
    src = open(os.path.join(ROOT, "daily_job.py")).read()
    assert "server.run_daily_job(market_only=MARKET_ONLY)" in src
    assert 'MARKET_ONLY = "--market-only" in sys.argv[1:]' in src
    assert "ammessa solo --market-only" in src


# ------------------------------------------------------------------ 2. the evening job in both modes (stubbed steps)

PERSONAL = ("portfolio.refresh", "portfolio.refresh_quotes", "portfolio.snapshot", "history.record", "save_signal_diary",
            "save_etf_diary", "save_pos_diary", "portfolio_view")


@pytest.fixture
def job(monkeypatch):
    """server.run_daily_job with every download replaced by a stub that only records the call."""
    import analysts
    import etf_prices
    import fundamentals
    import history
    import macro_calendar
    import portfolio
    import pos_diary
    import server
    import signals
    calls = []
    rec = lambda name, ret=None: (lambda *a, **k: calls.append(name) or ret)
    monkeypatch.setattr(server, "load_constituents", rec("constituents", [{"ticker": "AAA"}, {"ticker": "BBB"}]))
    monkeypatch.setattr(server, "load_infos", rec("infos", {}))
    monkeypatch.setattr(analysts, "is_fresh", lambda: True)
    monkeypatch.setattr(analysts, "cached_data", rec("analysts", {}))
    monkeypatch.setattr(server, "qqq_top_weights", rec("weights", {}))
    monkeypatch.setattr(server.store, "refresh_daily", rec("prices"))
    monkeypatch.setattr(server.store, "refresh_intraday", rec("intraday"))
    monkeypatch.setattr(server, "news", rec("news", []))
    monkeypatch.setattr(server.store, "build", rec("build"))
    monkeypatch.setattr(macro_calendar, "refresh", rec("macro"))
    monkeypatch.setattr(fundamentals, "refresh", rec("fundamentals"))
    monkeypatch.setattr(etf_prices, "due", lambda *a: False)
    monkeypatch.setattr(server, "save_etf_scan_diary", rec("etf scan diary"))
    monkeypatch.setattr(server, "save_opportunity_diary", rec("chain", "diario delle opportunità: seduta 2026-11-05 registrata"))
    monkeypatch.setattr(server, "save_alerts", rec("alerts", "alert: 3 nuovi"))
    monkeypatch.setattr(signals, "list_reports", lambda: [])
    monkeypatch.setattr(signals, "run", rec("report"))
    personal = {"portfolio.refresh": (portfolio, "refresh"), "portfolio.refresh_quotes": (portfolio, "refresh_quotes"),
                "portfolio.snapshot": (portfolio, "snapshot"), "history.record": (history, "record"),
                "save_signal_diary": (server, "save_signal_diary"), "save_etf_diary": (server, "save_etf_diary"),
                "save_pos_diary": (server, "save_pos_diary"), "portfolio_view": (server, "portfolio_view")}
    for name, (mod, attr) in personal.items():
        monkeypatch.setattr(mod, attr, rec(name, {"positions": [{"name": "SEGRETO", "value": 12345.67}]} if attr == "snapshot" else None))
    monkeypatch.setattr(pos_diary, "exists", lambda *a: True)
    monkeypatch.setattr(portfolio, "_state", {**portfolio._state, "resolving": False})
    return server, calls


def test_06_market_only_job_runs_only_the_public_steps(job, market_only, caplog):
    import job_status
    server, calls = job
    caplog.set_level("INFO")
    server.run_daily_job(market_only=True)
    assert not set(calls) & set(PERSONAL), [c for c in calls if c in PERSONAL]
    for step in ("constituents", "prices", "build", "macro", "fundamentals", "etf scan diary", "chain", "alerts"):
        assert step in calls
    assert calls.index("fundamentals") < calls.index("chain") < calls.index("alerts")
    assert app_env.private_blocked() == {}
    r = job_status.last()
    assert r["mode"] == "market-only" and r["completed"] and r["finishedAt"]
    names = [s["name"] for s in r["steps"]]
    assert "fotografia del portafoglio" not in names and "diario dei segnali" not in names and "catena dei diari" in names
    assert "SEGRETO" not in caplog.text and "12345" not in caplog.text and "market-only" in caplog.text


def test_07_market_only_without_the_protection_is_refused(job):
    server, calls = job
    assert not app_env.market_only()
    with pytest.raises(RuntimeError, match="protezione"):
        server.run_daily_job(market_only=True)
    assert calls == []


def test_08_full_job_keeps_the_previous_behaviour(job, caplog):
    import job_status
    server, calls = job
    caplog.set_level("INFO")
    server.run_daily_job()
    for step in ("portfolio.refresh", "history.record", "save_signal_diary", "save_etf_diary", "save_pos_diary", "chain", "alerts"):
        assert step in calls
    assert calls.index("history.record") < calls.index("chain")
    r = job_status.last()
    assert r["mode"] == "completo" and r["completed"]
    text = json.dumps(job_status.read())
    assert "SEGRETO" not in text and "12345" not in text and "SEGRETO" not in caplog.text


def test_09_personal_failure_does_not_stop_the_diaries_and_is_recorded_without_data(job, monkeypatch, caplog):
    import history
    import job_status
    server, calls = job
    monkeypatch.setattr(history, "record", lambda *a: (_ for _ in ()).throw(ValueError("posizione SEGRETO 12345.67")))
    server.run_daily_job()
    assert "chain" in calls and "alerts" in calls
    step = next(s for s in job_status.last()["steps"] if s["name"] == "fotografia del portafoglio")
    assert step == {"name": "fotografia del portafoglio", "outcome": "errore", "error": "ValueError"}
    assert "SEGRETO" not in caplog.text and "SEGRETO" not in json.dumps(job_status.read())


def test_10_interrupted_job_is_recorded_as_not_completed(job, monkeypatch):
    import job_status
    server, calls = job
    monkeypatch.setattr(server, "load_constituents", lambda: (_ for _ in ()).throw(ConnectionError("rete")))
    with pytest.raises(ConnectionError):
        server.run_daily_job()
    r = job_status.last()
    assert r["completed"] is False and r["error"] == "ConnectionError" and r["finishedAt"]
    assert job_status.last(completed=True) is None


def test_11_market_only_job_twice_is_idempotent_in_its_registry(job, market_only):
    import job_status
    server, calls = job
    server.run_daily_job(market_only=True)
    server.run_daily_job(market_only=True)
    runs = job_status.read()
    assert len(runs) == 2 and all(r["completed"] and r["mode"] == "market-only" for r in runs)   # same second: two runs
    assert len({r["id"] for r in runs}) == 2
    assert calls.count("chain") == 2                     # the diaries themselves refuse a second record (BEGIN IMMEDIATE)


def test_12_signal_diary_count_is_not_listed_in_market_only(market_only, monkeypatch):
    import diary
    import server
    monkeypatch.setattr(diary, "days", lambda: pytest.fail("signal diary listed in market-only"))
    assert server.diary_days() == 0
    assert app_env.private_blocked() == {}


def test_13_nothing_to_do_on_a_holiday_uses_the_public_diaries_only(market_only, monkeypatch):
    import daily_job
    import decision_diary
    import diary
    import opportunity_diary as od
    monkeypatch.setattr(daily_job, "MARKET_ONLY", True)
    monkeypatch.setattr(diary, "days", lambda: pytest.fail("portafoglio/diario read"))
    monkeypatch.setattr(od, "exists", lambda s, v, path=None: s == "2026-11-25")
    monkeypatch.setattr(decision_diary, "exists", lambda s, v, path=None: s == "2026-11-25")
    thanksgiving = datetime(2026, 11, 26, 22, 0, tzinfo=ET)
    assert daily_job.nothing_to_do(thanksgiving) is True
    monkeypatch.setattr(decision_diary, "exists", lambda s, v, path=None: False)
    assert daily_job.nothing_to_do(thanksgiving) is False            # decisions missing: the job runs
    assert daily_job.nothing_to_do(datetime(2026, 11, 25, 22, 0, tzinfo=ET)) is False   # trading day: always runs


def test_14_job_registry_concurrent_writers_keep_a_valid_file():
    import job_status
    errors = []

    def one(i):
        try:
            r = job_status.Run("market-only", datetime(2026, 11, 5, 17, 0, i, tzinfo=ET))
            r.step("prezzi")
            r.finish(datetime(2026, 11, 5, 17, 5, i, tzinfo=ET), session="2026-11-05")
        except Exception as e:                       # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=one, args=(i,)) for i in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    runs = job_status.read()
    assert len(runs) == 12 and all(r["completed"] for r in runs)
    assert not [f for f in os.listdir(os.path.dirname(job_status.FILE)) if f.endswith(".tmp")]


def test_15_job_registry_keeps_only_operational_fields():
    import job_status
    r = job_status.Run("completo", datetime(2026, 11, 5, 17, 0, tzinfo=ET))
    r.step("fotografia del portafoglio", "errore", error=KeyError("ISIN IT000SEGRETO"))
    r.finish(datetime(2026, 11, 5, 17, 1, tzinfo=ET))
    run = job_status.read()[-1]
    assert set(run) <= {"id", "mode", "startedAt", "finishedAt", "completed", "steps", "problems", "session", "error"}
    assert "SEGRETO" not in json.dumps(run) and run["steps"][0]["error"] == "KeyError"
    with pytest.raises(ValueError):
        job_status.Run("personale", datetime(2026, 11, 5, tzinfo=ET))


def test_16_stale_run_is_interrupted_not_running():
    import job_status
    start = datetime(2026, 11, 5, 17, 0, tzinfo=ET)
    run = {"mode": "market-only", "startedAt": start.isoformat(), "finishedAt": None, "completed": False}
    assert not job_status.stale(run, start + timedelta(hours=1))
    assert job_status.stale(run, start + timedelta(hours=4))                       # Mac switched off during the run


# ------------------------------------------------------------------ 3. schedule.sh (never launchctl for real)

def test_17_schedule_market_only_has_its_own_label_and_never_touches_the_personal_jobs():
    src = open(os.path.join(ROOT, "schedule.sh")).read()
    assert 'MARKET="com.nasdaq100.market"' in src and src.count("com.nasdaq100.market") == 1
    cases = {m.group(1): m.group(2) for m in re.finditer(r"\n  ([a-z-]+)\)\n(.*?)\n    ;;", src, re.S)}
    assert set(cases) >= {"install", "remove", "run", "status", "install-market", "remove-market", "status-market"}
    for c in ("install", "remove", "run", "status"):
        assert "$MARKET" not in cases[c]
    for c in ("install-market", "remove-market", "status-market"):
        assert "$MORNING" not in cases[c].replace('echo "Not touched: $MORNING and $EVENING"', "").replace(
            "(not touched: $MORNING and $EVENING)", "")
        assert "bootout \"gui/$(id -u)/$EVENING\"" not in cases[c] and "plist \"$EVENING\"" not in cases[c]
    assert 'plist "$MARKET" daily_job.py "$MARKET_H" "$MARKET_M" daily_job_market --market-only' in cases["install-market"]
    assert "MARKET_H=23; MARKET_M=0" in src


def test_18_install_market_writes_a_valid_plist_with_a_fake_launchctl(tmp_path):
    """A copy of schedule.sh where every launchctl is replaced by echo: nothing can be installed on this Mac."""
    src = open(os.path.join(ROOT, "schedule.sh")).read().replace("launchctl ", "echo FAKE-LAUNCHCTL ")
    assert "launchctl " not in src
    d = tmp_path / "progetto"
    (d / ".venv" / "bin").mkdir(parents=True)
    fake_py = d / ".venv" / "bin" / "python"
    fake_py.write_text("#!/bin/sh\nexit 0\n")
    fake_py.chmod(0o755)
    (d / "schedule.sh").write_text(src)
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home)}
    out = subprocess.run(["/bin/sh", str(d / "schedule.sh"), "install-market"], capture_output=True, text=True, env=env, timeout=30)
    assert out.returncode == 0, out.stderr
    agents = home / "Library" / "LaunchAgents"
    assert [p.name for p in agents.iterdir()] == ["com.nasdaq100.market.plist"]
    plist = (agents / "com.nasdaq100.market.plist").read_text()
    assert "<string>--market-only</string>" in plist and "daily_job_market.log" in plist
    assert plist.count("<key>Hour</key><integer>23</integer>") == 5 and "<integer>6</integer>" not in plist.split("StartCalendarInterval")[1].split("StandardOut")[0].replace("<integer>23</integer>", "")
    lint = subprocess.run(["/usr/bin/plutil", "-lint", str(agents / "com.nasdaq100.market.plist")], capture_output=True, text=True)
    assert lint.returncode == 0, lint.stdout
    assert "com.nasdaq100.daily" not in out.stdout.replace("Not touched", "") or "Not touched" in out.stdout
    assert all("com.nasdaq100.market" in line for line in out.stdout.splitlines() if "FAKE-LAUNCHCTL" in line)
    out = subprocess.run(["/bin/sh", str(d / "schedule.sh"), "remove-market"], capture_output=True, text=True, env=env, timeout=30)
    assert out.returncode == 0 and not list(agents.iterdir())


# ------------------------------------------------------------------ 4. calendars, DST, holidays, early closes, windows

def _sessions(first, last):
    import diaries_status
    return diaries_status.nyse_sessions(first, last)


def test_19_23_00_in_italy_is_always_after_the_nyse_close_and_inside_the_window():
    import diaries_status
    for day in _sessions("2026-01-02", "2027-12-31"):
        d = datetime.fromisoformat(day)
        run = datetime(d.year, d.month, d.day, 23, 0, tzinfo=ROME)
        ready = diaries_status.ready_at(day)
        assert run >= ready + timedelta(minutes=30), day                       # final daily bars, never mid-session
        assert run < diaries_status.recordable_until(day), day
        assert diaries_status.last_nyse_session(run) == day


def test_20_dst_gaps_early_closes_and_holidays():
    import diaries_status
    import market_calendar
    # US and EU daylight saving change on different Sundays: the close in Italy is 21:00 for a few weeks, not 22:00
    assert diaries_status.ready_at("2026-03-10").astimezone(ROME).strftime("%H:%M") == "21:20"
    assert diaries_status.ready_at("2026-10-29").astimezone(ROME).strftime("%H:%M") == "21:20"
    assert diaries_status.ready_at("2026-11-05").astimezone(ROME).strftime("%H:%M") == "22:20"
    # early close the day after Thanksgiving (13:00 New York)
    assert market_calendar.close_minute(datetime(2026, 11, 27, tzinfo=ET)) == 13 * 60
    assert diaries_status.ready_at("2026-11-27").astimezone(ET).strftime("%H:%M") == "13:20"
    # holidays: no session, the window of the previous session runs to the next real one
    assert not market_calendar.is_trading_day(datetime(2026, 11, 26).date())
    assert diaries_status.recordable_until("2026-11-25") == datetime(2026, 11, 27, 4, 0, tzinfo=ET)
    assert diaries_status.recordable_until("2026-10-30") == datetime(2026, 11, 2, 4, 0, tzinfo=ET)      # weekend + DST end
    assert diaries_status.recordable_until("2026-11-27") == datetime(2026, 11, 30, 4, 0, tzinfo=ET)


def test_21_mac_asleep_wakes_inside_or_outside_the_window():
    import diaries_status
    day = "2026-11-05"
    until = diaries_status.recordable_until(day)
    inside = datetime(2026, 11, 6, 8, 30, tzinfo=ROME)            # woken up the next morning before 10:00 in Italy
    late = datetime(2026, 11, 6, 10, 30, tzinfo=ROME)             # after 04:00 New York: the session is lost
    assert inside < until <= late
    assert "si può ancora" in diaries_status.next_text(None, day, inside) or "entro le" in diaries_status.next_text(
        {"session": "2026-11-04"}, day, inside)
    t = diaries_status.next_text({"session": "2026-11-04"}, day, late)
    assert "non più recuperabile" in t and "retroattiva" in t


def test_22_late_wake_never_records_the_lost_session(monkeypatch):
    """The evening chain refuses a session outside its window (Phase 7C): a Mac woken after 04:00 New York records nothing."""
    import server
    late = datetime(2026, 11, 6, 4, 30, tzinfo=ET)

    class Late(datetime):
        @classmethod
        def now(cls, tz=None):
            return late.astimezone(tz) if tz else late.replace(tzinfo=None)
    monkeypatch.setattr(server, "datetime", Late)
    monkeypatch.setattr(server, "market_status", lambda *a: "pre")
    msg = server.save_opportunity_diary(source="job serale")
    assert msg == "mercato aperto o pre-apertura: si registra dopo la chiusura"       # the window guard of 7C is tested there


# ------------------------------------------------------------------ 5. temporal reading of the alerts

def _diary(tmp_path):
    from tests.test_alerts import TABLES
    p = str(tmp_path / "dati" / "diari.sqlite3")
    os.makedirs(os.path.dirname(p))
    con = sqlite3.connect(p)
    for t, cols in TABLES.items():
        con.execute(f"CREATE TABLE {t} ({cols})")
    con.commit()
    con.close()
    return p


def _inv(path, session, ticker, quarter, announced=None, statements=None):
    from tests.test_alerts import add
    add(path, "inv_observations", session=session, model_version="F1", ticker=ticker, name=f"{ticker} Inc. (finta)",
        completeness={"state": "Completa"},
        dims={"growth": {"state": "Positiva" if quarter < "2026-09-30" else "Debole", "reasons": ["ricavi finti"]},
              "quality": {"state": "Buona", "reasons": []}, "solidity": {"state": "Solida", "reasons": []},
              "expectations": {"state": "Stabili", "reasons": []}},
        data_dates={"statements": statements or f"{session}T11:45:00-05:00", "latestQuarter": quarter, "latestYear": "2025-12-31",
                    "analysts": session, "latestQuarterAnnounced": announced})


def _two_sessions(tmp_path, announced="2026-11-02"):
    from tests.test_alerts import chain
    p = _diary(tmp_path)
    chain(p, "2026-11-04")
    chain(p, "2026-11-05")
    _inv(p, "2026-11-04", "AAA", "2026-06-30", "2026-07-30")
    _inv(p, "2026-11-05", "AAA", "2026-09-30", announced)
    _inv(p, "2026-11-04", "BBB", "2026-06-30", "2026-07-30")
    _inv(p, "2026-11-05", "BBB", "2026-09-30", None)
    return p


def _gen(diary, reg, now=datetime(2026, 11, 5, 17, 0, tzinfo=ET)):
    import alert_engine as ae
    return ae.generate(now, "test", diary, path=reg)


def test_23_publication_acquisition_period_detection_and_sessions_are_kept_apart(tmp_path):
    import alert_engine as ae
    p, reg = _two_sessions(tmp_path), str(tmp_path / "reg" / "alert.sqlite3")
    _gen(p, reg)
    a = {x["instrument"]: x for x in ae.read(reg)["alerts"] if x["rule"] == "AZ-FOND-PERIODO"}
    t = a["AAA"]["timeline"]
    assert t["period"] == "2026-09-30" and t["published"] == "2026-11-02" and t["publishedVerified"] is False
    assert t["acquired"].startswith("2026-11-05") and t["sessions"] == {"previous": "2026-11-04", "current": "2026-11-05"}
    assert t["detectedAt"].startswith("2026-11-05T17:00")
    assert "secondo la fonte" in t["headline"] and "non verificata" in t["headline"]
    assert a["BBB"]["timeline"]["headline"] == "Nuovi dati acquisiti" and a["BBB"]["timeline"]["published"] is None
    text = json.dumps(ae.read(reg), ensure_ascii=False).lower()
    assert "pubblicata oggi" not in text and "pubblicato oggi" not in text


def test_24_first_check_events_are_historical_at_activation_later_ones_are_not(tmp_path):
    import alert_engine as ae
    from tests.test_alerts import chain
    p, reg = _two_sessions(tmp_path), str(tmp_path / "reg" / "alert.sqlite3")
    _gen(p, reg)
    first = [x for x in ae.read(reg)["alerts"] if x["kind"] == "evento"]
    assert first and all(x["timeline"]["atActivation"] for x in first)
    assert all("all'attivazione" in x["timeline"]["activationText"] for x in first)
    chain(p, "2026-11-06")
    _inv(p, "2026-11-06", "AAA", "2026-09-30", "2026-11-02")
    _inv(p, "2026-11-06", "BBB", "2026-12-31", None)            # made-up later period: a change of the latest session
    _gen(p, reg, datetime(2026, 11, 6, 17, 0, tzinfo=ET))
    later = [x for x in ae.read(reg)["alerts"] if x["kind"] == "evento" and x["session"] == "2026-11-06"]
    assert later and not any(x["timeline"]["atActivation"] for x in later)


def test_25_same_inputs_on_another_day_create_no_second_event_and_reading_writes_nothing(tmp_path):
    import alert_engine as ae
    p, reg = _two_sessions(tmp_path), str(tmp_path / "reg" / "alert.sqlite3")
    _gen(p, reg)
    n = len(ae.read(reg)["alerts"])
    again = _gen(p, reg, datetime(2026, 11, 9, 17, 0, tzinfo=ET))
    assert again["created"] is False and len(ae.read(reg)["alerts"]) == n
    with app_env.record_writes() as seen:
        ae.read(reg)
    assert seen == []


def test_26_excluded_late_record_never_reaches_the_alerts_or_the_brief(tmp_path, monkeypatch):
    import alert_engine as ae
    import daily_brief
    import diary_exclusions as dx
    from tests.test_alerts import run_
    p = _diary(tmp_path)
    for s in ("2026-11-04", "2026-11-05"):
        for t, v in (("runs", "O2.1"), ("val_runs", "V2"), ("dec_runs", "D2")):
            run_(p, t, s, v)
    run_(p, "inv_runs", "2026-11-04", "F1")
    run_(p, "inv_runs", "2026-11-05", "F1", at="2026-11-06T16:00:00-05:00")          # late, excluded below
    _inv(p, "2026-11-04", "AAA", "2026-06-30", "2026-07-30")
    _inv(p, "2026-11-05", "AAA", "2026-09-30", "2026-11-02")
    reg_file = tmp_path / "esclusioni.json"
    reg_file.write_text(json.dumps({"schema": 1, "items": [{"id": "investment:2026-11-05:F1:x", "diary": "investment", "session": "2026-11-05",
                        "version": "F1", "computedAt": "2026-11-06T16:00:00-05:00", "reason": "registrata in ritardo (finta)",
                        "decidedAt": "2026-11-06", "decisionVersion": "test"}]}))
    monkeypatch.setattr(dx, "FILE", str(reg_file))
    monkeypatch.setattr(dx, "_cache", {"mtime": None, "data": None})
    reg = str(tmp_path / "reg" / "alert.sqlite3")
    _gen(p, reg, datetime(2026, 11, 6, 17, 0, tzinfo=ET))
    al = ae.read(reg)
    assert not [x for x in al["alerts"] if x["rule"].startswith("AZ-FOND")]
    b = daily_brief.build(datetime(2026, 11, 6, 17, 0, tzinfo=ET), al, _diaries("2026-11-05"), [], {})
    assert not [e for e in b["events"] if e["rule"].startswith("AZ-FOND")]


# ------------------------------------------------------------------ 6. Riepilogo del giorno (pure, synthetic inputs)

def _diaries(session, missing_in=(), excluded=None, last_closed=None):
    rows = []
    for key, name in (("opportunity", "Opportunità"), ("investment", "Fondamentali"), ("valuation", "Valutazioni"),
                      ("decision", "Decisioni"), ("etf", "Scanner ETF")):
        have = [] if key in missing_in else [session]
        rows.append({"key": key, "name": name, "version": "X", "last": {"session": session if have else "2026-11-04",
                     "computedAt": f"{session}T16:25:00-05:00", "source": "dashboard", "observations": 200},
                     "admissible": {"runs": len(have), "observations": 200 * len(have), "sessions": have},
                     "official": {"runs": len(have) + (1 if excluded == key else 0), "observations": 200 * len(have) + (202 if excluded == key else 0)},
                     "missing": [], "errors": [], "next": "prossima seduta: …",
                     "registryExcluded": [{"id": "x", "session": "2026-11-03", "reason": "registrata in ritardo (finta)", "observations": 202}] if excluded == key else []})
    return {"diaries": rows, "summary": {"lastSession": session}, "eveningJob": "non installato"}


def _alert(i, session="2026-11-05", priority="importante", rule="AZ-D2-STATO", status="nuovo", kind="evento", activation=False, **kw):
    a = {"id": f"A1-{i}", "rule": rule, "title": "Stato D2 cambiato", "scope": "azione", "family": "Decision Desk", "kind": kind,
         "priority": priority, "instrument": f"T{i}", "name": f"T{i} Inc. (finta)", "session": session, "previous": {"stato": "Monitora"},
         "current": {"stato": "Da approfondire"}, "reason": "regola finta", "model": {"name": "D2", "previousSession": "2026-11-04"},
         "sources": [], "limits": ["limite finto"], "link": {"view": "stock", "ticker": f"T{i}"}, "status": status, "active": True,
         "exploratory": False, "extra": {}, "timeline": {"atActivation": activation, "sessions": {"previous": "2026-11-04", "current": session}}}
    a.update(kw)
    return a


def _alerts(items, session="2026-11-05"):
    return {"started": True, "alerts": items, "counts": {"active": len(items)},
            "lastRun": {"at": f"{session}T17:00:00-05:00", "inputs": {"diaries": {"opportunity": {"last": {"session": session}},
                                                                                 "decision": {"last": {"session": session}}}}}}


NOW = datetime(2026, 11, 5, 18, 0, tzinfo=ET)


def test_27_no_change_message_only_when_up_to_date():
    import daily_brief as db
    b = db.build(NOW, _alerts([]), _diaries("2026-11-05"), [], {})
    assert b["upToDate"] and b["complete"] and b["message"] == db.NO_CHANGE and b["events"] == []
    assert b["message"] == "Nessun cambiamento rilevante rilevato nell'ultima seduta elaborata."


def test_28_stale_brief_says_not_updated_and_why_never_no_change():
    import daily_brief as db
    b = db.build(datetime(2026, 11, 6, 18, 0, tzinfo=ET), _alerts([]), _diaries("2026-11-05"), [], {})
    assert not b["upToDate"] and b["message"] == "Riepilogo non aggiornato" and b["message"] != db.NO_CHANGE
    assert any("2026-11-06" in r for r in b["reasons"])
    b = db.build(NOW, {"started": False, "alerts": []}, _diaries("2026-11-05"), [], {})
    assert b["message"] == db.NOT_UPDATED and any("alert" in r for r in b["reasons"])


def test_29_a_missing_diary_never_makes_a_complete_day():
    import daily_brief as db
    b = db.build(NOW, _alerts([]), _diaries("2026-11-05", missing_in=("valuation",)), [], {})
    assert not b["complete"] and b["message"] == db.NOT_UPDATED
    assert any("Valutazioni" in r for r in b["reasons"])
    st = {c["key"]: c["state"] for c in b["diaries"]}
    assert st["valuation"] != "registrata" and st["opportunity"] == "registrata"


def test_30_at_most_seven_important_events_never_filled():
    import daily_brief as db
    many = [_alert(i) for i in range(10)]
    b = db.build(NOW, _alerts(many), _diaries("2026-11-05"), [], {})
    assert len(b["events"]) == 7 and b["alerts"]["more"] == 3 and b["message"] is None
    few = [_alert(1), _alert(2, priority="ordinaria"), _alert(3, priority="ordinaria")]
    b = db.build(NOW, _alerts(few), _diaries("2026-11-05"), [], {})
    assert [e["id"] for e in b["events"]] == ["A1-1"] and b["alerts"]["ordinary"] == 2
    b = db.build(NOW, _alerts([_alert(2, priority="ordinaria")]), _diaries("2026-11-05"), [], {})
    assert b["events"] == [] and b["message"] == db.NO_CHANGE


def test_31_historical_events_at_activation_and_older_sessions_stay_apart():
    import daily_brief as db
    items = [_alert(1, activation=True), _alert(2, session="2026-11-04"), _alert(3, status="persistente"), _alert(4)]
    b = db.build(NOW, _alerts(items), _diaries("2026-11-05"), [], {})
    assert [e["id"] for e in b["events"]] == ["A1-4"]
    assert [e["id"] for e in b["historical"]] == ["A1-1"] and b["alerts"]["historicalAtActivation"] == 1


def test_32_cards_have_every_field_dcf_causes_and_exploratory_etf():
    import daily_brief as db
    dcf = _alert(1, rule="AZ-DCF-SOGLIA", title="Prezzo oltre un valore DCF",
                 extra={"causes": {"prezzo": "100 → 90 (−10%)", "ipotesi e bilanci": "valore base 95 → 95 (0%)"}})
    trend = _alert(2, rule="ETF-TREND", scope="etf", exploratory=True, title="Trend ETF cambiato")
    b = db.build(NOW, _alerts([dcf, trend]), _diaries("2026-11-05"), [], {})
    c = {e["rule"]: e for e in b["events"]}
    for e in c.values():
        for k in ("instrument", "what", "before", "after", "why", "dataDate", "limits", "link"):
            assert k in e and e[k] is not None
    assert c["AZ-DCF-SOGLIA"]["causes"] == {"prezzo": "100 → 90 (−10%)", "ipotesi e bilanci": "valore base 95 → 95 (0%)"}
    assert c["AZ-DCF-SOGLIA"]["section"] == "fondamentali"
    assert c["ETF-TREND"]["exploratory"] and any("esplorativo" in x for x in c["ETF-TREND"]["limits"])


def test_33_data_problems_are_separate_from_financial_events():
    import daily_brief as db
    items = [_alert(1, rule="AZ-DATI", kind="condizione", status="baseline", priority="critica", scope="operativo"), _alert(2)]
    b = db.build(NOW, _alerts(items), _diaries("2026-11-05"), [], {})
    assert [e["id"] for e in b["events"]] == ["A1-2"] and [e["id"] for e in b["dataIssues"]] == ["A1-1"]


def test_34_no_score_no_buy_sell_no_personal_data_in_the_brief():
    import daily_brief as db
    b = db.build(NOW, _alerts([_alert(i) for i in range(3)]), _diaries("2026-11-05"), [], {})
    text = json.dumps({k: v for k, v in b.items() if k != "rules"}, ensure_ascii=False)
    for w in ("Compra", "Vendi", "punteggio", "score", "probabilità", "rendimento atteso", "portafoglio personale"):
        assert w not in text.replace("Non è consulenza", ""), w
    assert "non è consulenza finanziaria" in text.lower()


def test_35_existing_and_admissible_counts_and_excluded_records_are_shown():
    import daily_brief as db
    b = db.build(NOW, _alerts([]), _diaries("2026-11-05", excluded="opportunity"), [], {})
    d = next(x for x in b["health"]["diaries"] if x["name"] == "Opportunità")
    assert d["official"]["observations"] == 402 and d["admissible"]["observations"] == 200
    assert b["health"]["excluded"] and b["health"]["excluded"][0]["session"] == "2026-11-03"


def test_36_health_shows_last_completed_job_errors_and_interrupted_runs():
    import daily_brief as db
    runs = [{"mode": "market-only", "startedAt": "2026-11-04T17:00:00-05:00", "finishedAt": "2026-11-04T17:10:00-05:00",
             "completed": True, "session": "2026-11-04", "steps": [{"name": "bilanci", "outcome": "errore", "error": "Timeout"}], "problems": []},
            {"mode": "market-only", "startedAt": "2026-11-05T17:00:00-05:00", "finishedAt": None, "completed": False, "steps": [], "problems": []}]
    h = db.build(datetime(2026, 11, 5, 23, 0, tzinfo=ET), _alerts([]), _diaries("2026-11-05"), runs,
                 {"prices": "2026-11-05T16:30:00-05:00", "fundamentals": None, "alertCheck": {"at": "x", "msg": "alert: controllo non riuscito (KeyError): nessun cambiamento registrato"}})["health"]
    assert h["lastJobCompleted"]["startedAt"].startswith("2026-11-04") and h["lastJobCompleted"]["stepsWithErrors"] == ["bilanci"]
    assert h["lastJobStarted"]["state"] == "interrotto"
    assert h["fundamentals"] is None and h["prices"].startswith("2026-11-05")
    kinds = " ".join(f"{e['step']} {e.get('error')} {e.get('note')}" for e in h["errors"])
    assert "Timeout" in kinds and "non completato" in kinds and "non riuscito" in kinds
    assert h["openFiles"]["limit"] is None or h["openFiles"]["limit"] >= 256


def test_37_brief_is_deterministic():
    import daily_brief as db
    a = db.build(NOW, _alerts([_alert(1)]), _diaries("2026-11-05"), [], {})
    b = db.build(NOW, _alerts([_alert(1)]), _diaries("2026-11-05"), [], {})
    a["health"].pop("openFiles"), b["health"].pop("openFiles")
    assert a == b


# ------------------------------------------------------------------ 7. the API: read only, no consent, no portfolio

def test_38_api_brief_is_read_only_needs_no_consent_and_never_reads_the_portfolio(market_only, monkeypatch):
    import portfolio
    import server
    monkeypatch.setattr(portfolio, "snapshot", lambda *a, **k: pytest.fail("portfolio read by the brief"))
    monkeypatch.setattr(server, "portfolio_view", lambda *a, **k: pytest.fail("portfolio read by the brief"))
    c = server.app.test_client()
    with app_env.record_writes() as seen:
        r = c.get("/api/brief", headers={"Host": "localhost:8100"})
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    d = r.get_json()
    assert d["message"] in ("Riepilogo non aggiornato", "Nessun cambiamento rilevante rilevato nell'ultima seduta elaborata.") or d["events"]
    assert "health" in d and "disclaimer" in d
    assert seen == [] and app_env.private_blocked() == {}


def test_39_page_has_the_brief_view_and_versions_match():
    import server
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    html = open(os.path.join(ROOT, "static", "index.html")).read()
    assert '["brief", "Riepilogo del giorno"], ["alerts", "Alert e cambiamenti"]' in js
    assert 'id="view-brief"' in html and 'id="briefBody"' in html
    assert f'const PAGE_VERSION = "{server.DASHBOARD_VERSION}"' in js
    assert 'fetch("/api/brief"' in js and "pubblicata oggi" not in js.lower()
    assert 'data-k="br-health"' in js                                 # Stato del sistema closed by default (details)


def test_40_older_alerts_get_the_publication_date_from_the_diary_at_read_time(tmp_path):
    """Alerts recorded by the 8A code carry no publication date: read() takes it from the fundamentals diary (read only)
    and never writes it into the registry."""
    import alert_engine as ae
    p, reg = _two_sessions(tmp_path), str(tmp_path / "reg" / "alert.sqlite3")
    _gen(p, reg)
    con = sqlite3.connect(reg)
    row = con.execute("SELECT alert_id, payload FROM alert_events WHERE rule='AZ-FOND-PERIODO' AND instrument='AAA'").fetchone()
    con.close()
    old = json.loads(row[1])
    old["sources"] = [s for s in old["sources"] if s["name"] != "annuncio del trimestre secondo la fonte"]   # as in 8A
    t = ae.timeline(old, "2026-11-06T09:08:27-05:00", True)
    assert t["published"] is None and t["headline"] == "Nuovi dati acquisiti"
    ann = ae._announced(p, [("2026-11-05", "AAA"), ("2026-11-05", "BBB")])
    assert ann == {("2026-11-05", "AAA"): "2026-11-02"}                       # BBB: the source gives no date
    t = ae.timeline(old, "2026-11-06T09:08:27-05:00", True, ann[("2026-11-05", "AAA")])
    assert t["published"] == "2026-11-02" and "non verificata" in t["headline"]
    before = open(reg, "rb").read()
    with app_env.record_writes() as seen:
        ae.read(reg, diary_path=p)
    assert seen == [] and open(reg, "rb").read() == before


def test_41_a_new_download_of_the_same_statements_is_not_called_new_statements():
    import alert_engine as ae
    same = ae._statements_note({"statements": "2026-11-04T11:42", "latestQuarter": "2026-06-30"},
                               {"statements": "2026-11-05T11:45", "latestQuarter": "2026-06-30"})
    new = ae._statements_note({"statements": "2026-11-04T11:42", "latestQuarter": "2026-06-30"},
                              {"statements": "2026-11-05T07:04", "latestQuarter": "2026-09-30"})
    assert "riscaricati, stesso periodo al 2026-06-30" in same and "aggiornati" not in same
    assert new == " (nuovo periodo di bilancio al 2026-09-30)"
    assert ae._statements_note({"statements": "x", "latestQuarter": "q"}, {"statements": "x", "latestQuarter": "q"}) == ""
