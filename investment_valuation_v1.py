"""FROZEN COPY of the phase 5B valuation model, VERSION "V1" (4 November 2026). Do not edit.

Kept unchanged so that V1 valuations stay reproducible and can be compared with the current model
(investment_valuation.py, VERSION "V2", phase 5C audit). The original docstring follows.

Valutazione economica e scenari (phase 5B, model VERSION "V1", experimental).

    .venv/bin/python investment_valuation_v1.py riepilogo        statuses, price position and groups of the 101 companies
    .venv/bin/python investment_valuation_v1.py mostra TICKER    the full valuation of one company
    .venv/bin/python investment_valuation_v1.py parametri        every parameter with its explanation

Next to the fundamental engine of phase 5A (investment_engine.py), never in place of it: the six dimensions, the
profiles and the Pagella are unchanged and only read. Data from the caches already on disk (no download here).

METHOD — discounted cash flow to the firm (FCFF), the same convention everywhere:
  * flows for ALL the providers of capital (shareholders and lenders): NOPAT = revenue x operating margin x (1 - tax),
    minus the reinvestment needed to grow (new revenue / sales-to-capital ratio);
  * discounted with the WACC (cost of equity from the 10-year Treasury, beta and an equity risk premium; after-tax cost
    of debt; market weights): flows of the firm with the rate of the firm, never mixed with flows to equity (FCFE);
  * enterprise value -> equity value = EV + cash - debt (leases included) - minorities - preferred, divided by the
    diluted shares, in USD (accounts in another currency converted at today's rate, recorded with source and date);
  * nominal USD for flows, discount rate and terminal growth; end-of-year discounting; 5 explicit years then a
    terminal value (Gordon growth) whose reinvestment is g / ROIC so growth and return stay coherent.
  The 5 years are the length of the explicit forecast, NOT a target price at 5 years.

Stock-based compensation: the GAAP operating income already deducts it as a cost. The DCF therefore does not subtract
it again and uses today's diluted shares, with no extra future dilution (that would count the same cost twice). The
"economic" free cash flow (accounting FCF - stock-based pay) is shown as an adjusted measure of this dashboard, not as
a standard accounting figure.

Three scenarios (prudent, base, favourable) change growth, margin and capital efficiency together; the discount rate
is the same in the three (it measures risk, not the scenario) and its effect is shown in the sensitivity table. No
probability is given to the scenarios and no weighted "expected value" or return is computed.

Not valued: financial companies and utilities (an industrial DCF does not fit), negative or very unstable operating
results, negative operating cash flow, obsolete or missing data. Every parameter is in PARAMS, shown in the page and
saved in the diary with VERSION. Thresholds and parameters are proposals of 4 November 2026, not validated.
"""
from __future__ import annotations

import math
import statistics
import sys
from datetime import date

import fundamentals as fu
import investment_engine as ie

VERSION = "V1"
_num = ie._num
it, sgn, day_it = ie.it, ie.sgn, ie.day_it

# ---------------------------------------------------------------- parameters (visible, explained, versioned)
P = {
    "years": 5,                 # explicit forecast
    "erp": 0.045,               # equity risk premium
    "gTerminal": 0.025,         # terminal growth, nominal USD
    "minSpread": 0.02,          # WACC must exceed terminal growth by at least 2 points
    "betaBlume": 0.67,          # adjusted beta = 0.67 x raw + 0.33 x 1
    "betaMin": 0.7, "betaMax": 2.0, "betaMissing": 1.0,
    "kdSpreadMax": 0.05, "kdSpreadDefault": 0.015,
    "taxMin": 0.10, "taxMax": 0.30, "taxDefault": 0.21,
    "g1Min": -0.15, "g1Max": 0.50,
    "gSpreadAbs": 0.04, "gSpreadRel": 0.35, "gPrudentFloor": -0.20, "gFavCap": 0.60,
    "mPrudentRel": 0.20, "mFavRel": 0.10, "mCap": 0.60,
    "s2cMin": 0.5, "s2cMax": 6.0, "s2cPrudent": 0.75, "s2cFav": 1.25,
    "roicTCap": 0.40,
    "unstableRange": 0.20,      # operating margins of the last 3 years + 12 months more than 20 points apart
    "sharesTol": 0.10, "sharesMaxGap": 0.33,
    "tvHeavy": 0.85, "sensWacc": 0.01, "sensHigh": 0.30, "spreadHigh": 3.0,
    "reinvGap": 2.0, "reinvShare": 0.25, "cashGap": 0.05,
    "ambitiousRev": 3.0, "ambitiousMargin": 0.45,
    "consensusMinAnalysts": 3,
}
PARAMS = [
    ("Metodo", "flusso di cassa per tutti i finanziatori (FCFF) scontato al costo medio del capitale (WACC); valore "
               "dell'impresa → valore delle azioni (+ liquidità − debito compresi i leasing − quote di minoranza − "
               "azioni privilegiate) ÷ azioni diluite; tutto in dollari nominali, sconto a fine anno"),
    ("Orizzonte", f"{P['years']} anni di previsione esplicita, poi valore terminale con crescita costante: la durata "
                  "della previsione non è un prezzo obiettivo a 5 anni"),
    ("Tasso privo di rischio", "rendimento del Treasury USA a 10 anni (^TNX), ultima chiusura disponibile, con la data"),
    ("Premio per il rischio azionario", f"{P['erp'] * 100:g}%: ipotesi fissa, dentro l'intervallo 4–5% usato comunemente "
                                        "per il mercato USA; non stimata da questa dashboard"),
    ("Beta", f"beta a 5 anni di Yahoo corretto verso 1 ({P['betaBlume']:g} × beta + {1 - P['betaBlume']:.2f}), limitato tra "
             f"{P['betaMin']:g} e {P['betaMax']:g}; se manca si usa {P['betaMissing']:g} (valutazione parziale)"),
    ("Costo del debito", f"interessi passivi ÷ debito, tra il tasso privo di rischio e +{P['kdSpreadMax'] * 100:g} punti; "
                         f"se manca, +{P['kdSpreadDefault'] * 100:g} punti; dopo le tasse"),
    ("Tasse", f"aliquota effettiva dell'ultimo bilancio annuale se tra {P['taxMin'] * 100:g}% e {P['taxMax'] * 100:g}%, "
              f"altrimenti {P['taxDefault'] * 100:g}%"),
    ("Crescita dei ricavi", "anno 1: crescita annua implicita nel consenso degli analisti sui ricavi del prossimo esercizio "
                            f"(almeno {P['consensusMinAnalysts']} analisti, esercizi del consenso coerenti con i bilanci), altrimenti l'ultima crescita misurata; "
                            f"limitata tra {P['g1Min'] * 100:g}% e +{P['g1Max'] * 100:g}%; poi scende in linea retta "
                            f"fino alla crescita terminale del {P['gTerminal'] * 100:g}%"),
    ("Margine operativo", "parte dal margine degli ultimi 12 mesi e arriva in 5 anni al margine «normale» (mediana di "
                          "ultimi 12 mesi e ultimi 3 esercizi)"),
    ("Reinvestimenti", "ricavi aggiuntivi ÷ rapporto ricavi/capitale = mediana di tre misure: marginale degli ultimi 3 "
                       "esercizi (ricavi aggiunti ÷ investimenti netti = capex − ammortamenti + capitale circolante, solo "
                       "con ricavi cresciuti almeno del 10%), di bilancio (ricavi ÷ patrimonio + debito − liquidità) e "
                       "mediana delle società con lo stesso modello; ognuna limitata tra "
                       f"{P['s2cMin']:g} e {P['s2cMax']:g}; nessun capitale liberato se i ricavi scendono"),
    ("Valore terminale", f"crescita {P['gTerminal'] * 100:g}% (non oltre il tasso privo di rischio), reinvestimento = "
                         "crescita ÷ rendimento del capitale a regime; rendimento a regime: prudente = WACC (la crescita "
                         "non crea valore), base = a metà tra WACC e il rendimento del modello, favorevole = rendimento "
                         f"del modello, al massimo {P['roicTCap'] * 100:g}%"),
    ("Scenari", f"prudente e favorevole: crescita iniziale ∓ il maggiore tra {P['gSpreadAbs'] * 100:g} punti e il "
                f"{P['gSpreadRel'] * 100:g}% della crescita base; margine a regime −{P['mPrudentRel'] * 100:g}% (prudente) o "
                f"+{P['mFavRel'] * 100:g}% (favorevole, al massimo {P['mCap'] * 100:g}%) del margine base; capitale ×{P['s2cPrudent']:g} "
                f"o ×{P['s2cFav']:g} di efficienza; stesso tasso di sconto; nessuna probabilità"),
    ("Ammissibilità", f"WACC almeno {P['minSpread'] * 100:g} punti sopra la crescita terminale, crescita terminale non "
                      "sopra il tasso privo di rischio, rendimento a regime sopra la crescita terminale, tasse e "
                      "margini tra 0 e 100%"),
    ("Affidabilità", f"«molto sensibile» se il valore terminale supera il {P['tvHeavy'] * 100:g}% del valore, se ±1 "
                     f"punto di WACC sposta il valore di oltre il {P['sensHigh'] * 100:g}%, se lo scenario favorevole "
                     f"vale più di {P['spreadHigh']:g} volte il prudente o se il prudente non è positivo; «non valutabile» "
                     f"con margini negativi o distanti oltre {P['unstableRange'] * 100:g} punti in 3 anni o cassa operativa "
                     "negativa"),
    ("Azioni", "azioni diluite dell'ultimo trimestre confrontate con quelle implicite nella capitalizzazione: si usa il "
               f"numero più alto; oltre il {P['sharesTol'] * 100:g}% di differenza valutazione parziale, oltre il "
               f"{P['sharesMaxGap'] * 100:g}% dati insufficienti (salvo un rapporto ADR intero)"),
]

