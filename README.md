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

La dashboard ha **cinque schede** (Fase 21, Opportunità aggiunta nella Fase O1); ognuna raggruppa le pagine descritte sotto.
All'avvio (senza un link con `#`) si apre **Opportunità**; prima della Fase O1 si apriva Portafoglio.

| Scheda | Domanda | Sotto-schede |
|---|---|---|
| **Opportunità** | Quali titoli meritano di essere approfonditi? | Una sola pagina con due classifiche: Trading (breve periodo) e Investimento (medio-lungo); vedi sotto |
| **Mercato** | Cosa sta succedendo? | Oggi (con eventi macro USA e trimestrali) · Settori (con la mappa di rotazione) |
| **Portafoglio** | Cosa ho e come sta andando? | Posizioni · Performance · Concentrazione · Rischio |
| **Azioni** | Quali azioni del Nasdaq-100 potrei comprare? | Screener · In osservazione (i preferiti ★) · Diario dei segnali (compare quando ha almeno 3 mesi di dati); da qui si apre la scheda del titolo con la sezione Decisione |
| **ETF** | Quali ETF potrei comprare? | Una sola pagina (Fase 24): vedi sotto |

Cambiare a mano solo la parte dopo `#` (o usare il tasto Indietro) apre la pagina corrispondente anche senza ricaricare
(Fase O2). I vecchi link portano alla pagina più vicina: `#overview` → Oggi, `#sectors` e `#ideas` (il vecchio Report) → Settori,
`#portfolio` e `#rules` → Posizioni, `#screener` e `#trade` (i vecchi Pattern tecnici) → Screener, `#watch` → In
osservazione, `#diary` → Diario se visibile, altrimenti Screener. `#mercato`, `#portafoglio` e `#azioni` aprono la
scheda sull'ultima pagina usata; `#ricerca` (la vecchia scheda) porta allo Screener, `#etf` alla scheda ETF.

**Server con codice vecchio.** Ogni risposta del server dice la versione del codice (`DASHBOARD_VERSION` in `server.py`);
la pagina la confronta con la sua (`PAGE_VERSION` in `static/app.js`) e, se sono diverse, mostra in alto «Il server usa una
versione vecchia del codice: riavvialo». Per riavviare: apri l'app **Nasdaq-100 Monitor** e scegli **Riavvia server**
(il 10 ottobre 2026 la dashboard era rimasta accesa da giorni con il codice vecchio: «Apri dashboard» non riavvia).

**Tolto nella Fase 21** (per una dashboard più semplice; i calcoli che restano non dipendono da queste parti):
la scheda Metodo con Report, Pattern tecnici, Diario e Le mie regole (i risultati dei backtest sono più sotto in
questo file; il diario continua a registrare in background); il riquadro "Cosa richiede attenzione oggi"; i limiti sui
pesi (titolo, ETF, tema, settore, paese, leva) con il riquadro "Rispetto delle regole", le regole R1, R2 e A3 delle
azioni (quindi l'azione "Riduci") e la regola D3 del verdetto; il verdetto "Entra su rottura" (diventa "Attendi: a
ridosso del massimo"); gli avvisi di calendario dentro le card (ora una piccola ⚠ in alto, solo negli ultimi 30 giorni).

- **Opportunità** (Fase O1, `opportunity_scanner.py`, `/api/opportunities`): due classifiche **esplorative** dei titoli del
  Nasdaq-100 da approfondire, fino a 10 ciascuna. **Non sono segnali di acquisto**: le condizioni non sono verificate da un
  backtest, non ci sono probabilità né rendimenti attesi, e lo stato è solo «Da approfondire» o «Dati insufficienti».
  - **Trading · breve periodo (3–30 sedute)**, solo prezzi su **sedute chiuse**: T1 meglio di QQQ a 21 sedute; T2 meglio di QQQ
    a 63 sedute; T3 chiusura sopra le medie 20 e 50; T4 media 20 più alta di 5 sedute prima; T5 volume medio di 20 sedute almeno
    pari a quello di 60 (solo se almeno 57 delle ultime 60 sedute hanno volume). Servono almeno 4 condizioni su 5.
    Avvisi: tirato (soglie della regola D5), sotto la media 200, ATR oltre il 4% del prezzo, trimestrale entro 5 giorni, pattern
    che **non ha superato** il test della Fase 11 (mostrato solo come avviso, mai come motivo).
  - **Investimento · medio-lungo periodo (3–24 mesi)**: le sei voci della Pagella (`pillars.py`, stesse funzioni e soglie
    approvate il 4 novembre 2026) — I1 ricavi +10%, I2 margine operativo stabile, I3 stime non tagliate oltre il 3% in 90 giorni,
    I4 consenso almeno «Acquisto», I5 valutazione non «Cara» — e I6 trend di fondo della regola B2 (prezzo sopra la media 200 e
    media 50 sopra la media 200, su sedute chiuse). Servono almeno 5 condizioni su 6. Avvisi: più downgrade che upgrade
    (come T4), stime tagliate oltre il 3% in 30 giorni (come T3), trimestrale entro 5 giorni, notizie dal tono negativo
    (punteggio ≤ −20), prezzo sotto la media 50. Accanto: rendimento contro la mediana del settore a 6 mesi e le note della
    valutazione.
    Sotto la classifica, la card **Analisi fondamentale** (Fase 5A, sperimentale): sei giudizi separati per ogni società,
    filtri e ordinamento; vedi la sezione «Analisi fondamentale per l'investimento». Sotto ancora la card **Valutazione e
    scenari** (Fase 5B, sperimentale): valore per azione in tre scenari, posizione del prezzo e crescita implicita nel
    prezzo; vedi la sezione «Valutazione e scenari».
  - **Ordine**: più condizioni soddisfatte, poi meno avvisi, poi (Trading) la differenza con QQQ a 1 mese più alta o
    (Investimento) la valutazione più bassa rispetto a settore e storia. Un dato mancante conta **sempre** come condizione non
    soddisfatta, mai come neutra, e il titolo diventa «Dati insufficienti».
  - Per ogni titolo: settore, prezzo con l'ora dell'ultimo dato, rendimenti dell'orizzonte (1 settimana e 1 mese, oppure 6 mesi
    e 1 anno), trend, motivo principale, avvisi e stato; «Dettagli» mostra ogni condizione con valore e soglia, i valori
    misurati e i dati mancanti; un clic sulla riga apre la scheda del titolo (il verdetto della sezione Decisione non cambia).
  - **Dati**: solo quelli già in memoria (storico giornaliero, dati societari, analisti, valutazioni, notizie): nessun
    download in più, nessun job programmato, calcolo in circa 0,1 secondi e rifatto al massimo ogni 10 minuti. I prezzi dei
    criteri sono sedute chiuse fino a una data (`as_of`): i test verificano che i giorni dopo non vengano mai letti. Analisti,
    valutazione e notizie sono i dati di oggi (non hanno storico). Nessun dato del portafoglio.
  - **Forza relativa e andamento (Fase O2)**: la riga del **mercato** (QQQ a 1 e 3 mesi, trend rispetto alle medie 50 e 200,
    quota di titoli sopra la media 200) e, per ogni titolo, il rendimento **assoluto** (Trading: 1 e 3 mesi) separato da quello
    **rispetto a QQQ**. Chi batte QQQ mentre il suo prezzo scende (o ha trend ribassista) porta la scritta «⚠ più forte di
    QQQ ma in calo»: è un'informazione, **non cambia l'ordine** e non è una nuova soglia.
  - **Copertura dei dati (Fase O2)**: per ogni condizione, quanti titoli la possono valutare. Se una condizione è valutabile
    per meno dell'80% dei titoli la classifica è dichiarata **«incompleta»** con un avviso in vista e l'elenco dei titoli
    senza il dato in «Come è fatta la classifica».
  - **Parametri sperimentali**: ATR oltre il 4%, minimo 4 condizioni su 5 (Trading), 5 su 6 (Investimento) e la copertura
    dell'80% sono proposte della Fase O1 **non validate**: restano per compatibilità, sono segnate «sperimentale» nella pagina
    e salvate ogni giorno nel diario, e non si cambiano senza una valutazione specifica. Versione del modello: `MODEL_VERSION`
    in `opportunity_scanner.py` (O2.1), da cambiare a ogni modifica di condizioni, soglie o ordine.
