"""Istanza separata di Nasdaq-100 Monitor per un altro utente (Fase 9A), per esempio la dashboard del secondo utente.

Stesso codice della dashboard personale, processo e dati personali separati:

    .venv/bin/python instance.py crea ~/NasdaqMonitor-istanze/utente2 --etichetta "Portafoglio secondario" --porta 8110
    .venv/bin/python instance.py password ~/NasdaqMonitor-istanze/utente2
    .venv/bin/python instance.py verifica ~/NasdaqMonitor-istanze/utente2
    .venv/bin/python instance.py avvia ~/NasdaqMonitor-istanze/utente2          # in primo piano (istanza.sh: in background)
    .venv/bin/python instance.py stato|ferma ~/NasdaqMonitor-istanze/utente2
    .venv/bin/python instance.py backup ~/NasdaqMonitor-istanze/utente2 ~/Backup/utente2.tar.gz
    .venv/bin/python instance.py ripristina ~/Backup/utente2.tar.gz ~/NasdaqMonitor-istanze/utente2

Isolamento (applicato dal backend, non dalla pagina):
- la cartella privata dell'istanza sta FUORI dal progetto, in una cartella contenitore marcata `.ndx-istanze`; tutti i
  dati personali dell'utente (export, Preferiti, classificazioni, zainetto, regole, storico, diari personali) sono lì;
- `app_env.enable_instance`, acceso PRIMA di importare il resto: ogni lettura, elenco o modifica di `portafoglio/` e
  `watchlist.json` del proprietario e delle cartelle degli altri utenti viene bloccata prima che avvenga; ogni scrittura
  nella cartella del progetto (codice, cache/, data/ con i diari pubblici, reports/) viene bloccata; il processo non può
  mai essere autorizzato a scrivere i diari di produzione;
- i dati pubblici pesanti si LEGGONO dai file che la dashboard personale e il job MARKET-ONLY delle 23:00 già scrivono
  (`server.load_public`, `server.follower_worker`); l'istanza scarica in memoria solo quotazioni del giorno, notizie,
  scheda ETF, trimestrali mancanti e prezzi delle proprie posizioni;
- ascolta solo su 127.0.0.1; ogni pagina e API richiede la sessione (password, `instance_auth`), ogni modifica il token
  CSRF e un'Origin ammessa; via Tailscale Serve è accettato solo un account elencato in `tailscale_login`.
Nessun servizio automatico viene installato: l'istanza si avvia e si ferma a mano (istanza.sh)."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = "istanza.json"
PASSWORD = "accesso.json"
PIDFILE = "istanza.pid"
LOGDIR = "logs"
RESERVED_PORTS = (8100, 8101)                    # the personal dashboard and the preview
BACKUP_SKIP = (LOGDIR, PIDFILE)                  # never in a backup: logs and the process number
MAX_BACKUP_MEMBERS = 20000


# ---------------------------------------------------------------- configuration

def read_config(d):
    with open(os.path.join(d, CONFIG)) as f:
        cfg = json.load(f)
    port = int(cfg.get("porta") or 0)
    if not 1024 < port < 65536 or port in RESERVED_PORTS:
        raise ValueError(f"porta non ammessa ({port}): non 8100 (dashboard personale) né 8101 (anteprima)")
    hosts = [h.strip().lower() for h in cfg.get("host_pubblici") or [] if isinstance(h, str) and h.strip()]
    for h in hosts:
        if not h.endswith(".ts.net") or "/" in h or ":" in h:
            raise ValueError(f"host pubblico non ammesso ({h}): solo il nome Tailscale del Mac, per esempio mac.tailXXXX.ts.net")
    logins = [x.strip().lower() for x in cfg.get("tailscale_login") or [] if isinstance(x, str) and x.strip()]
    return {"name": cfg.get("nome") or os.path.basename(d), "label": (cfg.get("etichetta") or "")[:40], "port": port,
            "hosts": hosts, "tailscale_logins": logins,
            "origins": [f"http://127.0.0.1:{port}", f"http://localhost:{port}"] + [f"https://{h}" for h in hosts]}


def private_dir(path):
    import app_env
    return app_env.check_instance_dir(path)


def create(path, label, port):
    """New empty private folder (permissions 700) with its configuration. Never copies anything from portafoglio/."""
    import app_env
    d = os.path.abspath(os.path.expanduser(path))
    parent = os.path.dirname(d)
    if os.path.exists(d) and os.listdir(d):
        raise SystemExit(f"{d} esiste già e non è vuota: scegli un'altra cartella")
    if os.path.realpath(parent) in ("/", os.path.realpath(os.path.expanduser("~"))):
        raise SystemExit("metti la cartella dentro una cartella contenitore, per esempio ~/NasdaqMonitor-istanze/utente2")
    os.makedirs(parent, mode=0o700, exist_ok=True)
    marker = os.path.join(parent, app_env.INSTANCE_MARKER)
    if not os.path.exists(marker):
        with open(marker, "w") as f:
            f.write("Cartella delle istanze separate di Nasdaq-100 Monitor: ogni sottocartella è di un solo utente.\n")
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    private_dir(d)                                  # same checks as at start (outside the project, marker, no link)
    cfg = {"nome": os.path.basename(d), "etichetta": label, "porta": port, "host_pubblici": [], "tailscale_login": []}
    with open(os.path.join(d, CONFIG), "w") as f:
        json.dump(cfg, f, indent=1, ensure_ascii=False)
    read_config(d)
    print(f"creata {d} (porta {port}). Ora imposta la password: instance.py password {d}")


def set_password(path, from_stdin=False):
    import instance_auth as ia
    d = private_dir(path)
    if from_stdin:
        pw = sys.stdin.readline().rstrip("\n")
    else:
        pw = getpass.getpass("Nuova password (almeno 10 caratteri): ")
        if getpass.getpass("Ripeti la password: ") != pw:
            raise SystemExit("le due password sono diverse: niente è cambiato")
    try:
        ia.save_password(os.path.join(d, PASSWORD), pw)
    except ValueError as e:
        raise SystemExit(str(e))
    print("password salvata (solo la sua impronta scrypt, permessi 600). Le sessioni aperte restano valide fino al riavvio.")


# ---------------------------------------------------------------- checks

def checks(path):
    """List of (ok, text) about a private folder, without starting anything and without reading personal content."""
    out = []
    try:
        d = private_dir(path)
        out.append((True, "cartella privata fuori dal progetto, in un contenitore marcato, non un collegamento"))
    except ValueError as e:
        return [(False, str(e))]
    mode = stat.S_IMODE(os.stat(d).st_mode)
    out.append((mode & 0o077 == 0, f"permessi della cartella {oct(mode)} (servono 700: nessun altro utente del Mac)"))
    try:
        cfg = read_config(d)
        out.append((True, f"configurazione valida: porta {cfg['port']}, etichetta «{cfg['label']}»"))
    except (OSError, ValueError) as e:
        return out + [(False, f"configurazione non valida: {e}")]
    pw = os.path.join(d, PASSWORD)
    out.append((os.path.exists(pw), "password impostata" if os.path.exists(pw) else "password NON impostata: instance.py password"))
    if os.path.exists(pw):
        out.append((stat.S_IMODE(os.stat(pw).st_mode) & 0o077 == 0, "file della password leggibile solo dal proprietario"))
    links = [os.path.join(r, n) for r, ds, fs in os.walk(d) for n in ds + fs if os.path.islink(os.path.join(r, n))]
    out.append((not links, "nessun collegamento simbolico nella cartella" if not links else f"{len(links)} collegamenti simbolici da togliere"))
    out.append((bool(cfg["hosts"]) == bool(cfg["tailscale_logins"]),
                "accesso remoto: nome Tailscale e account autorizzati impostati insieme" if cfg["hosts"] else
                "accesso remoto non configurato (solo da questo Mac): va bene finché non lo autorizzi"))
    out.append((not port_busy(cfg["port"]) or running(d), f"porta {cfg['port']} libera" if not port_busy(cfg["port"])
                else f"porta {cfg['port']} occupata" + (" (da questa istanza)" if running(d) else " da un altro programma")))
    return out


def port_busy(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------- process

def running(d):
    """Process number of this instance if it is running (checked against its command line), else None."""
    try:
        with open(os.path.join(d, PIDFILE)) as f:
            pid = int(f.read().strip())
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    except (OSError, ValueError):
        return None
    return pid if "instance.py" in cmd and os.path.realpath(d) in cmd else None


def stop(path):
    d = private_dir(path)
    pid = running(d)
    if not pid:
        print("l'istanza non è in esecuzione")
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not running(d):
            break
        time.sleep(0.1)
    print(f"istanza fermata (processo {pid}); la dashboard personale non è stata toccata")


def start(path):
    """Start the instance in this process (foreground). The protections are turned on BEFORE importing the server."""
    os.environ["NDX_ENV"] = "istanza"
    os.umask(0o077)                                          # every new file of the user: readable only by the owner
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import app_env
    assert app_env.env() == "istanza", app_env.env()
    d = app_env.enable_instance(path)                       # from here: owner's data unreadable, project read only
    cfg = read_config(d)
    if not os.path.exists(os.path.join(d, PASSWORD)):
        raise SystemExit("password non impostata: instance.py password " + d)
    if port_busy(cfg["port"]):
        raise SystemExit(f"la porta {cfg['port']} è già occupata")
    os.makedirs(os.path.join(d, LOGDIR), mode=0o700, exist_ok=True)
    import logging
    handler = logging.FileHandler(os.path.join(d, LOGDIR, "server.log"))
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
    logging.getLogger().addHandler(handler)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)       # no access log: it would list what the user looks at
    prepare(d, cfg)
    import server
    with open(os.path.join(d, PIDFILE), "w") as f:
        f.write(str(os.getpid()))
    threading.Thread(target=server.follower_worker, daemon=True).start()
    print(f"istanza «{cfg['label']}» su http://127.0.0.1:{cfg['port']} (solo questo Mac; via Tailscale solo se autorizzato)", flush=True)
    try:
        server.app.run(host="127.0.0.1", port=cfg["port"], debug=False, threaded=True)
    finally:
        try:
            os.remove(os.path.join(d, PIDFILE))
        except OSError:
            pass


def prepare(d, cfg, setter=setattr):
    """Points the server to this user's folder and turns off every writer of shared data (the guard blocks them anyway:
    these replacements avoid the failed attempts). Used by start() and by the tests (setter = monkeypatch.setattr)."""
    import app_env
    import earnings
    import etf_holdings
    import instance_auth
    import macro_calendar
    import portfolio
    import server
    app_env.isolate(d, setter, public_reads=True, shared_public=True)
    setter(portfolio, "STRICT_UPLOAD", True)
    setter(server, "INSTANCE", dict(cfg, password_file=os.path.join(d, PASSWORD)))
    setter(server, "SESSIONS", instance_auth.Sessions())
    server.app.config["MAX_CONTENT_LENGTH"] = portfolio.MAX_UPLOAD + 64 * 1024
    note = "istanza separata: i diari pubblici e gli alert li registra solo la dashboard personale o il job serale"
    for name in ("save_opportunity_diary", "save_etf_scan_diary", "save_alerts"):
        setter(server, name, lambda *a, **k: note)
    setter(server, "refresh_fundamentals", lambda *a, **k: False)
    setter(server, "refresh_etf_prices", lambda *a, **k: None)
    setter(server.store, "refresh_daily", lambda *a, **k: None)
    setter(server.store, "refresh_analysts", lambda *a, **k: None)
    setter(macro_calendar, "refresh", lambda: None)           # dates and BLS values: from the shared files (load_public)
    setter(macro_calendar, "check_official", lambda: None)
    setter(macro_calendar, "refresh_bls", lambda: None)
    setter(etf_holdings, "public", lambda universe: etf_holdings._read(etf_holdings.PUBLIC))   # ETF compositions: shared
    mem = {"day": None, "data": {}}

    def reports(tickers):
        """Earnings: the shared daily file; the missing tickers downloaded into memory only (never written)."""
        cached = server.read_daily_cache(earnings.CACHE) or {}
        if mem["day"] != server.today_et():
            mem.update(day=server.today_et(), data={})
        for t in tickers:
            if t not in cached and t not in mem["data"]:
                mem["data"][t] = earnings._dates(t)
        return {t: ((cached.get(t) or {}).get("reports") if t in cached else mem["data"].get(t)) or [] for t in tickers}
    setter(earnings, "reports", reports)


# ---------------------------------------------------------------- backup and restore

def backup(path, dest):
    """Archive (.tar.gz, permissions 600) of this user's folder only, without logs. Never reads anything else."""
    d = private_dir(path)
    dest = os.path.abspath(os.path.expanduser(dest))
    if os.path.commonpath([dest, d]) == d:
        raise SystemExit("salva il backup fuori dalla cartella dell'istanza")
    import app_env
    if os.path.commonpath([dest, app_env.ROOT]) == app_env.ROOT:
        raise SystemExit("salva il backup fuori dalla cartella del progetto (non deve finire in Git)")
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f, tarfile.open(fileobj=f, mode="w:gz") as tar:
        for name in sorted(os.listdir(d)):
            if name in BACKUP_SKIP or name.startswith(".caricamento"):
                continue
            tar.add(os.path.join(d, name), arcname=name, recursive=True,
                    filter=lambda ti: None if ti.issym() or ti.islnk() or ".caricamento" in ti.name else ti)
    print(f"backup salvato in {dest} (solo la cartella di questa istanza)")


