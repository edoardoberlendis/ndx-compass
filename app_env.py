"""Ambienti di esecuzione (Fase 6C): produzione, test e anteprima, con una protezione esplicita dei dati reali.

Perché esiste: il 4 novembre 2026 uno script di prova lanciato a mano nella cartella del progetto ha importato
server.py e chiamato save_etf_scan_diary(source="prova"): nessun controllo sapeva che quello non era il server, quindi la
registrazione è finita nel diario reale (data/opportunita.sqlite3). Da qui tre regole:

1. L'ambiente si dichiara e si verifica: `NDX_ENV` = produzione (predefinito), test o anteprima. Se pytest è caricato
   l'ambiente è SEMPRE "test", qualunque cosa dica la variabile (non ci si affida a una convenzione).
2. In produzione i diari SQLite si scrivono solo da un processo autorizzato (`authorize`): il server avviato con
   `python server.py`, il job serale, il comando manuale `opportunity_diary.py update`. Uno script o una console che
   importa server.py senza autorizzazione può leggere, ma ogni scrittura in un diario di produzione viene rifiutata.
   In produzione l'origine di una registrazione deve essere una di OFFICIAL_SOURCES.
3. In test e anteprima una guardia (audit hook di Python, `install_guard`) blocca PRIMA che avvenga ogni scrittura nella
   cartella del progetto (file, cartelle, rinomine, cancellazioni, database SQLite non in sola lettura): i dati vanno in
   cartelle temporanee (`isolate`). In test sono bloccate anche le connessioni di rete non locali.

La classificazione delle registrazioni già salvate deriva dall'origine (colonna `source`, mai modificata): solo
OFFICIAL_SOURCES contano nelle statistiche ufficiali; "prova", "test", "anteprima" e ogni altra origine restano
consultabili ma escluse (`classify`)."""
from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
import threading

ROOT = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
ENVS = ("produzione", "test", "anteprima")
ALIASES = {"production": "produzione", "prod": "produzione", "preview": "anteprima", "testing": "test"}
OFFICIAL_SOURCES = ("dashboard", "job serale", "comando manuale")
WRITE_EVENTS = ("open", "sqlite3.connect", "os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.truncate", "shutil.rmtree",
                "shutil.copyfile", "os.symlink", "os.link", "os.chmod")
ALLOWED_PARTS = ("__pycache__", ".pytest_cache")      # Python bytecode and pytest's own cache, never data
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


class ProductionWriteBlocked(PermissionError):
    """A write to production data from a process that may not do it. Subclass of OSError on purpose: code that already
    handles a failed write (and logs it) keeps working, and nothing is written."""


_state = {"authorized": None, "guard": None, "hook": False, "extra": [], "watch": None}
_lock = threading.Lock()


# ---------------------------------------------------------------- environment

def env():
    """'produzione', 'test' or 'anteprima'. pytest loaded = test, always; an unknown value is treated as 'anteprima'
    (no writes to production): a typo never turns into production."""
    if "pytest" in sys.modules or "_pytest" in sys.modules:
        return "test"
    v = (os.environ.get("NDX_ENV") or "produzione").strip().lower()
    v = ALIASES.get(v, v)
    return v if v in ENVS else "anteprima"


def is_production():
    return env() == "produzione"


def _real(path):
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    return os.path.realpath(os.path.abspath(os.fspath(path)))


def _under(p, root):
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def protected_roots():
    """Folders whose content is production data in this environment: the whole project folder (in test and preview)
    plus any sentinel folder registered by a test (`protect`)."""
    return [ROOT] + list(_state["extra"])


def protect(path):
    """Registers an extra folder as production (used by tests as a sentinel: a fake production folder)."""
    p = _real(path)
    if p not in _state["extra"]:
        _state["extra"].append(p)


def unprotect(path):
    p = _real(path)
    if p in _state["extra"]:
        _state["extra"].remove(p)


def is_protected(path):
    """True when writing `path` would touch production data from a test or a preview."""
    try:
        p = _real(path)
    except (TypeError, ValueError):
        return False
    if any(part in ALLOWED_PARTS for part in p.split(os.sep)):
        return False
    return any(_under(p, r) for r in protected_roots())


def is_production_diary(path):
    """The production diary folder (data/) or a sentinel folder registered by a test."""
    p = _real(path)
    return _under(p, os.path.realpath(DATA)) or any(_under(p, r) for r in _state["extra"])


# ---------------------------------------------------------------- authorization of the production writers

