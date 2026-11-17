"""Registro dei giri del job serale (Fase 8B): quando è partito, quando è FINITO, in che modalità e com'è andato ogni passo.

Serve al «Riepilogo del giorno» e allo «Stato del sistema» per dire se l'ultimo giro è stato completato davvero (non
solo avviato). Contiene soltanto nomi dei passi, orari, esito e tipo di errore: mai posizioni, importi, nomi di file del
portafoglio o altri dati personali. File `data/job_status.json` (fuori da Git, come i diari), scritto su un file
temporaneo per processo + os.replace (mai un file a metà), al massimo gli ultimi `KEEP` giri.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(ROOT, "data", "job_status.json")
KEEP = 60
MODES = ("completo", "market-only")


class Run:
    """One run of the evening job. step() records each step; finish() writes the run as completed."""

    def __init__(self, mode, now):
        if mode not in MODES:
            raise ValueError(mode)
        import uuid
        self.data = {"id": uuid.uuid4().hex[:12], "mode": mode, "startedAt": now.isoformat(timespec="seconds"), "finishedAt": None,
                     "completed": False, "steps": [], "problems": []}
        _write(self.data)                                  # started: a run that never finishes stays visible

    def step(self, name, outcome="ok", note=None, error=None):
        s = {"name": name, "outcome": outcome}
        if note:
            s["note"] = str(note)[:300]
        if error is not None:
            s["error"] = error if isinstance(error, str) else type(error).__name__
        self.data["steps"].append(s)

    def problem(self, text):
        self.data["problems"].append(str(text)[:300])

    def finish(self, now, session=None):
        self.data.update(finishedAt=now.isoformat(timespec="seconds"), completed=True, session=session)
        _write(self.data)

    def abort(self, now, error):
        self.data.update(finishedAt=now.isoformat(timespec="seconds"), completed=False,
                         error=type(error).__name__)
        _write(self.data)


def read(path=None):
    """All recorded runs, newest last ([] if the file is missing or unreadable: never an invented run)."""
    try:
        with open(path or FILE, encoding="utf-8") as f:
            runs = json.load(f).get("runs") or []
        return [r for r in runs if isinstance(r, dict)]
    except (OSError, ValueError):
        return []


def last(mode=None, completed=None, path=None):
    for r in reversed(read(path)):
        if (mode is None or r.get("mode") == mode) and (completed is None or bool(r.get("completed")) == completed):
            return r
    return None


def _write(run):
    """Read-modify-write under an exclusive lock (dashboard and job may write at the same time), then atomic replace."""
    import threading
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    with open(FILE + ".lock", "a") as lk:
        _lock_file(lk)
        try:
            runs = read()
            runs = [r for r in runs if r.get("id") != run["id"]]
            runs.append(dict(run))
            runs = runs[-KEEP:]
            tmp = f"{FILE}.{os.getpid()}.{threading.get_ident()}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"schema": 1, "runs": runs}, f, ensure_ascii=False, indent=1)
                os.replace(tmp, FILE)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        finally:
            _unlock_file(lk)


def _lock_file(f):
    """Exclusive lock of the lock file: fcntl on macOS (unchanged), msvcrt on Windows (phase 9B, the portable app)."""
    try:
        import fcntl
    except ImportError:                                      # Windows: lock the first byte, waiting until it is free
        _lock_windows(f)
        return
    fcntl.flock(f, fcntl.LOCK_EX)


LOCK_WAIT_S = 120           # Windows only: longest wait for the lock before a clear error (never skipped)


def _lock_windows(f, wait_s=None, pause_s=0.02):
    """msvcrt.LK_LOCK gives up after 10 tries one second apart (OSError 36 "Resource deadlock avoided"): with several
    writers one of them can wait longer than that (the first Windows test, 12 writers). Here: non-blocking tries every
    20 ms until the lock is free, up to LOCK_WAIT_S; then TimeoutError. The lock is the same: one writer at a time."""
    import msvcrt
    deadline = time.monotonic() + (LOCK_WAIT_S if wait_s is None else wait_s)
    while True:
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"registro dei giri occupato da più di {LOCK_WAIT_S if wait_s is None else wait_s} s")
            time.sleep(pause_s)


def _unlock_file(f):
    try:
        import fcntl
    except ImportError:
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(f, fcntl.LOCK_UN)


def stale(run, now):
    """A run started more than 3 hours ago and never finished: interrupted (Mac asleep or switched off, crash)."""
    if not run or run.get("completed") or run.get("finishedAt"):
        return False
    try:
        return (now - datetime.fromisoformat(run["startedAt"])).total_seconds() > 3 * 3600
    except (KeyError, ValueError, TypeError):
        return False
