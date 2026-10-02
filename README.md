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
./run.sh            # crea .venv se manca, installa le librerie (solo se requirements.txt è cambiato), avvia il server e apre il browser (Ctrl+C per fermare)
```

## Cosa contiene

- **Oggi**: 4 indicatori (Nasdaq-100, titoli in rialzo/ribasso, % di titoli sopra le medie 20/40/60 e 200, volatilità VIX e VXN con la fascia: calmo/normale/nervosismo/paura),
  mappa del mercato (clic sul nome di un settore per ingrandirlo), grafico intraday del Nasdaq-100, chi si è mosso e perché, trimestrali dei prossimi 7 giorni
  (i miei titoli in cima).
- **Eventi macro USA** (in Oggi, sopra le trimestrali): riunioni della Fed (FOMC, con conferenza stampa), inflazione CPI e
  PCE, rapporto sull'occupazione nei prossimi 7 giorni, con l'orario di New York e l'ora locale (calcolata, anche quando
  l'ora legale USA ed europea non coincidono). La card è corta: titolo, data, ora e dato uscito (o precedente). Un clic
  sul nome o su "Dettagli →" apre il pannello laterale (lo stesso dei titoli) con: data e ora di New York e italiana,
  valore uscito e del mese prima, spiegazione completa, "come reagisce di solito il mercato" (scenari "se… → di
  solito…", mai previsioni), settori e temi più sensibili, quota del mio portafoglio e preferiti coinvolti con
  l'elenco dei titoli (cliccabili). Valori di CPI e occupazione dall'API pubblica della BLS; il valore atteso
  non c'è (nessuna fonte gratuita affidabile), il PCE mostra solo la data (i valori richiederebbero una chiave BEA).
  Date ufficiali scritte in `macro_calendar.py` (Fed, BLS, BEA, 2026); ogni giorno la pagina della Fed e il calendario
  BEA vengono riletti per aggiungere le date nuove, con un avviso se il controllo non riesce o se l'elenco sta per finire.
- **I miei titoli**: i preferiti (★) con prezzo, variazioni, posizione rispetto alle medie, valutazione, analisti, segnale,
  prossima trimestrale e ultima notizia. Salvati in `watchlist.json` nella cartella del progetto.
- **Portafoglio**: le mie posizioni reali, dall'export Excel di Fineco ("Portafoglio sintesi") messo nella cartella
  `portafoglio/` (la dashboard legge da sola il file più recente). Il file si carica dalla scheda con il pulsante
  **Carica file Fineco** o trascinandolo sulla pagina: prima compare un'anteprima (posizioni nuove, vendute, con
  quantità cambiata) e solo dopo la conferma il file viene salvato come `portafoglio/portafoglio-AAAA-MM-GG_HHMMSS.xls`.
  I file precedenti non vengono mai cancellati (serviranno per lo storico del portafoglio). Un file che non è un
  export Fineco `.xls` viene rifiutato con un messaggio. Il caricamento funziona solo dalla dashboard aperta su questo
  Mac (server su 127.0.0.1, controllo di provenienza della richiesta); il file resta fuori da Git. Per ogni
  posizione: valore attuale in euro, guadagno/perdita in euro e in %, di cui effetto cambio (per i titoli in dollari),
  variazione di oggi e peso sul totale. Ticker Yahoo ricavati dal simbolo Fineco (`.O`/`.N` → nessun suffisso, `.MI`,
  `.FRA` su Xetra → `.DE`, `.PAR` → `.PA`, ...), controllati con valuta e prezzo del file; se uno non si trova si usa il
  prezzo del file e si può indicare il ticker in `portafoglio/ticker.json` (`{"ISIN": "TICKER"}`). Stesse formule di
  Fineco: valore = quantità × prezzo ÷ cambio EUR/USD. **Concentrazione** per settore, tema e paese, con affiancati il
  valore investito e l'**esposizione effettiva** (3× il valore per i prodotti a leva 3x). Azioni: settore della dashboard
  (Nasdaq-100) o di Yahoo, temi di `themes.json`, paese di Yahoo; ETF ed ETC e correzioni per le azioni in
  `portafoglio/classificazione.json` (modificabile; il Nasdaq-100 3x è diviso come i settori dell'indice).
  **Prodotti a leva** evidenziati (riga colorata, etichetta "leva 3x", riquadro con la loro quota di valore e di
  esposizione, ⓘ con il rischio: leva giornaliera, perdita di valore con mercato altalenante, crollo). Vista
  **Dati della dashboard**: per i titoli del Nasdaq-100 Trend, segnale, valutazione, potenziale analisti e prossima
  trimestrale. Nessuna indicazione "aumenta / vendi". **I dati personali restano sul Mac**: `portafoglio/` è esclusa
  da Git, niente viene salvato in `cache/` o nei report, a Yahoo vanno solo i ticker per i prezzi.
- **Chi si è mosso e perché** (in Oggi): per gli 8 migliori e gli 8 peggiori del giorno cerca tra le ultime
  40 notizie Yahoo quelle che nominano la società, uscite tra la chiusura precedente e la mattina dopo, e ne
  ricava il probabile motivo con regole a parole chiave (conti, guidance, analisti, acquisizioni, cause legali,
  prodotti/contratti, settore, macro). Preferisce gli articoli che spiegano il movimento ("Shares Jump, What You
  Need To Know") e ne estrae la frase con la causa. Se non trova nulla dice se il titolo si è mosso insieme al settore.
  È un aiuto, non una certezza: il link porta all'articolo per verificare.
- **Segnale finale** (nello Screener, in I miei titoli, in cima alla scheda del titolo e nel report): Molto positivo /
  Positivo / Neutro / Negativo / Molto negativo, da un punteggio −100…+100 che combina
  analisti 41,7% (target, giudizio medio, upgrade/downgrade, revisioni delle stime), valutazione 33,3% (settore + storia
  + PEG) e notizie 25% (tono dei titoli degli ultimi 3 giorni che nominano la società, notizie scaricate ogni 2 ore).
  Se una parte manca, il suo peso va alle altre; con una sola parte su tre compare **Dati insufficienti**. Le soglie:
  ≥ +50 molto positivo, ≥ +20 positivo, ≤ −20 negativo, ≤ −50 molto negativo. Calcolo in `score.py`.
  Analisti, valutazione e notizie non hanno uno storico gratuito: il segnale **non è verificato con un backtest**.
  È una combinazione meccanica di dati pubblici, **non una consulenza finanziaria**.
- **Trend**: il punteggio tecnico (medie 20/40/60, RSI, forza vs QQQ), mostrato accanto al segnale ma non più dentro:
  il backtest ha mostrato che non distingue la direzione. Descrive l'andamento del prezzo, non è un voto.
- **Screener**: i 100 titoli con colonne Panoramica / Performance / Valutazione / Tecnica, filtri (anche "Sopra/Sotto 20, 40 e 60", "Valutazione economica/cara", "Upgrade recenti", "Stime in rialzo/calo"), raggruppati per tema; un secondo clic su un filtro attivo lo toglie e torna a "Tutti". Export CSV. La vista Tecnica mostra la distanza dalle medie 20/40/60/50/200.
- **Settori**: rendimenti dei settori pesati per capitalizzazione e peso di ogni settore nell'indice. Clic su una riga:
  compaiono i titoli di quel settore; di nuovo sulla stessa riga (o "Tutti i settori") si torna a tutti.
- **Report**: il report tecnico generato da `signals.py` (vedi sotto): sintesi, mappa di rotazione, temi, cosa è cambiato
  (in frasi semplici rispetto al report precedente), tabella delle medie e backtest.
- **Pattern tecnici** (al posto della vecchia scheda Idee): per ciascuno dei 9 pattern provati con il backtest, l'esito
  del test (✅/❌ per le 6 condizioni, con i numeri veri passando sopra), una spiegazione semplice, i dettagli a 1, 3 e 6
  mesi e anno per anno, e i titoli che lo presentano nel report scelto in Report (per i pattern di tipo evento: quelli
  in cui è scattato nelle ultime 5 sedute, con la data). **Nessun pattern è mostrato come "favorevole"**: vedi sotto.
- **Scheda titolo**: grafico 1G–MAX, confronto con NDX, fondamentali, target degli analisti, notizie, più:
  - **Analisi tecnica** (solo titoli del Nasdaq-100), in cinque parti: **verdetto** (solo i pattern che hanno superato
    il test della Fase 11, mostrati come informazione e mai come "favorevoli"; altrimenti "Nessun segnale tecnico
    verificato oggi"; i pattern presenti ma bocciati hanno l'etichetta "non verificato"), **medie e trend**,
    **settore e tema** (fase di rotazione e titolo contro il gruppo a 1 e 3 mesi), **piano di rischio** e
    **livelli di attesa**. Piano di rischio: entrata al prezzo attuale; stop sotto la media 50 o sotto l'ultimo minimo
    (20 sedute), meno mezzo ATR, scegliendo il più vicino tra 1,5 e 3,5 ATR, altrimenti 2 × ATR (le altre opzioni si
    possono cliccare); target convenzionale a 2 volte il rischio, con avviso se prima c'è il massimo a 52 settimane;
    numero di azioni per rischiare al massimo una percentuale del portafoglio (default 1%) senza superare un massimo
    per posizione (default 20%), con il valore in euro dalla scheda Portafoglio e il cambio EUR/USD (se il portafoglio
    non è caricato si inserisce il capitale a mano; percentuali e capitale restano solo nel browser). Livelli di
    attesa: se il prezzo è entro il 5% sotto il massimo a 52 settimane o dentro una fase laterale (30 sedute, ampiezza
    ≤ 12%), ordine condizionato sopra la resistenza + un quarto di ATR, stop un ATR sotto il livello rotto, sempre con
    la scritta "pattern non verificato" e i numeri del test. I livelli servono a decidere il rischio in anticipo, non a
    prevedere il prezzo. Numeri grezzi da `technical.py` (sedute chiuse), piano calcolato nella pagina.
  - **Valutazione** (Economica / In linea / Cara): P/E atteso, P/S ed EV/EBITDA contro la mediana dei titoli dello
    stesso settore nel Nasdaq-100 (saltato se il settore ha meno di 3 titoli) e P/E / P/S di oggi contro la mediana
    alle ultime ~4 chiusure di bilancio, più il PEG. Lo storico usa gli utili realizzati (Yahoo non ha lo storico del
    P/E atteso) e stima le capitalizzazioni passate dal prezzo, ignorando buyback e diluizione.
  - **Analisti**: giudizi oggi e 3 mesi fa, upgrade/downgrade e target degli ultimi 30 giorni, stime di utili e
    ricavi con la loro revisione a 30/90 giorni, ultime azioni delle banche d'affari.
  Questi dati si scaricano una volta al giorno in background (circa 15 secondi) in `cache/analysts.json`.
  Si apre cliccando un titolo o con `http://localhost:8100/#NVDA`.

