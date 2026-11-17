# App portatile per Windows (Fase 9B)

Nasdaq-100 Monitor come programma Windows indipendente dal Mac: doppio clic su «Nasdaq-100 Monitor.exe», niente Python,
niente Terminale, niente server da configurare, niente servizi online o a pagamento.

## Com'è fatta

| | |
|---|---|
| Avvio | `desktop_app.py` (impacchettato con PyInstaller, cartella unica, senza finestra del terminale) |
| Server | Flask di `server.py`, solo `127.0.0.1`, prima porta libera tra 8130 e 8149 (su Windows senza condivisione della porta) |
| Apertura | browser predefinito su `/avvio?k=<chiave usa e getta, 2 minuti>` → sessione (cookie HttpOnly, SameSite=Strict) |
| Protezioni | Host locale, Origin esatto, token CSRF su ogni POST, CSP senza siti esterni (d3 è nel programma) |
| Chiusura | «Chiudi l'app» nella pagina o «Chiudi Nasdaq-100 Monitor» nella finestrella → server fermato, processo terminato (`os._exit`) |
| Una copia sola | `app.json` nella cartella dei dati: una seconda apertura chiede alla prima di riaprire il browser ed esce |
| Dati | `%LOCALAPPDATA%\Nasdaq100Monitor\` → `dati\` (personali e diari), `cache\` (mercato), `logs\`, `backup\` |
| Programma | cartella estratta dallo ZIP: **mai scritta** (`app_env.enable_desktop` blocca ogni scrittura prima che avvenga) |

`app_env.enable_desktop` vale come la protezione della Fase 9A: blocca anche ogni lettura di `portafoglio/` e
`watchlist.json` del progetto (utile se l'app gira sul Mac per prova). L'ambiente `desktop` autorizza a scrivere i diari
**solo** nella cartella dei dati dell'app e solo con origine ufficiale (`comando manuale` per «Aggiorna dati»,
`dashboard` per l'aggiornamento serale facoltativo).

## Dati di mercato

- **«Aggiorna dati»** (`desktop.run_update`): stessi passi e stesse funzioni del job serale del Mac
  (`server.run_daily_job`): elenco, dati società, analisti, pesi QQQ, storico 2 anni, quotazioni, notizie, calendario
  macro, bilanci, portafoglio, prezzi ETF, scheda ETF, diari e alert, report della sera. Nessuna regola cambiata.
  Controllo di Internet prima di tutto (senza connessione nulla cambia); ogni passo ha esito ok / errore con motivo; esito
  complessivo «completo», «parziale» o «non riuscito», ora e data scritte accanto al pulsante. Un secondo avvio mentre è
  in corso viene rifiutato.
- **Prima volta**: conferma con la stima (circa 50–100 MB, 5–15 minuti; prova reale sul Mac l'11/11/2026: 4 min 30 s).
- **Mentre l'app è aperta**, e solo dopo il primo aggiornamento: quotazioni del giorno e prezzi delle posizioni (una
  richiesta leggera al minuto con la borsa aperta, ogni 5 minuti altrimenti). La scheda ETF non si ricalcola da sola
  (sarebbe un download pesante): si aggiorna con «Aggiorna dati» e resta su disco tra un avvio e l'altro.
- **Aggiornamento serale** (facoltativo, spento di serie): se l'app è aperta, una volta per seduta dopo la chiusura NYSE
  + 20 minuti.
- **Diari**: partono vuoti sul PC; registrano solo l'ultima seduta disponibile e solo entro i limiti già in vigore
  (`diaries_status.recordable_until`: fino alle 04:00 ET della seduta successiva). Mai recuperi del passato.

## Build (solo su Windows)

PyInstaller non compila da Mac a Windows. Tutto è pronto in `packaging/`:

| File | A cosa serve |
|---|---|
| `requirements-windows.txt` | librerie con versioni bloccate (tutte con pacchetto già compilato per Windows 64 bit / Python 3.12; più `tzdata`) |
| `prepara_pubblici.py` | copia l'elenco chiuso dei file pubblici in `build/pubblici`, registro esclusioni vuoto, icona |
| `nasdaq100_monitor.spec` | PyInstaller: cartella unica, senza console, modalità UTF-8 (`X utf8`), `tzdata`, `curl_cffi` |
| `verifica_pacchetto.py` | rifiuta il pacchetto se manca un file o se c'è un dato personale / file vietato |
| `prova_exe.py` | prova l'eseguibile vero: avvio, cartelle, chiave, ascolto solo 127.0.0.1 (netstat), seconda copia, chiusura, nessun processo rimasto; `--con-internet` anche «Aggiorna dati» |
| `crea_zip.py` | `Nasdaq-100-Monitor-Windows.zip` + impronta SHA-256 |
| `build_windows.ps1` | tutti i passi in ordine: controlli, ambiente `.venv-win`, test, file pubblici, PyInstaller, controllo, prova, ZIP |
| `crea_kit.py` | «kit di build»: solo codice e file pubblici, per fare la build su un PC Windows senza Git |
| `LEGGIMI.txt` | guida di una pagina per chi usa l'app (va nello ZIP) |
| `.github/workflows/windows-build.yml` | stessa build su un PC Windows di GitHub, solo a mano (mai automatica) |

Due strade gratuite:

1. **Un PC Windows qualsiasi** (anche quello del secondo utente, con Python 3.12 installato solo per la build):
   `python packaging/crea_kit.py ~/Desktop/Nasdaq100-kit-build.zip` sul Mac, copia il file, estrai, poi
   `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -ConInternet`.
2. **GitHub Actions** su un repository **privato** (piano Free: 12 $ di utilizzo incluso al mese, circa 1.200 minuti
   Windows; senza carta di pagamento si ferma invece di addebitare; artefatti fino a 500 MB, qui tenuti 3 giorni). Una
   build con prova completa dura circa 20–40 minuti. Richiede di caricare il codice su GitHub: decisione dell'utente.

I riepiloghi degli studi pubblici (`data/validazione/…/riepilogo.json`, `data/strategie/riepilogo.json`) sono fuori da Git:
entrano nel pacchetto con la strada 1 (kit), non con la 2.

## Aggiornare il programma

Nuova versione = nuovo ZIP. Il secondo utente chiude l'app, cancella la vecchia cartella «Nasdaq-100 Monitor» ed estrae la nuova: i
dati in `%LOCALAPPDATA%\Nasdaq100Monitor` restano. Backup e ripristino dalla pagina («Altro»): il backup è uno ZIP di
`dati\`; il ripristino controlla l'archivio (solo percorsi e cartelle note, niente collegamenti, limiti di dimensione),
lo estrae in una cartella nuova e lo applica alla riapertura, tenendo i dati di prima in `backup\`.

## Limiti noti

- Programma non firmato: SmartScreen lo segnala; un certificato di firma costa (escluso). Controllare l'impronta SHA-256.
- Gli eseguibili PyInstaller vengono a volte segnalati per errore dagli antivirus: in quel caso inviare il file a
  Microsoft per l'analisi (gratis), mai disattivare la protezione.
- Windows 10 o 11 a 64 bit (Python 3.12 non supporta versioni più vecchie); sui PC ARM funziona tramite emulazione.
- Un nome utente Windows con `#`, `?` o `%` potrebbe disturbare i database in sola lettura (indirizzi `file:`): da
  verificare se capita.
