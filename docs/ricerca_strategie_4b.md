# Fase 4B · Ricerca controllata di nuove strategie Trading — protocollo pre-registrato

Scritto il 4 novembre 2026, **prima** di qualsiasi studio sui dati reali. Configurazione del laboratorio `S1`
(`opportunity_strategies.py`). L'impronta della configurazione (hash) e quella di questo documento vengono salvate in
`data/strategie/preregistrazione.json` con `python opportunity_strategies.py registra`. Lo studio parte solo se
l'impronta della configurazione è ancora quella registrata. Una registrazione non si riscrive: per cambiare qualcosa
serve una nuova versione (`S2`), dichiarata come nuova ipotesi e non come correzione della vecchia.

Tutti i risultati di questa fase sono **«Studio esplorativo con survivorship bias»**. Nessun risultato è una
validazione e nessuno diventa un segnale di acquisto o vendita. Lo scanner operativo (regole T1–T5, regola 4 su 5,
soglie, classifica), `score.py`, `decision.py`, il diario delle opportunità e i risultati delle fasi precedenti
restano invariati.

---

## 1. Dati, periodi e cose già viste

**Prezzi.** Uso solo la copia congelata della Fase 3, `data/validazione/prezzi_2026-11-04_0804.pkl`
(sha256 `37af042f…8790c9ef6`). Contiene 101 titoli di oggi più QQQ, dal 1° ottobre 2015, con prezzi rettificati di
Yahoo Finance. Il laboratorio rifiuta un file con un'impronta diversa. Niente viene riscaricato.

**Errori di dato.** Applico la revisione `R1` (`data_quality_reviews.json`) su una **copia** dei dati. La serie
originale non viene cancellata. Escludo solo i tratti marcati come «errore verificato»:
- **FER**, prima del 9 maggio 2024: titolo illiquido fuori dal Nasdaq, smentito dalla quotazione di Madrid. FER parte
  dal 9 maggio 2024 e non raggiunge le 252 sedute necessarie prima della fine dei dati usati, quindi non entra in
  nessuna famiglia.
- **HONA**, la negoziazione «when-issued» del 2026: cade nel periodo finale e non viene caricata.

Il numero di osservazioni perse per errori verificati viene calcolato e scritto nel report. I dati «sospetti» non
verificati restano nello studio. Una sensibilità secondaria li esclude (§6). Le variazioni estreme vere non vengono mai
tolte.

**Periodi.** Le date sono fisse e uguali alla Fase 3. Tra un periodo e il successivo ci sono 21 sedute di distacco.

| Periodo | Da | A | Uso |
|---|---|---|---|
| Sviluppo | 2016-01-11 | 2022-05-13 | si guarda per primo |
| Verifica | 2022-06-15 | 2024-07-10 | conferma, stesso segno richiesto |
| Finale (riservato) | 2024-08-09 | — | **non caricato**: i prezzi vengono tagliati al giorno prima |

**Esposizione del periodo finale: non è cieco del tutto.** Nella Fase 4A, per controllare gli errori di prezzo, ho
guardato alcuni dati del 2026:
- **MRNA** il 19 e 20 agosto 2026 (+177%, movimento reale);
- **HONA** dal 15 al 26 giugno 2026 (when-issued);
- **HON** il 29 giugno 2026 (rettifica sospetta);
- l'elenco dei movimenti estremi 2024–2026 prodotto dal rapporto di qualità.

Nessun rendimento di strategia del periodo finale è stato calcolato, né in 4A né qui. Questi casi non hanno
informato nessuna scelta di questo protocollo. Da qui in avanti il periodo finale va descritto come «riservato, con
un'esposizione parziale documentata», mai come «mai osservato». Il periodo finale non serve a scegliere né a
migliorare una strategia.

**Universo.** I 101 titoli del Nasdaq-100 di oggi applicati al passato. Mancano i titoli usciti dall'indice, falliti
o acquisiti, quindi i rendimenti assoluti sono gonfiati (**survivorship bias**). I confronti nello stesso giorno tra
titoli dello stesso universo ne risentono meno, ma non sono immuni.

**Idoneità.** Un titolo entra in un giorno solo se ha almeno 253 sedute di storia fino a quel giorno. Ogni indicatore
di un giorno usa solo i dati fino a quel giorno.

## 2. Esperimenti già fatti (test multipli)

Su questi stessi dati sono già state provate molte ipotesi:
- **Fase 11** (`backtest.py --patterns`): 9 schemi, tra cui il momentum 12-1 nel 20% migliore (`mom12_1`) e due forme
  di ritracciamento (`pull50`, `pullback`), tutti bocciati.
