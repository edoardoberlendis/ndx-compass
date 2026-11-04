"""Thesis and proposed action for each position I own (plan phase 17).

Personal data: my theses live in portafoglio/tesi.json (outside Git), edited from the dashboard.

For every position the dashboard proposes Mantieni / Accumula / Rivedi la tesi from the explicit rules below, and
always shows which rules fired, with their numbers. Rivedi la tesi wins over Accumula, otherwise Mantieni. These are
rules of discipline chosen by the user: NONE of them is verified by a backtest, and the page says so.
Phase 21 removed the rules based on the weight limits (R1, R2: the only "Riduci" rules, and A3): ids are not reused.

The indicative tax estimate (next to "Rivedi · target raggiunto") can use my capital losses carried forward
("zainetto fiscale", portafoglio/fiscale.json) for shares and ETC/ETN, never for ETF gains.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime

import portfolio

FILE = os.path.join(portfolio.PORTFOLIO_DIR, "tesi.json")
FISCAL = os.path.join(portfolio.PORTFOLIO_DIR, "fiscale.json")      # {"losses": EUR, "expiry": "AAAA-12-31"}
TEXTS = ("why", "expect", "sell")           # perché la possiedo, cosa mi aspetto, cosa mi farebbe vendere
NUMBERS = ("stop", "target", "weight")      # stop price, target price, target weight (% of the portfolio): all optional
MAX_TEXT = 2000
MAX_PILLARS = 4         # pillars chosen from the list (pillars.py), plus at most one written in words
PILLAR_IDS = {"ricavi": 0, "stime": 0, "consenso": 0, "margine": 0, "valutazione": 0, "trend": 0, "diversifica": 0}

# thresholds of the rules (proposed starting values, approved by the user)
EPS_CUT = -3.0          # V4: next year's EPS estimate cut by more than 3% in 30 days
LOSS = -25.0            # V6: price more than 25% below the average cost
LEV_DAYS = 30           # V7: leveraged product held for more than 30 days (counted from the first day in the history)
THESIS_MONTHS = 6       # V8: thesis older than 6 months
UNDER_TARGET = 0.8      # A1: weight below 80% of my target weight
EARNINGS_DAYS = 5       # A5: no "Accumula" with earnings within 5 days (Mantieni, "accumula dopo la trimestrale")
SILENCE_DAYS = 30       # after "Ho rivisto la tesi" the review rules that had fired stay silent for 30 days, unless a new one fires
TAX_RATE = 0.26         # indicative Italian tax on financial gains

ORDER = ["Rivedi la tesi", "Accumula", "Mantieni"]
SHORT = {"V1": "stop rotto", "V2": "target raggiunto: valuta una presa di profitto", "V3": "sotto la media a 200 giorni",
         "V4": "stime degli analisti tagliate", "V5": "più downgrade che upgrade", "V6": "",
         "V7": "prodotto a leva tenuto oltre 30 giorni", "V8": "tesi da rileggere (più di 6 mesi)"}
RULES = [   # id, group, what the rule says (shown in the position's panel)
    ("V1", "Rivedi la tesi", "Il prezzo è sceso sotto lo stop che ho scritto nella tesi"),
    ("V2", "Rivedi la tesi", "Il prezzo ha raggiunto il target che ho scritto: valuta una presa di profitto"),
    ("V3", "Rivedi la tesi", "Il prezzo è sotto la media a 200 giorni"),
    ("V4", "Rivedi la tesi", "Le stime di utile dell'anno prossimo sono state tagliate di oltre il 3% in 30 giorni"),
    ("V5", "Rivedi la tesi", "Negli ultimi 30 giorni ci sono stati più downgrade che upgrade"),
    ("V6", "Rivedi la tesi", "La posizione perde più del 25% rispetto al prezzo di carico"),
    ("V7", "Rivedi la tesi", "È un prodotto a leva in portafoglio da più di 30 giorni"),
    ("V8", "Rivedi la tesi", "La tesi è stata scritta più di 6 mesi fa: va riletta"),
    ("A1", "Accumula", "Ho scritto un peso obiettivo e il peso attuale è sotto l'80% di quell'obiettivo"),
    ("A2", "Accumula", "Nessuna regola Rivedi è scattata"),
    ("A4", "Accumula", "Non è un prodotto a leva"),
    ("A5", "Accumula", "Nessuna trimestrale nei prossimi 5 giorni"),
]


def it(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


# ---------------------------------------------------------------- theses

def load():
    try:
        with open(FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def save(isin, data):
    """Write one thesis in portafoglio/tesi.json. Raises ValueError with an Italian message."""
    if not isinstance(isin, str) or not 6 <= len(isin) <= 20:
        raise ValueError("Posizione non riconosciuta.")
    out = {}
    for k in TEXTS:
        v = (data or {}).get(k) or ""
        if not isinstance(v, str) or len(v) > MAX_TEXT:
            raise ValueError("Testo troppo lungo (massimo 2000 caratteri per campo).")
        out[k] = v.strip()
    for k in NUMBERS:
        v = (data or {}).get(k)
        if v in (None, ""):
            out[k] = None
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0 or (k == "weight" and v > 100):
            raise ValueError("Stop, target e peso obiettivo devono essere numeri positivi (il peso al massimo 100).")
        out[k] = float(v)
    all_ = load()
    old = all_.get(isin) or {}
    # pillars (pillars.py): ids from the list of the position's kind, at most 4, plus at most one written in words
    if "pillars" in (data or {}):
        ids = data.get("pillars")
        if not isinstance(ids, list) or not all(isinstance(x, str) and x in PILLAR_IDS for x in ids) or len(set(ids)) > MAX_PILLARS:
            raise ValueError(f"Scegli al massimo {MAX_PILLARS} pilastri dall'elenco.")
        out["pillars"] = sorted(set(ids), key=list(PILLAR_IDS).index)
    elif "pillars" in old:
        out["pillars"] = old["pillars"]
    text = (data or {}).get("manual")
    if text is None:
        text = (old.get("manual") or {}).get("text") or ""
    if not isinstance(text, str) or len(text) > 300:
        raise ValueError("Il pilastro scritto a parole può avere al massimo 300 caratteri.")
    text = text.strip()
    prev = old.get("manual") or {}
    out["manual"] = ({**prev, "text": text} if text == prev.get("text") else {"text": text, "state": None, "date": None}) if text else None
    rev = (data or {}).get("revMin", (old.get("pillarOpts") or {}).get("ricavi"))
    if rev not in (None, "") and (not isinstance(rev, (int, float)) or isinstance(rev, bool) or not 0 <= rev <= 100):
        raise ValueError("La soglia dei ricavi deve essere una percentuale tra 0 e 100.")
    out["pillarOpts"] = {"ricavi": float(rev)} if rev not in (None, "") else {}
    out["updated"] = date.today().isoformat()
    for k in ("reviews", "log", "last"):                 # "Ho rivisto la tesi", the pillars' log and their last states are kept
        out[k] = old.get(k) or ([] if k != "last" else {})
    if "pillars" in out and out.get("pillars") != old.get("pillars"):
        out["last"] = {k: v for k, v in out["last"].items() if k in out["pillars"]}
    all_[isin] = out
    _write(all_)
    return out


def _write(all_):
    os.makedirs(portfolio.PORTFOLIO_DIR, exist_ok=True)
    with open(FILE + ".tmp", "w") as f:
        json.dump(all_, f, indent=1, ensure_ascii=False)
    os.replace(FILE + ".tmp", FILE)


def add_note(isin, note):
    """A dated note of mine in the thesis' log (a fact that strengthens or weakens the thesis)."""
    note = (note or "").strip() if isinstance(note, str) else ""
    if not 3 <= len(note) <= 300:
        raise ValueError("Scrivi una nota da 3 a 300 caratteri.")
    all_ = load()
    if isin not in all_:
        raise ValueError("Scrivi e salva prima la tesi.")
    all_[isin].setdefault("log", []).append({"date": date.today().isoformat(), "note": note})
    _write(all_)