STATUS = {
    "adeguata": "Valutazione calcolabile con dati adeguati",
    "parziale": "Valutazione parziale",
    "sensibile": "Valutazione molto sensibile alle ipotesi",
    "dati_insufficienti": "Dati insufficienti",
    "non_affidabile": "Non valutabile con affidabilità sufficiente",
    "non_appropriato": "Modello non appropriato per la società",
}
COMPUTED = ("adeguata", "parziale", "sensibile")
POSITION = {
    "sotto_prudente": "Prezzo sotto lo scenario prudente",
    "prudente_base": "Prezzo tra scenario prudente e base",
    "base_favorevole": "Prezzo tra scenario base e favorevole",
    "sopra_favorevole": "Prezzo sopra anche lo scenario favorevole",
}
GROUPS = [
    ("qualita_approfondire", "Qualità con prezzo da approfondire",
     "qualità «Elevata» o «Buona» (Fase 5A), solidità «Solida» o «Adeguata», valutazione adeguata o parziale, nessuna "
     "criticità bloccante, prezzo non sopra il valore dello scenario base"),
    ("qualita_impegnativa", "Qualità con valutazione impegnativa",
     "qualità «Elevata» o «Buona», prezzo sopra il valore dello scenario base"),
    ("incerta", "Elevata incertezza di valutazione",
     "valutazione molto sensibile alle ipotesi, oppure valore sopra il prezzo ma con criticità che rendono la stima poco "
     "affidabile (dati in ritardo, solidità a rischio, qualità debole, investimenti fuori norma, crescita oltre il limite)"),
    ("altre", "Altre società valutate", "qualità non elevata, senza criticità bloccanti"),
    ("nessuna_stima", "Nessuna stima affidabile", "modello non appropriato, dati insufficienti o flussi non rappresentativi"),
]
SCEN = [("prudente", "Prudente"), ("base", "Base"), ("favorevole", "Favorevole")]


class Invalid(Exception):
    """An assumption that is mathematically or economically not admissible."""


# ---------------------------------------------------------------- small helpers

def nice(x):
    """Rounded value for the page (no false precision): 2 significant digits below 1,000, 3 above."""
    if not _num(x) or x == 0:
        return x
    digits = 2 if abs(x) < 1000 else 3
    k = digits - 1 - int(math.floor(math.log10(abs(x))))
    v = round(x, k)
    return int(v) if k <= 0 else v


def usd(x, rate):
    return x * rate if _num(x) and _num(rate) else None


def pc(x, d=0):
    return f"{it(x * 100, d)}%"


def spc(x, d=0):
    return f"{sgn(x * 100, d)}%"


# ---------------------------------------------------------------- the DCF (pure functions)

def check(a):
    """Raises Invalid with the reason if an assumption is not admissible."""
    why = []
    if not (_num(a["wacc"]) and 0 < a["wacc"] < 1):
        why.append("tasso di sconto fuori dall'intervallo 0–100%")
    elif a["wacc"] - a["gT"] < P["minSpread"]:
        why.append(f"tasso di sconto ({pc(a['wacc'], 1)}) non abbastanza sopra la crescita terminale ({pc(a['gT'], 1)})")
    if _num(a.get("rf")) and a["gT"] > a["rf"] + 1e-9:
        why.append(f"crescita terminale ({pc(a['gT'], 1)}) sopra il tasso privo di rischio ({pc(a['rf'], 1)})")
    if not (0 <= a["tax"] < 1):
        why.append("aliquota fiscale fuori dall'intervallo 0–100%")
    if not (a["s2c"] > 0):
        why.append("rapporto ricavi/capitale non positivo")
    if not (a["roicT"] > a["gT"]):
        why.append("rendimento del capitale a regime non superiore alla crescita terminale (reinvestimento oltre il 100%)")
    if not (-1 < a["g1"] < 1) or not (-1 < a["gT"] < 1):
        why.append("crescita fuori dall'intervallo ammesso")
    if not (a["m0"] < 1 and a["mT"] < 1):
        why.append("margine operativo pari o superiore al 100%")
    if not (_num(a["rev0"]) and a["rev0"] > 0):
        why.append("ricavi di partenza non positivi")
    if why:
        raise Invalid("; ".join(why))


def project(a):
    """Explicit years and terminal value. a: rev0, m0, mT, g1, gT, wacc, tax, s2c, roicT, years. Returns EV and the
    pieces (all in the currency of rev0, here USD)."""
    check(a)
    n = a.get("years", P["years"])
    rev, pv, rows = a["rev0"], 0.0, []
    for t in range(1, n + 1):
        g = a["g1"] + (a["gT"] - a["g1"]) * (t - 1) / n
        new = rev * (1 + g)
        m = a["m0"] + (a["mT"] - a["m0"]) * t / n
        nopat = new * m * (1 - a["tax"])
        reinv = max(0.0, (new - rev) / a["s2c"])
        fcff = nopat - reinv
        disc = (1 + a["wacc"]) ** t
        pv += fcff / disc
        rows.append({"year": t, "growth": g, "revenue": new, "margin": m, "nopat": nopat, "reinvestment": reinv,
                     "fcff": fcff, "pv": fcff / disc})
        rev = new
    nopat_t = rev * (1 + a["gT"]) * a["mT"] * (1 - a["tax"])
    rr = a["gT"] / a["roicT"]
    tv = nopat_t * (1 - rr) / (a["wacc"] - a["gT"])
    pv_tv = tv / (1 + a["wacc"]) ** n
    ev = pv + pv_tv
    return {"years": rows, "pvExplicit": pv, "terminal": tv, "pvTerminal": pv_tv, "ev": ev,
            "tvShare": pv_tv / ev if ev > 0 else None, "terminalReinvestRate": rr, "revEnd": rev,
            "revMultiple": rev / a["rev0"]}


