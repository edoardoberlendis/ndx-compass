"""Fase 9B: crea Nasdaq-100-Monitor-Windows.zip dalla cartella controllata da verifica_pacchetto.py.

    python packaging/crea_zip.py "build/dist/Nasdaq-100 Monitor" build/Nasdaq-100-Monitor-Windows.zip

Lo ZIP contiene una sola cartella «Nasdaq-100 Monitor» con il programma, _internal e LEGGIMI.txt. Accanto scrive
<zip>.sha256.txt con l'impronta SHA-256, da comunicare a parte a chi lo riceve (serve a controllare che il file sia
proprio quello preparato)."""
from __future__ import annotations

import hashlib
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))


def build_zip(folder, dest):
    top = "Nasdaq-100 Monitor"
    tmp = dest + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(os.path.join(HERE, "LEGGIMI.txt"), f"{top}/LEGGIMI.txt")
        for r, dirs, files in os.walk(folder):
            dirs.sort()
            for fn in sorted(files):
                full = os.path.join(r, fn)
                if os.path.islink(full):
                    raise SystemExit(f"collegamento nel pacchetto: {full}")
                z.write(full, f"{top}/" + os.path.relpath(full, folder).replace(os.sep, "/"))
    os.replace(tmp, dest)
    h = hashlib.sha256()
    with open(dest, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    digest = h.hexdigest()
    with open(dest + ".sha256.txt", "w", encoding="utf-8") as f:
        f.write(f"{digest}  {os.path.basename(dest)}\n")
    return digest


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("uso: crea_zip.py CARTELLA_DEL_PROGRAMMA DESTINAZIONE.zip")
    d = build_zip(sys.argv[1], sys.argv[2])
    print(f"{sys.argv[2]}  ({os.path.getsize(sys.argv[2]) / 1e6:.0f} MB)\nSHA-256: {d}")
