"""The "Decisione" section of the stock detail (plan phase 18): the sheet an analyst would bring to the investment
committee, in five blocks read in order, ending with a verdict produced by explicit rules.

    1. Azienda e valutazione  -> decides IF to buy
    2. Contesto               -> sector / theme, macro events, earnings
    3. Tempismo tecnico       -> decides WHEN and AT WHAT PRICE
    4. Posto nel portafoglio  -> decides HOW MUCH (my risk per trade, rules.py)
    5. Piano operativo        -> verdict: Entra ora / Entra su ritracciamento / Attendi / Evita
                                 (for a stock I own: the action of actions.py)

Nothing here is verified by a backtest, except the pattern test of phase 11 (which most patterns failed): the page
says so, shows every rule satisfied or not under the verdict, and keeps the "not investment advice" warning. The
signal diary (diary.py) records each day's verdicts to measure them from now on.
The raw technical levels come from technical.py; the same verdict is computed for the page and for the diary.
"""
from __future__ import annotations

import math
from datetime import datetime

import portfolio

# multiples of the ATR (the same values the page used in phase 12)
STOP_MA, STOP_ATR, OK_MIN, OK_MAX, ENTRY_MARGIN, STOP_LEVEL = 0.5, 2.0, 1.5, 3.5, 0.25, 1.0
NEAR_HIGH = 5.0          # waiting level shown: price within 5% below the 52-week high
RANGE_MAX = 12.0         # sideways phase: last 30 sessions at most 12% wide
RESISTANCE = 3.0         # verdict "Entra su rottura": price within 3% below the 52-week high
EXTENDED = 8.0           # "tirato": more than 8% above the 20-day average, or RSI above 75
RSI_MAX = 75
EARNINGS_DAYS = 5
PULLBACK_MIN = 2.0       # an average-quality company more than 2% above its 20-day average: wait for a pullback
SOLID, WEAK = 3, -1      # block 1: points >= 3 solid, <= -1 weak, otherwise average
MIN_CRITERIA = 4         # fewer criteria available: "dati insufficienti"


