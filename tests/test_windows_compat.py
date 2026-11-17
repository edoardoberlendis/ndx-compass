"""Fase 9B.1: compatibilità con Windows controllata dal Mac.

La prima build su Windows si è fermata perché server.py importava `resource` (esiste solo su macOS/Linux). Questi test
impediscono che succeda di nuovo: (1) nessun modulo dell'app importa un modulo solo Unix fuori da un try/except
ImportError; (2) tutti i moduli dell'app si importano in un processo dove i moduli solo Unix sono resi introvabili, come
su Windows; (3) dove una metrica Unix non esiste la pagina dice «non disponibile», mai un valore inventato.
Non sostituiscono la prova su un PC Windows vero (packaging/build_windows.ps1)."""
import ast
import glob
import hashlib
import json
import os
import subprocess
import sys

import pytest

import app_env

ROOT = app_env.ROOT
sys.path.insert(0, os.path.join(ROOT, "packaging"))
import crea_kit  # noqa: E402,F401
import prepara_pubblici  # noqa: E402

UNIX_ONLY = {"resource", "fcntl", "termios", "pwd", "grp", "tty", "pty", "syslog", "crypt", "readline", "curses", "posix"}


def app_modules():
    """The modules PyInstaller puts in the Windows app (same rule as prepara_pubblici), plus the launcher."""
    mods = sorted(os.path.basename(f)[:-3] for f in glob.glob(os.path.join(ROOT, "*.py")))
    return [m for m in mods if m not in prepara_pubblici.NOT_IN_APP] + ["desktop_app"]


def _guarded(node, parents):
    """True when an import is inside a function or inside a try whose handlers catch ImportError (or broader)."""
    for p in parents:
        if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return True
        if isinstance(p, ast.Try):
            for h in p.handlers:
                names = [h.type] if not isinstance(h.type, ast.Tuple) else list(h.type.elts)
                if h.type is None or any(isinstance(n, ast.Name) and n.id in ("ImportError", "ModuleNotFoundError", "Exception")
                                         for n in names):
                    return True
    return False


def unguarded_unix_imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = []

    def walk(node, parents):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in child.names] if isinstance(child, ast.Import) else [child.module or ""]
                bad = [n for n in names if n.split(".")[0] in UNIX_ONLY]
                if bad and not _guarded(child, parents + [node]):
                    out.append((child.lineno, bad))
            walk(child, parents + [node])
    walk(tree, [])
    return out


def test_01_no_app_module_imports_a_unix_only_module_at_top_level():
    found = {m: unguarded_unix_imports(os.path.join(ROOT, m + ".py")) for m in app_modules()}
    found = {m: v for m, v in found.items() if v}
    assert found == {}, f"import solo Unix senza try/except ImportError (su Windows non esistono): {found}"


def test_02_the_check_catches_the_bug_of_the_first_windows_build(tmp_path):
    """The exact shape that broke the build (server.py line 17) is caught; the fixed shape is accepted."""
    bad = tmp_path / "bad.py"
    bad.write_text("import os\nimport resource\n")
    good = tmp_path / "good.py"
    good.write_text("try:\n    import resource\nexcept ImportError:\n    resource = None\n"
                    "def f():\n    import fcntl\n")
    assert unguarded_unix_imports(str(bad)) == [(2, ["resource"])]
    assert unguarded_unix_imports(str(good)) == []


BLOCKER = """
import sys
UNIX_ONLY = %r
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in UNIX_ONLY - {"posix"}:
            raise ModuleNotFoundError("No module named %%r (come su Windows)" %% name, name=name)
        return None
for m in list(sys.modules):
    if m.split(".")[0] in UNIX_ONLY - {"posix"}:
        del sys.modules[m]
sys.meta_path.insert(0, Block())
"""


