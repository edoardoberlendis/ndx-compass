"""Scanner esplorativo delle esposizioni ETF (phase 6B).

It starts from the financial EXPOSURE (world equities, US large caps, semiconductors, euro government bonds 1-3 years,
...), not from the ETF: the share classes of the catalog that give the same exposure are grouped (one exposure, many
products), and the same fund traded on two exchanges is one product (one ISIN), never two opportunities.

What it does, for every exposure and from data already on disk (catalog + cache/etf_prices.pkl, no download):
- equity exposures: total returns in EUR at 1, 3, 6 and 12 months, the difference against a COHERENT benchmark of the
  same family (never QQQ for everything), how that difference evolved (now vs 21 or 5 sessions earlier, computed only
  with the data available at that earlier date), trend with the approved strict rule of the ETF tab, volatility,
  drawdown, concentration and aggregate valuations only as published by the issuer;
- bond exposures: a separate model (duration and rate sensitivity, yield to maturity, credit quality, maturity, currency
  and hedging, costs): momentum and moving averages are NOT the main method;
- trends (part D): transparent, measurable descriptions of what changed, with the previous value, the period, the
  benchmark, favourable and contrary factors and the data completeness;
- products (part E): the ETFs of the exposure with their differences and a product-quality checklist, kept separate from
  the judgement on the exposure. No product is "the best".

Nothing here is validated: the momentum rules on ETF categories failed their test (phase 24) and the Trading
strategies of phases 3-4B showed no advantage. Conditions and thresholds below are DESCRIPTIVE, fixed on 4 Nov 2026
before looking at today's results; changing them means a new VERSION (saved by the diary). Never "Compra"/"Vendi",
never a probability, never one score mixing trend, cost, risk, product quality and data reliability.

Model versions (both stay in the code, `scan(..., version=...)`):
- E1 (4 Nov 2026): bond condition O1 "yield ÷ duration ≥ 1" among the favourable ones. Kept unchanged so that every
  E1 record of the diary can be reproduced.
- E2 (5 Nov 2026, approved by the user): O1 is no longer a condition. The yield ÷ duration ratio stays as a descriptive
  figure without any threshold; yield, duration, credit, currency hedging and an indicative ±1 point rate scenario are
  shown apart (approximations, never added to the yield). The remaining bond conditions (O2 credit quality, O3 costs)
  describe the product, not an opportunity: in E2 a bond exposure that satisfies them and has no contrary condition is
  "Da approfondire — evidenza insufficiente per un giudizio favorevole", never "Esposizione da approfondire" (no
  automatic promotion, no new threshold). Equity exposures, thresholds and every other rule are identical to E1.
"""
from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

import etf_catalog as cat

VERSION = "E2"                                  # current model; E1 stays reproducible (see above)
VERSIONS = ("E1", "E2")
DISCLAIMER = ("Screening esplorativo, non consulenza finanziaria: descrive com'è andata un'esposizione e quali dati mancano, "
              "non prevede rendimenti. Le condizioni non sono validate: il momentum sulle categorie di ETF non ha superato il "
              "test della Fase 24 e le strategie Trading delle Fasi 3–4B non hanno mostrato vantaggi.")
MODES = {"breve": "Breve periodo (3–30 sedute)", "lungo": "Medio-lungo periodo (3–24 mesi)"}
H = {"1s": 5, "1m": 21, "3m": 63, "6m": 126, "12m": 252}
LAG = {"breve": 5, "lungo": 21}                 # "rilevazione precedente" computed on the past data only
MIN_SESSIONS = {"breve": 70, "lungo": 260}      # aligned sessions needed with the benchmark

# Thresholds (descriptive, not validated; a change = new VERSION)
P = {
    "rs_short": 1.0,        # S2: relative strength over 1 month, points
    "rs_short_up": 0.5,     # S4: 1-month relative strength improved vs 5 sessions ago, points
    "vol_jump_short": 1.3,  # K2: 1-month volatility / 3-month volatility
    "dd_short": -8.0,       # K3: fall from the 3-month high, %
    "rs_long": 2.0,         # L2 / M2: relative strength over 6 months, points
    "rs_long_up": 1.0,      # L4: 6-month relative strength improved vs 21 sessions ago, points
    "vol_jump_long": 1.25,  # M3: 3-month volatility / 12-month volatility
    "dd_long": -15.0,       # M4: fall from the 12-month high, %
    "risk_vol": 25.0,       # risk: 12-month volatility, %
    "risk_top10": 50.0,     # risk: weight of the first 10 holdings, %
    "risk_dd": -20.0,       # risk: fall from the 12-month high, %
    "bond_cushion": 1.0,    # O1: yield ÷ duration (points of rate rise absorbed by one year of yield)
    "bond_quality": 50.0,   # O2: share rated A or better, %
    "bond_cost": 10.0,      # O3: TER as % of the yield to maturity
    "bond_long": 10.0,      # P1: duration in years
    "change_points": 2.0,   # trend list: change of 6-month relative strength (long) to count as improving/worsening
    "max_selected": 6,      # at most this many exposures in "Opportunità da approfondire"
}

STATES_E1 = ["Esposizione da approfondire", "Trend favorevole da monitorare", "Condizioni contrastanti", "Rischio elevato",
             "Dati insufficienti", "Nessuna opportunità convincente", "Riferimento di mercato"]
INSUFFICIENT = "Da approfondire — evidenza insufficiente per un giudizio favorevole"     # E2, bonds only
STATES = STATES_E1[:2] + [INSUFFICIENT] + STATES_E1[2:]                                 # E2 (current)


def states_for(version):
    return STATES_E1 if version == "E1" else STATES


def params_for(version):
    """The thresholds a version uses: E2 has no O1 threshold (bond_cushion stays in P only for E1)."""
    return dict(P) if version == "E1" else {k: v for k, v in P.items() if k != "bond_cushion"}

FAMILIES = {"globale": "Azionario globale", "usa": "Stati Uniti", "europa": "Europa", "emergenti": "Mercati emergenti",
            "settori": "Settori", "temi": "Temi specifici", "gov": "Obbligazionario governativo",
            "corp": "Obbligazionario societario", "altre": "Altre esposizioni (Giappone, fattori, globali, liquidità, materie prime)"}
FAMILY_ORDER = list(FAMILIES)
EUROPE = {"italia", "germania", "regno_unito", "svizzera"}
EMERGING = {"cina", "india", "corea", "taiwan", "brasile", "messico"}
US_SECTORS = {"tech_usa", "sanita_usa", "semiconduttori"}
CORE = {"mondo_sviluppati", "mondo_tutto", "usa_large", "europa", "eurozona", "emergenti", "gov_euro_1_3", "gov_euro_tutte",
        "corporate_euro", "aggregato_globale"}
# Benchmarks: accumulating classes (total return), in EUR, real fund prices
B_WORLD_ALL, B_WORLD_DEV, B_US, B_EU, B_EM = "IE00BK5BQT80", "IE00B4L5Y983", "IE00B5BMR087", "IE00B4K48X80", "IE00BKM4GZ66"
BENCH_NAME = {B_WORLD_ALL: "azionario mondiale (FTSE All-World, VWCE)", B_WORLD_DEV: "mondo sviluppato (MSCI World, SWDA)",
              B_US: "USA grandi società (S&P 500, CSSPX)", B_EU: "Europa (MSCI Europe, SMEA)", B_EM: "mercati emergenti (MSCI EM IMI, EIMI)"}
