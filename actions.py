"""Proposed level for each position I own (phase 26, rules approved by the user on 4 November 2026).

Since phase 26 the levels use ONLY the analysis of the stock, as when I decide whether to buy: nothing written or
chosen by me (the thesis was removed; portafoglio/tesi.json is no longer read and never deleted). The inputs are the
"Pagella del titolo" (pillars.py), the market verdict of the "Decisione" section or of "Ha senso comprare?"
(server.position_market), the automatic stop (stop_auto.py) and the news of the last days.

Four levels, the first that applies wins: Valuta la vendita > Attenzione > Accumula > Mantieni. Every level shows
the rules with their numbers, what to do and when it goes away. These are rules of discipline: NONE of them is
verified by a backtest, and the page says so; the positions diary (pos_diary.py) measures them.

A check of the pagella that cannot be computed ("?") never counts as fallen and never counts as true.
Ids removed and never reused: R1, R2, A3 (phase 21), V1-V11 and A1-A6 (the rules with the thesis, phase 26).

The indicative tax estimate (next to "Valuta la vendita") can use my capital losses carried forward
("zainetto fiscale", portafoglio/fiscale.json) for shares and ETC/ETN, never for ETF gains.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

import portfolio

FISCAL = os.path.join(portfolio.PORTFOLIO_DIR, "fiscale.json")      # {"losses": EUR, "expiry": "AAAA-12-31"}

# thresholds (approved by the user on 4 November 2026)
EPS_CUT = -3.0          # T3: next year's EPS estimate cut by more than 3% in 30 days
LOSS = -25.0            # note only: price more than 25% below the average cost
LEV_DAYS = 30           # S3: leveraged product held for more than 30 days (counted from the first day in the history)
EARNINGS_DAYS = 5       # T5: earnings within 5 days
NEWS_SESSIONS = 10      # T1 and T2: "news" for 10 sessions
MIN_CHECKS = 3          # S2: at least 3 computable checks, otherwise "dati insufficienti"
STOCK_GOOD = 4          # B1: stocks at least 4 checks true out of 6 and none false; ETF and ETC all (2 out of 2)
NEAR_STOP_ATR = 1.0     # T6: price less than 1 ATR above the automatic stop
TAX_RATE = 0.26         # indicative Italian tax on financial gains
GOOD_VERDICTS = ("Entra ora", "Entra su ritracciamento")

SELL, WATCH, ADD, HOLD = "Valuta la vendita", "Attenzione", "Accumula", "Mantieni"
ORDER = [SELL, WATCH, ADD, HOLD]
SHORT = {"S1": "stop automatico rotto", "S2": "pagella: almeno metà dei controlli caduti", "S3": "prodotto a leva tenuto oltre 30 giorni",
         "S4": "verdetto «Evita»", "T1": "controllo appena caduto", "T2": "appena sceso sotto la media a 200 giorni",
         "T3": "stime degli analisti tagliate", "T4": "più downgrade che upgrade", "T5": "trimestrale in arrivo",
         "T6": "prezzo vicino allo stop automatico"}
RULES = [   # id, group, what the rule says (shown in the position's panel)
    ("S1", SELL, "Il prezzo è sceso sotto lo stop automatico"),
    ("S2", SELL, "Pagella: almeno 2 controlli caduti e almeno la metà di quelli valutabili (servono almeno 3 controlli valutabili)"),
    ("S3", SELL, "È un prodotto a leva in portafoglio da più di 30 giorni"),
    ("S4", SELL, "Il verdetto di mercato (sezione Decisione o «Ha senso comprare?») è «Evita»"),
    ("T1", WATCH, "Un controllo della pagella è caduto nelle ultime 10 sedute"),
    ("T2", WATCH, "Il prezzo è sceso sotto la media a 200 giorni nelle ultime 10 sedute"),
    ("T3", WATCH, "Le stime di utile dell'anno prossimo sono state tagliate di oltre il 3% in 30 giorni"),
    ("T4", WATCH, "Negli ultimi 30 giorni ci sono stati più downgrade che upgrade"),
    ("T5", WATCH, "Trimestrale nei prossimi 5 giorni"),
    ("T6", WATCH, "Il prezzo è a meno di 1 ATR sopra lo stop automatico"),
    ("B1", ADD, "Pagella buona: per le azioni almeno 4 controlli ✓ su 6 e nessun ✕; per ETF ed ETC tutti ✓"),
    ("B2", ADD, "Trend di fondo intatto: prezzo sopra la media a 200 giorni e media 50 sopra la media 200"),
    ("B3", ADD, "Verdetto di mercato «Entra ora» o «Entra su ritracciamento»"),
    ("B4", ADD, "Nessuna trimestrale nei prossimi 5 giorni"),
    ("B5", ADD, "Nessun avviso «Valuta la vendita» o «Attenzione»"),
    ("B6", ADD, "Non è un prodotto a leva"),
]
UNTIL = {"S1": "quando il prezzo torna sopra lo stop automatico",
         "S2": "quando i controlli caduti tornano meno della metà di quelli valutabili",
         "S3": "quando vendi il prodotto a leva",
         "S4": "quando il verdetto di mercato non è più «Evita»",
         "T1": "10 sedute dopo la caduta, o prima se il controllo torna vero",
         "T2": "dopo 10 sedute sotto la media a 200 giorni (lo dice poi il controllo «Trend»), o prima se il prezzo torna sopra",
         "T3": "quando la variazione delle stime in 30 giorni torna sopra il −3%",
         "T4": "quando negli ultimi 30 giorni gli upgrade tornano almeno pari ai downgrade",
         "T5": "il giorno dopo la trimestrale",
         "T6": "quando il prezzo si allontana dallo stop di più di 1 ATR (o lo stop si alza)"}
TODO = {SELL: "Guarda pagella e motivi qui sotto e decidi: vendere tutto, una parte, o tenere. È una regola di disciplina, non un ordine.",
        WATCH: "Controlla cosa è cambiato: non serve fare nulla subito.",
        ADD: "Puoi aumentare la posizione, con la quantità dal rischio per operazione delle tue regole (sezione Decisione).",
        HOLD: "Niente da fare."}


def it(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


# ---------------------------------------------------------------- zainetto fiscale and tax estimate

def load_fiscal():
    """My capital losses carried forward (zainetto fiscale): {"losses": EUR or None, "expiry": date or None}."""
    try:
        with open(FISCAL) as f:
            d = json.load(f)
    except Exception:
        d = {}
    v = d.get("losses")
    return {"losses": float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None, "expiry": d.get("expiry") or None}


def save_fiscal(losses, expiry):
    """Save the zainetto fiscale (empty losses = no zainetto). Raises ValueError with an Italian message."""
    if losses in (None, ""):
        losses = None
    elif not isinstance(losses, (int, float)) or isinstance(losses, bool) or losses < 0:
        raise ValueError("Le minusvalenze disponibili devono essere un importo in euro (zero o positivo).")
    if expiry:
        try:
            date.fromisoformat(expiry)
        except (TypeError, ValueError):
            raise ValueError("La scadenza deve essere una data (giorno, mese, anno).")
    os.makedirs(portfolio.PORTFOLIO_DIR, exist_ok=True)
    with open(FISCAL + ".tmp", "w") as f:
        json.dump({"losses": losses or None, "expiry": expiry or None}, f)
    os.replace(FISCAL + ".tmp", FISCAL)
    return load_fiscal()


def tax_estimate(p, sell_value, whole, fiscal=None):
    """Indicative Italian tax effect of selling sell_value EUR of a position (gain or loss in EUR in proportion to the
    part sold, as in Fineco's cost value). For shares and ETC/ETN a gain is first offset with the capital losses carried
    forward (fiscal = load_fiscal()); for ETF (UCITS) gains are capital income and are never offset. Not tax advice."""
    if not p.get("value") or sell_value <= 0:
        return None
    part = min(1.0, sell_value / p["value"])
    gain = (p["value"] - p["cost"]) * part
    kind = p["kind"].upper()
    etf = kind == "ETF"
    basis = "sull'intera posizione" if whole else "sulla quota da vendere"
    losses = (fiscal or {}).get("losses")
    used = 0.0
    if gain > 0:
        if etf:
            tax = gain * TAX_RATE
            how = "per gli ETF UCITS il guadagno è un reddito di capitale: non si compensa con le minusvalenze, nemmeno con quelle dello zainetto"
        elif losses:
            used = min(losses, gain)
            tax = (gain - used) * TAX_RATE
            exp = (fiscal or {}).get("expiry")
            how = (f"reddito diverso: usando {it(used, 0)} € delle minusvalenze del tuo zainetto"
                   + (f" (scadenza più vicina {exp[8:10]}/{exp[5:7]}/{exp[:4]})" if exp else "")
                   + f" l'imposta scende da circa {it(gain * TAX_RATE, 0)} € a circa {it(tax, 0)} €")
        else:
            tax = gain * TAX_RATE
            how = "reddito diverso: se hai minusvalenze nello zainetto, l'imposta reale può essere più bassa"
        text = f"plusvalenza stimata {basis} circa {it(gain, 0)} € → imposta indicativa al 26% circa {it(tax, 0)} € ({how})"
    else:
        tax = 0.0
        how = ("per gli ETF UCITS la perdita è un reddito diverso: compensa plusvalenze di azioni, ETC e derivati nei 4 anni successivi, non i guadagni degli ETF" if etf
               else "reddito diverso: compensa plusvalenze di azioni, ETC e derivati nei 4 anni successivi")
        text = f"minusvalenza stimata {basis} circa {it(-gain, 0)} € → nessuna imposta ({how})"
    return {"gain": gain, "tax": tax, "whole": whole, "etf": etf, "lossesUsed": used, "text": text}


# ---------------------------------------------------------------- rules

def sessions_between(since, today):
    """Weekday sessions from the day after `since` to `today` (holidays are not removed: a small approximation)."""
    import numpy as np
    return int(np.busday_count(date.fromisoformat(since), today + timedelta(days=1))) - 1 if since else 0


def evaluate(pf, ctx):
    """Attach to every position its proposed level:
    p["action"] = {"action", "label", "reasons", "todo", "until", "notes", "tax", "rules": [{"id", "group", "text", "state", "detail"}]}.
    ctx: {"rows": Nasdaq-100 rows by ticker, "analysts": analyst summaries by ticker, "sma200": {ticker: value},
          "below200": {ticker: sessions below}, "firstSeen": {isin: first day in the history},
          "pillars": {isin: pagella}, "market": {isin: market view}, "stops": {isin: automatic stop}}.
    Returns the counts by level."""
    positions = pf.get("positions") or []
    total = (pf.get("totals") or {}).get("value") or 0
    if not positions or not total:
        return {"counts": {}}
    fiscal = load_fiscal()
    today = date.today()
    counts = {a: 0 for a in ORDER}
    order = [r[0] for r in RULES]
    group = {rid: grp for rid, grp, _ in RULES}

    for p in positions:
        lev = (p.get("leverage") or 1) > 1
        fund = p.get("kind") in ("ETF", "ETC")
        price, tk = p["price"], p.get("ticker")
        m = (ctx.get("market") or {}).get(p["isin"]) or {}
        P = (ctx.get("pillars") or {}).get(p["isin"]) or {"list": [], "last": {}}
        st = (ctx.get("stops") or {}).get(p["isin"])
        res, notes = {}, []

        def put(rid, state, detail=""):
            res[rid] = (state, detail)

        # ---- pagella: a "?" never counts as fallen nor as true
        states = [x["state"] for x in P["list"]]
        ok, ko = states.count("ok"), states.count("ko")
        ev = ok + ko
        na_txt = f"; {len(states) - ev} non valutabili, che non contano" if len(states) > ev else ""

        # ---- Valuta la vendita
        if st and st.get("stop") is not None:
            put("S1", "on" if price <= st["stop"] else "off", f"prezzo {it(price, 2)}, stop {it(st['stop'], 2)} (dal {st['since']})")
        else:
            put("S1", "na", (st or {}).get("why") or "livelli del grafico non ancora disponibili per questa posizione")
        if ev < MIN_CHECKS:
            put("S2", "na", f"dati insufficienti: {ev} controlli valutabili su {len(states)} (ne servono almeno {MIN_CHECKS})")
        else:
            put("S2", "on" if ko >= 2 and ko * 2 >= ev else "off", f"{ko} caduti su {ev} valutabili{na_txt}")
        if lev:
            first = (ctx.get("firstSeen") or {}).get(p["isin"])
            days = (today - date.fromisoformat(first)).days if first else 0
            put("S3", "on" if days > LEV_DAYS else "off", f"nello storico da {days} giorni (lo storico parte dal {first or 'oggi'}; il file Fineco non dice quando hai comprato)")
            notes.append("Prodotto a leva: è pensato per periodi brevi e perde valore con il mercato altalenante.")
        else:
            put("S3", "na", "non è un prodotto a leva")
        if m.get("verdict"):
            put("S4", "on" if m["verdict"] == "Evita" else "off", f"«{m.get('label') or m['verdict']}»" + (f": {m['why'][0]}" if m.get("why") else ""))
        else:
            put("S4", "na", "verdetto di mercato non calcolabile oggi")

        # ---- Attenzione
        last = P.get("last") or {}
        fresh = [x["name"] for x in P["list"] if x["state"] == "ko" and (last.get(x["id"]) or {}).get("since")
                 and not last[x["id"]].get("initial") and sessions_between(last[x["id"]]["since"], today) <= NEWS_SESSIONS]
        put("T1", "on" if fresh else "off", ("caduto di recente: " + ", ".join(fresh)) if fresh else "nessun controllo caduto nelle ultime 10 sedute")
        sma = (ctx.get("sma200") or {}).get(tk)
        if sma:
            d = (price / sma - 1) * 100
            k = (ctx.get("below200") or {}).get(tk)
            if d >= 0:
                put("T2", "off", f"prezzo sopra la media 200 del {it(d)}%")
            else:
                k = max(k or 0, 1)
                put("T2", "on" if k <= NEWS_SESSIONS else "off", f"sotto la media 200 del {it(-d)}% da {k} {'seduta' if k == 1 else 'sedute'}"
                    + ("" if k <= NEWS_SESSIONS else ": non è più una novità (lo dice il controllo «Trend»)"))
        else:
            put("T2", "na", "meno di 200 sedute di prezzi, o prezzi storici non ancora caricati")
        an = (ctx.get("analysts") or {}).get(tk)
        if fund:
            put("T3", "na", "non vale per ETF ed ETC")
            put("T4", "na", "non vale per ETF ed ETC")
        else:
            if an and an.get("epsRev30") is not None:
                put("T3", "on" if an["epsRev30"] < EPS_CUT else "off", f"stime di utile {'+' if an['epsRev30'] > 0 else ''}{it(an['epsRev30'])}% in 30 giorni")
            else:
                put("T3", "na", "dati degli analisti non disponibili")
            if an:
                up, down = an.get("up30") or 0, an.get("down30") or 0
                put("T4", "on" if down > up else "off", f"{down} downgrade e {up} upgrade negli ultimi 30 giorni")
            else:
                put("T4", "na", "dati degli analisti non disponibili")
        ets = m.get("earningsTs") or ((ctx.get("rows") or {}).get(tk) or {}).get("earningsTs")
        earn_days = (datetime.fromtimestamp(ets).date() - today).days if ets else None
        earn_soon = earn_days is not None and 0 <= earn_days <= EARNINGS_DAYS
        earn_day = datetime.fromtimestamp(ets).strftime("%d/%m") if ets else None
        if fund:
            put("T5", "na", "non vale per ETF ed ETC")
        elif earn_days is None or earn_days < 0:
            put("T5", "na", "data della prossima trimestrale non nota")
        else:
            put("T5", "on" if earn_soon else "off", f"trimestrale il {earn_day}" + ("" if earn_soon else f", tra {earn_days} giorni"))
        if st and st.get("stop") is not None and st.get("atr") and price > st["stop"]:
            gap = (price - st["stop"]) / st["atr"]
            put("T6", "on" if gap < NEAR_STOP_ATR else "off", f"{it(gap)} ATR sopra lo stop automatico")
        else:
            ok_st = st and st.get("stop") is not None
            put("T6", "off" if ok_st else "na", "stop già rotto (vedi S1)" if ok_st else (st or {}).get("why") or "stop automatico non disponibile")

        # ---- Accumula (all must hold)
        if not states:
            put("B1", "na", "pagella non calcolabile")
        else:
            good = (ok >= STOCK_GOOD and ko == 0) if not fund else (ok == len(states))
            put("B1", "on" if good else "off", f"{ok} ✓, {ko} ✕ su {len(states)}{na_txt}")
        tb = m.get("trendBase")
        put("B2", "na" if tb is None else "on" if tb else "off",
            "medie non calcolabili" if tb is None else "prezzo sopra la media 200 e media 50 sopra la 200" if tb else "prezzo sotto la media 200, o media 50 sotto la 200")
        v = m.get("verdict")
        put("B3", "na" if not v else "on" if v in GOOD_VERDICTS else "off", f"«{m.get('label') or v}»" if v else "verdetto di mercato non calcolabile oggi")
        fired = [rid for rid, (s, _) in res.items() if s == "on" and group[rid] in (SELL, WATCH)]
        put("B4", "off" if earn_soon else "on", f"trimestrale il {earn_day}" if earn_soon else "")
        put("B5", "off" if fired else "on", "scattate: " + ", ".join(sorted(fired, key=order.index)) if fired else "nessuno")
        put("B6", "off" if lev else "on", "prodotto a leva" if lev else "")

        if any(group[r] == SELL for r in fired):
            action = SELL
        elif fired:
            action = WATCH
        elif all(res[r][0] == "on" for r in ("B1", "B2", "B3", "B4", "B5", "B6")):
            action = ADD
        else:
            action = HOLD
        counts[action] += 1
        fired = sorted(fired, key=order.index)
        reasons = [f"{SHORT[r]} ({res[r][1]})" for r in fired] if action in (SELL, WATCH) else \
            [f"{res['B1'][1]} · trend di fondo intatto · «{m.get('label') or v}»"] if action == ADD else []
        until = [UNTIL[r] for r in fired] if action in (SELL, WATCH) else \
            ["quando un controllo cade, il trend di fondo si rompe, cambia il verdetto o scatta un avviso"] if action == ADD else []
        tax = tax_estimate(p, p["value"], True, fiscal) if action == SELL else None

        # ---- notes without action
        if p.get("costPrice"):
            d = (price / p["costPrice"] - 1) * 100
            if d < LOSS:
                notes.append(f"Perde il {it(-d)}% dal prezzo di carico: decidi in base alle prospettive, non al prezzo pagato.")
        if m.get("skipped"):
            notes.append("Verdetto di mercato senza le regole " + " e ".join(m["skipped"]) + ": servono i dati di justETF, che per questo fondo non ci sono.")

        p["action"] = {"action": action, "label": action, "reasons": reasons, "notes": notes, "tax": tax,
                       "todo": TODO[action], "until": until,
                       "rules": [{"id": rid, "group": grp, "text": txt, "state": res[rid][0], "detail": res[rid][1]} for rid, grp, txt in RULES]}
    return {"counts": counts}
