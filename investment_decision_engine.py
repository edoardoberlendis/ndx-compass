"""Investment Decision Desk (phase 7A): one place that READS the results of the existing engines and says where to look.

It never recomputes or replaces an engine: the Trading conditions T1–T5 and the Pagella (opportunity_scanner), the
fundamental engine F1 (investment_engine), the valuation V2 (investment_valuation) and the ETF model E2
(etf_opportunity) are taken as they are. From their results it builds, for every stock and every ETF exposure and for
each horizon, a decision STATE chosen by explicit rules (RULES below, shown in the page), with the evidence for and
against, the risks, what would change the judgement, the dates of the data used and the state of validation.

What it never does: a total score, an expected return, a probability, "Compra"/"Vendi", a price at which to buy, a
download, a read of the personal portfolio. The order of the rows is declared and is not a forecast. When nothing is
convincing it says so: no ranking has to be filled.

Inputs (all already in memory in the server, see server.decision_snapshot):
    snap = {"asOf": iso timestamp of the snapshot, "session": last closed NYSE session,
            "opportunities": opportunity_scanner.scan(..., keep_all=True), "investment": investment_engine.analyze_all(...),
            "valuation": investment_valuation result, "etf": {"lungo": etf_opportunity.scan(...), "breve": ...},
            "catalog": etf catalog (for the freshness of the fund data)}
Any part may be missing: the rows that depend on it become "Dati insufficienti" with the reason.
"""
from __future__ import annotations

from datetime import date, datetime

VERSION = "D1"
DISCLAIMER = ("Decision Desk: screening esplorativo, non consulenza finanziaria. Riassume i motori esistenti senza "
              "prevedere rendimenti: nessuna probabilità, nessuna indicazione di acquisto o vendita, nessun prezzo di ingresso. "
              "Nessuno dei giudizi è validato sul passato.")

S_DEEP, S_WAIT, S_MON, S_MIX, S_RISK, S_NODATA, S_NONE = (
    "Da approfondire", "Attendi condizioni migliori", "Monitora", "Condizioni contrastanti", "Rischio elevato",
    "Dati insufficienti", "Nessuna opportunità convincente")
STATES = [S_DEEP, S_WAIT, S_MON, S_MIX, S_RISK, S_NODATA, S_NONE]
HORIZONS = {"lungo": "Medio-lungo periodo (3–24 mesi o più)", "breve": "Breve periodo (3–30 sedute)"}
KINDS = {"azione": "Azione", "etf": "ETF (esposizione)"}

# Every state comes from one of these rules, checked in this order for each kind of row. Shown in the page.
RULES = {
    # stocks, medium-long term (F1 + V2, Pagella only as context)
    "A-D1": "Dati insufficienti: manca l'analisi fondamentale, la completezza è «Insufficiente», almeno 2 dimensioni "
            "fondamentali non sono valutabili, manca il prezzo oppure un dato è successivo al momento dell'analisi",
    "A-R1": "Rischio elevato: solidità finanziaria «Fragile» (nessun fattore positivo la compensa)",
    "A-R2": "Rischio elevato: qualità «Debole» con ricavi «In calo»",
    "A-A1": "Da approfondire: qualità «Elevata» o «Buona», crescita «Forte» o «Positiva», solidità «Solida» o "
            "«Adeguata», stime non in peggioramento, trend non «Debole», DCF V2 calcolato (adeguato o con limitazioni) "
            "con il prezzo non sopra lo scenario base, e nessuna evidenza contraria (dati in ritardo, prezzi di sedute "
            "diverse, valuta o paese fuori dal modello, criticità della valutazione)",
    "A-W1": "Attendi condizioni migliori: fondamentali favorevoli (qualità, crescita, solidità, stime come in A-A1) ma "
            "prezzo sopra lo scenario base del DCF V2, oppure valutazione «Impegnativa» rispetto ai comparabili",
    "A-C1": "Condizioni contrastanti: almeno un'evidenza favorevole e almeno una contraria",
    "A-M1": "Monitora: evidenze favorevoli senza contrarie, ma insufficienti per A-A1 (DCF non calcolabile, dimensioni "
            "parziali)",
    "A-N1": "Nessuna opportunità convincente: nessuna delle regole precedenti",
    # stocks, short term (T1–T5 tested without advantage: never above "Monitora")
    "B-D1": "Dati insufficienti: condizioni Trading non valutabili (storico corto o prezzi fermi)",
    "B-R1": "Rischio elevato: almeno 4 condizioni Trading su 5 ma volatilità alta (ATR 14 oltre la soglia del motore "
            "Trading): il rischio non è compensato dalle condizioni favorevoli",
    "B-C1": "Condizioni contrastanti: almeno 4 condizioni Trading su 5 ma con avvisi (tirato, sotto la media 200, "
            "trimestrale vicina, pattern bocciato) o «più forte di QQQ ma in calo»",
    "B-M1": "Monitora: almeno 4 condizioni Trading su 5 senza avvisi. Massimo stato possibile nel breve periodo: le "
            "regole T1–T5 non hanno mostrato vantaggi nei test (Fasi O3–4B)",
    "B-N1": "Nessuna opportunità convincente: meno di 4 condizioni Trading su 5",
    # ETF exposures, medium-long term (E2 lungo)
    "E-D1": "Dati insufficienti: stato E2 «Dati insufficienti», scanner ETF non disponibile o dato successivo all'analisi",
    "E-R1": "Rischio elevato: stato E2 «Rischio elevato» (soglie di rischio o duration/emittente per le obbligazioni)",
    "E-A1": "Da approfondire: stato E2 «Esposizione da approfondire», almeno un ETF documentato (TER noto e non "
            "discordante, patrimonio e scambi non sotto le soglie Q2 e Q4), date di ETF e benchmark allineate, dati del "
            "fondo non datati secondo le regole del catalogo",
    "E-C2": "Condizioni contrastanti: esposizione «da approfondire» per E2 ma nessun ETF documentato (TER discordante o "
            "mancante, patrimonio o scambi sotto le soglie)",
    "E-M2": "Monitora: esposizione «da approfondire» per E2 ma date non allineate o dati del fondo datati",
    "E-M1": "Monitora: stato E2 «Trend favorevole da monitorare»",
    "E-C1": "Condizioni contrastanti: stato E2 «Condizioni contrastanti»",
    "E-N2": "Nessuna opportunità convincente: obbligazioni con stato E2 «Da approfondire — evidenza insufficiente». "
            "Qualità del credito (O2) e costi (O3) descrivono il prodotto, non la convenienza dell'esposizione: non sono "
            "un segnale favorevole e non vengono promossi",
    "E-N1": "Nessuna opportunità convincente: stato E2 «Nessuna opportunità convincente»",
    # ETF exposures, short term (E2 breve, equities only; never above "Monitora")
    "F-D1": "Dati insufficienti: stato E2 breve «Dati insufficienti»",
    "F-R1": "Rischio elevato: stato E2 breve «Rischio elevato»",
    "F-M1": "Monitora: stato E2 breve favorevole («Esposizione da approfondire» o «Trend favorevole»). Massimo stato "
            "possibile nel breve: il momentum sulle categorie di ETF non ha superato il test (Fase 24)",
    "F-C1": "Condizioni contrastanti: stato E2 breve «Condizioni contrastanti»",
    "F-N1": "Nessuna opportunità convincente: stato E2 breve «Nessuna opportunità convincente»",
}
ORDER_RULE = ("Ordine dichiarato, non una previsione: prima lo stato (nell'ordine della legenda), poi i dati più completi, "
              "poi meno rischi bloccanti, poi meno evidenze contrarie, poi più evidenze favorevoli, infine il nome. Mai i "
              "rendimenti recenti più alti o lo sconto teorico del DCF più ampio.")
