"""Fase 9B: controlla la cartella del programma impacchettato PRIMA di creare lo ZIP.

    python packaging/verifica_pacchetto.py "build/dist/Nasdaq-100 Monitor" [--avvisi build/work/.../warn-....txt]

Fallisce (codice 1) se manca un file necessario o se c'è anche un solo file che non deve partire: portafoglio, file
Fineco, Preferiti, dati fiscali, password, database e diari, cache, report della sera, log, file di sviluppo, percorsi
del Mac di sviluppo. Stampa solo nomi di file, mai il loro contenuto."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

D3_SHA256 = "f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539"      # d3 7.9.0 (npm integrity checked)
REQUIRED = ["Nasdaq-100 Monitor.exe", "_internal/static/index.html", "_internal/static/app.js",
            "_internal/static/vendor/d3.min.js", "_internal/static/chiuso.html", "_internal/etf_universe.json",
            "_internal/themes.json", "_internal/alert_rules.json", "_internal/diary_exclusions.json",
            "_internal/reports/patterns.json", "_internal/etf_catalog/strumenti.json", "_internal/VERSIONE.txt"]
FORBIDDEN_NAMES = {"portafoglio", "watchlist.json", "fiscale.json", "regole.json", "classificazione.json", "ticker.json",
                   "stop_auto.json", "pagella.json", "dati_titoli.json", "etf_composizioni.json", "accesso.json",
                   "istanza.json", "job_status.json", "latest.json", "server.log", ".env", ".git", ".claude",
                   "skills-lock.json", "tests", "fonti", "Nasdaq100.zip", "esclusi.json", "flussi.json", "storico",
                   "diario", "diario_etf", "diario_posizioni", "aggiornamento.json", "impostazioni.json", "app.json"}
FORBIDDEN_EXT = (".sqlite3", ".sqlite", ".db", ".xls", ".xlsx", ".csv", ".log", ".pem", ".key", ".tar.gz")
FORBIDDEN_RE = [re.compile(r"\d{4}-\d{2}-\d{2}_(close|morning|afternoon)\.json$"),        # evening reports
                re.compile(r"^portafoglio-.*", re.I), re.compile(r"^export.*\.xls", re.I)]
PRIVATE_MARKERS = [b"/Users/", b"\\Users\\edoardo", b"edoardoberlendis"]
TEXT_EXT = (".json", ".html", ".js", ".css", ".txt", ".md", ".svg")
OURS = ("static", "etf_catalog", "reports", "data")


def check(folder):
    problems = []
    for rel in REQUIRED:
        if not os.path.isfile(os.path.join(folder, *rel.split("/"))):
            problems.append(f"manca {rel}")
    internal = os.path.join(folder, "_internal")
    for name in ("cache", "data/opportunita.sqlite3", "data/alert.sqlite3"):
        if os.path.exists(os.path.join(internal, *name.split("/"))):
            problems.append(f"non deve esserci _internal/{name}")
    # personal data could only arrive with the program's own files: the top of the folder, the top of _internal and
    # the public folders copied by prepara_pubblici.py (the libraries' own folders are not ours to judge by name)
    areas = [(folder, False), (internal, False)] + [(os.path.join(internal, d), True) for d in OURS]
    for top, deep in areas:
        if not os.path.isdir(top):
            continue
        for r, dirs, files in os.walk(top):
            if not deep:
                dirs[:] = [d for d in dirs if d in FORBIDDEN_NAMES]          # only to report them
            for d in dirs:
                if d in FORBIDDEN_NAMES:
                    problems.append(f"cartella vietata: {os.path.relpath(os.path.join(r, d), folder)}")
            for fn in files:
                rel = os.path.relpath(os.path.join(r, fn), folder).replace(os.sep, "/")
                if fn in FORBIDDEN_NAMES or fn.lower().endswith(FORBIDDEN_EXT) or any(x.search(fn) for x in FORBIDDEN_RE):
                    problems.append(f"file vietato: {rel}")
                if fn.lower().endswith(TEXT_EXT):
                    with open(os.path.join(r, fn), "rb") as f:
                        data = f.read()
                    if any(m in data for m in PRIVATE_MARKERS):
                        problems.append(f"percorso del Mac di sviluppo in {rel}")
    problems = sorted(set(problems), key=problems.index)
    d3 = os.path.join(internal, "static", "vendor", "d3.min.js")
    if os.path.isfile(d3):
        with open(d3, "rb") as f:
            if hashlib.sha256(f.read()).hexdigest() != D3_SHA256:
                problems.append("d3.min.js diverso dalla versione controllata")
    ex = os.path.join(internal, "diary_exclusions.json")
    if os.path.isfile(ex):
        with open(ex, encoding="utf-8") as f:
            if json.load(f).get("items"):
                problems.append("diary_exclusions.json deve essere vuoto nell'app")
    return problems


MISSING_RE = re.compile(r"^missing module named (\S+) - imported by (.+)$")
IMPORTER_RE = re.compile(r"([\w.]+) \(([^)]*)\)")


def missing_top_level(warn_path, ours):
    """Phase 9B.1 (the `resource` error of the first Windows build): from PyInstaller's warnings file, the modules that
    one of OUR modules imports unconditionally (top-level, not in a try) but that do not exist on this system. Optional,
    conditional and delayed imports (try/except, inside functions) are fine: the code handles them."""
    if not os.path.isfile(warn_path):
        return [f"file degli avvisi di PyInstaller non trovato: {warn_path}"]
    out = []
    with open(warn_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = MISSING_RE.match(line.strip())
            if not m:
                continue
            for importer, kinds in IMPORTER_RE.findall(m.group(2)):
                kinds = {k.strip() for k in kinds.split(",")}
                if importer in ours and "top-level" in kinds and "optional" not in kinds:
                    out.append(f"modulo mancante su questo sistema: {m.group(1)} (importato da {importer} all'avvio)")
    return out


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    warn = None
    if len(argv) == 3 and argv[1] == "--avvisi":
        argv, warn = argv[:1], argv[2]
    if len(argv) != 1 or not os.path.isdir(argv[0]):
        print("uso: verifica_pacchetto.py CARTELLA_DEL_PROGRAMMA [--avvisi FILE_warn_DI_PYINSTALLER]")
        return 2
    problems = check(argv[0])
    if warn:
        mods = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "moduli.json")
        with open(mods, encoding="utf-8") as f:
            ours = set(json.load(f)) | {"desktop_app", "__main__"}
        problems += missing_top_level(warn, ours)
    for p in problems:
        print("✗", p)
    if problems:
        print(f"PACCHETTO NON VALIDO: {len(problems)} problemi")
        return 1
    print("✓ pacchetto controllato: file necessari presenti, nessun dato personale o file vietato")
    return 0


if __name__ == "__main__":
    sys.exit(main())
