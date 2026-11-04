"""Laboratorio di validazione (phase O3): an exploratory historical study of the five Trading conditions (T1-T5) of
opportunity_scanner.py. It never changes the scanner, the ranking or the opportunity diary.

    python opportunity_validation.py config                 configuration, thresholds and limits (nothing is computed)
    python opportunity_validation.py run [--scarica | --dashboard] [--apri-finale]
                                                            runs the study and saves a report in data/validazione/
    python opportunity_validation.py show [file]            prints the latest (or the given) saved report
    python opportunity_validation.py investimento           what the data allow for the Investment ranking (no backtest)
    python opportunity_validation.py rielabora [report]     phase 4A: reproduces a saved study, then reruns it without the
                                                            verified data errors (data_quality_reviews.json), saved apart

What can be tested on the past, and what cannot:
  - T1-T5 use only daily prices and volumes: they can be recomputed for every past day with the data of that day.
  - The Investment conditions I1-I5 use TODAY's fundamentals, estimates, consensus and valuation: applied to past dates
    they would be look-ahead. They are never backtested here; they are measured only going forward by the diary.
  - The universe is TODAY's Nasdaq-100: there is no history of its composition. Stocks that left the index (often the
    losers) are missing and stocks that joined later are present before they joined. Every result carries the label
    LABEL ("Studio esplorativo con survivorship bias") and is never a definitive validation.

Two layers kept apart:
  D1 signal statistics: close of the signal day -> close h sessions later (not tradable: the signal is known only
     after the close), compared on the SAME days with QQQ, the universe, the stocks not selected and a random selection.
  D2 simulation: entry at the next session's open, cost scenarios, a capital, a maximum number of positions and
     overlapping trades handled as a portfolio (returns of overlapping trades are never summed).

Heavy work runs only from the command line (never inside Flask); the dashboard can only read the saved summary.
Reports and the experiment log live in data/validazione/ (outside Git), separate from the opportunity diary.
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import market_calendar
import opportunity_scanner as o

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "data", "validazione")
LOG = os.path.join(OUT_DIR, "esperimenti.jsonl")
DIARY = os.path.join(ROOT, "data", "opportunita.sqlite3")   # read only, and only if it already exists
ET = o.ET
BENCH = "QQQ"

VERSION = "V1"                      # changes with any change of method, split, thresholds of evidence or simulation rules
LABEL = "Studio esplorativo con survivorship bias"
START = "2015-10-01"                # first day downloaded with --scarica (as backtest.py --patterns)
HORIZONS = (5, 10, 21)              # sessions, as the Trading horizons of the diary
MAIN_H = 21
SPLIT = (0.6, 0.2, 0.2)             # development, verification, final (sealed) share of the decision days, in time order
# evidence rules, fixed BEFORE any result was seen (4 November 2026)
MIN_SIGNALS = 100                   # signals in the development period
MIN_INDEP = 20                      # non-overlapping periods of h sessions in the development period
MIN_INDEP_VERIFY = 10               # ... in the verification period
T_MIN = 2.0                         # |t| with Newey-West errors (lag = h) on the daily differences
RAND_TAIL = 2.5                     # the selection must be outside 95% of the random selections (2.5% per side)
RANDOM_RUNS = 200
SEED = 20261104
JUMP = 40.0                         # a daily move above 40% is listed as a possible unadjusted corporate action
REGIME_MA = 200                     # market regime: QQQ above or below its 200-session average on the signal day
SIM = {"capital": 10000.0, "max_pos": 10, "hold": 21, "costs": [0.0, 0.10, 0.25], "random_runs": 20}

PRICE_CONVENTION = ("Prezzi giornalieri Yahoo Finance rettificati per frazionamenti e dividendi (auto_adjust), uguali per i "
                    "titoli e per QQQ: i rendimenti sono quindi vicini ai rendimenti totali, per entrambi. Nessun rendimento "
                    "di solo prezzo viene mescolato. Un prezzo mancante esclude il caso (mai riempito con valori inventati); "
                    "i titoli con giorni di borsa diversi da QQQ sono esclusi e elencati.")
LIMITS = [
    LABEL + ": l'universo è il Nasdaq-100 di oggi. Mancano i titoli usciti dall'indice (spesso perché scesi) e ci sono "
    "titoli entrati dopo, presenti anche prima di entrarci (spesso perché saliti). I rendimenti assoluti, quelli contro QQQ "
    "e quelli contro l'universo sono quindi spinti verso l'alto; il confronto tra titoli scelti e non scelti dello stesso "
    "giorno ne risente meno, ma non ne è libero.",
    "Le condizioni Investimento (fondamentali, stime, consenso, valutazione) non sono testate sul passato: i dati di oggi "
    "applicati a date passate sarebbero informazione futura. Si misurano solo in avanti con il diario delle opportunità.",
    "Gli avvisi della classifica (trimestrale vicina, notizie, stime tagliate, pattern bocciati) non hanno storico: nella "
    "simulazione l'ordine è solo condizioni soddisfatte e poi forza contro QQQ a 1 mese.",
    "Le statistiche dei segnali vanno dalla chiusura del giorno del segnale alla chiusura h sedute dopo: non sono un "
    "rendimento ottenibile, perché il segnale si conosce solo dopo la chiusura. La simulazione entra all'apertura dopo.",
    "I segnali dello stesso giorno e di giorni vicini non sono indipendenti: le prove usano la media di ogni giorno, errori "
    "di Newey-West con ritardo pari all'orizzonte e il conteggio dei periodi che non si sovrappongono.",
    "Molti confronti insieme: su circa 40 giudizi, 1 o 2 possono sembrare «credibili» per caso.",
    "Costi della simulazione: scenari ipotetici (commissione e scarto di prezzo insieme, per ogni lato), non le tariffe "
    "reali di Fineco. Nessun cambio euro/dollaro, nessuna tassa, liquidità senza interessi.",
    "Volumi di Yahoo: corretti per i frazionamenti ma non verificati con altre fonti.",
    "Nessun risultato promuove da solo una condizione o cambia le soglie dello scanner: servono una decisione esplicita "
    "dell'utente e poi la conferma del diario, giorno per giorno, in avanti.",
]
NOT_TESTABLE = [
    "I1-I5 (ricavi, margine, stime, consenso, valutazione): solo dati di oggi, nessuno storico affidabile",
    "Avvisi su notizie, trimestrali e stime: nessuno storico",
    "Composizione storica del Nasdaq-100: non disponibile",
]

CONDS = ["T1", "T2", "T3", "T4", "T5"]
GROUP_TEXT = {
    "T1": "T1 più forte di QQQ a 1 mese", "T2": "T2 più forte di QQQ a 3 mesi", "T3": "T3 sopra le medie 20 e 50",
    "T4": "T4 media 20 in salita", "T5": "T5 volumi 20/60 almeno 1",
    "C3": "almeno 3 condizioni su 5", "C4": "almeno 4 su 5 (regola attuale)", "C5": "tutte e 5",
    "G1": "forte contro QQQ e in salita", "G2": "forte contro QQQ ma in calo", "G3": "debole contro QQQ",
    "G4": "trend in salita senza forza contro QQQ",
    "A_LO": "4 su 5 con ATR fino al 4%", "A_HI": "4 su 5 con ATR oltre il 4%",
}
GROUP_DEF = {
    "G1": "T1 e T2 soddisfatte, rendimento a 21 e a 63 sedute sopra 0",
    "G2": "T1 e T2 soddisfatte, rendimento a 21 o a 63 sedute sotto 0 (scende meno del mercato)",
    "G3": "differenza con QQQ a 21 e a 63 sedute non sopra 0",
    "G4": "T3 e T4 soddisfatte, ma non T1 e T2 insieme",
    "A_LO": "almeno 4 su 5 e ATR 14 fino al 4% del prezzo (soglia sperimentale invariata)",
    "A_HI": "almeno 4 su 5 e ATR 14 oltre il 4% del prezzo",
}
JUDGED = ["T1", "T2", "T3", "T4", "T5", "C3", "C4", "C5", "G1", "G2", "G3", "G4"]   # A_LO / A_HI: exploratory only

COLS = ("Open", "High", "Low", "Close", "Volume")


def config():
    """Everything that defines an experiment (also hashed into the log)."""
    return {
        "version": VERSION, "label": LABEL, "scannerModel": o.MODEL_VERSION,
        "conditions": [{"id": i, "name": n, "rule": r} for i, n, r in o.TRADING],
        "scannerParams": {"MIN_SESSIONS": o.MIN_SESSIONS, "SLOPE_DAYS": o.SLOPE_DAYS, "VOL_SHORT": o.VOL_SHORT,
                          "VOL_LONG": o.VOL_LONG, "VOL_MIN_DAYS": o.VOL_MIN_DAYS, "TRADING_MIN": o.TRADING_MIN,
                          "ATR_HIGH": o.ATR_HIGH},
        "groups": {k: GROUP_TEXT[k] for k in GROUP_TEXT}, "groupRules": GROUP_DEF,
        "horizons": list(HORIZONS), "split": list(SPLIT), "purge": max(HORIZONS),
        "evidence": {"MIN_SIGNALS": MIN_SIGNALS, "MIN_INDEP": MIN_INDEP, "MIN_INDEP_VERIFY": MIN_INDEP_VERIFY,
                     "T_MIN": T_MIN, "RAND_TAIL": RAND_TAIL, "RANDOM_RUNS": RANDOM_RUNS, "SEED": SEED},
        "regime": f"QQQ sopra o sotto la sua media a {REGIME_MA} sedute nel giorno del segnale",
        "simulation": SIM, "priceConvention": PRICE_CONVENTION,
    }


def config_hash(extra=None):
    raw = json.dumps({**config(), **(extra or {})}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------- data: one table per field on the QQQ calendar

def _naive(df):
    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    df = df[~df.index.duplicated(keep="last")]
    df.index = df.index.normalize()
    return df.sort_index()


def prepare(data, tickers, last_day=None):
    """data: {ticker: DataFrame Open/High/Low/Close/Volume}, with BENCH. Returns the wide tables on the QQQ calendar (only
    days up to last_day: closed sessions), the excluded stocks with the reason and the data-quality notes."""
    if BENCH not in data:
        raise ValueError("QQQ mancante: senza benchmark lo studio non si fa")
    b = _naive(data[BENCH]).dropna(subset=["Close"])
    if last_day is not None:
        b = b[b.index <= pd.Timestamp(last_day)]
    cal = b.index
    frames, excluded = {}, {}
    for t in tickers:
        df = data.get(t)
        if df is None or df.empty or "Close" not in df:
            excluded[t] = "nessun prezzo"
            continue
        df = _naive(df).dropna(subset=["Close"])
        df = df[df.index <= cal[-1]]
        if len(df) == 0:
            excluded[t] = "nessun prezzo"
            continue
        if not df.index.equals(cal[cal >= df.index[0]]):
            excluded[t] = "giorni di borsa diversi da QQQ (sedute mancanti o in più)"
            continue
        frames[t] = df
    names = sorted(frames)
    wide = {c: pd.DataFrame({t: frames[t][c] if c in frames[t] else np.nan for t in names}, index=cal).astype(float)
            for c in COLS}
    C = wide["Close"]
    jumps = []
    move = (C / C.shift() - 1) * 100
    for t in names:
        big = move[t][move[t].abs() > JUMP]
        jumps += [{"ticker": t, "date": d.date().isoformat(), "move": round(float(v), 1)} for d, v in big.items()]
    quality = {
        "jumps": jumps,
        "missingOpen": int((wide["Open"].isna() & C.notna()).to_numpy().sum()),
        "zeroVolume": int(((wide["Volume"] <= 0) & C.notna()).to_numpy().sum()),
        "lateListing": sorted(t for t in names if frames[t].index[0] > cal[0]),
    }
    return {"cal": cal, "names": names, **{k.lower(): v for k, v in wide.items()}, "bench": b["Close"].astype(float),
            "excluded": excluded, "quality": quality}


# ---------------------------------------------------------------- the five conditions, every stock and every day

def features(P):
    """T1-T5 for every stock and day, with the same formulas as opportunity_scanner.tech / trading_conditions (checked by
    check_against_scanner). Each value at day d uses only the rows up to d (rolling windows and backward shifts)."""
    C, H, L, V, Q = P["close"], P["high"], P["low"], P["volume"], P["bench"]
    nb = C.notna().cumsum().where(C.notna())                  # sessions of the stock up to the day (no gaps after listing)
    valid = (nb >= o.MIN_SESSIONS)
    ret = {k: (C / C.shift(k) - 1) * 100 for k in (21, 63)}
    q = {k: (Q / Q.shift(k) - 1) * 100 for k in (21, 63)}
    rs = {k: ret[k].sub(q[k], axis=0) for k in (21, 63)}
    s20, s50 = C.rolling(20).mean(), C.rolling(50).mean()
    vs20, vs50 = (C / s20 - 1) * 100, (C / s50 - 1) * 100
    slope = (s20 / s20.shift(o.SLOPE_DAYS) - 1) * 100
    m60 = V.rolling(o.VOL_LONG, min_periods=1).mean()
    m20 = V.rolling(o.VOL_SHORT, min_periods=1).mean()
    pos = (V > 0).astype(float).where(C.notna()).rolling(o.VOL_LONG, min_periods=1).sum()
    vol_ok = (nb >= o.VOL_LONG) & (pos >= o.VOL_MIN_DAYS) & (m60 > 0)
    vol = (m20 / m60).where(vol_ok)
    pc = C.shift()
    tr = pd.DataFrame(np.fmax(np.fmax((H - L).to_numpy(), (H - pc).abs().to_numpy()), (L - pc).abs().to_numpy()),
                      index=C.index, columns=C.columns)                # like the scanner: the largest available range
    atr = tr.rolling(14).mean() / C * 100

    def state(ok, known):
        """1 met, 0 not met, NaN not judgeable (never counted as met)."""
        return ok.astype(float).where(known & valid)
    st = {
        "T1": state(rs[21] > 0, rs[21].notna()),
        "T2": state(rs[63] > 0, rs[63].notna()),
        "T3": state((vs20 > 0) & (vs50 > 0), vs20.notna() & vs50.notna()),
        "T4": state(slope > 0, slope.notna()),
        "T5": state(vol >= 1, vol.notna()),
    }
    count = sum((st[c] == 1).astype(int) for c in CONDS).where(valid)
    return {"state": st, "count": count, "valid": valid, "ret21": ret[21], "ret63": ret[63], "rs21": rs[21],
            "rs63": rs[63], "atr": atr.where(valid), "vol": vol}


def check_against_scanner(P, F, n=200, seed=SEED):
    """Recomputes random (day, stock) cases with opportunity_scanner on the data cut at that day. Returns (checked, diffs)."""
    rng = np.random.default_rng(seed)
    v = F["valid"].to_numpy()
    rows, cols = np.nonzero(v)
    if not len(rows):
        return 0, []
    pick = rng.choice(len(rows), size=min(n, len(rows)), replace=False)
    bad = []
    for k in pick:
        d, t = P["cal"][rows[k]], P["names"][cols[k]]
        df = pd.DataFrame({c: P[c.lower()][t] for c in COLS}).dropna(subset=["Close"])
        df = df[df.index <= d]
        conds = o.trading_conditions(o.tech(df, P["bench"][P["bench"].index <= d]))
        for c in conds:
            mine = F["state"][c["id"]].at[d, t]
            want = {"ok": 1.0, "ko": 0.0}.get(c["state"], np.nan)
            if not (mine == want or (np.isnan(mine) and np.isnan(want))):
                bad.append(f"{t} {d.date()} {c['id']}: laboratorio {mine}, scanner {c['state']}")
    return len(pick), bad


# ---------------------------------------------------------------- statistics on the same days, aggregated by date

def nw_t(x, lag):
    """t of the mean with Newey-West (Bartlett) errors: overlapping forward windows make consecutive days dependent."""
    x = np.asarray([v for v in x if v is not None and not np.isnan(v)], dtype=float)
    n = len(x)
    if n < 3:
        return None
    e = x - x.mean()
    var = e @ e / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    if var <= 0:
        return None
    return float(x.mean() / math.sqrt(var / n))


def independent(rows, x, h):
    """Non-overlapping subsample: days at least h sessions apart. Returns (n, mean, simple t)."""
    keep, last = [], -10 ** 9
    for r, v in zip(rows, x):
        if not np.isnan(v) and r >= last + h:
            keep.append(v)
            last = r
    n = len(keep)
    if n < 2:
        return n, (float(keep[0]) if keep else None), None
    a = np.asarray(keep)
    sd = a.std(ddof=1)
    return n, float(a.mean()), (float(a.mean() / (sd / math.sqrt(n))) if sd > 0 else None)


def _r(x, d=3):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(float(x), d)


class Lab:
    """All the arrays of one study (days x stocks), built once."""

    def __init__(self, P, F, open_final=False):
        self.P, self.F = P, F
        self.cal = P["cal"]
        C = P["close"].to_numpy()
        Q = P["bench"].to_numpy()
        self.fwd, self.qf = {}, {}
        for h in HORIZONS:
            f = np.full(C.shape, np.nan)
            f[:-h] = (C[h:] / C[:-h] - 1) * 100
            self.fwd[h] = f
            qf = np.full(len(Q), np.nan)
            qf[:-h] = (Q[h:] / Q[:-h] - 1) * 100
            self.qf[h] = qf
        hmax = max(HORIZONS)
        # an observation: the conditions are judgeable that day and the full future of every horizon is known
        self.E = F["valid"].to_numpy() & ~np.isnan(self.fwd[hmax])
        qma = P["bench"].rolling(REGIME_MA).mean().to_numpy()
        self.regime = np.where(np.isnan(qma), np.nan, (Q > qma).astype(float))
        self.years = self.cal.year.to_numpy()
        self.open_final = open_final
        self.segments = self._segments(hmax)
        self.masks = self._masks()
        self.mu = {h: self._mean(self.E, h) for h in HORIZONS}

    def _segments(self, purge):
        """Development / verification / final by time, on the days with observations. The last `purge` days of a segment
        are dropped: their forward windows would end inside the next one."""
        days = np.nonzero(self.E.any(axis=1))[0]
        n = len(days)
        a, b = int(n * SPLIT[0]), int(n * (SPLIT[0] + SPLIT[1]))
        parts = {"sviluppo": days[:a], "verifica": days[a:b], "finale": days[b:]}
        out, nxt = {}, {"sviluppo": "verifica", "verifica": "finale"}
        for name, rows in parts.items():
            m = np.zeros(len(self.cal), dtype=bool)
            m[rows] = True
            if name in nxt and len(parts[nxt[name]]):
                m[np.arange(len(self.cal)) + purge >= parts[nxt[name]][0]] = False
            out[name] = m
        out["tutto"] = out["sviluppo"] | out["verifica"] | (out["finale"] if self.open_final else False)
        return out

    def _masks(self):
        st = {c: self.F["state"][c].to_numpy() == 1 for c in CONDS}
        cnt = self.F["count"].to_numpy()
        r21, r63 = self.F["ret21"].to_numpy(), self.F["ret63"].to_numpy()
        rs21, rs63 = self.F["rs21"].to_numpy(), self.F["rs63"].to_numpy()
        atr = self.F["atr"].to_numpy()
        rs_pos = st["T1"] & st["T2"]
        with np.errstate(invalid="ignore"):
            m = {**st, "C3": cnt >= 3, "C4": cnt >= o.TRADING_MIN, "C5": cnt == 5,
                 "G1": rs_pos & (r21 > 0) & (r63 > 0),
                 "G2": rs_pos & ((r21 < 0) | (r63 < 0)),
                 "G3": (rs21 <= 0) & (rs63 <= 0),
                 "G4": st["T3"] & st["T4"] & ~rs_pos,
                 "A_LO": (cnt >= o.TRADING_MIN) & (atr <= o.ATR_HIGH),
                 "A_HI": (cnt >= o.TRADING_MIN) & (atr > o.ATR_HIGH)}
        return {k: v & self.E for k, v in m.items()}

    def _mean(self, S, h):
        k = S.sum(axis=1)
        s = np.where(S, self.fwd[h], 0.0).sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(k > 0, s / np.where(k > 0, k, 1), np.nan)

    def daily(self, key, h):
        """Per day: mean of the selected, of the others, of the universe, of QQQ and the number selected."""
        S = self.masks[key]
        return {"sel": self._mean(S, h), "non": self._mean(self.E & ~S, h), "uni": self.mu[h], "qqq": self.qf[h],
                "n": S.sum(axis=1)}

    def summary(self, key, h, seg, rand=None):
        S = self.masks[key] & seg[:, None]
        dl = self.daily(key, h)
        rows = np.nonzero(seg & (dl["n"] > 0))[0]
        vals = self.fwd[h][S]
        qx = (self.fwd[h] - self.qf[h][:, None])[S]
        n = int(S.sum())
        out = {"n": n, "days": int(len(rows)), "stocks": int(S.any(axis=0).sum())}
        if n == 0:
            return {**out, "verdict": "Evidenza insufficiente"}
        d_non = dl["sel"][rows] - dl["non"][rows]
        d_q = dl["sel"][rows] - dl["qqq"][rows]
        d_u = dl["sel"][rows] - dl["uni"][rows]
        ind_n, ind_mean, ind_t = independent(rows, d_non, h)
        years = {}
        for y in np.unique(self.years[rows]):
            v = d_non[self.years[rows] == y]
            v = v[~np.isnan(v)]
            if len(v):
                years[int(y)] = {"days": int(len(v)), "vsOthers": _r(v.mean())}
        regimes = {}
        for lab, val in (("QQQ sopra la media 200", 1.0), ("QQQ sotto la media 200", 0.0)):
            m = self.regime[rows] == val
            if m.any():
                regimes[lab] = {"days": int(m.sum()), "selected": _r(np.nanmean(dl["sel"][rows][m])),
                                "qqq": _r(np.nanmean(dl["qqq"][rows][m])), "vsOthers": _r(np.nanmean(d_non[m])),
                                "vsQqq": _r(np.nanmean(d_q[m]))}
        pct = np.percentile(vals, [10, 25, 50, 75, 90])
        out.update({
            "mean": _r(vals.mean()), "median": _r(np.median(vals)), "positive": _r((vals > 0).mean() * 100, 1),
            "std": _r(vals.std(ddof=1) if n > 1 else None), "p10": _r(pct[0]), "p25": _r(pct[1]), "p75": _r(pct[3]),
            "p90": _r(pct[4]), "aboveQqq": _r((qx > 0).mean() * 100, 1), "excessQqqMedian": _r(np.median(qx)),
            "vsQqq": _r(np.nanmean(d_q)), "vsUniverse": _r(np.nanmean(d_u)), "vsOthers": _r(np.nanmean(d_non)),
            "vsOthersStd": _r(np.nanstd(d_non, ddof=1) if np.sum(~np.isnan(d_non)) > 1 else None),
            "tOthers": _r(nw_t(d_non, h), 2), "tQqq": _r(nw_t(d_q, h), 2),
            "indep": ind_n, "indepMean": _r(ind_mean), "indepT": _r(ind_t, 2),
            "years": years, "yearsPositive": sum(1 for v in years.values() if (v["vsOthers"] or 0) > 0),
            "regimes": regimes,
        })
        if rand is not None:
            obs = float(np.nanmean(d_u))
            r = np.asarray(rand)
            r = r[~np.isnan(r)]
            if len(r):
                out["randomPct"] = _r((r < obs).mean() * 100 + (r == obs).mean() * 50, 1)
                out["randomMid"] = _r(np.median(r))
        return out

    def random_control(self, runs=RANDOM_RUNS, seed=SEED):
        """{key: {h: {segment: [mean over days of (random selection - universe)]}}}: each day the same number of stocks
        as the selection, drawn among the stocks observable that day (no future information)."""
        rng = np.random.default_rng(seed)
        out = {k: {h: {s: [] for s in self.segments} for h in HORIZONS} for k in self.masks}
        counts = {k: m.sum(axis=1) for k, m in self.masks.items()}
        fz = {h: np.where(self.E, self.fwd[h], 0.0) for h in HORIZONS}
        for _ in range(runs):
            u = rng.random(self.E.shape)
            u[~self.E] = 2.0
            rank = u.argsort(axis=1).argsort(axis=1)
            for k, cnt in counts.items():
                sel = rank < cnt[:, None]
                kk = np.where(cnt > 0, cnt, 1)
                for h in HORIZONS:
                    d = (fz[h] * sel).sum(axis=1) / kk - self.mu[h]
                    for s, seg in self.segments.items():
                        m = seg & (cnt > 0)
                        out[k][h][s].append(float(d[m].mean()) if m.any() else np.nan)
        return out


def verdict(dev, ver):
    """Fixed before the results. Never "validated": at most credible inside an exploratory study with survivorship bias."""
    if dev.get("n", 0) < MIN_SIGNALS or (dev.get("indep") or 0) < MIN_INDEP or dev.get("vsOthers") is None:
        return "Evidenza insufficiente"
    t, p = dev.get("tOthers"), dev.get("randomPct")
    strong = t is not None and abs(t) >= T_MIN and (p is None or p >= 100 - RAND_TAIL or p <= RAND_TAIL)
    if not strong:
        return "Differenza osservata, non credibile"
    side = "migliore" if dev["vsOthers"] > 0 else "peggiore"
    if not ver or ver.get("n", 0) < MIN_SIGNALS or (ver.get("indep") or 0) < MIN_INDEP_VERIFY or ver.get("vsOthers") is None:
        return f"Differenza {side} nello sviluppo, verifica non possibile (campione insufficiente)"
    if (ver["vsOthers"] > 0) == (dev["vsOthers"] > 0):
        return f"Differenza {side} credibile nello studio esplorativo (confermata nel periodo di verifica)"
    return f"Differenza {side} nello sviluppo, non confermata nel periodo di verifica"


# ---------------------------------------------------------------- redundancy between conditions

def redundancy(lab):
    """Phi correlation and P(Tj | Ti) over the observations where all five conditions are judgeable."""
    st = {c: lab.F["state"][c].to_numpy() for c in CONDS}
    all_known = lab.E & np.logical_and.reduce([~np.isnan(st[c]) for c in CONDS])
    x = {c: st[c][all_known] == 1 for c in CONDS}
    phi, cond = {}, {}
    for a in CONDS:
        phi[a], cond[a] = {}, {}
        for b in CONDS:
            xa, xb = x[a].astype(float), x[b].astype(float)
            sa, sb = xa.std(), xb.std()
            phi[a][b] = _r(((xa - xa.mean()) * (xb - xb.mean())).mean() / (sa * sb), 2) if sa > 0 and sb > 0 else None
            cond[a][b] = _r(x[b][x[a]].mean() * 100, 1) if x[a].any() else None
    share = {c: _r(x[c].mean() * 100, 1) if len(x[c]) else None for c in CONDS}
    missing = {c: int((lab.E & np.isnan(st[c])).sum()) for c in CONDS}
    return {"observations": int(all_known.sum()), "share": share, "phi": phi, "conditional": cond, "missing": missing}


def atr_buckets(lab, h=MAIN_H):
    """Exploratory: the universe split each day into ATR quintiles; mean (stock - universe) and spread per quintile."""
    atr = lab.F["atr"].to_numpy()
    seg = lab.segments["tutto"]
    E = lab.E & seg[:, None] & ~np.isnan(atr)
    pr = pd.DataFrame(np.where(E, atr, np.nan)).rank(axis=1, pct=True).to_numpy()
    ex = lab.fwd[h] - lab.mu[h][:, None]
    out = []
    for q in range(5):
        m = E & (pr > q / 5) & (pr <= (q + 1) / 5)
        if m.any():
            out.append({"quintile": q + 1, "n": int(m.sum()), "atrMedian": _r(np.median(atr[m]), 2),
                        "vsUniverse": _r(ex[m].mean()), "std": _r(lab.fwd[h][m].std())})
    return out


# ---------------------------------------------------------------- walk-forward of the choice between alternatives

def walk_forward(lab, keys, h=MAIN_H, fixed="C4"):
    """For every year: the alternative with the best past (vs others, days before the year minus the purge) is
    chosen, then measured in the year. Shows whether choosing by past results would have held."""
    allowed = lab.segments["tutto"]
    dl = {k: lab.daily(k, h) for k in keys + ([fixed] if fixed not in keys else [])}
    diff = {k: d["sel"] - d["non"] for k, d in dl.items()}
    years = sorted(set(lab.years[allowed]))
    rows = []
    for y in years[2:]:
        first = np.nonzero(lab.years == y)[0][0]
        train = allowed & (np.arange(len(lab.cal)) + max(HORIZONS) < first)
        test = allowed & (lab.years == y)
        past = {k: np.nanmean(diff[k][train]) if np.any(train & ~np.isnan(diff[k])) else np.nan for k in keys}
        past = {k: v for k, v in past.items() if not np.isnan(v)}
        if not past or not test.any():
            continue
        best = max(past, key=past.get)
        now = {k: np.nanmean(diff[k][test]) if np.any(test & ~np.isnan(diff[k])) else np.nan for k in keys}
        rows.append({"year": int(y), "chosen": best, "chosenPast": _r(past[best]), "chosenThen": _r(now.get(best)),
                     "fixed": fixed, "fixedThen": _r(np.nanmean(diff[fixed][test])),
                     "bestThen": max((k for k in now if not np.isnan(now[k])), key=lambda k: now[k], default=None)})
    held = [r for r in rows if r["chosenThen"] is not None]
    return {"keys": keys, "horizon": h, "rows": rows,
            "chosenPositive": sum(1 for r in held if r["chosenThen"] > 0), "years": len(held),
            "chosenWasBest": sum(1 for r in held if r["chosen"] == r["bestThen"])}


# ---------------------------------------------------------------- D2: tradable simulation (experimental)

def simulate(P, F, mask, segment, cost_pct, capital=SIM["capital"], max_pos=SIM["max_pos"], hold=SIM["hold"], order=None):
    """Signal at the close of day i -> buy at the open of day i+1; sale at the open of day i+1+hold. Equal slots of
    equity/max_pos, at most max_pos stocks, never the same stock twice; cost_pct per side (commission and slippage
    together). The portfolio is valued at each close: overlapping trades are never added up as returns.
    mask: days x stocks booleans (signals), segment: days allowed for signals. order: days x stocks score (higher first)."""
    C, O = P["close"].to_numpy(), P["open"].to_numpy()
    names, cal = P["names"], P["cal"]
    cfill = P["close"].ffill().to_numpy()
    cost = cost_pct / 100
    cash, pos, trades, equity, traded = capital, {}, [], [], 0.0
    sig_rows = np.nonzero(segment)[0]
    if not len(sig_rows):
        return None
    first, last = sig_rows[0], min(sig_rows[-1] + 1 + hold, len(cal) - 1)
    for j in range(first, last + 1):
        for t, p in list(pos.items()):                           # exits at the open
            if p["exit"] == j or j == last:
                px = O[j, p["col"]] if j < last or p["exit"] == j else C[j, p["col"]]
                if np.isnan(px):
                    px = cfill[j - 1, p["col"]]                  # missing open: previous close (documented)
                value = p["shares"] * px
                cash += value * (1 - cost)
                traded += value
                trades.append({"ticker": t, "signal": cal[p["sig"]].date().isoformat(),
                               "entry": cal[p["entry"]].date().isoformat(), "exit": cal[j].date().isoformat(),
                               "ret": (value * (1 - cost) / p["paid"] - 1) * 100})
                del pos[t]
        i = j - 1                                               # yesterday's signals, known after yesterday's close
        if j < last and i >= 0 and segment[i] and len(pos) < max_pos:
            cand = np.nonzero(mask[i])[0]
            if len(cand):
                score = order[i, cand] if order is not None else np.zeros(len(cand))
                cand = [c for _, c in sorted(zip(-np.nan_to_num(score, nan=-1e9), cand), key=lambda z: (z[0], names[z[1]]))]
                eq = cash + sum(p["shares"] * cfill[i, p["col"]] for p in pos.values())
                for c in cand:
                    t = names[c]
                    if len(pos) >= max_pos:
                        break
                    if t in pos or np.isnan(O[j, c]) or O[j, c] <= 0:
                        continue
                    amount = min(eq / max_pos, cash)
                    if amount < eq / max_pos * 0.5:
                        break
                    shares = amount / (O[j, c] * (1 + cost))
                    cash -= amount
                    traded += amount
                    pos[t] = {"col": c, "shares": shares, "paid": amount, "sig": i, "entry": j, "exit": j + hold}
        equity.append(cash + sum(p["shares"] * cfill[j, p["col"]] for p in pos.values()))
    return {"days": cal[first:last + 1], "equity": np.asarray(equity), "trades": trades, "traded": traded}


def perf(days, equity):
    eq = np.asarray(equity, dtype=float)
    ret = np.diff(eq) / eq[:-1]
    years = max(len(eq) - 1, 1) / 252
    peak = np.maximum.accumulate(eq)
    sd = ret.std(ddof=1) if len(ret) > 1 else 0
    return {"start": days[0].date().isoformat(), "end": days[-1].date().isoformat(), "total": _r((eq[-1] / eq[0] - 1) * 100, 2),
            "annual": _r(((eq[-1] / eq[0]) ** (1 / years) - 1) * 100, 2), "maxDrawdown": _r(((eq / peak) - 1).min() * 100, 2),
            "riskAdjusted": _r(ret.mean() / sd * math.sqrt(252), 2) if sd > 0 else None}


def sim_report(P, F, lab):
    seg = lab.segments["tutto"]
    known = F["valid"].to_numpy()                 # only what was known on the signal day (lab.E also needs the future)
    with np.errstate(invalid="ignore"):
        mask = (F["count"].to_numpy() >= o.TRADING_MIN) & known
    order = (F["count"].to_numpy() * 1e4 + np.nan_to_num(F["rs21"].to_numpy(), nan=-1e3))
    if P.get("open") is None or P["open"].isna().all().all():
        return {"available": False, "reason": "prezzi di apertura mancanti: solo il livello statistico"}
    out = {"available": True, "rule": GROUP_TEXT["C4"], "entry": "apertura della seduta dopo il segnale",
           "exit": f"apertura dopo {SIM['hold']} sedute", "capital": SIM["capital"], "maxPositions": SIM["max_pos"],
           "order": "più condizioni soddisfatte, poi differenza con QQQ a 1 mese più alta (avvisi non disponibili nel passato)",
           "costsNote": "costi ipotetici per lato (commissione e scarto di prezzo insieme), non le tariffe di Fineco",
           "scenarios": []}
    q = P["bench"]
    for cost in SIM["costs"]:
        r = simulate(P, F, mask, seg, cost, order=order)
        if r is None:
            return {"available": False, "reason": "nessun giorno di segnale nel periodo"}
        tr = np.asarray([t["ret"] for t in r["trades"]])
        gains, losses = tr[tr > 0].sum(), -tr[tr < 0].sum()
        years = max(len(r["equity"]) - 1, 1) / 252
        months = years * 12
        out["scenarios"].append({
            "cost": cost, **perf(r["days"], r["equity"]), "trades": int(len(tr)),
            "tradesPerMonth": _r(len(tr) / months, 1) if months else None,
            "profitFactor": _r(gains / losses, 2) if losses > 0 else None, "winRate": _r((tr > 0).mean() * 100, 1) if len(tr) else None,
            "turnover": _r(r["traded"] / np.mean(r["equity"]) / years, 1),
        })
        days = r["days"]
    qq = q.reindex(days).to_numpy()
    out["qqq"] = perf(days, qq)
    # control: the same rules on a random choice of the same number of stocks each day
    rng = np.random.default_rng(SEED)
    cnt = mask.sum(axis=1)
    totals = []
    for _ in range(SIM["random_runs"]):
        u = rng.random(known.shape)
        u[~known] = 2.0
        rank = u.argsort(axis=1).argsort(axis=1)
        rm = rank < cnt[:, None]
        rr = simulate(P, F, rm, seg, SIM["costs"][1], order=-rank.astype(float))   # random order too, never alphabetical
        totals.append(perf(rr["days"], rr["equity"])["total"])
    out["random"] = {"runs": SIM["random_runs"], "cost": SIM["costs"][1], "median": _r(np.median(totals), 2),
                     "p10": _r(np.percentile(totals, 10), 2), "p90": _r(np.percentile(totals, 90), 2),
                     "note": "stesse regole e stesso numero di titoli ogni giorno, scelti a caso tra quelli osservabili; "
                             "ordine casuale invece della forza contro QQQ"}
    return out


# ---------------------------------------------------------------- Investment: no backtest, only data availability

def invest_check(daily=None, now=None):
    """What the data allow for the Investment list: no historical Pagella. Reads the diary only if it exists, read-only."""
    now = now or datetime.now(ET)
    out = {"historicalTest": False,
           "why": "I1-I5 usano fondamentali, stime, consenso e valutazione di oggi: applicati al passato sarebbero informazione "
                  "futura. Nessuna Pagella retroattiva e nessun backtest dell'Investimento.",
           "conditions": [{"id": i, "name": n} for i, n, _ in o.INVEST], "model": o.MODEL_VERSION,
           "horizons": [63, 126], "status": "non validato"}
    if daily is not None and BENCH in daily:
        q = daily[BENCH].dropna(subset=["Close"])
        lens = [len(v.dropna(subset=["Close"])) for k, v in daily.items() if k != BENCH]
        out["dailyHistory"] = {"sessions": len(q), "from": q.index[0].date().isoformat(), "to": q.index[-1].date().isoformat(),
                               "stocksWith127": sum(1 for x in lens if x >= 127), "stocks": len(lens),
                               "note": "lo storico giornaliero della dashboard basta per misurare 63 e 126 sedute dopo ogni "
                                       "giorno salvato, finché il diario e l'aggiornamento serale continuano"}
    if not os.path.exists(DIARY):
        out["diary"] = {"exists": False, "sessions": 0,
                        "note": "diario non ancora avviato: nessuna registrazione forzata dal laboratorio"}
        out["firstResults"] = None
        return out
    con = sqlite3.connect(f"file:{DIARY}?mode=ro", uri=True)
    try:
        sessions = [r[0] for r in con.execute("SELECT DISTINCT session FROM runs ORDER BY session")]
        n_inv = con.execute("SELECT COUNT(*) FROM observations WHERE list='invest'").fetchone()[0]
        res = {h: con.execute("SELECT COUNT(*) FROM outcomes WHERE horizon=? AND status='ok'", (h,)).fetchone()[0]
               for h in (63, 126)}
    finally:
        con.close()
    out["diary"] = {"exists": True, "sessions": len(sessions), "first": sessions[0] if sessions else None,
                    "last": sessions[-1] if sessions else None, "investObservations": n_inv,
                    "results": {str(h): v for h, v in res.items()}}
    if sessions:
        d = date.fromisoformat(sessions[0])
        firsts = {}
        for h in (63, 126):
            x, k = d, 0
            while k < h:
                x = market_calendar.next_trading_day(x)
                k += 1
            firsts[str(h)] = x.isoformat()
        out["firstResults"] = firsts
    return out


# ---------------------------------------------------------------- the whole study

def study(data, tickers, last_day=None, open_final=False, source=None, random_runs=RANDOM_RUNS, check_n=200,
          with_sim=True, treatment=None):
    """Runs everything on prices already in memory and returns the report (a dict). No download, no file.
    treatment: what was done to the data before the study (phase 4A rechecks), saved in the report."""
    t0 = time.time()
    P = prepare(data, tickers, last_day)
    F = features(P)
    checked, bad = check_against_scanner(P, F, n=check_n)
    if bad:
        raise RuntimeError(f"{len(bad)} differenze con opportunity_scanner su {checked} controlli: " + "; ".join(bad[:5]))
    lab = Lab(P, F, open_final=open_final)
    rand = lab.random_control(random_runs) if random_runs else None
    segs = [s for s in ("sviluppo", "verifica", "finale", "tutto") if s != "finale" or open_final]
    groups = {}
    for k in lab.masks:
        groups[k] = {"name": GROUP_TEXT[k], "rule": GROUP_DEF.get(k), "judged": k in JUDGED, "h": {}}
        for h in HORIZONS:
            res = {s: lab.summary(k, h, lab.segments[s], rand[k][h][s] if rand else None) for s in segs}
            if k in JUDGED:
                res["verdict"] = verdict(res["sviluppo"], res["verifica"])
            groups[k]["h"][str(h)] = res
    seg_info = {}
    for s, m in lab.segments.items():
        rows = np.nonzero(m)[0]
        sealed = s == "finale" and not open_final
        seg_info[s] = {"from": lab.cal[rows[0]].date().isoformat() if len(rows) else None,
                       "to": lab.cal[rows[-1]].date().isoformat() if len(rows) else None, "days": int(len(rows)),
                       "sealed": sealed}
    obs_days = np.nonzero(lab.E.any(axis=1))[0]
    report = {
        "label": LABEL, "version": VERSION, "configHash": config_hash(), "config": config(),
        "createdAt": datetime.now(ET).isoformat(timespec="seconds"), "source": source or {},
        "universe": {"tickers": len(tickers), "used": len(P["names"]), "excluded": P["excluded"],
                     "note": "Nasdaq-100 di oggi applicato a tutto il periodo (survivorship bias)"},
        "period": {"prices": [P["cal"][0].date().isoformat(), P["cal"][-1].date().isoformat()],
                   "decisions": [lab.cal[obs_days[0]].date().isoformat(), lab.cal[obs_days[-1]].date().isoformat()]
                   if len(obs_days) else None, "segments": seg_info, "finalOpened": open_final},
        "observations": int(lab.E.sum()), "quality": P["quality"], "scannerCheck": {"checked": checked, "differences": 0},
        "groups": groups, "redundancy": redundancy(lab), "atrQuintiles": atr_buckets(lab),
        "walkForward": {"combinations": walk_forward(lab, ["C3", "C4", "C5"]), "singles": walk_forward(lab, CONDS)},
        "simulation": sim_report(P, F, lab) if with_sim else {"available": False, "reason": "non richiesta"},
        "limits": LIMITS, "notTestable": NOT_TESTABLE, "priceConvention": PRICE_CONVENTION,
        "seconds": round(time.time() - t0, 1),
    }
    if treatment:
        report["dataTreatment"] = treatment
    report["summary"] = panel_summary(report)
    return report


def panel_summary(r):
    """The few numbers the dashboard may show (horizon 21 sessions, all the allowed periods)."""
    rows = []
    for k in ("T1", "T2", "T3", "T4", "T5", "C3", "C4", "C5"):
        g = r["groups"][k]["h"][str(MAIN_H)]
        a = g["tutto"]
        rows.append({"id": k, "name": GROUP_TEXT[k], "n": a.get("n"), "days": a.get("days"),
                     "vsOthers": a.get("vsOthers"), "vsQqq": a.get("vsQqq"), "verdict": g.get("verdict"),
                     "verdicts": {h: r["groups"][k]["h"][str(h)].get("verdict") for h in map(str, HORIZONS)}})
    sim = r.get("simulation") or {}
    s = next((x for x in sim.get("scenarios", []) if x["cost"] == SIM["costs"][1]), None)
    return {"label": r["label"], "createdAt": r["createdAt"], "version": r["version"], "configHash": r["configHash"],
            "scannerModel": r["config"]["scannerModel"], "horizon": MAIN_H, "source": r["source"],
            "period": r["period"]["decisions"], "segments": r["period"]["segments"], "finalOpened": r["period"]["finalOpened"],
            "universe": r["universe"]["used"], "observations": r["observations"], "rows": rows,
            "sim": {"cost": s["cost"], "total": s["total"], "annual": s["annual"], "maxDrawdown": s["maxDrawdown"],
                    "qqqTotal": sim["qqq"]["total"], "qqqMaxDrawdown": sim["qqq"]["maxDrawdown"],
                    "randomMedian": sim["random"]["median"], "randomP10": sim["random"]["p10"],
                    "randomP90": sim["random"]["p90"]} if s else None,
            "limits": r["limits"]}


# ---------------------------------------------------------------- files: prices snapshot, reports, experiment log

def _closed_last_day(now=None):
    import server
    return server.last_closed_session(now)


def load_prices(mode):
    """mode 'salvati' (latest snapshot), 'scarica' (10 years from Yahoo, saved as a new snapshot) or 'dashboard' (the
    2-year cache of the dashboard, no download). Returns (data, tickers, source)."""
    import server
    if mode == "dashboard":
        got = server.load_daily_cache()
        if not got:
            raise SystemExit("cache giornaliera della dashboard assente o vecchia: avvia la dashboard o usa --scarica")
        data, saved = got
        tickers = [c["ticker"] for c in server.load_constituents()]
        return data, tickers, {"kind": "cache della dashboard (2 anni)", "saved": datetime.fromtimestamp(saved, ET).isoformat(timespec="seconds")}
    snaps = sorted(glob.glob(os.path.join(OUT_DIR, "prezzi_*.pkl")))
    if mode == "salvati" and snaps:
        s = pd.read_pickle(snaps[-1])
        return s["data"], s["tickers"], {"kind": "prezzi salvati", "file": os.path.basename(snaps[-1]), "saved": s["saved"]}
    tickers = [c["ticker"] for c in server.load_constituents()]
    print(f"Scarico {len(tickers) + 1} serie giornaliere da {START} (Yahoo Finance)…", flush=True)
    data = server.download(tickers + [BENCH], start=START, interval="1d")
    if BENCH not in data:
        raise SystemExit("download non riuscito: riprova più tardi")
    os.makedirs(OUT_DIR, exist_ok=True)
    name = f"prezzi_{datetime.now(ET):%Y-%m-%d_%H%M}.pkl"
    saved = datetime.now(ET).isoformat(timespec="seconds")
    pd.to_pickle({"saved": saved, "start": START, "tickers": tickers, "data": data}, os.path.join(OUT_DIR, name))
    return data, tickers, {"kind": "download Yahoo Finance", "file": name, "saved": saved}


def finite(x):
    if isinstance(x, dict):
        return {str(k): finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [finite(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return None if math.isnan(x) or math.isinf(x) else float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def save(report, out_dir=None, log=None):
    """Writes the report as a new file and appends one line to the experiment log (never rewritten)."""
    out_dir = out_dir or OUT_DIR
    log = log or os.path.join(out_dir, "esperimenti.jsonl")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(ET).strftime("%Y-%m-%d_%H%M%S")
    path = os.path.join(out_dir, f"report_{stamp}.json")
    with open(path, "w") as f:
        json.dump(finite(report), f, ensure_ascii=False, indent=1)
    entry = {"at": report["createdAt"], "file": os.path.basename(path), "configHash": report["configHash"],
             "version": report["version"], "source": report["source"], "period": report["period"]["decisions"],
             "finalOpened": report["period"]["finalOpened"],
             "verdicts": {k: g["h"][str(MAIN_H)].get("verdict") for k, g in report["groups"].items() if g["judged"]}}
    with open(log, "a") as f:
        f.write(json.dumps(finite(entry), ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "riepilogo.json"), "w") as f:     # the only file the dashboard reads
        json.dump(finite({**report["summary"], "file": os.path.basename(path)}), f, ensure_ascii=False)
    return path


def read_summary(out_dir=None):
    """The summary of the latest saved report for the dashboard (a small file: nothing is computed), or None."""
    try:
        with open(os.path.join(out_dir or OUT_DIR, "riepilogo.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def final_uses(config_h, log=None):
    """How many times the sealed final period was already opened with this configuration."""
    log = log or LOG
    if not os.path.exists(log):
        return 0
    n = 0
    with open(log) as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            n += bool(e.get("finalOpened")) and e.get("configHash") == config_h
    return n


def latest(out_dir=None):
    files = sorted(glob.glob(os.path.join(out_dir or OUT_DIR, "report_*.json")))
    if not files:
        return None
    with open(files[-1]) as f:
        return json.load(f)


# ---------------------------------------------------------------- printing (Italian, for the terminal)

def _f(x, d=2, plus=True):
    if x is None:
        return "n.d."
    s = f"{x:+.{d}f}" if plus else f"{x:.{d}f}"
    return s.replace(".", ",")


def print_report(r):
    p = r["period"]
    print(f"\n=== {r['label'].upper()} ===")
    print(f"Laboratorio {r['version']} · modello scanner {r['config']['scannerModel']} · configurazione {r['configHash']}")
    print(f"Creato {r['createdAt']} · dati: {r['source'].get('kind', 'n.d.')} {r['source'].get('file', '')}")
    print(f"Prezzi {p['prices'][0]} → {p['prices'][1]} · giorni di segnale {p['decisions'][0]} → {p['decisions'][1]}")
    for s, i in p["segments"].items():
        tag = " (SIGILLATO: non usato)" if i["sealed"] else ""
        print(f"  {s:9s} {i['from']} → {i['to']} · {i['days']} giorni{tag}")
    u = r["universe"]
    print(f"Universo: {u['used']} titoli del Nasdaq-100 di oggi (esclusi {len(u['excluded'])}: "
          f"{', '.join(f'{k} ({v})' for k, v in u['excluded'].items()) or 'nessuno'})")
    print(f"Osservazioni (titolo × giorno): {r['observations']} · controllo con lo scanner: "
          f"{r['scannerCheck']['checked']} casi, nessuna differenza")
    q = r["quality"]
    print(f"Qualità dati: {len(q['jumps'])} movimenti oltre ±{JUMP:.0f}% in un giorno, {q['missingOpen']} aperture mancanti, "
          f"{q['zeroVolume']} volumi a zero, {len(q['lateListing'])} titoli quotati dopo l'inizio")
    for j in q["jumps"][:8]:
        print(f"   {j['ticker']} {j['date']} {_f(j['move'], 1)}%")
    print("Rendimenti: chiusura del giorno del segnale → chiusura h sedute dopo (non ottenibile: segnale noto dopo la chiusura)")
    for h in HORIZONS:
        print(f"\n--- Orizzonte {h} sedute · differenze medie per giorno, in punti % ---")
        print(f"{'gruppo':42s} {'segnali':>8s} {'giorni':>6s} {'titoli':>6s} {'media':>7s} {'%>0':>5s} "
              f"{'vs QQQ':>7s} {'vs univ':>7s} {'vs altri':>8s} {'t':>5s} {'indip':>5s} {'caso%':>5s}  giudizio")
        for k, g in r["groups"].items():
            x = g["h"][str(h)]
            a = x["tutto"]
            print(f"{k + ' ' + g['name']:42.42s} {a.get('n', 0):8d} {a.get('days', 0):6d} {a.get('stocks', 0):6d} "
                  f"{_f(a.get('mean')):>7s} {_f(a.get('positive'), 0, False):>5s} {_f(a.get('vsQqq')):>7s} "
                  f"{_f(a.get('vsUniverse')):>7s} {_f(a.get('vsOthers')):>8s} {_f(a.get('tOthers'), 1):>5s} "
                  f"{a.get('indep', 0) or 0:5d} {_f(a.get('randomPct'), 0, False):>5s}  {x.get('verdict', 'esplorativo')}")
        print("  sviluppo → verifica (vs altri, t):", "; ".join(
            f"{k} {_f(g['h'][str(h)]['sviluppo'].get('vsOthers'))} ({_f(g['h'][str(h)]['sviluppo'].get('tOthers'), 1)}) → "
            f"{_f(g['h'][str(h)]['verifica'].get('vsOthers'))} ({_f(g['h'][str(h)]['verifica'].get('tOthers'), 1)})"
            for k, g in r["groups"].items() if g["judged"]))
    g = r["groups"]["C4"]["h"][str(MAIN_H)]["tutto"]
    print(f"\nRegola attuale 4/5 a {MAIN_H} sedute per anno (vs altri):",
          ", ".join(f"{y} {_f(v['vsOthers'])}" for y, v in g.get("years", {}).items()))
    print("Per regime di mercato:", "; ".join(f"{k}: {v['days']} giorni, vs altri {_f(v['vsOthers'])}, scelti {_f(v['selected'])} "
                                             f"contro QQQ {_f(v['qqq'])}" for k, v in g.get("regimes", {}).items()))
    red = r["redundancy"]
    print(f"\nRidondanza (correlazione phi su {red['observations']} osservazioni con tutte le condizioni giudicabili):")
    print("      " + " ".join(f"{c:>6s}" for c in CONDS) + "   % soddisfatta")
    for a in CONDS:
        print(f"  {a}  " + " ".join(f"{_f(red['phi'][a][b], 2, False):>6s}" for b in CONDS) + f"   {_f(red['share'][a], 1, False)}")
    print("Dati mancanti per condizione:", ", ".join(f"{c} {v}" for c, v in red["missing"].items()))
    print(f"\nATR (esplorativo, {MAIN_H} sedute, quintili di ogni giorno):",
          "; ".join(f"Q{b['quintile']} ATR {_f(b['atrMedian'], 1, False)}% vs univ {_f(b['vsUniverse'])} dev.st {_f(b['std'], 1, False)}"
                    for b in r["atrQuintiles"]))
    for name, wf in r["walkForward"].items():
        print(f"\nWalk-forward ({'combinazioni' if name == 'combinations' else 'condizioni singole'}, {wf['horizon']} sedute): "
              f"la scelta migliore sul passato è rimasta positiva {wf['chosenPositive']} anni su {wf['years']}, "
              f"è stata la migliore dell'anno {wf['chosenWasBest']} volte")
        for x in wf["rows"]:
            print(f"   {x['year']}: scelta {x['chosen']} (passato {_f(x['chosenPast'])}) → nell'anno {_f(x['chosenThen'])}; "
                  f"4/5 fisso {_f(x['fixedThen'])}; migliore dell'anno {x['bestThen']}")
    s = r["simulation"]
    print("\n--- Simulazione sperimentale (non una strategia, non un consiglio) ---")
    if not s.get("available"):
        print("Non disponibile:", s.get("reason"))
    else:
        print(f"Regola {s['rule']}; ingresso {s['entry']}; uscita {s['exit']}; capitale ipotetico {s['capital']:.0f}; "
              f"massimo {s['maxPositions']} titoli; {s['costsNote']}")
        for x in s["scenarios"]:
            print(f"  costi {_f(x['cost'], 2, False)}% per lato: totale {_f(x['total'])}%, annuo {_f(x['annual'])}%, "
                  f"perdita massima {_f(x['maxDrawdown'])}%, rendimento/rischio {_f(x['riskAdjusted'])}, "
                  f"profit factor {_f(x['profitFactor'], 2, False)}, operazioni {x['trades']} ({_f(x['tradesPerMonth'], 1, False)} al mese), "
                  f"rotazione {_f(x['turnover'], 1, False)} volte l'anno")
        qq = s["qqq"]
        print(f"  QQQ nello stesso periodo: totale {_f(qq['total'])}%, annuo {_f(qq['annual'])}%, "
              f"perdita massima {_f(qq['maxDrawdown'])}%, rendimento/rischio {_f(qq['riskAdjusted'])}")
        rd = s["random"]
        print(f"  Controllo casuale ({rd['runs']} prove, costi {_f(rd['cost'], 2, False)}%): totale mediano {_f(rd['median'])}% "
              f"(10°–90° percentile {_f(rd['p10'])}% … {_f(rd['p90'])}%)")
    print("\nLimiti:")
    for x in r["limits"]:
        print(" -", x)
    print("Non testabili sul passato:", "; ".join(r["notTestable"]))
    print(f"\n{r['label']}: nessun risultato è una validazione definitiva né un consiglio di acquisto.\n")


def print_config():
    c = config()
    print(json.dumps(c, ensure_ascii=False, indent=1))
    print("\nLimiti:")
    for x in LIMITS:
        print(" -", x)


def print_invest(x):
    print("\n=== Investimento: cosa permettono i dati ===")
    print(x["why"])
    print("Stato:", x["status"], "· modello", x["model"], "· orizzonti 63 e 126 sedute")
    if x.get("dailyHistory"):
        d = x["dailyHistory"]
        print(f"Storico giornaliero: {d['sessions']} sedute ({d['from']} → {d['to']}), {d['stocksWith127']} titoli su "
              f"{d['stocks']} con almeno 127 sedute. {d['note']}.")
    dd = x["diary"]
    if not dd["exists"]:
        print("Diario:", dd["note"])
    else:
        print(f"Diario: {dd['sessions']} sedute ({dd['first']} → {dd['last']}), {dd['investObservations']} osservazioni "
              f"Investimento, risultati misurati: 63 sedute {dd['results']['63']}, 126 sedute {dd['results']['126']}")
        if x.get("firstResults"):
            print(f"Primi risultati possibili: 63 sedute dal {x['firstResults']['63']}, 126 sedute dal {x['firstResults']['126']}")


# ---------------------------------------------------------------- phase 4A: recheck with verified data, kept apart

RECHECK_DIR = os.path.join(OUT_DIR, "rielaborazioni")
SAME_KEYS = ("groups", "redundancy", "atrQuintiles", "walkForward", "simulation", "observations", "period", "universe", "config")


def same_results(a, b):
    """True when two reports have the same results (creation time, duration, source and summary aside)."""
    pick = lambda r: json.dumps(finite({k: r.get(k) for k in SAME_KEYS}), sort_keys=True, ensure_ascii=False)
    return pick(a) == pick(b)


def compare(orig, new):
    """Original vs recheck, group by group and horizon: signals, difference with the others, t and verdict."""
    rows = []
    for k, g in orig["groups"].items():
        for h in map(str, HORIZONS):
            a, b = g["h"][h]["tutto"], new["groups"][k]["h"][h]["tutto"]
            va, vb = g["h"][h].get("verdict"), new["groups"][k]["h"][h].get("verdict")
            d = None if a.get("vsOthers") is None or b.get("vsOthers") is None else round(b["vsOthers"] - a["vsOthers"], 3)
            rows.append({"group": k, "name": g["name"], "h": int(h), "n": [a.get("n"), b.get("n")],
                         "vsOthers": [a.get("vsOthers"), b.get("vsOthers")], "vsQqq": [a.get("vsQqq"), b.get("vsQqq")],
                         "t": [a.get("tOthers"), b.get("tOthers")], "verdict": [va, vb], "diff": d,
                         "verdictChanged": va != vb})
    sa = next((x for x in orig.get("simulation", {}).get("scenarios", []) if x["cost"] == SIM["costs"][1]), None)
    sb = next((x for x in new.get("simulation", {}).get("scenarios", []) if x["cost"] == SIM["costs"][1]), None)
    diffs = [abs(r["diff"]) for r in rows if r["diff"] is not None]
    return {"rows": rows, "verdictsChanged": [r for r in rows if r["verdictChanged"]],
            "maxAbsDiff": max(diffs) if diffs else None,
            "sim": {"cost": SIM["costs"][1], "total": [sa and sa["total"], sb and sb["total"]],
                    "random": [orig.get("simulation", {}).get("random", {}).get("median"),
                               new.get("simulation", {}).get("random", {}).get("median")]},
            "observations": [orig.get("observations"), new.get("observations")]}


def recheck(original_path, reviews=None, out_dir=None):
    """Reproduces a saved study from its own price file, then reruns it on a copy without the verified errors
    (data_quality_reviews.json, exclude=true). Never opens the final period, never writes next to the originals."""
    import market_data_quality as mq
    with open(original_path) as f:
        orig = json.load(f)
    if orig["period"]["finalOpened"]:
        raise SystemExit("il report originale ha il periodo finale aperto: la rielaborazione lo terrebbe aperto")
    snap = os.path.join(os.path.dirname(original_path), orig["source"]["file"])
    s = pd.read_pickle(snap)
    last = orig["period"]["prices"][1]
    again = finite(study(s["data"], s["tickers"], last_day=last, source=orig["source"]))
    reproduced = same_results(orig, again)
    rev = reviews if reviews is not None else mq.load_reviews()
    data2, removed = mq.apply_verified(s["data"], rev)
    q = mq.check(s["data"], s["tickers"], as_of=s["saved"][:10], reviews=rev, saved_at=s["saved"])
    treatment = {"what": "esclusi solo i tratti «errore verificato» con exclude=true della revisione manuale",
                 "reviewsVersion": rev.get("version"), "reviewsHash": mq.reviews_hash(rev), "criteria": rev.get("criteria", []),
                 "removed": removed, "original": os.path.basename(original_path), "prices": orig["source"]["file"],
                 "qualityCounts": q["counts"]}
    new = finite(study(data2, s["tickers"], last_day=last, source={**orig["source"], "kind": orig["source"].get("kind", "") +
                                                                     f" + revisione {rev.get('version')}"},
                       treatment=treatment))
    new["variant"] = f"dati verificati {rev.get('version')}"
    new["comparison"] = compare(orig, new)
    new["reproducedOriginal"] = reproduced
    out_dir = out_dir or RECHECK_DIR
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(ET).strftime("%Y-%m-%d_%H%M%S")
    path = os.path.join(out_dir, f"report_{stamp}_{rev.get('version')}.json")
    with open(path, "w") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    c = new["comparison"]
    entry = {"at": new["createdAt"], "file": os.path.basename(path), "original": os.path.basename(original_path),
             "reviews": rev.get("version"), "reviewsHash": treatment["reviewsHash"], "configHash": new["configHash"],
             "removed": removed, "reproducedOriginal": reproduced, "finalOpened": False,
             "verdictsChanged": len(c["verdictsChanged"]), "maxAbsDiff": c["maxAbsDiff"]}
    with open(os.path.join(out_dir, "registro.jsonl"), "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "riepilogo.json"), "w") as f:
        json.dump({**entry, "variant": new["variant"], "label": new["label"], "qualityCounts": q["counts"],
                   "changes": [{k: r[k] for k in ("name", "h", "vsOthers", "verdict")} for r in c["verdictsChanged"]],
                   "verdicts": {k: {h: g["h"][h].get("verdict") for h in map(str, HORIZONS)}
                                for k, g in new["groups"].items() if g["judged"]},
                   "rows21": {k: new["groups"][k]["h"][str(MAIN_H)]["tutto"].get("vsOthers") for k in ("C4", "C5")},
                   "sim": c["sim"]}, f, ensure_ascii=False)
    return path, new, reproduced


# ---------------------------------------------------------------- phase 4A: reliability states shown in the dashboard

STATES = {
    "esplorativo": "Screening esplorativo",
    "in_verifica": "Strategia in fase di verifica",
    "validata": "Strategia validata secondo criteri documentati",
    "non_validata": "Strategia non validata o con risultati insufficienti",
}
SHORT = {"esplorativo": "screening esplorativo", "in_verifica": "in verifica", "validata": "validata",
         "non_validata": "non validata"}
STATE_CRITERIA = [
    ("Screening esplorativo", "le classifiche ordinano titoli da osservare con condizioni scritte; non sono una previsione "
     "di rendimento. Vale sempre per entrambe le classifiche."),
    ("Strategia validata secondo criteri documentati", "solo con tutte e tre: (1) giudizio «differenza migliore credibile» nello "
     "studio storico, sviluppo e verifica, sui dati verificati; (2) conferma nel periodo finale sigillato, aperto una sola "
     "volta; (3) conferma del diario prospettico con almeno 100 casi in 20 giornate. Nessuna regola oggi."),
    ("Strategia in fase di verifica", "giudizio credibile migliore nello studio storico in attesa del periodo finale e del "
     "diario; oppure, per ciò che non si può provare sul passato, diario prospettico già avviato."),
    ("Strategia non validata o con risultati insufficienti", "studio storico senza un vantaggio credibile sui titoli non "
     "scelti dello stesso giorno, oppure nessuno studio possibile e nessun dato del diario."),
]
RULES = {"C4": "Trading · almeno 4 condizioni su 5 (regola della classifica)", "C5": "Trading · tutte e 5 le condizioni"}


def reliability(summary=None, recheck=None, diary=None):
    """The validation state of each rule, from documented criteria (never set by hand). summary: riepilogo.json of the
    original study; recheck: riepilogo of the recheck with verified data; diary: opportunity_diary.stats()."""
    items = []
    rows = {r["id"]: r for r in (summary or {}).get("rows", [])}
    for k, name in RULES.items():
        r = rows.get(k)
        if not r:
            items.append({"id": k, "name": name, "state": "non_validata", "label": STATES["non_validata"],
                          "reason": "nessuno studio storico salvato"})
            continue
        verdicts = dict(r.get("verdicts") or {})
        if recheck and recheck.get("verdicts", {}).get(k):
            verdicts = recheck["verdicts"][k]               # the verified data come first
        better = [h for h, v in verdicts.items() if v and v.startswith("Differenza migliore credibile")]
        vs = (recheck or {}).get("rows21", {}).get(k, r.get("vsOthers"))
        num = f"{vs:+.2f}".replace(".", ",").replace("-", "−") if vs is not None else "n.d."
        if better:
            state = "in_verifica"
            reason = (f"vantaggio credibile nello studio storico a {', '.join(better)} sedute: mancano la conferma del periodo "
                      "finale sigillato e quella del diario")
            short = f"vantaggio storico da confermare ({', '.join(better)} sedute)"
        else:
            state = "non_validata"
            reason = (f"nello studio storico (survivorship bias{', dati verificati' if recheck else ''}) {num} punti a "
                      f"{summary.get('horizon', MAIN_H)} sedute contro i titoli non scelti dello stesso giorno: nessun vantaggio "
                      "credibile a 5, 10 e 21 sedute")
            short = f"studio storico: {num} punti contro i titoli non scelti, nessun vantaggio credibile"
        items.append({"id": k, "name": name, "state": state, "label": STATES[state], "shortLabel": SHORT[state],
                      "reason": reason, "short": short})
    days = (diary or {}).get("days", 0) if (diary or {}).get("started") else 0
    if days:
        recorded = f"{days} {'giornata registrata' if days == 1 else 'giornate registrate'}"
        inv = {"state": "in_verifica", "reason": f"non validabile sul passato (mancano fondamentali point-in-time); verifica solo "
                                                f"in avanti con il diario: {recorded}, risultati a 63 e 126 sedute",
               "short": f"non validabile sul passato; verifica in avanti con il diario ({recorded})"}
    else:
        inv = {"state": "non_validata", "reason": "non validabile sul passato (mancano fondamentali point-in-time); il diario "
                                                 "prospettico non ha ancora registrato sedute",
               "short": "non validabile sul passato; diario non ancora avviato"}
    items.append({"id": "INV", "name": "Investimento · almeno 5 condizioni su 6 (regola della classifica)",
                  "label": STATES[inv["state"]], "shortLabel": SHORT[inv["state"]], **inv})
    return {"screening": STATES["esplorativo"], "items": items, "states": STATES,
            "criteria": [{"title": a, "text": b} for a, b in STATE_CRITERIA],
            "note": "Il numero di condizioni soddisfatte serve a ordinare i titoli da osservare: non è una previsione di "
                    "rendimento né una prova che salgano."}


def read_recheck(out_dir=None):
    try:
        with open(os.path.join(out_dir or RECHECK_DIR, "riepilogo.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def print_comparison(new):
    c = new["comparison"]
    t = new["dataTreatment"]
    print(f"\n=== RIELABORAZIONE CON DATI VERIFICATI ({new['variant']}) · {new['label']} ===")
    print(f"Originale: {t['original']} · prezzi {t['prices']} · revisione {t['reviewsVersion']} ({t['reviewsHash']})")
    print("Studio originale riprodotto identico dagli stessi prezzi:", "sì" if new["reproducedOriginal"] else "NO")
    for r in t["removed"]:
        print(f"Escluso: {r['ticker']} dal {r['from']} al {r['to']} ({r['rows']} sedute){' — tratto centrale: titolo escluso' if r['middle'] else ''}")
    print(f"Osservazioni: {c['observations'][0]} → {c['observations'][1]} · differenza massima contro i non scelti: "
          f"{_f(c['maxAbsDiff'], 3, False)} punti · periodo finale: ancora sigillato")
    print(f"\n{'gruppo':40s} {'h':>3s} {'segnali':>15s} {'vs altri':>17s} {'t':>13s}  giudizio")
    for r in c["rows"]:
        if r["group"] not in JUDGED:
            continue
        mark = "  ← CAMBIATO" if r["verdictChanged"] else ""
        print(f"{r['name'][:40]:40s} {r['h']:3d} {r['n'][0]:>7} → {r['n'][1]:<6} {_f(r['vsOthers'][0]):>7s} → {_f(r['vsOthers'][1]):<7s} "
              f"{_f(r['t'][0], 1):>5s} → {_f(r['t'][1], 1):<5s}  {r['verdict'][1]}{mark}")
    s = c["sim"]
    print(f"\nSimulazione (costi {_f(s['cost'], 2, False)}%): {_f(s['total'][0])}% → {_f(s['total'][1])}% · scelte a caso "
          f"(mediana) {_f(s['random'][0])}% → {_f(s['random'][1])}%")
    print(f"Giudizi cambiati: {len(c['verdictsChanged'])}\n")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "show"
    if cmd == "config":
        print_config()
    elif cmd == "run":
        mode = "scarica" if "--scarica" in argv else "dashboard" if "--dashboard" in argv else "salvati"
        open_final = "--apri-finale" in argv
        h = config_hash()
        if open_final:
            used = final_uses(h)
            print(f"ATTENZIONE: apri il periodo finale sigillato (già aperto {used} volte con questa configurazione). "
                  "Non va usato per scegliere o ritoccare le regole.")
        data, tickers, source = load_prices(mode)
        r = study(data, tickers, last_day=_closed_last_day(), open_final=open_final, source=source)
        if open_final:
            r["finalPreviousUses"] = final_uses(h)
        path = save(r)
        print_report(r)
        print("Report salvato:", os.path.relpath(path, ROOT))
    elif cmd == "show":
        if len(argv) > 2:
            with open(argv[2]) as f:
                r = json.load(f)
        else:
            r = latest()
        if not r:
            print("Nessun report: esegui `python opportunity_validation.py run --scarica` (10 anni) o `run --dashboard` (2 anni).")
            return
        print_report(r)
    elif cmd == "rielabora":
        args = [a for a in argv[2:] if not a.startswith("--")]
        originals = sorted(glob.glob(os.path.join(OUT_DIR, "report_*.json")))
        target = args[0] if args else (originals[-1] if originals else None)
        if not target:
            print("Nessun report originale da rielaborare.")
            return
        path, new, ok = recheck(target)
        print_comparison(new)
        print("Rielaborazione salvata a parte:", os.path.relpath(path, ROOT), "(i report originali non sono stati toccati)")
    elif cmd == "investimento":
        import server
        got = server.load_daily_cache()
        print_invest(invest_check(got[0] if got else None))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
