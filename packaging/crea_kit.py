"""Fase 9B: «kit di build» - il codice e i SOLI file pubblici necessari per fare la build su un PC Windows, senza Git.

    python packaging/crea_kit.py DESTINAZIONE.zip

Elenco chiuso: moduli Python, pagina (static/), test, packaging/, catalogo ETF, file JSON pubblici, tre report pubblici
dei test e i riepiloghi degli studi pubblici. Mai: portafoglio/, watchlist.json, cache/, diari e database (data/*.sqlite3),
report della sera, log, .venv, .git, .claude, archivi. Il kit è ricontrollato dopo la creazione (stessa lista vietata
del pacchetto). Non carica nulla da nessuna parte: crea solo un file locale."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ROOT_FILES = ["*.py", "*.sh", "*.md", "requirements*.txt", ".gitignore", "*.json"]
ROOT_DENY = {"watchlist.json", "skills-lock.json"}
DIRS = ["static", "tests", "packaging", "etf_catalog", "docs", ".github"]
EXTRA = ["reports/patterns.json", "reports/backtest.json", "reports/etf_momentum.json",
         "data/validazione/riepilogo.json", "data/validazione/rielaborazioni/riepilogo.json",
         "data/strategie/riepilogo.json"]
DENY_PARTS = {"portafoglio", "cache", "__pycache__", ".pytest_cache", ".venv", ".venv-win", ".git", ".claude", "build",
              "fonti", "logs"}
DENY_EXT = (".sqlite3", ".sqlite", ".db", ".xls", ".xlsx", ".pkl", ".log", ".zip", ".tar.gz", ".pyc")


def members():
    out = []
    for fn in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, fn)
        if os.path.isfile(p) and not os.path.islink(p) and fn not in ROOT_DENY and any(fnmatch.fnmatch(fn, g) for g in ROOT_FILES):
            out.append(fn)
    for d in DIRS:
        for r, dirs, files in os.walk(os.path.join(ROOT, d)):
            dirs[:] = sorted(x for x in dirs if x not in DENY_PARTS and not os.path.islink(os.path.join(r, x)))
            for fn in sorted(files):
                if fn == ".DS_Store" or os.path.islink(os.path.join(r, fn)):
                    continue
                out.append(os.path.relpath(os.path.join(r, fn), ROOT).replace(os.sep, "/"))
    out += [x for x in EXTRA if os.path.isfile(os.path.join(ROOT, *x.split("/")))]
    return out


def problems(names):
    bad = []
    for n in names:
        parts = n.split("/")
        if any(p in DENY_PARTS for p in parts) or parts[-1] in ROOT_DENY or n.lower().endswith(DENY_EXT):
            bad.append(n)
        elif parts[0] in ("reports", "data") and n not in EXTRA:
            bad.append(n)
    return bad


JS_RECORD = "packaging/js_verificato.json"


def js_record(node=None):
    """Phase 9B.1: `node --check static/app.js` here on the Mac; the kit carries the fingerprint of the approved file, so
    the tests on a Windows PC without Node.js still check that app.js is exactly that file (tests/jscheck.py)."""
    node = node or shutil.which("node")
    if not node:
        raise SystemExit("serve Node.js sul Mac per creare il kit (controllo della sintassi di static/app.js)")
    app_js = os.path.join(ROOT, "static", "app.js")
    out = subprocess.run([node, "--check", app_js], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("static/app.js non supera node --check: " + out.stderr[-500:])
    ver = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    with open(app_js, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    return {"files": {"static/app.js": digest}, "node": ver, "at": datetime.now().isoformat(timespec="seconds"),
            "note": "sintassi controllata con node --check sul Mac alla creazione del kit"}


ENGINES_RECORD = "packaging/motori_verificati.json"


def engines_record():
    """Phase 9B.1: the financial engines must be identical to git HEAD (test 25 of tests/test_ui_8b1.py). The kit has
    no git: it carries the fingerprints of those files, checked here against HEAD, so the test still runs on Windows."""
    import ast
    src = open(os.path.join(ROOT, "tests", "test_ui_8b1.py"), encoding="utf-8").read()
    engines = next(ast.literal_eval(n.value) for n in ast.parse(src).body
                   if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "ENGINES")
    out = {}
    for f in engines:
        head = subprocess.run(["git", "-C", ROOT, "show", f"HEAD:{f}"], capture_output=True)
        if head.returncode != 0:
            raise SystemExit(f"git non disponibile o {f} non in HEAD: il kit si crea dal progetto con Git sul Mac")
        with open(os.path.join(ROOT, f), "rb") as fh:
            data = fh.read()
        if data != head.stdout:
            raise SystemExit(f"{f} è diverso da git HEAD: i motori non devono cambiare")
        out[f] = hashlib.sha256(data).hexdigest()
    return {"files": out, "at": datetime.now().isoformat(timespec="seconds"),
            "note": "motori identici a git HEAD, controllati sul Mac alla creazione del kit"}


def build(dest):
    names = members()
    for generated in (JS_RECORD, ENGINES_RECORD):
        if generated in names:
            names.remove(generated)                    # always written fresh below, never an old copy
    bad = problems(names)
    if bad:
        raise SystemExit("file vietati nel kit: " + ", ".join(bad))
    record, engines = js_record(), engines_record()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.write(os.path.join(ROOT, *n.split("/")), "Nasdaq100/" + n)
        z.writestr("Nasdaq100/" + JS_RECORD, json.dumps(record, indent=1) + "\n")
        z.writestr("Nasdaq100/" + ENGINES_RECORD, json.dumps(engines, indent=1) + "\n")
    names = names + [JS_RECORD, ENGINES_RECORD]
    with zipfile.ZipFile(dest) as z:                   # checked again, as written
        again = [x[len("Nasdaq100/"):] for x in z.namelist()]
    if problems(again):
        os.remove(dest)
        raise SystemExit("controllo del kit non superato")
    return names


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("uso: crea_kit.py DESTINAZIONE.zip")
    n = build(sys.argv[1])
    print(f"kit creato: {sys.argv[1]} ({len(n)} file, nessun dato personale)")
