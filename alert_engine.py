"""Alert e cambiamenti (Fase 8A, motore «A1»): cosa è cambiato dall'ultima osservazione valida, solo da analisi già
registrate. Informativo, verificabile, non predittivo: nessun ordine, nessun compra/vendi, nessuna probabilità.

Fonti (tutte pubbliche, mai il portafoglio personale):
- i cinque diari prospettici in data/opportunita.sqlite3, SOLO le registrazioni ufficiali e ammissibili (origine
  ufficiale e fuori dal registro delle esclusioni, diary_exclusions.json): mai prove, anteprime o registrazioni tardive;
- il catalogo ETF (etf_catalog.load) per prodotto, costi, concentrazione e freschezza dei dati;
- lo stato dei diari (diaries_status.status) per i problemi operativi.
Nessun modello viene ricalcolato e nulla viene scaricato.

Confronto: per ogni diario l'ultima seduta ammissibile con la precedente ammissibile, solo se le due hanno la STESSA
versione del modello. Con una sola seduta (o al primo giro dopo un cambio di versione) c'è solo la base di partenza
(«baseline»): nessun alert di cambiamento. Un cambio di versione è un cambiamento metodologico (OP-VERSIONE), mai
confrontato come se fosse un cambiamento dei dati.

Registro: data/alert.sqlite3, separato dai diari, scritto solo da un processo autorizzato (server avviato, job serale)
attraverso app_env.check_diary_write; righe mai modificate né cancellate (trigger). Un giro è identificato dall'impronta
dei suoi input: lo stesso stato dei dati non produce mai un secondo giro (idempotenza). Gli eventi hanno un
identificativo deterministico; il loro stato (nuovo, già segnalato/persistente, risolto, superato) è in una tabella a
parte, additiva. Lo stato «consultato» resta nel browser (localStorage) e non tocca il registro. Le richieste di
lettura (/api/alerts) aprono il registro in sola lettura: non creano alert e non scrivono nulla."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime

import app_env

VERSION = "A1"
ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(app_env.DATA, "alert.sqlite3")
RULES_FILE = os.path.join(ROOT, "alert_rules.json")
DISCLAIMER = ("Alert informativi su analisi già registrate: descrivono cosa è cambiato, non cosa accadrà. Nessun alert è un "
              "ordine o una raccomandazione di acquisto o vendita. Non costituisce consulenza finanziaria.")

PRIORITY = {"critica": "Criticità da verificare", "importante": "Cambiamento importante", "ordinaria": "Aggiornamento ordinario"}
PRIORITY_RULE = ("La priorità dipende solo dal tipo di evento, scritto prima nelle regole: criticità operative e dati non più "
                 "utilizzabili per l'analisi → «Criticità da verificare»; stati più restrittivi, soglie DCF dello scenario "
                 "base, nuovi bilanci con giudizi cambiati, nuovi rischi, cambi del prodotto o del credito → «Cambiamento "
                 "importante»; il resto → «Aggiornamento ordinario». Mai una probabilità di guadagno.")

# Alert thresholds of THIS module (documented here before use; the thresholds of the engines are never touched)
DCF_BAND = 0.03          # hysteresis: a DCF scenario value counts as crossed only with the price at least 3% beyond it
DCF_DIST_LOG = 0.15      # distance price / base value changed by at least 0.15 in log terms (about 16%)
BOND_DURATION = 0.5      # years
BOND_YIELD = 0.5         # percentage points
BOND_RATING = 10.0       # points of the share rated A or better
CONC_PP = 5.0            # points of the weight of the top 10 holdings (10 points: important)
TREND_CONFIRM = 2        # an ETF trend counts as changed only when the new value holds for 2 sessions in a row
USABLE_DCF = ("adeguata", "parziale", "sensibile")
RESTRICTIVE = ("Rischio elevato", "Dati insufficienti")
EXPLORATORY = ("Monitora — trend esplorativo", "Trend favorevole da monitorare")
FUND_DIMS = {"quality": "qualità (margini e flusso di cassa)", "growth": "crescita", "solidity": "solidità finanziaria"}

RULES = [
    {"id": "AZ-D2-STATO", "scope": "azione", "family": "Decision Desk", "kind": "evento",
     "title": "Stato del Decision Desk cambiato",
     "when": "lo stato D2 di una società (stesso orizzonte) è diverso tra due sedute ammissibili con la stessa versione",
     "priority": "importante se il nuovo stato è «Rischio elevato» o «Dati insufficienti» o se lascia «Da approfondire»; altrimenti ordinaria"},
    {"id": "AZ-FOND-PERIODO", "scope": "azione", "family": "Fondamentali", "kind": "evento",
     "title": "Nuovi bilanci con giudizi cambiati",
     "when": "trimestre o esercizio più recente della fonte diverso (periodo nuovo identificabile) e almeno uno tra qualità, "
             "crescita e solidità con un giudizio diverso; nuovi bilanci con giudizi invariati: un solo avviso raggruppato",
     "priority": "importante (giudizi cambiati), ordinaria (raggruppato)"},
    {"id": "AZ-FOND-STIME", "scope": "azione", "family": "Fondamentali", "kind": "evento",
     "title": "Aspettative degli analisti cambiate",
     "when": "giudizio sulle aspettative diverso con dati degli analisti di una data più recente (revisione osservabile)",
     "priority": "ordinaria"},
    {"id": "AZ-FOND-RIVISTI", "scope": "azione", "family": "Fondamentali", "kind": "evento",
     "title": "Giudizi fondamentali cambiati senza un nuovo periodo",
     "when": "qualità, crescita o solidità diverse con lo stesso periodo di bilancio: dati della fonte rivisti",
     "priority": "ordinaria"},
    {"id": "AZ-DCF-SOGLIA", "scope": "azione", "family": "Prezzo e DCF", "kind": "evento",
     "title": "Prezzo oltre un valore di scenario DCF",
     "when": f"il prezzo passa dall'altra parte del valore di uno scenario V2 (prudente, base, favorevole) con una fascia di "
             f"isteresi del {DCF_BAND:.0%} (dentro la fascia vale il lato precedente); solo con valutazione utilizzabile "
             "nelle due sedute; prezzo e ipotesi mostrati come cause separate",
     "priority": "importante per lo scenario base, ordinaria per prudente e favorevole"},
    {"id": "AZ-DCF-DISTANZA", "scope": "azione", "family": "Prezzo e DCF", "kind": "evento",
     "title": "Distanza dal valore base cambiata molto",
     "when": f"distanza prezzo / valore base cambiata di almeno {DCF_DIST_LOG} in logaritmo (circa 16%) senza "
             "attraversamento di soglia; prezzo e ipotesi mostrati come cause separate",
     "priority": "ordinaria"},
    {"id": "AZ-DCF-AFFIDABILITA", "scope": "azione", "family": "Prezzo e DCF", "kind": "evento",
     "title": "Valutazione DCF non più utilizzabile",
     "when": "stato della valutazione da adeguata/parziale/sensibile a non affidabile, non appropriata o dati insufficienti",
     "priority": "importante"},
    {"id": "AZ-RISCHIO", "scope": "azione", "family": "Rischio", "kind": "evento",
     "title": "Nuovo rischio bloccante",
     "when": "nella scheda D2 compare un rischio marcato come bloccante che nella seduta precedente non c'era (stessa fonte, "
             "stesso testo a meno dei numeri)",
     "priority": "importante"},
    {"id": "AZ-DATI", "scope": "azione", "family": "Qualità dei dati", "kind": "condizione",
     "title": "Dati insufficienti per l'analisi",
     "when": "qualità dei dati D2 «insufficiente» o completezza dei bilanci «Insufficiente»; segnalata una volta e "
             "seguita come problema persistente finché non si risolve",
     "priority": "ordinaria"},
    {"id": "ETF-E2-STATO", "scope": "etf", "family": "Scanner ETF", "kind": "evento",
     "title": "Stato E2 dell'esposizione cambiato",
     "when": "stato E2 diverso tra due sedute ammissibili con la stessa versione, stessa esposizione e stessa modalità",
     "priority": "importante se il nuovo stato è «Rischio elevato» o «Dati insufficienti»; altrimenti ordinaria; "
                 "stati di trend: solo esplorativi"},
    {"id": "ETF-D2-STATO", "scope": "etf", "family": "Decision Desk", "kind": "evento",
     "title": "Stato D2 dell'ETF cambiato",
     "when": "stato D2 di una riga ETF diverso tra due sedute ammissibili con la stessa versione",
     "priority": "come AZ-D2-STATO; «Monitora — trend esplorativo» resta esplorativo"},
    {"id": "ETF-TREND", "scope": "etf", "family": "Scanner ETF", "kind": "evento",
     "title": "Trend esplorativo cambiato",
     "when": f"trend della serie di riferimento diverso e confermato per {TREND_CONFIRM} sedute di fila (isteresi): "
             "trend non validato, solo esplorativo",
     "priority": "ordinaria"},
    {"id": "ETF-RISCHIO", "scope": "etf", "family": "Rischio", "kind": "evento",
     "title": "Rischio E2 aumentato",
     "when": "livello di rischio E2 più alto o nuovo segnale di rischio (R1–R6, con le soglie di E2) rispetto alla seduta precedente",
     "priority": "importante se il livello diventa «elevato» o il nuovo segnale è alto; altrimenti ordinaria"},
    {"id": "ETF-CONCENTRAZIONE", "scope": "etf", "family": "Esposizione", "kind": "evento",
     "title": "Concentrazione del fondo cambiata",
     "when": f"peso dei primi 10 titoli cambiato di almeno {CONC_PP:.0f} punti tra due versioni del catalogo",
     "priority": "importante da 10 punti, altrimenti ordinaria"},
    {"id": "ETF-PRODOTTO", "scope": "etf", "family": "Prodotto", "kind": "evento",
     "title": "Costi o struttura del prodotto cambiati",
     "when": "TER, replica, distribuzione, copertura del cambio, valuta di base, indice, domicilio o nome diversi tra due "
             "versioni del catalogo",
     "priority": "importante"},
    {"id": "ETF-OBBLIGAZIONI", "scope": "etf", "family": "Obbligazioni", "kind": "evento",
     "title": "Duration, rendimento o credito cambiati",
     "when": f"con dati del fondo di una data più recente: duration ±{BOND_DURATION} anni, rendimento a scadenza "
             f"±{BOND_YIELD} punti, quota con rating A o superiore ±{BOND_RATING:.0f} punti o descrizione del credito diversa",
     "priority": "importante per il credito, ordinaria per duration e rendimento"},
    {"id": "ETF-DATI", "scope": "etf", "family": "Qualità dei dati", "kind": "condizione",
     "title": "Dati del fondo obsoleti o insufficienti",
     "when": "dati del catalogo segnati come non aggiornati (TER, patrimonio, composizione, paesi), nessuna quotazione "
             "disponibile o analisi E2 non sufficiente; seguita come problema persistente",
     "priority": "ordinaria"},
    {"id": "OP-SEDUTA", "scope": "operativo", "family": "Aggiornamento", "kind": "condizione",
     "title": "Seduta non registrata",
     "when": "una seduta attesa manca da un diario (diaries_status): nessuna ricostruzione retroattiva",
     "priority": "critica"},
    {"id": "OP-REGISTRO", "scope": "operativo", "family": "Aggiornamento", "kind": "condizione",
     "title": "Registrazione da classificare",
     "when": "una registrazione tardiva non è ancora nel registro delle esclusioni, oppure un diario segnala un errore",
     "priority": "critica"},
    {"id": "OP-VERSIONE", "scope": "operativo", "family": "Metodo", "kind": "evento",
     "title": "Nuova versione del modello: nuova base di partenza",
     "when": "l'ultima seduta ammissibile di un diario ha una versione diversa dalla precedente: cambiamento "
             "metodologico, nessun confronto dei dati",
     "priority": "ordinaria"},
]
RULE = {r["id"]: r for r in RULES}

SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_runs (
  run_id TEXT PRIMARY KEY, generated_at TEXT NOT NULL, engine_version TEXT NOT NULL, source TEXT NOT NULL,
  fingerprint TEXT NOT NULL, inputs TEXT NOT NULL, counts TEXT NOT NULL, status TEXT NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS alert_events (
  alert_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, rule TEXT NOT NULL, scope TEXT NOT NULL, priority TEXT NOT NULL,
  kind TEXT NOT NULL, instrument TEXT NOT NULL, session TEXT, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alert_lifecycle (
  alert_id TEXT NOT NULL, run_id TEXT NOT NULL, status TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (alert_id, run_id));
CREATE TABLE IF NOT EXISTS catalog_snapshots (
  built_at TEXT NOT NULL, isin TEXT NOT NULL, data TEXT NOT NULL, run_id TEXT NOT NULL, PRIMARY KEY (built_at, isin));
"""
for _t in ("alert_runs", "alert_events", "alert_lifecycle", "catalog_snapshots"):
    SCHEMA += (f"CREATE TRIGGER IF NOT EXISTS {_t}_no_update BEFORE UPDATE ON {_t} BEGIN SELECT RAISE(ABORT, "
               f"'il registro degli alert non si modifica'); END;\n"
               f"CREATE TRIGGER IF NOT EXISTS {_t}_no_delete BEFORE DELETE ON {_t} BEGIN SELECT RAISE(ABORT, "
               f"'il registro degli alert non si modifica'); END;\n")


