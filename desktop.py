"""App portatile per Windows (Fase 9B): la stessa dashboard, sul PC di un'altra persona, senza Python e senza il Mac.

Come è fatta (il programma vero è desktop_app.py, impacchettato con PyInstaller):
- tutto il codice e i file pubblici stanno nella cartella del programma, che l'app NON scrive mai (app_env.enable_desktop
  blocca ogni scrittura lì prima che avvenga): una versione nuova si sostituisce senza perdere niente;
- i dati stanno in %LOCALAPPDATA%\\Nasdaq100Monitor (cartella dell'utente di Windows):
    dati\\    portafoglio, Preferiti, classificazioni, dati fiscali, storico, diari e alert di QUESTA persona, report;
    cache\\   dati di mercato scaricati (si possono cancellare: si riscaricano con «Aggiorna dati»);
    logs\\    registro tecnico (mai posizioni, quantità o valori);
    backup\\  copie fatte con «Backup dei miei dati»;
- niente job automatico: i dati pesanti si scaricano solo con il pulsante «Aggiorna dati» (Updater), che usa le stesse
  funzioni del job serale del Mac (server.run_daily_job) senza cambiare nessuna regola; mentre l'app è aperta si
  aggiornano da sole solo le quotazioni del giorno (una richiesta al minuto con la borsa aperta) e i prezzi delle
  posizioni, e solo dopo il primo «Aggiorna dati»;
- i diari partono vuoti sul PC e registrano solo le sedute aggiornate in tempo (mai recuperi del passato);
- server solo su 127.0.0.1; l'app apre il browser con una chiave usa e getta (/avvio?k=...), poi sessione, token CSRF,
  Origin esatto e Host locale come nella Fase 9A."""
from __future__ import annotations

import io
import json
import logging
import os
import pickle
import socket
import stat
import sys
import threading
import time
import zipfile
from datetime import datetime

import app_env

APP_NAME = "Nasdaq100Monitor"
TITLE = "Nasdaq-100 Monitor"
PORTS = tuple(range(8130, 8150))            # first free one; a stable port keeps the page's own settings (per origin)
SUBDIRS = ("dati", "cache", "logs", "backup")
BACKUP_MARK = "nasdaq100monitor-backup.json"
RESTORE_DIR = "ripristino_in_attesa"
MAX_RESTORE = 300 * 1024 * 1024             # uploaded backup, bytes
MAX_RESTORE_FILES = 50_000
MAX_RESTORE_UNPACKED = 1024 * 1024 * 1024
# What a backup may contain (top level of dati\): anything else in an uploaded archive is refused.
BACKUP_TOP = ("portafoglio", "diario", "diario_etf", "diario_posizioni", "storico", "data", "reports", "validazione",
              "watchlist.json", "fiscale.json", "regole.json", "dati_titoli.json", "pagella.json", "stop_auto.json",
              "etf_composizioni.json", "etf_holdings.json", "impostazioni.json", "aggiornamento.json")
SKIP_SUFFIX = (".tmp", ".lock", ".caricamento.xls")
FIRST_RUN = ("Benvenuto! I dati di mercato non sono ancora sul PC: premi «Aggiorna dati» in alto. La prima volta "
             "scarica circa 50–100 MB e richiede 5–15 minuti (serve Internet).")
EVENING_TEXT = ("app Windows: nessun job automatico; i diari si registrano con «Aggiorna dati» dopo la chiusura di Wall "
                "Street (o da soli, se hai attivato l'aggiornamento serale e l'app è aperta)")
JOB_HINT = "(nell'app Windows il report si salva con «Aggiorna dati» dopo la chiusura di Wall Street)"
CHECK_HOST = ("query1.finance.yahoo.com", 443)  # only to tell "no Internet" apart from a failing source

log = logging.getLogger("desktop")


# ---------------------------------------------------------------- folders

def default_dir():
    """%LOCALAPPDATA%\\Nasdaq100Monitor on Windows (NDX_DESKTOP_DIR overrides it: tests and trials on the Mac)."""
    override = os.environ.get("NDX_DESKTOP_DIR")
    if override:
        return os.path.abspath(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_NAME)


