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

La dashboard ha **tre schede** (Fase 21); ognuna raggruppa le pagine descritte sotto. All'avvio si apre **Portafoglio**.

| Scheda | Domanda | Sotto-schede |
|---|---|---|
| **Mercato** | Cosa sta succedendo? | Oggi (con eventi macro USA e trimestrali) · Settori (con la mappa di rotazione) |
| **Portafoglio** | Cosa ho e come sta andando? | Posizioni · Performance · Concentrazione · Rischio |
| **Ricerca** | Cosa potrei comprare? | Screener · ETF (Fase 24) · In osservazione (i preferiti ★) · Diario dei segnali (compare quando ha almeno 3 mesi di dati); da qui si apre la scheda del titolo con la sezione Decisione |

I vecchi link portano alla pagina più vicina: `#overview` → Oggi, `#sectors` e `#ideas` (il vecchio Report) → Settori,
`#portfolio` e `#rules` → Posizioni, `#screener` e `#trade` (i vecchi Pattern tecnici) → Screener, `#watch` → In
osservazione, `#diary` → Diario se visibile, altrimenti Screener. `#mercato`, `#portafoglio` e `#ricerca` aprono la
scheda sull'ultima pagina usata.

**Tolto nella Fase 21** (per una dashboard più semplice; i calcoli che restano non dipendono da queste parti):
la scheda Metodo con Report, Pattern tecnici, Diario e Le mie regole (i risultati dei backtest sono più sotto in
questo file; il diario continua a registrare in background); il riquadro "Cosa richiede attenzione oggi"; i limiti sui
pesi (titolo, ETF, tema, settore, paese, leva) con il riquadro "Rispetto delle regole", le regole R1, R2 e A3 delle
azioni (quindi l'azione "Riduci") e la regola D3 del verdetto; il verdetto "Entra su rottura" (diventa "Attendi: a
ridosso del massimo"); gli avvisi di calendario dentro le card (ora una piccola ⚠ in alto, solo negli ultimi 30 giorni).

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
- **Tesi e azioni sulle posizioni** (colonna "Azione" della tabella delle posizioni): per ogni posizione posso scrivere
  una tesi breve (perché la possiedo, cosa mi aspetto, cosa mi farebbe vendere) con stop, target e peso obiettivo
  facoltativi, salvata in `portafoglio/tesi.json`. La dashboard propone **Mantieni / Accumula / Rivedi la tesi** con
  regole esplicite (`actions.py`); accanto compaiono i motivi con i numeri. **Rivedi la tesi**: V1 stop rotto, V2 target
  raggiunto (etichetta "Rivedi · target raggiunto", valuta una presa di profitto), V3 prezzo sotto la media 200, V4 stime
  tagliate di oltre il 3% in 30 giorni, V5 più downgrade che upgrade, V6 perde oltre il 25% dal prezzo di carico ("la
  tesi è ancora valida? Decidi in base alle prospettive, non al prezzo pagato"), V7 prodotto a leva nello storico da più
  di 30 giorni, V8 tesi più vecchia di 6 mesi. **Accumula** solo se: A1 peso sotto l'80% del mio peso obiettivo, A2
  nessuna regola Rivedi scattata, A4 non è un prodotto a leva, A5 nessuna trimestrale entro 5 giorni (altrimenti
  Mantieni con la nota "accumula dopo la trimestrale del …"). Pulsante **Ho rivisto la tesi**: una riga di motivazione,
  e i motivi Rivedi scattati restano silenziati per 30 giorni, a meno che non ne scatti uno nuovo. Accanto a "Rivedi ·
  target raggiunto" c'è l'**effetto fiscale stimato** (plusvalenza o minusvalenza e imposta indicativa al 26%): per
  azioni ed ETC/ETN tiene conto dello **zainetto fiscale** indicato in Posizioni (sezione chiusa sotto la tabella,
  `portafoglio/fiscale.json`); per gli ETF UCITS no, perché i guadagni sono redditi di capitale. Senza zainetto una nota
  avverte che l'imposta reale può essere più bassa. Stima indicativa, non consulenza fiscale. Regole di disciplina,
  **non verificate da un backtest**. (Tolte nella Fase 21: R1, R2 e A3 sui limiti di peso, e con loro "Riduci".)
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
- **ETF** (Ricerca → ETF, Fase 24; `etf.py`, `/api/etf`): 63 ETF ed ETC UCITS quotati in Italia (`etf_universe.json`, elenco
  approvato l'8 ottobre 2026). I dati si calcolano una volta al giorno in background (circa un minuto la prima volta).
  - **Radar dei temi** (visibile): le 5 categorie più forti e le 5 più deboli sul rendimento in euro a 3 mesi, con
    accanto il momentum 12-1. Per ognuna c'è un «perché» calcolato: i due primi titoli dell'ETF americano equivalente
    che spiegano almeno il 10% del movimento, la categoria con cui si è mossa negli ultimi 6 mesi (correlazione) e i
    titoli delle notizie quando Yahoo li fornisce. «Si è mosso come» compare solo con correlazione almeno 0,70; sotto, la
    pagina scrive «non si muove in modo simile a nessun'altra categoria (correlazione massima X con Y)». C'è poi un verdetto in tre parti: (a) momentum forte, medio o debole
    (terzo delle categorie) e da quanti mesi, **non verificato**; (b) rischio di essere arrivati tardi, cioè il percentile
    della distanza di oggi dalla media 200 nei giorni degli ultimi 5 anni (alto sopra il 90°, medio tra 70° e 90°, basso
    sotto), più la perdita massima della storia più lunga disponibile (con la sua fonte) e la nota «tema giovane» sotto i
    5 anni; (c) se ha senso per il mio
    portafoglio. Per i temi c'è una ⓘ «satellite».
  - **Tabella** con filtro per gruppo e ordinamento. Colonne: 1 m, 3 m, 1 a, 3 a, 12-1, volatilità, perdita massima a 3
    anni, trend 50/200, TER, «Per il mio portafoglio». Rendimenti in euro.
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
  - **Pannello dell'ETF**: rendimenti in euro con la parte dovuta al cambio (per i sottostanti in una sola valuta), trend,
    «Ha senso adesso?» (solo rischio di essere arrivati tardi e «non verificato»: mai «favorevole» o «investi»), dettagli
    della sovrapposizione, composizione e dati di justETF con fonte e data (avviso se hanno più di 6 mesi), P/E
    dell'ETF americano equivalente, ⓘ sulle tasse, ★ per metterlo In osservazione e link alla posizione se lo possiedo.
    Gli ETF americani sono solo fonti di dati, mai prodotti da comprare.
  - **Sezioni chiuse**: mappa di rotazione delle categorie rispetto all'All-World (VWCE), con la scala adattata ai dati e
    i nomi scritti solo per le 10 categorie del radar (le altre al passaggio del mouse), e test delle regole di momentum.
  - Se i prezzi storici del portafoglio non arrivano da Yahoo, la dashboard riprova dopo 15 minuti (prima restavano vuoti
    fino al giorno dopo) e la pagina lo scrive, invece di mostrare verdetti senza correlazione.
  - Gli ETF con la ★ compaiono in Ricerca → In osservazione, sotto i titoli.
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

## Report e job programmati

Il report tecnico (`signals.py`) non è più una pagina della dashboard (Fase 21): la mappa di rotazione ora è in
Mercato → Settori e i titoli di ogni pattern nella sezione Decisione. Con la programmazione di macOS (launchd), dal
lunedì al venerdì, ora locale:

- **08:30** riepilogo del mattino (`morning_job.py`, Fase 23): se c'è qualcosa di rilevante compare una finestra con gli
  eventi macro di oggi (orario italiano), le trimestrali dei miei titoli (preferiti e portafoglio) nei prossimi 5 giorni,
  il numero di posizioni in "Rivedi la tesi" e le sedute mancanti nel diario; pulsanti "Chiudi" e "Apri la pagina Oggi"
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

## File del progetto

| File/cartella | A cosa serve |
|---|---|
| `server.py` | Server: scarica i dati e li serve alla pagina web |
| `signals.py` | Report tecnico della sera (archivio in `reports/`, generato dal job serale) |
| `actions.py` | Tesi delle posizioni, azione proposta (Mantieni / Accumula / Rivedi la tesi) con le sue regole, stima fiscale e zainetto |
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
| `decision.py` | Sezione Decisione della scheda titolo: cinque blocchi, verdetto e piani operativi con regole esplicite |
| `technical.py` | Numeri della sezione Analisi tecnica nella scheda del titolo (ATR, livelli, pattern, settore e tema) |
| `portfolio.py` | Portafoglio: lettura dell'export Fineco, ticker Yahoo, valori in euro |
| `macro_calendar.py` | Eventi macro USA: date ufficiali, controllo automatico, valori BLS (da aggiornare ogni anno per CPI e occupazione) |
| `market_calendar.py` | Festività e chiusure anticipate della borsa USA (da aggiornare ogni anno) |
| `themes.json` | Temi personalizzati (elenchi di ticker) |
| `etf_universe.py`, `etf_universe.json` | Elenco dei 63 ETF ed ETC della scheda ETF con i dati di justETF (fonte e data); rilanciarlo quando i dati hanno più di 6 mesi |
| `etf_holdings.py` | Primi 10 titoli degli ETF (file degli emittenti, ETF americano sullo stesso indice, justETF come ultima risorsa) e confronto dei titoli per ISIN o nome |
| `etf.py` | Scheda Ricerca → ETF: rendimenti in euro, radar dei temi, rischio di essere arrivati tardi, «Ha senso per il mio portafoglio?» |
| `etf_backtest.py` | Test delle regole di momentum sulle categorie (a mano, `reports/etf_momentum.json`) |
| `static/` | La pagina web (HTML, CSS, JavaScript) |
| `requirements.txt` | Librerie Python necessarie |
| `run.sh`, `schedule.sh` | Avvio da Terminale e programmazione del report |
| `Nasdaq-100 Monitor.app` | Avvio con doppio clic |
| `.venv/` | Ambiente Python isolato (si ricrea con `./run.sh`) |
| `cache/` | Dati temporanei e log del server (si può cancellare) |
| `reports/` | Report salvati |
| `portafoglio/` | Export Fineco delle mie posizioni (dati personali, esclusa da Git) |