VALIDATION = {
    "azione:lungo": "Esplorativo: motore fondamentale F1 e DCF V2 non sono validati sul passato (con i bilanci di oggi non "
                    "si possono provare); il diario delle decisioni li misura da ora in avanti.",
    "azione:breve": "Regole T1–T5 provate nelle Fasi O3–4B: nessun vantaggio rilevato. Solo ricerca e monitoraggio.",
    "etf:lungo": "Esplorativo: le condizioni di trend dello scanner E2 non sono validate e un test simile sul momentum "
                 "delle categorie di ETF non è stato superato (Fase 24).",
    "bond:lungo": "Modello E2: nessun criterio validato per un giudizio favorevole sulle obbligazioni; il rapporto "
                  "rendimento ÷ duration è solo descrittivo (la soglia O1 del modello E1 non è più usata).",
    "etf:breve": "Esplorativo e non validato: il momentum sulle categorie di ETF non ha superato il test (Fase 24).",
}
GOOD_Q, GOOD_G, GOOD_S = ("Elevata", "Buona"), ("Forte", "Positiva"), ("Solida", "Adeguata")
DIM_LABEL = {"quality": "qualità", "growth": "crescita", "solidity": "solidità", "valuation": "valutazione",
             "expectations": "stime degli analisti", "trend": "trend strutturale"}
NEGATIVE = {"Debole", "In calo", "Da verificare", "Fragile", "Impegnativa", "In peggioramento"}
V2_COMPUTED = ("adeguata", "parziale", "sensibile")
E2_INS = "Da approfondire — evidenza insufficiente per un giudizio favorevole"
FORBIDDEN = (r"\bcompra\b", r"\bvendi\b", r"probabilità (di|del) (guadagno|successo|rialzo)", r"rendimento atteso",
             r"prezzo obiettivo", r"target price", r"\bbuy\b", r"\bsell\b")


# ---------------------------------------------------------------- small helpers

def ev(text, dim, src):
    """One piece of evidence: text from a measured value, the dimension and the engine that produced it."""
    return {"text": text, "dim": dim, "src": src}


def risk(text, src, blocking=False):
    return {"text": text, "src": src, "blocking": bool(blocking)}


def _d(x):
    """'YYYY-MM-DD' of a date or ISO timestamp, None if missing."""
    return str(x)[:10] if x else None


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _it(x, d=1):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".") if _num(x) else "n.d."


def future_dates(dates, as_of):
    """Dates later than the snapshot day: information the analysis could not have had (never used)."""
    day = _d(as_of)
    return sorted({k for k, v in (dates or {}).items() if v and day and _d(v) > day})