- **Fase 3**: 12 gruppi giudicati su 3 orizzonti, cioè 36 confronti, più quintili di ATR, ridondanza, walk-forward e
  simulazione.
- **Fase 4A**: una rielaborazione con i dati corretti.

In totale sono **oltre 45 ipotesi**, e questa fase aggiunge 3 famiglie primarie. Con così tanti tentativi, un |t| di 2
uscirebbe spesso per caso. Per questo una differenza diventa «credibile» con la soglia della Fase 3 (|t| ≥ 2), ma per
lo stato più alto serve **|t| ≥ 3** nello sviluppo più gli altri criteri del §7. Un p < 0,05 da solo non conta nulla.

## 3. Famiglia A · Momentum relativo al settore

**Ipotesi economica.** Un titolo più forte dei titoli del **suo settore** potrebbe riflettere notizie proprie
dell'azienda (non del settore) che il mercato assorbe lentamente. Se è vero, la forza dentro il settore dovrebbe dare
informazione **in più** rispetto alla semplice forza nell'universo, che nella Fase 11 non ha funzionato.

**Limite dei dati, dichiarato prima.** Lo storico delle classificazioni settoriali **non esiste** nel progetto.
Abbiamo solo la colonna «ICB Industry» di Wikipedia di oggi (3 novembre 2026), congelata in
`data/strategie/settori_icb_2026-11-03.json`. Le classificazioni sono cambiate negli anni (per esempio la
riorganizzazione GICS del 2018 e i cambi ICB del 2019), quindi applicarle al passato è un'approssimazione. Non
invento nessuno storico.

Di conseguenza **A è solo esplorativa**. Anche con risultati ottimi il suo stato massimo resta «Candidato a verifica
prospettica», perché la verifica vera deve avvenire nel diario, con la classificazione del giorno.

Settori con meno di 5 titoli idonei quel giorno (Energy 2, Basic Materials 1 e a volte Utilities e
Telecommunications 4) **non hanno un valore**: i loro titoli escono dalla famiglia A e non vengono contati come
deboli.

**Regole (configurazione primaria, una sola).**
- Momentum 12-1: `mom = C[t−21] / C[t−252] − 1`. È il rendimento da 252 a 21 sedute fa, cioè l'ultimo mese è escluso.
- Forza nel settore: il percentile di `mom` tra i titoli idonei dello stesso settore, quel giorno.
- **A_TOP** (il gruppo giudicato): il terzo più forte del proprio settore (percentile > 2/3).
- **A_BOT**: il terzo più debole del settore (percentile ≤ 1/3).
- **A_NDX**: il terzo più forte di tutto l'universo, cioè il momentum 12-1 «semplice», già simile a quello bocciato
  nella Fase 11.
- **A_INC**: forte nel settore ma **non** nel terzo più forte dell'universo. Isola l'informazione in più.
- Ordine nella simulazione: distanza dalla mediana del settore (`mom − mediana del settore`), dalla più alta.

**Confronti.**
- A_TOP contro i non scelti, contro A_BOT, contro A_NDX e contro la regola 4/5.
- A_TOP contro la media del proprio settore nello stesso intervallo (rendimento settoriale).
- QQQ, l'universo del giorno e il controllo casuale (stesso numero di titoli scelti a caso).

**«Informazione aggiuntiva».** Regola fissata ora: A_TOP − A_NDX positivo nello sviluppo con t ≥ 2 **e** positivo
nella verifica (a 21 sedute).

**Falsificazione.** A non dà informazione aggiuntiva se A_TOP − A_NDX non è credibilmente positivo, oppure se A_INC
non batte i non scelti. Se A_TOP non batte i non scelti con un verdetto credibile, lo stato è «Nessun vantaggio
rilevato».

## 4. Famiglia B · Ritracciamento dentro un trend strutturale positivo

**Ipotesi economica.** Nei titoli in tendenza di fondo positiva, un mese debole rispetto al mercato è più spesso una
pausa che un'inversione. Prezzi temporaneamente più bassi in un trend solido potrebbero tornare verso il trend
(ritorno verso la media di breve dentro un momentum di lungo).

**Origine dei dati, dichiarata prima.** Questa ipotesi **nasce dai dati**: nella Fase 3, T1 (forza a 1 mese contro
QQQ) aveva un effetto **inverso** credibile, cioè i titoli deboli nell'ultimo mese facevano meglio. Studiare B sugli
stessi periodi non è una prova indipendente: sviluppo e verifica sono già stati guardati attraverso T1. Lo stato
massimo è «Candidato a verifica prospettica». La sola conferma valida sarà il diario o dati nuovi.

