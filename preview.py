"""Anteprima della dashboard (Fase 6C): per provare la pagina senza toccare nulla di reale.

    .venv/bin/python preview.py            # http://127.0.0.1:8101 (PORT=... per un'altra porta)
    .venv/bin/python preview.py --vuoto    # senza la copia dei diari (diari vuoti)

Cosa fa:
- dichiara l'ambiente «anteprima» e accende la guardia di app_env: ogni scrittura nella cartella del progetto (diari,
  portafoglio/, cache/, report, catalogo) viene bloccata prima che avvenga;
- portafoglio, diari personali e regole puntano a una cartella temporanea VUOTA: nessun dato personale è letto o mostrato;
- i diari delle opportunità sono una COPIA del database reale fatta in sola lettura (oppure vuoti con --vuoto): le
  registrazioni dell'anteprima, se ci fossero, finiscono nella copia con origine «anteprima»;
- usa solo i dati di mercato pubblici già in cache/ (in sola lettura): nessun download, nessun lavoro in background.
Non autorizza mai la scrittura dei diari di produzione."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ["NDX_ENV"] = "anteprima"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import app_env  # noqa: E402

assert app_env.env() == "anteprima", app_env.env()
app_env.install_guard()

import opportunity_diary as od  # noqa: E402

REAL_DB = od.DB
BASE = tempfile.mkdtemp(prefix="ndx_anteprima_")
app_env.isolate(BASE, public_reads=True)
copied = False if "--vuoto" in sys.argv else app_env.copy_diary(REAL_DB, od.DB)

import analysts  # noqa: E402
import server  # noqa: E402
import technical  # noqa: E402

server.download = lambda *a, **k: {}                   # never Yahoo
server.diary_days = lambda: 0                          # never list a personal diary
st = server.store
st.constituents = server.load_constituents()
infos = server.read_cache("infos.json", 30 * 86400)
st.infos = infos["data"] if isinstance(infos, dict) and "data" in infos else {}
st.analysts = analysts.cached_data() or {}
cached = server.load_daily_cache()
st.daily = cached[0] if cached else {}
st.tech = st.technicals(st.daily)
st.ta = technical.build(st.daily, st.constituents, st.tech)
st.build()
st.ready.set()

import etf  # noqa: E402

etf.public = lambda: None
etf.status = lambda: {"error": None, "running": True}
ALERTS = server.save_alerts(source="anteprima")         # phase 8A: one check, into the temporary registry only

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8101))
    if port == 8100:
        sys.exit("la porta 8100 è della dashboard reale: scegli un'altra porta per l'anteprima")
    print(f"anteprima su http://127.0.0.1:{port} — cartella temporanea {BASE}, diari "
          f"{'copiati in sola lettura' if copied else 'vuoti'}, guardia «{app_env.guard_active()}»; {ALERTS}", flush=True)
    server.app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