def ensure_dirs(base):
    """Creates the data folders at the first start (owner only where the system supports it). Refuses a symbolic link
    and a folder inside the program folder. Returns the resolved data folder."""
    base = os.path.abspath(base)
    if os.path.islink(base):
        raise ValueError("la cartella dei dati non può essere un collegamento")
    real = os.path.realpath(base)                    # checked BEFORE anything is created
    if app_env._under(real, app_env.ROOT) or app_env._under(app_env.ROOT, real):
        raise ValueError("la cartella dei dati deve stare fuori dalla cartella del programma")
    os.makedirs(base, mode=0o700, exist_ok=True)
    real = os.path.realpath(base)
    for d in SUBDIRS:
        p = os.path.join(real, d)
        if os.path.islink(p):
            raise ValueError(f"la cartella {d} non può essere un collegamento")
        os.makedirs(p, mode=0o700, exist_ok=True)
    return real


def paths(base):
    return {d: os.path.join(base, d) for d in SUBDIRS}


def _write_json(path, data):
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- settings

class Settings:
    """dati\\impostazioni.json: only the choices of the app (no personal data)."""
    DEFAULT = {"auto_sera": False}

    def __init__(self, path):
        self.path = path
        self.values = {**self.DEFAULT, **_read_json(path, {})}

    def set(self, **kw):
        for k, v in kw.items():
            if k in self.DEFAULT and isinstance(v, type(self.DEFAULT[k])):
                self.values[k] = v
        _write_json(self.path, self.values)
        return dict(self.values)


# ---------------------------------------------------------------- configuration of the modules

def configure(base, port, setter=setattr, setitem=None):
    """Points every module to the app's data folder and turns on the local access protection. Call it after
    app_env.enable_desktop(base) and after importing server (desktop_app.py does both)."""
    import analysts
    import diaries_status
    import etf
    import etf_holdings
    import etf_prices
    import fundamentals
    import instance_auth
    import macro_calendar
    import market_data_quality
    import opportunity_strategies
    import opportunity_validation
    import portfolio
    import server
    import signals
    p = paths(base)
    dati, cache = p["dati"], p["cache"]
    # public studies shipped with the program: read only from the program folder (never run by the app)
    keep = {(opportunity_validation, "OUT_DIR"): opportunity_validation.OUT_DIR,
            (opportunity_validation, "RECHECK_DIR"): opportunity_validation.RECHECK_DIR,
            (opportunity_validation, "LOG"): opportunity_validation.LOG,
            (opportunity_strategies, "OUT_DIR"): opportunity_strategies.OUT_DIR,
            (market_data_quality, "OUT_DIR"): market_data_quality.OUT_DIR}
    app_env.isolate(dati, setter)                       # everything personal, the diaries and the alerts: dati\
    for (mod, name), v in keep.items():
        setter(mod, name, v)
    setter(app_env, "DATA", os.path.join(dati, "data"))
    setter(server, "CACHE_DIR", cache)
    setter(server, "DAILY_CACHE", os.path.join(cache, "daily.pkl"))
    setter(analysts, "CACHE", os.path.join(cache, "analysts.json"))
    setter(macro_calendar, "CACHE_DIR", cache)
    setter(macro_calendar, "AUTO_CACHE", os.path.join(cache, "macro_auto.json"))
    setter(macro_calendar, "BLS_CACHE", os.path.join(cache, "macro_bls.json"))
    setter(fundamentals, "CACHE", os.path.join(cache, "fundamentals.json"))
    setter(etf_prices, "CACHE", os.path.join(cache, "etf_prices.pkl"))
    setter(etf_holdings, "PUBLIC", os.path.join(cache, "etf_holdings.json"))
    setter(signals, "REPORT_DIR", os.path.join(dati, "reports"))
    os.makedirs(os.path.join(dati, "reports"), exist_ok=True)
    setter(portfolio, "STRICT_UPLOAD", True)
    setter(server, "JOB_HINT", JOB_HINT)
    setter(diaries_status, "evening_job", lambda: EVENING_TEXT)
    try:
        import yfinance as yf
        os.makedirs(os.path.join(cache, "yfinance"), exist_ok=True)
        yf.set_tz_cache_location(os.path.join(cache, "yfinance"))
    except Exception:
        log.warning("yfinance: cartella della cache non impostata")
    origins = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
    setter(server, "INSTANCE", {"label": "", "hosts": [], "origins": origins, "tailscale_logins": [],
                                "password_file": None, "desktop": True, "open_keys": instance_auth.OneTimeKeys()})
    setter(server, "SESSIONS", instance_auth.Sessions())
    (setitem or (lambda d, k, v: d.__setitem__(k, v)))(server.app.config, "MAX_CONTENT_LENGTH", MAX_RESTORE + 64 * 1024)
    app = App(base, port)
    setter(etf, "public", app.etf_public)
    setter(server, "DESKTOP_API", app.handle)
    return app