- **Spiegazioni ⓘ**: passando il mouse (o cliccando) sull'icona ⓘ compare una spiegazione breve: volatilità in Oggi, indicatori
  della sintesi del Report (adattati ai valori attuali), ogni filtro e ogni colonna dello Screener e di I miei titoli.
  I testi sono scritti nel codice (`static/app.js`, cerca `COL_INFO` e `PRESET_INFO`).

- **Affidabilità delle notizie** (in Oggi, I miei titoli e nella scheda del titolo): ogni notizia ha un'etichetta
  *Ufficiale* (comunicati via Business Wire, PR Newswire, GlobeNewswire, Accesswire, documenti SEC), *Notizia*
  (testate e agenzie, e le fonti non riconosciute) oppure *Opinione / ipotesi* (siti come Motley Fool, Zacks, Seeking Alpha,
  InvestorPlace, Simply Wall St., Insider Monkey, 24/7 Wall St., GuruFocus, Stocktwits, TipRanks, oppure titoli con
  "could", "may", "should you buy", "?", "reportedly", "sources say", "rumor"). La casella "Nascondi opinioni" vale per
  tutta la dashboard. La classificazione è automatica e approssimativa (regole in `static/app.js`, cerca `NEWS_OPINION`).

Interfaccia, report e nomi di settori/temi sono in italiano. Nomi delle società, descrizioni e notizie
arrivano da Yahoo Finance e restano in inglese.