REFERENCE_EXPOSURE = "mondo_tutto"


# ---------------------------------------------------------------- grouping

def opp_family(k):
    """The family of the opportunity page (8 families plus 'altre') from the catalog's manual classification."""
    ac, fam, exp = k.get("assetClass"), k.get("family"), k.get("exposure")
    if ac == "obbligazionario":
        return {"governativi_euro": "gov", "societarie_euro": "corp"}.get(fam, "altre")
    if ac != "azionario":
        return "altre"
    if fam in ("globale", "usa", "europa", "emergenti"):
        return fam
    if fam == "paese":
        return "europa" if exp in EUROPE else "emergenti" if exp in EMERGING else "altre"
    if fam == "fattori":
        return "altre"
    return "temi" if k.get("theme") else "settori"


def exposures(catalog):
    """{exposure key: {key, label, family, assetClass, members [isin]}}: one exposure for many share classes; a
    class traded on several exchanges is one ISIN, so it is one member."""
    out = {}
    for isin, e in (catalog.get("items") or {}).items():
        if e.get("exclusion"):
            continue
        k = e.get("classification") or {}
        x = out.setdefault(k.get("exposure"), {"key": k.get("exposure"), "label": k.get("label"), "family": opp_family(k),
                                                "assetClass": k.get("assetClass"), "catalogFamily": k.get("familyLabel"),
                                                "theme": bool(k.get("theme")), "members": []})
        if isin not in x["members"]:
            x["members"].append(isin)
    return out


def benchmark_for(x):
    """(isin, name) of the coherent benchmark of an exposure, or (None, reason)."""
    if x["key"] == REFERENCE_EXPOSURE:
        return None, "è il riferimento del mercato azionario mondiale"
    if x["assetClass"] != "azionario":
        return None, "nessun benchmark azionario: si usa un modello separato" if x["assetClass"] == "obbligazionario" else \
            "nessun benchmark coerente per questa esposizione"
    f = x["family"]
    b = {"globale": B_WORLD_ALL, "usa": B_US, "europa": B_EU, "emergenti": B_EM}.get(f)
    if f in ("settori", "temi", "altre"):
        b = B_US if x["key"] in US_SECTORS else B_WORLD_DEV
    if b in x["members"]:                     # the family benchmark itself is measured against the world
        b = B_WORLD_ALL
    return b, BENCH_NAME[b]


# ---------------------------------------------------------------- pure measures (tested with made-up prices)

def cut(s, as_of):
    """Only data up to as_of (no future information)."""
    if s is None:
        return None
    return s[s.index <= pd.Timestamp(as_of)] if as_of is not None else s


def align(a, b):
    """The two series on their common dates only (never a forward-filled holiday)."""
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    return j["a"], j["b"]


def ret(s, n):
    s = s.dropna()
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) * 100 if len(s) > n else None


def rel(a, b, n):
    """Total return of a minus total return of b over the same n aligned sessions, in points."""
    ra, rb = ret(a, n), ret(b, n)
    return None if ra is None or rb is None else ra - rb


def rel_before(a, b, n, lag):
    """The same relative return `lag` sessions earlier, computed only with the data available then."""
    if len(a) <= lag:
        return None
    return rel(a.iloc[:-lag], b.iloc[:-lag], n)


def vol(s, n):
    r = s.pct_change().dropna().iloc[-n:]
    return float(r.std() * math.sqrt(252) * 100) if len(r) >= max(15, int(n * 0.8)) else None


def drawdown(s, n):
    """Fall of the last close from the highest close of the last n sessions, %."""
    w = s.iloc[-n:]
    return float(w.iloc[-1] / w.max() - 1) * 100 if len(w) >= min(n, 20) else None


def sma(s, n):
    return float(s.iloc[-n:].mean()) if len(s) >= n else None


def trend_word(price, s50, s200):
    """The strict rule approved for the ETF tab (etf.trend_word): Rialzista price > 50 > 200, Ribassista the opposite."""
    if None in (price, s50, s200):
        return None
    if price > s50 > s200:
        return "Rialzista"
    if price < s50 < s200:
        return "Ribassista"
    return "Laterale"


def cond(cid, text, ok, value=None, threshold=None, why=None):
    """One condition: ok True / False / None (not evaluable: never counted as satisfied)."""
    return {"id": cid, "text": text, "ok": ok, "value": value, "threshold": threshold, "why": why}


def fmt(x, d=1, sign=True, unit=""):
    if x is None:
        return "n.d."
    s = f"{x:+.{d}f}" if sign else f"{x:.{d}f}"
    return s.replace(".", ",").replace("-", "−") + unit


# ---------------------------------------------------------------- reference series of an exposure

def reference(x, catalog, prices):
    """The class whose prices measure the exposure (not a product choice): a series with the most sessions among the
    unhedged classes whose series is a total return; hedged or price-only classes only if nothing else exists."""
    items, meta, closes = catalog["items"], (prices or {}).get("meta") or {}, (prices or {}).get("closes") or {}
    def key(i):
        e = items[i]
        m = meta.get(i) or {}
        return (i in closes, not bool(cat.val(e["fund"].get("hedged"))), bool(m.get("totalReturn", False)),
                cat.val(e["fund"].get("distribution")) == "accumulazione", m.get("n") or 0)
    best = max(x["members"], key=key)
    return best if best in closes else None


# ---------------------------------------------------------------- equity analysis

def equity_measures(s, b, mode):
    """Measures of one exposure series s against the benchmark b (both EUR, total return), aligned dates."""
    out = {"returns": {k: ret(s, n) for k, n in H.items()}, "sessions": int(len(s)),
           "vol1m": vol(s, 21), "vol3m": vol(s, 63), "vol12m": vol(s, 252),
           "dd3m": drawdown(s, 63), "dd12m": drawdown(s, 252),
           "price": float(s.iloc[-1]), "sma20": sma(s, 20), "sma50": sma(s, 50), "sma200": sma(s, 200), "date": str(s.index[-1].date())}
    out["trend"] = trend_word(out["price"], out["sma50"], out["sma200"])
    if b is not None:
        a2, b2 = align(s, b)
        out["aligned"] = int(len(a2))
        out["rel"] = {k: rel(a2, b2, n) for k, n in H.items()}
        lag = LAG[mode]
        out["relPrev"] = {k: rel_before(a2, b2, n, lag) for k, n in H.items()}
        out["relPrev21"] = {k: rel_before(a2, b2, n, 21) for k, n in H.items()}
        out["relPrev5"] = {k: rel_before(a2, b2, n, 5) for k, n in H.items()}
        out["benchDate"] = str(b2.index[-1].date()) if len(b2) else None
    return out