def test_03_every_app_module_imports_without_the_unix_only_modules(tmp_path):
    """Like Windows: `resource`, `fcntl`, `termios`, ... cannot be imported. Every module of the app must still import
    (portafoglio/ protected as in the market-only import test: nothing personal is read)."""
    code = (BLOCKER % (UNIX_ONLY,)) + (
        "import importlib, json, os\n"
        f"sys.path.insert(0, {ROOT!r}); os.chdir({ROOT!r})\n"
        "import app_env\n"
        "app_env.enable_market_only()\n"
        "app_env.install_guard()\n"
        f"mods = {app_modules()!r}\n"
        "err = {}\n"
        "for m in mods:\n"
        "    try: importlib.import_module(m)\n"
        "    except Exception as e: err[m] = f'{type(e).__name__}: {e}'\n"
        "import server\n"
        "print(json.dumps({'n': len(mods), 'err': err, 'blocked': app_env.private_blocked(),\n"
        "                  'resource': server.resource is None}))\n")
    env = {**os.environ, "NDX_ENV": "anteprima", "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=240, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr[-2000:]
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["n"] > 40 and r["err"] == {}, r["err"]
    assert r["resource"] is True and r["blocked"] == {}


def test_04_open_files_metric_says_not_available_without_resource(monkeypatch):
    """On Windows the open-files limit does not exist: no number is invented, the page says why."""
    import builtins
    import daily_brief
    real = builtins.__import__

    def no_unix(name, *a, **k):
        if name in ("resource",):
            raise ModuleNotFoundError(name)
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_unix)
    monkeypatch.setattr(daily_brief.os, "listdir", lambda p: (_ for _ in ()).throw(FileNotFoundError(p)) if p == "/dev/fd" else [])
    assert daily_brief.open_files() == (None, None)
    h = daily_brief.health(None, {}, {}, [], {})
    assert h["openFiles"] == {"open": None, "limit": None, "note": daily_brief.OPEN_FILES_NA}
    assert "non disponibile" in daily_brief.OPEN_FILES_NA


@pytest.mark.skipif(sys.platform != "darwin", reason="solo macOS: il limite dei file aperti esiste solo lì")
def test_05_on_macos_the_open_files_limit_is_still_raised():
    """macOS unchanged: the server still raises the soft limit (from 256) and the page shows the number."""
    import resource
    import daily_brief
    import server
    assert server.resource is resource
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    assert soft >= min(4096, hard)
    n, limit = daily_brief.open_files()
    assert limit == soft and n is not None


def test_06_pyinstaller_spec_has_what_windows_needs():
    """The Windows-only parts are picked up by PyInstaller's analysis on Windows: msvcrt/winreg are built into Python
    there; tzdata (no system time zones on Windows), certifi and curl_cffi are collected explicitly; tkinter is listed.
    `resource` must NOT be required: it is only tried."""
    spec = open(os.path.join(ROOT, "packaging", "nasdaq100_monitor.spec"), encoding="utf-8").read()
    for need in ('collect_data_files("tzdata")', "certifi", "curl_cffi", "tkinter"):
        assert need in spec, need
    assert "resource" not in spec
    req = open(os.path.join(ROOT, "packaging", "requirements-windows.txt"), encoding="utf-8").read()
    assert "tzdata==" in req and "resource" not in req.lower().replace("pyinstaller", "")
    mods = [m for m in app_modules() if m != "desktop_app"]          # desktop_app is the entry script itself
    assert "desktop" in mods and "server" in mods and not set(mods) & prepara_pubblici.NOT_IN_APP


def test_07_bundle_check_refuses_a_top_level_missing_module_from_pyinstaller(tmp_path):
    """The PyInstaller warnings of the first build would have shown `resource` imported top-level by server: refused.
    The same module tried in a try (optional) or a missing module of a library is accepted."""
    import verifica_pacchetto as vp
    warn = tmp_path / "warn-nasdaq100_monitor.txt"
    ours = {"server", "desktop", "desktop_app"}
    warn.write_text("This file lists modules PyInstaller was not able to find.\n\n"
                    "missing module named resource - imported by posix (top-level), server (top-level)\n"
                    "missing module named fcntl - imported by job_status (delayed, conditional, optional), subprocess (optional)\n"
                    "missing module named _scproxy - imported by urllib.request (conditional)\n", encoding="utf-8")
    assert vp.missing_top_level(str(warn), ours) == ["modulo mancante su questo sistema: resource (importato da server all'avvio)"]
    warn.write_text("missing module named resource - imported by posix (top-level), server (optional)\n", encoding="utf-8")
    assert vp.missing_top_level(str(warn), ours) == []
    assert vp.missing_top_level(str(tmp_path / "nessuno.txt"), ours)[0].startswith("file degli avvisi")
    ps1 = open(os.path.join(ROOT, "packaging", "build_windows.ps1"), encoding="ascii").read()
    assert '"--avvisi", $Warn' in ps1 and "warn-nasdaq100_monitor.txt" in ps1


# ------------------------------------------------------------------ 9B.1, second Windows run (612 passed, 6 failed)

