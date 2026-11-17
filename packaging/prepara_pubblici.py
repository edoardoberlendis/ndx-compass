"""Fase 9B: prepara in build/pubblici/ i SOLI file pubblici che l'app Windows legge dalla sua cartella, più l'icona.

Elenco chiuso (PUBLIC): niente portafoglio, Preferiti, cache, diari, report della sera, log o file di sviluppo. Il registro
delle esclusioni dei diari parte vuoto (le voci di questo Mac riguardano i diari di questo Mac). Scrive anche
build/moduli.json (i moduli del programma da includere) e build/icona.ico. Funziona su Mac e su Windows.

    python packaging/prepara_pubblici.py"""
from __future__ import annotations

import glob
import json
import os
import shutil
import struct
import zlib

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BUILD = os.path.join(ROOT, "build")
STAGE = os.path.join(BUILD, "pubblici")

# public files read by the program at run time (relative to the project folder)
PUBLIC = ["etf_universe.json", "themes.json", "alert_rules.json", "data_quality_reviews.json",
          "reports/patterns.json", "reports/backtest.json", "reports/etf_momentum.json"]
# summaries of the public studies (phases O3, 4A, 4B): in data/, which Git ignores. Copied when present (build from a
# copy of the project folder); missing in a build from the Git repository: the two panels then say "no study saved".
OPTIONAL = ["data/validazione/riepilogo.json", "data/validazione/rielaborazioni/riepilogo.json",
            "data/strategie/riepilogo.json"]
PUBLIC_DIRS = {"static": None, "etf_catalog": ".json"}         # folder: allowed extension (None = every file)
# program modules that never run in the app (Mac tools, research run by hand, the Mac's separate instances)
NOT_IN_APP = {"preview", "instance", "morning_job", "daily_job", "etf_catalog_build", "etf_universe", "backtest",
              "etf_backtest", "desktop_app"}
EMPTY_EXCLUSIONS = {"schema": 1, "note": "Registro additivo delle registrazioni escluse dalle statistiche prospettiche "
                                         "ufficiali (Fase 8A). App Windows: parte vuoto, i diari di questo PC iniziano "
                                         "da zero.", "items": []}
# the logo of the page (static/icon.svg) on a 16×16 grid: x, y, w, h, colour
LOGO = [(1, 1, 8, 9, (0x1f, 0x9d, 0x55)), (10, 1, 5, 5, (0xd6, 0x39, 0x3b)), (10, 7, 5, 3, (0x1f, 0x9d, 0x55)),
        (1, 11, 14, 4, (0x55, 0x55, 0x55))]


def _png(size):
    rows = []
    unit = size / 16
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            u, v = (x + 0.5) / unit, (y + 0.5) / unit
            px = (0, 0, 0, 0)
            for rx, ry, rw, rh, col in LOGO:
                if rx <= u < rx + rw and ry <= v < ry + rh:
                    px = (*col, 255)
            row += bytes(px)
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def make_icon(path, sizes=(16, 24, 32, 48, 64, 128, 256)):
    images = [_png(s) for s in sizes]
    out = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    for s, img in zip(sizes, images):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    with open(path, "wb") as f:
        f.write(out + b"".join(images))


def modules():
    names = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, "*.py")))
    return [n for n in names if n not in NOT_IN_APP]


def stage(build=BUILD):
    """Copies the public files into <build>/pubblici and writes <build>/moduli.json and <build>/icona.ico."""
    STAGE = os.path.join(build, "pubblici")
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    os.makedirs(STAGE)
    copied, missing = [], []
    for rel in PUBLIC + OPTIONAL:
        src = os.path.join(ROOT, *rel.split("/"))
        if not os.path.isfile(src):
            if rel in OPTIONAL:
                missing.append(rel)
                continue
            raise SystemExit(f"manca il file pubblico {rel}")
        dst = os.path.join(STAGE, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        copied.append(rel)
    for folder, ext in PUBLIC_DIRS.items():
        for r, dirs, files in os.walk(os.path.join(ROOT, folder)):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for fn in files:
                if fn.startswith(".") or (ext and not fn.endswith(ext)):
                    continue
                src = os.path.join(r, fn)
                rel = os.path.relpath(src, ROOT).replace(os.sep, "/")
                dst = os.path.join(STAGE, *rel.split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
                copied.append(rel)
    with open(os.path.join(STAGE, "diary_exclusions.json"), "w", encoding="utf-8") as f:
        json.dump(EMPTY_EXCLUSIONS, f, ensure_ascii=False, indent=2)
    copied.append("diary_exclusions.json (vuoto)")
    with open(os.path.join(ROOT, "server.py"), encoding="utf-8") as f:
        version = next(line.split('"')[1] for line in f if line.startswith("DASHBOARD_VERSION"))
    with open(os.path.join(STAGE, "VERSIONE.txt"), "w", encoding="utf-8") as f:
        f.write(f"Nasdaq-100 Monitor per Windows · versione {version}\n")
    with open(os.path.join(build, "moduli.json"), "w", encoding="utf-8") as f:
        json.dump(modules(), f, indent=1)
    make_icon(os.path.join(build, "icona.ico"))
    return copied, version, missing


if __name__ == "__main__":
    files, version, missing = stage()
    print(f"versione {version}: {len(files)} file pubblici in {STAGE}, {len(modules())} moduli, icona in build/icona.ico")
    for rel in missing:
        print(f"ATTENZIONE: {rel} assente (cartella data/ fuori da Git): il pannello di quello studio dirà «nessuno studio salvato»")
