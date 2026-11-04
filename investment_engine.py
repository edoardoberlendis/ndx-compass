"""Motore di analisi fondamentale (phase 5A): why a Nasdaq-100 company looks financially interesting or problematic
for a medium-long term investment. Separate from the Pagella (pillars.py) and from the Investimento ranking of
opportunity_scanner.py, which are unchanged and shown next to it for comparison.

    .venv/bin/python investment_engine.py aggiorna [--forza]   downloads the statements that need it (fundamentals.py)
    .venv/bin/python investment_engine.py copertura            data coverage of every indicator
    .venv/bin/python investment_engine.py profili              how many companies per profile and per dimension state
    .venv/bin/python investment_engine.py mostra TICKER        the full analysis of one company

Six independent dimensions, each with a state taken from a short fixed list, the rule that produced it and the values
used: quality, growth, financial strength, valuation (against comparable companies), expectations (analysts) and the
structural price trend. They are never added into a single score: the order of the list counts favourable minus
unfavourable fundamental dimensions with equal weights, and it is EXPERIMENTAL. The profile is a description, never
a buy or sell signal; no fair value, target price or expected return is computed here (phase 5B).

Thresholds: proposals of phase 5A (4 November 2026), economic rules of thumb, NOT validated by any test. They are in
PARAMS, shown in the page and saved in the diary with VERSION. The analysis uses only data available at `now`: periods
ending later, or announced later, are ignored. Missing figures are never zero; a ratio with a negative or zero
denominator is "non significativo"; figures in another currency are converted to USD only for market multiples.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
from datetime import date, datetime, timedelta

import fundamentals as fu

VERSION = "F1"
ET = fu.ET

# ---------------------------------------------------------------- thresholds (experimental, phase 5A)
Q_OPM_HIGH, Q_OPM_OK, Q_OPM_WEAK = 20.0, 10.0, 5.0     # operating margin, %
Q_FCF_HIGH, Q_FCF_OK = 15.0, 5.0                        # free cash flow margin, % of revenue
Q_ROIC_HIGH = 15.0                                      # return on invested capital, %
Q_DROP_2Y, Q_DROP_TTM = 5.0, 3.0                        # operating margin points lost in 2 years / last 12 months vs FY
Q_SBC_SHARE = 0.5                                       # share-based pay at least half of the free cash flow
G_STRONG, G_POS, G_SHIFT = 15.0, 5.0, 5.0               # revenue growth %, and points of acceleration / slowdown
G_BASE_MIN = 2.0                                        # profit growth only if the old profit is at least 2% of revenue
S_ND_SOLID, S_ND_OK, S_ND_FRAGILE = 1.5, 3.0, 5.0       # net debt / EBITDA
S_COVER_WARN, S_COVER_FRAGILE = 3.0, 1.5                # EBIT / interest expense
S_RUNWAY_YEARS = 2.0                                    # net cash covers less than 2 years of negative free cash flow
V_MIN_PEERS, V_MIN_METRICS = 5, 2                       # comparable companies with the figure; multiples compared
V_HIGH, V_LOW = 0.70, 0.30                              # median position among comparables
E_REV = 3.0                                             # next-year EPS estimate change in 90 days, %
E_MIN_ANALYSTS = 3
STALE_Q_DAYS, STALE_FY_DAYS = 200, 550                  # newest quarter / annual report older than this = obsolete
COMPLETE_SHARE = 0.85

PARAMS = [
    ("Qualità", f"margine operativo «elevato» dal {Q_OPM_HIGH:g}%, «buono» dal {Q_OPM_OK:g}%, «debole» sotto il {Q_OPM_WEAK:g}%; "
                f"flusso di cassa libero dal {Q_FCF_HIGH:g}% (elevata) e dal {Q_FCF_OK:g}% (buona) dei ricavi, debole se negativo; "
                f"rendimento del capitale investito dal {Q_ROIC_HIGH:g}%; peggioramento con margine giù di {Q_DROP_2Y:g} punti "
                f"in 2 anni o di {Q_DROP_TTM:g} negli ultimi 12 mesi"),
    ("Crescita", f"ricavi «forte» dal +{G_STRONG:g}%, «positiva» dal +{G_POS:g}%, «in calo» sotto zero; accelerazione o "
                 f"rallentamento oltre {G_SHIFT:g} punti tra l'ultimo trimestre e l'ultimo esercizio; utili confrontati solo "
                 f"con una base positiva di almeno il {G_BASE_MIN:g}% dei ricavi"),
    ("Solidità", f"debito netto / EBITDA fino a {S_ND_SOLID:g} (solida), {S_ND_OK:g} (adeguata), {S_ND_FRAGILE:g} (da verificare), "
                 f"oltre è fragile; copertura degli interessi sotto {S_COVER_WARN:g} da verificare, sotto {S_COVER_FRAGILE:g} fragile; "
                 f"liquidità netta che copre meno di {S_RUNWAY_YEARS:g} anni di cassa bruciata = fragile"),
    ("Valutazione", f"confronto solo con almeno {V_MIN_PEERS} società comparabili con il dato e almeno {V_MIN_METRICS} multipli; "
                    f"«impegnativa» se la posizione mediana è sopra il {V_HIGH * 100:g}% del gruppo, «contenuta» sotto il "
                    f"{V_LOW * 100:g}%"),
    ("Aspettative", f"stima di utile del prossimo anno cambiata di almeno ±{E_REV:g}% in 90 giorni; meno di {E_MIN_ANALYSTS} analisti = "
                    f"copertura scarsa"),
    ("Dati", f"trimestre più recente oltre {STALE_Q_DAYS} giorni o bilancio annuale oltre {STALE_FY_DAYS} giorni = obsoleto; "
             f"analisi «completa» con almeno il {COMPLETE_SHARE * 100:g}% degli indicatori applicabili"),
]

DIMS = [("quality", "Qualità aziendale"), ("growth", "Crescita"), ("solidity", "Solidità finanziaria"),
        ("valuation", "Valutazione"), ("expectations", "Aspettative"), ("trend", "Trend strutturale")]
CORE = ("quality", "growth", "solidity", "valuation")
STATES = {
    "quality": ["Elevata", "Buona", "Modesta", "Debole", "Non valutabile"],
    "growth": ["Forte", "Positiva", "Modesta", "In calo", "Non valutabile"],
    "solidity": ["Solida", "Adeguata", "Da verificare", "Fragile", "Non valutabile"],
    "valuation": ["Contenuta", "Nella media del gruppo", "Impegnativa", "Non confrontabile"],
    "expectations": ["In miglioramento", "Stabili", "In peggioramento", "Revisione non verificabile"],
    "trend": ["Favorevole", "Misto", "Debole", "Non calcolabile"],
}
POSITIVE = {"Elevata", "Buona", "Forte", "Positiva", "Solida", "Contenuta", "In miglioramento", "Favorevole"}
NEGATIVE = {"Debole", "In calo", "Da verificare", "Fragile", "Impegnativa", "In peggioramento"}

MODELS = {
    "tech": ("Tecnologia e software", "Flusso di cassa libero al netto dei compensi in azioni (molto usati nel software)."),
    "general": ("Industriali, consumo e altri settori", "Criteri generici: margini, cassa, debito e multipli."),
    "financial": ("Settore finanziario", "Debito, EBITDA e flusso di cassa non hanno lo stesso significato (depositi e fondi dei "
                                         "clienti): solidità non valutabile con questi dati, qualità da margine netto e ROE."),
    "utility": ("Utility e servizi regolamentati", "Debito elevato e flusso di cassa negativo per gli investimenti sono normali in "
                                                   "un'attività regolamentata: solidità solo dalla copertura degli interessi, cassa "
                                                   "non giudicata. Mancano criteri specifici (base tariffaria, rating)."),
}
METRICS = {   # key: (label, higher means more expensive)
    "pe": ("P/E (12 mesi)", True), "fpe": ("P/E atteso", True), "evEbit": ("EV/utile operativo", True), "evEbitda": ("EV/EBITDA", True),
    "ps": ("Prezzo/ricavi", True), "fcfYield": ("Rendimento del flusso di cassa libero", False), "pb": ("Prezzo/patrimonio", True),
}
MODEL_METRICS = {"tech": ("pe", "fpe", "evEbit", "evEbitda", "ps", "fcfYield"),
                 "general": ("pe", "fpe", "evEbit", "evEbitda", "ps", "fcfYield"),
                 "financial": ("pe", "fpe", "pb"), "utility": ("pe", "fpe", "evEbitda", "pb")}
MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


# ---------------------------------------------------------------- small helpers

def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def it(x, d=1):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".").replace("-", "−")


def sgn(x, d=1):
    return ("+" if x > 0 else "") + it(x, d)


def day_it(iso):
    d = date.fromisoformat(str(iso)[:10])
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def big(x, cur):
    a = abs(x)
    v, u = (a / 1e12, "mila mld") if a >= 1e12 else (a / 1e9, "mld") if a >= 1e9 else (a / 1e6, "mln")
    return f"{'−' if x < 0 else ''}{it(v, 1)} {u} {cur}"


def pct(a, b):
    return a / b * 100 if _num(a) and _num(b) and b != 0 else None


def growth(new, old):
    """Percent change, only on a positive base (a change from a negative or zero base has no meaning)."""
    return (new / old - 1) * 100 if _num(new) and _num(old) and old > 0 else None


def _days(a, b):
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


# ---------------------------------------------------------------- periods (point in time)

def usable(entry, now, seen=None):
    """FY and Q periods known at `now`: ended before, not announced later, not first seen later."""
    today = now.date().isoformat()
    out = {}
    for kind in ("FY", "Q"):
        keep = []
        for p in (entry or {}).get(kind) or []:
            if p["end"] > today:
                continue
            pub = fu.announced(p["end"], entry.get("earnings"))
            if pub and pub > today:
                continue
            fs = (seen or {}).get(f"{kind}|{p['end']}")
            if fs and fs.get("date") and fs["date"] > today:
                continue
            keep.append(p)
        out[kind] = sorted(keep, key=lambda p: p["end"], reverse=True)
    return out


def ttm(qs, field):
    """Sum of the last 4 quarters if they are consecutive (75-105 days apart) and all have the figure."""
    if len(qs) < 4:
        return None
    four = qs[:4]
    if any(not (75 <= _days(four[i]["end"], four[i + 1]["end"]) <= 105) for i in range(3)):
        return None
    vals = [p.get(field) for p in four]
    return sum(vals) if all(_num(v) for v in vals) else None


def period(kind, end, entry=None, seen=None):
    lab = {"FY": f"esercizio chiuso a {MONTHS[int(end[5:7]) - 1]} {end[:4]}", "TTM": f"12 mesi al {day_it(end)}",
           "Q": f"trimestre al {day_it(end)}", "BS": f"bilancio al {day_it(end)}"}[kind]
    out = {"type": kind, "end": end, "label": lab}
    if entry is not None:
        out["announced"] = fu.announced(end, entry.get("earnings"))
        fs = (seen or {}).get(f"{'FY' if kind == 'FY' else 'Q'}|{end}")
        if fs:
            out["firstSeen"] = fs["date"]
            out["firstSeenInitial"] = bool(fs.get("initial"))
    return out


def flow(P, field, entry, seen):
    """(value, period) of a flow item: last 12 months from 4 quarters, otherwise the last annual report."""
    v = ttm(P["Q"], field)
    if v is not None:
        return v, period("TTM", P["Q"][0]["end"], entry, seen)
    if P["FY"] and _num(P["FY"][0].get(field)):
        return P["FY"][0][field], period("FY", P["FY"][0]["end"], entry, seen)
    return None, None


def stock(P, field, entry, seen):
    """(value, period) of a balance-sheet item: newest quarter, otherwise the annual report."""
    for kind, lab in (("Q", "BS"), ("FY", "FY")):
        if P[kind] and _num(P[kind][0].get(field)):
            return P[kind][0][field], period(lab, P[kind][0]["end"], entry, seen)
    return None, None


ICB_EN = {"Finanza": "Financials", "Utility": "Utilities", "Tecnologia": "Technology",
          "Telecomunicazioni": "Telecommunications"}   # the dashboard shows ICB sectors in Italian


def sector_model(icb, ysec, yind):
    ysec, yind, icb = ysec or "", yind or "", icb or ""
    icb = ICB_EN.get(icb, icb)
    if icb == "Financials" or (ysec == "Financial Services" and "Financial Data" not in yind):
        return "financial"
    if icb == "Utilities" or ysec == "Utilities" or "REIT" in yind:
        return "utility"
    if icb in ("Technology", "Telecommunications") or ysec in ("Technology", "Communication Services"):
        return "tech"
    return "general"


# ---------------------------------------------------------------- one company: indicators

class Ind(list):
    def add(self, key, label, value, unit, per=None, source="bilanci", status=None, note=None, dim=None, fmt=None):
        st = status or ("ok" if _num(value) else "mancante")
        self.append({"key": key, "label": label, "value": value if st == "ok" else None, "unit": unit, "period": per,
                     "source": source, "status": st, "note": note, "dim": dim,
                     "text": fmt if fmt is not None and st == "ok" else None})
        return value if st == "ok" else None

    def get(self, key):
        return next((x["value"] for x in self if x["key"] == key), None)


def indicators(u, entry, seen, info, an, tch, fx, now, model):
    """All the figures of one company with unit, period, source and status. Returns (Ind, facts) where facts keeps
    the raw values the dimensions need."""
    P = usable(entry, now, seen)
    q_stale = None
    if P["Q"] and _days(now.date().isoformat(), P["Q"][0]["end"]) > STALE_Q_DAYS:
        q_stale, P["Q"] = P["Q"][0]["end"], []      # old quarters (e.g. half-year reporters): only the annual reports
    I = Ind()
    cur = (entry.get("info") or {}).get("financialCurrency") or (info or {}).get("financialCurrency") or "USD"
    f = {"P": P, "cur": cur, "model": model, "entry": entry, "qStale": q_stale}
    fin, util, tech = model == "financial", model == "utility", model == "tech"

    rev, rp = flow(P, "revenue", entry, seen)
    I.add("revenue", "Ricavi", rev, cur, rp, dim="growth", fmt=big(rev, cur) if _num(rev) else None)
    oi, op = flow(P, "operatingIncome", entry, seen)
    I.add("operatingIncome", "Utile operativo", oi, cur, op, dim="quality", fmt=big(oi, cur) if _num(oi) else None)
    ni, nip = flow(P, "netIncome", entry, seen)
    I.add("netIncome", "Utile netto", ni, cur, nip, dim="quality", fmt=big(ni, cur) if _num(ni) else None)
    # Yahoo's EBIT is pre-tax income plus interest: it carries one-off and financial items. The operating figures
    # use the operating income, and EBITDA = operating income + depreciation (Yahoo EBITDA - Yahoo EBIT)
    y_ebit, ebp = flow(P, "ebit", entry, seen)
    y_ebitda, edp = flow(P, "ebitda", entry, seen)
    da = y_ebitda - y_ebit if _num(y_ebitda) and _num(y_ebit) and y_ebitda >= y_ebit else None
    ebit = oi
    ebitda = oi + da if _num(oi) and _num(da) else None
    f["ebitGap"] = (_num(y_ebit) and _num(oi) and _num(rev) and rev > 0 and abs(y_ebit - oi) > 0.10 * rev)
    I.add("ebitda", "EBITDA (utile operativo + ammortamenti)", ebitda, cur, op, status="non applicabile" if fin else None,
          dim="solidity", note="non significativo per un'azienda finanziaria" if fin else None,
          fmt=big(ebitda, cur) if _num(ebitda) else None)
    edp = op
    ocf, ocp = flow(P, "ocf", entry, seen)
    capex, cpp = flow(P, "capex", entry, seen)
    fcf, fcp = flow(P, "fcf", entry, seen)
    sbc, sbp = flow(P, "sbc", entry, seen)
    I.add("ocf", "Flusso di cassa operativo", ocf, cur, ocp, dim="quality", fmt=big(ocf, cur) if _num(ocf) else None)
    I.add("capex", "Investimenti (spese in conto capitale)", capex, cur, cpp, dim="quality", fmt=big(capex, cur) if _num(capex) else None)
    fcf_na = "non applicabile" if fin else None
    I.add("fcf", "Flusso di cassa libero", fcf, cur, fcp, status=fcf_na, dim="quality",
          note="i flussi di un'azienda finanziaria includono i fondi dei clienti" if fin else None,
          fmt=big(fcf, cur) if _num(fcf) else None)
    eps = P["FY"][0].get("dilutedEps") if P["FY"] else None
    I.add("eps", "Utile per azione diluito (annuale)", eps, f"{cur} per azione",
          period("FY", P["FY"][0]["end"], entry, seen) if P["FY"] else None, dim="growth",
          note="per azione ordinaria: per un ADR il rapporto tra azioni può essere diverso" if cur != "USD" else None,
          fmt=it(eps, 2) if _num(eps) else None)
    debt, dp = stock(P, "totalDebt", entry, seen)
    cash, cp = stock(P, "cash", entry, seen)
    equity, eqp = stock(P, "equity", entry, seen)
    I.add("debt", "Debito totale (compresi i leasing)", debt, cur, dp, dim="solidity", fmt=big(debt, cur) if _num(debt) else None)
    I.add("cash", "Liquidità e investimenti a breve", cash, cur, cp, dim="solidity", fmt=big(cash, cur) if _num(cash) else None)
    nd = debt - cash if _num(debt) and _num(cash) else None
    I.add("netDebt", "Debito netto (debito − liquidità)", nd, cur, dp, dim="solidity",
          status="non applicabile" if fin else None, note="non è leva finanziaria per un'azienda finanziaria" if fin else None,
          fmt=(big(nd, cur) if nd > 0 else f"liquidità netta {big(-nd, cur)}") if _num(nd) else None)
    f.update(rev=rev, oi=oi, ni=ni, ebit=ebit, ebitda=ebitda, ocf=ocf, capex=capex, fcf=fcf, sbc=sbc, debt=debt, cash=cash,
             equity=equity, nd=nd, revPer=rp, bsPer=dp or cp)

    # margins and returns
    opm = pct(oi, rev) if _num(rev) and rev > 0 else None
    I.add("opMargin", "Margine operativo", opm, "%", op, dim="quality", fmt=f"{it(opm)}%" if _num(opm) else None)
    npm = pct(ni, rev) if _num(rev) and rev > 0 else None
    I.add("netMargin", "Margine netto", npm, "%", nip, dim="quality", fmt=f"{it(npm)}%" if _num(npm) else None)
    fcfm = pct(fcf, rev) if _num(rev) and rev > 0 and not fin else None
    I.add("fcfMargin", "Flusso di cassa libero / ricavi", fcfm, "%", fcp, status=fcf_na, dim="quality",
          fmt=f"{it(fcfm)}%" if _num(fcfm) else None)
    fcf_sbc = pct(fcf - sbc, rev) if tech and _num(fcf) and _num(sbc) and _num(rev) and rev > 0 else None
    if tech:
        I.add("fcfSbcMargin", "Flusso di cassa libero al netto dei compensi in azioni / ricavi", fcf_sbc, "%", fcp, dim="quality",
              note=None if _num(sbc) else "compensi in azioni non disponibili", fmt=f"{it(fcf_sbc)}%" if _num(fcf_sbc) else None)
    conv = ocf / ni if _num(ocf) and _num(ni) and ni > 0 else None
    I.add("cashConversion", "Flusso di cassa operativo / utile netto", conv, "volte", ocp,
          status=("non applicabile" if fin else "non significativo" if _num(ni) and ni <= 0 else None), dim="quality",
          note="utile netto negativo o nullo" if _num(ni) and ni <= 0 else None, fmt=f"{it(conv, 2)} volte" if _num(conv) else None)
    roic = None
    if P["FY"] and not fin:
        y = P["FY"][0]
        ic, eb = y.get("investedCapital"), y.get("ebit")
        tax = (y["taxProvision"] / y["pretaxIncome"] if _num(y.get("taxProvision")) and _num(y.get("pretaxIncome"))
               and y["pretaxIncome"] > 0 and 0 <= y["taxProvision"] / y["pretaxIncome"] <= 0.5 else 0.21)
        if _num(ic) and ic > 0 and _num(eb):
            roic = eb * (1 - tax) / ic * 100
        I.add("roic", "Rendimento del capitale investito (EBIT dopo le tasse / capitale investito)", roic, "%",
              period("FY", y["end"], entry, seen), dim="quality",
              status=None if roic is not None or not _num(ic) else "non significativo",
              note="capitale investito negativo o nullo" if _num(ic) and ic <= 0 else
              "capitale investito = patrimonio + debito, liquidità compresa: per chi ha molta cassa il valore è prudente",
              fmt=f"{it(roic)}%" if _num(roic) else None)
    else:
        I.add("roic", "Rendimento del capitale investito", None, "%", status="non applicabile", dim="quality",
              note="non significativo per un'azienda finanziaria" if fin else "bilancio annuale non disponibile")
    roe = pct(ni, equity) if _num(equity) and equity > 0 else None
    I.add("roe", "Rendimento del patrimonio (ROE)", roe, "%", nip, dim="quality",
          status=None if roe is not None or not _num(equity) else "non significativo",
          note="patrimonio netto negativo (per esempio per i riacquisti di azioni)" if _num(equity) and equity <= 0 else None,
          fmt=f"{it(roe)}%" if _num(roe) else None)
    margins = [(y["end"], pct(y.get("operatingIncome"), y.get("revenue"))) for y in P["FY"]
               if _num(y.get("revenue")) and y["revenue"] > 0 and _num(y.get("operatingIncome"))]
    f.update(opm=opm, npm=npm, fcfm=fcfm, fcfSbc=fcf_sbc, conv=conv, roic=roic, roe=roe, margins=margins,
             opPer=op, fcfPer=fcp)

    # growth
    fy = P["FY"]
    def yoy(field, i=0):
        if len(fy) > i + 1 and 330 <= _days(fy[i]["end"], fy[i + 1]["end"]) <= 400:
            return growth(fy[i].get(field), fy[i + 1].get(field))
        return None
    g_fy = yoy("revenue")
    I.add("revGrowthFY", "Crescita dei ricavi (ultimo esercizio)", g_fy, "%", period("FY", fy[0]["end"], entry, seen) if fy else None,
          dim="growth", note=None if g_fy is not None or len(fy) < 2 else "esercizi non consecutivi o base non positiva",
          fmt=f"{sgn(g_fy)}%" if _num(g_fy) else None)
    cagr = None
    if len(fy) >= 4 and 1050 <= _days(fy[0]["end"], fy[3]["end"]) <= 1150 and _num(fy[0].get("revenue")) and _num(fy[3].get("revenue")) \
            and fy[3]["revenue"] > 0 and fy[0]["revenue"] > 0:
        cagr = ((fy[0]["revenue"] / fy[3]["revenue"]) ** (1 / 3) - 1) * 100
    I.add("revCagr3", "Crescita media annua dei ricavi (3 esercizi)", cagr, "%",
          period("FY", fy[0]["end"], entry, seen) if fy else None, dim="growth",
          note=None if cagr is not None else "servono 4 bilanci annuali consecutivi", fmt=f"{sgn(cagr)}% l'anno" if _num(cagr) else None)
    qs = P["Q"]
    g_q, q_old = None, None
    if qs:
        q_old = next((q for q in qs[1:] if 350 <= _days(qs[0]["end"], q["end"]) <= 380), None)
        if q_old:
            g_q = growth(qs[0].get("revenue"), q_old.get("revenue"))
    I.add("revGrowthQ", "Crescita dei ricavi (ultimo trimestre sullo stesso dell'anno prima)", g_q, "%",
          period("Q", qs[0]["end"], entry, seen) if qs else None, dim="growth",
          note=None if g_q is not None else "manca lo stesso trimestre dell'anno prima", fmt=f"{sgn(g_q)}%" if _num(g_q) else None)

    def profit_growth(field):
        if len(fy) < 2 or not (330 <= _days(fy[0]["end"], fy[1]["end"]) <= 400):
            return None, "esercizi non consecutivi"
        new, old, rv = fy[0].get(field), fy[1].get(field), fy[1].get("revenue")
        if not (_num(new) and _num(old)):
            return None, "dato mancante"
        if old <= 0 or not _num(rv) or rv <= 0 or old < rv * G_BASE_MIN / 100:
            return None, "base dell'anno prima negativa o troppo piccola: variazione non significativa"
        return growth(new, old), None
    for key, field, lab in (("oiGrowth", "operatingIncome", "Crescita dell'utile operativo (ultimo esercizio)"),
                            ("epsGrowth", "dilutedEps", "Crescita dell'utile per azione (ultimo esercizio)"),
                            ("fcfGrowth", "fcf", "Crescita del flusso di cassa libero (ultimo esercizio)")):
        if field == "dilutedEps":
            g, why = (growth(fy[0].get(field), fy[1].get(field)), None) if len(fy) > 1 and _num(fy[0].get(field)) and \
                _num(fy[1].get(field)) and fy[1][field] > 0 and 330 <= _days(fy[0]["end"], fy[1]["end"]) <= 400 else \
                (None, "utile per azione dell'anno prima negativo, nullo o mancante")
        elif field == "fcf" and fin:
            g, why = None, "non applicabile"
        else:
            g, why = profit_growth(field)
        st = "non applicabile" if why == "non applicabile" else ("non significativo" if why and "significativ" in why or
                                                                  why and "negativo" in why else None)
        I.add(key, lab, g, "%", period("FY", fy[0]["end"], entry, seen) if fy else None, dim="growth", status=st, note=why,
              fmt=f"{sgn(g)}%" if _num(g) else None)
        f[key] = g
    f.update(gFy=g_fy, gQ=g_q, cagr=cagr, qEnd=qs[0]["end"] if qs else None, qOld=q_old["end"] if q_old else None)

    # strength
    nd_e = nd / ebitda if _num(nd) and _num(ebitda) and ebitda > 0 else None
    I.add("ndEbitda", "Debito netto / EBITDA", nd_e, "volte", edp, dim="solidity",
          status="non applicabile" if fin else ("non significativo" if _num(ebitda) and ebitda <= 0 else None),
          note=("non è leva finanziaria per un'azienda finanziaria" if fin else
                "EBITDA negativo o nullo" if _num(ebitda) and ebitda <= 0 else
                "negativo = più liquidità che debito" if _num(nd_e) and nd_e < 0 else None),
          fmt=f"{it(nd_e, 2)} volte" if _num(nd_e) else None)
    interest, ip = flow(P, "interestExpense", entry, seen)
    cover = ebit / abs(interest) if _num(ebit) and _num(interest) and abs(interest) > 0 else None
    I.add("interestCover", "Copertura degli interessi (utile operativo / interessi passivi)", cover, "volte", ip, dim="solidity",
          status="non applicabile" if fin else (None if cover is not None else "mancante"),
          note=None if cover is not None or fin else "interessi passivi non indicati o nulli",
          fmt=f"{it(cover, 1)} volte" if _num(cover) else None)
    f.update(ndEbitda=nd_e, cover=cover)

    # market multiples (USD): market cap of today, accounts converted with today's FX rate
    mcap = (info or {}).get("marketCap")
    rate = 1.0 if cur == "USD" else (fx.get(cur) or {}).get("rate")
    f.update(mcap=mcap, rate=rate)
    mkt = {"type": "oggi", "end": None, "label": "capitalizzazione di oggi"}
    ok_mkt = _num(mcap) and mcap > 0 and _num(rate)
    conv_note = f"conti in {cur} convertiti al cambio di oggi ({it(rate, 4)} USD)" if cur != "USD" and _num(rate) else None
    no_mkt = ("cambio non disponibile" if not _num(rate) else "capitalizzazione non disponibile") if not ok_mkt else None
    usd = lambda x: x * rate if _num(x) and ok_mkt else None
    ev = mcap + usd(nd) if ok_mkt and _num(nd) and not fin else None
    vals = {}

    def multiple(key, num, den, note_neg):
        label, _ = METRICS[key]
        if key not in MODEL_METRICS[model]:
            I.add(key, label, None, "volte" if key != "fcfYield" else "%", mkt, source="calcolato", status="non applicabile",
                  dim="valuation", note=f"non adatto al modello «{MODELS[model][0]}»")
            return
        if no_mkt:
            I.add(key, label, None, "volte", mkt, source="calcolato", dim="valuation", note=no_mkt)
            return
        if not (_num(num) and _num(den)):
            I.add(key, label, None, "volte", mkt, source="calcolato", dim="valuation", note="dato del bilancio mancante")
            return
        if key == "fcfYield":
            v = num / den * 100
            vals[key] = I.add(key, label, v, "%", mkt, source="calcolato", dim="valuation", note=conv_note,
                              fmt=f"{it(v)}%")
            return
        if den <= 0:
            I.add(key, label, None, "volte", mkt, source="calcolato", status="non significativo", dim="valuation", note=note_neg)
            return
        v = num / den
        vals[key] = I.add(key, label, v, "volte", mkt, source="calcolato", dim="valuation", note=conv_note, fmt=f"{it(v, 1)}")
    multiple("pe", mcap, usd(ni), "utile netto negativo o nullo")
    multiple("evEbit", ev, usd(ebit), "utile operativo negativo o nullo")
    multiple("evEbitda", ev, usd(ebitda), "EBITDA negativo o nullo")
    multiple("ps", mcap, usd(rev), "ricavi nulli")
    multiple("fcfYield", usd(fcf), mcap, "")
    multiple("pb", mcap, usd(equity), "patrimonio netto negativo o nullo")
    fpe = (info or {}).get("forwardPE")
    same_cur = cur == ((entry.get("info") or {}).get("currency") or "USD")
    if "fpe" in MODEL_METRICS[model]:
        if not same_cur:
            I.add("fpe", "P/E atteso", None, "volte", mkt, source="dati del giorno", status="non significativo", dim="valuation",
                  note=f"stime in {cur} e prezzo in USD per un titolo quotato come ADR: rapporto non affidabile")
        elif _num(fpe) and fpe > 0:
            vals["fpe"] = I.add("fpe", "P/E atteso", fpe, "volte", mkt, source="dati del giorno", dim="valuation",
                                note="prezzo diviso la stima di utile per azione dei prossimi 12 mesi (Yahoo)", fmt=it(fpe, 1))
        else:
            I.add("fpe", "P/E atteso", None, "volte", mkt, source="dati del giorno",
                  status="non significativo" if _num(fpe) else None, dim="valuation",
                  note="utile atteso negativo o nullo" if _num(fpe) else "stima non disponibile")
    f["multiples"] = vals
    f["ev"] = ev

    # expectations (analysts: eps_trend is the source's own record of the estimate 30 and 90 days ago)
    tr = ((an or {}).get("epsTrend") or {}).get("+1y") or {}
    rv = ((an or {}).get("revisions") or {}).get("+1y") or {}
    rev30 = growth(tr.get("current"), tr.get("30daysAgo"))
    rev90 = growth(tr.get("current"), tr.get("90daysAgo"))
    neg_est = _num(tr.get("90daysAgo")) and tr["90daysAgo"] <= 0
    I.add("epsRev90", "Stima di utile per azione del prossimo anno: variazione in 90 giorni", rev90, "%",
          {"type": "stima", "end": None, "label": "stima di oggi contro 90 giorni fa"}, source="analisti", dim="expectations",
          status="non significativo" if neg_est else None,
          note="stima di 90 giorni fa negativa o nulla" if neg_est else (None if rev90 is not None else "storico della stima non disponibile"),
          fmt=f"{sgn(rev90)}%" if _num(rev90) else None)
    I.add("epsRev30", "Stima di utile per azione del prossimo anno: variazione in 30 giorni", rev30, "%",
          {"type": "stima", "end": None, "label": "stima di oggi contro 30 giorni fa"}, source="analisti", dim="expectations",
          fmt=f"{sgn(rev30)}%" if _num(rev30) else None)
    ups, downs = rv.get("upLast30days"), rv.get("downLast30days")
    I.add("revisionsUpDown", "Revisioni della stima in 30 giorni (in alto / in basso)", ups if _num(ups) and _num(downs) else None,
          "numero", {"type": "stima", "end": None, "label": "ultimi 30 giorni"}, source="analisti", dim="expectations",
          fmt=f"{int(ups)} in alto, {int(downs)} in basso" if _num(ups) and _num(downs) else None)
    eg = (((an or {}).get("eps") or {}).get("+1y") or {}).get("growth")
    rg = (((an or {}).get("rev") or {}).get("+1y") or {}).get("growth")
    I.add("epsGrowthNext", "Crescita attesa dell'utile per azione (prossimo esercizio)", eg * 100 if _num(eg) else None, "%",
          {"type": "stima", "end": None, "label": "consenso di oggi"}, source="analisti", dim="expectations",
          fmt=f"{sgn(eg * 100)}%" if _num(eg) else None)
    I.add("revGrowthNext", "Crescita attesa dei ricavi (prossimo esercizio)", rg * 100 if _num(rg) else None, "%",
          {"type": "stima", "end": None, "label": "consenso di oggi"}, source="analisti", dim="expectations",
          fmt=f"{sgn(rg * 100)}%" if _num(rg) else None)
    rec, recm, nan_ = (info or {}).get("recommendationKey"), (info or {}).get("recommendationMean"), (info or {}).get("numberOfAnalystOpinions")
    rec_it = {"strong_buy": "Forte acquisto", "buy": "Acquisto", "hold": "Mantenere", "underperform": "Sottoperformance",
              "sell": "Vendita"}.get(rec)
    I.add("consensus", "Consenso degli analisti (1 = forte acquisto, 5 = vendita)", recm, "media",
          {"type": "oggi", "end": None, "label": "consenso di oggi"}, source="dati del giorno", dim="expectations",
          fmt=f"{rec_it or rec} (media {it(recm, 1)}, {int(nan_ or 0)} analisti)" if _num(recm) else None)
    f.update(rev30=rev30, rev90=rev90, up30=ups, down30=downs, egNext=eg * 100 if _num(eg) else None,
             rgNext=rg * 100 if _num(rg) else None, recKey=rec, recIt=rec_it, recMean=recm, nAnalysts=nan_)

    # trend (closed sessions)
    f["tech"] = tch
    return I, f


# ---------------------------------------------------------------- the six dimensions (each: state, reasons, partial)

def dim(state, reasons, partial=False, rule=""):
    return {"state": state, "reasons": [r for r in reasons if r], "partial": partial, "rule": rule,
            "polarity": 1 if state in POSITIVE else -1 if state in NEGATIVE else 0}


def _down(state, order):
    i = order.index(state)
    return order[min(i + 1, 3)]


def quality(f):
    m, per = f["model"], (f.get("opPer") or {}).get("label", "")
    order = STATES["quality"]
    opm, fcfm, roic, npm, roe = f["opm"], f["fcfm"], f["roic"], f["npm"], f["roe"]
    if m == "financial":
        if npm is None:
            return dim("Non valutabile", ["margine netto non calcolabile"], True)
        if npm < 0:
            return dim("Debole", [f"utile netto negativo ({it(npm)}% dei ricavi, {per})"], True)
        st = "Buona" if npm >= Q_FCF_HIGH and (roe or 0) >= Q_ROIC_HIGH else "Modesta"
        return dim(st, [f"margine netto {it(npm)}%" + (f", ROE {it(roe)}%" if _num(roe) else "") + f" ({per})",
                        "azienda finanziaria: mancano qualità del credito e capitale regolamentare"], True,
                   f"margine netto e ROE almeno {Q_FCF_HIGH:g}% per «Buona»")
    if opm is None:
        return dim("Non valutabile", ["margine operativo non calcolabile (ricavi o utile operativo mancanti)"])
    fcf_used = f["fcfSbc"] if m == "tech" and f["fcfSbc"] is not None else fcfm
    fcf_lab = "al netto dei compensi in azioni" if m == "tech" and f["fcfSbc"] is not None else ""
    f["fcfUsed"], f["fcfLab"] = fcf_used, fcf_lab
    reasons = [f"margine operativo {it(opm)}% ({per})"]
    partial = False
    if m == "utility":
        st = "Debole" if opm < Q_OPM_WEAK else "Buona" if opm >= Q_OPM_HIGH else "Modesta"
        reasons += [f"ROE {it(roe)}%" if _num(roe) else None,
                    "utility: flusso di cassa libero non giudicato (investimenti regolamentati)"]
        return dim(st, reasons, True, f"margine operativo dal {Q_OPM_HIGH:g}% per «Buona», sotto il {Q_OPM_WEAK:g}% «Debole»")
    if fcf_used is not None:
        reasons.append(f"flusso di cassa libero {fcf_lab + ' ' if fcf_lab else ''}{it(fcf_used)}% dei ricavi")
    else:
        partial = True
        reasons.append("flusso di cassa libero non disponibile")
    if _num(roic):
        reasons.append(f"rendimento del capitale investito {it(roic)}%")
    f["qWhy"] = None
    if opm < Q_OPM_WEAK:
        st, f["qWhy"] = "Debole", "opm"
    elif fcf_used is not None and fcf_used < 0 and opm < Q_OPM_OK:
        st, f["qWhy"] = "Debole", "fcf"
    elif fcf_used is not None and fcf_used < 0:
        st, f["qWhy"] = "Modesta", "fcf_invest"        # good margins, cash absorbed by investments: not weak, not high
        capex_share = pct(-f["capex"], f["rev"]) if _num(f.get("capex")) and _num(f.get("rev")) and f["rev"] > 0 else None
        reasons.append("flusso di cassa libero negativo nonostante i margini" +
                       (f": investimenti pari al {it(capex_share)}% dei ricavi" if _num(capex_share) else ""))
    elif opm >= Q_OPM_HIGH and fcf_used is not None and fcf_used >= Q_FCF_HIGH and (roic is None or roic >= Q_ROIC_HIGH):
        st = "Elevata"
    elif opm >= Q_OPM_OK and (fcf_used is None or fcf_used >= Q_FCF_OK):
        st = "Buona"
    else:
        st = "Modesta"
    mg = f["margins"]
    drop2 = mg[0][1] - mg[2][1] if len(mg) >= 3 else None
    drop_t = opm - mg[0][1] if mg and (f.get("opPer") or {}).get("type") == "TTM" else None
    f["marginDrop"] = None
    if (drop2 is not None and drop2 <= -Q_DROP_2Y) or (drop_t is not None and drop_t <= -Q_DROP_TTM):
        f["marginDrop"] = drop_t if drop_t is not None and drop_t <= -Q_DROP_TTM else drop2
        reasons.append("redditività in peggioramento: " + (
            f"margine {sgn(drop_t)} punti negli ultimi 12 mesi rispetto all'ultimo esercizio" if drop_t is not None and drop_t <= -Q_DROP_TTM
            else f"margine {sgn(drop2)} punti in due esercizi"))
        if st in ("Elevata", "Buona"):
            st = _down(st, order)
    if len(mg) >= 3:
        rng = max(x[1] for x in mg) - min(x[1] for x in mg)
        reasons.append(f"margine {'stabile' if rng <= Q_DROP_2Y else 'variabile'} negli ultimi {len(mg)} esercizi "
                       f"(da {it(min(x[1] for x in mg))}% a {it(max(x[1] for x in mg))}%)")
    return dim(st, reasons, partial, f"margine dal {Q_OPM_HIGH:g}% e cassa libera dal {Q_FCF_HIGH:g}% dei ricavi per «Elevata»")


def growth_dim(f):
    gq, gfy, cagr = f["gQ"], f["gFy"], f["cagr"]
    g = gq if gq is not None else gfy
    if g is None:
        return dim("Non valutabile", ["crescita dei ricavi non calcolabile (periodi mancanti o non confrontabili)"])
    st = "In calo" if g < 0 else "Forte" if g >= G_STRONG else "Positiva" if g >= G_POS else "Modesta"
    reasons = []
    if gq is not None:
        reasons.append(f"ricavi {sgn(gq)}% nel trimestre al {day_it(f['qEnd'])} sullo stesso trimestre dell'anno prima")
    if gfy is not None:
        reasons.append(f"{sgn(gfy)}% nell'ultimo esercizio")
    if cagr is not None:
        reasons.append(f"{sgn(cagr)}% l'anno in media in 3 esercizi")
    shift = gq - gfy if gq is not None and gfy is not None else None
    f["growthShift"] = None
    if shift is not None and abs(shift) >= G_SHIFT:
        f["growthShift"] = "in accelerazione" if shift > 0 else "in rallentamento"
        reasons.append(f"crescita {f['growthShift']} ({sgn(shift)} punti tra l'ultimo trimestre e l'ultimo esercizio)")
    if gfy is not None and gfy > 0 and f.get("oiGrowth") is not None and f["oiGrowth"] < 0:
        reasons.append(f"ricavi in crescita ma utile operativo {sgn(f['oiGrowth'])}% nell'ultimo esercizio")
    f["growthAnomaly"] = g >= 50
    if g >= 50:
        reasons.append("crescita molto alta: può dipendere da acquisizioni o da una base di partenza piccola o anomala")
    out = dim(st, reasons, gq is None, f"ricavi dal +{G_STRONG:g}% «Forte», dal +{G_POS:g}% «Positiva», sotto zero «In calo»")
    out["shift"] = f["growthShift"]
    return out


def solidity(f):
    m, nd, ebitda, cover, fcf, cash = f["model"], f["nd"], f["ebitda"], f["cover"], f["fcf"], f["cash"]
    cur = f["cur"]
    per = (f.get("bsPer") or {}).get("label", "")
    if m == "financial":
        out = dim("Non valutabile", ["azienda finanziaria: debito e liquidità comprendono i fondi dei clienti; mancano capitale "
                                     "regolamentare e qualità del credito"], True)
        out["structural"] = True          # not missing data: these figures do not apply to the sector
        return out
    cov_txt = f"copertura degli interessi {it(cover, 1)} volte" if _num(cover) else None
    if m == "utility":
        if cover is None:
            return dim("Non valutabile", ["utility: copertura degli interessi non calcolabile"], True)
        st = "Adeguata" if cover >= S_COVER_WARN else "Da verificare" if cover >= S_COVER_FRAGILE else "Fragile"
        r = [cov_txt, f"debito netto {it(f['ndEbitda'], 1)} volte l'EBITDA (normale per un'attività regolamentata)" if _num(f["ndEbitda"]) else None]
        return dim(st, r, True, f"utility: solo copertura degli interessi (sotto {S_COVER_WARN:g} da verificare)")
    if nd is None:
        return dim("Non valutabile", ["debito o liquidità non disponibili"])
    reasons = []
    if nd <= 0:
        reasons.append(f"liquidità netta di {big(-nd, cur)} ({per})")
        if _num(fcf) and fcf < 0:
            years = (cash or 0) / -fcf if fcf else math.inf
            reasons.append(f"flusso di cassa libero negativo ({big(fcf, cur)} in 12 mesi): la liquidità copre circa {it(years, 1)} anni")
            st = "Fragile" if years < S_RUNWAY_YEARS else "Adeguata"
        else:
            st = "Solida"
    else:
        if not _num(ebitda):
            return dim("Non valutabile", [f"debito netto {big(nd, cur)} ma EBITDA non disponibile"])
        if ebitda <= 0:
            st = "Fragile"
            reasons.append(f"debito netto {big(nd, cur)} con EBITDA negativo")
        else:
            r = nd / ebitda
            st = "Solida" if r <= S_ND_SOLID else "Adeguata" if r <= S_ND_OK else "Da verificare" if r <= S_ND_FRAGILE else "Fragile"
            reasons.append(f"debito netto {it(r, 1)} volte l'EBITDA ({big(nd, cur)}, {per})")
    order = STATES["solidity"]
    if _num(cover) and nd > 0:
        reasons.append(cov_txt)
        worst = "Fragile" if cover < S_COVER_FRAGILE else "Da verificare" if cover < S_COVER_WARN else None
        if worst and order.index(worst) > order.index(st):
            st = worst
    if _num(f["equity"]) and f["equity"] <= 0:
        reasons.append("patrimonio netto negativo (spesso per riacquisti di azioni: da leggere insieme alla cassa)")
    return dim(st, reasons, False, f"debito netto/EBITDA fino a {S_ND_SOLID:g} «Solida», oltre {S_ND_FRAGILE:g} «Fragile»")


def expectations(f):
    rev90, rev30, n = f["rev90"], f["rev30"], f["nAnalysts"]
    cons = f"consenso «{f['recIt'] or f['recKey']}» di {int(n)} analisti" if f["recKey"] and _num(n) else None
    few = _num(n) and n < E_MIN_ANALYSTS
    if rev90 is None:
        return dim("Revisione non verificabile", ["storico della stima non disponibile: il consenso di oggi da solo non dice "
                                                  "se le aspettative migliorano", cons], True)
    st = "In miglioramento" if rev90 >= E_REV else "In peggioramento" if rev90 <= -E_REV else "Stabili"
    reasons = [f"stima di utile del prossimo anno {sgn(rev90)}% in 90 giorni" + (f" ({sgn(rev30)}% in 30)" if _num(rev30) else "")]
    if _num(f["up30"]) and _num(f["down30"]):
        reasons.append(f"{int(f['up30'])} revisioni in alto e {int(f['down30'])} in basso in 30 giorni")
    reasons.append(cons)
    if few:
        reasons.append(f"solo {int(n)} analisti: copertura scarsa")
    return dim(st, reasons, bool(few), f"stima cambiata di almeno ±{E_REV:g}% in 90 giorni")


def trend_dim(t, q252):
    if not t or not _num(t.get("sma200")) or not _num(t.get("sma50")):
        return dim("Non calcolabile", ["meno di 200 sedute chiuse di prezzi"])
    above, golden = t["close"] > t["sma200"], t["sma50"] > t["sma200"]
    st = "Favorevole" if above and golden else "Debole" if not above and not golden else "Misto"
    reasons = [f"prezzo {sgn(t['vs200'])}% dalla media 200, media 50 {'sopra' if golden else 'sotto'} la media 200 "
               f"(sedute chiuse fino al {day_it(t['date'])})"]
    if _num(t.get("ret252")):
        reasons.append(f"1 anno {sgn(t['ret252'])}%" + (f" contro {sgn(q252)}% di QQQ" if _num(q252) else ""))
    out = dim(st, reasons, False, "chiusura e media 50 sopra la media 200 = «Favorevole» (regola B2); è il comportamento del "
                                  "prezzo, non una prova di qualità, e non è validato come previsione")
    return out


# ---------------------------------------------------------------- valuation against comparable companies

def peer_group(t, rows, by_ind, by_sec):
    r = rows[t]
    ind = [x for x in by_ind.get(r["industry"], []) if rows[x]["model"] == r["model"]]
    if r["industry"] and len(ind) >= V_MIN_PEERS:
        return {"kind": "industria (Yahoo)", "name": r["industry"], "members": ind}
    sec = [x for x in by_sec.get(r["sector"], []) if rows[x]["model"] == r["model"]]
    if r["sector"] and len(sec) >= V_MIN_PEERS:
        return {"kind": "settore (ICB)", "name": r["sector"], "members": sec}
    return {"kind": None, "name": r["industry"] or r["sector"], "members": ind or sec}


def valuation(t, rows, group):
    r = rows[t]
    mult = r["facts"]["multiples"]
    if not group["kind"]:
        out = dim("Non confrontabile", [f"meno di {V_MIN_PEERS} società comparabili nel Nasdaq-100 ({group['name'] or 'settore ignoto'}, "
                                        f"{len(group['members'])} con lo stesso modello)"], True)
        out["structural"] = len(mult) >= V_MIN_METRICS     # the multiples exist: what is missing is a comparable group
        return out, []
    comps, positions = [], []
    for key in MODEL_METRICS[r["model"]]:
        if key not in mult:
            continue
        label, high_rich = METRICS[key]
        vals = {x: rows[x]["facts"]["multiples"].get(key) for x in group["members"]}
        vals = {x: v for x, v in vals.items() if _num(v)}
        c = {"key": key, "label": label, "value": mult[key], "n": len(vals), "groupSize": len(group["members"])}
        if len(vals) < V_MIN_PEERS:
            c["note"] = f"solo {len(vals)} società del gruppo con il dato: confronto non fatto"
            comps.append(c)
            continue
        others = [v for x, v in vals.items() if x != t]
        lower = sum(v < mult[key] for v in others) + 0.5 * sum(v == mult[key] for v in others)
        p = lower / len(others)
        rich = p if high_rich else 1 - p
        c.update(median=statistics.median(vals.values()), position=p, rich=rich)
        positions.append(rich)
        comps.append(c)
    gname = f"{group['name']}, {group['kind']}"
    if len(positions) < V_MIN_METRICS:
        out = dim("Non confrontabile", [f"meno di {V_MIN_METRICS} multipli confrontabili con il gruppo ({gname})"], True)
        out["structural"] = len(mult) >= V_MIN_METRICS
        return out, comps
    pos = statistics.median(positions)
    st = "Impegnativa" if pos >= V_HIGH else "Contenuta" if pos <= V_LOW else "Nella media del gruppo"
    show = [c for c in comps if "rich" in c]
    where = ("meno cara di tutte le" if pos <= 0 else "più cara di tutte le" if pos >= 1 else f"più cara del {it(pos * 100, 0)}% delle")
    reasons = [f"{where} {len(group['members'])} società comparabili ({gname}), posizione mediana di {len(show)} multipli"]
    reasons.append("; ".join(
        f"{c['label']} {it(c['value'], 1)}{'%' if c['key'] == 'fcfYield' else ''} contro una mediana di {it(c['median'], 1)}"
        f"{'%' if c['key'] == 'fcfYield' else ''} ({'più cara' if c['rich'] > 0.5 else 'meno cara' if c['rich'] < 0.5 else 'in linea'})"
        for c in show))
    if st == "Contenuta":
        reasons.append("multipli più bassi del gruppo non significano «sottovalutata»: possono esserci ragioni strutturali")
    if st == "Impegnativa":
        reasons.append("multipli alti possono riflettere qualità e crescita attese: non significano «sopravvalutata»")
    out = dim(st, reasons, False, f"posizione mediana tra i comparabili sopra il {V_HIGH * 100:g}% = «Impegnativa», sotto il "
                                  f"{V_LOW * 100:g}% = «Contenuta»")
    out["position"] = pos
    out["group"] = {"kind": group["kind"], "name": group["name"], "size": len(group["members"])}
    return out, comps


# ---------------------------------------------------------------- profile, strengths, weaknesses, follow-up

PROFILES = [
    ("dati_insufficienti", "Dati insufficienti"),
    ("fragilita", "Fragilità finanziaria da verificare"),
    ("contenuta_rischi", "Valutazione apparentemente contenuta, ma con rischi fondamentali"),
    ("peggioramento", "Fondamentali in peggioramento"),
    ("qualita_cara", "Qualità elevata, valutazione impegnativa"),
    ("buona_cara", "Buona qualità, valutazione impegnativa"),
    ("qualita_crescita", "Qualità e crescita"),
    ("crescita_investimenti", "Crescita forte, cassa assorbita dagli investimenti"),
    ("crescita_debole", "Crescita interessante, redditività ancora debole"),
    ("solida_moderata", "Azienda solida, crescita moderata"),
    ("qualita_ricavi_calo", "Buona qualità, ricavi in calo"),
    ("trend_da_approfondire", "Trend favorevole, fondamentali da approfondire"),
    ("misto", "Profilo misto"),
]
PROFILE_RULES = {
    "dati_insufficienti": "almeno 2 dimensioni fondamentali senza dati (non per i limiti del settore)",
    "fragilita": "solidità «Fragile»",
    "contenuta_rischi": "valutazione «Contenuta» con qualità «Debole», ricavi «In calo» o solidità «Da verificare»",
    "peggioramento": "ricavi «In calo» con qualità «Modesta» o «Debole»",
    "qualita_cara": "qualità «Elevata» e valutazione «Impegnativa»",
    "buona_cara": "qualità «Buona» e valutazione «Impegnativa»",
    "qualita_crescita": "qualità «Elevata» o «Buona», crescita «Forte» o «Positiva», solidità non a rischio, valutazione non "
                        "«Impegnativa» e stime non in peggioramento",
    "crescita_investimenti": "crescita «Forte» o «Positiva», margini buoni ma flusso di cassa libero negativo per gli investimenti",
    "crescita_debole": "crescita «Forte» con qualità «Modesta» o «Debole» (margini bassi o cassa negativa con margini bassi)",
    "solida_moderata": "qualità «Elevata» o «Buona», solidità «Solida» o «Adeguata», crescita «Modesta»",
    "qualita_ricavi_calo": "qualità «Elevata» o «Buona» con ricavi «In calo»",
    "trend_da_approfondire": "trend «Favorevole» senza un profilo fondamentale chiaro",
    "misto": "nessuna delle regole precedenti",
}


def profile(d, completeness, q_why=None):
    s = {k: v["state"] for k, v in d.items()}
    good_q = s["quality"] in ("Elevata", "Buona")
    if completeness == "Insufficiente":
        return "dati_insufficienti"
    if s["solidity"] == "Fragile":
        return "fragilita"
    if s["valuation"] == "Contenuta" and (s["quality"] == "Debole" or s["growth"] == "In calo" or s["solidity"] == "Da verificare"):
        return "contenuta_rischi"
    if s["growth"] == "In calo" and s["quality"] in ("Modesta", "Debole"):
        return "peggioramento"
    if s["quality"] == "Elevata" and s["valuation"] == "Impegnativa":
        return "qualita_cara"
    if s["quality"] == "Buona" and s["valuation"] == "Impegnativa":
        return "buona_cara"
    if good_q and s["growth"] in ("Forte", "Positiva") and s["solidity"] not in ("Da verificare", "Fragile") \
            and s["expectations"] != "In peggioramento":
        return "qualita_crescita"
    if q_why == "fcf_invest" and s["growth"] in ("Forte", "Positiva") and s["solidity"] not in ("Da verificare", "Fragile"):
        return "crescita_investimenti"
    if s["growth"] == "Forte" and s["quality"] in ("Modesta", "Debole"):
        return "crescita_debole"
    if good_q and s["solidity"] in ("Solida", "Adeguata") and s["growth"] == "Modesta":
        return "solida_moderata"
    if good_q and s["growth"] == "In calo":
        return "qualita_ricavi_calo"
    if s["trend"] == "Favorevole":
        return "trend_da_approfondire"
    return "misto"


def view_vs_trend(d):
    """C6: fundamentals and price trend kept apart, then put side by side in words."""
    bal = sum(d[k]["polarity"] for k in CORE + ("expectations",))
    risky = d["quality"]["state"] == "Debole" or d["solidity"]["state"] in ("Fragile", "Da verificare") or d["growth"]["state"] == "In calo"
    fund = "interessanti" if bal >= 2 and not risky else "poco convincenti" if bal <= -1 or (risky and bal <= 0) else "da approfondire"
    tr = d["trend"]["state"]
    if tr == "Non calcolabile":
        return f"Fondamentali {fund}; trend del prezzo non calcolabile."
    if fund == "interessanti":
        return f"Fondamentali interessanti con prezzo in trend {'favorevole' if tr == 'Favorevole' else 'debole' if tr == 'Debole' else 'incerto'}."
    if fund == "poco convincenti" and tr == "Favorevole":
        return "Fondamentali poco convincenti nonostante il prezzo in trend favorevole."
    return f"Fondamentali {fund}; trend del prezzo {tr.lower()}."


def notes(r):
    """Strengths, weaknesses and things to follow, each derived from a measured value of this company."""
    d, f = r["dims"], r["facts"]
    cur = f["cur"]
    per = (f.get("opPer") or {}).get("label") or ""
    S, W = [], []
    q = d["quality"]["state"]
    fu_, fl = f.get("fcfUsed"), f.get("fcfLab") or ""
    if q in ("Elevata", "Buona") and _num(f["opm"]):
        cash = (f" e flusso di cassa libero{' ' + fl if fl else ''} pari al {it(fu_)}% dei ricavi"
                if _num(fu_) and r["model"] not in ("utility", "financial") else "")
        S.append(("quality", f"Redditività {q.lower()}: margine operativo {it(f['opm'])}%{cash} ({per})."))
    if q == "Debole":
        why = {"opm": f"margine operativo {it(f['opm'])}%" if _num(f["opm"]) else "",
               "fcf": f"flusso di cassa libero{' ' + fl if fl else ''} negativo ({it(fu_)}% dei ricavi) con margine operativo "
                      f"{it(f['opm'])}%" if _num(fu_) and _num(f["opm"]) else ""}.get(f.get("qWhy")) or (
               f"utile netto negativo ({it(f['npm'])}% dei ricavi)" if _num(f["npm"]) else "dati di redditività negativi")
        W.append(("quality", f"Redditività debole: {why} ({per})."))
    if f.get("qWhy") == "fcf_invest":
        W.append(("quality", f"Flusso di cassa libero{' ' + fl if fl else ''} negativo ({it(fu_)}% dei ricavi) nonostante un margine "
                             f"operativo del {it(f['opm'])}%: la cassa va negli investimenti."))
    if f.get("marginDrop") is not None:
        W.append(("quality", f"Margine operativo in calo di {it(abs(f['marginDrop']))} punti: la redditività si sta riducendo."))
    if r["model"] == "tech" and _num(f["sbc"]) and _num(f["fcf"]) and f["fcf"] > 0 and f["sbc"] >= Q_SBC_SHARE * f["fcf"]:
        W.append(("quality", f"I compensi in azioni ({big(f['sbc'], cur)}) valgono {it(f['sbc'] / f['fcf'] * 100, 0)}% del flusso di "
                             "cassa libero: una parte della cassa «libera» è pagata con nuove azioni."))
    g = d["growth"]["state"]
    gtxt = (f"ricavi {sgn(f['gQ'])}% nell'ultimo trimestre" if _num(f["gQ"]) else f"ricavi {sgn(f['gFy'])}% nell'ultimo esercizio"
            if _num(f["gFy"]) else "")
    if f.get("growthAnomaly"):
        W.append(("growth", f"Crescita dei ricavi molto alta ({gtxt}): verificare se dipende da acquisizioni o da una base anomala."))
    if g in ("Forte", "Positiva") and f.get("growthShift") != "in rallentamento":
        S.append(("growth", f"Crescita {g.lower()}: {gtxt}" + (f" ({sgn(f['gFy'])}% nell'esercizio)" if _num(f["gQ"]) and _num(f["gFy"]) else "") + "."))
    if g in ("Forte", "Positiva") and f.get("growthShift") == "in rallentamento":
        S.append(("growth", f"Ricavi ancora in crescita: {gtxt}."))
        W.append(("growth", f"Crescita in rallentamento: {sgn(f['gQ'])}% nell'ultimo trimestre contro {sgn(f['gFy'])}% nell'ultimo esercizio."))
    if g == "In calo":
        W.append(("growth", f"Ricavi in calo: {gtxt}."))
    if _num(f["gFy"]) and f["gFy"] > 0 and _num(f.get("oiGrowth")) and f["oiGrowth"] < 0:
        W.append(("growth", f"Ricavi in crescita ({sgn(f['gFy'])}%) ma utile operativo in calo ({sgn(f['oiGrowth'])}%) nell'ultimo esercizio."))
    s = d["solidity"]["state"]
    if s == "Solida":
        S.append(("solidity", ("Più liquidità che debito: " + big(-f["nd"], cur) + " di liquidità netta.") if _num(f["nd"]) and f["nd"] <= 0
                  else f"Debito contenuto: debito netto {it(f['ndEbitda'], 1)} volte l'EBITDA."))
    if s in ("Da verificare", "Fragile"):
        W.append(("solidity", f"Solidità {s.lower()}: " + "; ".join(d["solidity"]["reasons"][:2]) + "."))
    v = d["valuation"]
    if v["state"] == "Impegnativa":
        W.append(("valuation", "Valutazione impegnativa: " + v["reasons"][0] + "."))
    if v["state"] == "Contenuta":
        S.append(("valuation", f"Multipli più bassi della maggior parte dei comparabili ({v['group']['name']}, {v['group']['size']} "
                               f"società): " + ("la meno cara del gruppo" if v["position"] <= 0 else f"più cara solo del {it(v['position'] * 100, 0)}% del gruppo")
                               + ". Non vuol dire sottovalutata."))
    e = d["expectations"]["state"]
    if e == "In miglioramento":
        S.append(("expectations", f"Stime degli analisti in aumento: utile del prossimo anno {sgn(f['rev90'])}% in 90 giorni."))
    if e == "In peggioramento":
        W.append(("expectations", f"Stime degli analisti in calo: utile del prossimo anno {sgn(f['rev90'])}% in 90 giorni."))
    for x in r["dataIssues"]:
        W.append(("data", x))
    prio_s = ["quality", "growth", "solidity", "expectations", "valuation"]
    prio_w = ["solidity", "quality", "growth", "data", "valuation", "expectations"]
    S.sort(key=lambda x: prio_s.index(x[0]))
    W.sort(key=lambda x: prio_w.index(x[0]))

    M = []
    nxt = r.get("nextEarnings")
    if nxt:
        what = [x for x in (f"ricavi (ultimo {sgn(f['gQ'])}% sull'anno prima)" if _num(f["gQ"]) else None,
                            f"margine operativo (ora {it(f['opm'])}%)" if _num(f["opm"]) else None) if x]
        M.append(f"Prossima trimestrale il {day_it(nxt)}" + (": " + " e ".join(what) if what else "") + ".")
    if r.get("lagging"):
        M.append(f"I risultati annunciati il {day_it(r['lagging'])} non sono ancora nei bilanci della fonte: l'analisi cambierà "
                 "al prossimo aggiornamento.")
    if f.get("growthShift") == "in rallentamento":
        M.append("Se il rallentamento dei ricavi continua anche nel prossimo trimestre.")
    if s in ("Da verificare", "Fragile") and _num(f["ndEbitda"]):
        M.append(f"Debito netto / EBITDA (ora {it(f['ndEbitda'], 1)} volte) e copertura degli interessi.")
    if f.get("marginDrop") is not None:
        M.append("Se il margine operativo smette di scendere.")
    if e == "Revisione non verificabile":
        M.append("Le stime degli analisti: lo storico delle revisioni non è disponibile.")
    elif e == "In peggioramento":
        M.append("Se i tagli delle stime si fermano.")
    if v["state"] == "Impegnativa":
        M.append("Se la crescita giustifica i multipli: confrontare la crescita dei prossimi trimestri con quella attesa.")
    if not M:
        M.append("Nessun elemento specifico: la prossima trimestrale non è ancora nel calendario della fonte.")
    return S, W, M


# ---------------------------------------------------------------- everything

def analyze_all(universe, fund, infos, analysts, techs, now, q252=None, pagella=None, infos_date=None, analysts_date=None):
    """universe: [{"ticker", "name", "sector"}] (ICB sector); fund: fundamentals cache (fundamentals.read());
    infos: {ticker: Yahoo info of today}; analysts: {ticker: analysts.fetch_one data}; techs: {ticker:
    opportunity_scanner.tech(...) on closed sessions}; now: aware datetime of the computation; pagella: {ticker:
    {"ok", "n", "status", "conditions"}} of the unchanged Investimento ranking (only shown)."""
    data, seen_all, fx = fund.get("data") or {}, fund.get("firstSeen") or {}, fund.get("fx") or {}
    rows = {}
    for u in universe:
        t = u["ticker"]
        e = data.get(t) or {}
        yi = e.get("info") or {}
        model = sector_model(u.get("sector"), yi.get("sector"), yi.get("industry"))
        I, f = indicators(u, e, seen_all.get(t), (infos or {}).get(t), (analysts or {}).get(t), (techs or {}).get(t), fx, now, model)
        rows[t] = {"ticker": t, "name": u.get("name") or t, "sector": u.get("sector"), "industry": yi.get("industry"),
                   "yahooSector": yi.get("sector"), "model": model, "indicators": I, "facts": f, "entry": e}
    by_ind, by_sec = {}, {}
    for t, r in rows.items():
        if r["industry"]:
            by_ind.setdefault(r["industry"], []).append(t)
        if r["sector"]:
            by_sec.setdefault(r["sector"], []).append(t)
    out = []
    today = now.date().isoformat()
    for t, r in rows.items():
        f, e = r["facts"], r["entry"]
        issues, limits = [], []
        P = f["P"]
        if not e:
            issues.append("Bilanci non ancora scaricati per questa società.")
        else:
            if f.get("qStale"):
                limits.append(f"Ultimo trimestre della fonte al {day_it(f['qStale'])} (la società potrebbe pubblicare solo "
                              "semestrali): i flussi usano l'ultimo bilancio annuale.")
            if f.get("ebitGap"):
                limits.append("L'EBIT della fonte è molto diverso dall'utile operativo (componenti straordinarie o finanziarie): "
                              "si usa l'utile operativo.")
            if P["FY"] and _days(today, P["FY"][0]["end"]) > STALE_FY_DAYS:
                issues.append(f"Dati obsoleti: l'ultimo bilancio annuale è chiuso al {day_it(P['FY'][0]['end'])}.")
            if not f.get("qStale") and (not P["Q"] or ttm(P["Q"], "revenue") is None):
                limits.append("Mancano 4 trimestri consecutivi completi: i flussi usano l'ultimo bilancio annuale.")
        lag = fu.latest_announcement(e, now) if e and P["Q"] and fu.lagging(e, now) else None
        if lag:
            issues.append(f"Risultati annunciati il {day_it(lag.date().isoformat())} non ancora nei bilanci della fonte: i numeri "
                          f"si fermano al trimestre al {day_it(P['Q'][0]['end'])}.")
        if f["cur"] != "USD":
            limits.append(f"Bilanci in {f['cur']} e prezzo in USD: i multipli usano il cambio di oggi; utile per azione e P/E atteso "
                          "di un ADR possono riferirsi a un numero di azioni diverso.")
        stale = any(x.startswith("Dati obsoleti") for x in issues)
        d = {"quality": quality(f), "growth": growth_dim(f), "solidity": solidity(f), "expectations": expectations(f),
             "trend": trend_dim(f["tech"], q252)}
        if stale or not e:
            for k in ("quality", "growth", "solidity"):
                d[k] = dim("Non valutabile", ["dati di bilancio obsoleti o assenti"])
        group = peer_group(t, rows, by_ind, by_sec)
        d["valuation"], comps = valuation(t, rows, group)
        if stale or not e:
            d["valuation"] = dim("Non confrontabile", ["dati di bilancio obsoleti o assenti"], True)
        r["dims"] = d
        applicable = [x for x in r["indicators"] if x["status"] != "non applicabile"]
        avail = [x for x in applicable if x["status"] == "ok"]
        na = [k for k in CORE if d[k]["state"] in ("Non valutabile", "Non confrontabile")]
        structural = [k for k in na if d[k].get("structural")]       # sector or comparables, not missing data
        missing_core = [k for k in na if k not in structural]
        share = len(avail) / len(applicable) if applicable else 0
        comp_state = ("Insufficiente" if len(missing_core) >= 2 else
                      "Completa" if not na and share >= COMPLETE_SHARE and not issues and not any(d[k]["partial"] for k in CORE)
                      else "Parziale")
        r["completeness"] = {"state": comp_state, "available": len(avail), "applicable": len(applicable),
                             "share": round(share, 3), "coreDims": len(CORE) - len(na),
                             "missingDims": missing_core, "sectorLimitedDims": structural}
        r["dataIssues"] = issues
        r["lagging"] = lag.date().isoformat() if lag else None
        nxt = (infos or {}).get(t, {}).get("earningsTimestamp")
        nxt_d = datetime.fromtimestamp(nxt, ET).date().isoformat() if _num(nxt) else None
        r["nextEarnings"] = nxt_d if nxt_d and nxt_d >= today else None
        pid = profile(d, comp_state, f.get("qWhy"))
        S, W, M = notes(r)
        missing = [{"label": x["label"], "status": x["status"], "note": x["note"]} for x in r["indicators"]
                   if x["status"] in ("mancante", "non significativo")]
        model_lab, model_note = MODELS[r["model"]]
        tch = f["tech"] or {}
        out.append({
            "ticker": t, "name": r["name"], "sector": r["sector"], "industry": r["industry"],
            "model": {"id": r["model"], "label": model_lab, "note": model_note},
            "price": tch.get("close"), "priceDate": tch.get("date"),
            "currency": {"accounts": f["cur"], "price": ((e.get("info") or {}).get("currency") or "USD"),
                         "fx": fx.get(f["cur"]) if f["cur"] != "USD" else None},
            "dims": d, "balance": {"pos": sum(d[k]["polarity"] > 0 for k in CORE + ("expectations",)),
                                   "neg": sum(d[k]["polarity"] < 0 for k in CORE + ("expectations",))},
            "profile": {"id": pid, "label": dict(PROFILES)[pid], "rule": PROFILE_RULES[pid]},
            "view": view_vs_trend(d),
            "strengths": [x[1] for x in S], "weaknesses": [x[1] for x in W], "monitor": M,
            "mainStrength": S[0][1] if S else "Nessun punto di forza netto nei dati disponibili.",
            "mainWeakness": W[0][1] if W else "Nessuna criticità evidente nei dati disponibili.",
            "indicators": list(r["indicators"]), "peers": comps,
            "missing": missing, "limits": limits + ([model_note] if r["model"] in ("financial", "utility") else []),
            "completeness": r["completeness"], "dataIssues": issues, "lagging": r["lagging"], "nextEarnings": r["nextEarnings"],
            "dataDates": {"statements": e.get("fetchedAt"), "marketData": infos_date, "analysts": analysts_date,
                          "prices": tch.get("date"),
                          "latestQuarter": P["Q"][0]["end"] if P["Q"] else None, "latestYear": P["FY"][0]["end"] if P["FY"] else None,
                          "latestQuarterAnnounced": fu.announced(P["Q"][0]["end"], e.get("earnings")) if P["Q"] else None},
            "pagella": (pagella or {}).get(t),
        })
    out.sort(key=lambda x: (x["completeness"]["state"] == "Insufficiente", -(x["balance"]["pos"] - x["balance"]["neg"]),
                            STATES["quality"].index(x["dims"]["quality"]["state"]), x["ticker"]))
    for i, x in enumerate(out, 1):
        x["order"] = i
    cov = {}
    for x in out:
        for ind in x["indicators"]:
            c = cov.setdefault(ind["key"], {"key": ind["key"], "label": ind["label"], "ok": 0, "applicable": 0})
            if ind["status"] != "non applicabile":
                c["applicable"] += 1
                c["ok"] += ind["status"] == "ok"
    groups = {}
    for x in out:
        g = x["dims"]["valuation"].get("group")
        if g:
            groups[f"{g['kind']}|{g['name']}"] = g
    return {"model": {"version": VERSION, "params": [{"name": a, "text": b} for a, b in PARAMS],
                      "profiles": [{"id": k, "label": v, "rule": PROFILE_RULES[k]} for k, v in PROFILES],
                      "dims": [{"id": k, "label": v, "states": STATES[k]} for k, v in DIMS],
                      "models": {k: {"label": a, "note": b} for k, (a, b) in MODELS.items()}},
            "generated": now.isoformat(timespec="seconds"), "items": out, "coverage": list(cov.values()),
            "groups": sorted(groups.values(), key=lambda g: -g["size"]), "fx": fx,
            "dataDates": {"statements": fund.get("savedAt"), "marketData": infos_date, "analysts": analysts_date}}


def compact(item):
    """The row of the list in the page (the full analysis is read on demand)."""
    keep = ("ticker", "name", "sector", "industry", "model", "price", "priceDate", "balance", "profile", "view",
            "mainStrength", "mainWeakness", "completeness", "dataIssues", "lagging", "order", "currency")
    out = {k: item[k] for k in keep}
    out["dims"] = {k: {"state": v["state"], "partial": v["partial"], "polarity": v["polarity"], "shift": v.get("shift")}
                   for k, v in item["dims"].items()}
    p = item.get("pagella")
    out["pagella"] = {"ok": p["ok"], "n": p["n"], "status": p.get("status"), "rank": p.get("rank")} if p else None
    return out


# ---------------------------------------------------------------- terminal

def _local_inputs():
    """Inputs from the caches already on disk (no download): constituents, infos, analysts, fundamentals, prices."""
    import analysts as an
    import opportunity_scanner as osc
    import server
    from datetime import datetime as dt
    rows = server.load_constituents()
    universe = [{"ticker": r["ticker"], "name": r.get("name"), "sector": r.get("sector")} for r in rows]
    infos = server.read_cache("infos.json", 30 * 86400)
    daily = server.load_daily_cache()[0] or {}
    now = dt.now(ET)
    import technical
    closed = technical.closed_sessions(daily, now)
    bench = closed.get(server.SIGNAL_BENCH)
    bclose = bench["Close"].dropna() if bench is not None else None
    techs = {u["ticker"]: osc.tech(closed.get(u["ticker"]), bclose) for u in universe}
    q252 = (float(bclose.iloc[-1] / bclose.iloc[-253] - 1) * 100) if bclose is not None and len(bclose) > 253 else None
    ac = an.read_cache() or {}
    return dict(universe=universe, fund=fu.read(), infos=(infos or {}).get("data", {}), analysts=ac.get("data", {}),
                techs=techs, now=now, q252=q252, infos_date=(infos or {}).get("date"), analysts_date=ac.get("date"))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "profili"
    if cmd == "aggiorna":
        import server
        tickers = [r["ticker"] for r in server.load_constituents()]
        print(fu.refresh(tickers, force="--forza" in argv))
        return
    res = analyze_all(**_local_inputs())
    if cmd == "copertura":
        print(f"Copertura degli indicatori ({len(res['items'])} società; dati del {res['dataDates']})")
        for c in res["coverage"]:
            print(f"  {c['label'][:70]:70s} {c['ok']:3d} su {c['applicable']:3d} applicabili")
        print("Gruppi di confronto:", "; ".join(f"{g['name']} ({g['kind']}, {g['size']})" for g in res["groups"]))
    elif cmd == "profili":
        from collections import Counter
        print(Counter(x["profile"]["label"] for x in res["items"]).most_common())
        for k, _ in DIMS:
            print(k, Counter(x["dims"][k]["state"] for x in res["items"]).most_common())
        print("completezza", Counter(x["completeness"]["state"] for x in res["items"]).most_common())
    elif cmd == "mostra" and len(argv) > 2:
        x = next((i for i in res["items"] if i["ticker"] == argv[2].upper()), None)
        if not x:
            print("Titolo non trovato")
            return
        print(f"{x['ticker']} · {x['name']} · {x['sector']} / {x['industry']} · modello {x['model']['label']}")
        print(f"Profilo: {x['profile']['label']} ({x['profile']['rule']}) · completezza {x['completeness']}")
        print(x["view"])
        for k, lab in DIMS:
            dd = x["dims"][k]
            print(f"  {lab}: {dd['state']}{' (parziale)' if dd['partial'] else ''} — " + "; ".join(dd["reasons"]))
        print("Punti di forza:", *x["strengths"], sep="\n  ")
        print("Debolezze:", *x["weaknesses"], sep="\n  ")
        print("Da monitorare:", *x["monitor"], sep="\n  ")
        print("Indicatori:")
        for i in x["indicators"]:
            print(f"  {i['label'][:60]:60s} {i['text'] or i['status']:>28s}  {(i['period'] or {}).get('label', '')} "
                  f"{'(annuncio ' + i['period']['announced'] + ')' if (i['period'] or {}).get('announced') else ''}"
                  f"{' · ' + i['note'] if i['note'] else ''}")
        print("Date dei dati:", x["dataDates"])
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
