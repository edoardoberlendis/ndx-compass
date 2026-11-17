"""Health of the long-running dashboard server (fix of 17 Nov 2026: "Too many open files" after a few days).

Cause: yfinance keeps three small SQLite caches (time zones `tkr-tz.db`, cookies `cookies.db`, ISIN `isin-tkr.db`)
through peewee, which opens one connection PER THREAD. `yf.download` starts a brand new thread for every ticker
(library `multitasking`): ~111 new threads at each intraday refresh, every minute. Each thread opened its own
connection to `tkr-tz.db` (plus its `-wal` file) and nobody ever closed it, also after the thread ended: 2 files lost per
ticker downloaded, until the limit of 4096 open files (seen: 2026 copies of tkr-tz.db in a process alive for 7 days).

What this module does:
1. `install_yf_memory_caches` replaces those three caches with dictionaries in memory (same answers, no file, no
   connection): the time zones already on disk are copied once at start with a single read-only connection, closed
   at once. `prune_finished_tasks` empties the list where `multitasking` keeps every finished thread forever.
2. `open_files` / `should_restart` / `restart`: safety net. Above FD_RESTART_LIMIT open files the server writes it in
   the log and restarts itself (same command, same process id, same log): never again a server blocked for days.
3. `free_port`: at start, if the port is held by an old dashboard server that does not answer, it is stopped
   (SIGTERM, then SIGKILL) so the new one can start; a server that answers is left alone; another program is never
   touched.
4. `rotate_log`: cache/server.log becomes one file per week, the last LOG_KEEP_WEEKS kept (server-YYYY-MM-DD.log).

Only the Mac path (`python server.py`, run.sh and the .app) uses 2-4; the Windows app has its own rotating logs and
ports (desktop_app.py). Nothing here reads portafoglio/ or downloads anything.
"""
from __future__ import annotations

import datetime as _dt
import glob
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

FD_RESTART_LIMIT = 2000      # open files above which the server restarts itself (the macOS limit set by server.py is 4096)
MIN_UPTIME_S = 10 * 60       # never restart a server younger than this (no restart loops)
LOG_KEEP_WEEKS = 4           # weekly archives of cache/server.log kept
_STARTED = time.time()


# ---------------------------------------------------------------- 1. yfinance caches in memory

class MemoryTzCache:
    """Same interface as yfinance's _TzCache (lookup/store), in a dictionary protected by a lock."""

    def __init__(self, seed=None):
        self._d = dict(seed or {})
        self._lock = threading.Lock()

    def lookup(self, key):
        with self._lock:
            return self._d.get(key)

    def store(self, key, value):
        with self._lock:
            if value is None:
                self._d.pop(key, None)
            else:
                self._d[key] = value

    @property
    def tz_db(self):
        return None


class MemoryCookieCache:
    """Same interface as yfinance's _CookieCache: lookup(strategy) -> {'cookie', 'age'} or None."""

    def __init__(self):
        self._d = {}
        self._lock = threading.Lock()

    def lookup(self, strategy):
        with self._lock:
            item = self._d.get(strategy)
        if item is None:
            return None
        cookie, fetched = item
        return {"cookie": cookie, "age": _dt.datetime.now() - fetched}

    def store(self, strategy, cookie):
        with self._lock:
            if cookie is None:
                self._d.pop(strategy, None)
            else:
                self._d[strategy] = (cookie, _dt.datetime.now())

    @property
    def Cookie_db(self):  # noqa: N802 (name used by yfinance)
        return None


class MemoryIsinCache(MemoryTzCache):
    """Same interface as yfinance's _ISINCache (lookup/store)."""


def _read_disk_tz(cache_dir):
    """Time zones already saved by yfinance, read once with ONE read-only connection closed at once (empty if missing)."""
    import sqlite3
    path = os.path.join(cache_dir or "", "tkr-tz.db")
    if not cache_dir or not os.path.isfile(path):
        return {}
    con = None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        return {k: v for k, v in con.execute("SELECT key, value FROM _tz_kv") if k and v}
    except Exception:
        return {}
    finally:
        if con is not None:
            con.close()


def install_yf_memory_caches(seed_from_disk=True):
    """Replace the SQLite caches of yfinance with the in-memory ones above. Returns the tz cache installed (or None
    when this yfinance has a different layout: then nothing is changed and the safety net of point 2 still works)."""
    try:
        from yfinance import cache as yc
        managers = (yc._TzCacheManager, yc._CookieCacheManager, yc._ISINCacheManager)
        dbs = (yc._TzDBManager, yc._CookieDBManager, yc._ISINDBManager)
    except (ImportError, AttributeError):
        return None
    seed = {}
    if seed_from_disk:
        try:
            seed = _read_disk_tz(yc._TzDBManager.get_location())
        except Exception:
            seed = {}
    tz = MemoryTzCache(seed)
    managers[0]._tz_cache = tz
    managers[1]._Cookie_cache = MemoryCookieCache()
    managers[2]._isin_cache = MemoryIsinCache()
    for db in dbs:                     # a connection opened before (by this thread) is closed now
        try:
            db.close_db()
        except Exception:
            pass
    return tz


def prune_finished_tasks():
    """`multitasking` (used by yf.download) appends every thread it starts to a list and never removes it: drop the
    finished ones (removed one by one, so a thread added meanwhile by another download is never lost). Returns how
    many were removed."""
    try:
        import multitasking
        tasks = multitasking.config["TASKS"]
    except (ImportError, AttributeError, KeyError, TypeError):
        return 0
    removed = 0
    for t in list(tasks):
        if not t.is_alive():
            try:
                tasks.remove(t)
                removed += 1
            except ValueError:
                pass
    return removed


