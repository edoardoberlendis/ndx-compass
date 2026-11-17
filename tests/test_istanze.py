"""Fase 9A: istanze separate (instance.py) - isolamento tra due utenti INVENTATI, A e B.

Solo dati finti e cartelle temporanee: mai i file di portafoglio/ né watchlist.json reali (la guardia dei test e la
modalità istanza li rendono comunque illeggibili). Un vero processo per utente non condivide memoria; qui un solo processo
fa A e poi B, e tra i due azzera lo stato in memoria come farebbe un processo nuovo (`become`). La separazione su disco,
i permessi delle API e i blocchi del backend sono quelli reali. In fondo, test in processi separati per la guardia."""
import json
import logging
import os
import re
import subprocess
import sys
import tarfile
import threading
import time

import pytest

import app_env
import instance
import instance_auth as ia
import portfolio

ROOT = app_env.ROOT
# Phase 9B.1: the separate instances are a Mac feature, but these tests check protections of the shared server code
# (separation, CSRF, Origin, paths, uploads, logs): they run on Windows too. Only two checks depend on Unix and are
# conditioned in place, with the reason: symbolic links (Windows needs a privilege to create them: without it the
# attack cannot be prepared either) and the 0o600 mode of the backup (Windows has ACLs, not Unix modes).
WINDOWS = os.name == "nt"


def can_symlink(tmp):
    """True when this system lets an ordinary user create a symbolic link (always on macOS; on Windows only with
    Developer Mode or the privilege)."""
    if not WINDOWS:
        return True
    try:
        os.symlink(os.path.join(tmp, "x"), os.path.join(tmp, "prova-link"))
        os.remove(os.path.join(tmp, "prova-link"))
        return True
    except OSError:
        return False
PW = {"A": "password-di-A-123", "B": "password-di-B-456"}
PORT = {"A": 8110, "B": 8111}
HOST = {"A": "mac-a.tail0000.ts.net", "B": "mac-b.tail0000.ts.net"}
LOGIN = {"A": "utente-a@example.com", "B": "utente-b@example.com"}

# ------------------------------------------------------------------ synthetic users
# name, isin, symbol, market, kind, currency, qty, price, ticker
POS = {
    "A": [("ALFA UNO SPA", "US00000AAA01", "AAA.O", "O", "Azioni", "USD", 10, 100.0, "AAA"),
          ("ALFA DUE SPA", "US00000AAB02", "AAB.O", "O", "Azioni", "USD", 7, 50.0, "AAB"),
          ("ALFA TRE SPA", "US00000AAC03", "AAC.O", "O", "Azioni", "USD", 3, 300.0, "AAC"),
          ("ETF ALFA MONDO", "IE00AAAETF01", "AWLD.MI", "MI", "ETF", "EUR", 40, 90.0, "AWLD.MI"),
          ("ETF ALFA EUROPA", "IE00AAAETF02", "AEUR.MI", "MI", "ETF", "EUR", 25, 45.0, "AEUR.MI")],
    "B": [("BETA UNO INC", "US00000BBA01", "BBA.O", "O", "Azioni", "USD", 4, 222.0, "BBA"),
          ("BETA DUE INC", "US00000BBB02", "BBB.O", "O", "Azioni", "USD", 9, 33.0, "BBB"),
          ("ETF BETA ASIA", "IE00BBBETF01", "BASI.MI", "MI", "ETF", "EUR", 11, 61.0, "BASI.MI"),
          ("ETF BETA OBBLIG", "IE00BBBETF02", "BBND.MI", "MI", "ETF", "EUR", 13, 101.0, "BBND.MI")],
}
WATCH = {"A": ["AAA", "AAB"], "B": ["BBA", "BBB"]}
FISCAL = {"A": 1111, "B": 2222}
SECRETS = {u: [p[0] for p in POS[u]] + [p[1] for p in POS[u]] + [p[8] for p in POS[u]] + [str(FISCAL[u]) + "."]
           for u in POS}


def export_bytes(rows):
    """A synthetic broker export: the .xls signature + a JSON table (the tests replace only the low-level xls reader)."""
    head = list(portfolio.COLUMNS.values())
    table = [["Portafoglio sintesi"], head]
    for n, i, s, m, k, c, q, pr, _t in rows:
        fx = 1.1 if c == "USD" else 1.0
        vals = {"name": n, "isin": i, "symbol": s, "market": m, "kind": k, "currency": c, "qty": q, "costPrice": pr * 0.9,
                "costFx": fx, "costValue": q * pr * 0.9 / fx, "filePrice": pr, "fileFx": fx, "fileValue": q * pr / fx}
        table.append([vals[k2] for k2 in portfolio.COLUMNS])
    table.append(["Totale"] + [""] * (len(head) - 1))
    return portfolio.XLS_MAGIC + json.dumps(table).encode()