def quality_level(core_missing, partial, notes=()):
    if core_missing:
        return "insufficiente"
    return "parziale" if partial or notes else "completa"


# ---------------------------------------------------------------- stocks, medium-long term

def stock_long(tk, inv, val, pag, opp_entry, session, as_of):
    """Decision row of one stock, horizon 3–24 months, from F1 (inv), V2 (val) and the Pagella (context only)."""
    name = (inv or val or opp_entry or {}).get("name") or tk
    fav, con, risks, change, missing, notes = [], [], [], [], [], []
    dates = {}
    if inv:
        dates.update(price=inv.get("priceDate"), statements=_d((inv.get("dataDates") or {}).get("statements")),
                     analysts=(inv.get("dataDates") or {}).get("analysts"),
                     latestQuarter=(inv.get("dataDates") or {}).get("latestQuarter"))
    if val:
        vd = val.get("dataDates") or {}
        dates.update(valuationPrices=vd.get("prices"), latestYear=vd.get("latestYear"),
                     latestQuarterAnnounced=vd.get("latestQuarterAnnounced"))
    row = base_row("azione", tk, name, tk, "lungo", session, as_of)
    row["links"] = {"stock": tk, "investment": tk if inv else None, "valuation": tk if val else None}
    if not inv:
        return finish(row, S_NODATA, "A-D1", [], [], [], [], ["analisi fondamentale (F1) non disponibile per il titolo"],
                      dates, "insufficiente", ["analisi fondamentale non disponibile"])
    fut = future_dates(dates, as_of)
    d = {k: (v or {}).get("state") for k, v in (inv.get("dims") or {}).items()}
    reasons = {k: ((v or {}).get("reasons") or [None])[0] for k, v in (inv.get("dims") or {}).items()}
    comp = inv.get("completeness") or {}
    core_na = [k for k in ("quality", "growth", "solidity", "valuation")
               if d.get(k) in (None, "Non valutabile", "Non confrontabile")]
    for k in core_na:
        missing.append(f"{DIM_LABEL[k]} non valutabile con i dati disponibili")
    missing += [m if isinstance(m, str) else str(m) for m in (inv.get("missing") or [])][:6]

    # evidence from F1 (each from the engine's own state and its first reason)
    for k in ("quality", "growth", "solidity", "expectations", "valuation", "trend"):
        s = d.get(k)
        if not s:
            continue
        why = f" ({reasons[k]})" if reasons.get(k) else ""
        if s in ("Elevata", "Buona", "Forte", "Positiva", "Solida", "Adeguata", "In miglioramento", "Contenuta", "Favorevole"):
            fav.append(ev(f"{DIM_LABEL[k]} «{s}»{why}", k, "F1"))
        elif s in NEGATIVE:
            con.append(ev(f"{DIM_LABEL[k]} «{s}»{why}", k, "F1"))
    # Pagella (approved, unchanged): context only, never decides the state
    if pag and pag.get("n"):
        notes.append(f"Pagella: {pag['ok']} controlli su {pag['n']} ({pag.get('status') or 'n.d.'}) — mostrata, non usata nella regola")
    # V2
    v_status, pos = (val or {}).get("status"), ((val or {}).get("position") or {}).get("id")
    disp = (val or {}).get("display") or ((val or {}).get("range") or {}).get("display")
    cur = ((val or {}).get("currency") or inv.get("currency") or {})
    unit = cur.get("price") or "USD"
    if not val:
        missing.append("valutazione DCF V2 non disponibile")
    elif v_status not in V2_COMPUTED:
        missing.append(f"DCF V2: {val.get('statusLabel') or v_status}" + (f" ({val['reasons'][0]})" if val.get("reasons") else ""))
    else:
        txt = (val.get("position") or {}).get("label") or "posizione del prezzo non calcolabile"
        sc = f" (prudente ~{_it(disp[0], 0)}, base ~{_it(disp[1], 0)}, favorevole ~{_it(disp[2], 0)} {unit})" if disp and len(disp) == 3 else ""
        if pos in ("sotto_prudente", "prudente_base"):
            fav.append(ev(f"DCF V2: {txt.lower()}{sc}", "valuation", "V2"))
        elif pos in ("base_favorevole", "sopra_favorevole"):
            con.append(ev(f"DCF V2: {txt.lower()}{sc}", "valuation", "V2"))
        if v_status == "sensibile":
            con.append(ev("DCF V2 molto sensibile alle ipotesi: " + "; ".join((val.get("reasons") or [])[:2]), "valuation", "V2"))
        for b in (val.get("blockers") or [])[:2]:
            con.append(ev(f"criticità della valutazione: {b}", "valuation", "V2"))
        for lv in (val.get("levels") or [])[:2]:
            change.append({"dir": "migliora", "text": lv["text"], "src": "V2"})
    # dates and data coherence (part G)
    lag = inv.get("lagging") or (val or {}).get("lagging")
    if lag:
        con.append(ev(f"prezzi del titolo fermi al {lag}: dati non allineati all'ultima seduta {session}", "dati", "F1"))
    if dates.get("price") and session and dates["price"] != session and not lag:
        con.append(ev(f"prezzo dell'analisi del {dates['price']}, ultima seduta {session}: sedute diverse", "dati", "F1"))
    if dates.get("analysts") and session and dates["analysts"] < session:
        con.append(ev(f"stime degli analisti del {dates['analysts']}, non aggiornate all'ultima seduta {session}", "dati", "F1"))
    acc = (inv.get("currency") or {}).get("accounts") or cur.get("accounts")
    if acc and acc != "USD":
        con.append(ev(f"bilanci in {acc}, prezzo in {unit}: cambio e rischio paese non sono rappresentati dal modello "
                      "(stesso tasso di sconto delle società USA)", "dati", "F1/V2"))
    for i in (inv.get("dataIssues") or [])[:2]:
        notes.append(f"dato da verificare: {i if isinstance(i, str) else i.get('text', i)}")

    # risks
    if d.get("solidity") == "Fragile":
        risks.append(risk(f"solidità finanziaria «Fragile» ({reasons.get('solidity') or 'debito elevato'})", "F1", True))
    if d.get("quality") == "Debole" and d.get("growth") == "In calo":
        risks.append(risk("qualità «Debole» con ricavi «In calo»", "F1", True))
    for r in ((val or {}).get("risks") or [])[:3]:
        risks.append(risk(r, "V2"))
    for w in (inv.get("weaknesses") or [])[:2]:
        if not any(w == r["text"] for r in risks):
            risks.append(risk(w, "F1"))

    # what would change the judgement (measurable, from the engines)
    for m in ((val or {}).get("monitor") or [])[:3]:
        change.append({"dir": "verifica", "text": m, "src": "V2"})
    for m in (inv.get("monitor") or [])[:2]:
        if not any(m == c["text"] for c in change):
            change.append({"dir": "verifica", "text": m, "src": "F1"})
    for k, good, bad in (("quality", GOOD_Q, ("Modesta", "Debole")), ("growth", GOOD_G, ("Modesta", "In calo")),
                         ("solidity", GOOD_S, ("Da verificare", "Fragile"))):
        s = d.get(k)
        if s in good:
            change.append({"dir": "peggiora", "text": f"{DIM_LABEL[k]} da «{s}» a «{bad[0]}» o «{bad[1]}» con i prossimi bilanci", "src": "F1"})
        elif s in bad:
            change.append({"dir": "migliora", "text": f"{DIM_LABEL[k]} da «{s}» a «{good[1]}» o «{good[0]}» con i prossimi bilanci", "src": "F1"})
    if d.get("expectations") != "In peggioramento":
        change.append({"dir": "peggiora", "text": "stime di utile tagliate (stato «In peggioramento»: −3% in 90 giorni)", "src": "F1"})

    # state (rules in RULES, in order)
    comp_state = comp.get("state")
    good_core = d.get("quality") in GOOD_Q and d.get("growth") in GOOD_G and d.get("solidity") in GOOD_S \
        and d.get("expectations") != "In peggioramento"
    if fut:
        state, rule = S_NODATA, "A-D1"
        missing.append("dati successivi al momento dell'analisi: " + ", ".join(fut))
    elif comp_state == "Insufficiente" or len(core_na) >= 2 or not _num((val or {}).get("price", {}).get("value") if val else inv.get("price")):
        state, rule = S_NODATA, "A-D1"
    elif d.get("solidity") == "Fragile":
        state, rule = S_RISK, "A-R1"
    elif d.get("quality") == "Debole" and d.get("growth") == "In calo":
        state, rule = S_RISK, "A-R2"
    elif good_core and d.get("trend") != "Debole" and v_status in ("adeguata", "parziale") \
            and pos in ("sotto_prudente", "prudente_base") and not con:
        state, rule = S_DEEP, "A-A1"
    elif good_core and ((v_status in V2_COMPUTED and pos in ("base_favorevole", "sopra_favorevole"))
                        or (v_status not in V2_COMPUTED and d.get("valuation") == "Impegnativa")):
        state, rule = S_WAIT, "A-W1"
    elif fav and con:
        state, rule = S_MIX, "A-C1"
    elif fav and good_core:
        state, rule = S_MON, "A-M1"
    else:
        state, rule = S_NONE, "A-N1"
    level = "insufficiente" if state == S_NODATA else quality_level(core_na, comp_state == "Parziale", [c for c in con if c["dim"] == "dati"])
    return finish(row, state, rule, fav, con, risks, change, missing, dates, level, notes,
                  context={"profile": (inv.get("profile") or {}).get("label"), "view": inv.get("view"),
                           "valuation": (val or {}).get("statusLabel"), "pagella": pag, "currency": cur})