Tastiera: `/` cerca, `Esc` chiude la scheda.

## Aggiornamento dei dati

- **Prezzi**: ogni 60 secondi (a mercato aperto, pre e post-market; ogni 5 minuti a mercato chiuso e nei giorni festivi).
- **Festività della borsa USA**: elenco NYSE 2026–2028 in `market_calendar.py` (fonte: nyse.com/markets/hours-calendars),
  con le chiusure anticipate alle 13:00 ora di New York. Nei giorni festivi lo stato diventa "Mercato USA chiuso ·
  festività (nome) · riapre …". Tre mesi prima della fine dell'elenco compare un avviso ⚠ accanto allo stato.
- **Storico giornaliero**: una volta al giorno, più una volta dopo la chiusura USA. È salvato in `cache/daily.pkl`:
  riavviando il server nello stesso giorno non si scarica niente (avvio in circa 4 secondi invece di 8–9); dopo qualche
  giorno si scaricano solo i giorni mancanti (i titoli con dividendi o frazionamenti nel frattempo vengono riscaricati
  per intero). Se la cache è rovinata o più vecchia di 10 giorni si riscarica tutto.
- **Fondamentali, dati analisti e stime**: una volta al giorno, salvati in `cache/infos.json` e `cache/analysts.json`.

Così si fanno poche richieste a Yahoo Finance ed è più difficile essere bloccati. I dati possono essere in ritardo.
L'elenco dei titoli viene da Wikipedia.