# ---------------------------------------------------------------- the app (state, update, light refresh, backup)

def online(timeout=5):
    """True when the main price source answers on the network (a TCP connection only, nothing sent)."""
    try:
        with socket.create_connection(CHECK_HOST, timeout=timeout):
            return True
    except OSError:
        return False


class App:
    STEPS = ("Connessione a Internet", "Elenco del Nasdaq-100", "Dati delle società", "Analisti", "Pesi di QQQ",
             "Storico dei prezzi (2 anni)", "Quotazioni di oggi", "Notizie", "Calendario macro", "Bilanci",
             "Portafoglio", "Prezzi degli ETF", "Scheda ETF", "Diari e alert", "Report della sera")

    def __init__(self, base, port):
        self.base, self.port = base, port
        p = paths(base)
        self.state_file = os.path.join(p["dati"], "aggiornamento.json")
        self.etf_file = os.path.join(p["cache"], "etf_scheda.pkl")
        self.settings = Settings(os.path.join(p["dati"], "impostazioni.json"))
        self.lock = threading.Lock()
        self.quit = threading.Event()
        self.state = {"running": False, "current": None, "steps": [], "startedAt": None, "finishedAt": None,
                      "outcome": None, "message": None, "lastComplete": None, "lastSession": None, "lastAuto": None,
                      **{k: v for k, v in _read_json(self.state_file, {}).items()
                         if k in ("finishedAt", "outcome", "message", "lastComplete", "lastSession", "lastAuto", "steps")}}
        self.state["running"] = False
        self.restored = False                # set by desktop_app when a backup was restored at this start
        self.open_browser = None             # set by desktop_app (opens /avvio with a new key)

    # -- state for the page
    def status(self):
        with self.lock:
            s = dict(self.state)
        s["steps"] = list(s.get("steps") or [])
        s["total"] = len(self.STEPS)
        s["settings"] = dict(self.settings.values)
        s["hasData"] = has_data()
        s["firstRun"] = not s["hasData"] and not s.get("finishedAt")
        s["firstRunText"] = FIRST_RUN
        s["dataDir"] = self.base
        s["restored"] = self.restored
        return s

    def _save(self):
        with self.lock:
            keep = {k: self.state.get(k) for k in ("finishedAt", "outcome", "message", "lastComplete", "lastSession",
                                                   "lastAuto", "steps")}
        try:
            _write_json(self.state_file, keep)
        except OSError:
            log.warning("stato dell'aggiornamento non salvato")

    # -- ETF tab: built only by «Aggiorna dati» (a few minutes), then kept on disk between starts
    def etf_public(self):
        import etf
        with etf._lock:
            if not etf._state["data"] and not etf._state["running"]:
                etf._state["error"] = "dati ETF non ancora scaricati: premi «Aggiorna dati» in alto"
            return etf._state["data"]

    def load_etf(self):
        import etf
        try:
            with open(self.etf_file, "rb") as f:            # our own file, written by save_etf below
                saved = pickle.load(f)
            with etf._lock:
                etf._state.update(day=saved.get("day"), data=saved.get("data"), error=None)
        except (OSError, ValueError, EOFError, pickle.UnpicklingError, AttributeError):
            pass

    def build_etf(self):
        import etf
        with etf._lock:
            if etf._state["running"]:
                return
            etf._state["running"] = True
            etf._state["error"] = None
        etf._job()                                          # same computation as the dashboard, here synchronous
        with etf._lock:
            d, day, err = etf._state["data"], etf._state["day"], etf._state["error"]
        if err:
            raise RuntimeError(err)
        if d:
            tmp = self.etf_file + ".tmp"
            with open(tmp, "wb") as f:
                pickle.dump({"day": day, "data": d}, f)
            os.replace(tmp, self.etf_file)

    # -- «Aggiorna dati»
    def start_update(self, source="comando manuale"):
        with self.lock:
            if self.state["running"]:
                return False, "aggiornamento già in corso"
            self.state.update(running=True, current=None, steps=[], startedAt=_now(), outcome=None, message=None)
        threading.Thread(target=self._update, args=(source,), daemon=True, name="aggiornamento").start()
        return True, "aggiornamento avviato"

    def _step(self, name, fn, required=False):
        with self.lock:
            self.state["current"] = name
        t0 = time.time()
        try:
            note = fn()
            status = "ok"
        except Exception as e:                              # only the kind of error: never personal data
            log.warning("aggiornamento: passo «%s» non riuscito (%s)", name, type(e).__name__)
            note, status = _friendly(e), "errore"
        with self.lock:
            self.state["steps"].append({"name": name, "status": status, "note": note if isinstance(note, str) else None,
                                        "seconds": round(time.time() - t0)})
        if status == "errore" and required:
            raise _Stop(note)
        return status == "ok"

    def _update(self, source):
        import server
        try:
            run_update(self, source)
        except _Stop as e:
            with self.lock:
                self.state.update(outcome="non riuscito", message=str(e))
        except Exception as e:
            log.exception("aggiornamento interrotto")
            with self.lock:
                self.state.update(outcome="non riuscito", message=_friendly(e))
        else:
            with self.lock:
                bad = [s["name"] for s in self.state["steps"] if s["status"] != "ok"]
                self.state.update(outcome="parziale" if bad else "completo",
                                  message=(f"non riusciti: {', '.join(bad)}" if bad else None))
                if not bad:
                    self.state["lastComplete"] = _now()
                try:
                    self.state["lastSession"] = server.last_closed_session()
                except Exception:
                    pass
        finally:
            with self.lock:
                self.state.update(running=False, current=None, finishedAt=_now())
            self._save()

    # -- light refresh while the app is open, and the optional evening update
    def worker(self):
        import portfolio
        import server
        load_local(self)
        while not self.quit.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("aggiornamento leggero non riuscito")
            delay = server.QUOTE_REFRESH_S if server.market_status() in ("open", "pre", "post") else 5 * 60
            self.quit.wait(delay)
        portfolio.on_quotes = None

    def tick(self, now=None):
        import portfolio
        import server
        with self.lock:
            running = self.state["running"]
        if running:
            return "aggiornamento in corso"
        if self.evening_due(now):
            with self.lock:
                self.state["lastAuto"] = server.last_closed_session()
            self.start_update(source="dashboard")
            return "aggiornamento serale avviato"
        if not has_data() or not self.state.get("finishedAt"):
            return "nessun dato: si aspetta «Aggiorna dati»"
        server.store.refresh_intraday()
        server.store.build()
        portfolio.refresh()
        return "quotazioni aggiornate"

    def evening_due(self, now=None):
        """The optional evening update: after the NYSE close (+20 minutes) of a trading day, once per session."""
        import market_calendar
        import server
        if not self.settings.values.get("auto_sera"):
            return False
        now = now or datetime.now(server.ET)
        if not market_calendar.is_trading_day(now.date()):
            return False
        if now.hour * 60 + now.minute < market_calendar.close_minute(now) + 20:
            return False
        day = now.date().isoformat()
        return self.state.get("lastAuto") != day and self.state.get("lastSession") != day

    # -- the page's API (/api/app/<action>, behind the session, CSRF and Origin checks of server.instance_guard)
    def handle(self, action):
        from flask import jsonify, request
        import server
        if action == "ping":                                 # public: only says "this is the app"; with the secret, opens
            if request.method == "POST" and self.secret_ok(request.headers.get("X-App-Secret")):
                if self.open_browser:
                    threading.Thread(target=self.open_browser, daemon=True).start()
                return jsonify(ok=True, opened=True)
            return jsonify(app=TITLE)
        if request.method == "GET" and action == "stato":
            return jsonify(self.status())
        if request.method != "POST" or not server.local_request():
            return jsonify(error="richiesta non ammessa"), 403
        if action == "aggiorna":
            ok, msg = self.start_update()
            return jsonify(ok=ok, message=msg, status=self.status()), (200 if ok else 409)
        if action == "impostazioni":
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                return jsonify(error="dati non validi"), 400
            return jsonify(settings=self.settings.set(**{k: v for k, v in body.items() if k in Settings.DEFAULT}))
        if action == "chiudi":                               # a moment later: the page first opens /static/chiuso.html
            threading.Timer(1.5, self.quit.set).start()
            return jsonify(ok=True)
        if action == "backup":
            name, data = make_backup(self.base)
            resp = server.app.response_class(data, mimetype="application/zip")
            resp.headers["Content-Disposition"] = f'attachment; filename="{name}"'
            return resp
        if action == "ripristina":
            try:
                n = stage_restore(self.base, request.get_data(cache=False))
            except ValueError as e:
                return jsonify(error=str(e)), 400
            return jsonify(ok=True, files=n, message="Backup controllato. Chiudi e riapri Nasdaq-100 Monitor per completare "
                                                     "il ripristino (i dati attuali restano in una copia di sicurezza).")
        return jsonify(error="not found"), 404

    secret = None

    def secret_ok(self, value):
        import hmac
        return bool(self.secret and isinstance(value, str) and hmac.compare_digest(value, self.secret))


