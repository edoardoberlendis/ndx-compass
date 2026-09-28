# Nasdaq-100 Monitor

Dashboard locale in stile finviz per il Nasdaq-100: si apre nel browser su `http://localhost:8100`.

## Primo avvio

Serve **Python 3.12** installato da python.org. Le librerie vengono installate in un ambiente isolato
nella cartella `.venv` del progetto (non toccano il resto del Mac).

**Doppio clic su `Nasdaq-100 Monitor.app`.** Avvia il server in background e apre la dashboard.
Se il server è già acceso, un nuovo doppio clic chiede *Open dashboard* (apri) o *Stop server* (ferma).
Tieni l'app dentro questa cartella; per una scorciatoia trascinala nel Dock. Il log del server è in `cache/server.log`.

Oppure dal Terminale:

```sh
./run.sh            # crea .venv se manca, installa le librerie, avvia il server e apre il browser (Ctrl+C per fermare)
```

## Cosa contiene

- **Oggi**: 4 indicatori (Nasdaq-100, titoli in rialzo/ribasso, % di titoli sopra le medie 20/40/60 e 200, VIX),
  mappa del mercato (clic sul nome di un settore per ingrandirlo), grafico intraday del Nasdaq-100, chi si è mosso e perché, trimestrali dei prossimi 7 giorni
  (i miei titoli in cima).
- **I miei titoli**: i preferiti (★) con prezzo, variazioni, posizione rispetto alle medie, valutazione, analisti, segnale,
  prossima trimestrale e ultima notizia. Salvati in `watchlist.json` nella cartella del progetto.