def risk_block(x, ref_entry, m):
    """Risk dimension, separate from trend: flags with the measured value; level elevato / medio / contenuto."""
    flags = []
    ex = (ref_entry or {}).get("exposure") or {}
    w = cat.val(ex.get("top10Weight"))
    w = w * 100 if w is not None and w <= 1.5 else w
    if m.get("vol12m") is not None and m["vol12m"] >= P["risk_vol"]:
        flags.append({"id": "R1", "text": f"volatilità a 12 mesi {fmt(m['vol12m'], 0, False, '%')} (soglia {P['risk_vol']:.0f}%)", "high": True})
    if w is not None and w >= P["risk_top10"]:
        flags.append({"id": "R2", "text": f"i primi 10 titoli pesano {fmt(w, 0, False, '%')} (soglia {P['risk_top10']:.0f}%)", "high": True})
    if m.get("dd12m") is not None and m["dd12m"] <= P["risk_dd"]:
        flags.append({"id": "R3", "text": f"calo dal massimo a 12 mesi {fmt(m['dd12m'], 0, True, '%')} (soglia {fmt(P['risk_dd'], 0, True, '%')})", "high": True})
    if x["theme"]:
        flags.append({"id": "R4", "text": "tema specifico: poche società, spesso giovani o cicliche", "high": False})
    elif x["family"] == "settori":
        flags.append({"id": "R4", "text": "un solo settore: meno diversificato del mercato", "high": False})
    if x["family"] in ("europa", "emergenti") and x["key"] not in CORE:
        flags.append({"id": "R5", "text": "un solo paese: rischio politico ed economico concentrato", "high": False})
    hedged = cat.val(((ref_entry or {}).get("fund") or {}).get("hedged"))
    cur = [c for c in (cat.val(ex.get("currencyExposure")) or []) if c.get("currency") not in ("EUR", "EUR (coperta)")]
    if not hedged and cur:
        flags.append({"id": "R6", "text": "rischio di cambio: valute dei titoli diverse dall'euro (" +
                      ", ".join(c["currency"] for c in cur[:3]) + ")", "high": False})
    level = "elevato" if any(f["high"] for f in flags) else "medio" if flags else "contenuto"
    return {"level": level, "flags": flags}


def equity_conditions(m, mode, has_bench):
    """(favourable, contrary) conditions of one mode. Without a benchmark the relative ones are not evaluable."""
    r, rp = m.get("rel") or {}, m.get("relPrev") or {}
    nb = None if has_bench else "nessun benchmark coerente"
    if mode == "breve":
        up = r.get("1m") - rp.get("1m") if r.get("1m") is not None and rp.get("1m") is not None else None
        s20, s50 = m.get("sma20"), m.get("sma50")
        fav = [cond("S1", "prezzo sopra la media a 20 sedute e media 20 sopra la media 50",
                    None if s20 is None or s50 is None else (m["price"] > s20 > s50), fmt(m["price"] / s20 * 100 - 100 if s20 else None, 1, True, "% dalla media 20")),
               cond("S2", f"forza relativa a 1 mese di almeno +{fmt(P['rs_short'], 1, False)} punti", None if r.get("1m") is None else r["1m"] >= P["rs_short"],
                    fmt(r.get("1m"), 1, True, " punti"), P["rs_short"], nb),
               cond("S3", "forza relativa a 3 mesi non negativa", None if r.get("3m") is None else r["3m"] >= 0, fmt(r.get("3m"), 1, True, " punti"), 0, nb),
               cond("S4", f"forza relativa a 1 mese salita di almeno {fmt(P['rs_short_up'], 1, False)} punti in 5 sedute",
                    None if up is None else up >= P["rs_short_up"], fmt(up, 1, True, " punti"), P["rs_short_up"], nb)]
        v1, v3 = m.get("vol1m"), m.get("vol3m")
        jump = v1 / v3 if v1 and v3 else None
        con = [cond("K1", "prezzo sotto la media a 50 sedute", None if s50 is None else m["price"] < s50),
               cond("K2", f"volatilità a 1 mese almeno {fmt(P['vol_jump_short'], 2, False)} volte quella a 3 mesi",
                    None if jump is None else jump >= P["vol_jump_short"], fmt(jump, 2, False, "×"), P["vol_jump_short"]),
               cond("K3", f"calo dal massimo di 3 mesi oltre {fmt(P['dd_short'], 0, True, '%')}", None if m.get("dd3m") is None else m["dd3m"] <= P["dd_short"],
                    fmt(m.get("dd3m"), 1, True, "%"), P["dd_short"]),
               cond("K4", f"forza relativa a 1 mese di −{fmt(P['rs_short'], 1, False)} punti o peggio", None if r.get("1m") is None else r["1m"] <= -P["rs_short"],
                    fmt(r.get("1m"), 1, True, " punti"), -P["rs_short"], nb)]
        return fav, con
    up = r.get("6m") - rp.get("6m") if r.get("6m") is not None and rp.get("6m") is not None else None
    fav = [cond("L1", "trend rialzista: prezzo sopra la media 50 e media 50 sopra la media 200", None if m.get("trend") is None else m["trend"] == "Rialzista",
                m.get("trend") or "n.d."),
           cond("L2", f"forza relativa a 6 mesi di almeno +{fmt(P['rs_long'], 0, False)} punti", None if r.get("6m") is None else r["6m"] >= P["rs_long"],
                fmt(r.get("6m"), 1, True, " punti"), P["rs_long"], nb),
           cond("L3", "forza relativa a 12 mesi non negativa", None if r.get("12m") is None else r["12m"] >= 0, fmt(r.get("12m"), 1, True, " punti"), 0, nb),
           cond("L4", f"forza relativa a 6 mesi salita di almeno {fmt(P['rs_long_up'], 0, False)} punto in 21 sedute",
                None if up is None else up >= P["rs_long_up"], fmt(up, 1, True, " punti"), P["rs_long_up"], nb)]
    v3, v12 = m.get("vol3m"), m.get("vol12m")
    jump = v3 / v12 if v3 and v12 else None
    con = [cond("M1", "trend ribassista: prezzo sotto la media 50 e media 50 sotto la media 200", None if m.get("trend") is None else m["trend"] == "Ribassista",
                m.get("trend") or "n.d."),
           cond("M2", f"forza relativa a 6 mesi di −{fmt(P['rs_long'], 0, False)} punti o peggio", None if r.get("6m") is None else r["6m"] <= -P["rs_long"],
                fmt(r.get("6m"), 1, True, " punti"), -P["rs_long"], nb),
           cond("M3", f"volatilità a 3 mesi almeno {fmt(P['vol_jump_long'], 2, False)} volte quella a 12 mesi",
                None if jump is None else jump >= P["vol_jump_long"], fmt(jump, 2, False, "×"), P["vol_jump_long"]),
           cond("M4", f"calo dal massimo a 12 mesi oltre {fmt(P['dd_long'], 0, True, '%')}", None if m.get("dd12m") is None else m["dd12m"] <= P["dd_long"],
                fmt(m.get("dd12m"), 1, True, "%"), P["dd_long"])]
    return fav, con