def mark_manual(isin, state):
    """The pillar written in words: "ok" = still valid, "ko" = fallen (confirmed by hand every 3 months)."""
    if state not in ("ok", "ko"):
        raise ValueError("Stato non valido.")
    all_ = load()
    m = (all_.get(isin) or {}).get("manual") or {}
    if not m.get("text"):
        raise ValueError("Non c'è un pilastro scritto a parole.")
    today = date.today().isoformat()
    if m.get("state") != state:
        all_[isin].setdefault("log", []).append({"date": today, "pillar": "manual", "name": m["text"], "from": m.get("state"), "to": state,
                                                 "detail": "segnato da te"})
    all_[isin]["manual"] = {**m, "state": state, "date": today}
    _write(all_)


def record_pillars(updates):
    """{isin: (entries, last)} from pillars.changes: append the changes to the log and keep the new states.
    Writes only when something changed."""
    all_ = load()
    dirty = False
    for isin, (entries, last) in updates.items():
        th = all_.get(isin)
        if th is None or (not entries and th.get("last") == last):
            continue
        th.setdefault("log", []).extend(entries)
        th["last"] = last
        dirty = True
    if dirty:
        _write(all_)


def review(isin, note, fired):
    """"Ho rivisto la tesi": save the reason with today's date and the review rules that had fired (they stay silent
    for SILENCE_DAYS, unless a new one fires). Raises ValueError with an Italian message."""
    note = (note or "").strip() if isinstance(note, str) else ""
    if not 3 <= len(note) <= 300:
        raise ValueError("Scrivi una riga di motivazione (da 3 a 300 caratteri).")
    if not fired:
        raise ValueError("Per questa posizione non è scattata nessuna regola «Rivedi la tesi».")
    all_ = load()
    th = all_.setdefault(isin, {k: "" for k in TEXTS} | {k: None for k in NUMBERS} | {"updated": None})
    th.setdefault("reviews", []).append({"date": date.today().isoformat(), "note": note, "rules": sorted(fired)})
    _write(all_)


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


