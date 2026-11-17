"""Fase 9B: prova dell'eseguibile vero, da lanciare su Windows dopo PyInstaller (build_windows.ps1 lo fa da solo).

    python packaging/prova_exe.py "build/dist/Nasdaq-100 Monitor/Nasdaq-100 Monitor.exe" [--con-internet]

Usa una cartella dei dati temporanea (mai quella vera di %LOCALAPPDATA%) e controlla: avvio, cartelle create, apertura
con la chiave, pagina con d3 locale, ascolto SOLO su 127.0.0.1 (netstat), primo avvio senza download, seconda copia che
non parte, chiusura con «Chiudi l'app» e nessun processo rimasto. Con --con-internet anche «Aggiorna dati» completo
(5-15 minuti, scarica dati pubblici di mercato)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http(url, data=None, headers=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        r = urllib.request.build_opener(NoRedirect).open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        r = e
    return getattr(r, "status", None) or r.code, dict(r.headers), r.read()


def ok(cond, text):
    print(("✓ " if cond else "✗ ") + text, flush=True)
    if not cond:
        raise SystemExit(1)


def listening_addresses(port):
    if os.name != "nt":
        return None
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    return sorted({line.split()[1] for line in out.splitlines()
                   if "LISTENING" in line and line.split()[1].endswith(f":{port}")})


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    exe = argv[0]
    online = "--con-internet" in argv
    tmp = tempfile.mkdtemp(prefix="ndx-prova-")
    base = os.path.join(tmp, "LocalAppData", "Nasdaq100Monitor")
    urls = os.path.join(tmp, "urls.txt")
    env = {**os.environ, "NDX_PROVA_URL_FILE": urls}
    cmd = [exe, "--senza-finestra", "--cartella", base]
    p = subprocess.Popen(cmd, env=env)
    try:
        for _ in range(600):                          # first start of a frozen program: up to a minute
            if os.path.exists(urls) and open(urls, encoding="utf-8").read().strip():
                break
            ok(p.poll() is None, "il programma resta acceso durante l'avvio")
            time.sleep(0.1)
        url = open(urls, encoding="utf-8").read().strip().splitlines()[-1]
        ok(bool(re.fullmatch(r"http://127\.0\.0\.1:81[34]\d/avvio\?k=[\w-]{20,}", url)), "apre il browser con la chiave")
        port = int(url.split(":")[2].split("/")[0])
        ok(sorted(os.listdir(base)) == ["app.json", "backup", "cache", "dati", "logs"], "cartelle personali create")
        addrs = listening_addresses(port)
        if addrs is not None:
            ok(addrs == [f"127.0.0.1:{port}"], f"ascolta solo su 127.0.0.1 ({addrs})")
        origin = url.split("/avvio")[0]
        s, h, _ = http(url)
        ok(s == 303 and "Set-Cookie" in h, "la chiave apre la sessione")
        cookie = h["Set-Cookie"].split(";")[0]
        s, _, _ = http(url)
        ok(s == 403 or s == 303, "la chiave non vale una seconda volta per un altro browser")
        s, _, body = http(origin + "/", headers={"Cookie": cookie})
        page = body.decode("utf-8")
        ok(s == 200 and 'name="ndx-desktop"' in page and "/static/vendor/d3.min.js" in page and "cdn.jsdelivr" not in page,
           "pagina dell'app con d3 locale")
        csrf = re.search(r'name="ndx-csrf" content="([^"]+)"', page).group(1)
        h = {"Cookie": cookie, "Origin": origin, "X-CSRF-Token": csrf, "X-Requested-With": "ndx-dashboard"}
        s, _, body = http(origin + "/api/app/stato", headers={"Cookie": cookie})
        st = json.loads(body)
        ok(s == 200 and st["firstRun"] and not st["running"], "primo avvio: nessun download senza «Aggiorna dati»")
        s, _, body = http(origin + "/static/vendor/d3.min.js")
        ok(s == 200 and body.startswith(b"// https://d3js.org v7.9.0"), "d3 servito dal programma")
        s, _, _ = http(origin + "/api/portfolio", headers={"Cookie": cookie})
        ok(s == 200, "portafoglio (vuoto) leggibile con la sessione")
        s, _, _ = http(origin + "/api/portfolio")
        ok(s == 401, "senza sessione nessun dato")
        r2 = subprocess.run(cmd, env=env, timeout=120)
        ok(r2.returncode == 0 and len(open(urls, encoding="utf-8").read().strip().splitlines()) == 2,
           "una seconda apertura riapre il browser e non avvia un secondo server")
        if online:
            s, _, _ = http(origin + "/api/app/aggiorna", data=b"", headers=h)
            ok(s == 200, "«Aggiorna dati» avviato")
            t0 = time.time()
            while time.time() - t0 < 30 * 60:
                time.sleep(10)
                st = json.loads(http(origin + "/api/app/stato", headers={"Cookie": cookie})[2])
                if not st["running"]:
                    break
            print("   passi:", ", ".join(f"{x['name']}={x['status']}" for x in st["steps"]))
            ok(st["outcome"] in ("completo", "parziale"), f"aggiornamento finito: {st['outcome']} {st.get('message') or ''}")
            s, _, body = http(origin + "/api/snapshot", headers={"Cookie": cookie}, timeout=120)
            ok(s == 200 and len(json.loads(body).get("stocks") or []) >= 90, "mercato con i titoli del Nasdaq-100")
            for path in ("/api/macro", "/api/brief", "/api/alerts", "/api/opportunities", "/api/etf", "/api/decisions"):
                s, _, _ = http(origin + path, headers={"Cookie": cookie}, timeout=180)
                ok(s == 200, f"{path} risponde")
        s, _, _ = http(origin + "/api/app/chiudi", data=b"", headers=h)
        ok(s == 200, "«Chiudi l'app» accettato")
        ok(p.wait(timeout=60) == 0, "il programma si chiude da solo")
        ok(not os.path.exists(os.path.join(base, "app.json")), "nessun blocco rimasto")
        if os.name == "nt":
            time.sleep(1)
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Nasdaq-100 Monitor.exe"], capture_output=True,
                                 text=True).stdout
            ok("Nasdaq-100 Monitor.exe" not in out, "nessun processo rimasto acceso")
            ok(listening_addresses(port) == [], "porta liberata")
        logs = open(os.path.join(base, "logs", "app.log"), encoding="utf-8").read()
        ok("avvio?k=" not in logs, "nessuna chiave nei log")
        print("PROVA DELL'ESEGUIBILE RIUSCITA")
        return 0
    finally:
        if p.poll() is None:
            p.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