def state_of(fav, con, risk_level, enough=True):
    """The state from explicit rules (documented in the page). A condition not evaluable never counts as satisfied."""
    if not enough:
        return "Dati insufficienti"
    nf = sum(1 for c in fav if c["ok"] is True)
    nc = sum(1 for c in con if c["ok"] is True)
    if nf == len(fav) and nc == 0:
        return "Rischio elevato" if risk_level == "elevato" else "Esposizione da approfondire"
    if nf >= 2 and nc == 0:
        return "Trend favorevole da monitorare"
    if nf >= 1 and nc >= 1:
        return "Condizioni contrastanti"
    if risk_level == "elevato" and nc >= 1:
        return "Rischio elevato"
    return "Nessuna opportunità convincente"


# ---------------------------------------------------------------- bonds

def bond_measures(e):
    """Bond figures of one product (the issuer's, each with its date)."""
    b = (e or {}).get("bond") or {}
    g = lambda k: cat.val(b.get(k))
    dur, ytm = g("duration"), g("yield")
    rat = g("ratings") or []
    a_or_better = sum(r["weight"] for r in rat if r["name"].split()[0] in ("AAA", "AA", "A")) if rat else None
    ter = cat.val(((e or {}).get("costs") or {}).get("ter"))
    return {"duration": dur, "durationAsOf": (b.get("duration") or {}).get("asOf"), "yield": ytm, "yieldAsOf": (b.get("yield") or {}).get("asOf"), "maturity": g("maturity"),
            "coupon": g("coupon"), "distYield": g("distYield"), "aOrBetter": a_or_better, "ratingsAsOf": (b.get("ratings") or {}).get("asOf"),
            "kind": g("bondKind"), "credit": g("credit"), "currency": g("currency"), "ter": ter,
            "cushion": ytm / dur if ytm is not None and dur else None,
            "sensitivity": -dur if dur is not None else None,
            "yieldAfterTer": ytm - ter if ytm is not None and ter is not None else None,
            "costShare": ter / ytm * 100 if ter is not None and ytm else None,
            "inflationLinked": "inflazione" in (g("bondKind") or ""), "singleIssuer": "un solo emittente" in (g("bondKind") or "") + (g("credit") or "")}


RATE_SHIFT = 1.0      # E2: indicative scenario of ±1 point on market yields (asked by the user, not a forecast)


def bond_profile(e, bm):
    """E2: descriptive bond figures shown apart (none of them is a condition). Rate sensitivity: price change ≈
    −duration × change of yields, with the modified duration when the issuer publishes it, otherwise the effective
    duration (declared). A linear approximation, never added to the yield to maturity."""
    b = (e or {}).get("bond") or {}
    mod = cat.val(b.get("modifiedDuration"))
    dur = mod if mod is not None else bm["duration"]
    kind = "modificata" if mod is not None else "effettiva" if dur is not None else None
    h = ((e or {}).get("fund") or {}).get("hedged")
    hedged = cat.val(h) if isinstance(h, dict) else h
    real = bm["inflationLinked"]
    scen = None if dur is None else [{"shift": RATE_SHIFT, "priceChange": -dur * RATE_SHIFT},
                                     {"shift": -RATE_SHIFT, "priceChange": dur * RATE_SHIFT}]
    notes = []
    if dur is None:
        notes.append("duration non pubblicata nelle fonti lette: sensibilità ai tassi non calcolabile")
    else:
        notes.append(f"approssimazione lineare con la duration {kind}: vale per variazioni piccole e uguali su tutte le scadenze, "
                     "ignora la convessità; non è una previsione")
        if kind == "effettiva":
            notes.append("duration modificata non pubblicata: usata la duration effettiva dell'emittente")
    if real:
        notes.append("titoli indicizzati all'inflazione: la sensibilità riguarda i rendimenti reali, non quelli nominali")
    notes.append("il rendimento a scadenza non si somma alla variazione di prezzo stimata: insieme non danno un rendimento certo")
    return {"durationKind": kind, "durationUsed": dur, "modifiedDuration": mod, "rateScenarios": scen, "scenarioNotes": notes,
            "ratio": bm["cushion"],
            "ratioNote": None if bm["cushion"] is None else
            ("rendimento reale ÷ duration: solo descrittivo, nessuna soglia, non confrontabile con quelli nominali" if real else
             "rendimento ÷ duration: solo descrittivo, nessuna soglia di approvazione (nel modello E1 era la condizione O1)"),
            "hedged": hedged, "hedgedText": "n.d." if hedged is None else
            ("classe coperta dal rischio di cambio verso la sua valuta di base" if hedged else "cambio non coperto")}


def bond_conditions(bm, version=VERSION):
    """Favourable and contrary bond conditions. E1 keeps O1; E2 drops it (descriptive ratio only)."""
    if version != "E1":
        fav = [cond("O2", f"almeno il {P['bond_quality']:.0f}% dei titoli con rating A o superiore", None if bm["aOrBetter"] is None else bm["aOrBetter"] >= P["bond_quality"],
                    fmt(bm["aOrBetter"], 0, False, "%"), P["bond_quality"]),
               cond("O3", f"TER non oltre il {P['bond_cost']:.0f}% del rendimento a scadenza", None if bm["costShare"] is None else bm["costShare"] <= P["bond_cost"],
                    fmt(bm["costShare"], 0, False, "%"), P["bond_cost"])]
        return fav, bond_contrary(bm)
    fav = [cond("O1", f"euristica sperimentale, non un criterio finanziario standard: un anno di rendimento compensa un rialzo dei "
                      f"tassi di almeno {fmt(P['bond_cushion'], 0, False)} punto (rendimento ÷ duration)",
                None if bm["cushion"] is None or bm["inflationLinked"] else bm["cushion"] >= P["bond_cushion"], fmt(bm["cushion"], 2, False, " punti"),
                P["bond_cushion"], "rendimento reale (indicizzati all'inflazione): non confrontabile" if bm["inflationLinked"] else None),
           cond("O2", f"almeno il {P['bond_quality']:.0f}% dei titoli con rating A o superiore", None if bm["aOrBetter"] is None else bm["aOrBetter"] >= P["bond_quality"],
                fmt(bm["aOrBetter"], 0, False, "%"), P["bond_quality"]),
           cond("O3", f"TER non oltre il {P['bond_cost']:.0f}% del rendimento a scadenza", None if bm["costShare"] is None else bm["costShare"] <= P["bond_cost"],
                fmt(bm["costShare"], 0, False, "%"), P["bond_cost"])]
    return fav, bond_contrary(bm)


def bond_contrary(bm):
    return [cond("P1", f"duration di almeno {P['bond_long']:.0f} anni: circa −{P['bond_long']:.0f}% per ogni punto di rialzo dei tassi",
                None if bm["duration"] is None else bm["duration"] >= P["bond_long"], fmt(bm["duration"], 1, False, " anni"), P["bond_long"]),
           cond("P2", "un solo emittente (rischio concentrato)", bool(bm["singleIssuer"]), "sì" if bm["singleIssuer"] else "no")]


def bond_state(bm, fav, con, version=VERSION):
    """E1 and E2 share every rule except the top one: in E2 credit quality and costs (O2, O3) alone are not evidence of
    an opportunity, so the best bond state is INSUFFICIENT, not "Esposizione da approfondire"."""
    if bm["duration"] is None or bm["yield"] is None:
        return "Dati insufficienti"
    if any(c["ok"] for c in con):
        return "Rischio elevato"
    nf = sum(1 for c in fav if c["ok"] is True)
    top = "Esposizione da approfondire" if version == "E1" else INSUFFICIENT
    return top if nf == len(fav) else "Condizioni contrastanti" if nf >= 1 else "Nessuna opportunità convincente"


