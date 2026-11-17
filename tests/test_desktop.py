"""Fase 9B: app portatile per Windows (desktop.py, desktop_app.py) - solo dati INVENTATI e cartelle temporanee.

Due «PC» finti (cartelle dei dati P1 e P2) al posto di %LOCALAPPDATA%\\Nasdaq100Monitor. Niente rete (la guardia dei
test la blocca): i download sono sostituiti da funzioni finte. In fondo, prove in processi separati: l'app vera avviata,
aperta e chiusa, e la protezione della modalità desktop. Le stesse prove girano su Windows nella build
(packaging/build_windows.ps1): qui, sul Mac, non dimostrano da sole che il programma funzioni su Windows."""
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import zipfile

import pytest

import app_env
import desktop
import portfolio
from test_istanze import POS, export_bytes, fake_rows

ROOT = app_env.ROOT
PORT = 8130
ORIGIN = f"http://127.0.0.1:{PORT}"


# ------------------------------------------------------------------ a fake PC

@pytest.fixture
def market(monkeypatch):
    """Fake public market: no network, a few invented stocks."""
    import earnings
    import server
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
    monkeypatch.setattr(server.store, "snapshot", {"asOf": "2026-11-09T10:00:00-05:00", "session": "2026-11-09",
                                                   "status": "open", "stocks": stocks, "indices": {}, "breadth": [],
                                                   "totalMcap": 0})
    monkeypatch.setattr(server.store, "infos", {})
    monkeypatch.setattr(server.store, "daily", {})
    monkeypatch.setattr(server.store, "constituents", [])
    monkeypatch.setattr(server.store, "error", None)
    server.store.ready.set()
    yield
    app_env._end_desktop_for_tests()


def pc(tmp_path, name, monkeypatch):
    """This process becomes the app on the PC `name`: data folder created, protection on, modules pointed to it, memory
    as in a new process."""
    import server
    app_env._end_desktop_for_tests()
    base = desktop.ensure_dirs(str(tmp_path / name / "Nasdaq100Monitor"))
    app_env.enable_desktop(base)
    app = desktop.configure(base, PORT, setter=monkeypatch.setattr, setitem=monkeypatch.setitem)
    with portfolio._lock:
        portfolio._state.update(path=None, mtime=None, positions=[], error=None, resolving=False, quotes={}, fx=None,
                                quotesAt=None)
    portfolio._upload["token"] = None
    return base, app, server.app.test_client()


class Browser:
    """The browser opened by the app (with its one-time key), then the page's own requests."""

    def __init__(self, client):
        import server
        self.c = client
        key = server.INSTANCE["open_keys"].make()
        r = self.c.get(f"/avvio?k={key}", base_url=ORIGIN)
        assert r.status_code == 303, r.data
        self.page = self.c.get("/", base_url=ORIGIN).get_data(as_text=True)
        self.csrf = re.search(r'name="ndx-csrf" content="([^"]+)"', self.page).group(1)

    def get(self, path):
        return self.c.get(path, base_url=ORIGIN)

    def post(self, path, body=None, raw=None, headers=None):
        h = {"Origin": ORIGIN, "X-CSRF-Token": self.csrf, "X-Requested-With": "ndx-dashboard", **(headers or {})}
        if raw is not None:
            return self.c.post(path, data=raw, base_url=ORIGIN, headers=h)
        return self.c.post(path, json=body if body is not None else {}, base_url=ORIGIN, headers=h)


def wait_resolved():
    for _ in range(100):
        if not portfolio._state["resolving"]:
            return
        time.sleep(0.05)
    raise AssertionError("ticker non risolti")


