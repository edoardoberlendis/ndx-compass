"""Server health (17 Nov 2026, "Too many open files" after a few days of dashboard): yfinance caches in memory, restart
above the open-files limit, port held by a blocked server, weekly log. Only made-up data and temporary folders."""
import datetime as dt
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time

import pytest

import server_health as sh

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
posix_only = pytest.mark.skipif(os.name != "posix", reason="solo macOS/Linux (/dev/fd, lsof, execv)")


# ---------------------------------------------------------------- 1. the leak

@posix_only
def test_01_many_download_threads_open_no_files():
    """The cause: every new thread of yf.download opened (and never closed) a connection to tkr-tz.db. With the caches
    in memory, 300 short-lived threads that read and write the time zones leave no file open."""
    from yfinance import cache as yc
    sh.install_yf_memory_caches(seed_from_disk=False)
    c = yc.get_tz_cache()
    assert isinstance(c, sh.MemoryTzCache)
    before = sh.open_files()
    for _ in range(10):
        ts = [threading.Thread(target=lambda i=i: (c.store(f"T{i}", "America/New_York"), c.lookup("T0")))
              for i in range(30)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    assert sh.open_files() <= before + 2
    assert c.lookup("T29") == "America/New_York"


def test_02_yfinance_reads_the_memory_cache():
    """yfinance really uses the cache in memory: a stored time zone is returned without any download (the network is
    blocked in the tests, so a request would fail)."""
    import yfinance as yf
    tz = sh.install_yf_memory_caches(seed_from_disk=False)
    tz.store("FAKE1", "America/New_York")
    assert yf.Ticker("FAKE1")._get_ticker_tz(timeout=1) == "America/New_York"


def test_03_cookie_and_isin_caches():
    from yfinance import cache as yc
    sh.install_yf_memory_caches(seed_from_disk=False)
    ck = yc.get_cookie_cache()
    assert ck.lookup("curlCffi") is None
    ck.store("curlCffi", {"x": 1})
    got = ck.lookup("curlCffi")
    assert got["cookie"] == {"x": 1} and got["age"] < dt.timedelta(seconds=5)
    ck.store("curlCffi", None)
    assert ck.lookup("curlCffi") is None
    isin = yc.get_isin_cache()
    isin.store("US0000000001", "FAKE")
    assert isin.lookup("US0000000001") == "FAKE"


def test_04_time_zones_on_disk_are_copied_once(tmp_path):
    import sqlite3
    con = sqlite3.connect(tmp_path / "tkr-tz.db")
    con.execute("CREATE TABLE _tz_kv (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO _tz_kv VALUES ('FAKE2', 'Europe/Rome'), ('FAKE3', NULL)")
    con.commit()
    con.close()
    assert sh._read_disk_tz(str(tmp_path)) == {"FAKE2": "Europe/Rome"}
    assert sh._read_disk_tz(str(tmp_path / "missing")) == {}


def test_05_finished_threads_are_dropped():
    import multitasking
    tasks = multitasking.config["TASKS"]
    done = threading.Thread(target=lambda: None)
    done.start()
    done.join()
    stop = threading.Event()
    running = threading.Thread(target=stop.wait)
    running.start()
    tasks.extend([done, running])
    try:
        sh.prune_finished_tasks()
        assert done not in tasks and running in tasks
    finally:
        stop.set()
        running.join()
        sh.prune_finished_tasks()


# ---------------------------------------------------------------- 2. safety net

def test_06_restart_only_above_the_limit_and_not_at_start():
    assert not sh.should_restart(1999, 2000, uptime=3600)
    assert sh.should_restart(2001, 2000, uptime=3600)
    assert not sh.should_restart(5000, 2000, uptime=60)          # just started: no restart loop


def test_07_check_waits_for_jobs_then_restarts(monkeypatch):
    calls = []
    monkeypatch.setattr(sh, "open_files", lambda: 2500)
    monkeypatch.setattr(sh, "_STARTED", time.time() - 3600)
    monkeypatch.setattr(sh, "restart", lambda log, reason: calls.append(reason))
    busy = iter([True, False])
    monkeypatch.setattr(sh.time, "sleep", lambda s: None)
    sh.check_open_files(None, limit=2000, busy=lambda: next(busy, False))
    assert calls == ["2500 file aperti, oltre la soglia di 2000"]
    calls.clear()
    monkeypatch.setattr(sh, "open_files", lambda: 300)
    assert sh.check_open_files(None, limit=2000) == 300 and calls == []


@posix_only
def test_08_restart_is_the_same_program_without_the_leaked_files(tmp_path):
    """A real restart (os.execv) in a child process: the 60 files left open before are closed after it."""
    script = tmp_path / "prog.py"
    script.write_text(textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {ROOT!r})
        import server_health as sh
        if os.environ.get("NDX_TEST_RESTARTED"):
            print("restarted", sh.open_files(), flush=True)
            sys.exit(0)
        os.environ["NDX_TEST_RESTARTED"] = "1"
        leaked = [open(__file__) for _ in range(60)]
        print("before", sh.open_files(), flush=True)
        sh.restart(None, "test")
    """))
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=60).stdout.split()
    assert out[0] == "before" and out[2] == "restarted"
    assert int(out[3]) < int(out[1]) - 50


# ---------------------------------------------------------------- 3. port held by a blocked server

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start(tmp_path, name, port, answers):
    """A made-up program called `name` that listens on `port`: it answers HTTP or never reads the requests (blocked)."""
    folder = tmp_path / name.replace(".", "_")
    folder.mkdir()
    script = folder / name
    if answers:
        body = f"""
            import http.server
            class H(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
                def log_message(self, *a): pass
            http.server.HTTPServer(("127.0.0.1", {port}), H).serve_forever()
        """
    else:
        body = f"""
            import socket, time
            s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", {port})); s.listen(5)
            time.sleep(300)
        """
    script.write_text(textwrap.dedent(body))
    p = subprocess.Popen([sys.executable, str(script)])
    end = time.time() + 15
    while time.time() < end and not sh._port_busy(port):
        time.sleep(0.1)
    assert sh._port_busy(port)
    return p


@posix_only
def test_09_free_port_nobody_there():
    assert sh.free_port(_free_port()) == "free"


@posix_only
def test_10_blocked_dashboard_server_is_stopped(tmp_path):
    port = _free_port()
    p = _start(tmp_path, "server.py", port, answers=False)
    try:
        assert sh.free_port(port, timeout=1) == "freed"
        assert p.wait(timeout=10) is not None
        assert not sh._port_busy(port)
    finally:
        p.kill()


@posix_only
def test_11_working_server_is_left_alone(tmp_path):
    port = _free_port()
    p = _start(tmp_path, "server.py", port, answers=True)
    try:
        assert sh.free_port(port, timeout=2) == "running"
        assert p.poll() is None
    finally:
        p.kill()
        p.wait()


@posix_only
def test_12_another_program_is_never_stopped(tmp_path):
    port = _free_port()
    p = _start(tmp_path, "altro_programma.py", port, answers=False)
    try:
        assert sh.free_port(port, timeout=1) == "other"
        assert p.poll() is None
    finally:
        p.kill()
        p.wait()


# ---------------------------------------------------------------- 4. weekly log

def test_13_one_log_per_week_last_four_kept(tmp_path):
    log = tmp_path / "server.log"
    stamp = tmp_path / "server.log.week"
    log.write_text("week 47\n")
    stamp.write_text("2026-W47")
    assert sh.rotate_log(str(log), now=dt.datetime(2026, 11, 20, 9)) is None    # same week: nothing to do
    assert log.read_text() == "week 47\n"
    for i, day in enumerate(["2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02"]):
        old = tmp_path / f"server-{day}.log"
        old.write_text("old")
        os.utime(old, (1_700_000_000 + i * 1000,) * 2)
    archive = sh.rotate_log(str(log), now=dt.datetime(2026, 11, 23, 9))          # new week (W48)
    assert os.path.basename(archive) == "server-2026-11-23.log"
    assert open(archive).read() == "week 47\n" and log.read_text() == "" and stamp.read_text() == "2026-W48"
    kept = sorted(p.name for p in tmp_path.glob("server-*.log"))
    assert kept == ["server-2026-10-19.log", "server-2026-10-26.log", "server-2026-11-02.log", "server-2026-11-23.log"]


def test_14_first_rotation_of_an_old_log_without_week(tmp_path):
    """The 8 MB log of today has no week written yet: it is archived at the first start."""
    log = tmp_path / "server.log"
    log.write_text("x" * 1000)
    assert sh.rotate_log(str(log), now=dt.datetime(2026, 11, 17, 9)) is not None
    assert log.read_text() == "" and (tmp_path / "server.log.week").read_text() == "2026-W47"
    empty = tmp_path / "vuoto" / "server.log"
    empty.parent.mkdir()
    assert sh.rotate_log(str(empty), now=dt.datetime(2026, 11, 17, 9)) is None   # nothing to archive


@posix_only
def test_15_output_of_the_server_follows_the_new_file(tmp_path):
    """Started as the .app does (`>> server.log`): after the rotation prints, logs and tracebacks go in the new file."""
    log = tmp_path / "server.log"
    script = tmp_path / "prog.py"
    script.write_text(textwrap.dedent(f"""
        import datetime as dt, logging, sys
        sys.path.insert(0, {ROOT!r})
        import server_health as sh
        logging.basicConfig(level=logging.INFO)
        print("prima", flush=True)
        sh.rotate_log({str(log)!r}, now=dt.datetime(2026, 11, 23, 9), force=True)
        print("dopo", flush=True)
        logging.getLogger("x").warning("avviso dopo")
    """))
    with open(log, "a") as f:
        subprocess.run([sys.executable, str(script)], stdout=f, stderr=f, timeout=60, check=True)
    archive = tmp_path / "server-2026-11-23.log"
    assert "prima" in archive.read_text() and "dopo" not in archive.read_text()
    assert "dopo" in log.read_text() and "avviso dopo" in log.read_text()


# ---------------------------------------------------------------- server.py uses all this

def test_16_server_installs_the_memory_caches_and_health_is_off_when_imported():
    import server
    from yfinance import cache as yc
    assert isinstance(yc.get_tz_cache(), sh.MemoryTzCache)
    assert server.HEALTH == {"restart": False, "log": None}      # tests, preview, job, instance, Windows app
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    assert "health_check()" in src and "server_health.prune_finished_tasks()" in src