class _Stop(Exception):
    pass


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _friendly(e):
    """A short Italian reason, without file names, values or personal data."""
    import requests
    if isinstance(e, _Stop):
        return str(e)
    if isinstance(e, (requests.ConnectionError, requests.Timeout, socket.timeout, TimeoutError, ConnectionError,
                      socket.gaierror)):
        return "fonte non raggiungibile (connessione assente o lenta)"
    if isinstance(e, PermissionError):
        return "file non scrivibile nella cartella dei dati"
    return f"non riuscito ({type(e).__name__})"


def has_data():
    import server
    with server.store.lock:
        return bool(server.store.constituents) and bool(server.store.daily)


def load_local(app):
    """At start: the data already on this PC (cache\\), never a download. First start: the welcome message."""
    import portfolio
    import server
    try:
        server.load_public()                                 # reads cache\ (configure moved CACHE_DIR there)
    except Exception:
        log.exception("dati locali non letti")
    app.load_etf()
    portfolio.on_quotes = server.save_portfolio_history
    if has_data():
        server.store.build()
        server.store.error = None
        if app.state.get("finishedAt"):
            try:
                portfolio.refresh()
            except Exception:
                log.warning("portafoglio non letto all'avvio")
    else:
        server.store.error = FIRST_RUN
    server.store.ready.set()