# ---------------------------------------------------------------- helpers

def _j(x, default=None):
    if x is None or x == "":
        return default
    try:
        return json.loads(x)
    except (TypeError, ValueError):
        return default


def _h(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def it(x, d=1):
    return "n.d." if x is None else f"{x:,.{d}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def disabled_rules(path=None):
    """Rules switched off in alert_rules.json ({"disabled": [ids]}): a noisy rule is disabled here, never by changing a
    financial model."""
    try:
        with open(path or RULES_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return sorted({x for x in d.get("disabled", []) if x in RULE})
    except (OSError, ValueError):
        return []


def _norm_text(t):
    return re.sub(r"[\d.,%−+-]+", "#", (t or "").lower()).strip()


# ---------------------------------------------------------------- 1. reading the admissible diary records (read only)

DIARY_TABLES = {"opportunity": ("runs", "observations"), "investment": ("inv_runs", "inv_observations"),
                "valuation": ("val_runs", "val_observations"), "decision": ("dec_runs", "dec_observations"),
                "etf": ("etf_runs", "etf_observations")}


def _ro(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def admissible_runs(con, diary, as_of=None):
    """Official and admissible runs of `diary`, oldest first, up to `as_of` (session date, inclusive): never a later one."""
    import opportunity_diary as od
    runs, _ = DIARY_TABLES[diary]
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (runs,)).fetchone():
        return []
    q = f"SELECT session, model_version, computed_at, source FROM {runs} r WHERE {od._official('r.source', diary)}"
    args = ()
    if as_of:
        q += " AND session <= ?"
        args = (as_of,)
    return [dict(r) for r in con.execute(q + " ORDER BY session, computed_at", args)]


def rows_of(con, diary, run, cols="*"):
    _, obs = DIARY_TABLES[diary]
    return [dict(r) for r in con.execute(f"SELECT {cols} FROM {obs} WHERE session=? AND model_version=?",
                                         (run["session"], run["model_version"]))]


def read_inputs(diary_path, as_of=None):
    """Everything the detection needs, from the admissible records only. Never writes, never downloads."""
    out = {"diaries": {}}
    if not os.path.exists(diary_path):
        return out
    with closing(_ro(diary_path)) as con:
        for d in DIARY_TABLES:
            runs = admissible_runs(con, d, as_of)
            last = runs[-1] if runs else None
            prev = runs[-2] if len(runs) > 1 else None
            x = {"runs": runs, "last": last, "prev": prev, "rows": {}, "prevRows": {}}
            if last:
                x["rows"] = rows_of(con, d, last)
            if prev and prev["model_version"] == last["model_version"]:
                x["prevRows"] = rows_of(con, d, prev)
            if d == "valuation" and last:            # DCF hysteresis: the whole history of the current version
                same = [r for r in runs if r["model_version"] == last["model_version"]]
                x["history"] = [(r["session"], rows_of(con, d, r, "ticker, price, value_prudent, value_base, "
                                                              "value_favourable, status")) for r in same]
            if d == "etf" and last:                  # trend confirmation: the last sessions of the current version
                same = [r for r in runs if r["model_version"] == last["model_version"]][-(TREND_CONFIRM + 1):]
                x["history"] = [(r["session"], rows_of(con, d, r, "exposure, mode, indicators")) for r in same]
            out["diaries"][d] = x
    return out


def comparison(x):
    """baseline / confronto / nuova versione / nessuna seduta, for one diary."""
    if not x or not x.get("last"):
        return "nessuna seduta"
    if not x.get("prev"):
        return "baseline"
    if x["prev"]["model_version"] != x["last"]["model_version"]:
        return "nuova versione"
    return "confronto"


# ---------------------------------------------------------------- 2. detection (pure functions)

def alert(rule, instrument, ident, *, name=None, session=None, observed_at=None, previous=None, current=None, reason="",
          model=None, sources=None, reliability="", limits=None, resolve=None, link=None, priority=None, horizon=None,
          exploratory=False, group=None, extra=None):
    r = RULE[rule]
    return {"id": f"{VERSION}-{_h(rule, instrument, horizon, ident)}", "rule": rule, "title": r["title"], "scope": r["scope"],
            "family": r["family"], "kind": r["kind"], "priority": priority or "ordinaria", "instrument": instrument,
            "name": name or instrument, "horizon": horizon, "session": session, "observedAt": observed_at,
            "previous": previous, "current": current, "reason": reason, "model": model or {}, "sources": sources or [],
            "reliability": reliability, "limits": limits or [], "resolveWhen": resolve, "link": link or {},
            "exploratory": exploratory, "group": group or rule, "extra": extra or {}}


def _meta(x, model):
    last, prev = x["last"], x["prev"]
    return {"session": last["session"], "observed_at": last["computed_at"],
            "model": {"name": model, "version": last["model_version"], "previousSession": prev["session"] if prev else None}}


def _d2_priority(old, new):
    return "importante" if new in RESTRICTIVE or old == "Da approfondire" else "ordinaria"


def detect_decisions(x):
    out = []
    if comparison(x) != "confronto":
        return out
    m = _meta(x, "Decision Desk")
    prev = {(r["kind"], r["instrument"], r["horizon"]): r for r in x["prevRows"]}
    for r in x["rows"]:
        k = (r["kind"], r["instrument"], r["horizon"])
        p = prev.get(k)
        if not p:
            continue
        dates = _j(r["dates"], {}) or {}
        if p["state"] != r["state"]:
            etf = r["kind"] == "etf"
            expl = r["state"] in EXPLORATORY or p["state"] in EXPLORATORY
            out.append(alert("ETF-D2-STATO" if etf else "AZ-D2-STATO", r["instrument"], (m["model"]["previousSession"], m["session"], p["state"], r["state"]),
                             name=r["name"], horizon=r["horizon"], session=m["session"], observed_at=m["observed_at"],
                             previous={"state": p["state"], "rule": p["rule"]}, current={"state": r["state"], "rule": r["rule"]},
                             reason=f"regola {r['rule']}: {r['main'] or ''}".strip(), model=m["model"],
                             sources=[{"name": k2, "date": v} for k2, v in (dates.items() if isinstance(dates, dict) else [])][:8],
                             priority=_d2_priority(p["state"], r["state"]), exploratory=expl,
                             reliability=f"qualità dei dati D2: {r['data_quality'] or 'n.d.'}",
                             limits=["lo stato D2 descrive le condizioni registrate, non è un segnale di acquisto o di vendita"]
                             + (["trend esplorativo non validato: solo da monitorare"] if expl else []),
                             link={"view": "opps", "ticker": None if etf else r["instrument"]},
                             group=f"{'ETF' if etf else 'AZ'}-D2:{m['session']}"))
        if r["kind"] == "azione" and r["horizon"] == "lungo":
            old = {(e.get("src"), _norm_text(e.get("text"))) for e in (_j(p["risks"], []) or []) if e.get("blocking")}
            new = [e for e in (_j(r["risks"], []) or []) if e.get("blocking") and (e.get("src"), _norm_text(e.get("text"))) not in old]
            for e in new:
                out.append(alert("AZ-RISCHIO", r["instrument"], (m["session"], e.get("src"), _norm_text(e.get("text"))),
                                 name=r["name"], horizon=r["horizon"], session=m["session"], observed_at=m["observed_at"],
                                 previous={"text": "assente"}, current={"text": e.get("text"), "source": e.get("src")},
                                 reason="rischio bloccante nuovo nella scheda D2", model=m["model"], priority="importante",
                                 sources=[{"name": e.get("src"), "date": m["session"]}],
                                 limits=["confronto per testo (numeri esclusi): una nuova formulazione dello stesso rischio "
                                         "può apparire come nuova"], link={"view": "opps", "ticker": r["instrument"]}))
    return out


def detect_fundamentals(x):
    out = []
    if comparison(x) != "confronto":
        return out
    m = _meta(x, "Motore fondamentale")
    prev = {r["ticker"]: r for r in x["prevRows"]}
    same_dims = []
    for r in x["rows"]:
        p = prev.get(r["ticker"])
        if not p:
            continue
        dn, dp = _j(r["dims"], {}) or {}, _j(p["dims"], {}) or {}
        tn, tp = _j(r["data_dates"], {}) or {}, _j(p["data_dates"], {}) or {}
        new_period = (tn.get("latestQuarter"), tn.get("latestYear")) != (tp.get("latestQuarter"), tp.get("latestYear")) \
            and bool(tn.get("latestQuarter") or tn.get("latestYear"))
        changed = {k: ((dp.get(k) or {}).get("state"), (dn.get(k) or {}).get("state")) for k in FUND_DIMS
                   if (dp.get(k) or {}).get("state") != (dn.get(k) or {}).get("state")}
        src = [{"name": "bilanci della fonte", "date": tn.get("statements")}, {"name": "trimestre più recente", "date": tn.get("latestQuarter")},
               {"name": "esercizio più recente", "date": tn.get("latestYear")}]
        common = dict(name=r["name"], session=m["session"], observed_at=m["observed_at"], model=m["model"], sources=src,
                      link={"view": "stock", "ticker": r["ticker"]})
        if new_period and changed:
            out.append(alert("AZ-FOND-PERIODO", r["ticker"], (m["session"], tn.get("latestQuarter"), tn.get("latestYear"), sorted(changed.items())),
                             previous={"periodo": f"trimestre {tp.get('latestQuarter')}, esercizio {tp.get('latestYear')}",
                                       **{FUND_DIMS[k]: a for k, (a, b) in changed.items()}},
                             current={"periodo": f"trimestre {tn.get('latestQuarter')}, esercizio {tn.get('latestYear')}",
                                      **{FUND_DIMS[k]: b for k, (a, b) in changed.items()}},
                             reason="nuovo periodo di bilancio nella fonte; " + "; ".join(
                                 f"{FUND_DIMS[k]} da «{a}» a «{b}»" + (f" ({(dn.get(k) or {}).get('reasons', [''])[0]})" if (dn.get(k) or {}).get('reasons') else "")
                                 for k, (a, b) in changed.items()),
                             priority="importante", reliability=f"completezza: {(_j(r['completeness'], {}) or {}).get('state', 'n.d.')}",
                             limits=["giudizi del modello F1 sui bilanci della fonte (Yahoo Finance): non sono una previsione"],
                             resolve=None, **common))
        elif new_period:
            same_dims.append(r["ticker"])
        elif changed and tn.get("statements") != tp.get("statements"):
            out.append(alert("AZ-FOND-RIVISTI", r["ticker"], (m["session"], sorted(changed.items())),
                             previous={FUND_DIMS[k]: a for k, (a, b) in changed.items()},
                             current={FUND_DIMS[k]: b for k, (a, b) in changed.items()},
                             reason="stesso periodo di bilancio, dati della fonte scaricati di nuovo e diversi",
                             limits=["può essere una correzione della fonte: verificare i bilanci"], **common))
        ep, en = (dp.get("expectations") or {}).get("state"), (dn.get("expectations") or {}).get("state")
        if ep != en and ep and en and tn.get("analysts") != tp.get("analysts"):
            out.append(alert("AZ-FOND-STIME", r["ticker"], (m["session"], ep, en), previous={"aspettative": ep}, current={"aspettative": en},
                             reason="; ".join((dn.get("expectations") or {}).get("reasons") or []) or "revisione delle stime",
                             limits=["le stime degli analisti cambiano spesso e non sono previsioni affidabili"],
                             **{**common, "sources": [{"name": "dati degli analisti", "date": tn.get("analysts")}]}))
    if same_dims:
        out.append(alert("AZ-FOND-PERIODO", "gruppo", (m["session"], sorted(same_dims)), name=f"{len(same_dims)} società",
                         session=m["session"], observed_at=m["observed_at"], model=m["model"],
                         current={"società": sorted(same_dims)}, priority="ordinaria",
                         reason="nuovi bilanci nella fonte, giudizi di qualità, crescita e solidità invariati",
                         limits=["avviso raggruppato: nessuna scheda da rivedere per un cambiamento di giudizio"],
                         link={"view": "opps"}, extra={"grouped": True}))
    return out


def _side(price, value, prev_side):
    if not _num(price) or not _num(value) or value <= 0:
        return None
    if price >= value * (1 + DCF_BAND):
        return 1
    if price <= value * (1 - DCF_BAND):
        return -1
    return prev_side                       # inside the band: the side stays the one already confirmed


def dcf_sides(history):
    """Confirmed side of the price for each scenario, session by session, with hysteresis (reproducible from the diary)."""
    conf, seq = {}, []
    for session, rows in history:
        for r in rows:
            for sc, col in (("prudente", "value_prudent"), ("base", "value_base"), ("favorevole", "value_favourable")):
                k = (r["ticker"], sc)
                if r["status"] not in USABLE_DCF:
                    conf[k] = None                  # an unusable valuation breaks the chain: a new side starts afterwards
                    continue
                conf[k] = _side(r["price"], r[col], conf.get(k))
        seq.append((session, dict(conf)))
    return seq


def detect_valuations(x):
    out = []
    if comparison(x) != "confronto":
        return out
    m = _meta(x, "DCF")
    prev = {r["ticker"]: r for r in x["prevRows"]}
    seq = dcf_sides(x.get("history") or [])
    s_now = seq[-1][1] if seq else {}
    s_prev = seq[-2][1] if len(seq) > 1 else {}
    for r in x["rows"]:
        p = prev.get(r["ticker"])
        if not p:
            continue
        tn, tp = _j(r["data_dates"], {}) or {}, _j(p["data_dates"], {}) or {}
        common = dict(name=r["ticker"], session=m["session"], observed_at=m["observed_at"], model=m["model"],
                      sources=[{"name": "prezzo di chiusura", "date": r["price_date"]}, {"name": "bilanci", "date": tn.get("statements")},
                               {"name": "trimestre più recente", "date": tn.get("latestQuarter")}],
                      link={"view": "stock", "ticker": r["ticker"]},
                      limits=["i valori DCF dipendono da ipotesi; superare un valore di scenario non è un ordine di acquisto o vendita"])
        if p["status"] in USABLE_DCF and r["status"] not in USABLE_DCF:
            out.append(alert("AZ-DCF-AFFIDABILITA", r["ticker"], (m["session"], p["status"], r["status"]),
                             previous={"stato": p["status"]}, current={"stato": r["status"], "motivi": (_j(r["blockers"], []) or [])[:3]},
                             reason="la valutazione non è più utilizzabile con i nuovi dati", priority="importante",
                             resolve="stato della valutazione di nuovo adeguata, parziale o sensibile", **common))
            continue
        if p["status"] not in USABLE_DCF or r["status"] not in USABLE_DCF:
            continue
        pb, nb, pp_, np_ = _num(p["value_base"]), _num(r["value_base"]), _num(p["price"]), _num(r["price"])
        if not (pb and nb and pp_ and np_):
            continue
        price_eff = (np_ / pb - pp_ / pb) * 100        # distance change with the old value: the price alone
        value_eff = (np_ / nb - np_ / pb) * 100        # the rest: the new value (statements or assumptions)
        causes = {"prezzo": f"{it(pp_, 2)} → {it(np_, 2)} ({it((np_ / pp_ - 1) * 100)}%), effetto sulla distanza {it(price_eff)} punti",
                  "ipotesi e bilanci": f"valore base {it(pb, 2)} → {it(nb, 2)} ({it((nb / pb - 1) * 100)}%), effetto {it(value_eff)} punti"
                  + (" (bilanci della fonte aggiornati)" if tn.get("statements") != tp.get("statements") else "")}
        crossed = False
        for sc, col in (("base", "value_base"), ("prudente", "value_prudent"), ("favorevole", "value_favourable")):
            a, b = s_prev.get((r["ticker"], sc)), s_now.get((r["ticker"], sc))
            if a is not None and b is not None and a != b:
                crossed = crossed or sc == "base"
                side = "sopra" if b > 0 else "sotto"
                out.append(alert("AZ-DCF-SOGLIA", r["ticker"], (m["session"], sc, a, b),
                                 previous={"lato": "sopra" if a > 0 else "sotto", "prezzo": pp_, f"valore {sc}": _num(p[col])},
                                 current={"lato": side, "prezzo": np_, f"valore {sc}": _num(r[col])},
                                 reason=f"il prezzo è ora {side} il valore dello scenario {sc} (fascia di isteresi {DCF_BAND:.0%})",
                                 priority="importante" if sc == "base" else "ordinaria", extra={"causes": causes, "scenario": sc},
                                 group=f"DCF:{r['ticker']}:{m['session']}", **common))
        dp, dn = math.log(pp_ / pb), math.log(np_ / nb)
        if not crossed and abs(dn - dp) >= DCF_DIST_LOG:
            out.append(alert("AZ-DCF-DISTANZA", r["ticker"], (m["session"], round(dp, 3), round(dn, 3)),
                             previous={"distanza dal valore base": f"{it((pp_ / pb - 1) * 100)}%"},
                             current={"distanza dal valore base": f"{it((np_ / nb - 1) * 100)}%"},
                             reason="distanza dal valore base cambiata molto", extra={"causes": causes},
                             group=f"DCF:{r['ticker']}:{m['session']}", **common))
    return out


def detect_etf(x):
    out = []
    if comparison(x) != "confronto":
        return out
    m = _meta(x, "Scanner ETF")
    prev = {(r["exposure"], r["mode"]): r for r in x["prevRows"]}
    for r in x["rows"]:
        p = prev.get((r["exposure"], r["mode"]))
        if not p:
            continue
        name = f"{r['exposure']} ({r['mode']})"
        common = dict(name=name, horizon=r["mode"], session=m["session"], observed_at=m["observed_at"], model=m["model"],
                      sources=[{"name": "prezzi ETF", "date": (_j(r["indicators"], {}) or {}).get("date")}],
                      link={"view": "opps", "mode": "etf"})
        if p["state"] != r["state"]:
            expl = r["state"] in EXPLORATORY or p["state"] in EXPLORATORY
            out.append(alert("ETF-E2-STATO", r["exposure"], (m["session"], r["mode"], p["state"], r["state"]),
                             previous={"state": p["state"]}, current={"state": r["state"]},
                             reason="; ".join((_j(r["reasons"], []) or [])[:3]), exploratory=expl,
                             priority="importante" if r["state"] in RESTRICTIVE else "ordinaria",
                             limits=["stato dello scanner E2: descrive le condizioni, non indica cosa comprare"]
                             + (["trend non validato: solo esplorativo"] if expl else []),
                             group=f"ETF-E2:{m['session']}", **common))
        rp, rn = _j(p["risk"], {}) or {}, _j(r["risk"], {}) or {}
        order = {"contenuto": 0, "medio": 1, "elevato": 2}
        old_ids = {f["id"] for f in rp.get("flags", [])}
        new_flags = [f for f in rn.get("flags", []) if f["id"] not in old_ids]
        if order.get(rn.get("level"), -1) > order.get(rp.get("level"), -1) or new_flags:
            out.append(alert("ETF-RISCHIO", r["exposure"], (m["session"], r["mode"], rp.get("level"), rn.get("level"), sorted(f["id"] for f in new_flags)),
                             previous={"livello": rp.get("level"), "segnali": sorted(old_ids)},
                             current={"livello": rn.get("level"), "nuovi segnali": [f"{f['id']}: {f['text']}" for f in new_flags]},
                             reason="misure di rischio di E2 (volatilità, perdita massima, concentrazione, paese, cambio) con le soglie di E2",
                             priority="importante" if rn.get("level") == "elevato" or any(f.get("high") for f in new_flags) else "ordinaria",
                             **common))
        if r["mode"] == "lungo":
            bp, bn = _j(p["bond"], {}) or {}, _j(r["bond"], {}) or {}
            dated = any(bn.get(k) and bn.get(k) != bp.get(k) for k in ("durationAsOf", "yieldAsOf", "ratingsAsOf"))
            if bn and bp and dated:
                ch = {}
                for k, lim, lab in (("duration", BOND_DURATION, "duration (anni)"), ("yield", BOND_YIELD, "rendimento a scadenza (%)"),
                                    ("aOrBetter", BOND_RATING, "rating A o superiore (%)")):
                    a, b = _num(bp.get(k)), _num(bn.get(k))
                    if a is not None and b is not None and abs(b - a) >= lim:
                        ch[lab] = (a, b)
                credit = bp.get("credit") != bn.get("credit")
                if credit:
                    ch["credito"] = (bp.get("credit"), bn.get("credit"))
                if ch:
                    out.append(alert("ETF-OBBLIGAZIONI", r["exposure"], (m["session"], sorted((k, str(v)) for k, v in ch.items())),
                                     previous={k: a for k, (a, b) in ch.items()}, current={k: b for k, (a, b) in ch.items()},
                                     reason="dati del fondo di una data più recente", priority="importante" if credit or "rating A o superiore (%)" in ch else "ordinaria",
                                     **{**common, "sources": [{"name": "caratteristiche del fondo", "date": bn.get("durationAsOf")}]}))
    # trend: confirmed for TREND_CONFIRM sessions in a row (hysteresis), exploratory only
    hist = x.get("history") or []
    if len(hist) >= TREND_CONFIRM + 1:
        series = {}
        for session, rows in hist:
            for r in rows:
                series.setdefault((r["exposure"], r["mode"]), []).append((session, (_j(r["indicators"], {}) or {}).get("trend")))
        for (exp, mode), s in series.items():
            vals = [v for _, v in s[-(TREND_CONFIRM + 1):]]
            if len(vals) == TREND_CONFIRM + 1 and None not in vals and len(set(vals[1:])) == 1 and vals[0] != vals[1]:
                out.append(alert("ETF-TREND", exp, (s[-1][0], mode, vals[0], vals[-1]), name=f"{exp} ({mode})", horizon=mode,
                                 session=m["session"], observed_at=m["observed_at"], model=m["model"],
                                 previous={"trend": vals[0]}, current={"trend": vals[-1], "confermato per": f"{TREND_CONFIRM} sedute"},
                                 reason="trend della serie di riferimento cambiato e confermato", exploratory=True,
                                 limits=["trend esplorativo non validato: non è un'indicazione di investimento"],
                                 link={"view": "opps", "mode": "etf"}))
    return out


CATALOG_FIELDS = {"name": "nome", "ter": "TER (%)", "replication": "replica", "distribution": "distribuzione",
                  "hedged": "copertura del cambio", "baseCurrency": "valuta di base", "index": "indice", "domicile": "domicilio"}


def catalog_fingerprint(item):
    """The public catalog fields the alerts compare, for one ETF (stored in the registry: the catalog has no history)."""
    v = lambda d: (d or {}).get("v") if isinstance(d, dict) else d
    ident, fund, costs, ex = item.get("identity") or {}, item.get("fund") or {}, item.get("costs") or {}, item.get("exposure") or {}
    lst = item.get("listings") or []
    return {"name": v(ident.get("name")), "ter": v(costs.get("ter")), "replication": v(fund.get("replication")),
            "distribution": v(fund.get("distribution")), "hedged": v(fund.get("hedged")), "baseCurrency": v(fund.get("baseCurrency")),
            "index": (item.get("classification") or {}).get("indexKey"), "domicile": v(ident.get("domicile")),
            "top10Weight": v(ex.get("top10Weight")), "top10Date": (ex.get("top10Weight") or {}).get("asOf") if isinstance(ex.get("top10Weight"), dict) else None,
            "stale": sorted((item.get("freshness") or {}).get("stale") or []),
            "quotes": any(l.get("quoteAvailable") for l in lst) if lst else None,
            "label": (item.get("classification") or {}).get("label")}


def detect_catalog(cur, prev, built_at, prev_built):
    out = []
    if not prev:
        return out
    for isin, c in cur.items():
        p = prev.get(isin)
        if not p:
            continue
        common = dict(name=c.get("name") or isin, session=built_at[:10], observed_at=built_at,
                      model={"name": "Catalogo ETF", "version": built_at, "previousSession": prev_built},
                      sources=[{"name": "catalogo ETF", "date": built_at}, {"name": "catalogo precedente", "date": prev_built}],
                      link={"view": "etf", "isin": isin})
        diff = {CATALOG_FIELDS[k]: (p.get(k), c.get(k)) for k in CATALOG_FIELDS if p.get(k) != c.get(k) and not (p.get(k) is None or c.get(k) is None)}
        if diff:
            out.append(alert("ETF-PRODOTTO", isin, (built_at, sorted((k, str(v)) for k, v in diff.items())),
                             previous={k: a for k, (a, b) in diff.items()}, current={k: b for k, (a, b) in diff.items()},
                             reason="cambiamento del prodotto (non dell'esposizione né dei prezzi)", priority="importante",
                             limits=["dati dell'emittente o di justETF/Borsa Italiana: verificare sul KID o sul prospetto"], **common))
        a, b = _num(p.get("top10Weight")), _num(c.get("top10Weight"))
        if a is not None and b is not None and abs(b - a) * 100 >= CONC_PP:
            out.append(alert("ETF-CONCENTRAZIONE", isin, (built_at, round(a, 4), round(b, 4)),
                             previous={"peso dei primi 10 titoli": f"{it(a * 100)}%"}, current={"peso dei primi 10 titoli": f"{it(b * 100)}%"},
                             reason=f"composizione del {c.get('top10Date') or 'n.d.'}: cambiamento dell'esposizione, non del prodotto",
                             priority="importante" if abs(b - a) * 100 >= 2 * CONC_PP else "ordinaria", **common))
    return out


def conditions(inputs, cat, status):
    """Active problems (conditions), keyed by (rule, instrument): followed until they disappear."""
    out = []
    dec = inputs["diaries"].get("decision") or {}
    inv = inputs["diaries"].get("investment") or {}
    bad = {}
    for r in dec.get("rows", {}) or []:
        if r["kind"] == "azione" and r["horizon"] == "lungo" and r["data_quality"] == "insufficiente":
            bad.setdefault(r["instrument"], {"name": r["name"], "why": []})["why"].append("qualità dei dati D2 insufficiente")
    for r in inv.get("rows", {}) or []:
        if (_j(r["completeness"], {}) or {}).get("state") == "Insufficiente":
            bad.setdefault(r["ticker"], {"name": r["name"], "why": []})["why"].append("bilanci incompleti per il modello F1")
    sess = (dec.get("last") or inv.get("last") or {}).get("session")
    for t, b in sorted(bad.items()):
        out.append(("AZ-DATI", t, dict(name=b["name"], session=sess, current={"problema": "; ".join(b["why"])},
                                      reason="la società non si può analizzare con affidabilità sufficiente",
                                      resolve="qualità dei dati di nuovo parziale o completa", link={"view": "stock", "ticker": t},
                                      limits=["il problema resta segnalato una sola volta finché non si risolve"])))
    for isin, c in (cat or {}).items():
        why = []
        if c.get("stale"):
            why.append("non aggiornati: " + ", ".join(c["stale"]))
        if c.get("quotes") is False:
            why.append("nessuna quotazione disponibile")
        if why:
            out.append(("ETF-DATI", isin, dict(name=c.get("name") or isin, current={"problema": "; ".join(why)},
                                              reason="dati del fondo obsoleti o mancanti nel catalogo",
                                              resolve="catalogo ricostruito con dati aggiornati", link={"view": "etf", "isin": isin})))
    etf = inputs["diaries"].get("etf") or {}
    for r in etf.get("rows", {}) or []:
        ds_ = _j(r["data_status"], {}) or {}
        if r["mode"] == "lungo" and ds_.get("analysis") and ds_["analysis"] != "sufficiente":
            out.append(("ETF-DATI", f"esposizione:{r['exposure']}", dict(name=r["exposure"], session=etf["last"]["session"],
                        current={"problema": f"analisi E2 {ds_['analysis']} ({ds_.get('conditions', 'n.d.')} condizioni)"},
                        reason="dati insufficienti per l'analisi dell'esposizione", resolve="analisi E2 di nuovo sufficiente",
                        link={"view": "opps", "mode": "etf"})))
    for d in (status or {}).get("diaries", []):
        for s in d.get("missing") or []:
            out.append(("OP-SEDUTA", f"{d['key']}:{s}", dict(name=d["name"], session=s, priority="critica",
                        current={"seduta mancante": s}, reason="seduta non registrata: non verrà ricostruita",
                        resolve="nessuna (una seduta persa resta persa): il problema si chiude quando esce dal controllo",
                        link={"view": "opps"})))
        for er in d.get("errors") or []:
            out.append(("OP-REGISTRO", f"{d['key']}:{_h(er)}", dict(name=d["name"], priority="critica", current={"errore": er},
                        reason="errore del diario", link={"view": "opps"})))
        for i in d.get("late") or []:
            if not i.get("registry"):
                out.append(("OP-REGISTRO", f"{d['key']}:{i['session']}:{i['version']}", dict(
                    name=d["name"], session=i["session"], priority="critica",
                    current={"registrata il": i["computedAt"]},
                    reason="registrazione tardiva non ancora classificata nel registro delle esclusioni",
                    resolve="decisione registrata in diary_exclusions.json", link={"view": "opps"})))
    return out


def detect_versions(inputs):
    out = []
    for d, x in inputs["diaries"].items():
        if comparison(x) == "nuova versione":
            out.append(alert("OP-VERSIONE", d, (x["prev"]["model_version"], x["last"]["model_version"], x["last"]["session"]),
                             name=d, session=x["last"]["session"], observed_at=x["last"]["computed_at"],
                             previous={"versione": x["prev"]["model_version"]}, current={"versione": x["last"]["model_version"]},
                             reason="cambiamento metodologico: i dati non si confrontano tra versioni diverse; da questa seduta "
                                    "riparte la base di partenza", model={"name": d, "version": x["last"]["model_version"]}))
    return out


# ---------------------------------------------------------------- 3. the registry (authorized writer only)

def connect(path=None, source=None):
    """WRITE connection to the alert registry: the gate of app_env (as the diaries). Never used by a read API."""
    p = path or DB
    app_env.check_diary_write(p, source)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    con = sqlite3.connect(p, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _last_run(con):
    r = con.execute("SELECT * FROM alert_runs ORDER BY generated_at DESC, rowid DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def _active_before(con, run_id):
    """Alerts active in the run `run_id`: {(rule, instrument): alert_id}."""
    if not run_id:
        return {}
    rows = con.execute("SELECT e.alert_id, e.rule, e.instrument, e.kind FROM alert_lifecycle l JOIN alert_events e ON "
                       "e.alert_id=l.alert_id WHERE l.run_id=? AND l.status IN ('nuovo','persistente','baseline')", (run_id,))
    return {(r["rule"], r["instrument"], r["kind"]): r["alert_id"] for r in rows}


def fingerprint(inputs, built_at, status_keys, disabled):
    diaries = {d: [(x["last"] or {}).get("session"), (x["last"] or {}).get("model_version"), (x["last"] or {}).get("computed_at"),
                   (x["prev"] or {}).get("session"), (x["prev"] or {}).get("model_version")]
               for d, x in sorted(inputs["diaries"].items())}
    return _h(VERSION, diaries, built_at, sorted(status_keys), disabled)


def generate(now, source, diary_path, catalog=None, status=None, path=None, as_of=None, disabled=None):
    """One check: reads the admissible diary records, the public catalog and the state of the diaries, and records a new
    run ONLY if its inputs differ from every run already recorded (idempotent). Returns a short summary (no personal data)."""
    t0 = time.perf_counter()
    disabled = disabled_rules() if disabled is None else disabled
    inputs = read_inputs(diary_path, as_of)
    items = (catalog or {}).get("items") or {}
    built_at = (catalog or {}).get("builtAt") or ""
    cat = {isin: catalog_fingerprint(it_) for isin, it_ in items.items()} if items else {}
    conds = conditions(inputs, cat, status)
    fp = fingerprint(inputs, built_at, [f"{r}|{i}" for r, i, _ in conds], disabled)
    with closing(connect(path, source)) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            if con.execute("SELECT 1 FROM alert_runs WHERE fingerprint=?", (fp,)).fetchone():
                con.execute("ROLLBACK")
                return {"created": False, "why": "input invariati: nessun nuovo controllo registrato", "fingerprint": fp}
            last = _last_run(con)
            first_run = last is None
            run_id = f"{now:%Y%m%dT%H%M%S}-{fp[:8]}"
            # catalog: stored once per build, compared with the previous build
            prev_built = con.execute("SELECT MAX(built_at) FROM catalog_snapshots WHERE built_at < ?", (built_at,)).fetchone()[0] if built_at else None
            have = con.execute("SELECT 1 FROM catalog_snapshots WHERE built_at=? LIMIT 1", (built_at,)).fetchone() if built_at else True
            if built_at and not have:
                con.executemany("INSERT INTO catalog_snapshots VALUES (?,?,?,?)",
                                [(built_at, isin, json.dumps(c, sort_keys=True, default=str), run_id) for isin, c in cat.items()])
            prev_cat = {r["isin"]: _j(r["data"], {}) for r in con.execute("SELECT isin, data FROM catalog_snapshots WHERE built_at=?", (prev_built,))} if prev_built else {}
            d = inputs["diaries"]
            events = (detect_decisions(d.get("decision")) + detect_fundamentals(d.get("investment")) + detect_valuations(d.get("valuation"))
                      + detect_etf(d.get("etf")) + detect_catalog(cat, prev_cat, built_at, prev_built) + detect_versions(inputs))
            active = _active_before(con, last["run_id"] if last else None)
            cond_alerts = []
            for rule, inst, kw in conds:
                keep = active.get((rule, inst, "condizione"))
                ident = ("episodio", keep) if keep else ("episodio", (kw.get("session") or f"{now:%Y-%m-%d}"))
                a = alert(rule, inst, ident, observed_at=now.isoformat(timespec="seconds"),
                          model={"name": "controlli di qualità", "version": VERSION}, priority=kw.pop("priority", "ordinaria"), **kw)
                if keep:
                    a["id"] = keep                    # same episode: same alert, never a second identical one
                cond_alerts.append(a)
            names = {r["ticker"]: r["name"] for r in (d.get("investment") or {}).get("rows") or []}
            names.update({r["instrument"]: r["name"] for r in (d.get("decision") or {}).get("rows") or [] if r["kind"] == "azione"})
            for a in events:
                if a["name"] == a["instrument"] and a["instrument"] in names:
                    a["name"] = names[a["instrument"]]
            alerts = [a for a in events + cond_alerts if a["rule"] not in disabled]
            seen = {}
            for a in alerts:                          # deduplication inside the run
                seen.setdefault(a["id"], a)
            alerts = list(seen.values())
            known = {r[0] for r in con.execute("SELECT alert_id FROM alert_events WHERE alert_id IN (%s)" % ",".join("?" * len(alerts)),
                                               [a["id"] for a in alerts])} if alerts else set()
            stamp = now.isoformat(timespec="seconds")
            life = []
            for a in alerts:
                if a["id"] not in known:
                    con.execute("INSERT INTO alert_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (a["id"], run_id, a["rule"], a["scope"], a["priority"], a["kind"], a["instrument"], a.get("session"),
                                 json.dumps(a, ensure_ascii=False, sort_keys=True, default=str), stamp))
                if a["id"] in known or a["id"] in active.values():
                    st = "persistente"
                elif first_run and a["kind"] == "condizione":
                    st = "baseline"                   # the first check: problems already there are the starting point
                else:
                    st = "nuovo"
                life.append((a["id"], run_id, st, stamp))
            cur = {a["id"] for a in alerts}
            for (rule, inst, kind), aid in active.items():
                if aid not in cur:
                    life.append((aid, run_id, "risolto" if kind == "condizione" else "superato", stamp))
            con.executemany("INSERT INTO alert_lifecycle VALUES (?,?,?,?)", life)
            counts = {"alerts": len(alerts), "new": sum(1 for x in life if x[2] == "nuovo"),
                      "resolved": sum(1 for x in life if x[2] == "risolto"), "baseline": sum(1 for x in life if x[2] == "baseline")}
            inp = {"engine": VERSION, "disabled": disabled, "catalog": {"builtAt": built_at, "previous": prev_built},
                   "diaries": {k: {"comparison": comparison(x), "last": {k2: (x["last"] or {}).get(k2) for k2 in ("session", "model_version", "computed_at")} if x.get("last") else None,
                                   "previous": {k2: (x["prev"] or {}).get(k2) for k2 in ("session", "model_version")} if x.get("prev") else None}
                               for k, x in d.items()}, "asOf": as_of}
            con.execute("INSERT INTO alert_runs VALUES (?,?,?,?,?,?,?,?,?)",
                        (run_id, stamp, VERSION, app_env.check_diary_write(path or DB, source) or source, fp,
                         json.dumps(inp, ensure_ascii=False, default=str), json.dumps(counts), "ok", None))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return {"created": True, "run": run_id, **counts, "ms": round((time.perf_counter() - t0) * 1000, 1)}


# ---------------------------------------------------------------- 4. reading the registry (read only, for the page)

def read(path=None, days=120):
    """The page: last run, alerts with their latest state, counts. mode=ro: never creates or changes anything."""
    p = path or DB
    base = {"version": VERSION, "rules": RULES, "disabled": disabled_rules(), "priorities": PRIORITY,
            "priorityRule": PRIORITY_RULE, "disclaimer": DISCLAIMER}
    if not os.path.exists(p):
        return {**base, "started": False, "alerts": [], "lastRun": None,
                "note": "nessun controllo registrato: il primo avviene dopo il prossimo aggiornamento dei diari"}
    with closing(_ro(p)) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='alert_runs'").fetchone():
            return {**base, "started": False, "alerts": [], "lastRun": None}
        runs = [dict(r) for r in con.execute("SELECT run_id, generated_at, source, inputs, counts FROM alert_runs ORDER BY generated_at, rowid")]
        if not runs:
            return {**base, "started": False, "alerts": [], "lastRun": None}
        last = runs[-1]
        order = {r["run_id"]: i for i, r in enumerate(runs)}
        rows = con.execute("SELECT e.alert_id, e.payload, e.created_at, l.run_id, l.status, l.at FROM alert_events e "
                           "JOIN alert_lifecycle l ON l.alert_id=e.alert_id").fetchall()
    hist = {}
    for r in rows:
        h = hist.setdefault(r["alert_id"], {"payload": r["payload"], "firstSeen": r["created_at"], "states": []})
        h["states"].append((order.get(r["run_id"], -1), r["status"], r["at"]))
    out = []
    cutoff = runs[-1]["generated_at"][:10]
    for aid, h in hist.items():
        states = sorted(h["states"])
        st = states[-1]
        a = _j(h["payload"], {})
        cur = st[0] == order[last["run_id"]]
        status = st[1] if cur else ("superato" if st[1] in ("nuovo", "persistente") and a.get("kind") == "evento" else st[1])
        if not cur and status in ("risolto", "superato") and st[2][:10] < _days_before(cutoff, days):
            continue
        a.update(status=status, current=a.get("current"), firstSeen=h["firstSeen"], lastSeen=st[2], active=cur and status != "risolto"
                 and status != "superato", history=[{"status": s, "at": at} for _, s, at in states][-6:])
        out.append(a)
    prio = {"critica": 0, "importante": 1, "ordinaria": 2}
    out.sort(key=lambda a: (not a["active"], a["status"] != "nuovo", prio.get(a["priority"], 3), a.get("session") or "", a["name"]))
    act = [a for a in out if a["active"]]
    counts = {"new": sum(1 for a in act if a["status"] == "nuovo"), "important": sum(1 for a in act if a["priority"] == "importante"),
              "critical": sum(1 for a in act if a["priority"] == "critica"), "stocks": sum(1 for a in act if a["scope"] == "azione"),
              "etf": sum(1 for a in act if a["scope"] == "etf"), "quality": sum(1 for a in act if a["family"] == "Qualità dei dati"),
              "operational": sum(1 for a in act if a["scope"] == "operativo"), "active": len(act)}
    return {**base, "started": True, "lastRun": {"id": last["run_id"], "at": last["generated_at"], "source": last["source"],
            "inputs": _j(last["inputs"], {}), "counts": _j(last["counts"], {})}, "runs": len(runs), "counts": counts, "alerts": out}


def _days_before(day, n):
    from datetime import date, timedelta
    return (date.fromisoformat(day) - timedelta(days=n)).isoformat()