**Pesi nell'indice.** Il Nasdaq-100 mette dei tetti ai titoli più grandi, quindi la semplice quota di capitalizzazione
sovrastima i giganti (a fine settembre 2026: NVDA 13,5% stimato contro 8,2% vero, i primi 10 insieme 62,8% contro 47,0%).
Una fonte gratuita e senza login con tutti i pesi non esiste: Invesco (QQQ) e Slickcharts bloccano le richieste,
il sito degli indici Nasdaq dà i pesi solo con login, stockanalysis.com solo i primi 25. Per questo la dashboard usa una
soluzione mista:
- per i **10 titoli più grandi** usa i pesi veri del fondo QQQ, letti una volta al giorno da Nasdaq.com
  (`api.nasdaq.com/api/company/QQQ/holdings`: è un indirizzo interno del sito, non un servizio ufficiale; se non risponde
  o i numeri non sono plausibili si usa la copia dei giorni precedenti, poi la stima);
- per **gli altri** divide il resto dell'indice in proporzione alla capitalizzazione, senza che nessuno superi il decimo
  peso vero (se lo supera, l'eccesso va agli altri). Questi pesi sono segnati con **≈**.
I pesi del fondo QQQ sono quasi uguali a quelli dell'indice, ma non identici (il fondo tiene anche un po' di liquidità).
Il peso dei settori è la somma dei pesi dei loro titoli.

## Report automatico (scheda Report)