# ---------------------------------------------------------------- 2. open files: safety net

def open_files():
    """Open files of this process (macOS/Linux: entries of /dev/fd); -1 where it cannot be counted (Windows)."""
    for d in ("/dev/fd", "/proc/self/fd"):
        try:
            return len(os.listdir(d))
        except OSError:
            continue
    return -1


def should_restart(count, limit=FD_RESTART_LIMIT, uptime=None):
    """True when the open files are above the limit and the process is not just started."""
    uptime = time.time() - _STARTED if uptime is None else uptime
    return count > limit and uptime >= MIN_UPTIME_S


def restart(log=None, reason=""):
    """Restart this same program in place (os.execv: same process id, same arguments, same log file). Python opens
    files and sockets as non-inheritable, so the leaked files and the listening port are closed by the exec."""
    if log is not None:
        log.warning("RIAVVIO AUTOMATICO del server: %s", reason)
        for h in list(getattr(log, "handlers", [])) + list(logging.getLogger().handlers):
            try:
                h.flush()
            except Exception:
                pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os.execv(sys.executable, [sys.executable] + sys.argv)


def check_open_files(log, limit=FD_RESTART_LIMIT, busy=lambda: False, wait_s=120):
    """Called by the server loop between two refreshes (a safe point). Above the limit: wait up to `wait_s` for the
    background jobs (`busy()`) to end, then restart. Returns the count when no restart happens."""
    n = open_files()
    if not should_restart(n, limit):
        return n
    end = time.time() + wait_s
    while busy() and time.time() < end:
        time.sleep(1)
    restart(log, f"{n} file aperti, oltre la soglia di {limit}")
    return n  # not reached


# ---------------------------------------------------------------- 3. port held by a blocked server

def _answers(port, timeout=5.0):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=timeout) as r:
            return r.status < 500
    except Exception:
        return False


def _port_busy(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def _listener_pids(port):
    try:
        out = subprocess.run(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(x) for x in out.split() if x.isdigit() and int(x) != os.getpid()]


def _command(pid):
    try:
        return subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def free_port(port, log=None, script="server.py", attempts=2, timeout=5.0):
    """Before starting: make sure `port` can be used.
    Returns "free" (nobody there), "running" (a server there answers: leave it, do not start a second one),
    "freed" (a dashboard server that did not answer was stopped) or "other" (held by a program that is not ours, or
    that could not be stopped: never touched)."""
    if not _port_busy(port):
        return "free"
    for _ in range(attempts):                       # a busy server may be slow: ask more than once before deciding
        if _answers(port, timeout):
            return "running"
    pids = _listener_pids(port)
    ours = [p for p in pids if script in _command(p)]
    if not pids or len(ours) != len(pids):
        if log is not None:
            log.error("porta %d occupata da un programma che non è la dashboard (pid %s): non lo fermo", port, pids)
        return "other"
    if log is not None:
        log.warning("porta %d occupata da un server della dashboard che non risponde (pid %s): lo fermo", port, ours)
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        for p in ours:
            try:
                os.kill(p, sig)
            except ProcessLookupError:
                pass
        end = time.time() + wait
        while time.time() < end and any(_alive(p) for p in ours):
            time.sleep(0.2)
        if not any(_alive(p) for p in ours):
            break
    end = time.time() + 5
    while time.time() < end and _port_busy(port):
        time.sleep(0.2)
    return "other" if _port_busy(port) else "freed"


# ---------------------------------------------------------------- 4. weekly log

def _week(now):
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


def _same_file(fd, path):
    try:
        a, b = os.fstat(fd), os.stat(path)
        return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
    except OSError:
        return False


def rotate_log(path, keep=LOG_KEEP_WEEKS, now=None, force=False):
    """One log per week. When the week written in `<path>.week` is not this week (or the file has no week yet and is not
    empty), `path` becomes `server-YYYY-MM-DD.log` (date of the rotation) and a new empty `path` is started; only the
    `keep` most recent archives stay. If stdout/stderr of this process were writing into `path` (the .app starts the
    server with `>> cache/server.log`), they are moved to the new file. Returns the archive created, or None."""
    now = now or _dt.datetime.now()
    week, stamp = _week(now), path + ".week"
    try:
        with open(stamp, encoding="utf-8") as f:
            current = f.read().strip()
    except OSError:
        current = ""
    size = os.path.getsize(path) if os.path.exists(path) else 0
    due = force or (current != week and (current or size > 0))
    archive = None
    if due and size > 0:
        redirect = [fd for fd in (1, 2) if _same_file(fd, path)]
        base = os.path.join(os.path.dirname(path), f"server-{now:%Y-%m-%d}")
        archive, n = base + ".log", 1
        while os.path.exists(archive):
            n += 1
            archive = f"{base}-{n}.log"
        for s in (sys.stdout, sys.stderr):
            try:
                s.flush()
            except Exception:
                pass
        os.replace(path, archive)
        if redirect:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            for target in redirect:
                os.dup2(fd, target)
            os.close(fd)
        else:
            open(path, "a").close()
        old = sorted(glob.glob(os.path.join(os.path.dirname(path), "server-*.log")), key=os.path.getmtime)
        for p in old[:-keep] if keep > 0 else old:
            try:
                os.remove(p)
            except OSError:
                pass
    if current != week:
        with open(stamp, "w", encoding="utf-8") as f:
            f.write(week)
    return archive