class FakeMsvcrt:
    """msvcrt.locking as the Windows C runtime does it: a byte locked by another handle refuses LK_NBLCK at once
    (OSError 13) and makes LK_LOCK give up after `tries` tries (OSError 36, "Resource deadlock avoided")."""
    LK_UNLCK, LK_LOCK, LK_NBLCK = 0, 1, 2

    def __init__(self, tries=10, pause=0.01):
        import threading
        self.owner, self.guard, self.tries, self.pause = None, threading.Lock(), tries, pause
        self.holders, self.max_holders = 0, 0

    def locking(self, fd, mode, n):
        import time as _t
        if mode == self.LK_UNLCK:
            with self.guard:
                assert self.owner == fd
                self.owner, self.holders = None, self.holders - 1
            return
        for _ in range(self.tries if mode == self.LK_LOCK else 1):
            with self.guard:
                if self.owner is None:
                    self.owner, self.holders = fd, self.holders + 1
                    self.max_holders = max(self.max_holders, self.holders)
                    return
            if mode == self.LK_NBLCK:
                raise OSError(13, "Permission denied")
            _t.sleep(self.pause)
        raise OSError(36, "Resource deadlock avoided")


@pytest.fixture
def windows_lock(monkeypatch):
    """job_status takes its Windows branch: `import fcntl` fails, msvcrt is the fake above."""
    fake = FakeMsvcrt()
    monkeypatch.setitem(sys.modules, "fcntl", None)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    return fake


def test_08_windows_lock_waits_longer_than_lk_lock_and_never_skips_the_lock(windows_lock, tmp_path):
    """Error 3 of the second Windows run: LK_LOCK gave up (OSError 36) while another writer held the lock. Now the wait
    goes on (still one holder at a time) and ends with a clear TimeoutError, never without the lock."""
    import threading
    import time as _t
    import job_status
    lk = open(tmp_path / "x.lock", "a")
    other = open(tmp_path / "x.lock", "a")
    windows_lock.locking(other.fileno(), windows_lock.LK_LOCK, 1)               # someone else holds it
    with pytest.raises(OSError) as e:                                            # what the old code did: gives up
        windows_lock.locking(lk.fileno(), windows_lock.LK_LOCK, 1)
    assert e.value.errno == 36
    threading.Timer(0.3, lambda: windows_lock.locking(other.fileno(), windows_lock.LK_UNLCK, 1)).start()
    t0 = _t.monotonic()
    job_status._lock_windows(lk)                                                 # waits past the 0.1 s of LK_LOCK
    assert _t.monotonic() - t0 >= 0.25 and windows_lock.owner == lk.fileno()
    with pytest.raises(TimeoutError):                                            # held: a clear error, no write
        job_status._lock_windows(other, wait_s=0.1)
    job_status._unlock_file(lk)
    lk.close(), other.close()


def test_09_job_registry_concurrent_writers_on_the_windows_lock_path(windows_lock, monkeypatch):
    """test_14 of test_market_only, on the Windows branch, with slow writes (antivirus scans the files on Windows):
    every run saved, a valid file, never two writers at once, no temporary file left."""
    import threading
    import time as _t
    import job_status
    from datetime import datetime
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    real_replace = os.replace
    monkeypatch.setattr(job_status.os, "replace", lambda a, b: (_t.sleep(0.01), real_replace(a, b))[1])
    errors = []

    def one(i):
        try:
            r = job_status.Run("market-only", datetime(2026, 11, 5, 17, 0, i, tzinfo=et))
            r.step("prezzi")
            r.finish(datetime(2026, 11, 5, 17, 5, i, tzinfo=et), session="2026-11-05")
        except Exception as e:                       # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=one, args=(i,)) for i in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors and windows_lock.max_holders == 1
    runs = job_status.read()
    assert len(runs) == 12 and all(r["completed"] for r in runs)
    assert not [f for f in os.listdir(os.path.dirname(job_status.FILE)) if f.endswith(".tmp")]