- **Diario delle opportunità** (Fase O2, `opportunity_diary.py`): ogni seduta chiusa salva **entrambe le classifiche per tutti
  i titoli** (in classifica e no, non solo i primi 10) e poi misura cosa è successo ai prezzi.
  - **Dove**: `data/opportunita.sqlite3` (SQLite), solo dati pubblici di mercato, separato da `portafoglio/` e dagli altri
    diari, fuori da Git (`data/` è in `.gitignore`; circa 0,85 MB per seduta, circa 200 MB l'anno).
  - **Cosa**: per ogni seduta (`runs`) data e ora del calcolo con fuso orario, seduta dei prezzi, fonte (dashboard, job serale,
    comando manuale), tipo di prezzo, versione del modello e tutti i parametri, contesto di mercato, copertura dei dati;
    per ogni titolo e classifica (`observations`) identificativo `yahoo:TICKER`, nome, settore, prezzo di riferimento,
    posizione in classifica (vuota se non selezionato), primi 10 sì/no, condizioni soddisfatte, non soddisfatte e mancanti,
    dettaglio di ogni condizione, avvisi, motivo, diagnosi e tutti i valori misurati. Così si ricostruisce perché un titolo
    era in classifica quel giorno (`opportunity_diary.observations(seduta, "trading")`).
  - **Quando**: dopo la chiusura, dal ciclo della dashboard e dal job serale già esistente (`server.run_daily_job`), una volta
    per seduta e versione del modello: una seconda esecuzione non duplica nulla. Un errore del diario finisce nel log e non
    ferma né i prezzi né il resto del job. Nessuno scheduler nuovo.
  - **Nessuna informazione futura**: si registra solo una seduta chiusa (almeno 15 minuti dopo la chiusura, mai con mercato
    aperto o in pre-apertura) e solo se lo storico giornaliero contiene la sua barra finale ed è stato aggiornato dopo la
    chiusura; la classifica usa solo sedute fino a quella data; le righe salvate **non si possono modificare né cancellare**
    (blocchi nel database); analisti, valutazione e notizie sono salvati come erano in quel momento, senza ricostruire il passato.
  - **Risultati** (`outcomes`): Trading a 5, 10 e 21 sedute, Investimento a 63 e 126, contati sulle date di borsa di QQQ;
    un risultato si calcola solo quando la seduta finale esiste («in attesa» prima). Rendimento del titolo, di QQQ nello stesso
    intervallo, differenza, e mediana di tutti i titoli salvati quel giorno nello stesso intervallo (`universe_medians`). Prezzi
    rettificati per dividendi e frazionamenti, presi dalla stessa serie a entrambe le estremità. Prezzo o QQQ mancanti:
    «prezzo mancante» / «benchmark mancante» (il prezzo che arriva dopo viene misurato allora).
  - **Pannello «Monitoraggio risultati»** (sezione chiusa sotto la classifica): da quando è attivo, giornate, osservazioni,
    maturate, in attesa, prezzi mancanti e casi usati per ogni orizzonte, Trading e Investimento separati. Le medie compaiono
    solo con almeno 100 casi maturati in almeno 20 giornate (come il Diario dei segnali); prima si legge «in raccolta».
    Non è un backtest: nessuna percentuale di successo e nessuna conclusione dai primi casi.
  - **Comandi**: `.venv/bin/python opportunity_diary.py status` (cosa è registrato) e `.venv/bin/python opportunity_diary.py update`
    (registra l'ultima seduta chiusa se manca e misura i risultati maturati, solo con i dati già in `cache/`, senza download;
    con il mercato aperto o in pre-apertura risponde che si registra dopo la chiusura). Indirizzo `/api/opportunities/diary`.
  - **Per i test futuri** (Parte D): `opportunity_diary.dataset("trading", 21)` dà una riga per osservazione con risultato,
    contesto di mercato e versione del modello: confronto selezionati / resto dello stesso giorno, configurazioni diverse del
    ranking (dalle condizioni e dai valori salvati), mercati in salita e in calo, prove fuori campione per data o versione,
    confronto con QQQ e con la mediana dei titoli come strategia passiva. Limiti da ricordare: **non esiste uno storico gratuito
    della composizione del Nasdaq-100**, quindi un test sul passato con i titoli di oggi ha il survivorship bias (dal giorno
    di avvio il diario salva anche la composizione); analisti, stime e notizie non hanno storico (solo da ora in avanti); le
    condizioni Trading, che usano solo i prezzi, si possono provare sul passato con lo stesso metodo della Fase 11 (condizioni
    fissate prima, controllo casuale), senza toccare `backtest.py` né i risultati salvati.
- **Oggi**: 4 indicatori (Nasdaq-100, titoli in rialzo/ribasso, % di titoli sopra le medie 20/40/60 e 200, volatilità VIX e VXN con la fascia: calmo/normale/nervosismo/paura),
  mappa del mercato (clic sul nome di un settore per ingrandirlo), grafico intraday del Nasdaq-100, chi si è mosso e perché, trimestrali dei prossimi 7 giorni
  (i miei titoli in cima).
- **Eventi macro USA** (in Oggi, sopra le trimestrali): riunioni della Fed (FOMC, con conferenza stampa), inflazione CPI e
  PCE, rapporto sull'occupazione nei prossimi 7 giorni, con l'orario di New York e l'ora locale (calcolata, anche quando
  l'ora legale USA ed europea non coincidono). La card è corta: titolo, data, ora e dato uscito (o precedente). Un clic
  sul nome o su "Dettagli →" apre il pannello laterale (lo stesso dei titoli) con: data e ora di New York e italiana,
  valore uscito e del mese prima, spiegazione completa, "come reagisce di solito il mercato" (scenari "se… → di
  solito…", mai previsioni), settori e temi più sensibili, quota del mio portafoglio e preferiti coinvolti con
  l'elenco dei titoli (cliccabili) e la riga "valore atteso: lo trovi nel calendario economico di Fineco (Mercati e
  trading)". Valori di CPI e occupazione dall'API pubblica della BLS; il valore atteso
  non c'è (nessuna fonte gratuita affidabile), il PCE mostra solo la data (i valori richiederebbero una chiave BEA).
  Date ufficiali scritte in `macro_calendar.py` (Fed, BLS, BEA, 2026); ogni giorno la pagina della Fed e il calendario
  BEA vengono riletti per aggiungere le date nuove, con un avviso se il controllo non riesce o se l'elenco sta per finire.
- **In osservazione** (Ricerca; prima "I miei titoli"): i preferiti (★) con prezzo, variazioni, posizione rispetto alle medie, valutazione, analisti, segnale,
  prossima trimestrale e ultima notizia. Salvati in `watchlist.json` nella cartella del progetto.
- **Trimestrali** (in Oggi): una riga compatta per società (data, prima o dopo la seduta, "di solito ±X%"); con un clic
  si aprono utile per azione e ricavi attesi con il numero di analisti, l'ultima trimestrale (atteso, effettivo,
  sorpresa %) e il movimento nel giorno di reazione alle ultime 8 trimestrali (la seduta stessa se i conti escono prima
  dell'apertura, la successiva se escono dopo la chiusura), calcolato dai prezzi giornalieri (`earnings.py`). Un dato
  che Yahoo non fornisce non viene mostrato.
- **Avvisi ⚠** (accanto all'orario di aggiornamento in alto): elenchi di date che finiscono entro 30 giorni (festività
  NYSE, Fed, CPI, PCE, occupazione), controlli automatici delle date non riusciti, sedute senza diario o senza report
  della sera. La spiegazione compare passando il mouse.
- **Rischio per operazione** (unica regola rimasta): quanta parte del portafoglio perdo al massimo se scatta lo stop di
  un'operazione (proposto 1%), con accanto la valuta con cui regolo i titoli USA (EUR con lo spread di cambio di Fineco, o USD). Si modifica nella sezione Decisione della scheda del titolo e si salva in
  `portafoglio/regole.json`. Le quantità vengono solo da questo rischio e dalla distanza tra entrata e stop: non ci
  sono più limiti di peso.
- **Rischio del portafoglio** (Portafoglio → Rischio), con una frase iniziale ("quali posizioni fanno oscillare il
  portafoglio più di quanto pesano") e ⓘ semplici: **volatilità annua** e confronto con
  QQQ; **beta** sul Nasdaq-100; **scenario** "se il Nasdaq-100 perde il 10% / 20% il portafoglio perde circa X €"
  (beta × calo × valore, la leva entra con i prezzi veri dei prodotti a leva); **massima perdita storica** del
  portafoglio di oggi negli ultimi 2 anni, con le date e QQQ negli stessi giorni; **contributo al rischio** di ogni
  posizione confrontato con il suo peso in euro (⚠ da 1,5 volte il peso); **correlazione** media pesata e le 5 coppie
  più simili (massima perdita e correlazione sono nella sezione chiusa "Altre misure"). Metodo (`risk.py`): 2 anni di chiusure giornaliere convertite in euro, portafoglio simulato con i pesi di
  oggi tenuti fissi; volatilità e massima perdita sui rendimenti giornalieri, beta, contributo e correlazioni su quelli
  settimanali (Milano e Francoforte chiudono prima di New York). Restano fuori, e sono elencate con il motivo, le
  posizioni con meno di 6 mesi di prezzi o con prezzi storici anomali (salti di un giorno oltre +150% / −75%). Limiti
  scritti nella sezione: due anni sono pochi, pesi di oggi nel passato, scenario lineare, stime e non previsioni.
  I prezzi si scaricano una volta al giorno e restano in memoria.
- **Storico e performance** (Portafoglio → Performance): ogni giorno, a ogni aggiornamento dei prezzi, la dashboard salva in
  `portafoglio/storico/AAAA-MM-GG.json` valore, costo, cambio e posizioni (solo su questo Mac; i giorni passati non si
  modificano e non si cancellano; i giorni con la dashboard spenta sono ricostruiti con le ultime quantità e le
  chiusure di quei giorni, e segnati come tali). Riquadro **Performance**: grafico del valore in euro con ▲▼ nei giorni
  di acquisti e vendite, e rendimento confrontato con **QQQ in euro** e **VWCE** (Vanguard FTSE All-World, Xetra),
  per 1 mese, 3 mesi, da inizio anno o tutto. Il rendimento è **ponderato per il tempo**: ogni giorno si calcola solo
  sui soldi che c'erano già (valore di fine giornata meno i soldi aggiunti, diviso il valore del giorno prima) e i
  giorni si concatenano, così versamenti e prelievi non contano come guadagni o perdite. I movimenti si ricavano dal
  confronto tra il nuovo file Fineco e il precedente (`portafoglio/storico/flussi.json`): acquisti = aumento del
  "Valore di carico" (esatto), vendite = quantità × prezzo di mercato (stimato). Limiti: i movimenti hanno la data
  di caricamento del file, non ci sono liquidità né dividendi incassati, sotto i 3 mesi lo storico è troppo corto per
  trarre conclusioni. Lo storico parte dal 2 ottobre 2026; dal solo file attuale il passato non si può ricostruire
  (mancano date e prezzi dei singoli acquisti).
- **Indicazioni sulle posizioni** (colonna "Azione" della tabella delle posizioni, Fase 26, regole approvate il 4 novembre
  2026): **niente tesi personale**. Le indicazioni vengono solo dall'analisi del titolo, come quando decido se comprare
  (`actions.py`); accanto compaiono i motivi con i numeri, **cosa fare** e **quando sparisce**. Il pannello della posizione
  mostra quattro parti:
  - **Verdetto di mercato**, "come se dovessi comprare oggi": per le azioni del Nasdaq-100 la sezione Decisione; per le altre
    azioni le stesse regole sui prezzi del titolo (valutazione solo contro la sua storia, `pillars.extra_valuation`); per gli
    ETF/ETC dell'elenco «Ha senso comprare?» solo mercato; per i fondi fuori elenco le stesse regole sui prezzi del fondo, senza
    E4 (patrimonio) e A2 (costo), che lo dice.
  - **Pagella del titolo** (`pillars.py`), uguale per tutti: per le azioni ricavi (+10% sull'ultimo bilancio annuale), stime (non
    tagliate oltre il 3% in 90 giorni), consenso (almeno «Acquisto»), margine operativo (al massimo 1 punto sotto l'anno prima),
    valutazione (non «Cara»), trend (sopra la media 200); per ETF ed ETC trend e diversificazione (correlazione settimanale con il
    resto del portafoglio sotto 0,60). Ogni controllo è ✓, ✕ o **«?»** (dato mancante, che non conta mai come caduto). I cambi
    ✓↔✕ vanno con la data in `portafoglio/pagella.json`, scritti solo con le quotazioni di oggi (mai il prezzo del file Fineco).
  - **Stop automatico** (`stop_auto.py`): la stessa regola del piano di acquisto (`decision.stops`: livello del grafico, media 50
    o ultimo minimo meno mezzo ATR, altrimenti 2 ATR), calcolata ogni giorno dall'ultimo prezzo della stessa serie dei livelli e
    **mai abbassata**; riparte se la posizione viene venduta. Se la regola darebbe uno stop sotto zero (titolo troppo volatile
    rispetto al prezzo) la pagina scrive "non calcolabile" con il motivo. Salvato in `portafoglio/stop_auto.json`.
  - **Le regole**, dal livello più grave:
    - **Valuta la vendita**: S1 prezzo sotto lo stop automatico; S2 almeno 2 controlli caduti e almeno la metà di quelli
      valutabili, solo con almeno 3 controlli valutabili (altrimenti "dati insufficienti" e la pagella non porta alla vendita);
      S3 prodotto a leva tenuto da più di 30 giorni; S4 verdetto di mercato «Evita».
    - **Attenzione**: T1 controllo caduto nelle ultime 10 sedute; T2 prezzo sceso sotto la media 200 nelle ultime 10 sedute;
      T3 stime tagliate di oltre il 3% in 30 giorni; T4 più downgrade che upgrade; T5 trimestrale entro 5 giorni; T6 prezzo a
      meno di 1 ATR sopra lo stop automatico.
    - **Accumula** solo se tutte: B1 azioni almeno 4 ✓ su 6 e nessun ✕, fondi tutti ✓; B2 trend di fondo intatto (prezzo sopra
      la media 200 e media 50 sopra la media 200); B3 verdetto «Entra ora» o «Entra su ritracciamento»; B4 nessuna trimestrale
      entro 5 giorni; B5 nessun avviso; B6 non a leva. **Mantieni**: tutto il resto.
    - Tolte (numeri non riusati): le regole V e A con la tesi (Fase 26), R1, R2 e A3 sui limiti di peso (Fase 21). I file della
      vecchia tesi (`portafoglio/tesi.json`) restano dove sono, ignorati.
  Accanto a "Valuta la vendita" c'è l'**effetto fiscale stimato** (plusvalenza o minusvalenza e imposta indicativa al 26%): per
  azioni ed ETC/ETN tiene conto dello **zainetto fiscale** indicato in Posizioni (sezione chiusa sotto la tabella,
  `portafoglio/fiscale.json`); per gli ETF UCITS no, perché i guadagni sono redditi di capitale. Stima indicativa, non consulenza
  fiscale. Regole di disciplina, **non verificate da un backtest**: le verifica il diario delle posizioni.
- **Diario delle posizioni** (`pos_diary.py`, Fase 26): ogni sera, dopo la chiusura di Wall Street, il livello di ogni posizione,
  le regole scattate, la pagella, il verdetto di mercato e il prezzo in euro in `portafoglio/diario_posizioni/` (un file per
  seduta, mai modificato, con la versione delle regole: il test conta solo i giorni salvati con le regole in vigore).
  Test fissato il 4 novembre 2026, prima di vedere i risultati: a 3 mesi «Valuta la vendita» funziona se le posizioni segnalate
  fanno peggio delle altre posizioni dello stesso giorno in almeno il 60% dei casi, con una differenza mediana di almeno 2 punti;
  «Accumula» al contrario; sotto i 30 casi "dati ancora insufficienti". Le posizioni vendute prima dei 3 mesi escono dal conto.
- **Portafoglio → Posizioni** (in quest'ordine: caricamento del file su una riga con la data del file attuale,
  riepilogo con valore, guadagno/perdita, effetto cambio e variazione di oggi, tabella delle posizioni, zainetto
  fiscale in una sezione chiusa): le mie posizioni reali, dall'export Excel di Fineco ("Portafoglio sintesi") messo nella cartella
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
- **Settori**: **mappa di rotazione** di temi e settori rispetto a QQQ (Leader, In miglioramento, In indebolimento,
  In ritardo; calcolata dalla dashboard con le ultime chiusure, prima era nel Report), rendimenti dei settori pesati per capitalizzazione e peso di ogni settore nell'indice. Clic su una riga:
  compaiono i titoli di quel settore; di nuovo sulla stessa riga (o "Tutti i settori") si torna a tutti.
- **ETF** (scheda principale ETF, Fase 24; `etf.py`, `/api/etf`): 63 ETF ed ETC UCITS quotati in Italia (`etf_universe.json`, elenco
  approvato l'8 ottobre 2026). I dati si calcolano una volta al giorno in background (qualche minuto la prima volta) e
  ancora una volta dopo le 18:00, quando le chiusure di Borsa Italiana sono definitive.
  - **Dati mancanti detti a parole**: se Yahoo non dà i prezzi degli ETF la pagina scrive «prezzi non disponibili» con
    l'ora del nuovo tentativo (ogni 15 minuti) e mostra i dati dell'ultimo giorno buono con la data; una riga senza
    prezzi lo dice; se mancano i prezzi del portafoglio «Per il mio portafoglio» resta «in attesa» (con l'ora del nuovo
    tentativo) e si vede il verdetto del solo mercato. Mai trattini o verdetti incompleti.
  - **Periodi di osservazione**: 1 settimana, 2 settimane, 1 mese, 3 mesi, 6 mesi, 1 anno, 3 anni (3 anni solo con uno
    storico vero o di ripiego segnalato con *). La tabella mostra 1 settimana, 1 mese, 3 mesi, 1 anno e 3 anni; l'ordine si
    sceglie cliccando le intestazioni; 2 settimane, 6 mesi, volatilità, perdita massima e momentum 12-1 sono nel pannello.
  - **Trend** (regola stretta approvata): Rialzista se il prezzo è sopra la media 50 e la media 50 sopra la media 200,
    Ribassista se il prezzo è sotto la media 50 e la media 50 sotto la media 200, Laterale altrimenti; con un
    mini-grafico di 6 mesi e la linea della media 200, in tabella e nel pannello.
  - **Ha senso comprare?** (`etf_buy.py`): un verdetto per ogni ETF, Entra ora / Entra su ritracciamento / Attendi /
    Evita (Solo informazione per i prodotti a leva), con le regole sotto il verdetto e ✅/❌: E1 leva, E2 trend
    ribassista, E3 si sovrappone al portafoglio, E4 patrimonio sotto 100 milioni → Evita; A0 trend non calcolabile, A1
    trend laterale, A2 TER sopra 0,50%, A3 «neutro» per il portafoglio → Attendi; R1 rischio di essere arrivati tardi
    alto → Entra su ritracciamento (entrata alla media 50); altrimenti Entra ora. Una seconda riga, «Solo mercato»,
    applica le stesse regole senza E3 e A3. Sempre «non verificato»; il momentum 12-1 è solo un'informazione.
  - **Piano operativo**: entrata, stop con la stessa regola delle azioni (media 50 o ultimo minimo meno mezzo ATR,
    altrimenti 2 ATR), obiettivo a 2 volte il rischio, quantità dal rischio per operazione con un **tetto del 10% del
    portafoglio per ogni ETF** («quantità limitata al 10% del portafoglio: con questo stop l'1% di rischio
    richiederebbe il X%», più il rischio effettivo). Il tetto vale solo per gli ETF. Prezzi della stessa borsa dello
    storico (Borsa Italiana o Xetra, sempre in euro: nessuno spread); se Milano e Xetra differiscono di oltre il 2% nei
    dati di Yahoo la pagina avvisa di controllare il prezzo su Fineco (oggi succede al Brasile).
  - **Diario degli ETF**: dopo la chiusura di Borsa Italiana i due verdetti di ogni ETF vanno in
    `portafoglio/diario_etf/AAAA-MM-GG.json` (un file per seduta, mai riscritto), solo con chiusure definitive e
    con il confronto con il portafoglio completo (correlazione compresa); anche dal job serale. Una sezione chiusa della
    scheda ETF (`/api/etf/diary`) mostra come è andato ogni verdetto a 1, 3 e 6 mesi contro tutti gli ETF dello stesso giorno.
  - **Tabella** con filtro per gruppo e ordinamento dalle intestazioni. Colonne: nome, 1 settimana, 1 mese, 3 mesi, 1 anno,
    3 anni, trend (parola e mini-grafico), TER, «Ha senso comprare?», «Per il mio portafoglio». Sta nella larghezza della
    pagina; su schermi stretti scorre solo la tabella, con il nome fermo. Rendimenti in euro.
  - **Cosa diversifica di più il tuo portafoglio** (riquadro in cima): investendo il 10% del portafoglio, i 3 ETF azionari
    e i 3 obbligazionari o difensivi (oro compreso) che abbassano di più la concentrazione più alta tra tecnologia, USA e
    dollaro. Esclusi i temi, i prodotti a leva e chi farebbe salire anche una sola delle tre; a parità di effetto viene
    prima chi abbassa di più le altre due, poi il TER più basso; un ETF per categoria. È una misura dell'effetto sul
    portafoglio, non una previsione di rendimento.
  - **Storico dei prezzi**: Borsa Italiana se completo, altrimenti Xetra, altrimenti l'ETF americano convertito in euro
    con il cambio di ogni giorno. I rendimenti calcolati con uno storico di ripiego hanno un asterisco in tabella (con la
    spiegazione nella ⓘ); il pannello indica la fonte e la data di nascita dell'ETF.
  - **Ha senso per il mio portafoglio?** Regole: sovrapposizione sui primi 10 titoli (somma dei pesi minori, guardando
    dentro i miei fondi; per gli ETF molto ampi il valore reale è più alto); accanto, solo come informazione, la «quota
    dell'ETF in titoli che già possiedi» con l'elenco dei titoli in comune. I primi 10 titoli vengono da `etf_holdings.py`:
    prima i file delle composizioni degli emittenti (iShares, Xtrackers, SPDR), poi l'ETF americano sullo stesso indice,
    infine justETF (al massimo una volta ogni 6 mesi per ETF, con una pausa tra le richieste e stop al primo rifiuto); fonte
    e data nel pannello. I titoli si confrontano per ISIN o per nome della società (le classi di azioni della stessa
    società contano come una); correlazione settimanale in euro su 2 anni;
    concentrazione in tecnologia, USA e dollaro (stimato dagli USA) se investissi il 10%. **Si sovrappone** se la
    sovrapposizione è almeno 25 punti, o la correlazione almeno 0,85, o la concentrazione più alta sale di almeno 1 punto.
    **Diversifica** se la sovrapposizione è sotto 10, la correlazione sotto 0,60 e una concentrazione scende di almeno 1
    senza che nessuna salga di più di 0,5. Altrimenti **neutro**. Note «costoso» con TER sopra lo 0,50% e «patrimonio
    piccolo» sotto i 100 milioni.
  - **Pannello dell'ETF**: «Perché si muove» in vista (calcolato all'apertura, `/api/etf/why/<isin>`: i due primi titoli
    dell'ETF americano equivalente che spiegano almeno il 10% del movimento a 1 mese, 3 mesi e 1 anno, oltre il 100%
    spiegato a parole; «si muove come» con correlazione almeno 0,70, altrimenti «non si muove in modo simile a nessun'altra
    categoria (correlazione massima X con Y)»; notizie sui due primi titoli), rendimenti in euro con la parte dovuta al
    cambio (per i sottostanti in una sola valuta), trend, rischio di essere arrivati tardi, dettagli
    della sovrapposizione, composizione e dati di justETF con fonte e data (avviso se hanno più di 6 mesi), P/E
    dell'ETF americano equivalente, ⓘ sulle tasse, ★ per metterlo In osservazione e link alla posizione se lo possiedo.
    Gli ETF americani sono solo fonti di dati, mai prodotti da comprare.
  - **Sezioni chiuse**: ETF in osservazione (solo con almeno una ★), mappa di rotazione delle categorie rispetto
    all'All-World (VWCE; segue la colonna ordinata, 3 mesi se non è un rendimento; nomi scritti per le 5 categorie più
    avanti e le 5 più indietro), diario degli ETF. Il radar dei temi e la sezione del test sono stati tolti il 10 ottobre
    2026: il «perché» è nel pannello, i risultati del test sono qui sotto e in una ⓘ dell'avviso in alto.
  - Se i prezzi storici del portafoglio non arrivano da Yahoo, la dashboard riprova dopo 15 minuti (prima restavano vuoti
    fino al giorno dopo) e la pagina lo scrive, invece di mostrare verdetti senza correlazione.
- **Diario dei segnali** (Ricerca → Diario, visibile solo con almeno 63 sedute, circa 3 mesi; prima registra in
  background): analisti, valutazione e notizie non si possono provare sul passato, quindi
  i verdetti della sezione Decisione si verificano da oggi in avanti. Dopo ogni chiusura (o al primo avvio prima
  dell'apertura successiva) la dashboard salva in `portafoglio/diario/AAAA-MM-GG.json` il verdetto di ogni titolo del
  Nasdaq-100 e delle mie posizioni: data, prezzo, verdetto, livelli del piano e regole soddisfatte o no. Dopo 1, 3 e
  6 mesi (21, 63 e 126 sedute) la pagina **Diario** misura ogni categoria di verdetto contro QQQ e contro tutti i
  titoli dello stesso giorno: casi, giorni, rendimento medio e mediano, extra-rendimento, % di volte meglio. Finché
  una categoria ha meno di 100 casi o meno di 20 giorni diversi la pagina scrive "troppo pochi casi". Il diario non si
  modifica mai a posteriori: un giorno si scrive una volta sola, anche se poi le regole cambiano. Le posizioni fuori
  dal Nasdaq-100 sono salvate ma non entrano nelle statistiche. I risultati si vedono anche **per regola che ha deciso
  il verdetto** (per esempio "Attendi" per trimestrale D2 o per media 200 D4), ricavata dalle regole salvate ogni giorno.
  La data di ogni giorno è quella della seduta dei prezzi (Fase 21: il giorno `2026-10-01` era stato salvato il 2 ottobre
  con i prezzi del 2 ottobre; il file resta com'è ma è escluso dalle statistiche con `portafoglio/diario/esclusi.json`).
  Le sedute senza diario compaiono nella ⚠ in alto e nella pagina.
- **Scheda titolo**: grafico 1G–MAX, confronto con NDX, fondamentali, target degli analisti, notizie, più:
  - **Analisi** (Fase 22, in cima alla sezione Decisione, in stile pagina "Analisi" di Fineco; riusa i calcoli esistenti e
    non cambia le regole del verdetto). In vista: **segnale** (il verdetto di oggi, "dalla data" = primo giorno della serie
    consecutiva di giorni del diario con lo stesso verdetto, al prezzo di quel giorno e con la variazione da allora; se il
    diario ha pochi giorni lo dice; poi entrata, stop, target e rapporto rischio/rendimento), **tendenza** a 1 settimana,
    1 mese e 3 mesi (▲ oltre +1% / +2% / +4%, ▼ sotto le stesse soglie, = in mezzo) e **commento** automatico da frasi
    fisse approvate (tendenze, medie, supporto e resistenza più vicini, oscillazione, volumi, trimestrale entro 30 giorni
    con il movimento tipico, verdetto e motivo, una frase "per chi possiede il titolo" e una "per chi non lo possiede").
    In sezioni chiuse: **supporti e resistenze** (massimi e minimi significativi delle ultime 120 sedute, massimo e minimo
    a 52 settimane, medie 50 e 200; livelli a meno dell'1% uniti in zone; due sopra e due sotto) e **punti pivot** del
    giorno (formula classica sui prezzi di ieri); **oscillazione normale a 5 giorni** (deviazione standard dei rendimenti
    giornalieri delle ultime 63 sedute × √5: fasce del 68% e del 90%, con l'avviso se lo stop cade dentro la fascia del
    68%); **dati sintetici** (volumi medi 5 e 21 giorni e rapporto, variazioni a 1, 5, 21 giorni, volatilità a 5, 10, 21
    giorni); **consenso degli analisti** (Strong Buy … Strong Sell, voto medio 1–5 calcolato dalla distribuzione, prezzo
    obiettivo medio e potenziale, ultima trimestrale con sorpresa e nota se oltre il 100%); **piano pronto per Fineco**
    (tipo di ordine e prezzo, stop loss e take profit autoescludenti, scadenza giornaliera per "Entra ora" e 30 giorni per
    gli ordini limite e condizionati, quantità dal rischio per operazione, note su after hours e AutoFX, pulsante "Copia
    riepilogo ordine"). Le quantità includono lo **spread di cambio di Fineco** (0,0033 sul EUR/USD all'acquisto e
    all'uscita) se regolo in euro; l'impostazione "Regolo i titoli USA in EUR / USD" sta accanto al rischio per
    operazione e si salva in `portafoglio/regole.json`. Niente pattern a candela: andrebbero prima testati come nella Fase 11.
  - **Decisione** (solo titoli del Nasdaq-100; assorbe la vecchia "Analisi tecnica"): la scheda che un analista
    porterebbe al comitato d'investimento, in cinque blocchi letti in ordine (`decision.py`).
    **1. Azienda e valutazione** (decide SE comprare): otto criteri da +1 / 0 / −1 (crescita di ricavi e utili oltre il
    10% o negativa, margine netto oltre il 15% o sotto il 5%, cassa generata oltre il 10% dei ricavi o negativa, debito
    netto ripagabile in meno di 2 o più di 5 anni di cassa, valutazione Economica o Cara, stime riviste di oltre +2% o
    −3%, più upgrade o più downgrade) e la sintesi: solida (da +3), debole (da −1 in giù), nella media.
    **2. Contesto**: settore e tema (fase di rotazione, titolo contro il gruppo), eventi macro dei prossimi 7 giorni,
    giorni alla trimestrale. **3. Tempismo tecnico** (decide QUANDO e A CHE PREZZO): medie e trend, livelli chiave,
    pattern presenti con l'etichetta "verificato" o "non verificato" dal test della Fase 11.
    **4. Posto nel mio portafoglio** (decide QUANTO): se lo possiedo e quanto pesa, sovrapposizione con i miei ETF sul
    Nasdaq-100 e il campo del **rischio per operazione**.
    **5. Piano operativo** con il verdetto e, sotto, l'elenco delle regole soddisfatte (✅) e non (❌); decide la prima
    non soddisfatta: D1 azienda debole → **Evita**; D2 trimestrale entro 5 giorni → **Attendi: trimestrale il …**;
    D4 prezzo sotto la media 200 → **Attendi**; D5 tirato (oltre l'8% sopra la media 20 o RSI oltre 75) → **Entra su
    ritracciamento** (ordine limite vicino alla media 20 o 50); D6 entro il 3% sotto il massimo a 52 settimane →
    **Attendi: a ridosso del massimo** (il livello di rottura e l'ordine condizionato restano visibili come
    informazione, con "pattern non verificato": la rottura non ha superato il test della Fase 11); D7 azienda nella
    media e prezzo oltre il 2% sopra la media 20 → **Entra su ritracciamento**; tutte soddisfatte → **Entra ora**.
    (Fase 21: tolta la regola D3 sui limiti di peso; gli altri numeri restano gli stessi, per confrontare il diario.) Per i titoli che possiedo il verdetto è l'azione della Fase 17.
    Ogni piano ha entrata, stop (sotto la media 50 o l'ultimo minimo meno mezzo ATR se tra 1,5 e 3,5 ATR, altrimenti
    2 × ATR; le altre opzioni si possono cliccare), target a 2 volte il rischio e quantità calcolata solo dal rischio per
    operazione (nessun tetto: la pagina mostra quanto peserebbe la posizione). Regole non verificate da backtest (lo dice la sezione): le
    misura il Diario dei segnali.
  - **Valutazione** (Economica / In linea / Cara): P/E atteso, P/S ed EV/EBITDA contro la mediana dei titoli dello
    stesso settore nel Nasdaq-100 (saltato se il settore ha meno di 3 titoli) e P/E / P/S di oggi contro la mediana
    alle ultime ~4 chiusure di bilancio, più il PEG. Lo storico usa gli utili realizzati (Yahoo non ha lo storico del
    P/E atteso) e stima le capitalizzazioni passate dal prezzo, ignorando buyback e diluizione.
  - **Analisti**: giudizi oggi e 3 mesi fa, upgrade/downgrade e target degli ultimi 30 giorni, stime di utili e
    ricavi con la loro revisione a 30/90 giorni, ultime azioni delle banche d'affari.
  Questi dati si scaricano una volta al giorno in background (circa 15 secondi) in `cache/analysts.json`. La cache porta una
  versione dei campi (`analysts.SCHEMA`, Fase O2): una cache scritta da codice più vecchio, per esempio senza l'utile
  operativo dei bilanci aggiunto nella Fase 26, viene riscaricata una volta sola anche se è del giorno stesso.
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

## Report e job programmati

Il report tecnico (`signals.py`) non è più una pagina della dashboard (Fase 21): la mappa di rotazione ora è in
Mercato → Settori e i titoli di ogni pattern nella sezione Decisione. Con la programmazione di macOS (launchd), dal
lunedì al venerdì, ora locale:

- **08:30** riepilogo del mattino (`morning_job.py`, Fase 23): se c'è qualcosa di rilevante compare una finestra con gli
  eventi macro di oggi (orario italiano), le trimestrali dei miei titoli (preferiti e portafoglio) nei prossimi 5 giorni,
  il numero di posizioni in "Valuta la vendita" e le sedute mancanti nel diario; pulsanti "Chiudi" e "Apri la pagina Oggi"
  (apre la dashboard su Oggi, avviando l'app se è chiusa). Senza niente di rilevante, nessuna finestra. È una finestra e
  non una notifica perché su macOS il clic su una notifica creata da uno script apre l'Editor di Script, non il browser;
  si chiude da sola dopo 30 minuti. Il report del mattino non viene più generato. Prova a mano:
  `.venv/bin/python morning_job.py` (con `--print` solo il testo, senza finestra);
- **22:45** job serale (`daily_job.py`): report della sera, diario dei segnali e fotografia del portafoglio del giorno,
  **anche con la dashboard chiusa**. Scrive solo quello che manca: se anche la dashboard è aperta, il primo che salva
  vince e l'altro salta.

Se il Mac è in stop all'orario, macOS esegue il job al risveglio (il diario usa i prezzi della seduta chiusa, ma i dati
degli analisti sono quelli del risveglio; l'ora è salvata nel file). Se il Mac è spento il job salta: un giorno di
diario non si può ricostruire dopo, e la ⚠ in alto lo segnala.

```sh
./schedule.sh install   # attiva (o riattiva) la programmazione delle 08:30 e delle 22:45
./schedule.sh status    # dice se è installata e mostra le ultime righe dei log
./schedule.sh run       # esegue subito il job serale, come farebbe la programmazione
./schedule.sh remove    # disattiva
```

Log: `reports/logs/morning_job.log` / `.err` (mattino) e `reports/logs/daily_job.log` / `.err` (sera). Dopo la Fase 23 va
rifatto `./schedule.sh install`, perché il job delle 08:30 cambia programma.
Il report è uno screening meccanico, **non è una consulenza finanziaria**.

## Backtest del Trend (parte tecnica)

```sh
.venv/bin/python backtest.py   # circa 10 secondi, salva reports/backtest.json
```

Ogni settimana degli ultimi ~10 anni ricalcola, per i titoli di oggi, il punteggio tecnico della dashboard (stesso
codice: la verifica automatica deve dare differenza 0), lo mette in una fascia con le stesse soglie del segnale e misura il rendimento
a 1, 3 e 6 mesi del titolo e di QQQ negli stessi giorni: rendimento medio, extra-rendimento medio e mediano, % di volte
meglio di QQQ, numero di casi, e la tabella anno per anno. Testa solo il Trend: visto che le fasce estreme vanno entrambe
meglio di quelle centrali (la parte tecnica non distingue la direzione), il Trend non fa più parte del segnale finale. Limiti
principali: survivorship bias (si usano i componenti di oggi), casi sovrapposti, un solo tipo di mercato, nessun costo.
Pesi e soglie non vengono adattati ai risultati.

Risultati (29 settembre 2026: casi dal 10 gen 2017 al 27 mar 2026, 99 titoli, 41.935 osservazioni settimanali), a 3 mesi:

| Fascia del Trend | Casi | Rendimento medio | Extra vs QQQ (media) | Extra vs QQQ (mediana) | % volte meglio di QQQ | vs media di tutti |
|---|---|---|---|---|---|---|
| Molto positivo | 8.761 | +8,59% | +3,77 | −0,10 | 49,7% | +2,08 |
| Positivo | 9.665 | +5,69% | +0,79 | −0,41 | 48,5% | −0,90 |
| Neutro | 12.081 | +6,06% | +0,56 | −0,55 | 48,6% | −1,14 |
| Negativo | 6.601 | +7,40% | +1,38 | −0,27 | 49,1% | −0,31 |
| Molto negativo | 4.827 | +8,86% | +2,99 | +1,04 | 52,2% | +1,30 |
| Tutti i titoli | 41.935 | +7,04% | +1,69 | −0,22 | 49,3% | — |

Le due fasce estreme vanno meglio di quelle centrali: il Trend non distingue la direzione, per questo non fa parte del
segnale finale.

## Test dei pattern tecnici (Fase 11)

```sh
.venv/bin/python backtest.py --patterns   # circa 15 secondi, salva reports/patterns.json (usato dalla sezione Decisione)
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

## Test del momentum sulle categorie di ETF (Fase 24)

`etf_backtest.py` (a mano, `.venv/bin/python etf_backtest.py`, risultato in `reports/etf_momentum.json`) prova due regole
sulle 47 categorie misurabili con un ETF americano di lunga storia, ogni mese dal 3 aprile 2000 al 1 aprile 2026
(313 mesi, 11.835 osservazioni). Idrogeno e Chip di memoria non sono misurabili. Misura: rendimento a 3 mesi della
categoria meno la media di tutte le categorie dello stesso mese. Le condizioni sono le stesse 6 della Fase 11, fissate
prima dei risultati; il controllo casuale usa 200 regole finte.

| Condizione | M1: momentum 12-1 nel terzo migliore | M2: sopra la media 200 |
|---|---|---|
| 1. media dell'extra a 3 mesi almeno +0,5 punti | ❌ +0,37 | ❌ +0,08 |
| 2. mediana sopra 0 | ✅ +0,20 | ❌ −0,08 |
| 3. positiva in almeno 2/3 degli anni | ✅ 18 su 27 | ❌ 12 su 27 |
| 4. positiva in entrambe le metà | ✅ +0,19 / +0,50 | ✅ +0,11 / +0,06 |
| 5. a 6 mesi non negativa | ✅ +0,70 | ✅ +0,18 |
| 6. almeno 100 casi | ✅ 4.053 | ✅ 8.185 |
| **Esito** | **non superato** | **non superato** |
| Controllo casuale (regole finte che superano tutto) | 0 su 200 | 0 su 200 |

**M2 come protezione nei crolli.** Soglia fissata prima del test: la massima perdita deve ridursi di almeno un terzo in
almeno 2/3 delle categorie con almeno 5 anni di storia, e la volatilità deve essere più bassa in almeno 2/3. Risultato:
perdita ridotta di un terzo in 24 categorie su 47 (ne servivano 32); volatilità più bassa in 47 su 47, un risultato
meccanico perché nei mesi sotto la media si sta fuori. Quindi la protezione è **non verificata**. Aiuta nei crolli lunghi
(Nasdaq da −83% a −45%, Finanziari da −83% a −36%) ma non in quelli rapidi (Oro da −46% a −42%, Sanità da −39% a −41%),
e riduce il rendimento annuo in molte categorie (Mondo da 11,6% a 7,4%).

In parole semplici: il momentum ha mostrato un vantaggio coerente ma piccolo (+0,37 punti ogni 3 mesi, circa 1,5% l'anno
prima dei costi), sotto la soglia fissata prima del test: resta non verificato.

**Regola della dashboard:** nella scheda ETF momentum e trend sono informazioni **non verificate**: niente «favorevole
adesso» né «investi». Limiti: le categorie sono misurate con ETF americani in dollari, nessun costo, test multipli.

## Laboratorio di validazione delle condizioni Trading (Fase O3)

`opportunity_validation.py` è uno **studio esplorativo con survivorship bias** delle cinque condizioni Trading (T1–T5) della
scheda Opportunità. Non cambia lo scanner, la classifica, le soglie (`MODEL_VERSION` resta O2.1) né il diario delle
opportunità. Si avvia solo a mano dal Terminale, mai dentro la dashboard:

```sh
.venv/bin/python opportunity_validation.py config         # configurazione, soglie, regole di evidenza e limiti
.venv/bin/python opportunity_validation.py run --scarica  # scarica 10 anni (dal 1/10/2015) e fa lo studio (~15 secondi)
.venv/bin/python opportunity_validation.py run            # rifà lo studio sugli ultimi prezzi salvati (stessi dati)
.venv/bin/python opportunity_validation.py run --dashboard  # solo i 2 anni della cache della dashboard, nessun download
.venv/bin/python opportunity_validation.py show [file]    # stampa l'ultimo report salvato (o quello indicato)
.venv/bin/python opportunity_validation.py investimento   # cosa permettono i dati per l'Investimento (nessun backtest)
```

**Dove**: `data/validazione/` (fuori da Git): `prezzi_*.pkl` (i prezzi usati, per poter rifare lo stesso studio),
`report_*.json` (un file per studio, mai riscritto), `esperimenti.jsonl` (registro degli esperimenti: si aggiunge una riga
per studio, con codice della configurazione e periodo finale aperto sì/no), `riepilogo.json` (l'unico file che legge la
dashboard). Nessun file del diario viene aperto in scrittura: il comando `investimento` legge il diario solo se esiste, in
sola lettura.

**Cosa si può provare sul passato e cosa no**
- T1–T5 usano solo prezzi e volumi giornalieri: si ricalcolano per ogni giorno passato con i soli dati di quel giorno. Ogni
  studio confronta 200 casi a caso con `opportunity_scanner` (stessi risultati, altrimenti si ferma).
- I1–I5 (bilanci, stime, consenso, valutazione) e gli avvisi (notizie, trimestrali) esistono solo con i dati di oggi:
  **nessuna Pagella retroattiva e nessun backtest dell'Investimento**. Si misurano solo in avanti con il diario (63 e 126
  sedute); lo storico di 2 anni della dashboard basta per misurarle finché il diario continua.
- L'universo è il **Nasdaq-100 di oggi** (non esiste uno storico della composizione): mancano i titoli usciti, spesso
  perché scesi, e ci sono quelli entrati dopo. Rendimenti assoluti, contro QQQ e contro l'universo sono spinti verso l'alto.

**Metodo** (fissato prima di vedere i risultati, 4 novembre 2026; versione del laboratorio `VERSION` = V1)
- Prezzi Yahoo rettificati per frazionamenti e dividendi per titoli e QQQ (rendimenti vicini a quelli totali, per tutti);
  solo sedute chiuse; titoli con giorni di borsa diversi da QQQ esclusi; prezzi mancanti mai riempiti. I movimenti oltre
  ±40% in un giorno sono elencati da controllare (possibili eventi societari non rettificati), non corretti.
- **Statistiche dei segnali**: rendimento dalla chiusura del giorno del segnale alla chiusura 5, 10 e 21 sedute dopo (sul
  calendario di QQQ), confrontato negli stessi giorni con QQQ, con tutti i titoli, con i titoli non scelti e con 200 scelte
  a caso dello stesso numero di titoli tra quelli osservabili quel giorno. Differenze calcolate **giorno per giorno** e poi
  mediate (i segnali dello stesso giorno non sono indipendenti), con errori di Newey-West (ritardo = orizzonte) e il
  numero di periodi che non si sovrappongono.
- **Periodi**: sviluppo (60% dei giorni), verifica (20%), finale (20%) **sigillato**, in ordine di tempo, togliendo 21
  sedute a ogni confine (i rendimenti futuri non attraversano il confine). Il periodo finale si apre solo con
  `--apri-finale`, che resta scritto nel registro: non va usato per scegliere o ritoccare le regole.
- **Giudizio** (mai «validato»): «Evidenza insufficiente» con meno di 100 segnali o 20 periodi indipendenti nello sviluppo;
  «credibile nello studio esplorativo» solo con |t| ≥ 2, fuori dal 95% delle scelte a caso e stesso segno nella verifica
  (con almeno 10 periodi indipendenti); altrimenti «osservata, non credibile» o «non confermata».
- **Walk-forward**: ogni anno si sceglie l'alternativa migliore sugli anni prima e la si misura nell'anno.
- **Simulazione sperimentale** (separata): segnale alla chiusura → acquisto all'**apertura della seduta dopo**, vendita
  all'apertura 21 sedute dopo, regola 4 su 5, massimo 10 titoli in quote uguali, mai lo stesso titolo due volte, capitale
  ipotetico 10.000, costi ipotetici 0 / 0,10 / 0,25% per lato (commissione e scarto insieme, **non** le tariffe di Fineco),
  valore del portafoglio a ogni chiusura (le operazioni sovrapposte non si sommano). Confronto con QQQ e con 20 simulazioni
  con le stesse regole su titoli scelti a caso.

**Risultati del 4 novembre 2026** (10 anni, 101 titoli, 242.667 osservazioni; sviluppo e verifica dall'11 gennaio 2016 al
10 luglio 2024; periodo finale dal 9 agosto 2024 sigillato, non aperto). Orizzonte 21 sedute, differenza media di ogni giorno:

| Gruppo | Segnali | Contro i non scelti | Contro QQQ | Giudizio a 5 · 10 · 21 sedute |
|---|---|---|---|---|
| T1 più forte di QQQ a 1 mese | 92.990 | −0,56 | +0,24 | non credibile · **peggiore, credibile** · **peggiore, credibile** |
| T2 più forte di QQQ a 3 mesi | 95.254 | −0,12 | +0,48 | non credibile (tutti) |
| T3 sopra le medie 20 e 50 | 95.228 | −0,40 | +0,37 | **peggiore, credibile** · non credibile · non credibile |
| T4 media 20 in salita | 111.940 | −0,43 | +0,43 | non credibile (tutti) |
| T5 volumi 20/60 almeno 1 | 82.513 | +0,04 | +0,57 | non credibile (tutti) |
| Almeno 3 su 5 | 96.960 | −0,45 | +0,27 | **peggiore, credibile** · **peggiore, credibile** · non credibile |
| **Almeno 4 su 5 (regola attuale)** | 62.317 | −0,12 | +0,43 | non credibile (tutti) |
| Tutte e 5 | 22.580 | −0,09 | +0,41 | non credibile (tutti) |

In parole semplici: nessuna condizione e nessuna combinazione ha fatto meglio dei titoli non scelti dello stesso giorno.
Battere QQQ di qualche decimo è comune a quasi tutti i gruppi, anche a quelli deboli (i titoli deboli contro QQQ: +0,80),
quindi viene dal survivorship bias, non dalla selezione. L'unico effetto «credibile» va al contrario: chi è più forte di
QQQ nell'ultimo mese è andato un po' peggio degli altri nel mese dopo. La simulazione (+823% con costi 0,10%, contro QQQ
+360%) sta dentro le scelte a caso con le stesse regole (mediana +545%, 10°–90° percentile da +427% a +790%): il guadagno
viene dall'universo dei sopravvissuti e dalla volatilità, non dalle condizioni. Le condizioni T1–T4 sono legate tra loro
(correlazione 0,3–0,6), T5 è indipendente dalle altre. Il walk-forward non trova un'alternativa stabile (la scelta
migliore sul passato resta positiva 3 anni su 7). **Nessuna soglia dello scanner è stata cambiata**: eventuali modifiche
solo su decisione esplicita dell'utente e poi con la conferma del diario.

Nella scheda Opportunità il pannello chiuso **«Qualità dei segnali»** mostra il riepilogo dell'ultimo studio
(`/api/opportunities/validation`, legge solo `riepilogo.json`), separato dal «Monitoraggio risultati» del diario.

## Qualità dei dati e stato di affidabilità (Fase 4A)

- `market_data_quality.py` (`.venv/bin/python market_data_quality.py [prezzi.pkl] [--report r.json] [--salva]`): controlli
  riproducibili (serie, date NYSE, duplicati, prezzi nulli, OHLC incoerenti, volumi, prezzi fermi, anni illiquidi, variazioni
  oltre ±40%, inversioni, possibili frazionamenti, prezzi prima della quotazione regolare, dati dopo la data del calcolo).
  **Segnala, non corregge.** Stati: errore verificato, dato sospetto non verificato, movimento reale confermato, dato mancante;
  solo una revisione con fonti (`data_quality_reviews.json`, versione R1, criteri scritti prima della rielaborazione) dà
  «errore» o «reale».
- Verifiche del 4 novembre 2026: **FER** prima del 9/5/2024 non è il titolo del Nasdaq (volume zero in 1.748 sedute; i salti
  del 2018 e del 2020 sono smentiti dalla quotazione di Madrid) → errore verificato; **MRNA** +177% il 19/8/2026 → movimento
  reale (risultati di fase 3 sul melanoma); **HONA** 15–26/6/2026 → negoziazione «when-issued», errore verificato; **HON**
  29/6/2026 → rettifica dello scorporo sospetta, non verificata.
- `opportunity_validation.py rielabora [report]`: riproduce lo studio originale dagli stessi prezzi (identico) e lo rifà senza
  i tratti «errore verificato» con exclude=true, in `data/validazione/rielaborazioni/` (i report della Fase 3, il registro e il
  periodo finale restano intatti). Esito: differenza massima 0,19 punti; 4/5 resta −0,12 contro i non scelti; cambiano solo due
  giudizi a 5 sedute (T3 e 3 su 5 da «peggiore, credibile» a «non credibile»).
- Stato di affidabilità (`opportunity_validation.reliability`, criteri nel codice): classifiche = «Screening esplorativo»;
  Trading 4/5 e 5/5 «non validate»; Investimento «non validata» finché il diario non registra, poi «in verifica» (solo in
  avanti). «Validata» solo con studio storico credibile, conferma del periodo finale (aperto una volta) e del diario.

## Ricerca controllata di nuove strategie Trading (Fase 4B)

`opportunity_strategies.py` è un'area sperimentale separata dallo scanner: non cambia regole, soglie o classifiche. Studia
tre famiglie con **una sola configurazione ciascuna**, scritta e registrata prima dei risultati in
`docs/ricerca_strategie_4b.md`.

```sh
.venv/bin/python opportunity_strategies.py ipotesi     # ipotesi, regole, criteri e condizioni di falsificazione
.venv/bin/python opportunity_strategies.py config      # configurazione, versione, impronta e se è registrata
.venv/bin/python opportunity_strategies.py registra    # registra la configurazione (una volta per versione, prima dello studio)
.venv/bin/python opportunity_strategies.py run         # esegue lo studio (rifiutato se la configurazione è cambiata)
.venv/bin/python opportunity_strategies.py show [A|B|C]  # report salvati
.venv/bin/python opportunity_strategies.py registro    # registro degli esperimenti
```

- **Dati.** Usa i prezzi congelati della Fase 3, controllati con un'impronta, senza i tratti «errore verificato» della
  revisione R1. I prezzi dal 9 agosto 2024 (periodo finale riservato) non vengono caricati. I settori sono quelli ICB di oggi,
  congelati in `data/strategie/settori_icb_2026-11-03.json`: lo storico delle classificazioni non esiste.
- **Risultati.** Vanno in `data/strategie/`: registrazione, un report per strategia, registro e riepilogo per il pannello.
- **Esito del 4 novembre 2026** (S1, impronta `9c7c2763fd71`), sempre «Studio esplorativo con survivorship bias»:
  - **A, momentum relativo al settore**: «Nessun vantaggio rilevato». Non aggiunge informazione rispetto al momentum
    semplice: +0,01 punti, t 0,1.
  - **B, ritracciamento nel trend**: «Nessun vantaggio rilevato». Fa −0,12 punti contro i non scelti, e il trend non
    aggiunge nulla.
  - **C, contesto di mercato da QQQ**: «Evidenza insufficiente». Ci sono 4 episodi ribassisti nello sviluppo, ne servono
    5. Il filtro peggiora il rapporto rendimento/rischio di A, B e della regola 4/5.
- **Simulazione.** Esclude i titoli con meno di un anno di storia. Così la regola 4/5 passa da +824% a +430%: il risultato
  della Fase 3 dipende molto dai titoli quotati da poco.
- **Pannello.** In «Qualità dei segnali» compare come sezione «2 · Strategie sperimentali», chiusa per default. Legge solo
  `data/strategie/riepilogo.json` e non calcola nulla.

## Analisi fondamentale per l'investimento (Fase 5A, sperimentale)

In **Opportunità → Investimento**, sotto la classifica della Pagella (che **non cambia**), c'è la card «Analisi fondamentale».
Per ogni società descrive sei aspetti **separati**, senza farne un voto e senza indicazioni di acquisto o vendita:

| Dimensione | Stati | Da cosa |
|---|---|---|
| Qualità | Elevata, Buona, Modesta, Debole | margine operativo, flusso di cassa libero (per tecnologia e software al netto dei compensi in azioni), rendimento del capitale investito, margine in calo |
| Crescita | Forte, Positiva, Modesta, In calo | ricavi dell'ultimo trimestre sullo stesso dell'anno prima, ultimo esercizio, media di 3 esercizi; accelerazione o rallentamento; utili solo su basi positive e non minuscole |
| Solidità | Solida, Adeguata, Da verificare, Fragile | debito netto/EBITDA, copertura degli interessi, anni di liquidità se la cassa è negativa |
| Valutazione | Contenuta, Nella media del gruppo, Impegnativa | posizione tra almeno 5 società comparabili (stessa industria Yahoo o stesso settore ICB e stesso modello) su P/E, P/E atteso, EV/utile operativo, EV/EBITDA, prezzo/ricavi, rendimento del flusso di cassa libero |
| Aspettative | In miglioramento, Stabili, In peggioramento, Revisione non verificabile | variazione in 90 giorni della stima di utile del prossimo anno (lo storico che dà la fonte); il consenso di oggi è mostrato a parte e non cambia lo stato |
| Trend | Favorevole, Misto, Debole | chiusura e media 50 rispetto alla media 200 (regola B2): è il comportamento del prezzo, non una qualità dell'azienda |

Ogni stato può essere «Non valutabile» o «Non confrontabile», e porta i motivi con i valori misurati e la regola.
Il **profilo** (per esempio «Qualità e crescita», «Qualità elevata, valutazione impegnativa», «Fragilità finanziaria da
verificare», «Valutazione apparentemente contenuta, ma con rischi fondamentali», «Dati insufficienti») viene da regole
controllate in un ordine fisso, con i rischi prima: una buona qualità non nasconde mai una solidità fragile. L'ordine
iniziale della tabella (completezza, poi giudizi favorevoli meno critici, pesi uguali) è dichiarato **sperimentale**.

- **Modelli per settore.** Tecnologia e software (cassa al netto dei compensi in azioni), industriali/consumo/altri
  (criteri generici), finanziario (solidità non valutabile con debito ed EBITDA, qualità da margine netto e ROE, P/E e
  prezzo/patrimonio), utility (solidità solo dalla copertura degli interessi). Un indicatore che non si applica è
  «non applicabile», mai stimato.
- **Dati.** `fundamentals.py` scarica da Yahoo bilanci annuali e trimestrali e calendario delle trimestrali, in background
  (all'avvio e ogni 30 minuti solo per i titoli che ne hanno bisogno: ogni 7 giorni, 2 giorni dopo una trimestrale, una
  volta al giorno per 14 giorni se i risultati annunciati non sono ancora nei bilanci). Cache in `cache/fundamentals.json`.
  Aprire la pagina non scarica nulla.
- **Data di fine e data di pubblicazione.** Ogni indicatore mostra il periodo (12 mesi = 4 trimestri consecutivi, esercizio,
  bilancio a una data) e la data in cui i risultati sono stati annunciati, se è nel calendario; altrimenti «non
  verificabile». Periodi che finiscono, sono annunciati o compaiono nella fonte dopo il momento del calcolo non si usano.
- **Valute.** I bilanci in EUR o CNY (ASML, CCEP, FER, PDD) sono convertiti con il cambio del giorno per i multipli; il P/E
  atteso di questi ADR non si calcola. L'«enterprise value» di Yahoo non si usa (è sbagliato per alcuni titoli esteri):
  si ricalcola da capitalizzazione e debito netto.
- **Limiti noti.** L'EBIT di Yahoo contiene voci straordinarie: si usa l'utile operativo. Chi pubblica solo semestrali
  (CCEP, FER) è analizzato sull'ultimo bilancio annuale. Dopo una trimestrale Yahoo può metterci giorni a caricare i
  bilanci: la scheda lo dice («risultati annunciati il … non ancora nei bilanci della fonte»).
- **Scheda del titolo.** Pannello «Analisi investimento»: profilo, sei giudizi, e sezioni chiuse con punti di forza e
  critici, motivi di ogni giudizio, indicatori con periodo e pubblicazione, confronto con i comparabili, dati mancanti e
  limiti, cose da monitorare.
- **Diario.** `investment_diary.py` salva i giudizi di una seduta **solo se il diario delle opportunità l'ha già
  registrata**, in tabelle nuove (`inv_runs`, `inv_observations`) dello stesso file `data/opportunita.sqlite3`, che non si
  possono modificare né cancellare. Nessun backtest dei fondamentali sul passato: i bilanci di oggi non erano noti allora.
- **Indirizzi.** `/api/investment` (una riga per società, modello, copertura, gruppi, date dei dati, stato del diario) e
  `/api/investment/<ticker>` (analisi completa).

```sh
.venv/bin/python investment_engine.py aggiorna [--forza]   # scarica i bilanci che servono (a mano)
.venv/bin/python investment_engine.py copertura            # copertura di ogni indicatore e gruppi di confronto
.venv/bin/python investment_engine.py profili              # quanti titoli per profilo e per stato
.venv/bin/python investment_engine.py mostra NVDA          # analisi completa di un titolo
```

## Valutazione e scenari (Fase 5B, sperimentale)

`investment_valuation.py` (modello `VERSION` «V1») si affianca all'analisi fondamentale della Fase 5A, senza cambiarla:
legge i suoi profili e le sue sei dimensioni, che restano quelle approvate. Risponde a «il prezzo di oggi è ragionevole, e
a quali condizioni?» con **intervalli condizionati alle ipotesi**, mai con un prezzo obiettivo, un'indicazione di acquisto
o vendita o una probabilità.

- **Metodo.** Flusso di cassa scontato per **tutti i finanziatori** (FCFF): utile operativo × (1 − tasse) − reinvestimento
  necessario per crescere (ricavi aggiuntivi ÷ rapporto ricavi/capitale), scontato al **costo medio del capitale** (WACC:
  Treasury USA a 10 anni + beta × premio per il rischio del 4,5%; costo del debito dopo le tasse; pesi di mercato). Dal
  valore dell'impresa al valore delle azioni: + liquidità − debito (leasing compresi) − minoranze − azioni privilegiate,
  diviso le azioni diluite. Mai flussi agli azionisti (FCFE) con il tasso dell'impresa. Tutto in dollari nominali.
- **Orizzonte.** 5 anni di previsione esplicita, poi valore terminale con crescita del 2,5% e reinvestimento = crescita ÷
  rendimento del capitale (crescita e rendimento restano coerenti). I 5 anni **non** sono un prezzo obiettivo a 5 anni.
- **Tre scenari.** Prudente, base e favorevole cambiano insieme crescita iniziale, margine a regime ed efficienza del
  capitale (non un ×0,8 o ×1,2 sul risultato); il tasso di sconto è lo stesso (misura il rischio, non lo scenario) e il
  suo effetto è nella tabella di sensibilità. Nessuna probabilità, nessun «valore atteso».
- **Ipotesi base.** Crescita del primo anno dal consenso degli analisti sui ricavi del prossimo esercizio (solo se gli
  esercizi del consenso coincidono con quelli dei bilanci), altrimenti l'ultima crescita misurata, limitata tra −15% e
  +50%; margine che va dal valore degli ultimi 12 mesi al margine «normale» (mediana di 12 mesi e 3 esercizi); rapporto
  ricavi/capitale = mediana di tre misure (marginale degli ultimi 3 esercizi, di bilancio, società simili).
- **Compensi in azioni.** L'utile operativo GAAP li sottrae già: il modello **non li toglie una seconda volta** e usa le
  azioni diluite di oggi. Il flusso «economico» (cassa libera − compensi in azioni) è mostrato come **misura rettificata
  di questa dashboard**, non come grandezza contabile standard; la diluizione storica è mostrata a parte.
- **Valute e ADR.** Bilanci in EUR o CNY convertiti al cambio del giorno, con fonte e data, lo stesso per tutti gli anni (mai
  usato per ricostruire il passato); il rischio paese non è nel tasso di sconto (per questo un valore sopra il prezzo non
  basta). Azioni del bilancio confrontate con quelle implicite nella capitalizzazione: si usa il numero più alto, un
  rapporto intero viene letto come rapporto ADR, un'incoerenza rende i dati insufficienti.
- **Non valutate** (risultato, non errore): banche, pagamenti e utility («Modello non appropriato»); utile operativo
  negativo, margini negativi o distanti oltre 20 punti in 3 anni, cassa operativa negativa («Non valutabile con
  affidabilità sufficiente»); bilanci obsoleti, debito, cambio, azioni o Treasury mancanti («Dati insufficienti»).
- **Affidabilità.** «Calcolabile con dati adeguati», «Parziale» (dati stimati, in ritardo o in un'altra valuta), «Molto
  sensibile alle ipotesi» (valore terminale oltre l'85%, ±1 punto di WACC oltre il 30%, favorevole oltre 3 volte il
  prudente). Descrivono dati e metodo, **non sono probabilità**.
- **Prezzo.** Posizione rispetto agli scenari (sotto il prudente, tra prudente e base, tra base e favorevole, sopra il
  favorevole), margine di sicurezza ipotetico rispetto a ogni scenario, **calcolo inverso** (la crescita del primo anno e
  il margine a regime che giustificherebbero il prezzo; «non univoco» quando la crescita non crea valore) e **livelli di
  prezzo per una nuova analisi** (il valore base e prudente, solo per valutazioni adeguate o parziali), sempre come
  condizioni e mai come ordini. Un valore sopra il prezzo non basta per il gruppo «Qualità, prezzo da approfondire»: servono
  anche qualità e solidità buone, valutazione non molto sensibile e nessuna criticità (dati in ritardo, valuta estera,
  investimenti fuori norma, crescita oltre il limite).
- **Pagina.** In Opportunità → Investimento la card «Valutazione e scenari» (filtri per gruppo, barra con scenari e
  prezzo, crescita implicita, affidabilità) e nella scheda del titolo la sezione omonima: tre scenari con le ipotesi,
  quando sono plausibili, calcolo inverso, sensibilità, livelli, rischi, condizioni da monitorare, tasso di sconto e
  passaggio al valore delle azioni, dati usati e mancanti. Valori arrotondati (2 cifre significative): niente precisione falsa.
- **Diario.** `valuation_diary.py` salva le valutazioni di una seduta **solo se il diario delle opportunità l'ha già
  registrata**, dopo la chiusura e con i **prezzi di chiusura** di quella seduta, in tabelle nuove (`val_runs`,
  `val_observations`) dello stesso file, che non si possono modificare né cancellare: prezzo, date dei dati, versione,
  parametri, scenari, intervallo, stato, motivi, condizioni da monitorare. Servirà a verificare più avanti se i livelli di
  valutazione sono stati informativi; nessuna ricostruzione del passato.
- **Dati.** Per la Fase 5B `fundamentals.py` scarica anche azioni diluite, ammortamenti, capitale circolante, minoranze e
  privilegiate (`FIELDS` 2, senza cambiare lo `SCHEMA` della 5A) e il rendimento del Treasury a 10 anni (`^TNX`), sempre in
  background. Nella scheda del titolo flusso di cassa libero, ricavi e stime dei ricavi mostrano la valuta dei bilanci
  (prima avevano sempre «$», anche per i conti in CNY o EUR).
- **Indirizzi.** `/api/valuation` (una riga per società, parametri, stato del diario) e `/api/valuation/<ticker>`.
- **Primo risultato (4 novembre 2026).** 69 società valutate su 101 (26 adeguate, 19 parziali, 24 molto sensibili), 32
  senza stima. Con questi parametri 51 delle 69 hanno un prezzo sopra anche lo scenario favorevole e la crescita implicita
  mediana è del 42% il primo anno contro il 10% delle ipotesi base: il mercato usa tassi più bassi o si aspetta crescite più
  lunghe di quelle del modello. È una lettura delle aspettative, non un segnale.

```sh
.venv/bin/python investment_valuation.py riepilogo      # stati, gruppi e posizione del prezzo
.venv/bin/python investment_valuation.py mostra MSFT    # valutazione completa di un titolo
.venv/bin/python investment_valuation.py parametri      # ogni parametro con la spiegazione
.venv/bin/python investment_valuation.py confronta      # modello V1 (congelato) e V2 sugli stessi dati
```

### Verifica del motore di valutazione (Fase 5C) e modello V2

Audit del 4 novembre 2026. Le formule (FCFF, WACC, valore terminale, passaggio alle azioni) sono state ricalcolate con un
DCF scritto da zero: stessi valori in tutti i 207 scenari, WACC identico, e per ADBE, MSFT, NVDA, AMZN e PDD i ricavi e
l'utile operativo dei bilanci coincidono con i comunicati delle società. Il WACC è davvero un costo medio del capitale
(capitale proprio + debito dopo le tasse, pesi di mercato), non il solo costo del capitale proprio.

Errori trovati e corretti nel **modello V2** (`investment_valuation.py`); il **V1** resta identico in
`investment_valuation_v1.py` per riprodurre e confrontare i risultati:

- **data di sconto**: gli anni previsti partono dalla fine dei dati di base e sono scontati fino a oggi (V1 li scontava
  un anno intero da oggi anche quando i dati erano di 10 mesi prima);
- **periodi incompleti**: Yahoo a volte pubblica un trimestre o un esercizio con solo utile per azione e numero di azioni;
  V1 tornava all'ultimo bilancio annuale (o non valutava, SBUX), V2 usa gli ultimi periodi completi e prende debito e
  liquidità alla stessa data dei flussi (mai un dato di oltre 100 giorni prima);
- **investimenti finanziari a lungo termine** (riga Yahoo «Investments And Advances") aggiunti al valore delle azioni:
  i loro proventi non sono nell'utile operativo;
- **sensibilità** al tasso di sconto con il rendimento a regime ricalcolato, come prevede il modello.

Solo trasparenza (valori invariati): limiti attivi (beta, aliquota, crescita) con il valore senza il limite; leasing e
investimenti quando pesano più del 10%; flusso di cassa storico all'impresa calcolato in due modi; struttura alternativa
a 10 anni (mai usata nei valori); più combinazioni di crescita, margine e tasso che giustificano lo stesso prezzo. Nuove
etichette: «Calcolo verificato, ipotesi esplicite» (dati adeguati / con limitazioni), «Molto sensibile alle ipotesi»,
«Dati obsoleti o insufficienti», «Metodologia non appropriata», «Valutazione sospesa per anomalie», con l'avvertenza che
la capacità predittiva non è dimostrata. Parametri e ipotesi economiche **non** sono cambiati. `fundamentals.py` scarica
anche leasing e investimenti a lungo termine (`FIELDS` 3).

Perché la maggior parte dei prezzi è sopra lo scenario favorevole: non per un errore di calcolo. Con crescita e margini
dello scenario base il prezzo corrisponde in mediana a un tasso di sconto del 6,7% (modello 9,3%); oppure a una crescita
che dura più dei 5 anni del modello (con 10 anni il valore base sale in mediana del 13%, per NVDA del 113%). Il modello
non dice quale delle due letture sia giusta. Limiti noti non corretti: leasing operativi non separabili, beta di Yahoo
poco affidabile per alcune società (PDD negativo), rischio paese assente dal tasso, partecipazioni non riportate dalla
fonte (per AMZN), stesso difetto dei periodi incompleti negli indicatori della Fase 5A (non modificata).

## Catalogo ETF UCITS e confronto (Fase 6A)

Nella scheda **ETF** c'è ora un secondo modo, **«Catalogo UCITS e confronto»**, accanto a «Mercato ETF» (la tabella di
sempre, che non cambia). Serve a **identificare** bene ogni ETF e a **confrontare** ETF simili con dati verificabili:
nessun segnale Compra/Vendi, nessun punteggio, nessun «vincitore». In Opportunità il modo **ETF** non ha classifiche:
porta solo al catalogo e ad alcuni confronti di esempio.

Aggiornamento **a mano** (mai programmato):

```sh
.venv/bin/python etf_catalog_build.py              # aggiornamento completo (~7 minuti: pagine di Borsa Italiana con pausa di 2 s)
.venv/bin/python etf_catalog_build.py --offline    # ricostruisce solo da quanto già salvato, senza rete
.venv/bin/python etf_catalog_build.py --book       # rilegge anche il book (da usare a mercato aperto: lo spread a mercato chiuso non vale)
.venv/bin/python etf_catalog.py riepilogo          # cosa contiene e quanto è completo
```

Regole:
- **L'ISIN identifica la classe**: una riga per ISIN, anche con più ticker, borse o valute di negoziazione (SWDA a
  Milano ed EUNL a Xetra sono la stessa riga). Le classi dello stesso fondo sono collegate (`fundKey`), mai fuse.
- **Valuta di negoziazione ≠ esposizione**: un ETF sull'S&P 500 comprato in euro resta esposto al dollaro, a meno che la
  classe sia coperta (hedged). L'esposizione valutaria è una stima dai paesi e lo dice.
- Ogni dato ha **fonte e data** (`{"v", "src", "asOf"}`); un dato mancante resta «n.d.», mai zero. Quando più fonti
  danno lo stesso dato lo stato è *verificato*, con una sola *fonte unica*, se non coincidono *discordante* (con tutti i
  valori visibili e l'elenco in `etf_catalog/controlli.json`).
- Fonti, in ordine: l'**emittente** (elenco prodotti iShares; composizioni già scaricate da `etf_holdings.py`), la
  **borsa** (schede ETF di Borsa Italiana: tipo, ticker, MIC, TER, emittente legale, benchmark, proventi, date di KID e
  prospetto, book ritardato di 15 minuti), la **copia di justETF** già salvata l'8 ottobre 2026 in `etf_universe.json`
  (mai riscaricata), **Yahoo** per valuta e volumi medi di ogni quotazione. Una richiesta alla volta, stop al primo rifiuto.
- **Tracking difference e tracking error**: nella Fase 6A non verificabili; dalla Fase 6B la tracking difference c'è per
  gli ETF iShares (vedi sotto); il tracking error resta «n.d.». **Disponibilità presso il broker (Fineco)**: non verificata. **Spread**: solo da un book reale e a mercato aperto.
- ETC, ETN, leva, inversi e non UCITS stanno **a parte** (oggi: gli ETC su oro e argento); restano nella scheda Mercato.
- Obbligazionari con un modello loro (tipo, duration, rendimento a scadenza al peggio, credito, valuta): il rendimento
  a scadenza non è una previsione.
- Cinque classi sono state **aggiunte nella Fase 6A** (IWLE, NQSE, IUSA, IEAA, SEGA: trovate nell'elenco ufficiale
  iShares) per mostrare classe coperta / distribuzione / fondo diverso sullo stesso indice. **Approvate il 4 novembre
  2026** (Fase 6B) dopo il controllo automatico sulla pagina iShares di ISIN, classe, indice, proventi e quotazioni.
  Non sono nella scheda Mercato e `etf_universe.json` non è cambiato.

**Livelli di comparabilità** (`etf_comparison.py`): **1** stesso indice e stessa copertura; **2** esposizione molto
simile (indice diverso sullo stesso mercato, o stesso indice con e senza copertura del cambio); **3** stessa categoria,
indice diverso; **4** non comparabili direttamente (es. azioni e obbligazioni). Il confronto mostra le dimensioni
separate (identità, indice ed esposizione, valuta, costi, struttura, dimensione e liquidità, rischi, date dei dati) e,
per i livelli 1–2, «cosa cambia tra loro» senza dire quale sia meglio. I titoli in comune si mostrano solo sui primi 10
con data, e solo come elenco: con i primi 10 non si può calcolare una sovrapposizione complessiva.

Catalogo al 4 novembre 2026 (dopo la Fase 6B): 66 ETF UCITS + 2 esclusi, 120 quotazioni (Borsa Italiana e Xetra; IWLE e
NQSE ora con Xetra). Dati mancanti noti: duration e rendimento per gli obbligazionari non iShares (X13E, BTP10, XEON),
tracking difference per gli ETF non iShares, TER di EQQQ (fonti discordanti, documento Invesco non letto); per i file
Xtrackers senza data si usa la data del download.

## Scanner delle esposizioni ETF (Fase 6B)

In **Opportunità → ETF** il catalogo diventa uno scanner **esplorativo** che parte dalle **esposizioni** (mercato
mondiale, USA, Europa, emergenti, settori, temi, governativi, societari, altre) e solo dopo guarda i prodotti. Nessun
Compra/Vendi, nessuna probabilità, nessun punteggio unico: le dimensioni (andamento, rischio, prodotto) restano separate.
Le condizioni **non sono validate** (il momentum sulle categorie di ETF non ha superato il test della Fase 24; le
strategie Trading delle Fasi 3–4B non hanno mostrato vantaggi).

```sh
.venv/bin/python etf_prices.py aggiorna           # scarica le chiusure degli ETF (di solito lo fa il server dopo le 18:00)
.venv/bin/python etf_prices.py stato              # cosa c'è in cache/etf_prices.pkl
.venv/bin/python etf_opportunity.py lungo         # lo scanner da Terminale (oppure `breve`)
.venv/bin/python etf_opportunity_diary.py         # stato del diario dello scanner ETF
```

- **Prezzi** (`etf_prices.py`): una serie per ISIN (Borsa Italiana se ha almeno 2 anni, altrimenti la quotazione più
  lunga, es. Xetra per India e Brasile), chiusure rettificate per dividendi, convertite in euro con il cambio dello
  stesso giorno, niente prima del lancio della classe; una classe a distribuzione senza dividendi registrati è segnata
  «solo prezzo». Prezzi dei fondi veri, mai degli ETF americani usati come fonte nella scheda Mercato. Scaricati solo in
  background dopo la chiusura; la pagina legge solo la cache.
- **Benchmark coerenti** (classi ad accumulo in euro): mondo VWCE; settori e temi mondiali SWDA; settori USA CSSPX;
  Europa SMEA; emergenti EIMI. Mai QQQ per tutto. La «classe di riferimento» dell'esposizione serve solo a misurare
  (serie più lunga, non coperta, con dividendi): non è una preferenza.
- **Due modi**: *Medio-lungo* (3–24 mesi: trend 50/200, forza relativa a 6 e 12 mesi, sua evoluzione in 21 sedute,
  volatilità 3/12 mesi, calo dal massimo a 12 mesi, condizioni L1–L4 e M1–M4) e *Breve* (3–30 sedute: medie 20/50, forza
  relativa a 1 e 3 mesi, evoluzione in 5 sedute, condizioni S1–S4 e K1–K4). Il breve periodo è solo esplorativo.
- **Obbligazioni** con un modello separato, mai momentum: quota con rating A o superiore (O2), peso del TER sul
  rendimento (O3), duration ≥ 10 anni (P1), un solo emittente (P2); nel modello E1 anche rendimento ÷ duration ≥ 1 (O1),
  tolta nel modello E2 (vedi sotto). Rendimento a scadenza, cedola
  e rendimento da distribuzione restano tre numeri diversi; il rendimento a scadenza non è un rendimento netto garantito.
- **Stati**: Esposizione da approfondire, Trend favorevole da monitorare, Condizioni contrastanti, Rischio elevato,
  Dati insufficienti, Nessuna opportunità convincente (più «Riferimento di mercato» per mondo e liquidità). Una
  condizione non valutabile non conta mai come soddisfatta. Rischio a parte (R1–R6: volatilità, concentrazione, calo,
  settore/tema, paese singolo, cambio). Prodotti con una lista di controlli (Q1–Q6: TER dell'emittente, patrimonio,
  tracking difference, scambi, spread a mercato aperto, anni di prezzi): nessun vincitore, indici diversi mai confrontati
  come uguali. Soglie in cima a `etf_opportunity.py` (modello attuale `E2`, `E1` riproducibile): cambiarle = nuova versione.
- **Dati del catalogo completati** (`etf_catalog_build.py` + `etf_catalog_verifiche.json`): pagine prodotto iShares (dati
  con la loro data, classe, quotazioni, rendimenti annui di fondo e indice, rating e scadenze); **tracking difference**
  = rendimento annuo del fondo − indice nella stessa valuta, solo anni interi dopo il lancio, bloccata se valute diverse
  o classe coperta contro indice non coperto; **TER** con priorità all'emittente e verifiche a mano su documenti
  dell'emittente (VWCE 0,14% OCF, IMIE 0,17%, VFEA 0,17%, XEON 0,10% all-in fee); se le fonti non coincidono e manca
  l'emittente il TER resta **non risolto** (mai il più basso: oggi EQQQ). Spread: solo letto a mercato aperto e da meno
  di 24 ore, altrimenti «non rappresentativo» o «datato».
- **Diario** (`etf_opportunity_diary.py`): tabelle nuove `etf_runs` e `etf_observations` in `data/opportunita.sqlite3`
  (le tabelle esistenti non cambiano), una volta per seduta di Borsa Italiana e versione, entrambi i modi, tutte le
  esposizioni, solo con prezzi scaricati dopo le 18:00, mai a posteriori, mai modificate (trigger). Salvato dal ciclo del
  server e dal job serale, mai all'apertura della pagina; nessuno scheduler nuovo.

## Sicurezza dei diari e ambienti separati (Fase 6C)

Il 4 novembre 2026 uno script di prova lanciato a mano nella cartella del progetto ha importato `server.py` e chiamato
`save_etf_scan_diary(source="prova")`: 110 osservazioni (55 esposizioni × 2 modi, cioè una seduta completa del modello
E1) sono finite nel diario reale. Non sono state cancellate né modificate. Da qui la Fase 6C (`app_env.py`):

- **Tre ambienti**: `produzione` (predefinito), `test` (sempre, se pytest è caricato, qualunque cosa dica `NDX_ENV`),
  `anteprima` (`NDX_ENV=anteprima`; un valore sbagliato vale come anteprima, mai come produzione).
- **Produzione**: i diari SQLite si scrivono solo da un processo autorizzato — il server avviato con `server.py`, il job
  serale, il comando `opportunity_diary.py update` — e solo con origine `dashboard`, `job serale` o `comando manuale`.
  Uno script o una console che importa `server.py` può leggere ma non registrare (errore «non autorizzata»).
- **Test e anteprima**: una guardia (audit hook di Python) blocca *prima* che avvenga ogni scrittura nella cartella del
  progetto (file, cartelle, rinomine, cancellazioni, SQLite non in sola lettura); nei test anche la rete non locale.
  Portafoglio, diari, report e cache vanno in cartelle temporanee (`app_env.isolate`, una sola lista per test e
  anteprima; ora copre anche `portafoglio/ticker.json` e `classificazione.json`, prima rimasti sul percorso reale).
- **Letture sempre in sola lettura** (`mode=ro`): aprire la pagina o un indirizzo API non scrive mai nei diari.
- **Registrazioni atomiche e idempotenti**: controllo e inserimento nella stessa transazione `BEGIN IMMEDIATE`; se server
  e job serale registrano insieme la stessa seduta, il secondo trova il primo e non scrive; un errore annulla tutta la
  giornata.
- **Prove escluse**: l'origine salvata decide (`app_env.classify`): `prova`/`test` → prova, `anteprima` → anteprima,
  altre → esclusa. Restano consultabili ma non entrano in statistiche, risultati maturati, dataset e «rilevazione
  precedente». La seduta ETF del 4 novembre resta occupata dalla prova (nessuna seconda registrazione): il diario ETF
  ufficiale parte dalla prima seduta successiva.
- **Stato dei diari** (sola lettura): `.venv/bin/python diaries_status.py` (o `--json`, e `/api/diaries/status`): cinque
  diari (opportunità, analisi fondamentale, valutazioni, ETF, decisioni) con ultima seduta ufficiale, osservazioni
  ufficiali ed escluse, versioni presenti e anomalie; in pagina
  una tabella nel pannello chiuso «Monitoraggio risultati».
- **Anteprima**: `.venv/bin/python preview.py` (porta 8101): portafoglio vuoto, copia dei diari in sola lettura (o
  `--vuoto`), nessun download, guardia attiva.
- **Orari ETF**: ogni serie salva borsa, fuso orario, ora di chiusura, ora del download e data del prezzo; l'ultima barra
  si scarta se scaricata prima della chiusura della sua borsa + 30 minuti (18:00 vale per Milano e Xetra, non per una
  borsa americana). Benchmark a data diversa e serie ferme sono segnalati; per gli obbligazionari le date di duration e
  rendimento restano separate da quella del prezzo. La condizione O1 (rendimento ÷ duration ≥ 1) era stata dichiarata
  **euristica sperimentale**; il 5 novembre 2026 l'utente ha deciso di toglierla (modello E2, sezione sotto).
- **Telefono**: sotto i 760 px la riga delle schede scorre di lato al suo interno (la pagina non sborda più: prima 21 px
  a 390 px e 91 px a 320 px), stesse schede nello stesso ordine, scheda attiva sempre visibile.

## Modello ETF E2: obbligazioni senza la soglia O1 (5 novembre 2026)

Decisione dell'utente: la soglia 1 di «rendimento a scadenza ÷ duration» non ha una giustificazione finanziaria
abbastanza solida e non decide più se un'esposizione obbligazionaria è interessante.

- **Due versioni nel codice**: `etf_opportunity.scan(..., version="E1")` riproduce esattamente il modello del 4 novembre
  (stessi stati, stesse soglie, stesso risultato carattere per carattere sui dati reali); `E2` è quella attuale
  (`VERSION`). Il diario salva la versione di ogni registrazione; le righe E1 già salvate non cambiano.
- **Cosa cambia in E2 (solo obbligazioni)**: O1 non è più una condizione. Restano O2 (rating), O3 (costi), P1 (duration ≥
  10 anni), P2 (un solo emittente), con le stesse soglie. O2 e O3 descrivono la qualità del prodotto, non un'opportunità:
  senza condizioni contrarie lo stato è **«Da approfondire — evidenza insufficiente per un giudizio favorevole»**, mai
  «Esposizione da approfondire» (nessuna promozione automatica, nessuna soglia nuova). Le obbligazioni non entrano più
  nella selezione «Opportunità da approfondire».
- **Mostrati a parte, senza soglie**: rendimento a scadenza, duration (modificata se l'emittente la pubblica, altrimenti
  effettiva, dichiarato: oggi sempre effettiva), credito e rating, valuta e copertura del cambio, rapporto rendimento ÷
  duration (solo descrittivo) e **sensibilità indicativa**: rendimenti di mercato +1 punto → prezzo circa −duration %,
  −1 punto → circa +duration %. È un'approssimazione lineare (ignora la convessità, vale per spostamenti piccoli e uguali
  su tutte le scadenze; per gli indicizzati all'inflazione riguarda i rendimenti reali), non una previsione, e non si somma
  al rendimento a scadenza per fare un «rendimento certo».
- **Effetto sui dati del 4 novembre** (entrambi i modi): Stato euro 1-3 anni da «Esposizione da approfondire» (era
  favorevole solo grazie a O1: 1,79) a «evidenza insufficiente»; Stato euro legati all'inflazione, tutte le scadenze,
  Obbligazioni societarie euro e Aggregato globale da «Condizioni contrastanti» (solo per O1) a «evidenza insufficiente»;
  Stato euro 15-30 anni resta «Rischio elevato» (P1), BTP 10 anni resta «Dati insufficienti». Azioni invariate; nel modo
  lungo la selezione passa da 6 a 5 esposizioni (esce Stato euro 1-3), nel breve non cambia.
- **Diario**: una seduta si registra una volta sola, con una sola versione. Una seduta già registrata con E1 (anche la
  prova del 4 novembre, che resta esclusa) non si registra di nuovo con E2: E2 vale dalla seduta successiva (controllo
  in `etf_opportunity_diary.record`, nella stessa transazione, e in `server.save_etf_scan_diary`).
- Test in `tests/test_etf_model_e2.py`; i quattro test della 6B/6C che descrivono O1 ora chiedono esplicitamente `E1`.

## Decision Desk (Fase 7A)

Prima modalità della scheda Opportunità (le modalità Trading, Investimento ed ETF restano). `investment_decision_engine.py`
(versione **D2**, funzioni pure; la D1 resta riproducibile con `decide(snap, "D1")`) **legge** i risultati dei motori esistenti — condizioni T1–T5 e Pagella
(`opportunity_scanner`), analisi fondamentale F1, DCF V2, scanner ETF E2 — e non ne ricalcola né sostituisce nessuno. Per
ogni azione e ogni esposizione ETF, per ciascun orizzonte, dà uno **stato** scelto da regole esplicite (mostrate in
pagina con il loro codice), mai da una somma di punteggi:

- **Stati**: Da approfondire · Attendi condizioni migliori · Monitora · Monitora — trend esplorativo (solo D2) · Condizioni contrastanti · Rischio elevato · Dati
  insufficienti · Nessuna opportunità convincente. Nessun punteggio complessivo, nessuna probabilità, nessun rendimento
  atteso, nessuna indicazione di acquisto o vendita, nessun prezzo di ingresso. Se nulla convince lo dice.
- **Azioni, medio-lungo periodo** (regole A-…): «Da approfondire» solo con qualità, crescita e solidità favorevoli, stime
  non in peggioramento, trend non debole, DCF V2 calcolato con il prezzo non sopra lo scenario base **e nessuna evidenza
  contraria** (dati in ritardo, prezzi di sedute diverse, stime non aggiornate, bilanci in valuta estera = rischio paese
  fuori dal modello, criticità o forte sensibilità della valutazione). Qualità con prezzo sopra lo scenario base o
  valutazione «Impegnativa» = «Attendi condizioni migliori». Solidità «Fragile» o qualità debole con ricavi in calo =
  «Rischio elevato» anche se la valutazione sembra contenuta. La Pagella è mostrata ma non decide.
- **Azioni, breve periodo** (B-…): solo descrizione; massimo «Monitora» (le regole T1–T5 non hanno mostrato vantaggi nelle
  Fasi O3–4B). Volatilità alta su un candidato = «Rischio elevato»; avvisi (tirato, trimestrale vicina, sotto la media 200)
  = «Condizioni contrastanti».
- **ETF, medio-lungo** (E-…): parte dallo stato E2. In **D2** un ETF non arriva mai a «Da approfondire» solo perché
  soddisfa le condizioni di trend E2 (esplorative, non validate come criterio predittivo): «Esposizione da approfondire»
  con almeno un ETF documentato (TER noto e non discordante, patrimonio e scambi sopra le soglie del catalogo), date
  allineate e dati del fondo non datati diventa **«Monitora — trend esplorativo»** (regola E-M3, con le stesse evidenze,
  rischi, date e spiegazione; non è un giudizio negativo). In D1 quei casi erano «Da approfondire» (E-A1). Senza ETF
  documentato «Condizioni contrastanti» (E-C2), con date non allineate «Monitora» (E-M2): uguali in D1 e D2. Uno stato più
  favorevole per un ETF richiederà evidenze ulteriori, criteri documentati e una decisione esplicita, non più condizioni di
  trend soddisfatte. Il giudizio sull'esposizione resta separato
  dalla qualità dei prodotti (mostrata a parte, con TER da fonte di borsa, spread non aggiornati e dati del fondo datati
  secondo le regole del catalogo). **Obbligazioni E2 «Da approfondire — evidenza insufficiente» → «Nessuna opportunità
  convincente»** (regola E-N2): O2 e O3 sono caratteristiche del prodotto, non della convenienza; mai promosse; il rapporto
  rendimento ÷ duration e la vecchia O1 non decidono nulla.
- **ETF, breve** (F-…): solo azionari, massimo «Monitora» (momentum sulle categorie bocciato nella Fase 24); per le
  obbligazioni nessun segnale di breve periodo (elencate tra i «non analizzati»).
- **Ordine dichiarato**: stato, completezza dei dati, rischi bloccanti, evidenze contrarie, evidenze favorevoli, nome. Mai i
  rendimenti recenti o lo sconto teorico del DCF.
- **Date**: ogni riga mostra le date dei dati determinanti; un dato successivo al momento dell'analisi rende la riga
  «Dati insufficienti»; date non allineate riducono il giudizio.
- **Condizioni di cambiamento**: «migliora se», «peggiora se», «da verificare», prese dai motori (livelli DCF come soglie
  per una nuova analisi, prossime trimestrali, invalidatori E2) e dalle regole (una dimensione che cambia stato).
- **Indirizzi** (sola lettura, nessun download): `/api/decisions` (righe compatte) e `/api/decisions/<id>` (scheda). Cache
  di 10 minuti come le classifiche; primo calcolo circa 1 secondo, poi pochi millisecondi.
- **Diario delle decisioni** (`decision_diary.py`): tabelle nuove `dec_runs`/`dec_observations` in
  `data/opportunita.sqlite3`, scritte da `server.save_decision_diary` nella stessa catena serale degli altri diari (nessuno
  scheduler nuovo), una volta per seduta NYSE e versione, solo dopo che il diario delle opportunità ha registrato quella
  seduta e dopo la chiusura; righe ETF solo se lo scanner ETF usa la stessa seduta con prezzi definitivi (altrimenti la
  nota lo dice). Protezioni della Fase 6C (`app_env`), `BEGIN IMMEDIATE`, trigger anti-modifica, letture in sola lettura.
- **Versioni**: D1 (Fase 7A) e D2 (5 nov 2026). Dati del 4 novembre: D2 cambia solo le 5 esposizioni ETF che D1 dava «Da
  approfondire» (dividendi, qualità, finanza mondo, sanità mondo, USA equal weight) → «Monitora — trend esplorativo»; azioni
  (ADBE resta «Da approfondire»), breve periodo, obbligazioni E2, rischi, contraddizioni e dati insufficienti invariati.
  Il diario salva la versione per ogni seduta e osservazione; una seduta già registrata con una versione non si registra
  con un'altra (la nuova parte dalla seduta successiva); i giudizi passati non si ricostruiscono.
- **Copertura ETF** (`coverage` nell'API, «Copertura ETF» in pagina): per orizzonte esposizioni dello scanner =
  classificate + riferimenti di mercato + non analizzabili (obbligazioni nel breve). Il 4 novembre: medio-lungo 55 = 53 + 2
  (mondo, monetario); breve 55 = 46 + 2 + 7 obbligazionari. Il catalogo ha 66 ETF nelle esposizioni; fuori dal catalogo
  ordinario 2 ETC (oro, argento: non fondi UCITS).
- Nessun dato del portafoglio (compatibilità con il portafoglio: Fase 7B). Test in `tests/test_decision_engine.py` e
  `tests/test_decision_d2.py`.

## Compatibilità con il portafoglio (Fase 7B)

Portafoglio → **Compatibilità** (e un riepilogo nella scheda di ogni riga del Decision Desk). `portfolio_fit.py` (modello
**P1**, funzioni pure: nessun file letto, nessun download, nessuna scrittura) descrive come un'azione o un ETF cambierebbe la
composizione di un portafoglio. È un giudizio **separato** dal Decision Desk: lo stato D2 resta quello che è (una riga «Da
approfondire» può essere poco compatibile; una riga poco interessante non diventa interessante perché diversifica).
Nessun punteggio unico, nessuna indicazione di acquisto o vendita, nessun ordine, nessuna probabilità, nessun VaR.

- **Attivazione esplicita**: aprire il Decision Desk o la pagina Compatibilità non legge il portafoglio. Solo i pulsanti
  «Analizza compatibilità con il mio portafoglio» o «Usa un portafoglio di esempio» chiamano `POST /api/portfolio/fit` con
  `consent: true`, dalla pagina della dashboard su questo Mac (`local_request`; GET = 405, senza consenso = 400). «Mio» usa
  la fotografia che `portfolio.py` tiene già in memoria per la scheda Portafoglio (nessuna nuova lettura dell'export,
  nessuna copia, niente nei diari, risposta `Cache-Control: no-store`, nei log solo il tipo di errore). «Esempio» è un
  portafoglio inventato su strumenti pubblici (`portfolio_fit.demo_book`). Nei test e nell'anteprima la cartella
  `portafoglio/` è una cartella temporanea vuota: «mio» risponde «nessun export», «esempio» funziona.
- **Normalizzazione**: azioni, ETF UCITS (ISIN del catalogo), ETC/ETN, liquidità, strumenti non identificati (mai una
  corrispondenza inventata). Le quotazioni dello stesso ISIN diventano un solo strumento; un ETF senza ISIN si riconosce
  dal ticker del catalogo; società con più titoli o ADR si uniscono per nome normalizzato (`etf_holdings.company_key`).
  Valute: mai sommate senza un cambio dichiarato (tasso, data, fonte); senza cambio il valore resta fuori dai totali con il
  motivo; prezzo o cambio con più di 5 giorni = valore «indicativo».
- **Composizione**: classe, settore, paese delle società, valuta **economica** (dai paesi dei titoli, stima; o copertura
  dichiarata), con la qualità del dato (osservato, stima, non disponibile). La valuta di negoziazione di un ETF non è la sua
  esposizione. «Non classificato» e «altri (non dettagliati)» restano visibili: nessun 100% costruito ripartendo i mancanti.
  Settori di azioni (ICB/Yahoo) ed ETF (justETF) confrontati in modo indicativo.
- **Sovrapposizioni (look-through)**: il valore di un ETF è ripartito tra i titoli noti (primi 10 del catalogo, con la
  data), mai sommato una seconda volta; la parte oltre i titoli noti resta «non analizzabile» (mai zero). Esposizione a una
  società = diretta + dentro gli ETF, «limite inferiore» quando i titoli sono solo i primi 10. Sovrapposizione nota tra due
  ETF = somma dei pesi minimi dei titoli in comune. Controllo: analizzato + oltre i titoli noti + senza dati + non
  azionario = 100%.
- **Concentrazione**: pesi, prime 5 e 10, numero equivalente di posizioni (1 ÷ Σ pesi²), società, settori, paesi, valuta
  principale, gestori dei fondi. Nessuna soglia: «oltre il limite» solo contro limiti personali impostati nella pagina
  (non salvati); senza limiti «non configurato».
- **Rischio**: volatilità, massima perdita e correlazioni settimanali con i pesi di oggi, solo con almeno 126 sedute in euro
  allineate (altrimenti «Non calcolabile con affidabilità sufficiente»); serie solo da memoria o cache (ETF:
  `cache/etf_prices.pkl`; azioni: solo se la pagina Rischio ha già caricato oggi il cambio EUR/USD giornaliero). Duration
  solo sulla parte obbligazionaria con dato. Ipotesi deterministiche (azioni −10% e −20%, tassi +1 punto, dollaro −10%):
  non previsioni.
- **Compatibilità di un candidato** (descrizioni verificabili con codice): C-P1 già presente direttamente, C-P2 esposizione
  equivalente, C-I1 esposizione indiretta già presente, C-O1 sovrapposizione con le società detenute, C-S1/C-G1/C-V1/C-A1
  aumento della concentrazione (la voce più pesante pesa di più nel candidato), C-N1/C-N2/C-N3/C-N4 nuova esposizione,
  C-D1 dati insufficienti.
- **Simulatore**: importo, valuta (convertita solo con cambio noto), finanziamento con nuova liquidità, liquidità già
  presente (solo se nota e sufficiente) o riduzione di una posizione scelta; prima e dopo, differenze, rischi aggiuntivi,
  limiti personali, dati mancanti. Non è un ordine, non modifica nulla, non viene salvato.
- Test in `tests/test_portfolio_fit.py` (portafogli, catalogo e prezzi inventati).

## Messa in esercizio e affidabilità dei diari (Fase 7C)

Nessun nuovo modello: solo controlli e correzioni per l'uso quotidiano.

- **Finestra di registrazione**: una seduta NYSE si registra (opportunità, analisi fondamentale, valutazioni, decisioni)
  solo dalla chiusura + 20 minuti fino alle 04:00 di New York della seduta successiva (`diaries_status.recordable_until`).
  Prima della 7C, tra le 16:00 e le 16:20 del giorno dopo la seduta precedente risultava ancora «ultima chiusa» e la catena
  poteva registrarla in ritardo: così il 5 novembre 2026 alle 16:00 ET il diario delle decisioni ha registrato il 4 novembre
  con i bilanci del 5. Ora `server.save_opportunity_diary` rifiuta ogni seduta fuori finestra («nessuna registrazione
  retroattiva»). Le registrazioni tardive già presenti (opportunità 3 nov, decisioni 4 nov) **restano nel file come sono**:
  `diaries_status.py` le segnala con una nota («registrata in ritardo»), senza cambiarle né toglierle.
- **Job serale senza dashboard** (`daily_job.py`): aggiorna anche i bilanci (stesse regole della dashboard) e scarica i prezzi
  ETF **prima** della catena dei diari, così le decisioni della sera hanno anche le righe ETF. I file di cache sono scritti
  in modo atomico con un file temporaneo per processo (server e job insieme non si leggono mai un file a metà).
- **Installazione** (solo su tua richiesta, mai da Claude): `./schedule.sh install` installa due LaunchAgent dell'utente
  (`com.nasdaq100.signals` lun–ven 08:30, `com.nasdaq100.daily` lun–ven 22:45 ora del Mac). Verifica:
  `./schedule.sh status` e `.venv/bin/python diaries_status.py`; log in `reports/logs/`. Rimozione: `./schedule.sh remove`.
  Mac in stop alle 22:45: macOS esegue il job al risveglio (se è dopo le 04:00 di New York del giorno dopo, la seduta è persa
  e non viene ricostruita); Mac spento: quella sera salta.
- **Sicurezza della dashboard**: ogni risposta solo a richieste indirizzate a `localhost` / `127.0.0.1` (contro il «DNS
  rebinding», anche per le pagine GET come `/api/portfolio`); le richieste che modificano o leggono dati personali con POST
  (`local_request`) vogliono l'origine esatta della dashboard (stesso host e porta), l'intestazione `X-Requested-With:
  ndx-dashboard` (che obbliga il browser a una verifica CORS mai approvata) e, per il Portfolio Fit, `consent: true`.
- **Rischio parziale**: la scheda Rischio della Compatibilità dice prima dei numeri quale parte è coperta dalle serie
  storiche (% del portafoglio e della parte investita), quale no, la liquidità esclusa e le posizioni senza valore in euro;
  con copertura incompleta il titolo è «Rischio parziale» e le statistiche sono «della sola parte coperta». Formule invariate.
- Test in `tests/test_environment_safety.py`, `tests/test_opportunity_diary.py`, `tests/test_portfolio_fit.py` (sezioni 7C).

## Alert e cambiamenti (Fase 8A)

Scheda **Alert** → «Alert e cambiamenti»: cosa è cambiato dall'ultima osservazione valida dei diari, con soli dati
pubblici di azioni ed ETF. Informativi e verificabili: nessuna previsione, nessun ordine, nessun compra/vendi.

- **Motore** `alert_engine.py` (versione «A1»): legge le registrazioni **ufficiali e ammissibili** dei cinque diari,
  il catalogo ETF e lo stato dei diari; non ricalcola modelli e non scarica nulla. Confronta l'ultima seduta ammissibile
  con la precedente **solo se hanno la stessa versione del modello**; con una sola seduta c'è solo la base di partenza
  (nessun alert di cambiamento); un cambio di versione è un cambiamento metodologico (OP-VERSIONE).
- **Regole** (tutte scritte in `alert_engine.RULES`, visibili nella pagina): azioni — stato D2, nuovi bilanci con
  giudizi cambiati (solo con un periodo nuovo identificabile; giudizi invariati = un solo avviso raggruppato), revisione
  osservabile delle stime, prezzo oltre un valore di scenario DCF (isteresi del 3%; prezzo e ipotesi mostrati come cause
  separate), forte cambio della distanza dal valore base, valutazione non più utilizzabile, nuovo rischio bloccante, dati
  insufficienti; ETF — stato E2 e D2 (i trend solo esplorativi), trend confermato per 2 sedute, rischio E2, concentrazione
  dei primi 10 titoli, costi e struttura del prodotto, duration/rendimento/credito (solo con dati del fondo più recenti),
  dati obsoleti; operativi — sedute non registrate, registrazioni da classificare. Una regola rumorosa si disattiva in
  `alert_rules.json` senza toccare i modelli.
- **Priorità** per tipo di evento (Criticità da verificare / Cambiamento importante / Aggiornamento ordinario), mai per
  probabilità di guadagno. **Antirumore**: identificativi deterministici, deduplicazione, eventi collegati raggruppati,
  problemi persistenti seguiti senza ripetizioni (nuovo → persistente → risolto), isteresi su DCF e trend.
- **Registro** `data/alert.sqlite3` (fuori da Git, separato dai diari): giri identificati dall'impronta degli input
  (lo stesso stato dei dati non crea mai un secondo giro), righe mai modificate né cancellate, stato del ciclo di vita
  in una tabella additiva, versioni del catalogo ETF salvate per i confronti. Scritto solo dal server avviato e dal job
  serale (`server.save_alerts`, dopo i diari e mai su una catena incompleta); `GET /api/alerts` lo legge in sola lettura.
  «Consultato» è un segno del solo browser.
- **Registro delle esclusioni** `diary_exclusions.json` (additivo, in Git): opportunità del 3 nov 2026 e decisioni del
  4 nov 2026 (registrate in ritardo) restano nei diari come sono, ma escono da risultati, statistiche, dataset di
  validazione, confronti e alert. `diaries_status.py` mostra separate le osservazioni registrate e quelle ammissibili.
- **Job serale**: la fotografia del portafoglio (`portafoglio/storico/`) non può più fermare i cinque diari (un errore
  viene registrato col solo tipo); gli alert si generano dopo i diari.
- Test in `tests/test_alerts.py` (diari, catalogo e registro sintetici).

## Riepilogo del giorno e job MARKET-ONLY (Fase 8B)

Scheda **Alert** → «Riepilogo del giorno» (prima sotto-pagina) e job serale che aggiorna **solo i dati pubblici**.

- **Modalità MARKET-ONLY** (`.venv/bin/python daily_job.py --market-only`, stesso codice del job serale:
  `server.run_daily_job(market_only=True)`): prezzi, analisi pubbliche di azioni ed ETF, i cinque diari prospettici
  (opportunità, fondamentali, valutazioni, scanner ETF, decisioni), gli alert e il report pubblico della sera. **Mai**:
  portafoglio, import Fineco, fotografia del giorno, `flussi.json`, diario dei segnali, diario ETF personale, diario
  delle posizioni. La protezione `app_env.enable_market_only()` si accende **prima di ogni import**: da lì ogni
  apertura, elenco, connessione SQLite o modifica di un file in `portafoglio/` viene bloccata prima che avvenga
  (`PrivateAccessBlocked`) e contata (solo il tipo di operazione, mai il nome del file). Gli import dei 48 moduli non
  toccano `portafoglio/` (test). Il job completo (`daily_job.py` senza opzioni) resta com'era.
- **Programmazione** (solo su tua richiesta, mai da Claude), con etichetta separata `com.nasdaq100.market` che non
  installa, sostituisce o rimuove i job personali:
  ```bash
  ./schedule.sh install-market   # job MARKET-ONLY lun–ven alle 23:00 (ora del Mac)
  ./schedule.sh status-market    # installato o no, orari e argomenti letti da launchd, ultimi giri
  ./schedule.sh remove-market    # toglie SOLO il job MARKET-ONLY
  ```
  Le 23:00 italiane sono sempre almeno un'ora dopo la chiusura NYSE (+20 minuti), anche nelle settimane in cui l'ora
  legale USA ed europea non coincidono (chiusura alle 21:00 italiane) e nei giorni a chiusura anticipata (19:00), e
  molto prima della fine della finestra di registrazione (04:00 di New York della seduta successiva = 10:00 italiane,
  09:00 nelle settimane sfasate). Festività NYSE da `market_calendar.py`; Borsa Italiana e Xetra dalla serie di
  riferimento degli ETF (un giorno festivo non ha barra e non è mai «mancante»).
- **Mac spento o in stop**: in stop, macOS esegue il giro saltato al risveglio; se il risveglio arriva entro le 04:00 di
  New York la seduta si registra, dopo è persa per sempre (nessuna registrazione tardiva). Mac spento: il giro salta.
  Nessun recupero promesso: le sedute perse restano tra le mancanti.
- **Registro dei giri** `data/job_status.json` (`job_status.py`): avvio, fine, modalità, esito di ogni passo e tipo
  di errore; un giro iniziato e mai finito è «interrotto». Nessun dato personale; scrittura con lock e file temporaneo.
- **Riepilogo del giorno** (`daily_brief.py`, `GET /api/brief`, sola lettura, senza consenso): ultima seduta elaborata,
  stato dei cinque diari, nuovi alert, al massimo **7** cambiamenti importanti della seduta (mai riempiti con altro),
  ognuno con strumento, cosa è cambiato, prima/dopo, perché, data effettiva dei dati, limiti e link; per il DCF effetto
  del prezzo ed effetto di ipotesi e bilanci separati; trend ETF sempre esplorativi. «Nessun cambiamento rilevante
  rilevato nell'ultima seduta elaborata.» solo con il riepilogo aggiornato; altrimenti «Riepilogo non aggiornato» con il
  motivo. Gli eventi del primo controllo del registro sono **eventi storici rilevati all'attivazione**, a parte. I
  problemi di dati e aggiornamento sono separati dagli eventi finanziari. Nessun punteggio, nessun compra/vendi.
- **Date di un alert** tenute distinte (calcolate in lettura, il registro non cambia): periodo di bilancio, annuncio
  indicato dalla fonte (calendario delle trimestrali di Yahoo, **non verificato**; per gli alert registrati prima della
  8B letto dal diario dei fondamentali), acquisizione da parte del sistema, rilevazione degli alert, sedute confrontate.
  Mai «pubblicata oggi»: senza data di pubblicazione il testo è «Nuovi dati acquisiti».
- **Stato del sistema** (sezione chiusa nel riepilogo): ultimo job completato, ultimo avviato, programmazione, ultima
  seduta, ultimi prezzi, bilanci e prezzi ETF, ultime registrazioni dei diari (registrate e ammissibili), ultimo
  controllo degli alert, errori recenti, sedute mancanti, registrazioni escluse, file aperti dal server. Un giorno è
  completo solo con tutti e cinque i diari.
- Test in `tests/test_market_only.py` (cartelle sentinella, filesystem temporanei, nessuna rete, nessun launchctl).

## Grafica, leggibilità e informazioni di mercato (Fase 8B.1)

Solo interfaccia e informazioni; motori, regole, soglie, diari e job **invariati**.

- **Logo** «NDX Monitor» a colori: piccolo SVG nell'intestazione (tre candele verde/rossa/verde) disegnato con i colori del
  tema, leggibile in chiaro, scuro e sul telefono. Nessuna immagine esterna.
- **Avvertenze**: i grandi riquadri gialli generici in cima a Opportunità, Decision Desk, ETF, opportunità ETF e catalogo
  sono una riga discreta «ⓘ … · Come funziona» (il testo completo si apre a richiesta). Una finestra modale con il testo
  «Screening operativo e non consulenza» non esisteva nel codice. Restano le note specifiche (dati mancanti o datati,
  copertura insufficiente, stop dentro l'oscillazione…). Un ⓘ fissato con un clic si chiude da solo quando cambia pagina,
  quando si scorre o quando il suo elemento sparisce.
- **Mercato → Oggi**: accanto alla mappa il grafico Nasdaq-100 e «Prossimi appuntamenti» (al massimo 6 righe); sotto, a
  tutta larghezza e **senza scorrimento interno**:
  - **Eventi macro USA** (`GET /api/macro?past=N&days=N`, al massimo 31 giorni per lato): periodo a scelta (prossimi 7 / 30,
    ultimi 7 / 30), stato **atteso / pubblicato / rinviato** («rinviato» solo per Fed e PCE, i cui calendari ufficiali sono
    riletti ogni giorno), precedente ed effettivo dai dati ufficiali già scaricati (BLS per CPI e occupazione, pagina della
    Fed per il tasso: «effettivo» solo se la pagina è stata riletta dopo la decisione), **consenso «Non disponibile»** (nessuna
    fonte gratuita affidabile) e quindi differenza «Non calcolabile», cosa muove di solito (azioni, tassi, obbligazioni,
    dollaro), fonte ufficiale con link e data di aggiornamento. PCE: solo la data (i valori richiederebbero una chiave BEA).
  - **Trimestrali** degli ultimi 7 giorni e dei prossimi 7, divise in «Da pubblicare» e «Pubblicate» e raggruppate per
    giorno: prima/dopo la chiusura, conferma della data secondo Yahoo (`isEarningsDateEstimate`: confermata / stimata /
    non indicata), trimestre contabile (dai bilanci se annunciato quel giorno, altrimenti stimato dalla cadenza), utile per
    azione e ricavi attesi ed effettivi con sorpresa, guidance «non disponibile nella fonte», link a Yahoo e al sito della
    società, data dell'annuncio separata dalla data di download. Per una trimestrale pubblicata l'utile atteso è la stima di
    **quella** trimestrale (prima si mostrava per errore la stima del trimestre successivo); i ricavi attesi solo se le stime
    erano state scaricate prima del giorno dell'annuncio.
  - **Chi si è mosso e perché**: ogni scheda ha un'etichetta (`server.move_evidence`, regole fisse, nessuna AI):
    **CAUSA DOCUMENTATA** solo se un articolo scritto per spiegare il movimento indica il motivo (e non è un sito
    d'opinione); **EVENTO CORRELATO** se nella stessa finestra c'è una trimestrale, una notizia o un comunicato sul titolo,
    un movimento del settore o un dato macro, senza che una fonte dica che è la causa; **CAUSA NON VERIFICATA** altrimenti.
    Mostra variazione e seduta, fonte, ora, link e come verificarlo. Poiché `yfinance get_news` può non rispondere per ore
    («Yahoo! Finance is currently down», successo il 6 novembre 2026), **solo per questa scheda** c'è il ripiego sul feed RSS
    pubblico di Yahoo (`server.news_moves`, una richiesta leggera per titolo, cache 10 minuti). Segnali e schede dei titoli
    usano ancora `news()` come prima.
- **Mappe**: mappa del mercato con nomi dei settori interi, abbreviati o omessi (mai tagliati a metà; nome intero nel
  tooltip) ed **elenco dei settori e dei titoli** sotto la mappa (aperto sul telefono); mappe di rotazione con etichette che
  non si sovrappongono mai fra loro, ai punti o ai nomi dei quadranti e non escono dal grafico (altrimenti un numero) ed
  **elenco numerato** con nomi e valori; punti raggiungibili con tastiera e tocco.
- **Portafoglio**: tolto il riquadro automatico sui prodotti a leva (la quota di valore e di esposizione è nell'ⓘ della
  posizione); «ETF non classificati» = strumenti il cui ISIN non è in `portafoglio/classificazione.json` (per ETF ed ETC la
  dashboard non ha una fonte affidabile di settore/tema/paese, è normale per ogni ETF nuovo): una riga «Alcuni strumenti
  non sono stati associati con certezza a una categoria…» con l'elenco di cosa manca (`snapshot()["unclassified"]`), mai
  una classificazione inventata, nessun file modificato. Il riquadro **Zainetto fiscale** non è più nella pagina: file,
  `/api/fiscal` e stima fiscale restano.
- **Compatibilità**: introduzione che spiega cosa misura e cosa no, con un esempio inventato; consenso invariato.
- **Preferiti** (prima «In osservazione»): la stessa `watchlist.json`, stella ★/☆ con stato chiaro; un titolo «Monitora» non
  viene mai aggiunto da solo. Spiegazioni ⓘ di «Monitora» (regole A-M1, B-M1, E-M1, E-M2, F-M1, E-M3), «Trend favorevole da
  monitorare» ed «Esposizioni monitorate», con la differenza dai Preferiti.
- **Trend ETF**: ⓘ completo (medie 50 e 200 delle chiusure in euro, condizioni esatte, cosa non significa, differenza da
  forza relativa, cambio di trend recente e volatilità).
- **Anteprima**: `.venv/bin/python preview.py --portafoglio-finto` mostra un portafoglio **inventato**, solo in memoria;
  eventi macro e trimestrali vengono letti dai file già in `cache/` in sola lettura.
- Test in `tests/test_ui_8b1.py` (27 test, dati sintetici, nessuna rete; controlla anche che i motori siano identici al commit).

## Istanza separata «Portafoglio secondario» (Fase 9A)

Una seconda dashboard completa, con un portafoglio indipendente, per chi la apre da un altro PC tramite Tailscale.
Stesso codice, un secondo processo (`./istanza.sh avvia ~/NasdaqMonitor-istanze/utente2`, porta 8110, solo 127.0.0.1):
legge i dati pubblici della dashboard personale senza mai scriverli e tiene portafoglio, Preferiti, classificazioni,
dati fiscali, storico e diari personali nella sua cartella privata. Non può aprire `portafoglio/` né `watchlist.json`
(blocco nel processo). Accesso con password, sessione e protezione CSRF. Istruzioni complete, configurazione Tailscale
proposta (non attivata), revoca e backup in `docs/istanza_secondaria.md`.

## App portatile per Windows (Fase 9B)

Lo stesso Nasdaq-100 Monitor come programma Windows indipendente dal Mac: si estrae lo ZIP, doppio clic su «Nasdaq-100
Monitor.exe», la dashboard si apre nel browser. Nessun Python da installare, nessun servizio online. I dati personali
stanno in `%LOCALAPPDATA%\Nasdaq100Monitor` (mai nella cartella del programma: una nuova versione non li cancella), i
dati di mercato si scaricano con il pulsante «Aggiorna dati». Il pacchetto si costruisce **su Windows** con
`packaging/build_windows.ps1` (test, PyInstaller, controllo che non ci siano dati personali, prova dell'eseguibile, ZIP con
impronta SHA-256). Dettagli, strade gratuite per la build e limiti in `docs/app_windows.md`; guida per l'utente in
`packaging/LEGGIMI.txt`.

## Da verificare quando il diario avrà almeno 3 mesi di dati

- **"Entra ora"**: togliendo la regola D3 (Fase 21) i titoli con "Entra ora" sono passati da 18 a 33 su 101. Controllare
  nel Diario se "Entra ora" fa meglio di tutti i titoli dello stesso giorno (colonna "extra vs tutti", con casi
  sufficienti); altrimenti le regole del verdetto vanno ripensate.

## Test automatici

```sh
.venv/bin/python -m pip install -r requirements-dev.txt   # una volta sola (pytest)
.venv/bin/python -m pytest -q                             # prima di ogni commit: devono passare tutti
```

I test (`tests/`) usano solo dati finti e una cartella temporanea al posto di `portafoglio/`, mai i dati reali:
verdetto (`decision.py`), azioni sulle posizioni (`actions.py`), stima fiscale con e senza zainetto, rendimento
ponderato per il tempo (`history.py`), quantità da comprare con e senza spread di cambio, tendenze, oscillazione a 5
giorni, supporti e resistenze, punti pivot, "dalla data" del diario e il riquadro Analisi; diario (un giorno salvato non
si riscrive mai, gli esclusi non entrano nelle statistiche, "dalla data" e "almeno dal", sedute mancanti senza weekend e
festività); trimestrali (giorno di reazione prima dell'apertura, dopo la chiusura e a cavallo del fine settimana);
testo del riepilogo del mattino; scheda ETF (scelta dello storico Borsa Italiana → Xetra → ETF americano in euro,
conversione in euro, effetto cambio, percentili del rischio di essere arrivati tardi, terzi del momentum e mesi
consecutivi, sovrapposizione, regole «si sovrappone / diversifica / neutro»).
Analisi fondamentale (`tests/test_investment_engine.py`, Fase 5A): indicatori e unità, valute e ADR, utili negativi,
flusso di cassa mancante, aziende finanziarie, comparabili dello stesso modello e gruppi troppo piccoli, dati vecchi o
in ritardo, data di fine contro data di pubblicazione, niente periodi futuri, consenso contro revisioni, profili, testi
coerenti con i valori, indirizzi `/api/investment`, classifiche e diario esistenti invariati, pagina.
Valutazione e scenari (`tests/test_valuation.py`, Fase 5B): flusso di cassa all'impresa, coerenza con la formula della
perpetuità, flussi e tasso dell'impresa, valore dell'impresa e delle azioni, azioni diluite e rapporto ADR, cambi,
compensi in azioni non contati due volte, scenari che cambiano le ipotesi, sensibilità, ipotesi non ammissibili, cassa e
utili negativi, margini instabili, dati mancanti, obsoleti o in ritardo, aziende finanziarie e utility, margine di
sicurezza e livelli, calcolo inverso, niente periodi futuri, riproducibilità, consenso coerente con i bilanci, Pagella e
Fase 5A solo lette, diario (mai avviato da qui, solo prezzi di chiusura, immutabile, altri diari invariati), indirizzi,
valuta dei bilanci nella scheda e pagina.
Verifica della valutazione (`tests/test_valuation_audit.py`, Fase 5C): DCF confrontato con un'implementazione da manuale
indipendente, casi calcolati a mano (un anno, WACC), crescita con rendimento uguale al costo del capitale, sconto dalla
data dei dati, flusso di cassa storico in due modi e compensi in azioni, tasse, costo del debito, limiti del beta e della
crescita, investimenti e leasing, ADR e diluizione, valute, periodi incompleti e dati vecchi, sensibilità, calcolo inverso
con più combinazioni, orizzonte alternativo, V1 congelato e uguale a V2 quando le correzioni non si applicano, etichette,
diario con due versioni immutabili, compatibilità degli indirizzi e pagina.
Catalogo ETF (`tests/test_etf_catalog.py`, Fase 6A): costruzione vera eseguita senza rete su ISIN, pagine di borsa ed
elenchi inventati; ISIN e cifra di controllo, più ticker per un ISIN, valuta di negoziazione contro esposizione,
accumulo/distribuzione, coperto/non coperto («unhedged» non è coperto), dati mancanti mai zero, date e dati datati, TER
da più fonti e discordanze, tracking difference ed error separati, spread solo a mercato aperto e nessuna penalità per i
pochi scambi, azionari contro obbligazionari, livelli di comparabilità, nessun vincitore, titoli in comune parziali,
classi dello stesso fondo, doppioni, prodotti esclusi, indirizzi, scheda ETF esistente invariata, prestazioni con 600
ETF e nessuna chiamata di rete.
Scanner delle esposizioni ETF (`tests/test_etf_opportunity.py`, Fase 6B): catalogo e prezzi inventati; esposizioni e
famiglie, stesso ISIN su più borse contato una volta, classi distinte (coperta, distribuzione), dati aggiornati o
datati (spread, cache dei prezzi, chiusure definitive), rendimenti assoluti e relativi con benchmark coerente, cambio,
accumulo/distribuzione e rendimento totale, quotazione più lunga, trend, volatilità, calo dal massimo, azionari contro
obbligazionari, duration e sensibilità ai tassi, rendimento a scadenza contro cedola e distribuzione, confronto dei
prodotti senza vincitore, dati mancanti mai soddisfatti, TER e conflitti non risolti, liquidità e spread, ordine e
motivi, nessuna informazione futura, niente Compra/Vendi, diario (solo sedute chiuse, idempotente, immutabile, mai
dall'apertura della pagina), indirizzi, pagine iShares e tracking difference, nessuna regressione.
Ambienti e diari (`tests/test_environment_safety.py`, Fase 6C): cartelle sentinella che fanno da «produzione» (mai il
database reale): ambiente test riconosciuto, scrittura e rete bloccate, processo di produzione non autorizzato o con
origine «prova» rifiutato (il caso del 4 novembre), anteprima isolata in un processo separato, indirizzi API e server
HTTP vero su porta temporanea senza scritture, letture che non scrivono, prove riconosciute ed escluse, immutabilità,
registrazioni contemporanee, transazioni fallite senza giornate parziali, idempotenza, ultima seduta chiusa, fusi orari e
chiusure delle borse, ETF e benchmark non allineati, date obbligazionarie, stato dei diari, navigazione sul
telefono e punti d'ingresso autorizzati.

## File del progetto

| File/cartella | A cosa serve |
|---|---|
| `server.py` | Server: scarica i dati e li serve alla pagina web |
| `signals.py` | Report tecnico della sera (archivio in `reports/`, generato dal job serale) |
| `actions.py` | Livello proposto per ogni posizione (Valuta la vendita / Attenzione / Accumula / Mantieni) con le regole S, T, B, stima fiscale e zainetto |
| `pillars.py` | Pagella del titolo controllata ogni giorno, registro dei cambi, dati delle azioni e dei fondi fuori dagli elenchi |
| `stop_auto.py` | Stop automatico di ogni posizione, mai abbassato |
| `pos_diary.py` | Diario serale dei livelli delle posizioni e test fissato a 3 mesi |
| `analysts.py` | Dati degli analisti e valutazione (scaricati una volta al giorno) |
| `score.py` | Segnale finale (analisti + valutazione + notizie) e Trend a parte |
| `backtest.py` | Backtest del Trend e, con `--patterns`, test dei pattern tecnici (a mano) |
| `history.py` | Storico giornaliero del portafoglio e rendimento ponderato per il tempo contro QQQ e VWCE |
| `risk.py` | Rischio del portafoglio: volatilità, beta, scenario, massima perdita, contributo al rischio, correlazione |
| `rules.py` | Il mio rischio massimo per operazione (unica regola rimasta dopo la Fase 21) |
| `morning_job.py` | Riepilogo del mattino (08:30): finestra con eventi macro, trimestrali dei miei titoli, posizioni da rivedere, sedute mancanti |
| `daily_job.py` | Job serale: report, diario e fotografia del portafoglio anche con la dashboard chiusa |
| `earnings.py` | Dettagli delle trimestrali in Oggi (ultima trimestrale, movimento tipico nel giorno di reazione) |
| `tests/`, `requirements-dev.txt` | Test automatici con dati finti (pytest) |
| `diary.py` | Diario dei segnali: salva ogni giorno i verdetti e misura com'è andata ogni categoria dopo 1, 3 e 6 mesi |
| `opportunity_scanner.py` | Scheda Opportunità: le due classifiche esplorative (Trading e Investimento) con condizioni, valori misurati, avvisi, dati mancanti, diagnosi, copertura e parametri |
| `opportunity_diary.py` | Diario delle opportunità (SQLite in `data/`): classifiche di ogni seduta per tutti i titoli e risultati a 5–126 sedute |
| `market_data_quality.py` | Controlli di qualità dei dati storici (Fase 4A); revisioni manuali in `data_quality_reviews.json` |
| `fundamentals.py` | Bilanci annuali e trimestrali e calendario delle trimestrali (Fase 5A): download in background e cache `cache/fundamentals.json` |
| `investment_engine.py` | Analisi fondamentale (Fase 5A): indicatori con periodo e fonte, sei dimensioni, comparabili, profili; `/api/investment` |
| `investment_diary.py` | Giudizi dell'analisi fondamentale nel diario delle opportunità (tabelle nuove, solo sedute già registrate) |
| `investment_valuation.py` | Valutazione e scenari (Fase 5B): DCF sui flussi all'impresa, tre scenari, sensibilità, calcolo inverso; `/api/valuation` |
| `investment_valuation_v1.py` | Copia congelata del modello di valutazione V1 (Fase 5B), per riprodurre e confrontare (`confronta`) |
| `valuation_diary.py` | Valutazioni nel diario delle opportunità (tabelle nuove, solo sedute già registrate, prezzi di chiusura) |
| `opportunity_strategies.py` | Ricerca controllata di nuove strategie Trading (Fase 4B): protocollo in `docs/ricerca_strategie_4b.md`, risultati in `data/strategie/` |
| `etf_catalog.py` | Catalogo ETF UCITS (Fase 6A): modello, controllo ISIN, esclusi, ricerca, completezza, date; `/api/etf/catalog` |
| `etf_catalog_build.py` | Aggiornamento manuale del catalogo (emittente, Borsa Italiana, copia justETF, Yahoo) e classificazione |
| `etf_comparison.py` | Confronto di 2–4 ETF: livelli di comparabilità, dimensioni separate, rischi, titoli in comune; `/api/etf/compare` |
| `etf_catalog_verifiche.json` | TER verificati a mano su documenti dell'emittente, conflitti non risolti, approvazione delle 5 classi aggiunte (Fase 6B) |
| `etf_prices.py` | Chiusure in euro degli ETF del catalogo (Fase 6B) in `cache/etf_prices.pkl`, scaricate in background dopo la chiusura |
| `etf_opportunity.py` | Scanner esplorativo delle esposizioni ETF (Fase 6B): due modi, condizioni, rischi, prodotti; `/api/etf/opportunities` |
| `etf_opportunity_diary.py` | Diario dello scanner ETF (tabelle nuove in `data/opportunita.sqlite3`, immutabili) |
| `investment_decision_engine.py` | Decision Desk (Fase 7A, versione D2): stati trasparenti da T1–T5, Pagella, F1, V2 ed E2, senza ricalcolarli |
| `decision_diary.py` | Diario prospettico delle decisioni (Fase 7A), tabelle `dec_runs`/`dec_observations` |
| `portfolio_fit.py` | Compatibilità con il portafoglio (Fase 7B, P1): look-through, concentrazioni, valute, simulatore ipotetico |
| `app_env.py` | Ambienti produzione/test/anteprima, autorizzazione degli scrittori dei diari, guardia e isolamento (Fase 6C) |
| `diaries_status.py` | Stato dei cinque diari in sola lettura (Fase 6C, decisioni dalla D2); `/api/diaries/status` |
| `preview.py` | Anteprima isolata della dashboard sulla porta 8101 (Fase 6C) |
| `etf_catalog/` | Il catalogo: `strumenti.json`, `quotazioni.json`, `esposizione.json`, `fonti.json`, `controlli.json` (dati pubblici) |
| `opportunity_validation.py` | Laboratorio di validazione (Fase O3): studio storico esplorativo delle condizioni Trading, simulazione sperimentale e controllo dei dati per l'Investimento; report in `data/validazione/` |
| `decision.py` | Sezione Decisione della scheda titolo: cinque blocchi, verdetto e piani operativi con regole esplicite |
| `technical.py` | Numeri della sezione Analisi tecnica nella scheda del titolo (ATR, livelli, pattern, settore e tema) |
| `portfolio.py` | Portafoglio: lettura dell'export Fineco, ticker Yahoo, valori in euro |
| `macro_calendar.py` | Eventi macro USA: date ufficiali, controllo automatico, valori BLS (da aggiornare ogni anno per CPI e occupazione) |
| `market_calendar.py` | Festività e chiusure anticipate della borsa USA (da aggiornare ogni anno) |
| `themes.json` | Temi personalizzati (elenchi di ticker) |
| `etf_universe.py`, `etf_universe.json` | Elenco dei 63 ETF ed ETC della scheda ETF con i dati di justETF (fonte e data); rilanciarlo quando i dati hanno più di 6 mesi |
| `etf_holdings.py` | Primi 10 titoli degli ETF (file degli emittenti, ETF americano sullo stesso indice, justETF come ultima risorsa) e confronto dei titoli per ISIN o nome |
| `etf_buy.py` | «Ha senso comprare?» per gli ETF: regole, piano con tetto del 10%, diario degli ETF in `portafoglio/diario_etf/` |
| `etf.py` | Scheda ETF: rendimenti in euro, trend, «perché si muove», rischio di essere arrivati tardi, «Ha senso per il mio portafoglio?» |
| `etf_backtest.py` | Test delle regole di momentum sulle categorie (a mano, `reports/etf_momentum.json`) |
| `static/` | La pagina web (HTML, CSS, JavaScript) |
| `requirements.txt` | Librerie Python necessarie |
| `run.sh`, `schedule.sh` | Avvio da Terminale e programmazione del report |
| `daily_brief.py`, `job_status.py` | Riepilogo del giorno e stato del sistema (sola lettura); registro dei giri del job serale (Fase 8B) |
| `Nasdaq-100 Monitor.app` | Avvio con doppio clic |
| `.venv/` | Ambiente Python isolato (si ricrea con `./run.sh`) |
| `cache/` | Dati temporanei e log del server (si può cancellare) |
| `reports/` | Report salvati |
| `portafoglio/` | Export Fineco delle mie posizioni (dati personali, esclusa da Git) |