def authorize(who):
    """Called only by the real entry points (server started as a program, evening job, manual update command).
    Refused outside production: a test or a preview can never become a production writer."""
    if not is_production():
        raise ProductionWriteBlocked(f"ambiente «{env()}»: «{who}» non può essere autorizzato a scrivere i diari di produzione")
    with _lock:
        _state["authorized"] = who
    return who


def authorized():
    return _state["authorized"] if is_production() else None


def check_diary_write(path, source=None):
    """Gate of every write connection to a diary database. Returns the origin label to store. Raises
    ProductionWriteBlocked when the write is not allowed:
    - test / preview: never inside a protected folder (the guard would block it anyway: this message is clearer);
    - production, diary in data/: only an authorized process and only an official origin."""
    e = env()
    if e != "produzione":
        if is_protected(path) or is_production_diary(path):
            raise ProductionWriteBlocked(f"ambiente «{e}»: scrittura nel diario di produzione bloccata ({path})")
        return "anteprima" if e == "anteprima" else (source or "test")
    if is_production_diary(path):
        if not _state["authorized"]:
            raise ProductionWriteBlocked("scrittura nel diario di produzione non autorizzata: solo il server avviato con "
                                         "server.py, il job serale o il comando manuale possono registrare")
        if source is not None and source not in OFFICIAL_SOURCES:
            raise ProductionWriteBlocked(f"origine «{source}» non ammessa nel diario di produzione "
                                         f"(ammesse: {', '.join(OFFICIAL_SOURCES)})")
    return source


# ---------------------------------------------------------------- classification of what is already recorded

def classify(source):
    """produzione / prova / anteprima / esclusa, from the origin stored with the record (never modified)."""
    if source in OFFICIAL_SOURCES:
        return "produzione"
    if source in ("prova", "test"):
        return "prova"
    if source == "anteprima":
        return "anteprima"
    return "esclusa"


def official_sql(col="source"):
    """SQL condition that keeps only the official records."""
    return f"{col} IN (" + ",".join("'" + s.replace("'", "''") + "'" for s in OFFICIAL_SOURCES) + ")"


# ---------------------------------------------------------------- guard for tests and previews (audit hook)

def _at(path, dir_fd):
    """A relative path given together with an open directory (dir_fd) is relative to THAT directory, not to the
    current folder: resolve it (macOS F_GETPATH), or give up (None) when it cannot be resolved."""
    if not isinstance(dir_fd, int) or dir_fd < 0 or isinstance(path, int):
        return path
    p = os.fsdecode(path) if isinstance(path, bytes) else str(path)
    if os.path.isabs(p):
        return p
    try:
        import fcntl
        base = fcntl.fcntl(dir_fd, getattr(fcntl, "F_GETPATH", 50), b"\0" * 1024).split(b"\0", 1)[0].decode()
        return os.path.join(base, p) if base else None
    except Exception:
        return None


def _is_write(event, args):
    """(True, path) when the audited operation writes `path`."""
    args = list(args)
    if event in ("os.mkdir",) and len(args) > 2:
        args[0] = _at(args[0], args[2])
    elif event in ("os.remove", "os.rmdir") and len(args) > 1:
        args[0] = _at(args[0], args[1])
    elif event == "os.rename" and len(args) > 3:
        args[1] = _at(args[1], args[3])
    if any(a is None for a in args[:1]) and event != "open":
        return False, None
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        if isinstance(path, int) or path is None:
            return False, None
        if isinstance(mode, str):
            return any(c in mode for c in "wax+"), path
        if isinstance(flags, int):
            return bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC)), path
        return False, path
    if event == "sqlite3.connect":
        db = args[0] if args else None
        if db is None:
            return False, None
        db = os.fsdecode(db) if isinstance(db, bytes) else str(db)
        if db in ("", ":memory:") or db.startswith("file::memory:"):
            return False, None
        if db.startswith("file:"):
            path, _, query = db[5:].partition("?")
            return "mode=ro" not in query, path
        return True, db
    if event == "os.mkdir":
        p = args[0]
        return (not isinstance(p, int) and not os.path.isdir(p)), p
    if event in ("os.rename", "shutil.copyfile", "os.symlink", "os.link"):
        return True, args[1]
    if event in ("os.remove", "os.rmdir", "os.truncate", "shutil.rmtree", "os.chmod"):
        p = args[0]
        return (not isinstance(p, int)), p
    return False, None