B è diversa dagli schemi bocciati nella Fase 11 (`pull50` vicino alla media 50; `pullback` vicino alla media 20 con
RSI). Qui il ritracciamento è **relativo al mercato** e il trend è **strutturale** (medie 50 e 200).

**Regole (configurazione primaria, una sola). Solo indicatori già presenti nel progetto.**
- **Condizione di trend**: chiusura sopra la media a 200 sedute **e** media 50 sopra media 200. È la stessa idea
  della regola B2 / I6 del progetto.
- **Misura del ritracciamento**: la differenza di rendimento con QQQ a 21 sedute (la misura di T1). Il titolo è nel
  **20% più debole** dei titoli idonei del giorno (percentile ≤ 0,20).
- **Invalidazione**: il titolo è escluso se è più del 25% sotto il massimo delle ultime 252 sedute. Non è un
  ritracciamento ma un crollo.
- **Filtro di volatilità**: nessuno nella primaria. Secondaria: ATR 14 fino al 4% del prezzo (la soglia `ATR_HIGH`
  dello scanner).
- **Conferma**: nessuna nella primaria. Secondaria: chiusura sopra quella del giorno prima.
- **Orizzonti**: 5, 10 e 21 sedute. Lo stato si decide a 21.
- **Ordine nella simulazione**: rendimento a 126 sedute, dal più alto (il trend più forte prima).

**Confronti.**
- **B_TNP**: trend senza ritracciamento (percentile > 0,40).
- **B_PNT**: ritracciamento senza trend (stesso 20% più debole, ma senza la condizione di trend).
- I non scelti dello stesso giorno, l'universo del giorno, QQQ, il controllo casuale e la regola 4/5.

**Falsificazione.** B non ha vantaggio se non batte i non scelti con un verdetto credibile, **oppure** se non batte
B_TNP e B_PNT. Se B batte i non scelti ma non B_PNT, il trend non aggiunge nulla e il risultato è solo l'effetto
inverso di T1 già noto.

## 5. Famiglia C · Contesto di mercato

**Ipotesi economica.** Le strategie di selezione funzionano peggio quando tutto il mercato scende. Le correlazioni
salgono e la selezione conta meno. Un filtro di contesto potrebbe ridurre le perdite senza rinunciare troppo ai
guadagni.

**Contesti, solo da QQQ e noti alla data del segnale.**
- **Ribassista**: QQQ sotto la sua media a 200 sedute.
- **Recupero**: QQQ sopra la media 200, ma sotto almeno una volta nelle 63 sedute precedenti.
- **Rialzista**: tutti gli altri giorni.

**Ampiezza di mercato (breadth): non usata.** Con i soli 101 titoli di oggi applicati al passato sarebbe falsata
dal survivorship bias: mancano proprio i titoli che sono crollati e usciti.

**Applicazione.** Il contesto modifica tre strategie: A_TOP, B e la regola attuale 4/5. Il filtro è uno solo: **nessun
nuovo ingresso nei giorni ribassisti**. Le posizioni aperte proseguono fino alla scadenza.

**Misure.**
- **Statistica**: il vantaggio della strategia contro i non scelti, separato per contesto.
- **Episodi**: il numero di episodi ribassisti distinti. Due tratti a meno di 21 sedute di distanza sono un solo
  episodio.
- **Simulazione con e senza filtro**:
  - rendimento netto, perdita massima e rendimento/rischio;
  - esposizione e operazioni perse (opportunità mancate).
- **Stare fuori dal mercato non è selezione.** Confronto il filtro con **QQQ filtrato allo stesso modo**. La misura
  «effetto del filtro oltre il semplice stare fuori dal mercato» vale
  (strategia con filtro − strategia senza) − (QQQ con filtro − QQQ senza).

**Evidenza minima.** Servono almeno 5 episodi ribassisti nello sviluppo e 2 nella verifica. Altrimenti lo stato è
«Evidenza insufficiente», qualunque sia il numero.

**Regola dello stato.** Il filtro è utile per una strategia solo se:
- il vantaggio della strategia è credibilmente **peggiore** nei giorni ribassisti (t ≤ −2 nello sviluppo e media
  negativa nella verifica);
- **e** il filtro migliora il rendimento/rischio della simulazione (costi 0,10%).

Lo stato massimo per C è «Risultato esplorativo promettente». Il contesto non è una strategia di selezione e non
viene messo in verifica prospettica da solo.