def bond_role(x, bm):
    if bm["duration"] is None:
        return "ruolo non definibile senza duration"
    if x["family"] == "corp":
        return "rendimento con rischio di credito (società) e rischio tasso medio"
    if bm["duration"] <= 3:
        return "stabilizzazione: oscillazioni contenute, sensibilità ai tassi bassa"
    if bm["duration"] >= P["bond_long"]:
        return "scommessa sui tassi: forte sensibilità, oscillazioni simili alle azioni"
    return "rendimento con rischio tasso medio"


# ---------------------------------------------------------------- products of an exposure

def product(e, prices, now=None):
    """Facts and a product-quality checklist of one ETF, separate from the judgement on the exposure."""
    f, c, ex = e.get("fund") or {}, e.get("costs") or {}, e.get("exposure") or {}
    meta = ((prices or {}).get("meta") or {}).get(e["isin"]) or {}
    lst = e.get("listings") or []
    turn = [(l["ticker"], l["venue"], cat.val(l.get("avgTurnover3m")), l.get("zeroVolumeDays")) for l in lst if cat.val(l.get("avgTurnover3m")) is not None]
    sp = next(((l, cat.spread_state(l.get("spread"), now)) for l in lst if l.get("spread")), None)
    td = c.get("trackingDifference") or {}
    size = f.get("sizeFund") or {}
    years = (meta.get("n") or 0) / 252
    ter = c.get("ter") or {}
    checks = [
        cond("Q1", "TER confermato da un documento dell'emittente", None if ter.get("v") is None and c.get("terResolution") == "non risolto"
             else c.get("terResolution") in ("riferimento dell'emittente", "documento dell'emittente verificato a mano"), c.get("terResolution")),
        cond("Q2", "patrimonio del fondo di almeno 100 milioni", None if size.get("v") is None else size["v"] >= 100,
             f"{size.get('v'):,.0f} mln {size.get('unit') or ''}".replace(",", ".") if size.get("v") is not None else "n.d."),
        cond("Q3", "tracking difference pubblicata e calcolabile", td.get("v") is not None, fmt(td.get("avg"), 2, True, " punti l'anno") if td.get("v") is not None else td.get("note")),
        cond("Q4", "scambi medi di almeno 100.000 € al giorno su una borsa", None if not turn else max(t[2] for t in turn) >= 100000,
             f"{max(t[2] for t in turn):,.0f} €".replace(",", ".") if turn else "n.d."),
        cond("Q5", "spread rappresentativo letto a mercato aperto", None if not sp else sp[1][0] == "rappresentativo", sp[1][1] if sp else "n.d."),
        cond("Q6", "almeno un anno di prezzi della classe", None if not meta else years >= 1, f"{years:.1f} anni".replace(".", ",") if meta else "n.d."),
    ]
    order = {"ETFP": 0, "XETR": 1}
    tick = list(dict.fromkeys(l["ticker"] for l in sorted(lst, key=lambda l: order.get(l.get("mic"), 9)) if l.get("ticker")))
    return {"isin": e["isin"], "name": cat.val(e["identity"]["name"]), "tickers": tick, "issuer": cat.val(e["identity"]["issuer"]),
            "index": cat.val(e["identity"]["index"]), "ter": ter.get("v"), "terState": c.get("terState"), "terResolution": c.get("terResolution"),
            "terNote": ter.get("note"), "td": td.get("v"), "tdAvg": td.get("avg"), "tdNote": td.get("note"), "replication": cat.val(f.get("replication")),
            "distribution": cat.val(f.get("distribution")), "frequency": cat.val(f.get("distributionFrequency")), "hedged": cat.val(f.get("hedged")),
            "size": size.get("v"), "sizeUnit": size.get("unit"), "domicile": cat.val(e["identity"]["domicile"]),
            "tradingCurrencies": sorted({cat.val(l.get("currency")) for l in lst if cat.val(l.get("currency"))}),
            "listings": [{"ticker": l["ticker"], "venue": l["venue"], "turnover": cat.val(l.get("avgTurnover3m")),
                          "zeroDays": l.get("zeroVolumeDays")} for l in lst],
            "spread": sp[1][1] if sp else "n.d. (nessun book letto)", "broker": c.get("brokerAvailability") or "non verificata",
            "priceSeries": {"symbol": meta.get("symbol"), "from": meta.get("first"), "years": round(years, 1) if meta else None,
                            "totalReturn": meta.get("totalReturn"), "choice": meta.get("choice")},
            "status": e.get("status"), "checks": checks,
            "valuation": {k: {"v": v.get("v"), "asOf": v.get("asOf")} for k, v in (e.get("valuation") or {}).items()}}


def product_block(x, catalog, prices, ref, now=None):
    import etf_comparison as cmp
    items = catalog["items"]
    prods = [product(items[i], prices, now) for i in x["members"]]
    for p in prods:
        lv, why = cmp.pair_level(items[ref], items[p["isin"]]) if ref and p["isin"] != ref else (None, [])
        p["level"], p["levelWhy"] = lv, why
    diffs = cmp.differences([items[i] for i in x["members"]]) if len(x["members"]) > 1 else []
    tds = [p for p in prods if p["td"] is not None]
    if len(x["members"]) == 1:
        verdict = "un solo ETF nel catalogo per questa esposizione: nessun confronto possibile"
    elif len(tds) < len(prods) or any(p["ter"] is None for p in prods):
        verdict = "dati incompleti (TER o tracking difference mancanti): nessun prodotto indicato come preferibile"
    else:
        verdict = "confronta costi, tracking difference, liquidità e struttura: il catalogo non sceglie un vincitore"
    similar = []
    fam = (items[ref]["classification"] if ref else {}).get("family")
    for i, e in items.items():
        k = e.get("classification") or {}
        if not e.get("exclusion") and k.get("family") == fam and k.get("exposure") != x["key"] and fam not in (None,):
            similar.append({"isin": i, "label": k.get("label"), "name": cat.val(e["identity"]["name"]), "level": 3})
    return {"products": prods, "differences": diffs, "verdict": verdict, "similar": similar[:6],
            "compare": x["members"][:4]}


# ---------------------------------------------------------------- one exposure