def _hook(event, args):
    g = _state["guard"]
    w = _state["watch"]
    if g is None and w is None:
        return
    if event == "socket.connect" and g == "test":
        addr = args[1] if len(args) > 1 else None
        host = addr[0] if isinstance(addr, tuple) and addr else addr
        if isinstance(host, str) and host not in LOCAL_HOSTS and not host.startswith("/"):
            raise ProductionWriteBlocked(f"ambiente test: connessione di rete verso {host} bloccata")
        return
    if event not in WRITE_EVENTS:
        return
    try:
        write, path = _is_write(event, args)
    except Exception:
        return
    if not write or path is None:
        return
    if w is not None:
        w.append((event, os.fsdecode(path) if isinstance(path, bytes) else str(path)))
    if g is not None and is_protected(path):
        raise ProductionWriteBlocked(f"ambiente «{g}»: scrittura bloccata in un percorso di produzione ({path})")


def install_guard():
    """Turns on the guard for this process (test or preview only; refused in production, where it is not needed).
    Audit hooks cannot be removed: the guard stays on until the process ends."""
    e = env()
    if e == "produzione":
        raise RuntimeError("la guardia è per test e anteprima: in produzione scrivono solo i processi autorizzati")
    with _lock:
        if not _state["hook"]:
            sys.addaudithook(_hook)
            _state["hook"] = True
        _state["guard"] = e
        _state["authorized"] = None
    return e


def guard_active():
    return _state["guard"]


@contextlib.contextmanager
def record_writes():
    """Collects every write attempted inside the block (path and kind), wherever it goes: used by the tests to prove
    that a read-only endpoint writes nothing."""
    with _lock:
        if not _state["hook"]:
            sys.addaudithook(_hook)
            _state["hook"] = True
    seen = []
    prev = _state["watch"]
    _state["watch"] = seen
    try:
        yield seen
    finally:
        _state["watch"] = prev


# ---------------------------------------------------------------- isolation of the private and production paths

def isolate(base, setter=setattr, public_reads=False):
    """Points every module that writes personal data, diaries, reports or caches to folders inside `base` (one list for
    tests and preview). public_reads=True (preview) keeps the PUBLIC market caches on the real files, read only (the
    guard blocks writes): the page then shows real public data, never personal data."""
    import actions
    import diary
    import etf_buy
    import etf_holdings
    import fundamentals
    import history
    import market_data_quality
    import opportunity_diary
    import opportunity_strategies
    import opportunity_validation
    import pillars
    import portfolio
    import pos_diary
    import rules
    import stop_auto
    import etf_prices
    j = lambda *p: os.path.join(str(base), *p)
    pf = j("portafoglio")
    setter(portfolio, "PORTFOLIO_DIR", pf)
    setter(portfolio, "OVERRIDES", os.path.join(pf, "ticker.json"))
    setter(portfolio, "CLASS_FILE", os.path.join(pf, "classificazione.json"))
    setter(actions, "FISCAL", j("fiscale.json"))
    setter(pos_diary, "DIR", j("diario_posizioni"))
    setter(pillars, "FILE", j("dati_titoli.json"))
    setter(pillars, "LOG", j("pagella.json"))
    setter(stop_auto, "FILE", j("stop_auto.json"))
    setter(rules, "FILE", j("regole.json"))
    setter(history, "DIR", j("storico"))
    setter(history, "FLOWS", j("storico", "flussi.json"))
    setter(diary, "DIR", j("diario"))
    setter(diary, "EXCLUDED", j("diario", "esclusi.json"))
    setter(etf_buy, "DIR", j("diario_etf"))
    setter(etf_holdings, "PRIVATE", j("etf_composizioni.json"))
    setter(opportunity_diary, "DB", j("data", "opportunita.sqlite3"))
    setter(opportunity_validation, "OUT_DIR", j("validazione"))
    setter(opportunity_validation, "LOG", j("validazione", "esperimenti.jsonl"))
    setter(opportunity_validation, "RECHECK_DIR", j("validazione", "rielaborazioni"))
    setter(opportunity_validation, "DIARY", j("data", "opportunita.sqlite3"))
    setter(market_data_quality, "OUT_DIR", j("validazione", "qualita"))
    setter(opportunity_strategies, "OUT_DIR", j("strategie"))
    if not public_reads:
        setter(etf_holdings, "PUBLIC", j("etf_holdings.json"))
        setter(fundamentals, "CACHE", j("cache", "fundamentals.json"))
        setter(etf_prices, "CACHE", j("cache", "etf_prices.pkl"))
    return str(base)


def copy_diary(src, dst):
    """Read-only copy of a diary database (SQLite backup from a read-only connection): the preview shows the real state
    of the diaries while writing only to its own copy."""
    if not os.path.exists(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        s.close()
        d.close()
    return True


def describe():
    return {"env": env(), "authorized": authorized(), "guard": guard_active(), "root": ROOT,
            "officialSources": list(OFFICIAL_SOURCES)}
