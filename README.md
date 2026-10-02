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
- **Le mie regole** (in cima alla scheda Portafoglio): pochi limiti, come il mandato di una banca privata. Riquadro
  **Rispetto delle regole**: verde se tutto è nei limiti, altrimenti l'elenco dei limiti superati con valore, limite e
  di quanto (per esempio "Prodotti a leva: 28,8% dell'esposizione effettiva, limite 15% (+13,8 punti)"), in giallo quelli
  vicini al limite. Limiti: singolo titolo, singolo ETF ampio, altro ETF/ETC (quota del valore); tema, settore, paese
  (quota dell'esposizione effettiva, dove un prodotto a leva 3x conta 3 volte); prodotti a leva (sul valore e
  sull'esposizione effettiva); rischio massimo per singola operazione (usato per il numero di azioni nell'Analisi
  tecnica, insieme al limite per singolo titolo). **Modifica regole** apre la pagina con i campi, i valori proposti
  (10 / 35 / 15 / 25 / 50 / 80 / 5 / 15 / 1%, avviso dal 90% del limite) e la spunta "ampio" per i miei ETF. Si salvano
  in `portafoglio/regole.json` (fuori da Git, solo da questo Mac); finché non salvo valgono i valori proposti, indicati
  come "non ancora confermati". Superare un limite non è un ordine di vendita: è un punto da guardare.
- **Rischio del portafoglio** (scheda Portafoglio, sotto i totali), con ⓘ semplici: **volatilità annua** e confronto con
  QQQ; **beta** sul Nasdaq-100; **scenario** "se il Nasdaq-100 perde il 10% / 20% il portafoglio perde circa X €"
  (beta × calo × valore, la leva entra con i prezzi veri dei prodotti a leva); **massima perdita storica** del
  portafoglio di oggi negli ultimi 2 anni, con le date e QQQ negli stessi giorni; **contributo al rischio** di ogni
  posizione confrontato con il suo peso in euro (⚠ da 1,5 volte il peso); **correlazione** media pesata e le 5 coppie
  più simili. Metodo (`risk.py`): 2 anni di chiusure giornaliere convertite in euro, portafoglio simulato con i pesi di
  oggi tenuti fissi; volatilità e massima perdita sui rendimenti giornalieri, beta, contributo e correlazioni su quelli
  settimanali (Milano e Francoforte chiudono prima di New York). Restano fuori, e sono elencate con il motivo, le
  posizioni con meno di 6 mesi di prezzi o con prezzi storici anomali (salti di un giorno oltre +150% / −75%). Limiti
  scritti nella sezione: due anni sono pochi, pesi di oggi nel passato, scenario lineare, stime e non previsioni.
  I prezzi si scaricano una volta al giorno e restano in memoria.