def per_share(ev, bridge, shares):
    """Equity value and value per share: EV + cash - debt - minorities - preferred, / diluted shares."""
    eq = ev + bridge["cash"] - bridge["debt"] - bridge.get("minority", 0.0) - bridge.get("preferred", 0.0)
    return eq, eq / shares


def value(a, bridge, shares):
    return per_share(project(a)["ev"], bridge, shares)[1]


def roic_model(m, tax, s2c):
    """Return on the capital added in the explicit years: margin x (1 - tax) x sales-to-capital."""
    return m * (1 - tax) * s2c


def terminal_roic(kind, m, tax, s2c, wacc, gT):
    rm = roic_model(m, tax, s2c)
    cap = P["roicTCap"]
    if rm <= wacc:
        r = rm                                   # growth does not create value: the terminal return stays as it is
    elif kind == "prudente":
        r = wacc
    elif kind == "base":
        r = wacc + (min(rm, cap) - wacc) / 2 if cap > wacc else wacc
    else:
        r = max(min(rm, cap), wacc)
    return max(r, gT + 0.01)


def scenarios(base):
    """The three internally coherent sets of assumptions from the base inputs (growth, margin, capital efficiency
    change together; same discount rate and terminal growth)."""
    out = {}
    g1, mT, s2c = base["g1"], base["mT"], base["s2c"]
    dg = max(P["gSpreadAbs"], P["gSpreadRel"] * abs(g1))
    for kind, _ in SCEN:
        a = dict(base)
        if kind == "prudente":
            a["g1"] = max(g1 - dg, P["gPrudentFloor"])
            a["mT"] = mT * (1 - P["mPrudentRel"])
            a["s2c"] = s2c * P["s2cPrudent"]
        elif kind == "favorevole":
            a["g1"] = min(g1 + dg, P["gFavCap"])
            a["mT"] = min(mT * (1 + P["mFavRel"]), max(P["mCap"], mT))
            a["s2c"] = s2c * P["s2cFav"]
        a["roicT"] = terminal_roic(kind, a["mT"], a["tax"], a["s2c"], a["wacc"], a["gT"])
        a["kind"] = kind
        out[kind] = a
    return out


def sensitivity(base, bridge, shares):
    """Value per share of the base scenario when one assumption moves (the others fixed)."""
    v0 = value(base, bridge, shares)
    rows = []
    for key, lab, steps, fmt in (("wacc", "Tasso di sconto", (-0.01, 0.01), "punti"),
                                 ("gT", "Crescita terminale", (-0.005, 0.005), "punti"),
                                 ("mT", "Margine operativo a regime", (-0.02, 0.02), "punti"),
                                 ("g1", "Crescita dei ricavi del primo anno", (-0.05, 0.05), "punti")):
        cells = []
        for d in steps:
            a = dict(base)
            a[key] = base[key] + d
            if key in ("mT", "s2c"):
                a["roicT"] = terminal_roic("base", a["mT"], a["tax"], a["s2c"], a["wacc"], a["gT"])
            try:
                v = value(a, bridge, shares)
                cells.append({"delta": d, "value": v, "change": (v / v0 - 1) if v0 > 0 else None})
            except Invalid as e:
                cells.append({"delta": d, "value": None, "change": None, "invalid": str(e)})
        rows.append({"key": key, "label": lab, "cells": cells})
    return v0, rows