def restore(archive, path):
    """Restores a backup into a NEW or empty folder (never over existing data). Refuses absolute paths, '..', links and
    special files: a manipulated archive cannot write outside the folder."""
    d = os.path.abspath(os.path.expanduser(path))
    if os.path.exists(d) and os.listdir(d):
        raise SystemExit("la cartella di destinazione deve essere nuova o vuota: niente viene sovrascritto")
    with tarfile.open(os.path.expanduser(archive), "r:gz") as tar:
        members = tar.getmembers()
        if len(members) > MAX_BACKUP_MEMBERS:
            raise SystemExit("archivio troppo grande")
        for m in members:
            parts = m.name.replace("\\", "/").split("/")
            if m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir()):
                raise SystemExit("archivio non valido: contiene percorsi o elementi non ammessi")
        os.makedirs(d, mode=0o700, exist_ok=True)
        private_dir(d)
        tar.extractall(d, members=members, filter="data")
    for r, ds, fs in os.walk(d):
        for n in ds:
            os.chmod(os.path.join(r, n), 0o700)
        for n in fs:
            os.chmod(os.path.join(r, n), 0o600)
    os.chmod(d, 0o700)
    read_config(d)
    print(f"ripristinata in {d}")


# ---------------------------------------------------------------- command line

def main(argv=None):
    ap = argparse.ArgumentParser(description="Istanza separata di Nasdaq-100 Monitor (Fase 9A)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crea")
    c.add_argument("dir")
    c.add_argument("--etichetta", default="Portafoglio secondario")
    c.add_argument("--porta", type=int, default=8110)
    p = sub.add_parser("password")
    p.add_argument("dir")
    p.add_argument("--da-stdin", action="store_true")
    for name in ("verifica", "avvia", "stato", "ferma"):
        sub.add_parser(name).add_argument("dir")
    b = sub.add_parser("backup")
    b.add_argument("dir")
    b.add_argument("dest")
    r = sub.add_parser("ripristina")
    r.add_argument("archivio")
    r.add_argument("dir")
    a = ap.parse_args(argv)
    if a.cmd == "crea":
        create(a.dir, a.etichetta, a.porta)
    elif a.cmd == "password":
        set_password(a.dir, a.da_stdin)
    elif a.cmd == "verifica":
        res = checks(a.dir)
        for ok, text in res:
            print(("✓ " if ok else "✗ ") + text)
        sys.exit(0 if all(ok for ok, _ in res) else 1)
    elif a.cmd == "avvia":
        start(a.dir)
    elif a.cmd == "stato":
        d = private_dir(a.dir)
        pid = running(d)
        print(f"in esecuzione (processo {pid}, porta {read_config(d)['port']})" if pid else "ferma")
    elif a.cmd == "ferma":
        stop(a.dir)
    elif a.cmd == "backup":
        backup(a.dir, a.dest)
    elif a.cmd == "ripristina":
        restore(a.archivio, a.dir)


if __name__ == "__main__":
    main()