# ---------------------------------------------------------------- stocks, short term

def stock_short(e, market, minimum, session, as_of):
    """Decision row of one stock, horizon 3–30 sessions, from the Trading entry of opportunity_scanner (T1–T5)."""
    tk = e["ticker"]
    row = base_row("azione", tk, e.get("name") or tk, tk, "breve", session, as_of)
    row["links"] = {"stock": tk}
    fav, con, risks, change, missing, notes = [], [], [], [], [], []
    dates = {"price": e.get("closeDate")}
    for c in e.get("conditions") or []:
        txt = f"{c['id']} {c['name']}" + (f" ({c['detail']})" if c.get("detail") else "")
        if c.get("state") == "ok":
            fav.append(ev(txt, "trend", "T1–T5"))
            change.append({"dir": "peggiora", "text": f"{c['id']} {c['name'].lower()} non più soddisfatta", "src": "T1–T5"})
        elif c.get("state") in ("ko", "no"):
            change.append({"dir": "migliora", "text": f"{c['id']} {c['name'].lower()} soddisfatta", "src": "T1–T5"})
        else:
            missing.append(f"{c['id']} {c['name']}: non valutabile")
    for w in e.get("warnings") or []:
        (risks if w["id"] in ("vol", "earn") else con).append(
            risk(w["text"], "Trading", w["id"] == "vol") if w["id"] in ("vol", "earn") else ev(w["text"], "rischio", "Trading"))
    diag = e.get("diag") or {}
    if diag.get("flag"):
        con.append(ev(str(diag["flag"]), "trend", "Trading"))
    m = e.get("metrics") or {}
    if market:
        notes.append(f"contesto: QQQ {_it(market.get('qqq1m'))}% a 1 mese, trend «{market.get('qqqTrend') or 'n.d.'}», "
                     f"{_it(market.get('above200'), 0)}% dei titoli sopra la media 200 (al {market.get('date')})")
    if _num(m.get("atrPct")):
        notes.append(f"oscillazione media giornaliera (ATR 14) {_it(m['atrPct'])}% del prezzo")
    fut = future_dates(dates, as_of)
    ok, n = e.get("ok") or 0, e.get("n") or 5
    vol = any(w["id"] == "vol" for w in e.get("warnings") or [])
    if fut or e.get("status") == "Dati insufficienti":
        state, rule = S_NODATA, "B-D1"
        if fut:
            missing.append("dati successivi al momento dell'analisi: " + ", ".join(fut))
    elif ok >= minimum and vol:
        state, rule = S_RISK, "B-R1"
    elif ok >= minimum and con:
        state, rule = S_MIX, "B-C1"
    elif ok >= minimum:
        state, rule = S_MON, "B-M1"
    else:
        state, rule = S_NONE, "B-N1"
        fav = fav if ok else []
    level = "insufficiente" if state == S_NODATA else quality_level([], bool(missing))
    return finish(row, state, rule, fav, con, risks, change, missing, dates, level, notes,
                  context={"ok": ok, "n": n, "trend": e.get("trend"), "main": e.get("main")})