def trends(x, m, mode, risk, bench_name):
    """Part D: what changed, described with measurable conditions (never a forecast)."""
    if not m or "rel" not in m:
        return []
    r, p21, p5 = m["rel"], m.get("relPrev21") or {}, m.get("relPrev5") or {}
    out = []
    def add(kind, label, obs, period, prev, fav, con):
        out.append({"kind": kind, "label": label, "observed": obs, "period": period, "benchmark": bench_name, "previous": prev,
                    "favourable": fav, "contrary": con})
    short = mode == "breve"
    k, lag, pk = ("1m", 5, p5) if short else ("3m", 21, p21)
    if r.get(k) is not None and pk.get(k) is not None:
        if r[k] > 0 >= pk[k]:
            add("sovraperforma", "Inizia a fare meglio del suo mercato", f"differenza a {'1 mese' if short else '3 mesi'} {fmt(r[k])} punti",
                f"{'1 mese' if short else '3 mesi'}", f"{fmt(pk[k])} punti {lag} sedute fa", ["forza relativa tornata positiva"],
                ["un passaggio sopra zero può durare poco: non è una previsione"])
        elif r[k] < 0 <= pk[k]:
            add("sottoperforma", "Inizia a fare peggio del suo mercato", f"differenza a {'1 mese' if short else '3 mesi'} {fmt(r[k])} punti",
                f"{'1 mese' if short else '3 mesi'}", f"{fmt(pk[k])} punti {lag} sedute fa", [], ["forza relativa diventata negativa"])
    if not short and r.get("6m") is not None and p21.get("6m") is not None:
        st = lambda v: "forte" if v >= P["rs_long"] else "debole" if v <= -P["rs_long"] else "neutra"
        a, b = st(p21["6m"]), st(r["6m"])
        if a == "debole" and b != "debole":
            add("miglioramento", "Da debolezza a forza relativa", f"differenza a 6 mesi {fmt(r['6m'])} punti ({b})", "6 mesi",
                f"{fmt(p21['6m'])} punti 21 sedute fa (debole)", ["la differenza col mercato è risalita"], [])
        elif a == "forte" and b != "forte":
            add("peggioramento", "La forza relativa si è affievolita", f"differenza a 6 mesi {fmt(r['6m'])} punti ({b})", "6 mesi",
                f"{fmt(p21['6m'])} punti 21 sedute fa (forte)", [], ["la differenza col mercato è scesa"])
    if m.get("trend") == "Rialzista" and r.get("1m") is not None and r["1m"] <= -1 and (r.get("6m") or 0) > 0:
        add("perde_intensita", "Trend positivo che perde intensità", f"ultimo mese {fmt(r['1m'])} punti contro il mercato", "1 mese",
            f"a 6 mesi ancora {fmt(r['6m'])} punti", ["trend rialzista sulle medie"], ["ultimo mese peggiore del mercato"])
    v_a, v_b = (m.get("vol1m"), m.get("vol3m")) if short else (m.get("vol3m"), m.get("vol12m"))
    if v_a and v_b and v_a / v_b >= (P["vol_jump_short"] if short else P["vol_jump_long"]):
        add("volatilita", "Volatilità in aumento", f"volatilità {fmt(v_a, 0, False, '%')} contro {fmt(v_b, 0, False, '%')}",
            "1 contro 3 mesi" if short else "3 contro 12 mesi", f"{fmt(v_b, 0, False, '%')} sul periodo più lungo", [], ["oscillazioni più ampie"])
    if (r.get("6m") or 0) >= 5 and any(f["id"] in ("R2", "R4", "R5") for f in risk["flags"]):
        add("forte_concentrato", "Molto forte ma concentrato", f"differenza a 6 mesi {fmt(r['6m'])} punti", "6 mesi", None,
            ["forza relativa elevata"], [f["text"] for f in risk["flags"] if f["id"] in ("R2", "R4", "R5")])
    return out