`signals.py` gira dal lunedì al venerdì alle **08:30** (piano prima dell'apertura, sulla chiusura precedente)
e alle **22:30** (dopo la chiusura USA), ora locale, tramite launchd (il programmatore di macOS).
Nei giorni festivi della borsa USA l'esecuzione programmata non genera report (da Terminale o con il pulsante sì).
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
definiti in `themes.json` (modificabile). Il report contiene anche i titoli che presentano ciascun pattern tecnico
(scheda Pattern tecnici). Le idee di trading con entrata, stop e target sono state tolte: i setup non hanno superato il test.

Il report è uno screening meccanico, **non è una consulenza finanziaria**.

## Backtest del Trend (parte tecnica)

```sh
.venv/bin/python backtest.py   # circa 10 secondi, salva reports/backtest.json (sezione nella scheda Report)
```

Ogni settimana degli ultimi ~10 anni ricalcola, per i titoli di oggi, il punteggio tecnico della dashboard (stesso
codice: la verifica automatica deve dare differenza 0), lo mette in una fascia con le stesse soglie del segnale e misura il rendimento
a 1, 3 e 6 mesi del titolo e di QQQ negli stessi giorni: rendimento medio, extra-rendimento medio e mediano, % di volte
meglio di QQQ, numero di casi, e la tabella anno per anno. Testa solo il Trend: visto che le fasce estreme vanno entrambe
meglio di quelle centrali (la parte tecnica non distingue la direzione), il Trend non fa più parte del segnale finale. Limiti
principali: survivorship bias (si usano i componenti di oggi), casi sovrapposti, un solo tipo di mercato, nessun costo.
Pesi e soglie non vengono adattati ai risultati.

## Test dei pattern tecnici (Fase 11)

```sh
.venv/bin/python backtest.py --patterns   # circa 15 secondi, salva reports/patterns.json (scheda Pattern tecnici)
```

Verifica 9 pattern rialzisti con regole fissate **prima** di vedere i risultati; `reports/backtest.json` non viene toccato.
Dati: chiusure rettificate e volumi di Yahoo da ottobre 2015, titoli del Nasdaq-100 di oggi; casi dal 2017, solo quelli
con tutti i 6 mesi successivi. Pattern di tipo **evento**: conta il primo giorno, poi 20 sedute di pausa per lo stesso
titolo. Pattern di tipo **stato**: misurati una volta a settimana. I tre setup di `signals.py` sono ricalcolati in modo
veloce e confrontati con `signals.py` su 3.500 casi (devono dare 0 differenze, altrimenti il test si ferma).

La misura principale è l'**extra vs tutti i titoli**: il rendimento di ogni caso meno la media di tutti i titoli nello
stesso giorno. Un pattern supera il test solo se, su questo extra:

1. la media a 3 mesi è almeno +0,5 punti;
2. la mediana a 3 mesi è sopra 0;
3. la media a 3 mesi è positiva in almeno 6 anni (contano solo gli anni con almeno 20 casi);
4. la media a 3 mesi è positiva sia nel 2017–2021 sia nel 2022–2026;
5. a 6 mesi la media non è negativa;
6. ci sono almeno 100 casi.

**Queste condizioni non si cambiano dopo aver visto i risultati.** Controllo casuale: 200 pattern finti che scelgono
titoli a caso con la stessa frequenza dei pattern evento; se più del 5% superasse tutte le condizioni, la regola sarebbe
troppo facile.

Risultati del 2 ottobre 2026 (casi 3 gen 2017 → 1 apr 2026, 99 titoli); controllo casuale: 0 su 200.

| Pattern | Tipo | Casi | Media 3 mesi | Mediana 3 mesi | Condizioni rispettate | Esito |
|---|---|---|---|---|---|---|
| Golden cross 50/200 | evento | 561 | +1,44 | +0,0003 | 1 2 3 4 5 6 | superato di misura |
| Momentum 12 mesi escluso l'ultimo | stato | 8.443 | +2,47 | −1,51 | 1 3 4 5 6 | no |
| Leader di momentum | evento | 2.502 | +1,02 | −1,60 | 1 3 4 5 6 | no |
| Nuovo massimo a 52 settimane con volumi | evento | 1.384 | +1,10 | −1,78 | 1 3 5 6 | no |
| Ritracciamento in trend rialzista | evento | 3.809 | +0,14 | −1,63 | 4 6 | no |
| Ritracciamento sulla media 50 in salita | evento | 2.107 | −0,41 | −2,12 | 6 | no |
| Incrocio rialzista | evento | 1.022 | −0,53 | −2,31 | 6 | no |
| Vicino al massimo a 52 settimane | stato | 14.807 | −0,59 | −1,74 | 6 | no |
| Uscita da una fase laterale | evento | 1.240 | −2,38 | −2,71 | 6 | no |

Il Golden cross passa per un soffio: la mediana è praticamente zero (281 casi su 561 sopra la media di tutti), ha battuto
QQQ a 3 mesi nel 51% dei casi contro il 49% di tutti i titoli, e avendo provato 9 pattern può essere dovuto al caso
(pattern finti con soli 561 casi superano il test circa 1 volta su 100). Per questo è mostrato come informazione, non
come pattern "favorevole".

**Regola della dashboard:** nessun pattern viene mostrato come "favorevole" se non ha superato questo test; chi lo supera
è mostrato con i suoi limiti; chi non lo supera è mostrato come "Test non superato". Limiti del test: survivorship bias
residuo (favorisce i pattern di forza), test multipli, casi sovrapposti, nessun costo, un solo tipo di mercato.

## File del progetto

| File/cartella | A cosa serve |
|---|---|
| `server.py` | Server: scarica i dati e li serve alla pagina web |
| `signals.py` | Report tecnico due volte al giorno (schede Report e Pattern tecnici) |
| `analysts.py` | Dati degli analisti e valutazione (scaricati una volta al giorno) |
| `score.py` | Segnale finale (analisti + valutazione + notizie) e Trend a parte |
| `backtest.py` | Backtest del Trend e, con `--patterns`, test dei pattern tecnici (a mano) |
| `technical.py` | Numeri della sezione Analisi tecnica nella scheda del titolo (ATR, livelli, pattern, settore e tema) |
| `portfolio.py` | Portafoglio: lettura dell'export Fineco, ticker Yahoo, valori in euro |
| `macro_calendar.py` | Eventi macro USA: date ufficiali, controllo automatico, valori BLS (da aggiornare ogni anno per CPI e occupazione) |
| `market_calendar.py` | Festività e chiusure anticipate della borsa USA (da aggiornare ogni anno) |
| `themes.json` | Temi personalizzati (elenchi di ticker) |
| `static/` | La pagina web (HTML, CSS, JavaScript) |
| `requirements.txt` | Librerie Python necessarie |
| `run.sh`, `schedule.sh` | Avvio da Terminale e programmazione del report |
| `Nasdaq-100 Monitor.app` | Avvio con doppio clic |
| `.venv/` | Ambiente Python isolato (si ricrea con `./run.sh`) |
| `cache/` | Dati temporanei e log del server (si può cancellare) |
| `reports/` | Report salvati |
| `portafoglio/` | Export Fineco delle mie posizioni (dati personali, esclusa da Git) |
