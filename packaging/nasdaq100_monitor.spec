# -*- mode: python ; coding: utf-8 -*-
# Fase 9B - PyInstaller, modalità "una cartella" (onedir), SOLO su Windows (PyInstaller non compila Mac → Windows).
# Prima: python packaging/prepara_pubblici.py   (crea build/pubblici, build/moduli.json, build/icona.ico)
# Poi:   python -m PyInstaller packaging/nasdaq100_monitor.spec --noconfirm --clean --distpath build/dist --workpath build/work
#
# Risultato: build/dist/Nasdaq-100 Monitor/
#   Nasdaq-100 Monitor.exe      il programma (senza finestra del terminale)
#   _internal/                  Python, librerie e i SOLI file pubblici di build/pubblici (mai dati personali)
import json
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
BUILD = os.path.join(ROOT, "build")
STAGE = os.path.join(BUILD, "pubblici")
with open(os.path.join(BUILD, "moduli.json"), encoding="utf-8") as f:
    MODULES = json.load(f)

datas = [(STAGE, ".")]                                 # public files at the root of _internal (= app_env.ROOT)
datas += collect_data_files("tzdata")                  # time zones: Windows has no IANA database of its own
datas += collect_data_files("certifi")                 # certificates for HTTPS
datas += collect_data_files("curl_cffi")
datas += collect_data_files("yfinance")
binaries = collect_dynamic_libs("curl_cffi")           # the native library used by yfinance for its requests

a = Analysis(
    [os.path.join(ROOT, "desktop_app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=MODULES + ["tzdata", "tkinter", "tkinter.ttk", "tkinter.messagebox"],
    excludes=["pytest", "_pytest", "IPython", "matplotlib", "PyQt5", "PyQt6", "PySide6", "notebook", "jupyter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [("X utf8", None, "OPTION")],                      # UTF-8 mode: every file is read and written as UTF-8, as on the Mac
    exclude_binaries=True,
    name="Nasdaq-100 Monitor",
    console=False,                                     # no terminal window
    icon=os.path.join(BUILD, "icona.ico"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Nasdaq-100 Monitor", upx=False)
