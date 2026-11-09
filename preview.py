"""Anteprima della dashboard (Fase 6C): per provare la pagina senza toccare nulla di reale.

    .venv/bin/python preview.py            # http://127.0.0.1:8101 (PORT=... per un'altra porta)
    .venv/bin/python preview.py --vuoto    # senza la copia dei diari (diari vuoti)
    .venv/bin/python preview.py --portafoglio-finto   # con un portafoglio INVENTATO, solo in memoria (Fase 8B.1)

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

# Fase 8B.1: eventi macro e trimestrali dai file pubblici già in cache/ (sola lettura, nessun download)
import json  # noqa: E402

import earnings  # noqa: E402
import macro_calendar  # noqa: E402

for path, target in ((macro_calendar.AUTO_CACHE, macro_calendar._auto), (macro_calendar.BLS_CACHE, macro_calendar._bls)):
    try:
        with open(path) as f:
            target.update(json.load(f))
    except (OSError, ValueError):
        pass
macro_calendar.check_official = lambda: None           # mai le pagine Fed / BEA dall'anteprima
macro_calendar.refresh_bls = lambda: None              # mai l'API BLS dall'anteprima
earnings._dates = lambda ticker: []                    # trimestrali: solo quelle già in cache/earnings.json


def _cached_reports(tickers):
    """Come earnings.reports, ma in sola lettura: niente download e niente scrittura della cache."""
    c = server.read_cache(earnings.CACHE, 7 * 86400) or {}
    data = c.get("data") or {}
    return {t: (data.get(t) or {}).get("reports") or [] for t in tickers}


earnings.reports = _cached_reports

# Fase 8B.1: --portafoglio-finto = posizioni INVENTATE in memoria, per vedere le pagine del Portafoglio senza dati reali
FAKE = [  # name, isin, symbol, market, kind, currency, qty, price, ticker
    ("NVIDIA CORP", "US67066G1040", "NVDA", "OQ", "Azioni", "USD", 10, 180.0, "NVDA"),
    ("MICROSOFT CORP", "US5949181045", "MSFT", "OQ", "Azioni", "USD", 4, 500.0, "MSFT"),
    ("ETF INVENTATO NASDAQ 100", "XX0000000001", "FNDQ", "MI", "ETF", "EUR", 20, 100.0, None),
    ("ETF INVENTATO 3X LEVA", "XX0000000002", "FLV3", "MI", "ETF", "EUR", 15, 40.0, None),
]
if "--portafoglio-finto" in sys.argv:
    import portfolio  # noqa: E402
    fake = [{"name": n, "isin": i, "symbol": sy, "market": m, "kind": k, "currency": c, "qty": q, "costPrice": pr * 0.9,
             "costFx": 1.1 if c == "USD" else 1.0, "costValue": q * pr * 0.9 / (1.1 if c == "USD" else 1.0), "filePrice": pr,
             "fileFx": 1.1 if c == "USD" else 1.0, "fileValue": q * pr / (1.1 if c == "USD" else 1.0), "ticker": t,
             "tickerHow": "inventato" if t else None} for n, i, sy, m, k, c, q, pr, t in FAKE]
    portfolio._state.update(path=os.path.join(BASE, "portafoglio_inventato.xls"), mtime=__import__("time").time(), positions=fake, error=None,
                            resolving=False, quotes={}, fx=None, quotesAt=None)
ALERTS = server.save_alerts(source="anteprima")         # phase 8A: one check, into the temporary registry only

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8101))
    if port == 8100:
        sys.exit("la porta 8100 è della dashboard reale: scegli un'altra porta per l'anteprima")
    print(f"anteprima su http://127.0.0.1:{port} — cartella temporanea {BASE}, diari "
          f"{'copiati in sola lettura' if copied else 'vuoti'}, guardia «{app_env.guard_active()}»; {ALERTS}", flush=True)
    server.app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