def test_10_macos_keeps_the_fcntl_lock():
    """macOS unchanged: fcntl.flock, exclusive, released after the write (the Windows branch is only the except)."""
    src = open(os.path.join(ROOT, "job_status.py"), encoding="utf-8").read()
    assert "fcntl.flock(f, fcntl.LOCK_EX)" in src and "fcntl.flock(f, fcntl.LOCK_UN)" in src
    if sys.platform == "darwin":
        import fcntl
        import job_status
        os.makedirs(os.path.dirname(job_status.FILE), exist_ok=True)
        with open(job_status.FILE + ".lock", "a") as a, open(job_status.FILE + ".lock", "a") as b:
            job_status._lock_file(a)
            with pytest.raises(BlockingIOError):                     # a second holder is refused while held
                fcntl.flock(b, fcntl.LOCK_EX | fcntl.LOCK_NB)
            job_status._unlock_file(a)
            fcntl.flock(b, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(b, fcntl.LOCK_UN)


def test_11_tests_close_their_sqlite_connections():
    """Errors 4-5: `with sqlite3.connect (...) as con` commits but does NOT close; Windows then refuses to delete the
    database (WinError 32). The app code always uses closing(); the tests must too."""
    bad = {}
    for p in glob.glob(os.path.join(ROOT, "tests", "*.py")) + [os.path.join(ROOT, m + ".py") for m in app_modules()]:
        src = open(p, encoding="utf-8").read()
        n = src.count("with sqlite3." + "connect(")          # split: this file must not match itself
        if n:
            bad[os.path.basename(p)] = n
    assert bad == {}, bad


def test_12a_portfolio_memory_left_by_a_test(tmp_path):
    """First half of the pair: leaves a synthetic portfolio in memory, as test_desktop.py did."""
    import portfolio
    portfolio._state.update(path=str(tmp_path / "finto.xls"), positions=[{"name": "TITOLO FINTO"}])
    portfolio._upload["token"] = "finto"


def test_12b_every_test_starts_with_an_empty_portfolio_memory():
    """Error 6: the next test sees the memory of a new process (conftest), whatever ran before."""
    import portfolio
    assert portfolio._state["path"] is None and portfolio._state["positions"] == [] and portfolio._upload["token"] is None


def test_13_snapshot_never_shows_a_portfolio_of_another_folder(tmp_path):
    """Defence in depth: a portfolio in memory read from a folder that is not the current portfolio folder is never
    shown (in a running dashboard the folder never changes, so nothing changes there). Synthetic data only."""
    import portfolio
    other = tmp_path / "altra_cartella"
    other.mkdir()
    portfolio._state.update(path=str(other / "export.xls"), mtime=1.0, positions=[])
    assert portfolio.snapshot({"stocks": []}, {}) == {"file": None}
    portfolio._state.update(path=os.path.join(portfolio.PORTFOLIO_DIR, "export.xls"))
    assert portfolio.snapshot({"stocks": []}, {}).get("file")


def test_14_javascript_check_without_node_uses_the_mac_fingerprint(tmp_path):
    """Errors 1-2: `node` does not exist on the Windows PC. Without Node.js the syntax check is not skipped: app.js must
    be identical to the file approved by node on the Mac; a missing or different fingerprint fails."""
    import jscheck
    rec = tmp_path / "js_verificato.json"
    assert jscheck.check_app_js(node="", record=str(rec))[0] is False                       # nothing: fails
    rec.write_text(json.dumps({"files": {"static/app.js": "0" * 64}, "node": "v0", "at": "x"}), encoding="utf-8")
    ok, how = jscheck.check_app_js(node="", record=str(rec))
    assert ok is False and "diverso" in how                                                 # another file: fails
    rec.write_text(json.dumps({"files": {"static/app.js": jscheck.sha256(jscheck.APP_JS)}, "node": "v24", "at": "x"}),
                   encoding="utf-8")
    ok, how = jscheck.check_app_js(node="", record=str(rec))
    assert ok is True and "identico" in how
    ps1 = open(os.path.join(ROOT, "packaging", "build_windows.ps1"), encoding="ascii").read()
    assert "Get-Command node" in ps1 and "js_verificato.json" in ps1


@pytest.mark.skipif(not (__import__("shutil").which("node") and os.path.isdir(os.path.join(ROOT, ".git"))),
                    reason="il kit si crea solo dal progetto sul Mac (servono Node.js e Git): nel kit non c'è Git")
def test_15_the_kit_carries_the_fingerprint_of_the_node_checked_app_js(tmp_path):
    import zipfile
    import crea_kit
    import jscheck
    dest = tmp_path / "kit.zip"
    crea_kit.build(str(dest))
    with zipfile.ZipFile(dest) as z:
        rec = json.loads(z.read("Nasdaq100/packaging/js_verificato.json"))
        assert rec["files"]["static/app.js"] == hashlib.sha256(z.read("Nasdaq100/static/app.js")).hexdigest()
    assert rec["files"]["static/app.js"] == jscheck.sha256(jscheck.APP_JS) and rec["node"].startswith("v")
    with zipfile.ZipFile(dest) as z:                   # test 25 without git: engines identical to HEAD, by fingerprint
        eng = json.loads(z.read("Nasdaq100/packaging/motori_verificati.json"))["files"]
        assert "portfolio_fit.py" in eng and "opportunity_scanner.py" in eng
        assert all(hashlib.sha256(z.read("Nasdaq100/" + f)).hexdigest() == h for f, h in eng.items())