def run_update(app, source):
    """The steps of «Aggiorna dati»: the same functions and order as server.run_daily_job (the evening job of the Mac),
    with progress for the page and without its long waits. Every rule stays in those functions."""
    import analysts
    import etf_catalog
    import etf_prices
    import fundamentals
    import history
    import job_status
    import macro_calendar
    import market_calendar
    import portfolio
    import server
    import signals
    from concurrent.futures import ThreadPoolExecutor
    st = server.store
    ctx = {}

    def net():
        if not online():
            raise _Stop("Internet non raggiungibile: nessun dato è stato cambiato. Riprova quando sei connesso.")
    app._step("Connessione a Internet", net, required=True)
    run = job_status.Run("completo", datetime.now(server.ET))          # only once there is something to record

    def constituents():
        rows = server.load_constituents()
        if not rows:
            raise _Stop("elenco del Nasdaq-100 non disponibile: riprova più tardi")
        st.constituents = rows
        ctx["tickers"] = [c["ticker"] for c in rows]
    app._step("Elenco del Nasdaq-100", constituents, required=True)
    tickers = ctx["tickers"]
    app._step("Dati delle società", lambda: setattr(st, "infos", server.load_infos(tickers)))
    app._step("Analisti", lambda: setattr(st, "analysts", analysts.load(tickers) if not analysts.is_fresh()
                                         else analysts.cached_data()))
    app._step("Pesi di QQQ", lambda: setattr(st, "top_weights", server.qqq_top_weights() or st.top_weights))

    def daily():
        st.refresh_daily()
        if not st.daily:
            raise _Stop("storico dei prezzi non disponibile: riprova più tardi")
        return server._bars_note()
    app._step("Storico dei prezzi (2 anni)", daily, required=True)
    app._step("Quotazioni di oggi", st.refresh_intraday)

    def headlines():
        with ThreadPoolExecutor(4) as ex:
            st.news_all = dict(zip(tickers, ex.map(lambda t: server.news(t, 40), tickers)))
        st.news_at = time.time()
    app._step("Notizie", headlines)
    st.build()
    st.error = None
    st.ready.set()
    run.step("prezzi", note=server._bars_note())
    app._step("Calendario macro", macro_calendar.refresh)

    def statements():
        fundamentals.refresh(tickers)
        server._inv_invalidate()
    app._step("Bilanci", statements)

    def mine():
        portfolio.refresh()
        for _ in range(180):                                 # tickers of the positions are matched in the background
            if not portfolio._state["resolving"]:
                break
            time.sleep(1)
        portfolio.refresh_quotes()
        with st.lock:
            snap, infos = st.snapshot, dict(st.infos)
        pf = portfolio.snapshot(snap, infos)
        if pf.get("positions"):
            history.record(pf)
            return "fotografia del giorno salvata"
        return "nessun portafoglio caricato"
    app._step("Portafoglio", mine)

    def etf_closes():
        if etf_prices.due(etf_prices.load(), datetime.now(server.ROME_TZ)):
            etf_prices.save(etf_prices.build(server.download, etf_catalog.load()))
    app._step("Prezzi degli ETF", etf_closes)
    app._step("Scheda ETF", app.build_etf)

    def diaries():
        server.save_signal_diary()
        server.save_etf_scan_diary(source=source)
        msg = server.save_opportunity_diary(source=source)
        server.save_etf_scan_diary(source=source)
        alerts = server.save_alerts(source=source)
        server.save_etf_diary()
        server.save_pos_diary()
        run.step("catena dei diari", note=msg)
        return "; ".join(str(x) for x in (msg, alerts) if x)
    app._step("Diari e alert", diaries)

    def report():
        now = datetime.now(server.ET)
        rid = f"{now:%Y-%m-%d}_close"
        after = now.hour * 60 + now.minute >= market_calendar.close_minute(now)
        if market_calendar.is_trading_day(now.date()) and after and rid not in signals.list_reports():
            signals.run(notify_user=False)
            return "salvato"
        return "solo dopo la chiusura di una seduta"
    app._step("Report della sera", report)
    run.finish(datetime.now(server.ET), session=server.last_closed_session())