# ---------------------------------------------------------------- ETF exposures

def product_view(o, catalog):
    """Quality of the products of an exposure, kept APART from the judgement on the exposure."""
    P = o.get("products") or {}
    items = (catalog or {}).get("items") or {}
    out, documented, con, notes = [], [], [], []
    for p in P.get("products") or []:
        ck = {c["id"]: c["ok"] for c in p.get("checks") or []}
        tk = (p.get("tickers") or [p["isin"]])[0]
        unresolved = p.get("ter") is None or p.get("terResolution") == "non risolto"
        doc = not unresolved and ck.get("Q2") is not False and ck.get("Q4") is not False
        if doc:
            documented.append(tk)
        if unresolved:
            con.append(ev(f"{tk}: TER discordante tra le fonti o non disponibile (non risolto: mai il più basso)", "prodotto", "E2 Q1"))
        elif ck.get("Q1") is not True:
            notes.append(f"{tk}: TER {_it(p.get('ter'), 2)}% da fonte «{p.get('terResolution')}», non da un documento dell'emittente")
        if ck.get("Q2") is False or ck.get("Q4") is False:
            con.append(ev(f"{tk}: " + " e ".join(x for x in ("patrimonio sotto 100 milioni" if ck.get("Q2") is False else None,
                                                            "scambi sotto 100.000 € al giorno" if ck.get("Q4") is False else None) if x),
                          "prodotto", "E2 Q2/Q4"))
        if ck.get("Q5") is not True:
            notes.append(f"{tk}: spread non rappresentativo o non aggiornato ({p.get('spread') or 'n.d.'})")
        fr = cat_freshness(items.get(p["isin"]))
        if fr:
            notes.append(f"{tk}: dati del fondo datati ({', '.join(fr)}) secondo le regole del catalogo")
        out.append({"ticker": tk, "isin": p["isin"], "ter": p.get("ter"), "terResolution": p.get("terResolution"),
                    "hedged": p.get("hedged"), "documented": doc, "stale": fr,
                    "checks": {k: v for k, v in ck.items()}})
    return {"products": out, "documented": documented, "verdict": P.get("verdict"),
            "differences": (P.get("differences") or [])[:4], "contrary": con, "notes": notes}


def cat_freshness(e):
    if not e:
        return []
    try:
        import etf_catalog
        return etf_catalog.freshness(e).get("stale") or []
    except Exception:
        return []


