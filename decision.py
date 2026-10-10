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
from datetime import datetime, timedelta

import portfolio
import technical

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

def stops(entry, ta, break_level=None, money=usd):
    """Stop options below the entry, the proposed one and why (same rule as phase 12). money formats the prices in
    the labels: dollars for the stocks, euro for the ETFs of Borsa Italiana (etf_buy.py)."""
    a = ta["atr"]
    opts = []
    if break_level is not None:
        opts.append({"id": "level", "v": break_level - STOP_LEVEL * a, "label": f"un ATR sotto il livello rotto ({money(break_level)})"})
    elif ta.get("sma50"):
        opts.append({"id": "sma50", "v": ta["sma50"] - STOP_MA * a, "label": f"sotto la media 50 ({money(ta['sma50'])}) meno mezzo ATR"})
    opts.append({"id": "low", "v": ta["low"]["v"] - STOP_MA * a, "label": f"sotto l'ultimo minimo ({money(ta['low']['v'])} del {ta['low']['date'][8:]}/{ta['low']['date'][5:7]}) meno mezzo ATR"})
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
    if money.get("budgetEur") is not None and money.get("fx"):
        for o in opts:                                   # every stop option has its own quantity (the page lets me switch)
            q = quantity_eur(money["budgetEur"], entry, o["v"], money["fx"], money["spread"])
            o.update(q)
        out.update(qty=next(o for o in opts if o["id"] == default)["qty"])
    return out


def quantity_eur(budget_eur, entry, stop, fx, spread=0.0):
    """Shares of a USD stock to buy so that hitting the stop loses at most budget_eur (rounded down; no cap since
    phase 21). fx = USD per 1 EUR. Settling in euro, Fineco converts at fx - spread when buying and at fx + spread
    when selling: the loss per share in euro is entry / (fx - spread) - stop / (fx + spread). Settling in dollars:
    spread 0, so it is simply (entry - stop) / fx."""
    per_share = entry / (fx - spread) - stop / (fx + spread)
    if per_share <= 0 or budget_eur <= 0:
        return {"qty": 0, "lossEur": 0.0, "valueEur": 0.0, "perShareEur": per_share}
    n = math.floor(budget_eur / per_share + 1e-9)        # + 1e-9: 22.0 must not become 21 because of rounding
    return {"qty": n, "lossEur": n * per_share, "valueEur": n * entry / (fx - spread), "perShareEur": per_share}


# ---------------------------------------------------------------- 4. place in my portfolio

def place(t, row, pf, fx, capital=None):
    """Do I own it, overlap with my Nasdaq-100 ETFs, and the money for the position size (my risk per trade).
    Phase 21 removed the weight limits: the quantity comes only from the risk per trade, with no cap."""
    R = (pf or {}).get("rules") or {}
    risk_pct = R.get("tradeRisk") or 1.0
    settle = R.get("settle") or "EUR"
    spread = R.get("spread", 0.0033 if settle == "EUR" else 0.0)
    positions = (pf or {}).get("positions") or []
    total = ((pf or {}).get("totals") or {}).get("value") or 0
    if not positions or not total:
        cap = capital if capital and capital > 0 else None
        money = {"capital": cap, "fx": fx, "riskPct": risk_pct, "settle": settle, "spread": spread,
                 "budgetEur": cap * risk_pct / 100 if cap else None}
        return {"loaded": False, "riskPct": risk_pct, "settle": settle}, money, None
    own = next((p for p in positions if p.get("ticker") == t), None)
    etfs = [p for p in positions if p.get("sector") == portfolio.LOOK_THROUGH_NDX]
    w = row.get("weight") or 0
    use_fx = pf.get("fx") or fx
    money = {"capital": total, "fx": use_fx, "riskPct": risk_pct, "settle": settle, "spread": spread, "budgetEur": total * risk_pct / 100}
    return {"loaded": True, "riskPct": risk_pct, "settle": settle, "owned": bool(own), "weight": own["value"] / total * 100 if own else 0.0,
            "value": own["value"] if own else 0,
            "etfOverlap": {"eur": sum(p["exposure"] for p in etfs) * w / 100, "indexWeight": w, "etfs": [p["name"] for p in etfs]} if etfs and w else None}, money, own


# ---------------------------------------------------------------- the whole sheet