def it(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def usd(x):
    return it(x, 2) + " $"


# ---------------------------------------------------------------- 1. company and valuation

def company(info, valuation, an):
    """Eight criteria, each +1 / 0 / -1, and the summary solida / nella media / debole."""
    info = info or {}
    out = []

    def add(key, label, value, text, good, bad):
        pts = None if value is None else 1 if good(value) else -1 if bad(value) else 0
        out.append({"key": key, "label": label, "value": value, "text": text if value is not None else "dato non disponibile", "points": pts})
    pct = lambda v: None if v is None else v * 100
    g = pct(info.get("revenueGrowth"))
    add("rev", "Crescita dei ricavi", g, f"{it(g or 0)}% sull'anno", lambda v: v > 10, lambda v: v < 0)
    e = pct(info.get("earningsGrowth"))
    if e is None and an:
        e = an.get("epsGrowthNextY")
    add("eps", "Crescita degli utili", e, f"{it(e or 0)}%", lambda v: v > 10, lambda v: v < 0)
    m = pct(info.get("profitMargins"))
    add("margin", "Margine netto", m, f"{it(m or 0)}% dei ricavi", lambda v: v > 15, lambda v: v < 5)
    fcf, rev = info.get("freeCashflow"), info.get("totalRevenue")
    f = fcf / rev * 100 if fcf is not None and rev else None
    add("fcf", "Cassa generata (free cash flow)", f, f"{it(f or 0)}% dei ricavi", lambda v: v > 10, lambda v: v < 0)
    debt, cash = info.get("totalDebt"), info.get("totalCash")
    if debt is not None and cash is not None:
        net = debt - cash
        years = net / fcf if fcf and fcf > 0 else None
        if net <= 0:
            out.append({"key": "debt", "label": "Debito netto", "value": net, "text": "più cassa che debiti", "points": 1})
        elif years is None:
            out.append({"key": "debt", "label": "Debito netto", "value": net, "text": "debito netto positivo e cassa generata negativa", "points": -1})
        else:
            out.append({"key": "debt", "label": "Debito netto", "value": net, "text": f"si ripaga in circa {it(years)} anni di cassa generata",
                        "points": 1 if years < 2 else -1 if years > 5 else 0})
    else:
        out.append({"key": "debt", "label": "Debito netto", "value": None, "text": "dato non disponibile", "points": None})
    lab = (valuation or {}).get("label")
    out.append({"key": "val", "label": "Valutazione rispetto a settore e storia", "value": lab, "text": lab or "dato non disponibile",
                "points": None if not lab else 1 if lab == "Economica" else -1 if lab == "Cara" else 0})
    r = (an or {}).get("epsRev30")
    add("est", "Stime di utile degli analisti (30 giorni)", r, f"{'+' if (r or 0) > 0 else ''}{it(r or 0)}%", lambda v: v > 2, lambda v: v < -3)
    if an:
        up, down = an.get("up30") or 0, an.get("down30") or 0
        out.append({"key": "rec", "label": "Giudizi degli analisti (30 giorni)", "value": up - down, "text": f"{up} upgrade, {down} downgrade",
                    "points": 1 if up > down else -1 if down > up else 0})
    else:
        out.append({"key": "rec", "label": "Giudizi degli analisti (30 giorni)", "value": None, "text": "dato non disponibile", "points": None})
    known = [c["points"] for c in out if c["points"] is not None]
    score = sum(known)
    summary = "dati insufficienti" if len(known) < MIN_CRITERIA else "solida" if score >= SOLID else "debole" if score <= WEAK else "nella media"
    return {"criteria": out, "score": score, "known": len(known), "summary": summary,
            "rule": f"Ogni criterio vale +1, 0 o −1. Solida da +{SOLID} in su, debole da {WEAK} in giù, altrimenti nella media; con meno di {MIN_CRITERIA} criteri disponibili: dati insufficienti."}


# ---------------------------------------------------------------- stops and plans

def stops(entry, ta, break_level=None):
    """Stop options below the entry, the proposed one and why (same rule as phase 12)."""
    a = ta["atr"]
    opts = []
    if break_level is not None:
        opts.append({"id": "level", "v": break_level - STOP_LEVEL * a, "label": f"un ATR sotto il livello rotto ({usd(break_level)})"})
    elif ta.get("sma50"):
        opts.append({"id": "sma50", "v": ta["sma50"] - STOP_MA * a, "label": f"sotto la media 50 ({usd(ta['sma50'])}) meno mezzo ATR"})
    opts.append({"id": "low", "v": ta["low"]["v"] - STOP_MA * a, "label": f"sotto l'ultimo minimo ({usd(ta['low']['v'])} del {ta['low']['date'][8:]}/{ta['low']['date'][5:7]}) meno mezzo ATR"})
    if break_level is None:
        opts.append({"id": "atr", "v": entry - STOP_ATR * a, "label": f"{it(STOP_ATR, 0)} × ATR sotto l'entrata"})
    ok = [dict(o, atrs=(entry - o["v"]) / a) for o in opts if o["v"] < entry]
    if not ok:
        return [], None, ""
    if break_level is not None:
        return ok, ok[0]["id"], "se il prezzo torna sotto il livello appena superato, la rottura è fallita."
    best = sorted((o for o in ok if o["id"] != "atr" and OK_MIN <= o["atrs"] <= OK_MAX), key=lambda o: o["atrs"])
    if best:
        return ok, best[0]["id"], f"è il livello oggettivo più vicino a una distanza ragionevole (tra {it(OK_MIN)} e {it(OK_MAX)} ATR)."
    return ok, "atr", f"media 50 e ultimo minimo sono troppo vicini o troppo lontani dal prezzo (fuori da {it(OK_MIN)}–{it(OK_MAX)} ATR): uso la volatilità."


def plan(kind, entry, note, ta, money, break_level=None, extra=None):
    """One operating plan: entry, stop options, target at 2 times the risk, quantity from my rules."""
    opts, default, why = stops(entry, ta, break_level)
    if not default:
        return None
    st = next(o for o in opts if o["id"] == default)
    risk = entry - st["v"]
    out = {"kind": kind, "entry": entry, "entryNote": note, "opts": opts, "def": default, "why": why, "stop": st["v"],
           "target": entry + 2 * risk, "breakLevel": break_level, **(extra or {}), **money}
    if money.get("budgetUsd") is not None:
        out["qty"] = quantity(money["budgetUsd"], entry, st["v"])
    return out


def quantity(budget_usd, entry, stop):
    """Shares to buy so that hitting the stop loses at most budget_usd (rounded down; no cap since phase 21)."""
    risk = entry - stop
    return max(0, math.floor(budget_usd / risk)) if risk > 0 else 0


# ---------------------------------------------------------------- 4. place in my portfolio

def place(t, row, pf, fx, capital=None):
    """Do I own it, overlap with my Nasdaq-100 ETFs, and the money for the position size (my risk per trade).
    Phase 21 removed the weight limits: the quantity comes only from the risk per trade, with no cap."""
    risk_pct = ((pf or {}).get("rules") or {}).get("tradeRisk") or 1.0
    positions = (pf or {}).get("positions") or []
    total = ((pf or {}).get("totals") or {}).get("value") or 0
    if not positions or not total:
        cap = capital if capital and capital > 0 else None
        money = {"capital": cap, "fx": fx, "riskPct": risk_pct, "budgetUsd": cap * risk_pct / 100 * fx if cap and fx else None}
        return {"loaded": False, "riskPct": risk_pct}, money, None
    own = next((p for p in positions if p.get("ticker") == t), None)
    etfs = [p for p in positions if p.get("sector") == portfolio.LOOK_THROUGH_NDX]
    w = row.get("weight") or 0
    use_fx = pf.get("fx") or fx
    money = {"capital": total, "fx": use_fx, "riskPct": risk_pct, "budgetUsd": total * risk_pct / 100 * use_fx if use_fx else None}
    return {"loaded": True, "riskPct": risk_pct, "owned": bool(own), "weight": own["value"] / total * 100 if own else 0.0,
            "value": own["value"] if own else 0,
            "etfOverlap": {"eur": sum(p["exposure"] for p in etfs) * w / 100, "indexWeight": w, "etfs": [p["name"] for p in etfs]} if etfs and w else None}, money, own


# ---------------------------------------------------------------- the whole sheet

def decide(t, row, info, valuation, an, ta, ptest, events, pf, fx, capital=None):
    """All five blocks for one Nasdaq-100 stock. `ta` comes from technical.py (None = no technical data)."""
    price = row["price"]
    now = datetime.now()
    comp = company(info, valuation, an)
    ets = row.get("earningsTs")
    earn_days = (datetime.fromtimestamp(ets).date() - now.date()).days if ets else None
    earn_soon = earn_days is not None and 0 <= earn_days <= EARNINGS_DAYS
    earn_day = datetime.fromtimestamp(ets).strftime("%d/%m") if ets and (earn_days or 0) >= 0 else None
    pl, money, own = place(t, row, pf, fx, capital)

    tests = {p["key"]: p for p in (ptest or {}).get("patterns", [])}
    patterns = [{"key": x["key"], "date": x.get("date"), "name": tests[x["key"]]["name"], "verified": bool(tests[x["key"]]["favorable"])}
                for x in (ta or {}).get("patterns", []) if x["key"] in tests]
    timing = {"vs": {n: row.get(f"vsSma{n}") for n in (20, 40, 60, 50, 200)}, "rsi": row.get("rsi"), "patterns": patterns,
              "testAvailable": bool(tests),
              "levels": {"high52": ta["high52"], "low": ta["low"], "sma50": ta["sma50"], "sma200": row.get("sma200"), "sma20": row.get("sma20"), "atr": ta["atr"]} if ta else None}
    context = {"groups": (ta or {}).get("groups", []), "earningsDays": earn_days if (earn_days or 0) >= 0 else None, "earningsDay": earn_day,
               "events": [{"kind": e["kind"], "date": e["date"], "ts": e["ts"], "ref": e.get("ref"), "sep": e.get("sep")} for e in events or []]}

    # ---- plans (only with technical data)
    plans = {}
    vs20, vs200, rsi = row.get("vsSma20"), row.get("vsSma200"), row.get("rsi")
    if ta:
        plans["now"] = plan("now", price, "prezzo attuale", ta, money)
        h = ta["high52"]["v"]
        if plans["now"] and h > price and h < plans["now"]["target"]:
            plans["now"]["resistance"] = {"v": h, "rr": (h - price) / (price - plans["now"]["stop"])}
        s20, s50 = row.get("sma20"), ta.get("sma50")
        level = s20 if s20 and price > s20 * 1.01 else s50 if s50 and price > s50 * 1.01 else None
        if level:
            plans["pullback"] = plan("pullback", level, f"ordine limite vicino alla media {'20' if level == s20 else '50'}", ta, money,
                                     extra={"ma": 20 if level == s20 else 50})
        waits = []
        if price <= h and price >= h * (1 - NEAR_HIGH / 100):
            waits.append(("high52", h, f"massimo a 52 settimane (chiusura più alta dell'ultimo anno, {ta['high52']['date'][8:]}/{ta['high52']['date'][5:7]})"))
        r = ta["range"]
        if r["width"] <= RANGE_MAX and price <= r["hi"] and abs(r["hi"] / h - 1) > 0.001:
            waits.append(("range_break", r["hi"], f"massimo della fase laterale delle ultime {r['days']} sedute (ampiezza {it(r['width'])}%)"))
        plans["breakouts"] = [p for p in (plan("breakout", lv + ENTRY_MARGIN * ta["atr"], "se l'ordine scatta", ta, money, break_level=lv,
                                               extra={"pattern": key, "what": what, "level": lv}) for key, lv, what in sorted(waits, key=lambda x: x[1])) if p]

    # ---- verdict: the first rule not satisfied decides (the list is shown under the verdict)
    near_high = bool(ta and price <= ta["high52"]["v"] and price >= ta["high52"]["v"] * (1 - RESISTANCE / 100))
    extended = (vs20 is not None and vs20 > EXTENDED) or (rsi is not None and rsi > RSI_MAX)
    checks = [
        {"id": "D1", "text": "Azienda e valutazione: solida o nella media (decide SE comprare)", "ok": None if comp["summary"] == "dati insufficienti" else comp["summary"] != "debole",
         "detail": f"{comp['summary']} ({comp['score']:+d} punti su {comp['known']} criteri)"},
        {"id": "D2", "text": f"Nessuna trimestrale nei prossimi {EARNINGS_DAYS} giorni", "ok": not earn_soon, "detail": f"trimestrale il {earn_day}" if earn_day else "data non nota"},
        {"id": "D4", "text": "Prezzo sopra la media a 200 giorni", "ok": None if vs200 is None else vs200 >= 0, "detail": "" if vs200 is None else f"{'+' if vs200 >= 0 else ''}{it(vs200)}%"},
        {"id": "D5", "text": f"Non tirato: al massimo {it(EXTENDED, 0)}% sopra la media 20 e RSI non oltre {RSI_MAX}", "ok": None if vs20 is None else not extended,
         "detail": "" if vs20 is None else f"{'+' if vs20 >= 0 else ''}{it(vs20)}% sulla media 20, RSI {it(rsi or 0, 0)}"},
        {"id": "D6", "text": f"Non a ridosso di una resistenza: più del {it(RESISTANCE, 0)}% sotto il massimo a 52 settimane, o già sopra", "ok": None if not ta else not near_high,
         "detail": "" if not ta else f"massimo {usd(ta['high52']['v'])}, prezzo {'+' if price >= ta['high52']['v'] else ''}{it((price / ta['high52']['v'] - 1) * 100)}%"},
        {"id": "D7", "text": f"Azienda solida, oppure prezzo entro il {it(PULLBACK_MIN, 0)}% dalla media 20 (un'azienda nella media si compra solo a sconto)",
         "ok": None if vs20 is None else comp["summary"] == "solida" or vs20 <= PULLBACK_MIN, "detail": comp["summary"]},
    ]
    ok = {c["id"]: c["ok"] for c in checks}
    if own:
        a = own["action"]
        verdict = {"label": a.get("label") or a["action"], "category": a["action"], "owned": True, "isin": own["isin"],
                   "why": a["reasons"] or ["Nessuna regola delle posizioni è scattata."], "plan": "now" if a["action"] == "Accumula" else None,
                   "change": None, "decidedBy": "posizione"}
    else:
        def v(label, why, by, plan_key=None, change=None, pattern=None):
            return {"label": label, "category": label.split(":")[0], "owned": False, "why": [why], "plan": plan_key, "change": change,
                    "pattern": pattern, "decidedBy": by}
        if not ta or ok["D1"] is None:
            verdict = v("Attendi", "dati insufficienti per valutare l'azienda o il tempismo", "dati", change="servono più dati (fondamentali, analisti o storico dei prezzi)")
        elif ok["D1"] is False:
            verdict = v("Evita", f"azienda e valutazione deboli ({comp['score']:+d} punti): " + ", ".join(c["label"].lower() for c in comp["criteria"] if c["points"] == -1),
                        "D1", change="da rivalutare se i criteri negativi migliorano")
        elif ok["D2"] is False:
            verdict = v(f"Attendi: trimestrale il {earn_day}", "la trimestrale è entro 5 giorni: il prezzo può saltare in entrambe le direzioni", "D2", change="rivaluta dopo la trimestrale")
        elif ok["D4"] is False:
            verdict = v("Attendi", f"il prezzo è sotto la media a 200 giorni ({it(vs200)}%): il trend di fondo è negativo", "D4", change="rivaluta quando il prezzo torna sopra la media a 200 giorni")
        elif ok["D5"] is False and plans.get("pullback"):
            verdict = v("Entra su ritracciamento", f"il titolo è tirato ({'+' if vs20 >= 0 else ''}{it(vs20)}% sulla media 20, RSI {it(rsi or 0, 0)}): meglio un prezzo più vicino alle medie", "D5", "pullback")
        elif ok["D6"] is False:
            # phase 21: no "Entra su rottura" any more, the breakout of the 52-week high failed the pattern test (phase 11)
            verdict = v("Attendi: a ridosso del massimo", "il prezzo è a meno del 3% sotto il massimo a 52 settimane: comprando ora il primo ostacolo è vicino, "
                        "e la rottura del massimo non ha superato il test dei pattern", "D6", "breakout" if plans.get("breakouts") else None,
                        change="rivaluta se il prezzo si allontana dal massimo (ritracciamento) o lo supera con decisione", pattern="high52")
        elif ok["D7"] is False and plans.get("pullback"):
            verdict = v("Entra su ritracciamento", "l'azienda è nella media, non solida: ha senso solo a un prezzo più vicino alle medie", "D7", "pullback")
        elif plans.get("now"):
            verdict = v("Entra ora", "tutte le regole sono soddisfatte", "tutte", "now")
        else:
            verdict = v("Attendi", "livelli tecnici non calcolabili", "dati", change="servono più dati di prezzo")
    return {"ticker": t, "price": price, "company": comp, "context": context, "timing": timing, "place": pl, "plans": plans,
            "verdict": verdict, "checks": checks,
            "principle": "L'azienda e la valutazione decidono SE comprare, il tempismo tecnico decide QUANDO e A CHE PREZZO, il portafoglio decide QUANTO."}
