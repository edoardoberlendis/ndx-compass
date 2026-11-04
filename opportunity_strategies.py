"""Ricerca controllata di nuove strategie Trading (phase 4B). An experimental area of the validation lab, separate from
the scanner (nothing here changes opportunity_scanner.py, its rules, thresholds or rankings) and from the phase 3 study.

    python opportunity_strategies.py ipotesi        the registered hypotheses, rules and evaluation criteria
    python opportunity_strategies.py config         configuration, version and fingerprint (and whether it is registered)
    python opportunity_strategies.py registra       registers the configuration BEFORE any study (once per version)
    python opportunity_strategies.py run            runs the three studies on the frozen data (refused if not registered
                                                    or if the configuration changed after the registration)
    python opportunity_strategies.py show [A|B|C]   prints the saved reports
    python opportunity_strategies.py registro       the experiment log

Three families, ONE primary configuration each, written in docs/ricerca_strategie_4b.md before the results:
    A  momentum relative to the sector (12-1 months, top third of its sector, today's ICB sectors: exploratory)
    B  short-term pullback inside a structural uptrend (born from the phase 3 data: never an independent validation)
    C  market context from QQQ (bullish / recovery / bearish) as a modifier of A, B and the old 4/5 rule

The final period (from 9 August 2024) is never read: prices are cut the day before it starts. Results carry the label
"Studio esplorativo con survivorship bias" (today's Nasdaq-100 applied to the past). No buy or sell signal anywhere.
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

import market_data_quality as mq
import opportunity_scanner as o
import opportunity_validation as v

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "data", "strategie")
PRICES_DIR = os.path.join(ROOT, "data", "validazione")
PROTOCOL = os.path.join(ROOT, "docs", "ricerca_strategie_4b.md")
ET = v.ET
BENCH = "QQQ"

VERSION = "S1"
LABEL = v.LABEL
SNAPSHOT = "prezzi_2026-11-04_0804.pkl"                       # the frozen prices of phase 3 (never downloaded again)
SNAPSHOT_SHA = "37af042f05f979062c9c9d97262d876c6fdfd83af52db64bff6a4248790c9ef6"
SECTORS_FILE = "settori_icb_2026-11-03.json"                  # frozen copy of today's ICB industries (Wikipedia)
REVIEWS_VERSION = "R1"                                        # data_quality_reviews.json used for the verified errors
FINAL_START = "2024-08-09"                                    # sealed: prices from this day on are never loaded
SEGMENTS = {"sviluppo": ("2016-01-11", "2022-05-13"), "verifica": ("2022-06-15", "2024-07-10")}   # as phase 3
HORIZONS = v.HORIZONS
MAIN_H = 21                                                   # the horizon that decides the state; 5 and 10 are shown
HIST = 252                                                    # sessions of own history to be eligible (all families)

A = {"formation": [252, 21], "peers_min": 5, "top": 2 / 3, "bottom": 1 / 3, "order": "forza nel settore più alta"}
B = {"trend": "chiusura sopra la media 200 e media 50 sopra la media 200 (regola B2 / I6)",
     "pullback": "differenza con QQQ a 21 sedute (la misura di T1) nel 20% più debole dei titoli del giorno",
     "pullback_pct": 0.20, "no_pullback_pct": 0.40, "invalid_dd": -25.0, "confirmation": "nessuna (primaria)",
     "volatility": "nessun filtro (primaria)", "order": "rendimento a 126 sedute più alto"}
C = {"ma": 200, "recovery": 63, "episode_gap": 21, "min_episodes_dev": 5, "min_episodes_ver": 2,
     "filter": "nessun nuovo ingresso nei giorni «ribassista»"}
SECONDARY = {
    "A_6_1": "formazione 6-1 mesi (126 → 21 sedute) invece di 12-1",
    "B_CONF": "con conferma: chiusura sopra quella del giorno prima",
    "B_ATR": f"con filtro di volatilità: ATR 14 fino al {o.ATR_HIGH:g}% del prezzo",
    "WINSOR": "rendimenti futuri limitati al 1° e al 99° percentile (casi estremi)",
    "SUSPECT": "esclusi i giorni con un dato sospetto non verificato da 252 sedute prima a 21 sedute dopo",
    "C_2": "contesto con due soli stati: QQQ sopra o sotto la media 200",
}
EVIDENCE = {"T_MIN": v.T_MIN, "T_STRICT": 3.0, "VERIFY_T": 1.0, "MIN_SIGNALS": v.MIN_SIGNALS, "MIN_INDEP": v.MIN_INDEP,
            "MIN_INDEP_VERIFY": v.MIN_INDEP_VERIFY, "RAND_TAIL": v.RAND_TAIL, "RANDOM_RUNS": v.RANDOM_RUNS, "SEED": v.SEED}
STATES = ["Ipotesi non verificabile", "Evidenza insufficiente", "Nessun vantaggio rilevato",
          "Risultato esplorativo promettente", "Candidato a verifica prospettica"]
EXPOSURE = ("Il periodo finale non è cieco del tutto: nella Fase 4A sono stati guardati alcuni prezzi del 2026 (MRNA il 19 "
            "agosto, HONA dal 15 al 26 giugno, HON il 29 giugno) e i movimenti estremi del 2024-2026 elencati dal "
            "rapporto di qualità, solo per controllare gli errori di prezzo; nessun rendimento di strategia del periodo "
            "finale è stato calcolato. In questa fase i prezzi dal 9 agosto 2024 non vengono nemmeno caricati.")
NAMES = {
    "A_TOP": "A · terzo più forte del proprio settore (12-1)", "A_BOT": "A · terzo più debole del proprio settore",
    "A_NDX": "A · terzo più forte dell'universo (momentum 12-1, già bocciato nella Fase 11)",
    "A_INC": "A · forte nel settore ma non nel terzo più forte dell'universo",
    "A_6_1": "A · secondaria: terzo più forte del settore (6-1)",
    "B": "B · ritracciamento nel trend", "B_TNP": "B · trend senza ritracciamento", "B_PNT": "B · ritracciamento senza trend",
    "B_CONF": "B · secondaria: con conferma", "B_ATR": "B · secondaria: con ATR fino al 4%",
    "C4": "Regola attuale 4 su 5",
}


def config():
    return {"version": VERSION, "label": LABEL, "snapshot": SNAPSHOT, "snapshotSha": SNAPSHOT_SHA, "sectors": SECTORS_FILE,
            "reviews": REVIEWS_VERSION, "finalStart": FINAL_START, "segments": SEGMENTS, "horizons": list(HORIZONS),
            "mainHorizon": MAIN_H, "history": HIST, "A": A, "B": B, "C": C, "secondary": SECONDARY, "evidence": EVIDENCE,
            "simulation": v.SIM, "states": STATES, "scannerModel": o.MODEL_VERSION}


def config_hash(cfg=None):
    return hashlib.sha256(json.dumps(cfg or config(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- frozen data, cut before the final period

def freeze_sectors(out_dir=None):
    """Copies today's ICB industries (cache/constituents.json, Wikipedia) into a dated file: the classification used by
    family A, never rewritten."""
    out_dir = out_dir or OUT_DIR
    path = os.path.join(out_dir, SECTORS_FILE)
    if os.path.exists(path):
        return path
    src = os.path.join(ROOT, "cache", "constituents.json")
    rows = json.load(open(src))
    rows = rows["data"] if isinstance(rows, dict) else rows
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"source": "Wikipedia, NASDAQ-100 companies, colonna ICB Industry (cache del 3 novembre 2026)",
                   "frozen": datetime.now(ET).isoformat(timespec="seconds"), "sha256Source": _sha(src),
                   "note": "classificazione di OGGI: non è uno storico, i settori possono essere cambiati negli anni",
                   "sectors": {r["ticker"]: r["sector"] for r in rows}}, f, ensure_ascii=False, indent=1)
    return path


def load_frozen(prices_dir=None, out_dir=None, reviews=None):
    """Prices of phase 3 (checked by hash), verified errors removed (a copy), cut before the final period, sectors."""
    path = os.path.join(prices_dir or PRICES_DIR, SNAPSHOT)
    if _sha(path) != SNAPSHOT_SHA:
        raise SystemExit("il file dei prezzi non è quello congelato della Fase 3: studio non eseguito")
    s = pd.read_pickle(path)
    rev = reviews if reviews is not None else mq.load_reviews()
    if rev.get("version") != REVIEWS_VERSION:
        raise SystemExit(f"revisione dei dati {rev.get('version')} diversa da quella registrata ({REVIEWS_VERSION})")
    data, removed = mq.apply_verified(s["data"], rev)
    sectors = json.load(open(os.path.join(out_dir or OUT_DIR, SECTORS_FILE)))["sectors"]
    return cut_final(data), s["tickers"], sectors, {"removed": removed, "raw": cut_final(s["data"]), "saved": s["saved"]}


def cut_final(data):
    """Every series without the rows from FINAL_START on (the sealed period is never in memory)."""
    end = pd.Timestamp(FINAL_START)
    out = {}
    for t, df in data.items():
        df = v._naive(df)
        out[t] = df[df.index < end]
    return out


# ---------------------------------------------------------------- indicators (each day uses only data up to that day)

def indicators(P, sectors, formation=None):
    C, Q = P["close"], P["bench"]
    nb = C.notna().cumsum().where(C.notna())
    elig = nb >= HIST + 1
    a, b = formation or A["formation"]
    mom = (C.shift(b) / C.shift(a) - 1) * 100                       # from a sessions ago to b sessions ago
    sec = pd.Series({t: sectors.get(t) for t in C.columns})
    srm = pd.DataFrame(np.nan, index=C.index, columns=C.columns)
    pct_sec = srm.copy()
    peers = pd.DataFrame(0, index=C.index, columns=C.columns)
    for s_name in sorted(x for x in sec.dropna().unique()):
        cols = list(sec[sec == s_name].index)
        m = mom[cols].where(elig[cols])
        n = m.notna().sum(axis=1)
        med = m.median(axis=1)
        ok = n >= A["peers_min"]
        srm[cols] = m.sub(med, axis=0).where(ok, axis=0)
        pct_sec[cols] = m.rank(axis=1, pct=True).where(ok, axis=0)
        peers[cols] = np.repeat(n.to_numpy()[:, None], len(cols), axis=1)
    pct_uni = mom.where(elig).rank(axis=1, pct=True)
    s50, s200 = C.rolling(50).mean(), C.rolling(200).mean()
    trend = (C > s200) & (s50 > s200)
    rs21 = ((C / C.shift(21) - 1) * 100).sub((Q / Q.shift(21) - 1) * 100, axis=0)
    pct_rs21 = rs21.where(elig).rank(axis=1, pct=True)
    dd252 = (C / C.rolling(252).max() - 1) * 100
    ret126 = (C / C.shift(126) - 1) * 100
    H, L = P["high"], P["low"]
    pc = C.shift()
    tr = pd.DataFrame(np.fmax(np.fmax((H - L).to_numpy(), (H - pc).abs().to_numpy()), (L - pc).abs().to_numpy()),
                      index=C.index, columns=C.columns)
    atr = tr.rolling(14).mean() / C * 100
    return {"elig": elig, "mom": mom, "srm": srm, "pctSector": pct_sec, "peers": peers, "pctUniverse": pct_uni,
            "trend": trend, "rs21": rs21, "pctRs21": pct_rs21, "dd252": dd252, "ret126": ret126, "atr": atr,
            "up": C > C.shift(), "sector": sec}


def regimes(Q):
    """Per day, from QQQ only: 'rialzista', 'recupero' (above the 200 average after being below it in the previous
    63 sessions), 'ribassista' (below the 200 average); 'n.d.' before 200 sessions."""
    ma = Q.rolling(C["ma"]).mean()
    above = Q > ma
    was_below = (~above & ma.notna()).astype(float).shift(1).rolling(C["recovery"], min_periods=1).max() > 0
    out = np.where(ma.isna(), "n.d.", np.where(~above, "ribassista", np.where(was_below, "recupero", "rialzista")))
    return pd.Series(out, index=Q.index)


def episodes(rows, flags, gap=None):
    """Number of separate spells of the flagged days among rows (spells closer than `gap` sessions are one)."""
    gap = gap or C["episode_gap"]
    idx = [r for r, f in zip(rows, flags) if f]
    if not idx:
        return 0
    n, last = 1, idx[0]
    for r in idx[1:]:
        if r - last > gap:
            n += 1
        last = r
    return n


def masks_a(I):
    pct, pu = I["pctSector"], I["pctUniverse"]
    top, bot = pct > A["top"], pct <= A["bottom"]
    ndx = pu > A["top"]
    return {"A_TOP": top, "A_BOT": bot, "A_NDX": ndx & pct.notna(), "A_INC": top & ~ndx}


def masks_b(I, extra=True):
    e = I["elig"]
    ok = I["dd252"] > B["invalid_dd"]
    pb = I["pctRs21"] <= B["pullback_pct"]
    m = {"B": I["trend"] & pb & ok & e, "B_TNP": I["trend"] & (I["pctRs21"] > B["no_pullback_pct"]) & ok & e,
         "B_PNT": ~I["trend"] & pb & e}
    if extra:
        m["B_CONF"] = m["B"] & I["up"]
        m["B_ATR"] = m["B"] & (I["atr"] <= o.ATR_HIGH)
    return m


def old_rule(P, elig):
    F = v.features(P)
    return (F["count"] >= o.TRADING_MIN) & elig


# ---------------------------------------------------------------- the lab of phase 3, with fixed periods and given masks

class StratLab(v.Lab):
    """Phase 3 statistics (daily means, Newey-West, independent periods, random control) on fixed date periods."""

    def __init__(self, P, valid, masks):
        self._given = masks
        super().__init__(P, {"valid": valid}, open_final=False)

    def _segments(self, purge):
        out = {}
        for name, (a, b) in SEGMENTS.items():
            out[name] = np.asarray((self.cal >= pd.Timestamp(a)) & (self.cal <= pd.Timestamp(b)))
        out["tutto"] = out["sviluppo"] | out["verifica"]
        return out

    def _masks(self):
        return {k: np.asarray(m, dtype=bool) & self.E for k, m in self._given.items()}


def _daily(E, S, f):
    def mean(M):
        k = M.sum(axis=1)
        s = np.where(M, f, 0.0).sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(k > 0, s / np.maximum(k, 1), np.nan)
    sel = S & E
    return mean(sel), mean(E & ~S), mean(E), sel.sum(axis=1)


def diff_stats(rows, d, h):
    d = np.asarray(d, dtype=float)
    keep = ~np.isnan(d)
    rows, d = np.asarray(rows)[keep], d[keep]
    n_ind, m_ind, t_ind = v.independent(rows, d, h)
    return {"days": int(len(d)), "mean": v._r(d.mean()) if len(d) else None, "t": v._r(v.nw_t(d, h), 2),
            "indep": n_ind, "indepMean": v._r(m_ind)}


def pair(lab, a, b, h, seg, f=None, keep=None):
    """Same-day difference between the mean of group a and the mean of group b (or the others when b is None)."""
    f = lab.fwd[h] if f is None else f
    E = lab.E & (keep if keep is not None else True)
    ma, mn, _, ka = _daily(E, lab.masks[a] & E, f)
    mb = mn if b is None else _daily(E, lab.masks[b] & E, f)[0]
    rows = np.nonzero(seg & (ka > 0))[0]
    return diff_stats(rows, (ma - mb)[rows], h)


def judge_block(lab, key, rand):
    out = {}
    for h in HORIZONS:
        res = {s: lab.summary(key, h, lab.segments[s], rand[key][h][s] if rand else None) for s in ("sviluppo", "verifica", "tutto")}
        res["verdict"] = v.verdict(res["sviluppo"], res["verifica"])
        out[str(h)] = res
    return out


def winsor(lab, h):
    vals = lab.fwd[h][lab.E & lab.segments["tutto"][:, None]]
    lo, hi = np.percentile(vals, [1, 99]) if len(vals) else (np.nan, np.nan)
    return np.clip(lab.fwd[h], lo, hi)


def suspect_keep(lab, issues):
    """False for the stock-days whose formation (252 sessions before) or forward window (21 after) contains a date with
    a suspicious, unverified anomaly."""
    keep = np.ones(lab.E.shape, dtype=bool)
    col = {t: i for i, t in enumerate(lab.P["names"])}
    pos = {d: i for i, d in enumerate(lab.cal)}
    n = 0
    for x in issues:
        if x["status"] != "sospetto" or x["ticker"] not in col or not x.get("from"):
            continue
        i = pos.get(pd.Timestamp(x["from"]))
        if i is None:
            continue
        keep[max(0, i - MAIN_H): i + HIST + 1, col[x["ticker"]]] = False
        n += 1
    return keep, n


def sector_excess(lab, I, key, h, seg):
    """Mean over days of (selected stock - equal mean of its eligible sector peers), same forward window."""
    f = lab.fwd[h]
    sec = I["sector"]
    sf = np.full(f.shape, np.nan)
    for s_name in sec.dropna().unique():
        cols = [lab.P["names"].index(t) for t in sec[sec == s_name].index if t in lab.P["names"]]
        sub = np.where(lab.E[:, cols], f[:, cols], np.nan)
        k = (~np.isnan(sub)).sum(axis=1)
        m = np.where(k > 0, np.nansum(sub, axis=1) / np.maximum(k, 1), np.nan)
        sf[:, cols] = m[:, None]
    ex = f - sf
    S = lab.masks[key]
    ms, _, _, k = _daily(lab.E, S, np.nan_to_num(ex))
    rows = np.nonzero(seg & (k > 0))[0]
    return diff_stats(rows, ms[rows], h)


def regime_split(lab, reg, key, h=MAIN_H):
    d_sel, d_non, _, k = _daily(lab.E, lab.masks[key], lab.fwd[h])
    d = d_sel - d_non
    out = {}
    for seg_name in ("sviluppo", "verifica", "tutto"):
        seg = lab.segments[seg_name] & (k > 0)
        rows = np.nonzero(seg)[0]
        part = {}
        for r in ("rialzista", "recupero", "ribassista"):
            flags = reg[rows] == r
            st = diff_stats(rows[flags], d[rows][flags], h)
            st["episodes"] = episodes(rows, flags)
            st["qqq"] = v._r(np.nanmean(lab.qf[h][rows][flags])) if flags.any() else None
            part[r] = st
        bear = reg[rows] == "ribassista"
        st = diff_stats(rows, np.where(bear, d[rows], np.nan), h)
        other = diff_stats(rows, np.where(~bear, d[rows], np.nan), h)
        part["differenzaRibassistaAltri"] = (v._r(st["mean"] - other["mean"]) if st["mean"] is not None
                                             and other["mean"] is not None else None)
        out[seg_name] = part
    return out


# ---------------------------------------------------------------- simulation (same engine as phase 3)

def simulate_block(P, lab, key, order, reg=None, costs=None):
    seg = lab.segments["tutto"]
    known = lab.P["close"].notna().to_numpy() & np.asarray(lab.F["valid"])     # only what was known that day
    base = np.asarray(lab._given[key], dtype=bool) & known
    out = {}
    for name, mask in (("senza filtro", base), ("con filtro di contesto", None)):
        if mask is None:
            if reg is None:
                continue
            mask = base & ((reg != "ribassista") & (reg != "n.d."))[:, None]
        sc = []
        for cost in (costs or v.SIM["costs"]):
            r = v.simulate(P, None, mask, seg, cost, order=order)
            if r is None:
                return {"available": False, "reason": "nessun giorno di segnale"}
            tr = np.asarray([t["ret"] for t in r["trades"]])
            gains, losses = tr[tr > 0].sum(), -tr[tr < 0].sum()
            years = max(len(r["equity"]) - 1, 1) / 252
            pos_days = np.zeros(len(r["days"]))
            dix = {d: i for i, d in enumerate(r["days"])}
            for t in r["trades"]:
                a, b = dix.get(pd.Timestamp(t["entry"])), dix.get(pd.Timestamp(t["exit"]))
                if a is not None and b is not None:
                    pos_days[a:b] += 1
            sc.append({"cost": cost, **v.perf(r["days"], r["equity"]), "trades": int(len(tr)),
                       "profitFactor": v._r(gains / losses, 2) if losses > 0 else None,
                       "winRate": v._r((tr > 0).mean() * 100, 1) if len(tr) else None,
                       "exposure": v._r(pos_days.mean() / v.SIM["max_pos"] * 100, 1),
                       "turnover": v._r(r["traded"] / np.mean(r["equity"]) / years, 1)})
            days = r["days"]
        out[name] = sc
    q = P["bench"].reindex(days)
    out["qqq"] = v.perf(days, q.to_numpy())
    if reg is not None:
        rr = pd.Series(reg, index=lab.cal).reindex(days).shift(1)
        inv = (rr != "ribassista") & rr.notna() & (rr != "n.d.")
        eq = np.cumprod(1 + (q.pct_change().fillna(0) * inv).to_numpy())
        out["qqqConFiltro"] = {**v.perf(days, eq), "exposure": v._r(inv.mean() * 100, 1),
                               "note": "QQQ tenuto solo dopo un giorno non ribassista (chiusura→chiusura)"}
    rng = np.random.default_rng(v.SEED)
    cnt = base.sum(axis=1)
    totals = []
    for _ in range(v.SIM["random_runs"]):
        u = rng.random(known.shape)
        u[~known] = 2.0
        rank = u.argsort(axis=1).argsort(axis=1)
        rr2 = v.simulate(P, None, rank < cnt[:, None], seg, v.SIM["costs"][1], order=-rank.astype(float))
        totals.append(v.perf(rr2["days"], rr2["equity"])["total"])
    out["random"] = {"runs": v.SIM["random_runs"], "cost": v.SIM["costs"][1], "median": v._r(np.median(totals), 2),
                     "p10": v._r(np.percentile(totals, 10), 2), "p90": v._r(np.percentile(totals, 90), 2)}
    out["available"] = True
    return out


# ---------------------------------------------------------------- states, fixed before the results

def state_of(block, sens, sim, verifiable=True):
    """block: judge_block of the primary group; sens: list of secondary t/means at MAIN_H; sim: simulate_block."""
    if not verifiable:
        return STATES[0], "dati necessari non disponibili"
    main = block[str(MAIN_H)]
    vd = main["verdict"]
    if vd == "Evidenza insufficiente" or "verifica non possibile" in vd:
        return STATES[1], vd
    if not vd.startswith("Differenza migliore credibile"):
        return STATES[2], vd
    dev, ver = main["sviluppo"], main["verifica"]
    strict = abs(dev.get("tOthers") or 0) >= EVIDENCE["T_STRICT"] and (ver.get("tOthers") or 0) >= EVIDENCE["VERIFY_T"]
    sens_ok = all(s.get("mean") is not None and s["mean"] > 0 and (s.get("t") or 0) >= EVIDENCE["T_MIN"] for s in sens)
    sc = next((x for x in (sim or {}).get("senza filtro", []) if x["cost"] == v.SIM["costs"][1]), None)
    sim_ok = bool(sc and sim.get("random") and sc["total"] is not None and sc["total"] > sim["random"]["median"])
    if strict and sens_ok and sim_ok:
        return STATES[4], "criteri rigorosi soddisfatti (|t| ≥ 3, verifica, sensibilità, simulazione sopra il caso)"
    why = [w for w, ok in (("|t| sotto 3 o verifica debole", strict), ("sensibilità non concordi", sens_ok),
                           ("simulazione non sopra le scelte a caso", sim_ok)) if not ok]
    return STATES[3], "; ".join(why)


# ---------------------------------------------------------------- the three studies

def run_all(data, tickers, sectors, treatment, random_runs=None, with_sim=True, check_n=100, reviews=None):
    t0 = time.time()
    rr = v.RANDOM_RUNS if random_runs is None else random_runs
    P = v.prepare(data, tickers)
    if len(P["cal"]) and P["cal"][-1] >= pd.Timestamp(FINAL_START):
        raise RuntimeError("dati del periodo finale presenti: studio fermato")
    I = indicators(P, sectors)
    F = v.features(P)
    checked, bad = v.check_against_scanner(P, F, n=check_n)
    if bad:
        raise RuntimeError("le condizioni T1-T5 non coincidono con lo scanner: " + "; ".join(bad[:3]))
    c4 = (F["count"] >= o.TRADING_MIN) & I["elig"]
    reg = regimes(P["bench"]).to_numpy()
    quality = mq.check(data, tickers, reviews=reviews if reviews is not None else mq.load_reviews())
    reports = {}

    # A: sector-relative momentum, only stocks whose sector has enough eligible peers
    validA = I["elig"] & I["pctSector"].notna()
    mA = {**masks_a(I), "C4": c4}
    I61 = indicators(P, sectors, formation=[126, 21])
    mA["A_6_1"] = (I61["pctSector"] > A["top"]) & validA
    labA = StratLab(P, validA, mA)
    randA = labA.random_control(rr) if rr else None
    keepA, nsA = suspect_keep(labA, quality["issues"])
    blockA = {k: judge_block(labA, k, randA) for k in ("A_TOP", "A_BOT", "A_NDX", "A_INC", "A_6_1", "C4")}
    pairsA = {f"{a} − {b or 'altri'}": {str(h): {s: pair(labA, a, b, h, labA.segments[s]) for s in ("sviluppo", "verifica", "tutto")}
                                       for h in HORIZONS}
              for a, b in (("A_TOP", "A_BOT"), ("A_TOP", "A_NDX"), ("A_INC", None), ("A_TOP", "C4"))}
    secA = {s: sector_excess(labA, I, "A_TOP", MAIN_H, labA.segments[s]) for s in ("sviluppo", "verifica", "tutto")}
    sensA = {"A_6_1": pair(labA, "A_6_1", None, MAIN_H, labA.segments["tutto"]),
             "WINSOR": pair(labA, "A_TOP", None, MAIN_H, labA.segments["tutto"], f=winsor(labA, MAIN_H)),
             "SUSPECT": pair(labA, "A_TOP", None, MAIN_H, labA.segments["tutto"], keep=keepA)}
    simA = simulate_block(P, labA, "A_TOP", I["srm"].to_numpy(), reg) if with_sim else None
    inc = pairsA["A_TOP − A_NDX"][str(MAIN_H)]
    inc_ok = (inc["sviluppo"]["mean"] or 0) > 0 and (inc["sviluppo"]["t"] or 0) >= EVIDENCE["T_MIN"] and (inc["verifica"]["mean"] or 0) > 0
    stA = state_of(blockA["A_TOP"], list(sensA.values()), simA)
    secs = I["sector"].dropna()
    reports["A"] = {
        "family": "A", "title": "Momentum relativo al settore", "groups": blockA, "pairs": pairsA, "vsSector": secA,
        "sensitivity": sensA, "suspectExcluded": nsA, "simulation": simA, "state": stA[0], "stateWhy": stA[1],
        "additionalInformation": {"credible": bool(inc_ok), "rule": "A_TOP meglio di A_NDX nello sviluppo con t ≥ 2 e "
                                  "stesso segno nella verifica (fissata prima dei risultati)"},
        "sectorsUsed": {s: int((secs == s).sum()) for s in sorted(secs.unique())},
        "sectorsTooSmall": sorted({s for s in secs.unique() if (secs == s).sum() < A["peers_min"]}),
        "observations": int(labA.E.sum()),
        "dataLimit": "Settori ICB di oggi (Wikipedia, 3 novembre 2026) applicati a tutti gli anni: nessuno storico delle "
                     "classificazioni è disponibile (cambi noti nel 2018-2019 e nel 2023). Studio solo esplorativo.",
    }

    # B: pullback in the trend (data-generated hypothesis)
    validB = I["elig"]
    mB = {**masks_b(I), "C4": c4}
    labB = StratLab(P, validB, mB)
    randB = labB.random_control(rr) if rr else None
    keepB, nsB = suspect_keep(labB, quality["issues"])
    blockB = {k: judge_block(labB, k, randB) for k in ("B", "B_TNP", "B_PNT", "B_CONF", "B_ATR", "C4")}
    pairsB = {f"{a} − {b or 'altri'}": {str(h): {s: pair(labB, a, b, h, labB.segments[s]) for s in ("sviluppo", "verifica", "tutto")}
                                       for h in HORIZONS}
              for a, b in (("B", "B_TNP"), ("B", "B_PNT"), ("B", "C4"))}
    sensB = {"B_CONF": pair(labB, "B_CONF", None, MAIN_H, labB.segments["tutto"]),
             "B_ATR": pair(labB, "B_ATR", None, MAIN_H, labB.segments["tutto"]),
             "WINSOR": pair(labB, "B", None, MAIN_H, labB.segments["tutto"], f=winsor(labB, MAIN_H)),
             "SUSPECT": pair(labB, "B", None, MAIN_H, labB.segments["tutto"], keep=keepB)}
    simB = simulate_block(P, labB, "B", I["ret126"].to_numpy(), reg) if with_sim else None
    stB = state_of(blockB["B"], list(sensB.values()), simB)
    reports["B"] = {
        "family": "B", "title": "Ritracciamento nel trend", "groups": blockB, "pairs": pairsB, "sensitivity": sensB,
        "suspectExcluded": nsB, "simulation": simB, "state": stB[0], "stateWhy": stB[1], "observations": int(labB.E.sum()),
        "dataGenerated": True,
        "dataLimit": "Ipotesi nata dall'effetto inverso di T1 visto nella Fase 3 sugli stessi periodi: sviluppo e verifica "
                     "NON sono una prova indipendente. La conferma richiede il diario prospettico o dati nuovi.",
    }

    # C: market context as a modifier of A, B and the old rule
    c_out = {}
    reg2 = np.where(reg == "n.d.", "n.d.", np.where(reg == "ribassista", "ribassista", "rialzista"))   # C_2
    c_two = {}
    for name, lab, key in (("A_TOP", labA, "A_TOP"), ("B", labB, "B"), ("C4", labB, "C4")):
        c_out[name] = regime_split(lab, reg, key)
        c_two[name] = {seg: {r: part[r] for r in ("rialzista", "ribassista")}
                       for seg, part in regime_split(lab, reg2, key).items()}
    rows_all = np.nonzero(labB.segments["tutto"])[0]
    ep = {s: {r: episodes(np.nonzero(labB.segments[s])[0], reg[labB.segments[s]] == r) for r in ("rialzista", "recupero", "ribassista")}
          for s in ("sviluppo", "verifica")}
    enough = ep["sviluppo"]["ribassista"] >= C["min_episodes_dev"] and ep["verifica"]["ribassista"] >= C["min_episodes_ver"]
    simC = {"A_TOP": simA, "B": simB,
            "C4": simulate_block(P, labB, "C4", (F["count"].to_numpy() * 1e4 + np.nan_to_num(F["rs21"].to_numpy(), nan=-1e3)), reg)
            if with_sim else None}
    improved = []
    for k, s in simC.items():
        if not s or not s.get("available"):
            continue
        a = next(x for x in s["senza filtro"] if x["cost"] == v.SIM["costs"][1])
        b = next(x for x in s["con filtro di contesto"] if x["cost"] == v.SIM["costs"][1])
        beyond = (b["total"] - a["total"]) - (s["qqqConFiltro"]["total"] - s["qqq"]["total"])
        better = (b["riskAdjusted"] or 0) > (a["riskAdjusted"] or 0)
        improved.append({"strategy": k, "netWithout": a["total"], "netWith": b["total"], "ddWithout": a["maxDrawdown"],
                         "ddWith": b["maxDrawdown"], "raWithout": a["riskAdjusted"], "raWith": b["riskAdjusted"],
                         "exposureWithout": a["exposure"], "exposureWith": b["exposure"], "tradesWithout": a["trades"],
                         "tradesWith": b["trades"], "missedTrades": a["trades"] - b["trades"],
                         "qqq": s["qqq"]["total"], "qqqFiltered": s["qqqConFiltro"]["total"],
                         "qqqExposure": s["qqqConFiltro"]["exposure"], "beyondTiming": v._r(beyond, 2),
                         "riskAdjustedBetter": bool(better)})
    better_ra = {x["strategy"] for x in improved if x["riskAdjustedBetter"]}
    # the filter is useful for a strategy only if its advantage is credibly WORSE on bearish days (development t <= -2,
    # negative in verification) and the filter improves its return/risk in the simulation (fixed before the results)
    credible_c = [k for k, x in c_out.items()
                  if (x["sviluppo"]["ribassista"]["t"] or 0) <= -EVIDENCE["T_MIN"]
                  and (x["verifica"]["ribassista"]["mean"] or 0) < 0 and (k in better_ra or not with_sim)]
    if not enough:
        stC = (STATES[1], f"episodi ribassisti: {ep['sviluppo']['ribassista']} nello sviluppo e {ep['verifica']['ribassista']} "
                          f"nella verifica (servono {C['min_episodes_dev']} e {C['min_episodes_ver']})")
    elif not credible_c:
        stC = (STATES[2], "nessuna strategia va credibilmente peggio nei giorni ribassisti con un filtro che migliori "
                          "rendimento/rischio")
    else:
        stC = (STATES[3], "vantaggio peggiore nei giorni ribassisti e filtro utile per " + ", ".join(credible_c))
    reports["C"] = {"family": "C", "title": "Contesto di mercato", "regimeSplit": c_out, "episodes": ep, "filter": improved,
                    "state": stC[0], "stateWhy": stC[1],
                    "regimeDays": {r: int((reg[rows_all] == r).sum()) for r in ("rialzista", "recupero", "ribassista")},
                    "secondaryTwoStates": c_two,
                    "breadth": "non usata: con i soli 101 titoli di oggi sarebbe distorta dal survivorship bias",
                    "simulation": simC}

    removed = treatment.get("removed", [])
    common = {"label": LABEL, "version": VERSION, "configHash": config_hash(), "config": config(),
              "createdAt": datetime.now(ET).isoformat(timespec="seconds"), "exposure": EXPOSURE,
              "period": {"prices": [P["cal"][0].date().isoformat(), P["cal"][-1].date().isoformat()],
                         "segments": {k: list(x) for k, x in SEGMENTS.items()}, "finalStart": FINAL_START, "finalRead": False},
              "universe": {"tickers": len(tickers), "used": len(P["names"]), "excluded": P["excluded"]},
              "dataTreatment": {"reviews": REVIEWS_VERSION, "removed": removed,
                                "excludedObservations": treatment.get("excludedObservations")},
              "quality": {"counts": quality["counts"], "suspectUsed": True}, "scannerCheck": {"checked": checked},
              "seconds": round(time.time() - t0, 1)}
    for k in reports:
        reports[k] = {**common, **reports[k]}
    return reports


def excluded_observations(raw, data, tickers):
    """Eligible stock-days lost because of the verified errors (same rules, raw vs treated copy)."""
    def count(d):
        P = v.prepare(d, tickers)
        C = P["close"]
        nb = C.notna().cumsum().where(C.notna())
        return int((nb >= HIST + 1).to_numpy().sum())
    return count(raw) - count(data)


# ---------------------------------------------------------------- files

def registered(out_dir=None):
    try:
        with open(os.path.join(out_dir or OUT_DIR, "preregistrazione.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def register(out_dir=None):
    out_dir = out_dir or OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "preregistrazione.json")
    if os.path.exists(path):
        raise SystemExit("configurazione già registrata: una registrazione non si riscrive (cambiare VERSION per una nuova)")
    rec = {"version": VERSION, "configHash": config_hash(), "registeredAt": datetime.now(ET).isoformat(timespec="seconds"),
           "protocol": os.path.relpath(PROTOCOL, ROOT), "protocolSha": _sha(PROTOCOL) if os.path.exists(PROTOCOL) else None,
           "config": config(), "exposure": EXPOSURE}
    with open(path, "w") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return rec


def save_reports(reports, out_dir=None):
    out_dir = out_dir or OUT_DIR
    run_dir = os.path.join(out_dir, VERSION, datetime.now(ET).strftime("%Y-%m-%d_%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    files = {}
    for k, r in reports.items():
        p = os.path.join(run_dir, f"strategia_{k}.json")
        with open(p, "w") as f:
            json.dump(v.finite(r), f, ensure_ascii=False, indent=1)
        files[k] = os.path.relpath(p, out_dir)
    entry = {"at": next(iter(reports.values()))["createdAt"], "version": VERSION, "configHash": config_hash(),
             "files": files, "finalRead": False, "states": {k: r["state"] for k, r in reports.items()}}
    with open(os.path.join(out_dir, "registro.jsonl"), "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "riepilogo.json"), "w") as f:
        json.dump(v.finite(panel_summary(reports, files)), f, ensure_ascii=False)
    return run_dir


def panel_summary(reports, files=None):
    def line(r, key):
        g = r["groups"][key][str(MAIN_H)]
        return {"dev": g["sviluppo"].get("vsOthers"), "devT": g["sviluppo"].get("tOthers"),
                "ver": g["verifica"].get("vsOthers"), "verT": g["verifica"].get("tOthers"), "n": g["tutto"].get("n")}
    def vs(r, key):
        x = r["pairs"][key][str(MAIN_H)]["tutto"]
        return {"mean": x["mean"], "t": x["t"]}
    a, b, c = reports["A"], reports["B"], reports["C"]
    ep = c["episodes"]
    return {"label": LABEL, "version": VERSION, "configHash": a["configHash"], "createdAt": a["createdAt"],
            "horizon": MAIN_H, "finalStart": FINAL_START, "files": files,
            "rows": [{"id": "A", "name": "A · forza rispetto al settore (12-1 mesi)", "state": a["state"], "why": a["stateWhy"],
                      **line(a, "A_TOP"), "vsOld": vs(a, "A_TOP − C4"), "key": {"label": "contro il momentum 12-1 semplice",
                                                                                **vs(a, "A_TOP − A_NDX")},
                      "note": "settori di oggi applicati al passato: solo esplorativo"},
                     {"id": "B", "name": "B · ritracciamento in trend positivo", "state": b["state"], "why": b["stateWhy"],
                      **line(b, "B"), "vsOld": vs(b, "B − C4"), "key": {"label": "contro il ritracciamento senza trend",
                                                                        **vs(b, "B − B_PNT")},
                      "note": "ipotesi nata dai dati della Fase 3: non è una prova indipendente"},
                     {"id": "C", "name": "C · contesto di mercato (QQQ)", "state": c["state"], "why": c["stateWhy"],
                      "episodes": {"dev": ep["sviluppo"]["ribassista"], "ver": ep["verifica"]["ribassista"],
                                   "need": [C["min_episodes_dev"], C["min_episodes_ver"]]},
                      "filter": [{k: x[k] for k in ("strategy", "netWithout", "netWith", "raWithout", "raWith",
                                                    "exposureWithout", "exposureWith", "beyondTiming")} for x in c["filter"]],
                      "note": "modifica A, B e la regola 4/5; breadth non usata (survivorship)"}]}


def read_summary(out_dir=None):
    try:
        with open(os.path.join(out_dir or OUT_DIR, "riepilogo.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def latest_reports(out_dir=None):
    runs = sorted(glob.glob(os.path.join(out_dir or OUT_DIR, VERSION, "*")))
    if not runs:
        return None
    return {os.path.basename(p)[10]: json.load(open(p)) for p in sorted(glob.glob(os.path.join(runs[-1], "strategia_*.json")))}


# ---------------------------------------------------------------- terminal

_f = v._f


def _g(x):
    return f"{_f(x.get('vsOthers'))} (t {_f(x.get('tOthers'), 1)}, n {x.get('n', 0)}, indip. {x.get('indep', 0)})"


def print_report(r):
    print(f"\n=== {r['family']} · {r['title'].upper()} · {r['label']} ===")
    print(f"Laboratorio {r['version']} · configurazione {r['configHash']} · creato {r['createdAt']}")
    print(f"Prezzi {r['period']['prices'][0]} → {r['period']['prices'][1]} (periodo finale dal {r['period']['finalStart']} "
          "non caricato) · sviluppo " + " → ".join(r["period"]["segments"]["sviluppo"]) + " · verifica " +
          " → ".join(r["period"]["segments"]["verifica"]))
    t = r["dataTreatment"]
    print(f"Dati: revisione {t['reviews']}, esclusi " + (", ".join(f"{x['ticker']} {x['from']}→{x['to']} ({x['rows']} sedute)"
          for x in t["removed"]) or "nessun tratto") + f"; osservazioni idonee perse per errori verificati: "
          f"{t.get('excludedObservations')}")
    print("Esposizione del periodo finale:", r["exposure"])
    if r.get("dataLimit"):
        print("LIMITE:", r["dataLimit"])
    print(f"\nSTATO: {r['state']} — {r['stateWhy']}")
    if "groups" in r:
        print(f"\nRendimento dopo h sedute, differenza media di ogni giorno contro i titoli NON scelti (punti); sviluppo → verifica")
        for k, g in r["groups"].items():
            for h in map(str, HORIZONS):
                x = g[h]
                a = x["tutto"]
                print(f"  {NAMES.get(k, k)[:62]:62s} h{h:>2s}: {_g(x['sviluppo'])} → {_g(x['verifica'])} · "
                      f"vs QQQ {_f(a.get('vsQqq'))} · vs universo {_f(a.get('vsUniverse'))} · media {_f(a.get('mean'))} "
                      f"mediana {_f(a.get('median'))} · %>0 {_f(a.get('positive'), 0, False)} · p10/p90 {_f(a.get('p10'))}/"
                      f"{_f(a.get('p90'))} · caso% {_f(a.get('randomPct'), 0, False)} · {x['verdict']}")
        print("\nConfronti diretti (stesso giorno, punti, t Newey-West):")
        for name, by_h in r["pairs"].items():
            print(f"  {name}: " + " · ".join(f"h{h} svil. {_f(x['sviluppo']['mean'])} (t {_f(x['sviluppo']['t'], 1)}) → "
                                               f"verif. {_f(x['verifica']['mean'])} (t {_f(x['verifica']['t'], 1)})"
                                               for h, x in by_h.items()))
        if r.get("vsSector"):
            print("  A_TOP rispetto alla media del proprio settore (21 sedute): " + " · ".join(
                f"{s} {_f(x['mean'])} (t {_f(x['t'], 1)})" for s, x in r["vsSector"].items()))
        print("Sensibilità secondarie (21 sedute, tutto, contro i non scelti): " + " · ".join(
            f"{k} {_f(x['mean'])} (t {_f(x['t'], 1)}, {x['days']} giorni)" for k, x in r["sensitivity"].items()))
        main = r["groups"]["A_TOP" if r["family"] == "A" else "B"][str(MAIN_H)]["tutto"]
        print("Per anno (contro i non scelti):", ", ".join(f"{y} {_f(x['vsOthers'])}" for y, x in main.get("years", {}).items()))
        if r.get("additionalInformation"):
            print("Informazione aggiuntiva rispetto al Nasdaq:", "sì" if r["additionalInformation"]["credible"] else "no",
                  "—", r["additionalInformation"]["rule"])
    if r["family"] == "C":
        print("Giorni per contesto (sviluppo+verifica):", r["regimeDays"], "· episodi:", r["episodes"])
        for k, x in r["regimeSplit"].items():
            print(f"  {k}: " + " · ".join(f"{seg}: " + ", ".join(f"{reg} {_f(y['mean'])} (t {_f(y['t'], 1)}, {y['days']} g, "
                                                                f"{y['episodes']} ep.)" for reg, y in part.items()
                                                                if isinstance(y, dict))
                                          for seg, part in x.items()))
        for x in r["filter"]:
            print(f"  filtro su {x['strategy']} (costi 0,10%): netto {_f(x['netWithout'])}% → {_f(x['netWith'])}%, perdita "
                  f"massima {_f(x['ddWithout'])}% → {_f(x['ddWith'])}%, rendimento/rischio {_f(x['raWithout'])} → "
                  f"{_f(x['raWith'])}, esposizione {_f(x['exposureWithout'], 0, False)}% → {_f(x['exposureWith'], 0, False)}%, "
                  f"operazioni perse {x['missedTrades']}; QQQ {_f(x['qqq'])}% → con lo stesso filtro {_f(x['qqqFiltered'])}% "
                  f"(investito {_f(x['qqqExposure'], 0, False)}% dei giorni); effetto del filtro oltre il semplice stare "
                  f"fuori dal mercato {_f(x['beyondTiming'])} punti")
        print("Secondaria C_2 (solo sopra/sotto la media 200, 21 sedute, tutto): " + " · ".join(
            f"{k} sopra {_f(x['tutto']['rialzista']['mean'])} (t {_f(x['tutto']['rialzista']['t'], 1)}), sotto "
            f"{_f(x['tutto']['ribassista']['mean'])} (t {_f(x['tutto']['ribassista']['t'], 1)})"
            for k, x in r["secondaryTwoStates"].items()))
        print("Breadth:", r["breadth"])
    s = r.get("simulation")
    if r["family"] != "C" and s and s.get("available"):
        print("\nSimulazione sperimentale (non una prova di redditività; ingresso all'apertura dopo, 21 sedute, max 10 titoli):")
        for name in ("senza filtro", "con filtro di contesto"):
            for x in s.get(name, []):
                print(f"  {name}, costi {_f(x['cost'], 2, False)}%: totale {_f(x['total'])}%, annuo {_f(x['annual'])}%, perdita "
                      f"massima {_f(x['maxDrawdown'])}%, rendimento/rischio {_f(x['riskAdjusted'])}, esposizione "
                      f"{_f(x['exposure'], 0, False)}%, operazioni {x['trades']}")
        print(f"  QQQ {_f(s['qqq']['total'])}% · scelte a caso (stesse regole, costi 0,10%) mediana {_f(s['random']['median'])}% "
              f"({_f(s['random']['p10'])}% … {_f(s['random']['p90'])}%)")
    print(f"\n{r['label']}: nessuna conclusione è una validazione; nessun segnale di acquisto o vendita.\n")


def print_hypotheses():
    if os.path.exists(PROTOCOL):
        print(open(PROTOCOL).read())
    else:
        print(json.dumps(config(), ensure_ascii=False, indent=1))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "show"
    if cmd == "ipotesi":
        print_hypotheses()
    elif cmd == "config":
        reg = registered()
        print(json.dumps(config(), ensure_ascii=False, indent=1))
        print(f"\nVersione {VERSION} · impronta {config_hash()} · registrata: "
              + (f"sì ({reg['registeredAt']}, impronta {reg['configHash']}{'' if reg['configHash'] == config_hash() else ' — DIVERSA!'})"
                 if reg else "no"))
    elif cmd == "registra":
        freeze_sectors()
        rec = register()
        print(f"Registrata la configurazione {rec['version']} ({rec['configHash']}) il {rec['registeredAt']}; "
              f"protocollo {rec['protocol']} ({(rec['protocolSha'] or '')[:12]})")
    elif cmd == "run":
        reg = registered()
        if not reg:
            raise SystemExit("prima registra la configurazione: python opportunity_strategies.py registra")
        if reg["configHash"] != config_hash():
            raise SystemExit("la configurazione è cambiata dopo la registrazione: studio non eseguito")
        data, tickers, sectors, tr = load_frozen()
        tr["excludedObservations"] = excluded_observations(tr["raw"], data, tickers)
        reports = run_all(data, tickers, sectors, tr)
        d = save_reports(reports)
        for r in reports.values():
            print_report(r)
        print("Report salvati in", os.path.relpath(d, ROOT))
    elif cmd == "show":
        reps = latest_reports()
        if not reps:
            print("Nessuno studio salvato.")
            return
        for k, r in reps.items():
            if len(argv) < 3 or argv[2].upper() == k:
                print_report(r)
    elif cmd == "registro":
        p = os.path.join(OUT_DIR, "registro.jsonl")
        reg = registered()
        if reg:
            print(f"Registrazione: {reg['version']} {reg['configHash']} il {reg['registeredAt']}")
        if os.path.exists(p):
            for line in open(p):
                print(line.rstrip())
        else:
            print("Registro vuoto.")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