def decide(t, row, info, valuation, an, ta, ptest, events, pf, fx, capital=None, extra=None):
    """All five blocks for one Nasdaq-100 stock, and the "Analisi" box on top. `ta` comes from technical.py (None = no
    technical data). extra (all optional): {"recTrend", "target", "targetN", "reports", "usualMove", "since", "today"}."""
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

    def v(label, why, by, plan_key=None, change=None, pattern=None):
        return {"label": label, "category": label.split(":")[0], "owned": False, "why": [why], "plan": plan_key, "change": change,
                "pattern": pattern, "decidedBy": by}
    if not ta or ok["D1"] is None:
        buy = v("Attendi", "dati insufficienti per valutare l'azienda o il tempismo", "dati", change="servono più dati (fondamentali, analisti o storico dei prezzi)")
    elif ok["D1"] is False:
        buy = v("Evita", f"azienda e valutazione deboli ({comp['score']:+d} punti): " + ", ".join(c["label"].lower() for c in comp["criteria"] if c["points"] == -1),
                "D1", change="da rivalutare se i criteri negativi migliorano")
    elif ok["D2"] is False:
        buy = v(f"Attendi: trimestrale il {earn_day}", "la trimestrale è entro 5 giorni: il prezzo può saltare in entrambe le direzioni", "D2", change="rivaluta dopo la trimestrale")
    elif ok["D4"] is False:
        buy = v("Attendi", f"il prezzo è sotto la media a 200 giorni ({it(vs200)}%): il trend di fondo è negativo", "D4", change="rivaluta quando il prezzo torna sopra la media a 200 giorni")
    elif ok["D5"] is False and plans.get("pullback"):
        buy = v("Entra su ritracciamento", f"il titolo è tirato ({'+' if vs20 >= 0 else ''}{it(vs20)}% sulla media 20, RSI {it(rsi or 0, 0)}): meglio un prezzo più vicino alle medie", "D5", "pullback")
    elif ok["D6"] is False:
        # phase 21: no "Entra su rottura" any more, the breakout of the 52-week high failed the pattern test (phase 11)
        buy = v("Attendi: a ridosso del massimo", "il prezzo è a meno del 3% sotto il massimo a 52 settimane: comprando ora il primo ostacolo è vicino, "
                "e la rottura del massimo non ha superato il test dei pattern", "D6", "breakout" if plans.get("breakouts") else None,
                change="rivaluta se il prezzo si allontana dal massimo (ritracciamento) o lo supera con decisione", pattern="high52")
    elif ok["D7"] is False and plans.get("pullback"):
        buy = v("Entra su ritracciamento", "l'azienda è nella media, non solida: ha senso solo a un prezzo più vicino alle medie", "D7", "pullback")
    elif plans.get("now"):
        buy = v("Entra ora", "tutte le regole sono soddisfatte", "tutte", "now")
    else:
        buy = v("Attendi", "livelli tecnici non calcolabili", "dati", change="servono più dati di prezzo")
    if own:
        a = own["action"]
        verdict = {"label": a.get("label") or a["action"], "category": a["action"], "owned": True, "isin": own["isin"],
                   "why": a["reasons"] or ["Nessuna regola delle posizioni è scattata."], "plan": "now" if a["action"] == "Accumula" else None,
                   "change": None, "decidedBy": "posizione"}
    else:
        verdict = buy
    box = analysis_box(row, price, ta, verdict, buy, plans, money, extra or {}, earn_days, earn_day, bool(own))
    return {"ticker": t, "price": price, "company": comp, "context": context, "timing": timing, "place": pl, "plans": plans,
            "verdict": verdict, "buyVerdict": buy, "checks": checks, "analysis": box,
            "principle": "L'azienda e la valutazione decidono SE comprare, il tempismo tecnico decide QUANDO e A CHE PREZZO, il portafoglio decide QUANTO."}


# ---------------------------------------------------------------- the "Analisi" box on top of Decisione (plan phase 22)
SURPRISE_HIGH = 100.0      # a surprise above +-100% usually comes from one-off items
EARN_SOON = 30             # the comment mentions the earnings only within 30 days
ORDER_DAYS = 30            # suggested expiry of limit and conditional orders
MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def sgn(x, d=1):
    return f"{'+' if x > 0 else ''}{it(x, d)}%"


