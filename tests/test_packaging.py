"""Fase 9B: i file che preparano lo ZIP per Windows (packaging/). Girano anche sul Mac: controllano CHE COSA entra nel
pacchetto, non che il programma funzioni su Windows (quello lo prova packaging/prova_exe.py dopo la build)."""
import io
import json
import os
import re
import shutil
import struct
import sys
import zipfile

import pytest

import app_env

ROOT = app_env.ROOT
sys.path.insert(0, os.path.join(ROOT, "packaging"))
import crea_kit            # noqa: E402
import crea_zip            # noqa: E402
import prepara_pubblici    # noqa: E402
import verifica_pacchetto  # noqa: E402


@pytest.fixture
def staged(tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    files, version, missing = prepara_pubblici.stage(str(build))
    return build, files, version


def fake_bundle(build, tmp_path):
    """The folder PyInstaller would make, with the public files where the spec puts them (no real Python inside)."""
    app = tmp_path / "dist" / "Nasdaq-100 Monitor"
    shutil.copytree(build / "pubblici", app / "_internal")
    (app / "Nasdaq-100 Monitor.exe").write_bytes(b"MZ finto")
    return app


def test_only_public_files_are_staged(staged):
    build, files, version = staged
    names = sorted(os.path.relpath(os.path.join(r, f), build / "pubblici").replace(os.sep, "/")
                   for r, _, fs in os.walk(build / "pubblici") for f in fs)
    allowed = re.compile(r"(static/.+|etf_catalog/[\w-]+\.json|reports/(patterns|backtest|etf_momentum)\.json|"
                         r"data/validazione/(rielaborazioni/)?riepilogo\.json|data/strategie/riepilogo\.json|"
                         r"(etf_universe|themes|alert_rules|data_quality_reviews|diary_exclusions)\.json|VERSIONE\.txt)")
    assert names and all(allowed.fullmatch(n) for n in names), [n for n in names if not allowed.fullmatch(n)]
    with open(build / "pubblici" / "diary_exclusions.json", encoding="utf-8") as f:
        assert json.load(f)["items"] == []
    mods = json.loads((build / "moduli.json").read_text())
    assert {"server", "desktop", "app_env", "portfolio_fit"} <= set(mods)
    assert not set(mods) & prepara_pubblici.NOT_IN_APP


def test_icon_is_a_valid_windows_icon(staged):
    build, _, _ = staged
    data = (build / "icona.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, 7)
    for i in range(count):
        w, h, _, _, planes, bits, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        assert data[offset:offset + 8] == b"\x89PNG\r\n\x1a\n" and planes == 1 and bits == 32
        assert offset + size <= len(data)


def test_the_bundle_check_accepts_a_clean_bundle_and_refuses_personal_data(staged, tmp_path):
    build, _, _ = staged
    app = fake_bundle(build, tmp_path)
    assert verifica_pacchetto.check(str(app)) == []
    for rel, data in (("_internal/portafoglio/portafoglio-2026-11-09.xls", b"x"), ("_internal/watchlist.json", b"{}"),
                      ("_internal/data/opportunita.sqlite3", b"x"), ("_internal/cache/daily.pkl", b"x"),
                      ("_internal/reports/2026-11-09_close.json", b"{}"), ("_internal/static/x.json", b"/Users/qualcuno")):
        p = app / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        assert verifica_pacchetto.check(str(app)), rel
        p.unlink()
    (app / "_internal" / "static" / "vendor" / "d3.min.js").write_text("// alterato")
    assert "d3.min.js diverso dalla versione controllata" in verifica_pacchetto.check(str(app))


def test_the_zip_has_one_folder_the_guide_and_a_checksum(staged, tmp_path):
    build, _, _ = staged
    app = fake_bundle(build, tmp_path)
    dest = str(tmp_path / "Nasdaq-100-Monitor-Windows.zip")
    digest = crea_zip.build_zip(str(app), dest)
    names = zipfile.ZipFile(dest).namelist()
    assert all(n.startswith("Nasdaq-100 Monitor/") for n in names)
    assert "Nasdaq-100 Monitor/LEGGIMI.txt" in names and "Nasdaq-100 Monitor/Nasdaq-100 Monitor.exe" in names
    assert open(dest + ".sha256.txt").read().startswith(digest) and len(digest) == 64


def test_the_build_kit_has_no_personal_data():
    names = crea_kit.members()
    assert crea_kit.problems(names) == []
    assert not any(n.split("/")[0] in ("portafoglio", "cache") or n == "watchlist.json" or n.endswith((".sqlite3", ".xls"))
                   for n in names)
    assert {"desktop.py", "desktop_app.py", "packaging/build_windows.ps1", "static/vendor/d3.min.js"} <= set(names)


def test_spec_requirements_and_scripts():
    spec = open(os.path.join(ROOT, "packaging", "nasdaq100_monitor.spec"), encoding="utf-8").read()
    assert '("X utf8", None, "OPTION")' in spec and "console=False" in spec and 'collect_data_files("tzdata")' in spec
    req = [x.split("#")[0].strip() for x in open(os.path.join(ROOT, "packaging", "requirements-windows.txt"), encoding="utf-8")]
    req = [x for x in req if x]
    assert all(re.fullmatch(r"[\w.-]+==[\w.]+", x) for x in req), req
    assert any(x.startswith("tzdata==") for x in req) and any(x.startswith("pyinstaller==") for x in req)
    ps1 = open(os.path.join(ROOT, "packaging", "build_windows.ps1"), "rb").read()
    assert ps1.isascii()
    for step in ("pytest", "prepara_pubblici.py", "PyInstaller", "verifica_pacchetto.py", "prova_exe.py", "crea_zip.py"):
        assert step.encode() in ps1
    wf = open(os.path.join(ROOT, ".github", "workflows", "windows-build.yml"), encoding="utf-8").read()
    assert "workflow_dispatch" in wf and "push:" not in wf and "schedule:" not in wf and "pull_request" not in wf


def test_the_guide_is_short_and_never_asks_to_turn_protections_off():
    text = open(os.path.join(ROOT, "packaging", "LEGGIMI.txt"), encoding="utf-8").read()
    assert len(text.splitlines()) <= 60
    assert "SmartScreen" in text and "Non disattivare mai" in text and "SHA-256" in text
    assert "%LOCALAPPDATA%\\Nasdaq100Monitor" in text