def etf_long(o, catalog, session, as_of):
    bond = o.get("kind") == "bond"
    code = o.get("reference") or (o.get("members") or [None])[0]
    row = base_row("etf", o["key"], o["label"], code, "lungo", session, as_of)
    row["family"] = o.get("familyLabel")
    row["links"] = {"etf": o["key"], "compare": (o.get("products") or {}).get("compare")}
    pv = product_view(o, catalog)
    row["product"] = {k: pv[k] for k in ("products", "documented", "verdict", "differences")}
    fav = [ev(("caratteristica del prodotto, non della convenienza dell'esposizione: " if bond else "")
              + f"{c['id']} {c['text']} ({c['value']})", "prodotto" if bond else "trend", "E2") for c in o.get("favourable") or []]
    con = [ev(f"{c['id']} {c['text']} ({c['value']})", "rischio" if bond else "trend", "E2") for c in o.get("contrary") or []]
    missing = [f"{c['id']} {c['text']}: non valutabile" for c in o.get("missing") or []]
    risks = [risk(f["text"], "E2 " + f.get("id", ""), bool(f.get("high"))) for f in (o.get("risk") or {}).get("flags") or []]
    notes = list((o.get("completeness") or {}).get("notes") or [])
    dates = dict(o.get("dates") or {})
    change = [{"dir": "peggiora", "text": t, "src": "E2"} for t in o.get("invalidate") or []]
    change += [{"dir": "migliora", "text": f"{c['id']} {c['text']}", "src": "E2"}
               for c in (o.get("conditions") or {}).get("fav", []) if c.get("ok") is not True]
    misaligned = [n for n in notes if "benchmark aggiornato" in n or "prezzi fermi" in n]
    ref_stale = cat_freshness(((catalog or {}).get("items") or {}).get(code))
    if bond:
        b = o.get("bond") or {}
        ctx = {"yield": b.get("yield"), "duration": b.get("durationUsed", b.get("duration")), "durationKind": b.get("durationKind"),
               "credit": b.get("credit"), "aOrBetter": b.get("aOrBetter"), "hedged": b.get("hedgedText"),
               "ratio": b.get("ratio"), "scenarios": b.get("rateScenarios"), "scenarioNotes": b.get("scenarioNotes")}
        if _num(b.get("yield")) and _num(b.get("duration")) and b["duration"] >= 10:
            con.append(ev(f"rendimento a scadenza {_it(b['yield'], 2)}% ma duration {_it(b['duration'])} anni: con i rendimenti "
                          f"+1 punto il prezzo scende di circa il {_it(b['duration'])}% (approssimazione)", "rischio", "E2"))
        change = [c for c in change if c["dir"] != "migliora"]
        change += [{"dir": "migliora", "text": "nessuna regola del modello E2 rende favorevole un'esposizione obbligazionaria: "
                    "servirebbe un criterio nuovo, giustificato e approvato (nuova versione del modello)", "src": "E2"},
                   {"dir": "verifica", "text": "nuovo dato dell'emittente su duration, rendimento a scadenza o rating", "src": "E2"}]
        if b.get("yieldAsOf"):
            dates["yield"] = b.get("yieldAsOf")
    else:
        m = o.get("measures") or {}
        conc = (o.get("concentration") or {}).get("top10")
        ctx = {"returns": m.get("returns"), "rel": m.get("rel"), "trend": m.get("trend"), "vol12m": m.get("vol12m"),
               "dd12m": m.get("dd12m"), "top10": conc, "role": o.get("role")}
        if _num(conc) and conc >= 50 and fav:
            con.append(ev(f"segnali di trend o forza relativa favorevoli ma concentrazione elevata: primi 10 titoli {_it(conc, 0)}% "
                          "del fondo", "rischio", "E2"))
    if ref_stale:
        notes.append(f"dati del fondo di riferimento datati ({', '.join(ref_stale)}) secondo le regole del catalogo")
    fut = future_dates(dates, as_of)
    st = o.get("state")
    if fut or st == "Dati insufficienti":
        state, rule = S_NODATA, "E-D1"
        if fut:
            missing.append("dati successivi al momento dell'analisi: " + ", ".join(fut))
    elif st == "Rischio elevato":
        state, rule = S_RISK, "E-R1"
    elif st == "Esposizione da approfondire" and not bond:
        if not pv["documented"]:
            state, rule = S_MIX, "E-C2"
            con += pv["contrary"]
        elif misaligned or ref_stale:
            state, rule = S_MON, "E-M2"
        else:
            state, rule = S_DEEP, "E-A1"
    elif st == "Trend favorevole da monitorare":
        state, rule = S_MON, "E-M1"
    elif st == "Condizioni contrastanti":
        state, rule = S_MIX, "E-C1"
    elif st == E2_INS:
        state, rule = S_NONE, "E-N2"
        main = ("evidenza insufficiente per un giudizio favorevole (modello E2): qualità del credito e costi descrivono il "
                "prodotto, non la convenienza dell'esposizione")
        notes.insert(0, "evidenza insufficiente (modello E2): una buona qualità del credito o un TER basso non sono, da "
                        "soli, una ragione per investire oggi")
    else:
        state, rule = S_NONE, "E-N1"
    if rule != "E-C2":
        notes += [c["text"] for c in pv["contrary"]]          # product issues stay visible, apart from the exposure
    notes += pv["notes"]
    level = "insufficiente" if state == S_NODATA else quality_level([], bool(missing), misaligned + ref_stale)
    out = finish(row, state, rule, fav, con, risks, change, missing, dates, level, notes,
                 context=ctx, validation_key="bond:lungo" if bond else "etf:lungo",
                 extra={"e2State": st, "e2Version": o.get("version"), "assetClass": o.get("assetClass")})
    if rule == "E-N2":
        out["main"] = main
    return out