def analyze_exposure(x, catalog, prices, mode, as_of=None, previous=None, now=None, version=VERSION):
    items = catalog["items"]
    closes = (prices or {}).get("closes") or {}
    ref = reference(x, catalog, prices)
    ref_e = items.get(ref) if ref else items[x["members"][0]]
    bench, bench_name = benchmark_for(x)
    out = {"key": x["key"], "label": x["label"], "family": x["family"], "familyLabel": FAMILIES[x["family"]],
           "assetClass": x["assetClass"], "members": x["members"], "reference": ref,
           "referenceWhy": "classe scelta solo per misurare l'esposizione (serie più lunga, non coperta, con dividendi): non è una preferenza",
           "benchmark": bench, "benchmarkName": bench_name, "role": None, "core": x["key"] in CORE}
    s = cut(closes.get(ref), as_of) if ref else None
    data_notes = []
    if x["assetClass"] == "obbligazionario":
        cands = [items[i] for i in x["members"]]
        with_data = [e for e in cands if bond_measures(e)["duration"] is not None and bond_measures(e)["yield"] is not None]
        be = with_data[0] if with_data else ref_e
        bm = bond_measures(be)
        if version != "E1":                         # E2: descriptive figures added, the E1 record stays as it was
            bm = dict(bm, **bond_profile(be, bm))
        fav, con = bond_conditions(bm, version)
        st = bond_state(bm, fav, con, version)
        out.update(kind="bond", bond=bm, bondSource=be["isin"], role=bond_role(x, bm), conditions={"fav": fav, "con": con}, state=st)
        # phase 6C: the date of the price and the dates of the fund's characteristics stay separate (never mixed)
        pdate = str(s.index[-1].date()) if s is not None and len(s) else None
        out["dates"] = {"price": pdate, "duration": bm.get("durationAsOf"), "yield": bm.get("yieldAsOf"), "ratings": bm.get("ratingsAsOf")}
        older = sorted({k for k in ("duration", "yield", "ratings") if out["dates"][k] and pdate and out["dates"][k] < pdate})
        if older:
            data_notes.append("caratteristiche del fondo (" + ", ".join({"duration": "duration", "yield": "rendimento a scadenza",
                              "ratings": "rating"}[k] for k in older) + f") al {min(out['dates'][k] for k in older)}, prezzo al {pdate}: "
                              "date diverse, il rendimento non è ricalcolato sul prezzo più recente")
        if not with_data:
            data_notes.append("duration e rendimento a scadenza non pubblicati nelle fonti lette per " + ", ".join(cands_t(cands)))
        if previous and previous.get("bond") and bm["yield"] is not None and previous["bond"].get("yield") is not None:
            out["bondChange"] = {"yield": bm["yield"] - previous["bond"]["yield"], "duration": (bm["duration"] or 0) - (previous["bond"].get("duration") or 0),
                                 "since": previous.get("session")}
        else:
            out["bondChange"] = None
        if s is not None and len(s) > 63:
            out["measures"] = {"returns": {k: ret(s, n) for k, n in H.items()}, "dd12m": drawdown(s, 252), "vol12m": vol(s, 252),
                               "date": str(s.index[-1].date())}
        out["risk"] = {"level": "elevato" if st == "Rischio elevato" else "medio" if x["family"] == "corp" else "contenuto",
                       "flags": [{"id": c["id"], "text": c["text"], "high": True} for c in con if c["ok"]]}
        out["trends"] = []
        if out["bondChange"] and abs(out["bondChange"]["yield"]) >= 0.25:
            ch = out["bondChange"]
            out["trends"].append({"kind": "obbligazioni", "label": "Rendimento a scadenza cambiato", "observed": f"{fmt(ch['yield'], 2)} punti",
                                  "period": f"dal {ch['since']}", "benchmark": None, "previous": None,
                                  "favourable": ["rendimento più alto"] if ch["yield"] > 0 else [],
                                  "contrary": ["prezzi scesi con il rialzo dei rendimenti"] if ch["yield"] > 0 else ["rendimento più basso"]})
        evaluable = sum(1 for c in fav + con if c["ok"] is not None)
        out["completeness"] = {"conditions": f"{evaluable} su {len(fav) + len(con)}", "notes": data_notes,
                               "analysis": "sufficiente" if st != "Dati insufficienti" else "insufficiente"}
    else:
        b = cut(closes.get(bench), as_of) if bench else None
        enough = s is not None and len(s) >= MIN_SESSIONS[mode]
        if bench and b is None:
            data_notes.append("prezzi del benchmark non disponibili")
        if s is None:
            data_notes.append("nessuna serie di prezzi per le classi di questa esposizione")
        elif len(s) < MIN_SESSIONS[mode]:
            data_notes.append(f"storico di {len(s)} sedute, ne servono {MIN_SESSIONS[mode]}")
        m = equity_measures(s, b, mode) if s is not None and len(s) > 25 else {}
        if m and bench and m.get("benchDate") and m["benchDate"] != m["date"]:        # phase 6C: never silently
            data_notes.append(f"benchmark aggiornato al {(b.index[-1].date() if b is not None and len(b) else 'n.d.')}, ETF al {m['date']}: "
                              f"la forza relativa usa solo le date comuni (fino al {m['benchDate']})")
        out["dates"] = {"price": m.get("date"), "benchmark": str(b.index[-1].date()) if b is not None and len(b) else None,
                        "common": m.get("benchDate")}
        if m and bench and m.get("aligned", 0) < MIN_SESSIONS[mode]:
            enough = False
            data_notes.append(f"solo {m.get('aligned', 0)} sedute in comune con il benchmark")
        risk = risk_block(x, ref_e, m) if m else {"level": "non valutabile", "flags": []}
        fav, con = equity_conditions(m, mode, bench is not None) if m else ([], [])
        if x["key"] == REFERENCE_EXPOSURE or x["assetClass"] == "monetario":
            st = "Riferimento di mercato"
        elif x["assetClass"] != "azionario" and m:
            st = state_of(fav, con, risk["level"], enough)
        else:
            st = state_of(fav, con, risk["level"], enough and bench is not None) if m else "Dati insufficienti"
        out.update(kind="equity", measures=m, conditions={"fav": fav, "con": con}, state=st, risk=risk,
                   trends=trends(x, m, mode, risk, bench_name) if bench else [])
        if x["assetClass"] == "azionario":
            out["role"] = ("base diversificata (esposizione ampia)" if x["key"] in CORE else
                           "complemento concentrato (settore, tema, paese o stile)")
        ex = ref_e.get("exposure") or {}
        w = cat.val(ex.get("top10Weight"))
        out["concentration"] = {"top10": (w * 100 if w is not None and w <= 1.5 else w), "src": (ex.get("top10") or {}).get("note"),
                                "asOf": (ex.get("top10") or {}).get("asOf"), "kind": ex.get("top10Kind"),
                                "countries": cat.val(ex.get("countries")), "sectors": cat.val(ex.get("sectors"))}
        val = ref_e.get("valuation") or {}
        bval = (items.get(bench) or {}).get("valuation") or {} if bench else {}
        out["valuation"] = {"pe": (val.get("priceEarnings") or {}).get("v"), "pb": (val.get("priceBook") or {}).get("v"),
                            "asOf": (val.get("priceEarnings") or {}).get("asOf"),
                            "benchPe": (bval.get("priceEarnings") or {}).get("v"),
                            "note": "P/E e P/B calcolati dall'emittente sui titoli del fondo; nessuna stima di questo programma"
                            if val else "valutazioni aggregate non pubblicate dalle fonti lette per questa classe: non calcolate"}
        evaluable = sum(1 for c in fav + con if c["ok"] is not None)
        out["completeness"] = {"conditions": f"{evaluable} su {len(fav) + len(con)}" if fav else "0", "notes": data_notes,
                               "analysis": "sufficiente" if st not in ("Dati insufficienti",) else "insufficiente"}
    out["favourable"] = [c for c in out["conditions"]["fav"] if c["ok"] is True]
    out["contrary"] = [c for c in out["conditions"]["con"] if c["ok"] is True]
    out["missing"] = [c for c in out["conditions"]["fav"] + out["conditions"]["con"] if c["ok"] is None]
    out["version"] = version
    out["why"] = reasons(out)
    out["invalidate"] = invalidators(out, mode)
    out["catalogCompleteness"] = cat.completeness(ref_e)["state"]
    out["products"] = product_block(x, catalog, prices, ref or x["members"][0], now)
    out["prices"] = {i: {"last": float(cut(closes[i], as_of).iloc[-1]), "date": str(cut(closes[i], as_of).index[-1].date())}
                     for i in x["members"] if i in closes and len(cut(closes[i], as_of))}
    return out


def cands_t(cands):
    return [cat.tickers(e)[0] if cat.tickers(e) else e["isin"] for e in cands]


def reasons(o):
    """Why the exposure is in its state, from the conditions (each sentence from a measured value)."""
    if o["state"] == "Riferimento di mercato":
        if o["assetClass"] == "monetario":
            return ["liquidità in euro (tasso €STR): riferimento del rendimento quasi senza rischio, non un'opportunità"]
        return ["è il mercato azionario mondiale: serve da riferimento per le altre esposizioni"]
    if o["state"] == "Dati insufficienti":
        return o["completeness"]["notes"] or ["condizioni non valutabili"]
    out = [f"✓ {c['text']} ({c['value']})" for c in o["favourable"]]
    out += [f"✕ {c['text']} ({c['value']})" for c in o["contrary"]]
    if o["state"] == "Rischio elevato":
        out += ["⚠ " + f["text"] for f in (o.get("risk") or {}).get("flags", []) if f["high"]]
    if o["state"] == INSUFFICIENT:
        out.append("qualità del credito e costi descrivono il prodotto, non un'opportunità: il modello E2 non ha un criterio "
                   "validato per un giudizio favorevole sulle obbligazioni (rendimento ÷ duration ora è solo descrittivo)")
    return out


def invalidators(o, mode):
    """What would change the judgement (descriptive)."""
    if o["kind"] == "bond":
        bm = o["bond"]
        out = []
        if bm["duration"]:
            out.append(f"un rialzo dei tassi di 1 punto costerebbe circa il {fmt(bm['duration'], 1, False)}% del valore")
        if o["family"] == "corp":
            out.append("un allargamento degli spread di credito delle società")
        out.append("un nuovo dato dell'emittente con rendimento o duration molto diversi")
        return out
    if mode == "breve":
        return ["la forza relativa a 1 mese torna sotto zero", "il prezzo scende sotto la media a 20 sedute",
                "la volatilità a 1 mese sale oltre 1,3 volte quella a 3 mesi"]
    return ["il prezzo scende sotto la media a 50 sedute (trend non più rialzista)", "la forza relativa a 6 mesi torna sotto zero",
            "un calo dal massimo a 12 mesi oltre il 15%", "la concentrazione o la volatilità crescono oltre le soglie di rischio"]


# ---------------------------------------------------------------- whole scan

