#!/bin/sh
# Avvia la dashboard Nasdaq-100 e la apre nel browser.
# Usa l'ambiente Python isolato in .venv (lo crea al primo avvio).
cd "$(dirname "$0")"
PY312="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12"
if [ ! -x .venv/bin/python ]; then
  [ -x "$PY312" ] || { echo "Python 3.12 non trovato: installalo da python.org"; exit 1; }
  echo "Creo l'ambiente .venv…"
  "$PY312" -m venv .venv || exit 1
fi
# libraries only when .venv is new or requirements.txt changed (its fingerprint is kept in .venv/.requirements.sha)
REQ_SHA=$(/usr/bin/shasum requirements.txt | cut -d' ' -f1)
if [ "$(cat .venv/.requirements.sha 2>/dev/null)" != "$REQ_SHA" ]; then
  echo "Installo le librerie Python…"
  .venv/bin/python -m pip install -q -r requirements.txt || exit 1
  echo "$REQ_SHA" > .venv/.requirements.sha
fi
(sleep 4 && open http://localhost:8100) &
exec .venv/bin/python server.py