def fake_rows(path):
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(portfolio.XLS_MAGIC):
        raise ValueError("non è un file Excel")
    table = json.loads(data[len(portfolio.XLS_MAGIC):])
    return [r + [""] * (13 - len(r)) for r in table]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Container with two private folders A and B, configured as instance.py crea would do, and a fake market."""
    import earnings
    import server
    cont = tmp_path / "istanze"
    cont.mkdir()
    (cont / app_env.INSTANCE_MARKER).write_text("x")
    dirs = {}
    for u in ("A", "B"):
        d = cont / u
        d.mkdir(mode=0o700)
        (d / instance.CONFIG).write_text(json.dumps({"nome": u, "etichetta": f"Portafoglio {u}", "porta": PORT[u],
                                                     "host_pubblici": [HOST[u]], "tailscale_login": [LOGIN[u]]}))
        ia.save_password(str(d / instance.PASSWORD), PW[u])
        dirs[u] = str(d)
    monkeypatch.setattr(ia, "SCRYPT", {"n": 2 ** 12, "r": 8, "p": 1})            # faster hashes for the tests
    monkeypatch.setattr(portfolio, "_rows", fake_rows)
    monkeypatch.setattr(portfolio, "_fetch_meta", lambda tickers: None)
    monkeypatch.setattr(portfolio, "on_quotes", None)

    def quotes():
        with portfolio._lock:
            portfolio._state.update(quotes={}, fx=1.1, quotesAt=time.time())
    monkeypatch.setattr(portfolio, "refresh_quotes", quotes)
    monkeypatch.setattr(server, "download", lambda *a, **k: {})
    monkeypatch.setattr(server, "news", lambda *a, **k: [])
    monkeypatch.setattr(earnings, "_dates", lambda t: [])
    stocks = [{"ticker": t, "name": f"Pubblica {t}", "sector": "Tecnologia", "weight": 1.0, "price": 10.0, "chgPct": 0.1}
              for t in ("NDXA", "NDXB")]
    monkeypatch.setattr(server.store, "snapshot", {"asOf": "2026-11-09T10:00:00-05:00", "session": "2026-11-09", "status": "open",
                                                   "stocks": stocks, "indices": {}, "breadth": [], "totalMcap": 0})
    monkeypatch.setattr(server.store, "infos", {})
    monkeypatch.setattr(server.store, "daily", {})
    monkeypatch.setattr(server.store, "error", None)
    server.store.ready.set()
    yield {"dirs": dirs, "cont": str(cont)}
    app_env._end_instance_for_tests()
    monkeypatch.setattr(server, "INSTANCE", None)


def become(world, u, monkeypatch):
    """This process becomes the instance of user u: protections on, paths to u's folder, memory as in a new process."""
    import server
    app_env._end_instance_for_tests()
    d = app_env.enable_instance(world["dirs"][u])
    cfg = instance.read_config(d)
    instance.prepare(d, cfg, setter=monkeypatch.setattr)
    with portfolio._lock:
        portfolio._state.update(path=None, mtime=None, positions=[], error=None, resolving=False, quotes={}, fx=None, quotesAt=None)
    portfolio._upload["token"] = None
    return server.app.test_client()


def wait_resolved():
    for _ in range(100):
        if not portfolio._state["resolving"]:
            return
        time.sleep(0.05)
    raise AssertionError("ticker non risolti")


class User:
    """A logged-in browser of user u (local, or through Tailscale Serve with its identity header)."""

    def __init__(self, client, u, remote=False):
        self.c, self.u = client, u
        self.base = f"https://{HOST[u]}" if remote else f"https://localhost:{PORT[u]}"
        self.origin = f"https://{HOST[u]}" if remote else f"http://localhost:{PORT[u]}"
        self.h = {"Tailscale-User-Login": LOGIN[u]} if remote else {}
        r = self.c.post("/accesso", data={"password": PW[u]}, base_url=self.base, headers={**self.h, "Origin": self.origin})
        assert r.status_code == 303, r.data
        page = self.c.get("/", base_url=self.base, headers=self.h).get_data(as_text=True)
        self.csrf = re.search(r'name="ndx-csrf" content="([^"]+)"', page).group(1)

    def get(self, path):
        return self.c.get(path, base_url=self.base, headers=self.h)

    def post(self, path, body=None, raw=None, headers=None):
        h = {**self.h, "Origin": self.origin, "X-CSRF-Token": self.csrf, "X-Requested-With": "ndx-dashboard", **(headers or {})}
        if raw is not None:
            return self.c.post(path, data=raw, base_url=self.base, headers=h)
        return self.c.post(path, json=body if body is not None else {}, base_url=self.base, headers=h)