def _has_thesis(t):
    return bool(t and (any(t.get(k) for k in TEXTS) or any(t.get(k) for k in NUMBERS) or t.get("pillars") or (t.get("manual") or {}).get("text")))


# ---------------------------------------------------------------- rules

def evaluate(pf, ctx):
    """Attach to every position of the snapshot its thesis and proposed action:
    p["action"] = {"action", "reasons", "rules": [{"id", "group", "text", "state": on|off|na, "detail"}], "notes"}.
    ctx: {"rows": Nasdaq-100 rows by ticker, "analysts": analyst summaries by ticker, "sma200": {ticker: value},
          "firstSeen": {isin: first day in the history}}. Returns a short summary (counts)."""
    positions = pf.get("positions") or []
    total = (pf.get("totals") or {}).get("value") or 0
    if not positions or not total:
        return {"attention": 0, "noThesis": 0, "silenced": 0, "counts": {}}
    theses = load()
    fiscal = load_fiscal()
    today = date.today()
    counts = {a: 0 for a in ORDER}
    no_thesis = silenced_n = 0

    for p in positions:
        th = theses.get(p["isin"]) or {}
        has = _has_thesis(th)
        no_thesis += not has
        lev = (p.get("leverage") or 1) > 1
        weight = p["value"] / total * 100
        price, tk = p["price"], p.get("ticker")
        row = (ctx.get("rows") or {}).get(tk) or {}
        res, notes = {}, []

        def put(rid, state, detail=""):
            res[rid] = (state, detail)

        # ---- Rivedi la tesi
        if th.get("stop"):
            put("V1", "on" if price <= th["stop"] else "off", f"prezzo {it(price, 2)}, stop {it(th['stop'], 2)}")
        else:
            put("V1", "na", "nessuno stop indicato nella tesi")
        if th.get("target"):
            put("V2", "on" if price >= th["target"] else "off", f"prezzo {it(price, 2)}, target {it(th['target'], 2)}")
        else:
            put("V2", "na", "nessun target indicato nella tesi")
        sma = (ctx.get("sma200") or {}).get(tk)
        if sma:
            d = (price / sma - 1) * 100
            put("V3", "on" if d < 0 else "off", f"prezzo {'sotto' if d < 0 else 'sopra'} la media 200 del {it(abs(d))}%")
        else:
            put("V3", "na", "meno di 200 sedute di prezzi, o prezzi storici non ancora caricati")
        an = (ctx.get("analysts") or {}).get(tk)
        if an and an.get("epsRev30") is not None:
            put("V4", "on" if an["epsRev30"] < EPS_CUT else "off", f"stime di utile {'+' if an['epsRev30'] > 0 else ''}{it(an['epsRev30'])}% in 30 giorni")
        else:
            put("V4", "na", "dati degli analisti disponibili solo per i titoli del Nasdaq-100")
        if an:
            up, down = an.get("up30") or 0, an.get("down30") or 0
            put("V5", "on" if down > up else "off", f"{down} downgrade e {up} upgrade negli ultimi 30 giorni")
        else:
            put("V5", "na", "dati degli analisti disponibili solo per i titoli del Nasdaq-100")
        if p.get("costPrice"):
            d = (price / p["costPrice"] - 1) * 100
            put("V6", "on" if d < LOSS else "off", f"perde il {it(-d)}% dal prezzo di carico: la tesi è ancora valida? Decidi in base alle prospettive, non al prezzo pagato"
                if d < LOSS else f"{'+' if d > 0 else ''}{it(d)}% rispetto al prezzo di carico ({it(p['costPrice'], 2)})")
        else:
            put("V6", "na", "prezzo di carico non disponibile")
        if lev:
            first = (ctx.get("firstSeen") or {}).get(p["isin"])
            days = (today - date.fromisoformat(first)).days if first else 0
            put("V7", "on" if days > LEV_DAYS else "off", f"nello storico da {days} giorni (lo storico parte dal {first or 'oggi'}; il file Fineco non dice quando hai comprato)")
            notes.append("Prodotto a leva: è pensato per periodi brevi e perde valore con il mercato altalenante.")
        else:
            put("V7", "na", "non è un prodotto a leva")
        if has and th.get("updated"):
            months = (today - date.fromisoformat(th["updated"])).days / 30.4
            put("V8", "on" if months > THESIS_MONTHS else "off", f"tesi aggiornata il {th['updated']}")
        else:
            put("V8", "na", "tesi non ancora scritta")

        fired = [rid for rid, (s, _) in res.items() if s == "on"]
        fired_v = [r for r in fired if r.startswith("V")]
        last = (th.get("reviews") or [None])[-1]
        left = SILENCE_DAYS - (today - date.fromisoformat(last["date"])).days if last else 0
        silenced = bool(fired_v and last and left > 0 and set(fired_v) <= set(last["rules"]))   # nothing new since my review
        ets = row.get("earningsTs")
        earn_days = (datetime.fromtimestamp(ets).date() - today).days if ets else None
        earn_soon = earn_days is not None and 0 <= earn_days <= EARNINGS_DAYS
        earn_day = datetime.fromtimestamp(ets).strftime("%d/%m") if earn_soon else None

        # ---- Accumula (all four)
        tw = th.get("weight")
        if tw:
            put("A1", "on" if weight < tw * UNDER_TARGET else "off", f"peso {it(weight)}%, obiettivo {it(tw)}%")
        else:
            put("A1", "na", "nessun peso obiettivo indicato nella tesi")
        put("A2", "off" if fired else "on", "scattate: " + ", ".join(fired) if fired else "nessuna")
        put("A4", "off" if lev else "on", "prodotto a leva" if lev else "")
        put("A5", "off" if earn_soon else "on", f"trimestrale il {earn_day}" if earn_soon else "" if row else "data della trimestrale nota solo per i titoli del Nasdaq-100")

        if fired_v and not silenced:
            action = "Rivedi la tesi"
        elif all(res[r][0] == "on" for r in ("A1", "A2", "A4", "A5")):
            action = "Accumula"
        else:
            action = "Mantieni"
        counts[action] += 1
        silenced_n += silenced and action == "Mantieni"
        target_hit = "V2" in fired_v and not silenced
        label = "Rivedi · target raggiunto" if action == "Rivedi la tesi" and target_hit else action
        if action == "Accumula":
            reasons = [f"peso {it(weight)}%, obiettivo {it(tw)}% · nessuna regola contraria"]
        else:           # every rule that fired, with its numbers (none once I have reviewed the thesis)
            why_v = lambda r: res[r][1] if r == "V6" else f"{SHORT[r]} ({res[r][1]})"
            reasons = [] if silenced else [why_v(r) for r in fired_v]
        if action == "Mantieni" and earn_soon and all(res[r][0] == "on" for r in ("A1", "A2", "A4")):
            notes.append(f"Accumula dopo la trimestrale del {earn_day}.")
        tax = tax_estimate(p, p["value"], True, fiscal) if target_hit else None

        # ---- notes without action
        if not has:
            notes.append("Tesi non ancora scritta.")
        if earn_soon:
            notes.append(f"Trimestrale {'oggi' if earn_days == 0 else 'domani' if earn_days == 1 else f'tra {earn_days} giorni'}.")
        if row.get("signal"):
            notes.append(f"Segnale della dashboard: {row['signal']}" + (f" · Trend {row['trend']:+.0f}" if row.get("trend") is not None else "") + " (non verificati da backtest).")

        p["thesis"] = th if has else None
        p["action"] = {"action": action, "label": label, "reasons": reasons, "notes": notes, "tax": tax,
                       "canReview": bool(fired_v) and not silenced,
                       "silenced": {"until": left, "date": last["date"], "note": last["note"],
                                    "rules": [SHORT[r] or "perdita oltre il 25% dal prezzo di carico" for r in fired_v]} if silenced else None,
                       "rules": [{"id": rid, "group": grp, "text": txt, "state": res[rid][0], "detail": res[rid][1]} for rid, grp, txt in RULES]}
    return {"noThesis": no_thesis, "silenced": int(silenced_n), "counts": counts}