**Falsificazione.** Se il filtro migliora i numeri solo quanto migliorerebbe QQQ filtrato, non aggiunge nulla alla
selezione.

**Secondaria.** Due soli stati (QQQ sopra o sotto la media 200). È il contesto già mostrato nella Fase 3.

## 6. Analisi secondarie (dichiarate ora, non decidono da sole)

| Codice | Cosa cambia |
|---|---|
| A_6_1 | formazione 6-1 mesi (126 → 21 sedute) invece di 12-1 |
| B_CONF | B con conferma: chiusura sopra quella del giorno prima |
| B_ATR | B con ATR 14 fino al 4% del prezzo |
| WINSOR | rendimenti futuri limitati al 1° e al 99° percentile (peso dei casi estremi) |
| SUSPECT | esclusi i giorni la cui finestra (252 sedute prima, 21 dopo) contiene un dato sospetto non verificato |
| C_2 | contesto con due soli stati |

Nessuna ricerca su altre soglie. Nessuna combinazione automatica. Le sensibilità servono solo a dire se il risultato
primario regge.

## 7. Misure, verdetti e stati

**Misure** (stesse funzioni della Fase 3, nessuna statistica duplicata).
- Per ogni gruppo e orizzonte: numero di segnali, giorni e titoli; media e mediana; percentuale positiva; percentili
  10, 25, 75 e 90.
- I confronti:
  - contro QQQ, contro l'universo e contro i non scelti dello stesso giorno (differenza media giornaliera);
  - t con errori di Newey-West (ritardo = orizzonte) per le osservazioni sovrapposte;
  - periodi indipendenti non sovrapposti;
  - risultati per anno e per contesto;
  - il controllo casuale (200 estrazioni).

**Verdetto** per gruppo e orizzonte: la funzione `verdict` della Fase 3. Servono almeno 100 segnali, almeno 20
periodi indipendenti nello sviluppo e 10 nella verifica, |t| ≥ 2 e lo stesso segno nella verifica. Altrimenti il
verdetto è «Evidenza insufficiente».

**Stato** per famiglia, a 21 sedute. Le regole sono fissate ora:
1. Dati necessari assenti: **Ipotesi non verificabile**.
2. Verdetto «Evidenza insufficiente» o «verifica non possibile»: **Evidenza insufficiente**.
3. Verdetto diverso da «Differenza migliore credibile»: **Nessun vantaggio rilevato**. Questo vale anche per una
   differenza peggiore credibile.
4. Altrimenti **Risultato esplorativo promettente**.
5. Diventa **Candidato a verifica prospettica** solo se valgono tutte queste condizioni:
   - |t| ≥ 3 nello sviluppo e t ≥ 1 nella verifica;
   - tutte le sensibilità secondarie con lo stesso segno e t ≥ 2;
   - la simulazione con costi 0,10% sopra la mediana delle scelte a caso.

Mai «Strategia validata». C ha le regole del §5.

## 8. Simulazione (separata dalla previsione)

Il motore è lo stesso della Fase 3 (`opportunity_validation.simulate`):
- **Segnale e ingresso**: segnale alla chiusura, ingresso all'**apertura della seduta dopo**, mai alla chiusura del
  segnale.
- **Uscita**: all'apertura dopo 21 sedute.
- **Posizioni e capitale**: al massimo 10 titoli in quote uguali, capitale 10.000. Ogni titolo una volta sola alla
  volta.
- **Costi ipotetici per lato**: 0%, 0,10% e 0,25%.
- **Prezzi mancanti**: nessun prezzo inventato. Un'apertura mancante usa la chiusura precedente, come nella Fase 3, ed
  è documentato.
- **Valutazione**: il portafoglio è valutato ogni sera. I rendimenti dei singoli segnali non vengono mai sommati.
- **Segnali usati**: solo quelli noti quel giorno.
- **Confronti**: QQQ nello stesso intervallo e 20 portafogli con le stesse regole e titoli a caso.

Una simulazione positiva **non è una prova di redditività**: lo stesso universo con il survivorship bias gonfia i
numeri.

## 9. Cosa non si fa

- Nessuna ottimizzazione delle soglie.
- Nessuna famiglia oltre A, B e C.
- Nessun uso del periodo finale.
- Nessuna modifica allo scanner, alle regole, a `score.py`, a `decision.py`, al diario o ai dati del portafoglio.
- Nessun commit automatico.
- Se una famiglia non è verificabile in modo credibile, lo dico e passo oltre, senza dati sostitutivi.