def etf_short(o, catalog, session, as_of):
    code = o.get("reference") or (o.get("members") or [None])[0]
    row = base_row("etf", o["key"], o["label"], code, "breve", session, as_of)
    row["family"] = o.get("familyLabel")
    row["links"] = {"etf": o["key"], "compare": (o.get("products") or {}).get("compare")}
    fav = [ev(f"{c['id']} {c['text']} ({c['value']})", "trend", "E2") for c in o.get("favourable") or []]
    con = [ev(f"{c['id']} {c['text']} ({c['value']})", "trend", "E2") for c in o.get("contrary") or []]
    missing = [f"{c['id']} {c['text']}: non valutabile" for c in o.get("missing") or []]
    risks = [risk(f["text"], "E2 " + f.get("id", ""), bool(f.get("high"))) for f in (o.get("risk") or {}).get("flags") or []]
    notes = list((o.get("completeness") or {}).get("notes") or [])
    dates = dict(o.get("dates") or {})
    change = [{"dir": "peggiora", "text": t, "src": "E2"} for t in o.get("invalidate") or []]
    change += [{"dir": "migliora", "text": f"{c['id']} {c['text']}", "src": "E2"}
               for c in (o.get("conditions") or {}).get("fav", []) if c.get("ok") is not True]
    m = o.get("measures") or {}
    fut = future_dates(dates, as_of)
    st = o.get("state")
    if fut or st == "Dati insufficienti":
        state, rule = S_NODATA, "F-D1"
    elif st == "Rischio elevato":
        state, rule = S_RISK, "F-R1"
    elif st in ("Esposizione da approfondire", "Trend favorevole da monitorare"):
        state, rule = S_MON, "F-M1"
    elif st == "Condizioni contrastanti":
        state, rule = S_MIX, "F-C1"
    else:
        state, rule = S_NONE, "F-N1"
    level = "insufficiente" if state == S_NODATA else quality_level([], bool(missing), notes)
    return finish(row, state, rule, fav, con, risks, change, missing, dates, level, notes,
                  context={"returns": m.get("returns"), "rel": m.get("rel"), "trend": m.get("trend"), "vol1m": m.get("vol1m")},
                  validation_key="etf:breve", extra={"e2State": st, "e2Version": o.get("version")})


# ---------------------------------------------------------------- rows

def base_row(kind, key, name, code, horizon, session, as_of):
    return {"id": f"{kind}:{key}:{horizon}", "kind": kind, "kindLabel": KINDS[kind], "key": key, "name": name, "code": code,
            "horizon": horizon, "horizonLabel": HORIZONS[horizon], "session": session, "analysedAt": as_of}


def finish(row, state, rule, fav, con, risks, change, missing, dates, level, notes, context=None, validation_key=None,
           extra=None):
    blocking = [r for r in risks if r["blocking"]]
    main = (fav[0]["text"] if fav and state in (S_DEEP, S_WAIT, S_MON, S_MIX) else
            blocking[0]["text"] if blocking else
            (con[0]["text"] if con else (missing[0] if missing else (fav[0]["text"] if fav else "nessuna evidenza favorevole"))))
    if state == S_WAIT and con:
        why = next((c for c in con if c["dim"] == "valuation"), con[0])
        main = (fav[0]["text"] if fav else "fondamentali favorevoli") + " — ma " + why["text"]
    main_risk = (blocking[0]["text"] if blocking else risks[0]["text"] if risks else con[0]["text"] if con else
                 "nessun rischio oltre le soglie dei motori")
    vk = validation_key or f"{row['kind']}:{row['horizon']}"
    row.update(state=state, rule=rule, ruleText=RULES[rule], main=main, mainRisk=main_risk, favourable=fav, contrary=con,
               risks=risks, blocking=len(blocking), change=dedupe(change)[:10], missing=dedupe(missing), dates={k: v for k, v in dates.items() if v},
               dataQuality=level, notes=dedupe(notes), validation=VALIDATION[vk], context=context or {})
    row.update(extra or {})
    return row


def dedupe(xs):
    seen, out = set(), []
    for x in xs:
        k = x["text"] if isinstance(x, dict) else x
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


QUALITY_ORDER = {"completa": 0, "parziale": 1, "insufficiente": 2}


def order_key(r):
    """Declared order (ORDER_RULE): never recent returns, never the DCF discount."""
    return (STATES.index(r["state"]), QUALITY_ORDER[r["dataQuality"]], r["blocking"], len(r["contrary"]),
            -len(r["favourable"]), r["name"].lower())


# ---------------------------------------------------------------- whole desk