# ---------------------------------------------------------------- backup and restore (only the data of this PC)

def make_backup(base):
    """Zip of dati\\ (never cache\\ or logs\\), also kept in backup\\. Returns (file name, bytes)."""
    p = paths(base)
    name = f"Nasdaq100Monitor-backup-{datetime.now():%Y-%m-%d_%H%M%S}.zip"
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(BACKUP_MARK, json.dumps({"app": TITLE, "schema": 1, "created": _now()}))
        for root, dirs, files in os.walk(p["dati"]):
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, p["dati"]).replace(os.sep, "/")
                if os.path.islink(full) or fn.endswith(SKIP_SUFFIX) or rel.split("/")[0] not in BACKUP_TOP:
                    continue
                z.write(full, rel)
                n += 1
    data = buf.getvalue()
    tmp = os.path.join(p["backup"], name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, os.path.join(p["backup"], name))
    log.info("backup: %d file", n)
    return name, data


def _safe_member(name):
    """A relative path inside dati\\ (forward slashes), or None for anything that could leave it."""
    if not name or "\\" in name or name.startswith("/") or ":" in name or "\0" in name:
        return None
    parts = name.split("/")
    if any(x in ("", ".", "..") for x in parts[:-1]) or parts[-1] in (".", ".."):
        return None
    if parts[0] not in BACKUP_TOP:
        return None
    return parts