def setup_user(world, u, monkeypatch, remote=False):
    """Logs in, uploads u's export, sets tickers, Preferiti, zainetto, rules and one classification."""
    c = become(world, u, monkeypatch)
    me = User(c, u, remote)
    for p in POS[u]:                                         # tickers first: the upload then resolves them without Yahoo
        assert me.post("/api/portfolio/ticker", {"isin": p[1], "ticker": p[8]}).status_code == 200
    wait_resolved()
    r = me.post("/api/portfolio/upload", raw=export_bytes(POS[u]),
                headers={"X-Filename": "export.xls", "Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.data
    tok = r.get_json()["token"]
    assert me.post("/api/portfolio/upload/confirm", {"token": tok}).status_code == 200
    wait_resolved()
    assert me.post("/api/watchlist", {"tickers": WATCH[u]}).status_code == 200
    assert me.post("/api/fiscal", {"losses": FISCAL[u], "expiry": "2029-12-31"}).status_code == 200
    assert me.post("/api/rules", {"tradeRisk": 1.0 if u == "A" else 2.0}).status_code == 200
    etf = next(p for p in POS[u] if p[4] == "ETF")
    r = me.post("/api/portfolio/classification", {"isin": etf[1], "fields": {"settore": f"Settore {u}", "paese": f"Paese {u}"}})
    assert r.status_code == 200, r.data
    return me


def outside():
    """Look at the folders as the owner of the Mac does (instance mode off): inside an instance the other user's folder is
    unreadable, so os.walk would silently see nothing."""
    app_env._end_instance_for_tests()


def posix_rel(path, base, sep=os.sep):
    """Path of a file relative to its user folder, always with "/" (phase 9B.1: on Windows relpath gives
    "portafoglio\\portafoglio-....xls" and the checks below on "portafoglio/..." failed although the file was there)."""
    return os.path.relpath(path, base).replace(sep, "/")


def all_files(d):
    return {posix_rel(os.path.join(r, f), d): os.path.getmtime(os.path.join(r, f))
            for r, _, fs in os.walk(d) for f in fs}


def contents(d):
    out = ""
    for r, _, fs in os.walk(d):
        for f in fs:
            with open(os.path.join(r, f), "rb") as fh:
                out += fh.read().decode("utf-8", "replace")
    return out


# ------------------------------------------------------------------ 1-2. each user sees only his own portfolio

def test_01_02_each_user_sees_only_his_own_portfolio(world, monkeypatch):
    for u, other in (("A", "B"), ("B", "A")):
        me = setup_user(world, u, monkeypatch)
        d = me.get("/api/portfolio").get_json()
        assert sorted(p["isin"] for p in d["positions"]) == sorted(p[1] for p in POS[u])
        assert not any(s in json.dumps(d) for s in SECRETS[other])
        assert d["fiscal"]["losses"] == FISCAL[u] and d["rules"]["tradeRisk"] == (1.0 if u == "A" else 2.0)
    outside()
    files = {u: all_files(world["dirs"][u]) for u in "AB"}
    for u in "AB":
        exports = [f for f in files[u] if f.startswith("portafoglio/portafoglio-") and f.endswith(".xls")]
        assert len(exports) == 1, files[u]                       # one Fineco file per user, in HIS portafoglio/ only
        assert {"watchlist.json", "fiscale.json", "regole.json", "portafoglio/ticker.json", "portafoglio/classificazione.json"} <= set(files[u])
        with open(os.path.join(world["dirs"][u], *exports[0].split("/")), "rb") as fh:
            assert fh.read() == export_bytes(POS[u])            # the file saved is exactly u's upload, not the other's
    assert export_bytes(POS["A"]) != export_bytes(POS["B"])     # so the two checks above tell A's file from B's


def test_01b_relative_paths_are_compared_with_forward_slashes():
    """Regression (third Windows run): the Windows separator is normalised, so the checks above mean the same there."""
    import ntpath
    assert posix_rel("/c/u/A/portafoglio/portafoglio-1.xls", "/c/u/A", sep="/") == "portafoglio/portafoglio-1.xls"
    win = ntpath.relpath("C:\\u\\A\\portafoglio\\portafoglio-1.xls", "C:\\u\\A")
    assert win == "portafoglio\\portafoglio-1.xls" and win.replace("\\", "/") == "portafoglio/portafoglio-1.xls"
    assert posix_rel(os.path.join("base", "portafoglio", "x.xls"), "base") == "portafoglio/x.xls"


# ------------------------------------------------------------------ 3-4. B can neither read nor change A, through any API

def test_03_04_b_cannot_read_or_change_a_through_any_api(world, monkeypatch):
    setup_user(world, "A", monkeypatch)
    before = all_files(world["dirs"]["A"])
    a_content = contents(world["dirs"]["A"])
    b = setup_user(world, "B", monkeypatch)
    import server
    hits, statuses = [], {}
    sample = {"ticker": "ZZZ", "rng": "1M", "isin": "IE00ZZZETF09", "key": "IE00ZZZETF09", "rid": "azione:ZZZ:lungo",
              "step": "confirm", "p": "../../A/watchlist.json"}
    for rule in server.app.url_map.iter_rules():
        if rule.endpoint == "static" or "GET" not in rule.methods and "POST" not in rule.methods:
            continue
        path = rule.rule
        for arg in rule.arguments:
            path = re.sub(r"<(?:[a-z]+:)?%s>" % arg, sample.get(arg, "x"), path)
        for method in ("GET", "POST"):
            if method not in rule.methods or path in ("/accesso", "/esci"):
                continue
            r = b.get(path) if method == "GET" else b.post(path, {"consent": True, "source": "mio", "isin": "IE00ZZZETF09",
                                                                  "ticker": "ZZZ", "tickers": ["ZZZ"], "token": "x"})
            statuses[(method, path)] = r.status_code
            body = r.get_data(as_text=True)
            hits += [(method, path, s) for s in SECRETS["A"] if s in body]
    assert hits == [], hits                                         # nothing of A in any answer
    assert len(statuses) > 40
    outside()
    assert all_files(world["dirs"]["A"]) == before and contents(world["dirs"]["A"]) == a_content    # A untouched
    assert b.get("/static/../A/watchlist.json").status_code == 404


# ------------------------------------------------------------------ 5. B's upload does not touch A

def test_05_upload_of_b_leaves_a_untouched(world, monkeypatch):
    setup_user(world, "A", monkeypatch)
    before = all_files(world["dirs"]["A"])
    b = setup_user(world, "B", monkeypatch)
    for name in ("../A/portafoglio/x.xls", "/etc/passwd.xls", "..\\..\\x.xls"):
        r = b.post("/api/portfolio/upload", raw=export_bytes(POS["B"][:1]),
                   headers={"X-Filename": name, "Content-Type": "application/octet-stream"})
        assert r.status_code == 200
        assert b.post("/api/portfolio/upload/confirm", {"token": r.get_json()["token"]}).status_code == 200
    outside()
    assert all_files(world["dirs"]["A"]) == before
    files = os.listdir(os.path.join(world["dirs"]["B"], "portafoglio"))
    assert all(re.fullmatch(r"portafoglio-[0-9_-]+\.xls|ticker\.json|classificazione\.json", f) for f in files), files


# ------------------------------------------------------------------ 6-9. Preferiti, classifications, fiscal data, history

def test_06_09_personal_files_stay_separate(world, monkeypatch):
    import server
    a = setup_user(world, "A", monkeypatch)
    server.save_portfolio_history()
    assert a.get("/api/watchlist").get_json()["tickers"] == WATCH["A"]
    b = setup_user(world, "B", monkeypatch)
    server.save_portfolio_history()
    assert b.get("/api/watchlist").get_json()["tickers"] == WATCH["B"]
    h = b.get("/api/portfolio/history").get_json()
    assert not any(s in json.dumps(h) for s in SECRETS["A"])
    outside()
    for u, other in (("A", "B"), ("B", "A")):
        d = world["dirs"][u]
        with open(os.path.join(d, "watchlist.json")) as f:
            assert json.load(f)["tickers"] == WATCH[u]
        with open(os.path.join(d, "portafoglio", "classificazione.json")) as f:
            cls = json.load(f)
        assert set(cls) == {next(p[1] for p in POS[u] if p[4] == "ETF")} and cls[next(iter(cls))]["settore"] == f"Settore {u}"
        with open(os.path.join(d, "fiscale.json")) as f:
            assert json.load(f)["losses"] == FISCAL[u]
        hist = os.listdir(os.path.join(d, "storico"))
        assert len(hist) == 1 and not any(s in contents(os.path.join(d, "storico")) for s in SECRETS[other])


# ------------------------------------------------------------------ 10-12. risk, Portfolio Fit and simulations

def test_10_12_risk_fit_and_simulation_use_only_the_users_positions(world, monkeypatch):
    import risk
    seen = []
    monkeypatch.setattr(risk, "snapshot", lambda pf: seen.append(sorted(p["isin"] for p in pf.get("positions") or [])) or {"ok": True})
    setup_user(world, "A", monkeypatch)
    b = setup_user(world, "B", monkeypatch)
    assert b.get("/api/portfolio/risk").status_code == 200
    assert seen == [sorted(p[1] for p in POS["B"])]
    r = b.post("/api/portfolio/fit", {"consent": True, "source": "mio", "candidate": "NDXA",
                                      "whatif": {"amount": 500, "funding": "nuova"}})
    assert r.status_code == 200, r.data
    d = r.get_json()
    assert d["available"], d
    assert sorted(p["name"] for p in d["positions"]) == sorted(p[0] for p in POS["B"])
    assert not any(s in json.dumps(d) for s in SECRETS["A"])
    assert d.get("whatif") and "non è un ordine" in json.dumps(d["whatif"], ensure_ascii=False)


# ------------------------------------------------------------------ 13. public endpoints still work

def test_13_public_endpoints_work_in_an_instance(world, monkeypatch):
    b = setup_user(world, "B", monkeypatch)
    for path in ("/api/snapshot", "/api/macro", "/api/brief", "/api/alerts", "/api/diaries/status"):
        r = b.get(path)
        assert r.status_code == 200, (path, r.status_code, r.get_data(as_text=True)[:200])


# ------------------------------------------------------------------ 14. unauthorized requests are refused

def test_14_unauthorized_requests_are_refused(world, monkeypatch):
    import server
    c = become(world, "A", monkeypatch)
    base, origin = f"https://localhost:{PORT['A']}", f"http://localhost:{PORT['A']}"
    assert c.get("/api/portfolio", base_url=base).status_code == 401                         # no session
    assert c.get("/", base_url=base).status_code == 303                                     # to the login page
    assert c.post("/accesso", data={"password": "sbagliata!!"}, base_url=base, headers={"Origin": origin}).status_code == 401
    assert c.post("/accesso", data={"password": PW["A"]}, base_url=base).status_code == 403          # no Origin
    assert c.post("/accesso", data={"password": PW["A"]}, base_url=base, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/portfolio", base_url="https://evil.example").status_code == 403       # foreign Host (DNS rebinding)
    me = User(c, "A")
    ok = {"Origin": me.origin, "X-CSRF-Token": me.csrf, "X-Requested-With": "ndx-dashboard"}
    for bad in ({**ok, "X-CSRF-Token": "x"}, {k: v for k, v in ok.items() if k != "X-CSRF-Token"},
                {k: v for k, v in ok.items() if k != "Origin"}, {**ok, "Origin": "https://evil.example"}):
        assert c.post("/api/fiscal", json={"losses": 5}, base_url=base, headers=bad).status_code == 403
    assert c.post("/api/fiscal", json={"losses": 5}, base_url=base, headers={k: v for k, v in ok.items() if k != "X-Requested-With"}).status_code == 403
    assert c.post("/api/watchlist", data="tickers=", base_url=base, headers={**ok, "Content-Type": "text/plain"}).status_code == 400
    assert c.get("/api/portfolio", base_url=base, headers={"Tailscale-User-Login": LOGIN["B"]}).status_code == 403  # another account
    assert c.open("/api/portfolio", method="PUT", base_url=base).status_code == 405
    # throttling: 5 wrong passwords lock the login, even the right one, for 15 minutes
    server.SESSIONS = ia.Sessions()
    for _ in range(ia.MAX_FAILS):
        c.post("/accesso", data={"password": "sbagliata!!"}, base_url=base, headers={"Origin": origin})
    assert c.post("/accesso", data={"password": PW["A"]}, base_url=base, headers={"Origin": origin}).status_code == 429
    # sessions end: idle, absolute, logout
    clock = [1000.0]
    s = ia.Sessions(clock=lambda: clock[0])
    sid = s.create()
    clock[0] += ia.IDLE_S + 1
    assert s.get(sid) is None


def test_14b_logout_and_remote_access_through_tailscale(world, monkeypatch):
    c = become(world, "A", monkeypatch)
    me = User(c, "A", remote=True)                                     # Host = the Tailscale name, identity header present
    assert me.get("/api/portfolio").status_code == 200
    assert me.post("/esci").status_code == 200
    assert me.get("/api/portfolio").status_code == 401
    page = c.get("/accesso", base_url=me.base, headers=me.h)
    assert page.status_code == 200 and "Portafoglio A" in page.get_data(as_text=True)
    assert page.headers["Cache-Control"] == "no-store" and "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    # no-referrer would make Chrome send «Origin: null» with the login form, which the Origin check rejects
    assert page.headers["Referrer-Policy"] == "same-origin"


# ------------------------------------------------------------------ 15. paths cannot be manipulated

def test_15_paths_and_links_cannot_reach_other_users(world, monkeypatch, tmp_path):
    setup_user(world, "A", monkeypatch)
    b = setup_user(world, "B", monkeypatch)
    a_dir, b_dir = world["dirs"]["A"], world["dirs"]["B"]
    with pytest.raises(app_env.PrivateAccessBlocked):
        open(os.path.join(a_dir, "watchlist.json"))
    with pytest.raises(app_env.PrivateAccessBlocked):
        os.listdir(a_dir)
    with pytest.raises(app_env.PrivateAccessBlocked):
        open(os.path.join(b_dir, "..", "A", "fiscale.json"))
    link = os.path.join(b_dir, "scorciatoia.json")
    with pytest.raises(app_env.PrivateAccessBlocked):                    # B cannot even create a link towards A
        os.symlink(os.path.join(a_dir, "fiscale.json"), link)
    links = can_symlink(str(tmp_path))                                   # blocked above before the OS is even asked
    if links:
        outside()
        os.symlink(os.path.join(a_dir, "fiscale.json"), link)            # a link planted from outside in B's folder
        app_env.enable_instance(b_dir)
        with pytest.raises(app_env.PrivateAccessBlocked):                # still unreadable: the real path is checked
            open(link)
        outside()
        os.remove(link)
        app_env.enable_instance(b_dir)
    for p in (os.path.join(ROOT, "portafoglio", "x"), os.path.join(ROOT, "watchlist.json")):
        assert app_env._denied(app_env._real(p))                         # the owner's data: denied as a whole
    assert app_env.is_protected(os.path.join(ROOT, "cache", "x.json"))  # project folder: read only
    # the private folder itself must be a real folder outside the project, in a marked container
    for bad in (ROOT, os.path.join(ROOT, "portafoglio"), str(tmp_path)):
        with pytest.raises(ValueError):
            app_env.check_instance_dir(bad)
    assert b.post("/api/portfolio/classification", {"isin": "../../x", "fields": {"settore": "x"}}).status_code == 400
    assert b.post("/api/portfolio/ticker", {"isin": "IE00BBBETF01", "ticker": "../../etc"}).status_code == 400
    with pytest.raises(app_env.PrivateAccessBlocked):                    # B cannot make a link to A's folder either
        os.symlink(a_dir, os.path.join(world["cont"], "C"))
    if links:
        outside()
        os.symlink(a_dir, os.path.join(world["cont"], "C"))              # a private folder that is a link: refused at start
        with pytest.raises(ValueError):
            app_env.check_instance_dir(os.path.join(world["cont"], "C"))


# ------------------------------------------------------------------ 16. no personal data in logs or error messages

def test_16_no_personal_data_in_logs_or_errors(world, monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        b = setup_user(world, "B", monkeypatch)
        bad = export_bytes(POS["B"]).replace(b'"US00000BBA01"', b'"SEGRETO-ISIN-123"')
        r = b.post("/api/portfolio/upload", raw=bad, headers={"X-Filename": "export.xls", "Content-Type": "application/octet-stream"})
        assert r.status_code == 400 and "riga 1: codice ISIN non valido" in r.get_json()["error"]
        bad = export_bytes(POS["B"]).replace(b"222.0", b'"NUMERO-SEGRETO"')
        r = b.post("/api/portfolio/upload", raw=bad, headers={"X-Filename": "export.xls", "Content-Type": "application/octet-stream"})
        assert r.status_code == 400 and "NUMERO-SEGRETO" not in r.get_data(as_text=True)
        r = b.post("/api/portfolio/upload", raw=b"#!/bin/sh\nrm -rf /\n", headers={"X-Filename": "x.xls", "Content-Type": "application/octet-stream"})
        assert r.status_code == 400
        b.c.post("/accesso", data={"password": "SEGRETISSIMA-1"}, base_url=b.base, headers={"Origin": b.origin})
    text = caplog.text
    assert not any(s in text for s in SECRETS["B"] + ["SEGRETO-ISIN", "NUMERO-SEGRETO", "SEGRETISSIMA", PW["B"]]), text
    assert not os.path.exists(portfolio.UPLOAD_TMP)                    # a refused file is not kept


# ------------------------------------------------------------------ 17. no write in the public diaries while consulting

def test_17_consultation_writes_nothing_public(world, monkeypatch):
    setup_user(world, "A", monkeypatch)
    b = setup_user(world, "B", monkeypatch)
    with app_env.record_writes() as seen:
        for path in ("/", "/api/snapshot", "/api/portfolio", "/api/watchlist", "/api/macro", "/api/brief", "/api/alerts",
                     "/api/diaries/status", "/api/opportunities", "/api/decisions", "/api/portfolio/history",
                     "/api/portfolio/risk", "/api/etf/catalog", "/api/opportunities/diary"):
            b.get(path)
    outside = [w for w in seen if not w[1].startswith(world["dirs"]["B"]) and "__pycache__" not in w[1]]
    assert outside == [], outside
    import server
    for name in ("save_opportunity_diary", "save_etf_scan_diary", "save_alerts"):
        assert "istanza separata" in getattr(server, name)()               # public writers turned off in an instance


# ------------------------------------------------------------------ 18. administrative access, ports, remote reach

def test_18_no_admin_or_personal_server_reachable():
    src = open(os.path.join(ROOT, "instance.py")).read()
    assert 'host="127.0.0.1"' in src and "0.0.0.0" not in src
    assert "proxy" not in src.lower().replace("never proxied", "")
    for bad in (8100, 8101, 22, 80):
        with pytest.raises(ValueError):
            _cfg_with_port(bad)
    import server
    c = server.app.test_client()                                        # the personal dashboard: no login pages at all
    assert c.get("/accesso", base_url="http://127.0.0.1:8100").status_code == 404
    assert c.post("/esci", base_url="http://127.0.0.1:8100").status_code == 404


def _cfg_with_port(port, tmp=None):
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, instance.CONFIG), "w") as f:
        json.dump({"porta": port}, f)
    return instance.read_config(d)


def test_18b_only_tailscale_names_as_public_hosts(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    for hosts in (["evil.example.com"], ["mac.tail0000.ts.net:443"], ["0.0.0.0"]):
        (d / instance.CONFIG).write_text(json.dumps({"porta": 8110, "host_pubblici": hosts}))
        with pytest.raises(ValueError):
            instance.read_config(str(d))


# ------------------------------------------------------------------ 19. the MARKET-ONLY job stays independent

def test_19_market_only_job_is_independent():
    job = open(os.path.join(ROOT, "daily_job.py")).read()
    sched = open(os.path.join(ROOT, "schedule.sh")).read()
    assert "instance" not in job and "istanza" not in sched
    import inspect
    import server
    fw = inspect.getsource(server.follower_worker)
    for forbidden in ("save_opportunity_diary", "save_etf_scan_diary", "save_alerts", "refresh_fundamentals",
                      "refresh_etf_prices", "refresh_daily", "authorize", "write_cache", "save_daily_cache"):
        assert forbidden not in fw, forbidden
    lp = inspect.getsource(server.load_public)
    assert "download(" not in lp and "write_cache" not in lp and "save_daily_cache" not in lp and '"w"' not in lp
    assert "INSTANCE" not in inspect.getsource(server.run_daily_job)


def test_19b_instance_process_is_never_a_production_writer(world, monkeypatch):
    become(world, "A", monkeypatch)
    with pytest.raises(app_env.ProductionWriteBlocked):
        app_env.check_diary_write(os.path.join(app_env.DATA, "opportunita.sqlite3"), "dashboard")


# ------------------------------------------------------------------ backup and restore of one user only

def test_backup_and_restore_one_user(world, monkeypatch, tmp_path):
    setup_user(world, "A", monkeypatch)
    app_env._end_instance_for_tests()
    dest = str(tmp_path / "backup-a.tar.gz")
    instance.backup(world["dirs"]["A"], dest)
    if not WINDOWS:                                                     # Windows: ACLs, no Unix mode to check
        assert oct(os.stat(dest).st_mode & 0o777) == "0o600"
    with tarfile.open(dest) as t:
        names = t.getnames()
    assert "watchlist.json" in names and not any(n.startswith(("logs", "../")) or "B" == n[:1] for n in names)
    target = os.path.join(world["cont"], "A2")
    instance.restore(dest, target)
    with open(os.path.join(target, "watchlist.json")) as f:
        assert json.load(f)["tickers"] == WATCH["A"]
    with pytest.raises(SystemExit):
        instance.restore(dest, target)                                   # never over existing data
    evil = str(tmp_path / "evil.tar.gz")
    with tarfile.open(evil, "w:gz") as t:
        info = tarfile.TarInfo("../fuori.txt")
        info.size = 1
        import io
        t.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(SystemExit):
        instance.restore(evil, os.path.join(world["cont"], "A3"))
    assert not os.path.exists(os.path.join(world["cont"], "fuori.txt"))


# ------------------------------------------------------------------ 20 (+ process level). separate processes

def run_py(code, env_extra=None):
    env = {**os.environ, "NDX_ENV": "istanza", "PYTHONDONTWRITEBYTECODE": "1", **(env_extra or {})}
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "", r.stderr


def test_20_a_real_separate_process_cannot_read_the_owner_or_another_user(tmp_path):
    cont = tmp_path / "istanze"
    (cont / "A").mkdir(parents=True)
    (cont / "B").mkdir()
    (cont / app_env.INSTANCE_MARKER).write_text("x")
    (cont / "A" / "segreto.json").write_text('{"x": 1}')
    sentinel = tmp_path / "sentinella"
    sentinel.mkdir()
    code = f"""
import os, sys, sqlite3
sys.path.insert(0, {ROOT!r})
import app_env
app_env.enable_instance({str(cont / 'B')!r})
app_env.protect({str(sentinel)!r})
import server, portfolio, instance
out = []
for what, fn in (("leggi A", lambda: open({str(cont / 'A' / 'segreto.json')!r})),
                 ("elenca A", lambda: os.listdir({str(cont / 'A')!r})),
                 ("sqlite A", lambda: sqlite3.connect({str(cont / 'A' / 'x.sqlite3')!r})),
                 ("leggi portafoglio proprietario", lambda: os.listdir(os.path.join(app_env.ROOT, "portafoglio"))),
                 ("leggi preferiti proprietario", lambda: open(os.path.join(app_env.ROOT, "watchlist.json"))),
                 ("scrivi nel progetto (sentinella)", lambda: open({str(sentinel / 'x')!r}, "w"))):
    try:
        fn(); out.append(what + ": PERMESSO")
    except (app_env.PrivateAccessBlocked, app_env.ProductionWriteBlocked):
        out.append(what + ": bloccato")
open({str(cont / 'B' / 'mio.json')!r}, "w").write("{{}}")
out.append("scrivi B: ok")
try:
    app_env.authorize("server")
    out.append("autorizzato: SI")
except app_env.ProductionWriteBlocked:
    out.append("autorizzato: no")
print(" | ".join(out))
"""
    rc, last, err = run_py(code)
    assert rc == 0, err
    assert "PERMESSO" not in last and last.count("bloccato") == 6 and "scrivi B: ok" in last and "autorizzato: no" in last, last
    assert not os.path.exists(sentinel / "x")


def test_20b_instance_mode_needs_its_environment(tmp_path):
    cont = tmp_path / "istanze"
    (cont / "A").mkdir(parents=True)
    (cont / app_env.INSTANCE_MARKER).write_text("x")
    code = f"import sys; sys.path.insert(0, {ROOT!r}); import app_env; app_env.enable_instance({str(cont / 'A')!r}); print('acceso')"
    rc, last, err = run_py(code, {"NDX_ENV": "produzione"})
    assert rc != 0 and "NDX_ENV=istanza" in err


# ------------------------------------------------------------------ page

def test_page_label_and_csrf_only_in_an_instance(world, monkeypatch):
    import server
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    assert 'meta[name="ndx-csrf"]' in js and '"X-CSRF-Token": INSTANCE.csrf' in js and 'location.assign("/accesso")' in js
    personal = server.app.test_client().get("/", base_url="http://127.0.0.1:8100").get_data(as_text=True)
    assert "ndx-csrf" not in personal and "ndx-istanza" not in personal
    c = become(world, "A", monkeypatch)
    me = User(c, "A")
    page = me.get("/").get_data(as_text=True)
    assert '<meta name="ndx-istanza" content="Portafoglio A">' in page and "<title>Nasdaq-100 Monitor</title>" in page
