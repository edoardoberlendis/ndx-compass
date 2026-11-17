"""Accesso a un'istanza separata (Fase 9A): password, sessioni e protezione CSRF, applicati dal backend.

Solo per le istanze avviate con instance.py (la dashboard personale sulla 8100 non lo usa e resta com'era).

- Password: mai salvata in chiaro. Nel file `accesso.json` della cartella privata dell'istanza (permessi 600) c'è solo
  l'impronta scrypt (libreria standard di Python) con il suo sale casuale.
- Sessione: un identificativo casuale di 32 byte nel cookie `ndx_sessione` (HttpOnly, Secure, SameSite=Strict), tenuto
  solo in memoria: riavviare l'istanza chiude tutte le sessioni. Scade dopo IDLE_S senza uso e comunque dopo MAX_S.
- CSRF: ogni sessione ha un suo token casuale, scritto nella pagina (meta `ndx-csrf`) e richiesto nell'intestazione
  X-CSRF-Token di ogni richiesta che modifica qualcosa, insieme a un'Origin ammessa. Né CORS, né un'intestazione fissa,
  né il solo `consent: true` bastano.
- Tentativi sbagliati: dopo MAX_FAILS errori in FAIL_WINDOW_S l'accesso si blocca per LOCK_S (per tutti: dietro
  Tailscale Serve le richieste arrivano tutte da 127.0.0.1).
Nessun dato personale nei messaggi o nei log: solo l'esito."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time

COOKIE = "ndx_sessione"
IDLE_S = 14 * 86400            # a session unused for 14 days ends
MAX_S = 30 * 86400             # and every session ends after 30 days anyway
MAX_FAILS = 5
FAIL_WINDOW_S = 15 * 60
LOCK_S = 15 * 60
MIN_PASSWORD = 10
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
_MAXMEM = 64 * 1024 * 1024


def hash_password(password, salt=None, params=None):
    """{"algo", "salt", "hash", "n", "r", "p"} for a password (scrypt, random 16-byte salt)."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise ValueError(f"la password deve avere almeno {MIN_PASSWORD} caratteri")
    prm = dict(params or SCRYPT)
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=prm["n"], r=prm["r"], p=prm["p"], maxmem=_MAXMEM, dklen=32)
    return {"algo": "scrypt", "salt": salt.hex(), "hash": h.hex(), **prm}


def verify_password(password, record):
    """True when `password` matches the stored record (constant-time comparison)."""
    if not isinstance(password, str) or not isinstance(record, dict) or record.get("algo") != "scrypt":
        return False
    try:
        h = hashlib.scrypt(password.encode(), salt=bytes.fromhex(record["salt"]), n=int(record["n"]), r=int(record["r"]),
                           p=int(record["p"]), maxmem=_MAXMEM, dklen=32)
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(h.hex(), str(record.get("hash", "")))


def save_password(path, password):
    """Writes the password record in `path` (permissions 600, atomic)."""
    rec = hash_password(password)
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(rec, f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    os.chmod(path, 0o600)


def load_password(path):
    try:
        with open(path) as f:
            rec = json.load(f)
        return rec if isinstance(rec, dict) and rec.get("algo") == "scrypt" else None
    except (OSError, ValueError):
        return None


class Sessions:
    """Sessions in memory: {id: {"csrf", "created", "seen"}}. A clock can be passed for the tests."""

    def __init__(self, clock=time.time):
        self._s = {}
        self._fails = []
        self._locked_until = 0.0
        self._lock = threading.Lock()
        self.clock = clock

    # -- tentativi
    def locked(self):
        return self.clock() < self._locked_until

    def lock_remaining(self):
        return max(0, int(self._locked_until - self.clock()))

    def failed(self):
        now = self.clock()
        with self._lock:
            self._fails = [t for t in self._fails if now - t < FAIL_WINDOW_S] + [now]
            if len(self._fails) >= MAX_FAILS:
                self._locked_until = now + LOCK_S
                self._fails = []

    # -- sessioni
    def create(self):
        sid, now = secrets.token_urlsafe(32), self.clock()
        with self._lock:
            self._fails = []
            self._s[sid] = {"csrf": secrets.token_urlsafe(32), "created": now, "seen": now}
        return sid

    def get(self, sid):
        """The live session for this id (and its last use updated), or None."""
        if not isinstance(sid, str) or not sid:
            return None
        now = self.clock()
        with self._lock:
            s = self._s.get(sid)
            if s is None:
                return None
            if now - s["seen"] > IDLE_S or now - s["created"] > MAX_S:
                del self._s[sid]
                return None
            s["seen"] = now
            return s

    def end(self, sid):
        with self._lock:
            self._s.pop(sid, None)

    def end_all(self):
        with self._lock:
            self._s.clear()

    def count(self):
        return len(self._s)


def csrf_ok(session, header_value):
    return bool(session) and isinstance(header_value, str) and hmac.compare_digest(session["csrf"], header_value)


def origin_ok(origin, allowed):
    """The browser's Origin must be exactly one of the dashboard's own addresses. A request that changes something
    without an Origin is refused (Chrome and Edge always send it with fetch POST)."""
    return isinstance(origin, str) and origin in allowed


class OneTimeKeys:
    """Keys that open the portable app's dashboard (phase 9B): the program makes one each time it opens the browser on
    /avvio?k=<key>. A key works once and only for KEY_S seconds: a link copied from the browser history is useless."""
    KEY_S = 120

    def __init__(self, clock=time.time):
        self._clock = clock
        self._keys = {}
        self._lock = threading.Lock()

    def make(self):
        k = secrets.token_urlsafe(32)
        with self._lock:
            now = self._clock()
            self._keys = {x: t for x, t in self._keys.items() if now - t < self.KEY_S}
            self._keys[k] = now
        return k

    def use(self, key):
        if not key or not isinstance(key, str):
            return False
        with self._lock:
            now = self._clock()
            for k in list(self._keys):
                if hmac.compare_digest(k, key):
                    t = self._keys.pop(k)
                    return now - t < self.KEY_S
        return False