- **Chi si è mosso e perché** (in Oggi): per gli 8 migliori e gli 8 peggiori del giorno cerca tra le ultime
  40 notizie Yahoo quelle che nominano la società, uscite tra la chiusura precedente e la mattina dopo, e ne
  ricava il probabile motivo con regole a parole chiave (conti, guidance, analisti, acquisizioni, cause legali,
  prodotti/contratti, settore, macro). Preferisce gli articoli che spiegano il movimento ("Shares Jump, What You
  Need To Know") e ne estrae la frase con la causa. Se non trova nulla dice se il titolo si è mosso insieme al settore.
  È un aiuto, non una certezza: il link porta all'articolo per verificare.
- **Segnale finale** (nello Screener, in I miei titoli, in cima alla scheda del titolo e nel report): Molto positivo /
  Positivo / Neutro / Negativo / Molto negativo, da un punteggio −100…+100 che combina
  tecnica 40% (medie 20/40/60, RSI, forza vs QQQ), analisti 25% (target, giudizio medio, upgrade/downgrade, revisioni
  delle stime), valutazione 20% (settore + storia + PEG) e notizie 15% (tono dei titoli degli ultimi 3 giorni che
  nominano la società, notizie scaricate ogni 2 ore). Se una parte manca, il suo peso va alle altre. Le soglie:
  ≥ +50 molto positivo, ≥ +20 positivo, ≤ −20 negativo, ≤ −50 molto negativo. Calcolo in `score.py`.
  È una combinazione meccanica di dati pubblici, **non una consulenza finanziaria**.
- **Screener**: i 100 titoli con colonne Panoramica / Performance / Valutazione / Tecnica, filtri (anche "Sopra/Sotto 20, 40 e 60", "Valutazione economica/cara", "Upgrade recenti", "Stime in rialzo/calo"), export CSV. La vista Tecnica mostra la distanza dalle medie 20/40/60/50/200.
- **Settori**: rendimenti dei settori pesati per capitalizzazione e peso di ogni settore nell'indice. Clic su una riga:
  compaiono i titoli di quel settore; di nuovo sulla stessa riga (o "Tutti i settori") si torna a tutti.
- **Report**: il report tecnico generato da `signals.py` (vedi sotto): sintesi, mappa di rotazione, temi, cosa è cambiato,
  tabella delle medie e backtest. Le idee di trading (entrata/stop/target) sono in fondo, chiuse di default.
- **Scheda titolo**: grafico 1G–MAX, confronto con NDX, fondamentali, target degli analisti, notizie, più:
  - **Valutazione** (Economica / In linea / Cara): P/E atteso, P/S ed EV/EBITDA contro la mediana dei titoli dello
    stesso settore nel Nasdaq-100 (saltato se il settore ha meno di 3 titoli) e P/E / P/S di oggi contro la mediana
    alle ultime ~4 chiusure di bilancio, più il PEG. Lo storico usa gli utili realizzati (Yahoo non ha lo storico del
    P/E atteso) e stima le capitalizzazioni passate dal prezzo, ignorando buyback e diluizione.
  - **Analisti**: giudizi oggi e 3 mesi fa, upgrade/downgrade e target degli ultimi 30 giorni, stime di utili e
    ricavi con la loro revisione a 30/90 giorni, ultime azioni delle banche d'affari.
  Questi dati si scaricano una volta al giorno in background (circa 15 secondi) in `cache/analysts.json`.
  Si apre cliccando un titolo o con `http://localhost:8100/#NVDA`.

Interfaccia, report e nomi di settori/temi sono in italiano. Nomi delle società, descrizioni e notizie
arrivano da Yahoo Finance e restano in inglese.

Tastiera: `/` cerca, `Esc` chiude la scheda.

## Aggiornamento dei dati

- **Prezzi**: ogni 60 secondi (a mercato aperto, pre e post-market; ogni 5 minuti a mercato chiuso).
- **Storico giornaliero**: una volta al giorno, più una volta dopo la chiusura USA.
- **Fondamentali, dati analisti e stime**: una volta al giorno, salvati in `cache/infos.json` e `cache/analysts.json`.

Così si fanno poche richieste a Yahoo Finance ed è più difficile essere bloccati. I dati possono essere in ritardo.
L'elenco dei titoli viene da Wikipedia. Pesi e contributi all'indice sono stimati dalla capitalizzazione.

## Report automatico (scheda Report)

`signals.py` gira dal lunedì al venerdì alle **08:30** (piano prima dell'apertura, sulla chiusura precedente)
e alle **22:30** (dopo la chiusura USA), ora locale, tramite launchd (il programmatore di macOS).
Ogni esecuzione salva `reports/<data>_<sessione>.json`, mostra una notifica e compare nella scheda **Report**.

```sh
./schedule.sh install   # attiva (o riattiva) la programmazione
./schedule.sh run       # esegue subito il job, come farebbe la programmazione
./schedule.sh remove    # disattiva
.venv/bin/python signals.py   # esegue il report a mano
```

Log del job: `reports/logs/signals.log` e `reports/logs/signals.err`.

Cosa calcola per ogni titolo: medie mobili a 20/40/60 giorni, il loro ordine e la pendenza settimanale,
la distanza del prezzo da ciascuna, RSI(14), ATR, forza relativa rispetto a QQQ (1S/1M/3M) e rapporto volumi 20/60 giorni.
Tutto confluisce in un punteggio di trend da −100 a +100. I titoli sono raggruppati per settore e per **temi**
definiti in `themes.json` (modificabile). Ogni *setup* ha entrata, stop, target e un livello di convinzione.

Il report è uno screening meccanico, **non è una consulenza finanziaria**.

## Backtest della parte tecnica

```sh
.venv/bin/python backtest.py   # circa 10 secondi, salva reports/backtest.json (sezione nella scheda Report)
```

Ogni settimana degli ultimi ~10 anni ricalcola, per i titoli di oggi, il punteggio tecnico della dashboard (stesso
codice: la verifica automatica deve dare differenza 0), lo mette nella fascia del segnale finale e misura il rendimento
a 1, 3 e 6 mesi del titolo e di QQQ negli stessi giorni: rendimento medio, extra-rendimento medio e mediano, % di volte
meglio di QQQ, numero di casi, e la tabella anno per anno. Testa solo la parte tecnica (40% del segnale). Limiti
principali: survivorship bias (si usano i componenti di oggi), casi sovrapposti, un solo tipo di mercato, nessun costo.
Pesi e soglie non vengono adattati ai risultati.

## File del progetto

| File/cartella | A cosa serve |
|---|---|
| `server.py` | Server: scarica i dati e li serve alla pagina web |
| `signals.py` | Report tecnico due volte al giorno (scheda Report) |
| `analysts.py` | Dati degli analisti e valutazione (scaricati una volta al giorno) |
| `score.py` | Segnale finale: tecnica + analisti + valutazione + notizie |
| `backtest.py` | Backtest della parte tecnica del segnale (a mano) |
| `themes.json` | Temi personalizzati (elenchi di ticker) |
| `static/` | La pagina web (HTML, CSS, JavaScript) |
| `requirements.txt` | Librerie Python necessarie |
| `run.sh`, `schedule.sh` | Avvio da Terminale e programmazione del report |
| `Nasdaq-100 Monitor.app` | Avvio con doppio clic |
| `.venv/` | Ambiente Python isolato (si ricrea con `./run.sh`) |
| `cache/` | Dati temporanei e log del server (si può cancellare) |
| `reports/` | Report salvati |