- **Storico e performance** (scheda Portafoglio): ogni giorno, a ogni aggiornamento dei prezzi, la dashboard salva in
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
- **Tesi e azioni sulle posizioni** (scheda Portafoglio): per ogni posizione posso scrivere una tesi breve (perché la
  possiedo, cosa mi aspetto, cosa mi farebbe vendere) con stop, target e peso obiettivo facoltativi, salvata in
  `portafoglio/tesi.json` (solo su questo Mac). La dashboard propone **Mantieni / Accumula / Riduci / Rivedi la tesi**
  con regole esplicite (`actions.py`); vince la più grave e accanto compaiono i motivi con i numeri.
  **Riduci**: R1 peso sopra il mio limite (titolo, ETF ampio, altro ETF), R2 prodotto a leva con i limiti sulla leva
  superati. **Rivedi la tesi**: V1 stop rotto, V2 target raggiunto (valuta una presa di profitto), V3 prezzo sotto la
  media 200, V4 stime di utile tagliate di oltre il 3% in 30 giorni, V5 più downgrade che upgrade in 30 giorni,
  V6 perdita oltre il 25% dal prezzo di carico, V7 prodotto a leva nello storico da più di 30 giorni, V8 tesi più
  vecchia di 6 mesi. **Accumula** solo se: A1 peso sotto l'80% del mio peso obiettivo, A2 nessuna regola Riduci o
  Rivedi scattata, A3 arrivare all'obiettivo non supera nessun mio limite, A4 non è un prodotto a leva, A5 nessuna
  trimestrale entro 5 giorni (altrimenti Mantieni con la nota "accumula dopo la trimestrale del …"). Il target
  raggiunto compare con l'etichetta **"Rivedi · target raggiunto"**. Il motivo della V6 non suggerisce di vendere
  ("la tesi è ancora valida? Decidi in base alle prospettive, non al prezzo pagato"). Pulsante **Ho rivisto la tesi**
  nel pannello: scrivo una riga di motivazione, salvata in `tesi.json` con la data, e i motivi "Rivedi" scattati
  restano silenziati per 30 giorni, a meno che non ne scatti uno nuovo; nel riquadro le posizioni silenziate sono solo
  un conteggio. Accanto a "Riduci" e a "Rivedi · target raggiunto" c'è l'**effetto fiscale stimato**: plusvalenza o
  minusvalenza sulla quota da vendere (sull'intera posizione per il target) e imposta indicativa al 26%; azioni ed
  ETC/ETN: redditi diversi, plus e minus compensabili; ETF UCITS: i guadagni sono redditi di capitale (non compensano
  le minusvalenze), le perdite redditi diversi. È una stima indicativa, non una consulenza fiscale. Note senza
  azione: tesi mancante, trimestrale entro 5 giorni, tema/settore/paese sopra il limite, segnale e Trend ("non
  verificati"). In cima alla scheda il riquadro **Cosa richiede attenzione oggi** elenca solo le posizioni con azione
  diversa da Mantieni; la colonna "Azione" della tabella apre il pannello della posizione (tesi, azione, tutte le
  regole con ✅ / — / non valutabile). Sono regole di disciplina, **non verificate da un backtest**: V4 e V5 valgono
  solo per i titoli del Nasdaq-100.
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
  - **Decisione** (solo titoli del Nasdaq-100; assorbe la vecchia "Analisi tecnica"): la scheda che un analista
    porterebbe al comitato d'investimento, in cinque blocchi letti in ordine (`decision.py`).
    **1. Azienda e valutazione** (decide SE comprare): otto criteri da +1 / 0 / −1 (crescita di ricavi e utili oltre il
    10% o negativa, margine netto oltre il 15% o sotto il 5%, cassa generata oltre il 10% dei ricavi o negativa, debito
    netto ripagabile in meno di 2 o più di 5 anni di cassa, valutazione Economica o Cara, stime riviste di oltre +2% o
    −3%, più upgrade o più downgrade) e la sintesi: solida (da +3), debole (da −1 in giù), nella media.
    **2. Contesto**: settore e tema (fase di rotazione, titolo contro il gruppo), eventi macro dei prossimi 7 giorni,
    giorni alla trimestrale. **3. Tempismo tecnico** (decide QUANDO e A CHE PREZZO): medie e trend, livelli chiave,
    pattern presenti con l'etichetta "verificato" o "non verificato" dal test della Fase 11.
    **4. Posto nel mio portafoglio** (decide QUANTO): se lo possiedo e quanto pesa, spazio lasciato da ogni mia regola
    (titolo, tema, settore, paese), sovrapposizione con i miei ETF sul Nasdaq-100, massimo acquistabile.
    **5. Piano operativo** con il verdetto e, sotto, l'elenco delle regole soddisfatte (✅) e non (❌); decide la prima
    non soddisfatta: D1 azienda debole → **Evita**; D2 trimestrale entro 5 giorni → **Attendi: trimestrale il …**;
    D3 l'acquisto supererebbe un mio limite → **Attendi**; D4 prezzo sotto la media 200 → **Attendi**; D5 tirato
    (oltre l'8% sopra la media 20 o RSI oltre 75) → **Entra su ritracciamento** (ordine limite vicino alla media 20 o
    50); D6 entro il 3% sotto il massimo a 52 settimane → **Entra su rottura** (ordine condizionato, con la nota che la
    rottura NON ha superato il test); D7 azienda nella media e prezzo oltre il 2% sopra la media 20 → **Entra su
    ritracciamento**; tutte soddisfatte → **Entra ora**. Per i titoli che possiedo il verdetto è l'azione della Fase 17.
    Ogni piano ha entrata, stop (sotto la media 50 o l'ultimo minimo meno mezzo ATR se tra 1,5 e 3,5 ATR, altrimenti
    2 × ATR; le altre opzioni si possono cliccare), target a 2 volte il rischio e quantità calcolata dal rischio per
    operazione e dallo spazio lasciato dalle mie regole. Regole non verificate da backtest (lo dice la sezione): le
    misura il Diario dei segnali.
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
| `actions.py` | Tesi delle posizioni e azione proposta (Mantieni / Accumula / Riduci / Rivedi la tesi) con le sue regole |
| `analysts.py` | Dati degli analisti e valutazione (scaricati una volta al giorno) |
| `score.py` | Segnale finale (analisti + valutazione + notizie) e Trend a parte |
| `backtest.py` | Backtest del Trend e, con `--patterns`, test dei pattern tecnici (a mano) |
| `history.py` | Storico giornaliero del portafoglio e rendimento ponderato per il tempo contro QQQ e VWCE |
| `risk.py` | Rischio del portafoglio: volatilità, beta, scenario, massima perdita, contributo al rischio, correlazione |
| `rules.py` | Le mie regole di investimento (limiti) e il controllo sul portafoglio |
| `decision.py` | Sezione Decisione della scheda titolo: cinque blocchi, verdetto e piani operativi con regole esplicite |
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