def order_key(o, mode):
    """Exploratory order, declared in the page: more favourable conditions, fewer contrary, then relative strength
    (1 month in the short mode, 6 months in the long one). Not a forecast and not a score."""
    r = ((o.get("measures") or {}).get("rel") or {}).get("1m" if mode == "breve" else "6m")
    return (-len(o["favourable"]), len(o["contrary"]), -(r if r is not None else -999))


def scan(catalog, prices, mode="lungo", as_of=None, previous=None, now=None, version=VERSION):
    """Every exposure analysed in one mode, the overview and the short selection. Pure on its inputs. `version` E1
    reproduces the 4 Nov 2026 model exactly; E2 is the current one."""
    if mode not in MODES:
        raise ValueError("modo sconosciuto")
    if version not in VERSIONS:
        raise ValueError("versione del modello sconosciuta")
    states = states_for(version)
    previous = previous or {}
    X = exposures(catalog)
    rows = [analyze_exposure(x, catalog, prices, mode, as_of, previous.get(k), now, version) for k, x in X.items()]
    rows.sort(key=lambda o: (FAMILY_ORDER.index(o["family"]), states.index(o["state"]), o["label"]))
    sel = sorted([o for o in rows if o["state"] == "Esposizione da approfondire"], key=lambda o: order_key(o, mode))[:P["max_selected"]]
    for n, o in enumerate(sel, 1):
        o["rank"] = n
    lk = "1m" if mode == "breve" else "6m"
    def change(o):
        m = o.get("measures") or {}
        a, b = (m.get("rel") or {}).get(lk), (m.get("relPrev") or {}).get(lk)
        return None if a is None or b is None else a - b
    ch = [(o, change(o)) for o in rows if o["kind"] == "equity" and change(o) is not None]
    thr = P["change_points"] if mode == "lungo" else P["rs_short_up"] * 2
    better = sorted([(o, c) for o, c in ch if c >= thr], key=lambda t: -t[1])[:5]
    worse = sorted([(o, c) for o, c in ch if c <= -thr], key=lambda t: t[1])[:5]
    risks = [o for o in rows if (o.get("risk") or {}).get("level") == "elevato"]
    counts = {s: sum(1 for o in rows if o["state"] == s) for s in states}
    last = max(((o.get("measures") or {}).get("date") or "") for o in rows) or None
    for o in rows:                                  # phase 6C: a series that stops before the latest session is declared
        d = (o.get("dates") or {}).get("price")
        if d and last and d < last:
            note = f"prezzi fermi al {d}: la seduta più recente delle altre serie è il {last}"
            if note not in o["completeness"]["notes"]:
                o["completeness"]["notes"].append(note)
    meta = (prices or {}).get("meta") or {}
    world = next((o for o in rows if o["key"] == REFERENCE_EXPOSURE), None)
    return {"version": version, "mode": mode, "modeLabel": MODES[mode], "asOf": as_of, "session": last,
            "pricesFetched": (prices or {}).get("fetched"), "pricesSource": (prices or {}).get("source"),
            "catalogBuilt": catalog.get("builtAt"), "disclaimer": DISCLAIMER,
            "overview": {"exposures": len(rows), "products": sum(len(x["members"]) for x in X.values()), "counts": counts,
                         "improving": [{"key": o["key"], "label": o["label"], "change": c, "period": lk} for o, c in better],
                         "worsening": [{"key": o["key"], "label": o["label"], "change": c, "period": lk} for o, c in worse],
                         "risks": [{"key": o["key"], "label": o["label"], "flags": [f["text"] for f in o["risk"]["flags"] if f.get("high")]} for o in risks],
                         "world": {"returns": ((world or {}).get("measures") or {}).get("returns"), "trend": ((world or {}).get("measures") or {}).get("trend")} if world else None,
                         "priceSeries": len((prices or {}).get("closes") or {}), "missingSeries": [i for i, m in meta.items() if m.get("missing")]},
            "selected": [o["key"] for o in sel],
            "noneText": None if sel else "Nessuna esposizione soddisfa oggi tutte le condizioni favorevoli senza condizioni contrarie.",
            "orderRule": "ordine esplorativo: prima più condizioni favorevoli, poi meno contrarie, poi forza relativa " +
                         ("a 1 mese" if mode == "breve" else "a 6 mesi") + ". Non è una previsione né un punteggio.",
            "families": [{"key": k, "label": v} for k, v in FAMILIES.items()], "params": params_for(version), "states": states,
            "rows": rows}


def summary_row(o):
    """A compact row for the list (the detail is sent only when an exposure is opened)."""
    m = o.get("measures") or {}
    return {k: o.get(k) for k in ("key", "label", "family", "familyLabel", "assetClass", "state", "role", "core", "benchmarkName", "kind", "rank")} | {
        "returns": m.get("returns"), "rel": m.get("rel"), "trend": m.get("trend"), "vol12m": m.get("vol12m"), "dd12m": m.get("dd12m"),
        "risk": (o.get("risk") or {}).get("level"), "riskFlags": [f["text"] for f in (o.get("risk") or {}).get("flags", [])],
        "nFav": len(o["favourable"]), "nCon": len(o["contrary"]), "nMissing": len(o["missing"]),
        "nFavTotal": len(o["conditions"]["fav"]), "why": o["why"], "invalidate": o["invalidate"],
        "bond": o.get("bond"), "bondRole": o.get("role") if o["kind"] == "bond" else None,
        "products": [{"isin": p["isin"], "ticker": (p["tickers"] or [p["isin"]])[0], "ter": p["ter"], "hedged": p["hedged"],
                      "distribution": p["distribution"]} for p in o["products"]["products"]],
        "trends": o["trends"], "completeness": o["completeness"]}


def page(result):
    """What the page receives: the overview, the list (compact rows) and the selection (full rows)."""
    out = {k: v for k, v in result.items() if k != "rows"}
    out["rows"] = [summary_row(o) for o in result["rows"]]
    out["selectedRows"] = [o for o in result["rows"] if o["key"] in result["selected"]]
    return out


def detail(result, key):
    return next((o for o in result["rows"] if o["key"] == key), None)


# ---------------------------------------------------------------- command line

def main(argv=None):
    import sys
    import etf_prices
    argv = argv if argv is not None else sys.argv[1:]
    mode = argv[0] if argv and argv[0] in MODES else "lungo"
    prices = etf_prices.load()
    if not prices:
        print("prezzi non in cache: `.venv/bin/python etf_prices.py aggiorna`")
        return
    version = next((a for a in argv if a in VERSIONS), VERSION)
    r = scan(cat.load(), prices, mode, now=datetime.now(), version=version)
    print(f"{r['modeLabel']} — seduta {r['session']}, prezzi del {r['pricesFetched']}, modello {r['version']}")
    for s, n in r["overview"]["counts"].items():
        if n:
            print(f"  {s}: {n}")
    print("Da approfondire:", ", ".join(r["selected"]) or "nessuna")
    for o in r["rows"]:
        m = o.get("measures") or {}
        rel6 = ((m.get("rel") or {}).get("6m"))
        print(f"  {o['familyLabel'][:22]:22} {o['label'][:34]:34} {o['state']:32} rischio {(o.get('risk') or {}).get('level', ''):9} "
              f"rel6m {fmt(rel6)} trend {m.get('trend') or '-'}")


if __name__ == "__main__":
    main()