def stage_restore(base, data):
    """Checks an uploaded backup and unpacks it into a NEW folder next to dati\\; the swap happens at the next start
    (apply_pending_restore), so nothing in use is overwritten. Raises ValueError with a short reason."""
    if not data or len(data) > MAX_RESTORE:
        raise ValueError("file assente o troppo grande")
    if not data.startswith(b"PK\x03\x04"):
        raise ValueError("non è un file di backup (.zip) di Nasdaq-100 Monitor")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("file di backup danneggiato") from None
    with z:
        infos = z.infolist()
        if BACKUP_MARK not in z.namelist():
            raise ValueError("non è un backup di Nasdaq-100 Monitor")
        if len(infos) > MAX_RESTORE_FILES or sum(i.file_size for i in infos) > MAX_RESTORE_UNPACKED:
            raise ValueError("backup troppo grande")
        members = []
        for i in infos:
            if i.filename == BACKUP_MARK or i.is_dir():
                continue
            mode = (i.external_attr >> 16) & 0o170000
            if mode and mode != stat.S_IFREG:
                raise ValueError("il backup contiene collegamenti o file speciali")
            parts = _safe_member(i.filename)
            if parts is None:
                raise ValueError("il backup contiene percorsi non ammessi")
            members.append((i, parts))
        target = os.path.join(base, RESTORE_DIR)
        if os.path.lexists(target):
            _remove_tree(target)
        os.makedirs(target, mode=0o700)
        try:
            for i, parts in members:
                dest = os.path.join(target, *parts)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(i) as src, open(dest, "xb") as out:
                    out.write(src.read())
        except Exception:
            _remove_tree(target)
            raise
    return len(members)


def _remove_tree(path):
    import shutil
    if os.path.islink(path):
        os.remove(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)


def apply_pending_restore(base):
    """At start, before anything reads the data: dati\\ → backup\\dati-prima-del-ripristino-<time>, then the checked
    copy becomes dati\\. Returns True when a restore was applied."""
    p = paths(base)
    staged = os.path.join(base, RESTORE_DIR)
    if not os.path.isdir(staged) or os.path.islink(staged):
        return False
    old = os.path.join(p["backup"], f"dati-prima-del-ripristino-{datetime.now():%Y-%m-%d_%H%M%S}")
    if os.path.isdir(p["dati"]):
        os.replace(p["dati"], old)
    os.replace(staged, p["dati"])
    return True


# ---------------------------------------------------------------- one copy of the app at a time

LOCK_FILE = "app.json"


def read_lock(base):
    return _read_json(os.path.join(base, LOCK_FILE), {})


def write_lock(base, port, secret):
    _write_json(os.path.join(base, LOCK_FILE), {"port": port, "secret": secret, "started": _now()})


def remove_lock(base):
    try:
        os.remove(os.path.join(base, LOCK_FILE))
    except OSError:
        pass


def ask_running_copy(base, timeout=3):
    """True when another copy of the app is running with these data (it then opens the browser itself)."""
    import urllib.request
    info = read_lock(base)
    port, secret = info.get("port"), info.get("secret")
    if not isinstance(port, int) or not isinstance(secret, str):
        return False
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/app/ping", data=b"", method="POST",
                                 headers={"X-App-Secret": secret})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never through a system proxy
    try:
        with opener.open(req, timeout=timeout) as r:
            return bool(json.load(r).get("opened"))
    except Exception:
        return False


def _port_free(port):
    """Windows: a port another program already uses must not be shared (SO_REUSEADDR there would allow it)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def bind_server(app, ports=PORTS):
    """The first free port of `ports` on 127.0.0.1 only. Returns (server, port)."""
    from werkzeug import serving
    from werkzeug.serving import make_server
    if os.name == "nt":
        serving.BaseWSGIServer.allow_reuse_address = False      # this process only: no port sharing on Windows
    last = None
    for port in ports:
        if os.name == "nt" and not _port_free(port):
            continue
        try:
            return make_server("127.0.0.1", port, app, threaded=True), port
        except (OSError, SystemExit) as e:          # werkzeug exits when the port is in use
            last = e
    raise RuntimeError(f"nessuna porta libera tra {ports[0]} e {ports[-1]}") from last


def patch_windows_replace():
    """Windows only: replacing a file that another thread is reading fails for a moment (PermissionError). Retry a few
    times instead of losing the write. Nothing changes on the Mac."""
    if os.name != "nt" or getattr(os.replace, "_ndx", False):
        return
    original = os.replace

    def replace(src, dst, *a, **kw):
        for i in range(20):
            try:
                return original(src, dst, *a, **kw)
            except PermissionError:
                if i == 19:
                    raise
                time.sleep(0.05 * (i + 1))
    replace._ndx = True
    os.replace = replace
