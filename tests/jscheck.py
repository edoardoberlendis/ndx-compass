"""Phase 9B.1: syntax check of static/app.js for the tests.

With Node.js installed (the Mac): `node --check`, as before. Without Node.js (the Windows PC that only builds the app):
app.js must be byte-identical to the file that `node --check` approved on the Mac when the build kit was made
(packaging/js_verificato.json, written by packaging/crea_kit.py). Neither = the test FAILS: never a silent skip.
Node.js is never needed by the finished app (the browser runs app.js)."""
import hashlib
import json
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(ROOT, "static", "app.js")
RECORD = os.path.join(ROOT, "packaging", "js_verificato.json")


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def check_app_js(node=None, record=RECORD):
    """(ok, how): how the syntax of app.js was verified, or why it could not be."""
    node = node if node is not None else shutil.which("node")
    if node:
        out = subprocess.run([node, "--check", APP_JS], capture_output=True, text=True)
        return out.returncode == 0, f"node --check: {out.stderr.strip()[-500:] or 'ok'}"
    if not os.path.isfile(record):
        return False, ("Node.js non installato e packaging/js_verificato.json assente: installa Node.js oppure usa un kit "
                       "creato con packaging/crea_kit.py sul Mac")
    with open(record, encoding="utf-8") as f:
        rec = json.load(f)
    want = (rec.get("files") or {}).get("static/app.js")
    if want and want == sha256(APP_JS):
        return True, f"identico al file verificato con node {rec.get('node')} il {rec.get('at')}"
    return False, "static/app.js è diverso da quello verificato con node sul Mac: rigenera il kit sul Mac"