def upload(b, rows):
    for p in rows:
        assert b.post("/api/portfolio/ticker", {"isin": p[1], "ticker": p[8]}).status_code == 200
    wait_resolved()
    r = b.post("/api/portfolio/upload", raw=export_bytes(rows),
               headers={"X-Filename": "export.xls", "Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.data
    assert b.post("/api/portfolio/upload/confirm", {"token": r.get_json()["token"]}).status_code == 200
    wait_resolved()


def files_under(d):
    return sorted(os.path.relpath(os.path.join(r, f), d).replace(os.sep, "/") for r, _, fs in os.walk(d) for f in fs)


# ------------------------------------------------------------------ personal folders

def test_personal_folders_are_created_outside_the_program(tmp_path, monkeypatch):
    base = desktop.ensure_dirs(str(tmp_path / "LocalAppData" / "Nasdaq100Monitor"))
    assert sorted(os.listdir(base)) == sorted(desktop.SUBDIRS)
    with pytest.raises(ValueError):
        desktop.ensure_dirs(os.path.join(ROOT, "dati-app"))                 # never inside the program folder
    try:
        os.symlink(base, str(tmp_path / "link"))
    except (OSError, NotImplementedError):                                   # Windows without the right privilege
        pass
    else:
        with pytest.raises(ValueError):
            desktop.ensure_dirs(str(tmp_path / "link"))
    with monkeypatch.context() as m:                                         # Windows: %LOCALAPPDATA%\Nasdaq100Monitor
        m.delenv("NDX_DESKTOP_DIR", raising=False)
        m.setenv("LOCALAPPDATA", str(tmp_path / "LAD"))
        m.setattr(desktop.os, "name", "nt")
        where = desktop.default_dir()
    assert where == os.path.join(str(tmp_path / "LAD"), "Nasdaq100Monitor")


def test_every_path_points_to_the_pc_never_to_the_program(tmp_path, monkeypatch, market):
    import analysts
    import diary
    import etf_prices
    import fundamentals
    import history
    import macro_calendar
    import opportunity_diary
    import alert_engine
    import server
    import signals
    base, app, _ = pc(tmp_path, "P1", monkeypatch)
    personal = [portfolio.PORTFOLIO_DIR, portfolio.UPLOAD_TMP, server.WATCHLIST, diary.DIR, history.DIR,
                opportunity_diary.DB, alert_engine.DB, signals.REPORT_DIR]
    caches = [server.CACHE_DIR, server.DAILY_CACHE, analysts.CACHE, macro_calendar.AUTO_CACHE, fundamentals.CACHE,
              etf_prices.CACHE]
    for p in personal:
        assert app_env._under(os.path.realpath(p), os.path.join(base, "dati")), p
    for p in caches:
        assert app_env._under(os.path.realpath(p), os.path.join(base, "cache")), p
    assert not any(app_env._under(os.path.realpath(p), ROOT) for p in personal + caches)


def test_configure_never_touches_the_financial_engines(tmp_path, monkeypatch, market):
    """The app changes only paths, the access protection and the ETF tab trigger: never a model, threshold or rule."""
    touched = []

    def spy(obj, name, value):
        touched.append((getattr(obj, "__name__", type(obj).__name__), name))
        monkeypatch.setattr(obj, name, value)
    app_env._end_desktop_for_tests()
    base = desktop.ensure_dirs(str(tmp_path / "P1"))
    app_env.enable_desktop(base)
    desktop.configure(base, PORT, setter=spy, setitem=monkeypatch.setitem)
    engines = {"opportunity_scanner", "investment_engine", "investment_valuation", "investment_valuation_v1",
               "etf_opportunity", "investment_decision_engine", "portfolio_fit", "decision", "actions", "pillars",
               "score", "technical", "risk", "etf_buy", "stop_auto"}
    allowed = {"PORTFOLIO_DIR", "OVERRIDES", "CLASS_FILE", "UPLOAD_TMP", "FISCAL", "DIR", "FILE", "LOG", "EXCLUDED"}
    for mod, name in touched:
        assert mod not in engines or name in allowed, (mod, name)
    import alert_engine, etf_opportunity, investment_decision_engine, investment_engine, investment_valuation
    import opportunity_scanner, portfolio_fit
    assert (opportunity_scanner.MODEL_VERSION, investment_engine.VERSION, investment_valuation.VERSION,
            etf_opportunity.VERSION, investment_decision_engine.VERSION, portfolio_fit.VERSION,
            alert_engine.VERSION) == ("O2.1", "F1", "V2", "E2", "D2", "P1", "A1")


# ------------------------------------------------------------------ access: key, session, CSRF, Origin, Host

def test_the_page_opens_only_with_the_programs_key(tmp_path, monkeypatch, market):
    import server
    _, app, c = pc(tmp_path, "P1", monkeypatch)
    assert c.get("/", base_url=ORIGIN).status_code == 303                           # no session: to /accesso
    assert c.get("/api/portfolio", base_url=ORIGIN).status_code == 401
    assert "Apri la dashboard" in c.get("/accesso", base_url=ORIGIN).get_data(as_text=True)
    assert c.post("/accesso", data={"password": "x"}, base_url=ORIGIN, headers={"Origin": ORIGIN}).status_code == 404
    assert c.get("/avvio?k=inventata", base_url=ORIGIN).status_code == 403
    key = server.INSTANCE["open_keys"].make()
    r = c.get(f"/avvio?k={key}", base_url=ORIGIN)
    assert r.status_code == 303 and "HttpOnly" in r.headers["Set-Cookie"] and "SameSite=Strict" in r.headers["Set-Cookie"]
    c2 = server.app.test_client()
    assert c2.get(f"/avvio?k={key}", base_url=ORIGIN).status_code == 403            # a key works once
    page = c.get("/", base_url=ORIGIN)
    html = page.get_data(as_text=True)
    assert 'name="ndx-desktop"' in html and "/static/vendor/d3.min.js" in html and "cdn.jsdelivr" not in html
    assert "questo Mac" not in html
    assert "cdn.jsdelivr" not in page.headers["Content-Security-Policy"]
    assert page.headers["Referrer-Policy"] == "same-origin" and page.headers["X-Frame-Options"] == "DENY"


def test_old_keys_expire(monkeypatch):
    import instance_auth as ia
    now = [1000.0]
    keys = ia.OneTimeKeys(clock=lambda: now[0])
    k = keys.make()
    now[0] += ia.OneTimeKeys.KEY_S + 1
    assert not keys.use(k)
    assert not keys.use("") and not keys.use(None)


def test_other_sites_and_hosts_are_refused(tmp_path, monkeypatch, market):
    _, app, c = pc(tmp_path, "P1", monkeypatch)
    b = Browser(c)
    assert b.c.get("/api/app/stato", base_url="http://evil.example").status_code == 403          # DNS rebinding
    h = {"X-Requested-With": "ndx-dashboard", "X-CSRF-Token": b.csrf}
    assert c.post("/api/app/chiudi", base_url=ORIGIN, headers={**h, "Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/app/chiudi", base_url=ORIGIN, headers={**h, "X-CSRF-Token": "sbagliato", "Origin": ORIGIN}).status_code == 403
    assert c.post("/api/watchlist", base_url=ORIGIN, data="x", headers={"Origin": ORIGIN}).status_code == 403
    assert not app.quit.is_set()
    assert b.post("/api/app/chiudi").status_code == 200
    for _ in range(40):
        if app.quit.is_set():
            break
        time.sleep(0.1)
    assert app.quit.is_set()


def test_listens_only_on_this_pc():
    import server
    srv, port = desktop.bind_server(server.app, ports=range(18130, 18150))
    try:
        assert srv.server_address[0] == "127.0.0.1" and 18130 <= port < 18150
        srv2, port2 = desktop.bind_server(server.app, ports=range(port, port + 3))          # taken: the next one
        srv2.server_close()
        assert port2 != port
    finally:
        srv.server_close()


def test_the_mac_dashboard_does_not_change():
    import server
    assert server.INSTANCE is None
    c = server.app.test_client()
    for path in ("/avvio?k=x", "/api/app/stato", "/api/app/ping"):
        assert c.get(path).status_code == 404
    html = c.get("/").get_data(as_text=True)
    assert "cdn.jsdelivr.net/npm/d3@7.9.0" in html and "ndx-desktop" not in html


# ------------------------------------------------------------------ the father's data: upload, restart, separation

def test_upload_save_and_restart_on_the_pc(tmp_path, monkeypatch, market):
    base, app, c = pc(tmp_path, "P1", monkeypatch)
    b = Browser(c)
    upload(b, POS["A"])
    d = b.get("/api/portfolio").get_json()
    assert sorted(p["isin"] for p in d["positions"]) == sorted(p[1] for p in POS["A"])
    saved = [f for f in files_under(os.path.join(base, "dati")) if f.startswith("portafoglio/portafoglio-")]
    assert len(saved) == 1 and saved[0].endswith(".xls")
    assert not os.path.exists(portfolio.UPLOAD_TMP)                                    # no leftover copy
    # restart: a new process reads the same folder
    _, app2, c2 = pc(tmp_path, "P1", monkeypatch)
    portfolio.refresh()
    wait_resolved()
    d2 = Browser(c2).get("/api/portfolio").get_json()
    assert sorted(p["isin"] for p in d2["positions"]) == sorted(p[1] for p in POS["A"])


def test_a_bad_upload_keeps_the_previous_portfolio(tmp_path, monkeypatch, market):
    base, app, c = pc(tmp_path, "P1", monkeypatch)
    b = Browser(c)
    upload(b, POS["A"])
    before = files_under(os.path.join(base, "dati", "portafoglio"))
    for raw in (b"MZ\x90\x00 programma", b"PK\x03\x04 zip", portfolio.XLS_MAGIC + b"[[]]"):
        r = b.post("/api/portfolio/upload", raw=raw, headers={"X-Filename": "x.xls", "Content-Type": "application/octet-stream"})
        assert r.status_code == 400
    assert files_under(os.path.join(base, "dati", "portafoglio")) == before
    assert sorted(p["isin"] for p in b.get("/api/portfolio").get_json()["positions"]) == sorted(p[1] for p in POS["A"])


def test_two_pcs_keep_preferiti_and_classifications_apart(tmp_path, monkeypatch, market):
    base1, _, c1 = pc(tmp_path, "P1", monkeypatch)
    b1 = Browser(c1)
    upload(b1, POS["A"])
    assert b1.post("/api/watchlist", {"tickers": ["AAA", "AAB"]}).status_code == 200
    etf = next(p for p in POS["A"] if p[4] == "ETF")
    assert b1.post("/api/portfolio/classification", {"isin": etf[1], "fields": {"settore": "Settore P1"}}).status_code == 200
    base2, _, c2 = pc(tmp_path, "P2", monkeypatch)
    b2 = Browser(c2)
    assert b2.get("/api/watchlist").get_json()["tickers"] == []
    assert b2.get("/api/portfolio").get_json().get("positions") in ([], None)
    assert b2.post("/api/watchlist", {"tickers": ["BBA"]}).status_code == 200
    app_env._end_desktop_for_tests()
    with open(os.path.join(base1, "dati", "watchlist.json")) as f:
        assert json.load(f)["tickers"] == ["AAA", "AAB"]
    with open(os.path.join(base2, "dati", "watchlist.json")) as f:
        assert json.load(f)["tickers"] == ["BBA"]
    with open(os.path.join(base1, "dati", "portafoglio", "classificazione.json")) as f:
        assert json.load(f)[etf[1]]["settore"] == "Settore P1"
    assert not os.path.exists(os.path.join(base2, "dati", "portafoglio", "classificazione.json"))


def test_risk_fit_and_simulation_use_the_pcs_portfolio(tmp_path, monkeypatch, market):
    import risk
    seen = []
    monkeypatch.setattr(risk, "snapshot", lambda pf: seen.append(sorted(p["isin"] for p in pf.get("positions") or [])) or {"ok": True})
    _, _, c = pc(tmp_path, "P1", monkeypatch)
    b = Browser(c)
    upload(b, POS["B"])
    assert b.get("/api/portfolio/risk").status_code == 200
    assert seen == [sorted(p[1] for p in POS["B"])]
    r = b.post("/api/portfolio/fit", {"consent": True, "source": "mio", "candidate": "NDXA",
                                      "whatif": {"amount": 500, "funding": "nuova"}})
    assert r.status_code == 200, r.data
    d = r.get_json()
    assert d["available"] and sorted(p["name"] for p in d["positions"]) == sorted(p[0] for p in POS["B"])
    assert d.get("whatif") and "non è un ordine" in json.dumps(d["whatif"], ensure_ascii=False)


# ------------------------------------------------------------------ «Aggiorna dati»

@pytest.fixture
def fake_sources(monkeypatch):
    """Every download of the update replaced; records what the diaries were asked to save and with which origin."""
    import analysts
    import fundamentals
    import macro_calendar
    import server
    import signals
    calls = []
    rows = [{"ticker": "NDXA", "name": "A", "sector": "Tecnologia", "industry": "Software"}]
    monkeypatch.setattr(desktop, "online", lambda timeout=5: True)
    monkeypatch.setattr(server, "load_constituents", lambda: calls.append("constituents") or rows)
    monkeypatch.setattr(server, "load_infos", lambda t: {})
    monkeypatch.setattr(analysts, "is_fresh", lambda: True)
    monkeypatch.setattr(analysts, "cached_data", lambda: {})
    monkeypatch.setattr(server, "qqq_top_weights", lambda: None)

    def daily():
        calls.append("daily")
        server.store.daily = {"NDXA": object()}
    monkeypatch.setattr(server.store, "refresh_daily", daily)
    monkeypatch.setattr(server.store, "refresh_intraday", lambda: calls.append("intraday"))
    monkeypatch.setattr(server.store, "build", lambda: None)
    monkeypatch.setattr(server, "_bars_note", lambda: "ultima barra QQQ 2026-11-09")
    monkeypatch.setattr(macro_calendar, "refresh", lambda: calls.append("macro"))
    monkeypatch.setattr(fundamentals, "refresh", lambda t: calls.append("fundamentals"))
    import etf_prices
    monkeypatch.setattr(etf_prices, "due", lambda *a: False)
    monkeypatch.setattr(desktop.App, "build_etf", lambda self: calls.append("etf"))
    for name in ("save_signal_diary", "save_etf_diary", "save_pos_diary"):
        monkeypatch.setattr(server, name, lambda *a, _n=name, **k: calls.append(_n))
    for name in ("save_etf_scan_diary", "save_opportunity_diary", "save_alerts"):
        monkeypatch.setattr(server, name, lambda source=None, _n=name: calls.append((_n, source)) or "ok")
    monkeypatch.setattr(signals, "list_reports", lambda: [])
    monkeypatch.setattr(signals, "run", lambda **k: calls.append("report"))
    return calls


def test_manual_update_runs_every_step_with_the_official_origin(tmp_path, monkeypatch, market, fake_sources):
    base, app, c = pc(tmp_path, "P1", monkeypatch)
    b = Browser(c)
    st = b.get("/api/app/stato").get_json()
    assert st["firstRun"] and "Aggiorna dati" in st["firstRunText"] and not st["running"]
    app.state["running"] = True                                       # while one runs, a second is refused
    assert b.post("/api/app/aggiorna").status_code == 409
    app.state["running"] = False
    app._update("comando manuale")                                    # the thread's body, here synchronous
    st = b.get("/api/app/stato").get_json()
    assert st["outcome"] == "completo", st
    assert [s["name"] for s in st["steps"]] == list(desktop.App.STEPS)[:len(st["steps"])]
    assert all(s["status"] == "ok" for s in st["steps"])
    assert ("save_opportunity_diary", "comando manuale") in fake_sources
    assert ("save_alerts", "comando manuale") in fake_sources and "etf" in fake_sources
    with open(os.path.join(base, "dati", "aggiornamento.json")) as f:
        assert json.load(f)["outcome"] == "completo"


def test_without_internet_nothing_changes(tmp_path, monkeypatch, market, fake_sources):
    base, app, c = pc(tmp_path, "P1", monkeypatch)
    monkeypatch.setattr(desktop, "online", lambda timeout=5: False)
    before = files_under(base)
    app._update("comando manuale")
    assert app.state["outcome"] == "non riuscito" and "Internet" in app.state["message"]
    assert fake_sources == []                                          # not one download tried
    assert [f for f in files_under(base) if f != "dati/aggiornamento.json"] == before


def test_a_failing_source_gives_a_partial_update(tmp_path, monkeypatch, market, fake_sources):
    import requests
    import fundamentals
    _, app, _ = pc(tmp_path, "P1", monkeypatch)

    def down(t):
        raise requests.ConnectionError("rete")
    monkeypatch.setattr(fundamentals, "refresh", down)
    app._update("comando manuale")
    assert app.state["outcome"] == "parziale"
    bad = [s for s in app.state["steps"] if s["status"] != "ok"]
    assert [s["name"] for s in bad] == ["Bilanci"] and "non raggiungibile" in bad[0]["note"]


def test_no_download_before_the_first_update(tmp_path, monkeypatch, market):
    import server
    _, app, _ = pc(tmp_path, "P1", monkeypatch)
    monkeypatch.setattr(server.store, "refresh_intraday", lambda: pytest.fail("scaricato senza «Aggiorna dati»"))
    desktop.load_local(app)
    assert server.store.error == desktop.FIRST_RUN
    assert app.tick() == "nessun dato: si aspetta «Aggiorna dati»"
    import etf
    with etf._lock:
        etf._state.update(data=None, running=False, error=None)
    assert app.etf_public() is None and "Aggiorna dati" in etf._state["error"] and not etf._state["running"]


def test_evening_update_only_when_chosen(tmp_path, monkeypatch, market):
    from datetime import datetime
    import server
    _, app, _ = pc(tmp_path, "P1", monkeypatch)
    evening = datetime(2026, 11, 10, 16, 30, tzinfo=server.ET)          # Tuesday, after the close + 20 minutes
    assert not app.evening_due(evening)
    app.settings.set(auto_sera=True)
    assert app.evening_due(evening)
    assert not app.evening_due(datetime(2026, 11, 10, 15, 30, tzinfo=server.ET))       # before the close
    assert not app.evening_due(datetime(2026, 11, 14, 18, 0, tzinfo=server.ET))        # Saturday
    app.state["lastSession"] = "2026-11-10"
    assert not app.evening_due(evening)                                                   # once per session


# ------------------------------------------------------------------ backup and restore

def test_backup_contains_only_the_personal_data(tmp_path, monkeypatch, market):
    base, app, c = pc(tmp_path, "P1", monkeypatch)
    b = Browser(c)
    upload(b, POS["A"])
    b.post("/api/watchlist", {"tickers": ["AAA"]})
    with open(os.path.join(base, "cache", "daily.pkl"), "wb") as f:
        f.write(b"cache")
    r = b.post("/api/app/backup")
    assert r.status_code == 200 and r.headers["Content-Disposition"].startswith("attachment;")
    names = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert desktop.BACKUP_MARK in names and "watchlist.json" in names
    assert any(n.startswith("portafoglio/portafoglio-") for n in names)
    assert not any(n.startswith(("cache/", "logs/")) or n.endswith(".tmp") for n in names)
    assert len(os.listdir(os.path.join(base, "backup"))) == 1


def make_zip(entries, mark=True, link=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if mark:
            z.writestr(desktop.BACKUP_MARK, "{}")
        for n, data in entries.items():
            z.writestr(n, data)
        if link:
            info = zipfile.ZipInfo(link)
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
    return buf.getvalue()


@pytest.mark.parametrize("entries,mark,link,why", [
    ({"../fuori.json": "x"}, True, None, "percorsi"),
    ({"/assoluto.json": "x"}, True, None, "percorsi"),
    ({"portafoglio\\..\\x.json": "x"}, True, None, "percorsi"),
    ({"C:/Windows/x.json": "x"}, True, None, "percorsi"),
    ({"programma.exe": "MZ"}, True, None, "percorsi"),
    ({"watchlist.json": "{}"}, False, None, "non è un backup"),
    ({}, True, "portafoglio/collegamento", "collegamenti"),
])
def test_restore_refuses_dangerous_archives(tmp_path, entries, mark, link, why):
    base = desktop.ensure_dirs(str(tmp_path / "P1"))
    with pytest.raises(ValueError, match=why):
        desktop.stage_restore(base, make_zip(entries, mark, link))
    assert not os.path.exists(os.path.join(base, desktop.RESTORE_DIR))
    with pytest.raises(ValueError):
        desktop.stage_restore(base, b"non uno zip")


def test_restore_is_applied_at_the_next_start_and_keeps_the_old_data(tmp_path):
    base = desktop.ensure_dirs(str(tmp_path / "P1"))
    with open(os.path.join(base, "dati", "watchlist.json"), "w") as f:
        json.dump({"tickers": ["VECCHIO"]}, f)
    n = desktop.stage_restore(base, make_zip({"watchlist.json": json.dumps({"tickers": ["NUOVO"]}),
                                              "portafoglio/ticker.json": "{}"}))
    assert n == 2
    with open(os.path.join(base, "dati", "watchlist.json")) as f:
        assert json.load(f)["tickers"] == ["VECCHIO"]                    # nothing in use is overwritten now
    assert desktop.apply_pending_restore(base)
    with open(os.path.join(base, "dati", "watchlist.json")) as f:
        assert json.load(f)["tickers"] == ["NUOVO"]
    old = [d for d in os.listdir(os.path.join(base, "backup")) if d.startswith("dati-prima-del-ripristino-")]
    with open(os.path.join(base, "backup", old[0], "watchlist.json")) as f:
        assert json.load(f)["tickers"] == ["VECCHIO"]
    assert not desktop.apply_pending_restore(base)


# ------------------------------------------------------------------ real processes

def _env(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("NDX_", "PYTEST"))}
    env.update(NDX_ENV="desktop", PYTHONUTF8="1", **extra)
    return env


def test_protection_of_the_desktop_mode_in_a_real_process(tmp_path):
    """NDX_ENV=desktop, without pytest: the program folder is read only, the project's personal files are unreadable,
    the diaries are written only in the app's folder and only with an official origin."""
    base = tmp_path / "P1"
    base.mkdir()
    code = f"""
import os, sys
sys.path.insert(0, {ROOT!r})
import app_env
app_env.enable_desktop({str(base)!r})
out = []
def t(name, fn):
    try:
        fn(); out.append(name + "=ok")
    except Exception as e:
        out.append(name + "=" + type(e).__name__)
t("leggi_portafoglio", lambda: open(os.path.join(app_env.ROOT, "portafoglio", "__non_esiste__.json")))
t("elenca_portafoglio", lambda: os.listdir(os.path.join(app_env.ROOT, "portafoglio")))
t("leggi_preferiti", lambda: open(os.path.join(app_env.ROOT, "watchlist.json")))
t("scrivi_programma", lambda: open(os.path.join(app_env.ROOT, "static", "__prova__.txt"), "w"))
t("scrivi_pc", lambda: open(os.path.join({str(base)!r}, "prova.txt"), "w").close())
t("autorizza", lambda: app_env.authorize("app desktop"))
t("diario_pc", lambda: app_env.check_diary_write(os.path.join({str(base)!r}, "dati", "data", "opportunita.sqlite3"), "comando manuale"))
t("diario_progetto", lambda: app_env.check_diary_write(os.path.join(app_env.ROOT, "data", "opportunita.sqlite3"), "comando manuale"))
t("origine_prova", lambda: app_env.check_diary_write(os.path.join({str(base)!r}, "dati", "data", "x.sqlite3"), "prova"))
print(";".join(out))
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=_env(tmp_path), timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    got = dict(x.split("=") for x in r.stdout.strip().split(";"))
    assert got == {"leggi_portafoglio": "PrivateAccessBlocked", "elenca_portafoglio": "PrivateAccessBlocked",
                   "leggi_preferiti": "PrivateAccessBlocked", "scrivi_programma": "ProductionWriteBlocked",
                   "scrivi_pc": "ok", "autorizza": "ok", "diario_pc": "ok", "diario_progetto": "ProductionWriteBlocked",
                   "origine_prova": "ProductionWriteBlocked"}, got


def _http(url, data=None, headers=None, cookie=None):
    h = dict(headers or {})
    if cookie:
        h["Cookie"] = cookie
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        r = opener.open(req, timeout=20)
    except urllib.error.HTTPError as e:
        r = e
    return r.status if hasattr(r, "status") else r.code, dict(r.headers), r.read()


def test_the_real_app_starts_opens_the_browser_and_closes(tmp_path):
    """desktop_app.py as on Windows (without the small window): first start creates the folders, opens the browser with
    a key, a second start only asks the first one to open the browser again, «Chiudi l'app» ends the process."""
    urls = tmp_path / "urls.txt"
    base = tmp_path / "LocalAppData" / "Nasdaq100Monitor"
    env = _env(tmp_path, NDX_PROVA_URL_FILE=str(urls))
    cmd = [sys.executable, os.path.join(ROOT, "desktop_app.py"), "--senza-finestra", "--cartella", str(base)]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(300):
            if urls.exists() and urls.read_text().strip():
                break
            assert p.poll() is None, p.stderr.read().decode()[-800:]
            time.sleep(0.1)
        url = urls.read_text().strip().splitlines()[-1]
        assert re.fullmatch(r"http://127\.0\.0\.1:81[34]\d/avvio\?k=[\w-]{20,}", url), url
        assert sorted(os.listdir(base)) == sorted(list(desktop.SUBDIRS) + ["app.json"])
        status, headers, _ = _http(url)
        assert status == 303
        cookie = headers["Set-Cookie"].split(";")[0]
        origin = url.split("/avvio")[0]
        status, _, body = _http(origin + "/", cookie=cookie)
        html = body.decode()
        assert status == 200 and 'name="ndx-desktop"' in html
        csrf = re.search(r'name="ndx-csrf" content="([^"]+)"', html).group(1)
        status, _, body = _http(origin + "/api/app/stato", cookie=cookie)
        assert status == 200 and json.loads(body)["firstRun"]
        # a second double click: the running copy opens the browser again, the new process exits
        r2 = subprocess.run(cmd, env=env, capture_output=True, timeout=60)
        assert r2.returncode == 0 and len(urls.read_text().strip().splitlines()) == 2
        status, _, _ = _http(origin + "/api/app/chiudi", data=b"", cookie=cookie,
                             headers={"Origin": origin, "X-CSRF-Token": csrf, "X-Requested-With": "ndx-dashboard"})
        assert status == 200
        assert p.wait(timeout=30) == 0
        assert not (base / "app.json").exists()
        logs = (base / "logs" / "app.log").read_text(encoding="utf-8")
        assert "avvio?k=" not in logs and "chiusa" in logs
    finally:
        if p.poll() is None:
            p.kill()