def solve(fn, target, lo, hi, n=60):
    """Bisection for an increasing fn: x with fn(x) = target in [lo, hi], or None if outside the range."""
    flo, fhi = fn(lo), fn(hi)
    if target < flo or target > fhi:
        return None
    for _ in range(n):
        mid = (lo + hi) / 2
        if fn(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def reverse(base, bridge, shares, price):
    """What the price implies (D2): the first-year revenue growth with the base margins, and the long-run margin with
    the base growth. Declared unstable or not unique instead of forcing a number."""
    out = {}

    def by_growth(g):
        a = dict(base, g1=g)
        return value(a, bridge, shares)
    lo, hi = -0.30, 0.95
    grid = [lo + (hi - lo) * i / 26 for i in range(27)]
    try:
        vals = [by_growth(g) for g in grid]
    except Invalid as e:
        vals, out["growthNote"] = None, f"calcolo non possibile: {e}"
    if vals is not None:
        inc = all(vals[i + 1] >= vals[i] for i in range(len(vals) - 1))
        rm = roic_model(base["mT"], base["tax"], base["s2c"])
        if not inc or rm <= base["wacc"]:
            out["growth"] = None
            out["growthNote"] = (f"con queste ipotesi la crescita non crea valore (rendimento del capitale aggiunto "
                                 f"{pc(rm, 0)} non sopra il tasso di sconto {pc(base['wacc'], 1)}): il calcolo inverso "
                                 "sulla crescita non è univoco")
        else:
            g = solve(by_growth, price, lo, hi)
            out["growth"] = g
            if g is None:
                out["growthNote"] = ("il prezzo richiederebbe una crescita iniziale dei ricavi oltre il +95% il primo anno" if price > vals[-1]
                                     else "il prezzo è sotto il valore anche con ricavi in calo del 30% il primo anno")
            else:
                a = dict(base, g1=g)
                out["growthRevMultiple"] = project(a)["revMultiple"]

    def by_margin(m):
        a = dict(base, mT=m)
        a["roicT"] = terminal_roic("base", m, a["tax"], a["s2c"], a["wacc"], a["gT"])
        return value(a, bridge, shares)
    try:
        grid = [0.0 + 0.9 * i / 30 for i in range(31)]
        vals = [by_margin(m) for m in grid]
        if not all(vals[i + 1] >= vals[i] for i in range(len(vals) - 1)):
            out["margin"], out["marginNote"] = None, "valore non crescente con il margine: calcolo inverso non univoco"
        else:
            m = solve(by_margin, price, 0.0, 0.9)
            out["margin"] = m
            if m is None:
                out["marginNote"] = ("il prezzo richiederebbe un margine operativo oltre il 90%" if price > vals[-1]
                                     else "il prezzo è sotto il valore anche con margine nullo")
    except Invalid as e:
        out["margin"], out["marginNote"] = None, f"calcolo non possibile: {e}"
    return out


# ---------------------------------------------------------------- inputs of one company (point in time)

def shares_check(diluted, implied):
    """(shares in units of the quoted instrument, adr ratio, problem, partial note)."""
    if not (_num(diluted) and diluted > 0 and _num(implied) and implied > 0):
        return None, None, "numero di azioni non disponibile", None
    r = diluted / implied
    if r > 1.5:
        n = round(r)
        if abs(r / n - 1) <= P["sharesTol"]:
            adj = diluted / n
            return max(adj, implied), n, None, (f"1 titolo quotato = {n} azioni ordinarie (rapporto stimato dal confronto tra "
                                                "azioni del bilancio e capitalizzazione)")
        return None, None, f"azioni del bilancio e della capitalizzazione incoerenti (rapporto {it(r, 2)})", None
    if abs(r - 1) > P["sharesMaxGap"]:
        return None, None, f"azioni del bilancio e della capitalizzazione incoerenti (rapporto {it(r, 2)})", None
    note = None
    if abs(r - 1) > P["sharesTol"]:
        note = (f"azioni diluite del bilancio e azioni implicite nella capitalizzazione differiscono del "
                f"{it(abs(r - 1) * 100, 0)}%: si usa il numero più alto (stima prudente per azione)")
    return max(diluted, implied), 1, None, note


def own_s2c(entry, now, seen):
    """The company's own sales-to-capital measures, each bounded to [s2cMin, s2cMax]: {"marginal", "book"} (missing keys
    when not computable). Marginal = revenue added in the last 3 fiscal years / net reinvestment of those years (capex -
    depreciation + working capital), only if revenue grew at least 10% (a small change makes the ratio noise); book =
    revenue / (equity + debt - cash + minorities), only with a positive invested capital."""
    Pp = ie.usable(entry, now, seen)
    fy, out = Pp["FY"], {}
    bound = lambda x: min(max(x, P["s2cMin"]), P["s2cMax"])
    if len(fy) >= 4 and 1050 <= ie._days(fy[0]["end"], fy[3]["end"]) <= 1150 and _num(fy[0].get("revenue")) \
            and _num(fy[3].get("revenue")) and fy[3]["revenue"] > 0:
        d_rev = fy[0]["revenue"] - fy[3]["revenue"]
        parts = [(-y["capex"] - y["da"] - (y.get("wcChange") or 0)) for y in fy[:3] if _num(y.get("capex")) and _num(y.get("da"))]
        if len(parts) == 3 and d_rev >= 0.10 * fy[3]["revenue"]:
            reinv = sum(parts)
            out["marginal"] = bound(d_rev / reinv) if reinv > 0 else P["s2cMax"]
    rev, _ = ie.flow(Pp, "revenue", entry, seen)
    eq, _ = ie.stock(Pp, "equity", entry, seen)
    debt, _ = ie.stock(Pp, "totalDebt", entry, seen)
    cash, _ = ie.stock(Pp, "cash", entry, seen)
    mino, _ = ie.stock(Pp, "minority", entry, seen)
    if all(_num(x) for x in (rev, eq, debt, cash)) and rev > 0:
        ic = eq + debt - cash + (mino or 0)
        if ic > 0:
            out["book"] = bound(rev / ic)
    return out


def robust_s2c(own, peer):
    """Median of the available measures (marginal, book, median of the companies with the same model): a single
    distorted measure (goodwill of acquisitions, a capex cycle, buybacks) does not decide alone."""
    vals = dict(own)
    if _num(peer):
        vals["peer"] = peer
    if not vals:
        return None, None, False
    lab = {"marginal": "marginale 3 esercizi", "book": "di bilancio", "peer": "mediana delle società simili"}
    src = "mediana di: " + ", ".join(f"{lab[k]} {it(v, 2)}" for k, v in vals.items())
    return statistics.median(vals.values()), src, not own


def inputs(item, entry, seen, info, an, fx, rates, now, peer_s2c, close):
    """Everything the DCF needs for one company, each figure with its source; and why it cannot be valued."""
    model = item["model"]["id"]
    out = {"problems": [], "partial": [], "notes": [], "blockers": [], "used": [], "missing": []}
    if model in ("financial", "utility"):
        out["status"] = "non_appropriato"
        out["problems"].append("un DCF industriale non è adatto: " + ("depositi, crediti e capitale regolamentare contano più "
                               "del flusso di cassa" if model == "financial" else "rendimenti fissati dal regolatore e debito "
                               "strutturale richiedono un modello sulla base tariffaria, che qui non c'è"))
        return out
    if not entry or not (entry.get("FY") or entry.get("Q")):
        out["status"] = "dati_insufficienti"
        out["problems"].append("bilanci non disponibili")
        return out
    if any(x.startswith("Dati obsoleti") for x in item.get("dataIssues") or []):
        out["status"] = "dati_insufficienti"
        out["problems"].append("bilanci obsoleti: " + next(x for x in item["dataIssues"] if x.startswith("Dati obsoleti")))
        return out
    Pp = ie.usable(entry, now, seen)
    if Pp["Q"] and ie._days(now.date().isoformat(), Pp["Q"][0]["end"]) > ie.STALE_Q_DAYS:
        Pp["Q"] = []
        out["partial"].append("trimestri non recenti (società che pubblica semestrali): flussi dall'ultimo bilancio annuale")
    cur = item["currency"]["accounts"]
    rate = 1.0 if cur == "USD" else (fx.get(cur) or {}).get("rate")
    if not _num(rate):
        out["status"] = "dati_insufficienti"
        out["problems"].append(f"cambio {cur}/USD non disponibile")
        return out
    out["fx"] = None if cur == "USD" else {"currency": cur, "rate": rate, "date": (fx.get(cur) or {}).get("date"),
                                          "source": f"Yahoo Finance, {(fx.get(cur) or {}).get('symbol')}, chiusura giornaliera"}
    if cur != "USD":
        out["blockers"].append(f"bilanci in {cur}: cambio futuro e rischio paese non sono nel modello")
        out["partial"].append(f"bilanci in {cur} convertiti in dollari al cambio del {day_it(out['fx']['date'])} "
                              f"({it(rate, 4)}), lo stesso per tutti gli anni; rischio paese non incluso nel tasso di sconto")
    rev, rp = ie.flow(Pp, "revenue", entry, seen)
    oi, op = ie.flow(Pp, "operatingIncome", entry, seen)
    ocf, _ = ie.flow(Pp, "ocf", entry, seen)
    if not (_num(rev) and rev > 0 and _num(oi)):
        out["status"] = "dati_insufficienti"
        out["problems"].append("ricavi o utile operativo non disponibili")
        return out
    m0 = oi / rev
    fy = Pp["FY"]
    fy_m = [(y["end"], y["operatingIncome"] / y["revenue"]) for y in fy[:3]
            if _num(y.get("revenue")) and y["revenue"] > 0 and _num(y.get("operatingIncome"))]
    out.update(rev0Acc=rev, revPer=rp, m0=m0, opPer=op, fyMargins=fy_m, cur=cur, rate=rate)
    if (rp or {}).get("type") == "FY" and not any("semestrali" in x for x in out["partial"]):
        out["partial"].append("mancano 4 trimestri consecutivi: ricavi e margini dall'ultimo bilancio annuale")
    allm = [m0] + [m for _, m in fy_m]
    if m0 <= 0:
        out["status"] = "non_affidabile"
        out["problems"].append(f"utile operativo negativo o nullo negli ultimi 12 mesi (margine {pc(m0, 1)}): servirebbe "
                               "inventare quando e quanto diventerà positivo")
        return out
    if any(m < 0 for _, m in fy_m):
        out["status"] = "non_affidabile"
        out["problems"].append("margine operativo negativo in almeno uno degli ultimi 3 esercizi: flussi non rappresentativi")
        return out
    if max(allm) - min(allm) > P["unstableRange"]:
        out["status"] = "non_affidabile"
        out["problems"].append(f"margini operativi molto instabili (da {pc(min(allm), 0)} a {pc(max(allm), 0)} tra ultimi "
                               "12 mesi e ultimi 3 esercizi)")
        return out
    if _num(ocf) and ocf <= 0:
        out["status"] = "non_affidabile"
        out["problems"].append("flusso di cassa operativo negativo negli ultimi 12 mesi")
        return out
    mT = statistics.median(allm)
    out["mT"] = mT

    # tax
    y0 = fy[0] if fy else {}
    tax, tax_src = P["taxDefault"], f"aliquota di riferimento {pc(P['taxDefault'])}"
    if _num(y0.get("taxProvision")) and _num(y0.get("pretaxIncome")) and y0["pretaxIncome"] > 0:
        eff = y0["taxProvision"] / y0["pretaxIncome"]
        if P["taxMin"] <= eff <= P["taxMax"]:
            tax, tax_src = eff, f"aliquota effettiva dell'esercizio al {day_it(y0['end'])}"
        else:
            tax_src = f"aliquota effettiva {pc(eff, 0)} fuori dall'intervallo: usata quella di riferimento {pc(P['taxDefault'])}"
    out.update(tax=tax, taxSrc=tax_src)

    # balance sheet bridge (USD)
    debt, dp = ie.stock(Pp, "totalDebt", entry, seen)
    cash, _ = ie.stock(Pp, "cash", entry, seen)
    mino, _ = ie.stock(Pp, "minority", entry, seen)
    pref, _ = ie.stock(Pp, "preferred", entry, seen)
    if not (_num(debt) and _num(cash)):
        out["status"] = "dati_insufficienti"
        out["problems"].append("debito o liquidità non disponibili")
        return out
    out["bridge"] = {"cash": usd(cash, rate), "debt": usd(debt, rate), "minority": usd(mino, rate) or 0.0,
                     "preferred": usd(pref, rate) or 0.0, "period": dp}
    out["notes"].append("il debito comprende i leasing mentre il margine operativo già sottrae i canoni: valore leggermente prudente")

    # market data and shares
    mcap = (info or {}).get("marketCap")
    if not (_num(mcap) and mcap > 0 and _num(close) and close > 0):
        out["status"] = "dati_insufficienti"
        out["problems"].append("capitalizzazione o prezzo non disponibili")
        return out
    qd = Pp["Q"][0].get("dilutedShares") if Pp["Q"] else None
    dil = qd if _num(qd) else (fy[0].get("dilutedShares") if fy else None)
    shares, adr, prob, note = shares_check(dil, mcap / close)
    if prob:
        out["status"] = "dati_insufficienti"
        out["problems"].append(prob)
        return out
    if note:
        (out["partial"] if adr == 1 else out["notes"]).append(note)
    out.update(shares=shares, adr=adr, mcap=mcap, sharesDiluted=dil, sharesImplied=mcap / close)
    sh = [(y["end"], y.get("dilutedShares")) for y in fy[:4] if _num(y.get("dilutedShares"))]
    if len(sh) >= 2:
        yrs = max(ie._days(sh[0][0], sh[-1][0]) / 365.25, 0.5)
        out["dilution"] = {"perYear": (sh[0][1] / sh[-1][1]) ** (1 / yrs) - 1, "from": sh[-1][0], "to": sh[0][0]}

    # discount rate
    rf = (rates or {}).get("rf") or {}
    if not _num(rf.get("rate")):
        out["status"] = "dati_insufficienti"
        out["problems"].append("tasso privo di rischio (Treasury a 10 anni) non disponibile")
        return out
    beta_raw = (info or {}).get("beta")
    if _num(beta_raw):
        beta = min(max(P["betaBlume"] * beta_raw + (1 - P["betaBlume"]), P["betaMin"]), P["betaMax"])
    else:
        beta = P["betaMissing"]
        out["partial"].append(f"beta non disponibile: usato {P['betaMissing']:g}")
    ke = rf["rate"] + beta * P["erp"]
    interest, _ = ie.flow(Pp, "interestExpense", entry, seen)
    kd_src = "interessi passivi ÷ debito"
    if _num(interest) and debt > 0 and abs(interest) > 0:
        kd = min(max(abs(interest) / debt, rf["rate"]), rf["rate"] + P["kdSpreadMax"])
    else:
        kd, kd_src = rf["rate"] + P["kdSpreadDefault"], "interessi non disponibili: tasso privo di rischio + 1,5 punti"
    D, E = usd(debt, rate), mcap
    wd = D / (D + E) if D + E > 0 else 0
    if kd_src.startswith("interessi non") and wd > 0.2:
        out["partial"].append("costo del debito stimato senza gli interessi passivi, con un debito rilevante")
    wacc = (1 - wd) * ke + wd * kd * (1 - tax)
    out["discount"] = {"rf": rf["rate"], "rfDate": rf.get("date"), "rfSource": rf.get("source"), "betaRaw": beta_raw,
                       "beta": beta, "erp": P["erp"], "ke": ke, "kd": kd, "kdSrc": kd_src, "wd": wd, "wacc": wacc}

    # sales to capital
    s2c, s2c_src, only_peer = robust_s2c(own_s2c(entry, now, seen), peer_s2c)
    if s2c is None:
        out["status"] = "dati_insufficienti"
        out["problems"].append("rapporto ricavi/capitale non stimabile (né dati propri né società simili)")
        return out
    if only_peer:
        out["partial"].append("rapporto ricavi/capitale solo dalla mediana delle società simili")
    out.update(s2c=s2c, s2cSrc=s2c_src)

    # first-year growth: consensus (implied annual rate from the last 12 months to the next fiscal year), else history
    g1, g_src = None, None
    rv = (an or {}).get("rev") or {}
    nxt, cur_y = rv.get("+1y") or {}, rv.get("0y") or {}
    if fy and _num(nxt.get("avg")) and (nxt.get("numberOfAnalysts") or 0) >= P["consensusMinAnalysts"]:
        ago = cur_y.get("yearAgoRevenue")
        fy0 = fy[0].get("revenue")
        chain = nxt.get("yearAgoRevenue")
        coherent = not _num(chain) or (_num(cur_y.get("avg")) and cur_y["avg"] > 0 and abs(chain / cur_y["avg"] - 1) <= 0.05)
        if _num(ago) and _num(fy0) and fy0 > 0 and abs(ago / fy0 - 1) <= 0.05 and coherent:
            end_next = date.fromisoformat(fy[0]["end"]).replace(year=int(fy[0]["end"][:4]) + 2)
            base_end = date.fromisoformat((rp or {}).get("end") or fy[0]["end"])
            yrs = (end_next - base_end).days / 365.25
            if yrs >= 0.75 and nxt["avg"] > 0:
                g1 = (nxt["avg"] / rev) ** (1 / yrs) - 1
                g_src = (f"consenso di {int(nxt['numberOfAnalysts'])} analisti sui ricavi dell'esercizio che chiude a "
                         f"{ie.MONTHS[end_next.month - 1]} {end_next.year} ({ie.big(nxt['avg'], cur)}), come crescita "
                         f"annua dai ricavi degli ultimi 12 mesi")
    if g1 is None:
        ind = {i["key"]: i["value"] for i in item.get("indicators") or []}
        hist = next((ind.get(k) for k in ("revGrowthQ", "revGrowthFY", "revCagr3") if _num(ind.get(k))), None)
        if hist is not None:
            g1, g_src = hist / 100, "ultima crescita dei ricavi misurata (consenso degli analisti non utilizzabile)"
            out["partial"].append("crescita iniziale dai dati storici: consenso sui ricavi non disponibile o non coerente")
    if g1 is None:
        out["status"] = "dati_insufficienti"
        out["problems"].append("crescita dei ricavi non stimabile (né consenso né storico)")
        return out
    g_raw = g1
    if g1 > P["g1Max"]:
        g1 = P["g1Max"]
        out["blockers"].append(f"crescita attesa ({spc(g_raw)}) oltre il limite del modello: ipotesi base ridotta a "
                               f"{spc(g1)}")
        out["partial"].append(f"crescita iniziale limitata a {spc(g1)} (attesa {spc(g_raw)})")
    elif g1 < P["g1Min"]:
        g1 = P["g1Min"]
        out["partial"].append(f"crescita iniziale limitata a {spc(g1)} (misurata {spc(g_raw)})")
    out.update(g1=g1, g1Raw=g_raw, g1Src=g_src)

    # observed reinvestment vs the model (capex and working capital of the last 12 months)
    capex, _ = ie.flow(Pp, "capex", entry, seen)
    da, _ = ie.flow(Pp, "da", entry, seen)
    wc, _ = ie.flow(Pp, "wcChange", entry, seen)
    sbc, _ = ie.flow(Pp, "sbc", entry, seen)
    fcf, _ = ie.flow(Pp, "fcf", entry, seen)
    nopat0 = oi * (1 - tax)
    obs = (-capex - da - (wc or 0)) if _num(capex) and _num(da) else None
    model_y1 = rev * g1 / s2c if g1 > 0 else 0.0
    out["reinvest"] = {"observed": usd(obs, rate), "observedShare": obs / nopat0 if _num(obs) and nopat0 > 0 else None,
                       "modelYear1": usd(model_y1, rate), "capexShare": -capex / rev if _num(capex) else None,
                       "daShare": da / rev if _num(da) else None}
    if _num(obs) and nopat0 > 0 and obs / nopat0 > P["reinvShare"] and obs > P["reinvGap"] * max(model_y1, 0):
        out["blockers"].append(f"investimenti netti attuali ({ie.big(obs, cur)}, {pc(obs / nopat0)} dell'utile operativo "
                               "dopo le tasse) molto sopra quelli del modello: la stima presume che tornino nella norma")
    out["cash"] = {"ocf": usd(ocf, rate), "fcf": usd(fcf, rate), "sbc": usd(sbc, rate),
                   "fcfEconomic": usd(fcf - sbc, rate) if _num(fcf) and _num(sbc) else None,
                   "sbcShare": sbc / rev if _num(sbc) else None}
    if _num(fcf) and _num(sbc) and nopat0 > 0 and (fcf - sbc) / rev > nopat0 / rev + P["cashGap"]:
        out["partial"].append(f"flusso di cassa economico (cassa libera − compensi in azioni, {pc((fcf - sbc) / rev)} dei ricavi) "
                              f"molto sopra l'utile operativo dopo le tasse ({pc(nopat0 / rev)}): per esempio incassi anticipati "
                              "degli abbonamenti, che il modello basato sull'utile non conta (stima prudente)")
    out["rev0"] = usd(rev, rate)
    out["status"] = None
    return out


# ---------------------------------------------------------------- one company

def scenario_text(kind, a, base):
    g, m = a["g1"], a["mT"]
    if kind == "prudente":
        return {"plausible": f"se la crescita dei ricavi scende verso il {spc(g)} nel prossimo anno e il margine operativo "
                             f"si ferma intorno al {pc(m)} (concorrenza, domanda più debole, costi più alti)",
                "implausible": f"se i prossimi trimestri confermano una crescita vicina al {spc(base['g1'])} con margini stabili"}
    if kind == "favorevole":
        return {"plausible": f"se la crescita resta vicina al {spc(g)} il prossimo anno e il margine sale verso il {pc(m)} "
                             "con meno capitale per ogni dollaro di ricavi",
                "implausible": "se la crescita rallenta come negli ultimi trimestri o il margine è già vicino al massimo storico"}
    return {"plausible": f"se ricavi e margini seguono il consenso o gli ultimi dati: {spc(g)} il primo anno, margine "
                         f"verso il {pc(m)}",
            "implausible": "se la prossima trimestrale si allontana molto da queste ipotesi"}


def valuate(item, inp, price, price_info):
    """The valuation of one company from its inputs; item = the phase 5A analysis (only read)."""
    q = item["dims"]["quality"]["state"]
    sol = item["dims"]["solidity"]["state"]
    res = {"ticker": item["ticker"], "name": item["name"], "sector": item["sector"], "model": item["model"],
           "fundamental": {"profile": item["profile"], "quality": q, "growth": item["dims"]["growth"]["state"],
                           "solidity": sol, "valuation5A": item["dims"]["valuation"]["state"],
                           "completeness": item["completeness"]["state"]},
           "price": {"value": price, **price_info}, "currency": item["currency"],
           "dataDates": item["dataDates"], "lagging": item.get("lagging"), "nextEarnings": item.get("nextEarnings")}
    blockers = list(inp.get("blockers") or [])
    partial = list(inp.get("partial") or [])
    notes = list(inp.get("notes") or [])
    if item.get("lagging"):
        blockers.append(f"risultati annunciati il {day_it(item['lagging'])} non ancora nei bilanci della fonte: valutazione "
                        "provvisoria")
        partial.append(f"risultati del {day_it(item['lagging'])} non ancora inclusi")
    if sol in ("Fragile", "Da verificare"):
        blockers.append(f"solidità finanziaria «{sol}» (Fase 5A)")
    if q == "Debole":
        blockers.append("qualità aziendale «Debole» (Fase 5A)")
    res["status"] = inp.get("status")
    if res["status"] in ("non_appropriato", "dati_insufficienti", "non_affidabile"):
        res.update(statusLabel=STATUS[res["status"]], reasons=inp["problems"], group="nessuna_stima", scenarios=None,
                   blockers=blockers, partial=partial, notes=notes,
                   summary=f"{STATUS[res['status']]}: {inp['problems'][0]}.",
                   monitor=item.get("monitor", [])[:3], risks=item.get("weaknesses", [])[:3])
        return res
    d = inp["discount"]
    base = {"rev0": inp["rev0"], "m0": inp["m0"], "mT": inp["mT"], "g1": inp["g1"], "gT": P["gTerminal"],
            "wacc": d["wacc"], "rf": d["rf"], "tax": inp["tax"], "s2c": inp["s2c"], "years": P["years"]}
    sc = scenarios(base)
    bridge, shares = inp["bridge"], inp["shares"]
    out_sc = {}
    try:
        for kind, lab in SCEN:
            a = sc[kind]
            pr = project(a)
            eq, vps = per_share(pr["ev"], bridge, shares)
            out_sc[kind] = {
                "kind": kind, "label": lab, "assumptions": {k: a[k] for k in ("g1", "gT", "m0", "mT", "tax", "s2c", "wacc",
                                                                                 "roicT")},
                "growthPath": [r["growth"] for r in pr["years"]], "revMultiple": pr["revMultiple"],
                "reinvestment5y": sum(r["reinvestment"] for r in pr["years"]),
                "reinvestShare": (sum(r["reinvestment"] for r in pr["years"]) / sum(r["nopat"] for r in pr["years"])
                                  if sum(r["nopat"] for r in pr["years"]) > 0 else None),
                "terminalReinvestRate": pr["terminalReinvestRate"],
                "ev": pr["ev"], "equity": eq, "perShare": vps, "display": nice(vps),
                "tvShare": pr["tvShare"], "pvExplicit": pr["pvExplicit"], "pvTerminal": pr["pvTerminal"],
                "years": pr["years"],
                "priceVsValue": (price / vps - 1) if _num(price) and vps > 0 else None,
                "text": scenario_text(kind, a, base),
            }
        v0, sens = sensitivity(sc["base"], bridge, shares)
        rv = reverse(sc["base"], bridge, shares, price) if _num(price) else {}
    except Invalid as e:
        res.update(status="non_affidabile", statusLabel=STATUS["non_affidabile"], reasons=[f"ipotesi non ammissibili: {e}"],
                   group="nessuna_stima", scenarios=None, blockers=blockers, partial=partial, notes=notes,
                   summary=f"Non valutabile: ipotesi non ammissibili ({e}).", monitor=item.get("monitor", [])[:3],
                   risks=item.get("weaknesses", [])[:3])
        return res
    vp, vb, vf = (out_sc[k]["perShare"] for k in ("prudente", "base", "favorevole"))
    # reliability
    sens_flags = []
    tv = out_sc["base"]["tvShare"]
    if tv is not None and tv > P["tvHeavy"]:
        sens_flags.append(f"il valore terminale pesa il {pc(tv)} del valore dello scenario base")
    w = next(r for r in sens if r["key"] == "wacc")
    swing = max((abs(c["change"]) for c in w["cells"] if _num(c.get("change"))), default=None)
    if swing is not None and swing > P["sensHigh"]:
        sens_flags.append(f"±1 punto di tasso di sconto sposta il valore base fino al {pc(swing)}")
    if vp <= 0:
        sens_flags.append("lo scenario prudente non dà un valore positivo")
    elif vf / vp > P["spreadHigh"]:
        sens_flags.append(f"lo scenario favorevole vale {it(vf / vp, 1)} volte il prudente")
    if vb <= 0:
        sens_flags.append("lo scenario base non dà un valore positivo")
    if out_sc["base"]["revMultiple"] > P["ambitiousRev"] or inp["mT"] > P["ambitiousMargin"]:
        notes.append("ipotesi base ambiziose: " + ", ".join(x for x in (
            f"ricavi × {it(out_sc['base']['revMultiple'], 1)} in 5 anni" if out_sc["base"]["revMultiple"] > P["ambitiousRev"] else None,
            f"margine operativo del {pc(inp['mT'])} mantenuto nel tempo" if inp["mT"] > P["ambitiousMargin"] else None) if x))
    status = "sensibile" if sens_flags else "parziale" if partial else "adeguata"
    res["status"] = status
    res["statusLabel"] = STATUS[status]
    res["reasons"] = sens_flags + partial
    # position of the price
    pos = None
    if _num(price):
        pos = ("sotto_prudente" if price < vp else "prudente_base" if price <= vb else "base_favorevole" if price <= vf
               else "sopra_favorevole")
    res["position"] = {"id": pos, "label": POSITION.get(pos)} if pos else None
    good_q = q in ("Elevata", "Buona")
    if status == "sensibile":
        group = "incerta"
    elif _num(price) and price <= vb and blockers:
        group = "incerta"
    elif good_q and _num(price) and price <= vb and sol in ("Solida", "Adeguata"):
        group = "qualita_approfondire"
    elif good_q and _num(price) and price > vb:
        group = "qualita_impegnativa"
    else:
        group = "altre"
    res["group"] = group
    # margin of safety and levels of interest (conditions, never orders)
    mos = {k: (out_sc[k]["perShare"] - price) / out_sc[k]["perShare"] if _num(price) and out_sc[k]["perShare"] > 0 else None
           for k, _ in SCEN}
    res["marginOfSafety"] = mos
    levels = []
    if status in ("adeguata", "parziale") and vb > 0:
        for k, lab in (("base", "base"), ("prudente", "prudente")):
            v = out_sc[k]["perShare"]
            if v > 0 and _num(price) and v < price:
                levels.append({"scenario": k, "price": v, "display": nice(v), "fromPrice": v / price - 1,
                               "text": f"Sotto circa {it(nice(v), 0 if v >= 10 else 1)} USD il prezzo sarebbe inferiore al "
                                       f"valore dello scenario {lab} ({spc(v / price - 1)} dal prezzo attuale), purché bilanci "
                                       "e ipotesi restino invariati: un livello per una nuova analisi, non un prezzo di acquisto."})
    res["levels"] = levels
    res.update(scenarios=out_sc, sensitivity=sens, reverse=rv, blockers=blockers, partial=partial, notes=notes,
               inputs={k: inp.get(k) for k in ("rev0", "revPer", "m0", "mT", "fyMargins", "tax", "taxSrc", "s2c", "s2cSrc",
                                               "g1", "g1Raw", "g1Src", "discount", "bridge", "shares", "adr", "sharesDiluted",
                                               "sharesImplied", "mcap", "dilution", "reinvest", "cash", "fx", "opPer")},
               range={"low": min(vp, vf), "base": vb, "high": max(vp, vf),
                      "display": [nice(vp), nice(vb), nice(vf)]})
    # summary in words
    ptxt = f"{it(price, 2)} USD" if _num(price) else "prezzo non disponibile"
    s = f"Prezzo {ptxt}: {POSITION[pos].lower().replace('prezzo ', '')}" if pos else "Prezzo non disponibile"
    s += f" (prudente ~{it(nice(vp), 0)}, base ~{it(nice(vb), 0)}, favorevole ~{it(nice(vf), 0)} USD per azione)."
    if rv.get("growth") is not None:
        s += (f" Il prezzo corrisponde a una crescita iniziale dei ricavi di circa {spc(rv['growth'])} con i margini dello "
              f"scenario base (ipotesi base {spc(inp['g1'])}).")
    elif rv.get("growthNote"):
        s += f" Calcolo inverso: {rv['growthNote']}."
    res["summary"] = s
    res["risks"] = _risks(res, inp, item, sens_flags)
    res["monitor"] = _monitor(res, inp, item)
    res["dataUsed"], res["dataMissing"] = _data_lists(inp, item)
    return res


def _risks(res, inp, item, flags):
    r = list(flags)
    r += res["blockers"]
    dil = inp.get("dilution")
    cash = inp.get("cash") or {}
    if _num(cash.get("sbcShare")) and cash["sbcShare"] >= 0.05:
        r.append(f"compensi in azioni pari al {pc(cash['sbcShare'], 1)} dei ricavi: già sottratti nell'utile operativo, ma "
                 "diluiscono i soci se non compensati da riacquisti")
    if dil and _num(dil["perYear"]) and dil["perYear"] > 0.01:
        r.append(f"azioni diluite in aumento del {pc(dil['perYear'], 1)} l'anno dal {day_it(dil['from'])}")
    r += [x for x in res["notes"] if x.startswith("ipotesi base ambiziose")]
    r += [w for w in item.get("weaknesses", [])[:2] if w not in r]
    return r[:7]


def _monitor(res, inp, item):
    b, p = res["scenarios"]["base"]["assumptions"], res["scenarios"]["prudente"]["assumptions"]
    m = [f"Crescita dei ricavi: lo scenario base ipotizza {spc(b['g1'])} il primo anno; verso {spc(p['g1'])} diventa più "
         "plausibile lo scenario prudente.",
         f"Margine operativo: ora {pc(inp['m0'], 1)}, base {pc(b['mT'], 1)} a regime, prudente {pc(p['mT'], 1)}."]
    if item.get("nextEarnings"):
        m.append(f"Prossima trimestrale il {day_it(item['nextEarnings'])}: confrontare ricavi e margine con queste ipotesi.")
    if item.get("lagging"):
        m.append(f"Risultati del {day_it(item['lagging'])} non ancora nei bilanci della fonte: la valutazione cambierà.")
    rei = inp.get("reinvest") or {}
    if any(x.startswith("investimenti netti attuali") for x in res["blockers"]) and _num(rei.get("capexShare")):
        m.append(f"Investimenti: oggi {pc(rei['capexShare'], 1)} dei ricavi; il modello presume che tornino proporzionati "
                 "alla crescita.")
    w = next(r for r in res["sensitivity"] if r["key"] == "wacc")
    up = next((c for c in w["cells"] if c["delta"] > 0 and _num(c.get("change"))), None)
    if up:
        m.append(f"Tassi d'interesse: con il Treasury a 10 anni ora al {pc(inp['discount']['rf'], 1)}, un punto in più di "
                 f"tasso di sconto cambia il valore base del {spc(up['change'])}.")
    return m


def _data_lists(inp, item):
    used = [f"Ricavi e margine operativo: {(inp.get('revPer') or {}).get('label', '')}"
            + (f" (annunciati il {day_it(inp['revPer']['announced'])})" if (inp.get('revPer') or {}).get('announced') else ""),
            f"Debito, liquidità, minoranze: {(inp['bridge'].get('period') or {}).get('label', '')}",
            f"Azioni diluite e capitalizzazione: dati del giorno del {day_it(item['dataDates']['marketData'])}"
            if item["dataDates"].get("marketData") else "Azioni diluite e capitalizzazione",
            f"Treasury a 10 anni: {pc(inp['discount']['rf'], 2)} del {day_it(inp['discount']['rfDate'])}",
            f"Beta: {it(inp['discount']['betaRaw'], 2) if _num(inp['discount']['betaRaw']) else 'non disponibile'} (Yahoo)",
            f"Crescita iniziale: {inp['g1Src']}"]
    if inp.get("fx"):
        used.append(f"Cambio {inp['fx']['currency']}/USD {it(inp['fx']['rate'], 4)} del {day_it(inp['fx']['date'])} ({inp['fx']['source']})")
    missing = list(inp.get("partial") or [])
    return used, missing


# ---------------------------------------------------------------- everything

def analyze_all(inv, fund, infos, analysts, now, quotes=None, closes=None):
    """inv: result of investment_engine.analyze_all (phase 5A, only read); fund: fundamentals cache; infos/analysts:
    data of the day; quotes: {ticker: {"price", "time"}} for the page (current price); closes: {ticker: {"close",
    "date"}} of the last closed session (the reference of the diary and of the share count check)."""
    data, seen_all, fx, rates = fund.get("data") or {}, fund.get("firstSeen") or {}, fund.get("fx") or {}, fund.get("rates") or {}
    items = {x["ticker"]: x for x in inv["items"]}
    # median sales-to-capital per model (only for companies whose own invested capital is not positive)
    s2c_by_model = {}
    for t, x in items.items():
        own = own_s2c(data.get(t) or {}, now, seen_all.get(t)) if data.get(t) else {}
        s = statistics.median(own.values()) if own else None
        if _num(s):
            s2c_by_model.setdefault(x["model"]["id"], []).append(s)
    peer = {k: statistics.median(v) for k, v in s2c_by_model.items() if len(v) >= 5}
    out = []
    for t, x in items.items():
        cl = (closes or {}).get(t) or {}
        q = (quotes or {}).get(t) or {}
        close = cl.get("close") if _num(cl.get("close")) else x.get("price")
        if _num(q.get("price")):
            price, pinfo = q["price"], {"time": q.get("time"), "kind": "quotazione", "label": "ultima quotazione"}
        else:
            price, pinfo = close, {"date": cl.get("date") or x.get("priceDate"), "kind": "chiusura",
                                   "label": "chiusura dell'ultima seduta"}
        inp = inputs(x, data.get(t), seen_all.get(t), (infos or {}).get(t), (analysts or {}).get(t), fx, rates, now,
                     peer.get(x["model"]["id"]), close)
        out.append(valuate(x, inp, price, pinfo))
    order = {g: i for i, (g, _, _) in enumerate(GROUPS)}
    out.sort(key=lambda r: (order[r["group"]], -(r.get("marginOfSafety") or {}).get("base", -9) if r.get("marginOfSafety")
                            and _num(r["marginOfSafety"].get("base")) else 9, r["ticker"]))
    from collections import Counter
    return {"model": {"version": VERSION, "params": [{"name": a, "text": b} for a, b in PARAMS], "values": P,
                      "statuses": STATUS, "positions": POSITION,
                      "groups": [{"id": a, "label": b, "rule": c} for a, b, c in GROUPS], "fundamentalVersion": inv["model"]["version"]},
            "generated": now.isoformat(timespec="seconds"), "items": out, "rates": rates, "fx": fx,
            "counts": {"status": dict(Counter(r["status"] for r in out)), "group": dict(Counter(r["group"] for r in out)),
                       "position": dict(Counter((r.get("position") or {}).get("id") for r in out if r.get("position")))},
            "dataDates": inv.get("dataDates")}


def compact(r):
    """One row of the list in the page."""
    sc = r.get("scenarios") or {}
    return {"ticker": r["ticker"], "name": r["name"], "status": r["status"], "statusLabel": r["statusLabel"],
            "group": r["group"], "fundamental": r["fundamental"], "price": r["price"],
            "position": r.get("position"), "summary": r["summary"],
            "values": {k: (sc.get(k) or {}).get("perShare") for k, _ in SCEN} if sc else None,
            "display": (r.get("range") or {}).get("display"),
            "impliedGrowth": (r.get("reverse") or {}).get("growth"), "baseGrowth": (r.get("inputs") or {}).get("g1"),
            "tvShare": (sc.get("base") or {}).get("tvShare") if sc else None,
            "reason": (r.get("reasons") or [None])[0], "lagging": r.get("lagging")}


# ---------------------------------------------------------------- terminal

def _local():
    a = ie._local_inputs()
    inv = ie.analyze_all(**a)
    import analysts as an
    import server
    infos = (server.read_cache("infos.json", 30 * 86400) or {}).get("data", {})
    closes = {x["ticker"]: {"close": x["price"], "date": x["priceDate"]} for x in inv["items"]}
    return analyze_all(inv, a["fund"], infos, (an.read_cache() or {}).get("data", {}), a["now"], closes=closes)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "riepilogo"
    if cmd == "parametri":
        for a, b in PARAMS:
            print(f"{a}: {b}")
        return
    res = _local()
    if cmd == "riepilogo":
        print("Stato:", res["counts"]["status"])
        print("Gruppi:", res["counts"]["group"])
        print("Posizione del prezzo:", res["counts"]["position"])
        for r in res["items"]:
            print(f"{r['ticker']:6s} {r['statusLabel'][:42]:42s} {r['group']:20s} {r['summary'][:150]}")
    elif cmd == "mostra" and len(argv) > 2:
        r = next((x for x in res["items"] if x["ticker"] == argv[2].upper()), None)
        if not r:
            print("Titolo non trovato")
            return
        import json
        r = dict(r)
        for k in (r.get("scenarios") or {}).values():
            k.pop("years", None)
        print(json.dumps(r, indent=1, ensure_ascii=False, default=str))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