def decide(snap):
    """All decision rows from one snapshot of the engines' results. Pure: same snapshot, same result."""
    as_of = snap.get("asOf")
    session = snap.get("session")
    opp, inv, val, etf = snap.get("opportunities") or {}, snap.get("investment") or {}, snap.get("valuation") or {}, snap.get("etf") or {}
    catalog = snap.get("catalog")
    rows, not_analysed, sources = [], [], {}
    trading_all = (opp.get("trading") or {}).get("all") or []
    invest_all = {e["ticker"]: e for e in (opp.get("invest") or {}).get("all") or []}
    inv_items = {x["ticker"]: x for x in inv.get("items") or []}
    val_items = {x["ticker"]: x for x in val.get("items") or []}
    tickers = sorted(set(inv_items) | set(val_items) | {e["ticker"] for e in trading_all})
    if opp:
        sources["trading"] = {"model": (opp.get("model") or {}).get("version"), "session": opp.get("asOf"),
                              "note": "T1–T5 e Pagella del motore Opportunità, invariati"}
    if inv:
        sources["fundamentals"] = {"model": (inv.get("model") or {}).get("version"), "dates": inv.get("dataDates")}
    if val:
        sources["valuation"] = {"model": (val.get("model") or {}).get("version"), "dates": val.get("dataDates"),
                                "rates": (val.get("rates") or {}).get("rf", {}).get("date")}
    for tk in tickers:
        e = invest_all.get(tk) or {}
        pag = {"ok": e.get("ok"), "n": e.get("n"), "status": e.get("status")} if e else None
        rows.append(stock_long(tk, inv_items.get(tk), val_items.get(tk), pag, e, session, as_of))
    minimum = (opp.get("trading") or {}).get("min") or 4
    for e in trading_all:
        rows.append(stock_short(e, opp.get("market"), minimum, opp.get("asOf") or session, as_of))
    for mode, fn in (("lungo", etf_long), ("breve", etf_short)):
        r = etf.get(mode)
        if not r:
            not_analysed.append({"what": f"ETF, {HORIZONS[mode].lower()}", "why": "scanner ETF non disponibile (prezzi non in cache)"})
            continue
        sources[f"etf_{mode}"] = {"model": r.get("version"), "session": r.get("session"), "prices": r.get("pricesFetched"),
                                  "catalog": r.get("catalogBuilt")}
        for o in r.get("rows") or []:
            if o.get("state") == "Riferimento di mercato":
                not_analysed.append({"what": o["label"], "why": "riferimento di mercato (mondo o liquidità): non un'opportunità"})
            elif mode == "breve" and o.get("kind") == "bond":
                not_analysed.append({"what": f"{o['label']} (breve periodo)", "why": "obbligazioni: solo informazioni strutturali "
                                     "sul prodotto, nessun segnale di breve periodo"})
            else:
                rows.append(fn(o, catalog, r.get("session"), as_of))
    if not opp:
        not_analysed.append({"what": "Azioni, breve periodo", "why": "classifiche Trading non ancora disponibili (dati in caricamento)"})
    if not inv:
        not_analysed.append({"what": "Azioni, medio-lungo periodo", "why": "analisi fondamentale non disponibile (bilanci non ancora in cache)"})
    rows.sort(key=order_key)
    counts = {h: {k: {s: sum(1 for r in rows if r["horizon"] == h and r["kind"] == k and r["state"] == s) for s in STATES}
                  for k in KINDS} for h in HORIZONS}
    deep = [r for r in rows if r["state"] == S_DEEP]
    return {"version": VERSION, "asOf": as_of, "session": session, "disclaimer": DISCLAIMER, "states": STATES,
            "horizons": HORIZONS, "kinds": KINDS, "rules": RULES, "orderRule": ORDER_RULE, "validation": VALIDATION,
            "sources": sources, "counts": counts, "rows": rows, "notAnalysed": not_analysed,
            "noneText": None if deep else ("Oggi nessuna azione o esposizione ETF soddisfa tutte le condizioni di «Da "
                                           "approfondire»: nessuna opportunità è abbastanza convincente.")}


COMPACT = ("id", "kind", "kindLabel", "key", "name", "code", "horizon", "state", "rule", "main", "mainRisk",
           "dataQuality", "blocking", "session", "analysedAt", "family", "e2State")


def compact(r):
    """A row for the list (the detail is sent when the row is opened)."""
    out = {k: r.get(k) for k in COMPACT}
    out.update(nFav=len(r["favourable"]), nCon=len(r["contrary"]), lastDate=max(r["dates"].values()) if r["dates"] else r["session"])
    return out


def page(result):
    out = {k: v for k, v in result.items() if k != "rows"}
    out["rows"] = [compact(r) for r in result["rows"]]
    return out


def detail(result, rid):
    return next((r for r in result["rows"] if r["id"] == rid), None)


def text_of(result):
    """Every judgement the desk shows (rows: states, reasons, evidence, risks, conditions), for the tests on forbidden
    words. The disclaimer, which says what the desk never does, is left out."""
    import json
    return json.dumps(result.get("rows", result), ensure_ascii=False).lower()


def check_no_forbidden(result):
    """None or the forbidden word found: the desk never says buy/sell, never gives a probability or an expected return."""
    import re
    t = text_of(result)
    return next((w for w in FORBIDDEN if re.search(w, t)), None)


def as_of_now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _today():
    return date.today().isoformat()