def trend_sentence(tr):
    """'Tendenza in salita nell'ultima settimana (+1,9%) e nell'ultimo mese (+3,6%), laterale negli ultimi 3 mesi (-2,3%).'"""
    word = {"▲": "in salita", "▼": "in discesa", "=": "laterale"}
    when = {5: "nell'ultima settimana", 21: "nell'ultimo mese", 63: "negli ultimi 3 mesi"}
    parts, cur = [], None
    for x in (x for x in tr if x["arrow"]):
        item = f"{when[x['days']]} ({sgn(x['pct'])})"
        if cur and cur[0] == x["arrow"]:
            cur[1].append(item)
        else:
            cur = (x["arrow"], [item])
            parts.append(cur)
    if not parts:
        return None
    return "Tendenza " + ", ".join(f"{word[a]} {' e '.join(items)}" for a, items in parts) + "."


def zone_text(z):
    val = usd(z["lo"]) if abs(z["hi"] - z["lo"]) < 0.005 else f"{it(z['lo'], 2)}–{it(z['hi'], 2)} $"
    return f"{val} ({' e '.join(z['names'])}, {sgn(z['pct'])})"


def analysis_box(row, price, ta, verdict, buy, plans, money, extra, earn_days, earn_day, owned):
    """Signal, trend, levels, normal swing, data, consensus, comment and the order fields for Fineco."""
    A = (ta or {}).get("analysis")
    if not A:
        return None
    # ---- signal: today's verdict, since when (from the diary) and its plan
    key = verdict.get("plan")
    brk = next((b for b in plans.get("breakouts") or [] if b["pattern"] == verdict.get("pattern")), None) if key == "breakout" else None
    main = brk if key == "breakout" else plans.get(key) if key else None
    since = extra.get("since")
    sig = {"label": verdict["label"], "category": verdict["category"], "since": since,
           "sinceChg": (price / since["price"] - 1) * 100 if since and since.get("price") else None,
           "plan": {"kind": main["kind"], "entry": main["entry"], "stop": main["stop"], "target": main["target"], "rr": 2.0,
                    "rrResistance": (main["resistance"]["v"] - main["entry"]) / (main["entry"] - main["stop"]) if main.get("resistance") else None,
                    "resistance": main.get("resistance", {}).get("v"), "info": key == "breakout"} if main else None}
    # ---- levels, swing and data
    zs = technical.zones(A["levels"], price)
    bd = technical.band_from_sd(A["dailySd"], price)
    stop = (plans.get("now") or {}).get("stop") if not main else main["stop"]
    bd["stopInside"] = bool(stop and bd["p68"][0] < stop < bd["p68"][1])
    bd["stop"] = stop
    # ---- consensus (Yahoo): 1 = strong buy ... 5 = strong sell
    rt = extra.get("recTrend") or {}
    counts = [rt.get(k) or 0 for k in ("strongBuy", "buy", "hold", "sell", "strongSell")]
    n = sum(counts)
    tgt = extra.get("target")
    rep = (extra.get("reports") or [None])[0]
    cons = {"counts": counts, "n": n, "mean": sum((i + 1) * c for i, c in enumerate(counts)) / n if n else None,
            "target": tgt, "targetN": extra.get("targetN"), "upside": (tgt / price - 1) * 100 if tgt else None,
            "last": rep, "surpriseHigh": bool(rep and rep.get("surprise") is not None and abs(rep["surprise"]) > SURPRISE_HIGH)}
    # ---- comment: fixed sentences, each only when its data exists (templates approved by the user)
    say = []
    t1 = trend_sentence(A["trends"])
    if t1:
        say.append(t1)
    v50, v200 = row.get("vsSma50"), row.get("vsSma200")
    if v50 is not None and v200 is not None:
        say.append("Il prezzo è sopra le medie a 50 e a 200 giorni." if v50 >= 0 and v200 >= 0
                   else "Il prezzo è sotto le medie a 50 e a 200 giorni." if v50 < 0 and v200 < 0
                   else "Il prezzo è sopra la media a 200 giorni ma sotto quella a 50." if v200 >= 0
                   else "Il prezzo è sopra la media a 50 giorni ma sotto quella a 200.")
    sup, res = (zs["below"] or [None])[0], (zs["above"] or [None])[0]
    if sup and res:
        say.append(f"Il supporto più vicino è a {zone_text(sup)}; la resistenza più vicina a {zone_text(res)}.")
    elif sup:
        say.append(f"Il supporto più vicino è a {zone_text(sup)}. Sopra il prezzo non ci sono livelli tra quelli considerati: è sopra il massimo a 52 settimane.")
    s = f"Di solito in una settimana si muove di circa ±{it(bd['sd'])}% (2 volte su 3)."
    if bd["stopInside"]:
        s += " Lo stop proposto cade dentro questa oscillazione: rischia di scattare per rumore."
    say.append(s)
    vr = A["data"].get("volRatio")
    if vr and (vr >= 1.3 or vr <= 0.7):
        say.append(f"Negli ultimi 5 giorni gli scambi sono {'sopra' if vr >= 1.3 else 'sotto'} la media del mese ({it(vr, 2)}×).")
    if earn_days is not None and 0 <= earn_days <= EARN_SOON:
        when = "oggi" if earn_days == 0 else "domani" if earn_days == 1 else f"tra {earn_days} giorni"
        s = f"La trimestrale è il {earn_day}, {when}"
        um = extra.get("usualMove")
        say.append(s + (f": di solito il giorno dopo il titolo si muove di circa ±{it(um, 0)}%." if um else "."))
    why = "; ".join(w.rstrip(".") for w in verdict["why"])
    say.append(f"Verdetto: «{verdict['label']}», {why[:1].lower() + why[1:]}.")
    h52 = ta["high52"]["v"]
    if v200 is not None and v200 < 0:
        own_s = "il prezzo è sotto la media a 200 giorni: vale la pena rileggere la tesi."
    elif price <= h52 and price >= h52 * (1 - RESISTANCE / 100):
        own_s = "il titolo è a ridosso del massimo a 52 settimane: se hai un target, controlla quanto è vicino."
    elif sup:
        own_s = f"nessuno dei segnali tecnici considerati chiede di rivedere la posizione; il livello da tenere d'occhio è il supporto a {usd(sup['lo'])}."
    else:
        own_s = "nessuno dei segnali tecnici considerati chiede di rivedere la posizione."
    cat, bwhy = buy["category"], buy["why"][0]
    not_s = (f"il verdetto è «Entra ora»; il piano qui sotto indica entrata, stop e quantità per rischiare al massimo l'{it(money['riskPct'])}% del portafoglio."
             if cat == "Entra ora" else
             f"meglio aspettare un prezzo più vicino a {usd(plans['pullback']['entry'])} con un ordine limite." if cat == "Entra su ritracciamento" and plans.get("pullback") else
             f"le regole sull'azienda sono negative: {bwhy}." if cat == "Evita" else
             f"conviene aspettare: {bwhy}" + (f"; da rivalutare {buy['change'].replace('rivaluta ', '')}." if buy.get("change") else "."))
    comment = {"text": " ".join(say), "owner": "Per chi possiede il titolo: " + own_s, "notOwner": "Per chi non lo possiede: " + not_s,
               "end": "Commento generato da regole fisse sui dati: non è un consiglio."}
    # ---- order fields as in Fineco's order book, for every plan
    today = datetime.now()
    fmt = lambda d: d.strftime("%d/%m/%Y")
    orders = []
    for p in ([plans.get("now"), plans.get("pullback")] + list(plans.get("breakouts") or [])):
        if not p:
            continue
        st = next(o for o in p["opts"] if o["id"] == p["def"])
        orders.append({"kind": p["kind"], "type": "Limite" if p["kind"] in ("now", "pullback") else "Condizionato (stop)",
                       "price": p["entry"], "stopLoss": p["stop"], "takeProfit": p["target"],
                       "expiry": fmt(today) if p["kind"] == "now" else fmt(today + timedelta(days=ORDER_DAYS)),
                       "expiryNote": "giornaliero" if p["kind"] == "now" else f"{ORDER_DAYS} giorni",
                       "qty": st.get("qty"), "valueEur": st.get("valueEur"), "lossEur": st.get("lossEur"),
                       "noSpreadQty": quantity_eur(money["budgetEur"], p["entry"], p["stop"], money["fx"], 0.0)["qty"] if money.get("budgetEur") and money.get("fx") else None,
                       "info": p["kind"] == "breakout"})
    return {"signal": sig, "trends": A["trends"], "zones": zs, "pivots": A["pivots"], "band": bd, "data": A["data"],
            "consensus": cons, "comment": comment, "orders": orders, "settle": money.get("settle"), "spread": money.get("spread"),
            "fx": money.get("fx"), "riskPct": money.get("riskPct"), "capital": money.get("capital"),
            "rules": {"trend": technical.TREND, "zone": technical.ZONE, "swing": [technical.SWING_DAYS, technical.SWING_SIDE], "bandDays": technical.BAND_DAYS}}
