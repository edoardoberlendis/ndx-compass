"""Backtest of the technical part of the final signal (plan phase 8).

Every STEP trading days over the last ~10 years it recomputes, for each of TODAY's Nasdaq-100 stocks,
the same technical score the dashboard uses (signals.metrics: 20/40/60-day averages, RSI, strength vs
QQQ), puts it in the same bands as the final signal (score.level: Forte acquisto … Forte vendita) and
measures what happened 1, 3 and 6 months later, for the stock and for QQQ over the same days.

    .venv/bin/python backtest.py          # ~30 s, writes reports/backtest.json (shown in the Ideas tab)

Only the technical part can be tested: analysts, valuation and news have no free point-in-time
history. Weights and thresholds are NOT tuned here. Read the limits in LIMITS before trusting it.
"""
from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime

import numpy as np
import pandas as pd

import score
import signals
from server import ET, ROOT, clean, download, load_constituents

BENCH = signals.BENCH                 # QQQ
MAS = signals.MAS                     # (20, 40, 60)
HORIZONS = {"1M": 21, "3M": 63, "6M": 126}
STEP = 5                              # one observation per stock per week
YEARS = "10y"
BANDS = ["Forte acquisto", "Acquisto", "Neutro", "Vendita", "Forte vendita"]
OUT = os.path.join(ROOT, "reports", "backtest.json")

LIMITS = [
    ("Survivorship bias (il più importante)",
     "Il test usa i titoli che sono nel Nasdaq-100 OGGI. Mancano quelli usciti negli ultimi 10 anni perché sono crollati, "
     "falliti o sono stati comprati, e ci sono titoli entrati di recente proprio perché sono saliti moltissimo (per esempio "
     "Palantir, AppLovin, Strategy). Il loro rialzo passato è incluso: per questo quasi tutte le fasce sembrano battere QQQ. "
     "Un segnale che segue il trend, come questo, è favorito più degli altri, perché tende a comprare proprio i titoli che poi "
     "sono diventati grandi. La riga «Tutti i titoli» mostra quanto vale questo vantaggio 'gratuito': conta soprattutto la "
     "differenza tra le fasce, non il valore assoluto."),
    ("Casi non indipendenti",
     "Il segnale è misurato ogni settimana ma i rendimenti coprono 1, 3 o 6 mesi: le finestre si sovrappongono e lo stesso "
     "titolo compare molte volte di fila con lo stesso segnale. Il numero di casi sembra grande, ma le osservazioni davvero "
     "indipendenti sono molte meno: differenze piccole tra le fasce possono essere dovute al caso."),
    ("Un solo tipo di mercato",
     "Gli ultimi 10 anni sono stati soprattutto un mercato rialzista guidato dalla tecnologia, con un solo anno negativo "
     "importante (2022). Guarda la tabella per anno: se una fascia funziona solo in alcuni anni, il risultato è fragile."),
    ("Nessun costo",
     "Non ci sono commissioni, spread, tasse né slittamenti di prezzo. I prezzi sono rettificati per dividendi e frazionamenti."),
    ("Solo il 40% del segnale",
     "Viene testata solo la parte tecnica. Analisti, valutazione e notizie (60% del segnale finale) non hanno uno storico "
     "gratuito 'com'era quel giorno', quindi il segnale completo non è verificato."),
    ("Pesi e soglie non ottimizzati",
     "Le soglie (±20, ±50) e il calcolo del punteggio sono quelli della dashboard, scelti prima del test e non adattati ai "
     "risultati: questo evita di 'imparare il passato a memoria', ma significa anche che non sono stati convalidati."),
]


# ---------------------------------------------------------------- vectorised technical score

def _ewm_last(x, alpha):
    """Last value of an adjust=False EWM along axis 1 (x: samples × window), started at the first value."""
    y = x[:, 0].copy()
    for j in range(1, x.shape[1]):
        y = (1 - alpha) * y + alpha * x[:, j]
    return y


def tech_scores(df, bench, positions):
    """signals.metrics()["score"] at the given row positions of df, without recomputing each slice."""
    c, h, lo, v = df["Close"], df["High"], df["Low"], df["Volume"]
    sma = {n: c.rolling(n).mean() for n in MAS}
    slope = {n: (sma[n] / sma[n].shift(5) - 1) * 100 for n in MAS}
    s20, s40, s60 = (sma[n] for n in MAS)
    bull = (c > s20) & (s20 > s40) & (s40 > s60)
    bear = (c < s20) & (s20 < s40) & (s40 < s60)
    sc = sum(np.where(x, 8.33, -8.33) for x in (c > s20, s20 > s40, s40 > s60))
    sc = sc + sum(5 * np.tanh(slope[n] / 1.0) for n in MAS)
    b = bench.reindex(c.index).ffill()
    ret = lambda s, n: ((s / s.shift(n) - 1) * 100).fillna(0)
    sc = sc + np.clip(1.5 * (ret(c, 21) - ret(b, 21)), -20, 20) + np.clip(0.5 * (ret(c, 63) - ret(b, 63)), -15, 15)
    vr = v.rolling(20).mean() / v.rolling(60).mean()
    sc = sc + np.where((vr > 1.1) & bull, 5, 0) - np.where((vr > 1.1) & bear, 5, 0)
    sc = sc - np.where((c / s20 - 1) * 100 > 10, 10, 0)
    sc = np.asarray(sc)[positions]

    # RSI(14) exactly as signals.rsi: EWM over the last 42 daily changes only
    d = c.diff().to_numpy()
    win = np.stack([d[p - 41:p + 1] for p in positions])
    up, dn = _ewm_last(np.clip(win, 0, None), 1 / 14), _ewm_last(-np.clip(win, None, 0), 1 / 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = np.where(dn == 0, 100.0, 100 - 100 / (1 + up / dn))
    sc = sc + np.clip((rsi - 50) * 0.5, -10, 10)
    return np.round(np.clip(sc, -100, 100), 1)


def check_against_signals(frames, bench, n=25):
    """Largest difference vs signals.metrics() on random (stock, day) pairs: must be ~0 (rounding)."""
    rnd, worst = random.Random(7), 0.0
    for _ in range(n):
        t = rnd.choice(list(frames))
        df = frames[t]
        if len(df) < 200:
            continue
        p = rnd.randrange(80, len(df))
        ref = signals.metrics(df.iloc[:p + 1], bench)["score"]
        worst = max(worst, abs(tech_scores(df, bench, np.array([p]))[0] - ref))
    return worst


# ---------------------------------------------------------------- run

def run():
    t0 = time.time()
    tickers = [c["ticker"] for c in load_constituents()]
    data = download(tickers + [BENCH], period=YEARS, interval="1d")
    bench = data[BENCH]["Close"].dropna()
    frames = {t: data[t].dropna(subset=["Close"]) for t in tickers if t in data}
    sample_dates = bench.index[70::STEP]          # same calendar for every stock
    max_h = max(HORIZONS.values())

    rows = []
    for t, df in frames.items():
        idx = df.index
        pos = idx.get_indexer(sample_dates)
        pos = pos[(pos >= 69) & (pos + max_h < len(df))]  # metrics() needs 70 bars; need the full 6-month future
        if not len(pos):
            continue
        scores = tech_scores(df, bench, pos)
        c = df["Close"].to_numpy()
        q = bench.reindex(idx).ffill().to_numpy()
        for k, p in enumerate(pos):
            rec = {"date": idx[p], "ticker": t, "score": scores[k], "band": score.level(scores[k])}
            for name, hz in HORIZONS.items():
                rec[f"r{name}"] = (c[p + hz] / c[p] - 1) * 100
                rec[f"q{name}"] = (q[p + hz] / q[p] - 1) * 100
            rows.append(rec)
    obs = pd.DataFrame(rows)
    diff = check_against_signals(frames, bench)

    results = {}
    for name in HORIZONS:
        ex = obs[f"r{name}"] - obs[f"q{name}"]
        all_ex = float(ex.mean())

        def summary(mask, label):
            e = ex[mask]
            return {"band": label, "n": int(mask.sum()), "tickers": int(obs.loc[mask, "ticker"].nunique()),
                    "ret": float(obs.loc[mask, f"r{name}"].mean()), "qqq": float(obs.loc[mask, f"q{name}"].mean()),
                    "excess": float(e.mean()), "excessMedian": float(e.median()), "beat": float((e > 0).mean() * 100),
                    "vsAll": float(e.mean() - all_ex)}
        results[name] = [summary(obs["band"] == b, b) for b in BANDS if (obs["band"] == b).any()]
        results[name].append(summary(obs["band"].notna(), "Tutti i titoli"))

    # 3-month excess return by calendar year: is the pattern stable, or driven by a few years?
    obs["year"] = obs["date"].dt.year
    obs["ex3M"] = obs["r3M"] - obs["q3M"]
    by_year = []
    for y, g in obs.groupby("year"):
        row = {"year": int(y), "n": int(len(g)), "all": float(g["ex3M"].mean())}
        for b in BANDS:
            gb = g[g["band"] == b]["ex3M"]
            row[b] = float(gb.mean()) if len(gb) >= 20 else None   # too few cases → not shown
        by_year.append(row)

    report = {
        "generated": datetime.now(ET).isoformat(timespec="seconds"),
        "from": str(obs["date"].min().date()), "to": str(obs["date"].max().date()),
        "stocks": int(obs["ticker"].nunique()), "observations": int(len(obs)), "stepDays": STEP,
        "horizons": {k: v for k, v in HORIZONS.items()}, "bands": BANDS,
        "results": results, "byYear": by_year,
        "scoreDist": {b: int((obs["band"] == b).sum()) for b in BANDS},
        "checkMaxDiff": float(diff),
        "limits": [{"title": a, "text": b} for a, b in LIMITS],
        "elapsed": round(time.time() - t0, 1),
    }
    with open(OUT, "w") as f:
        json.dump(report, f, default=clean, allow_nan=False)
    return report


def print_report(r):
    print(f"Backtest {r['from']} → {r['to']} · {r['stocks']} titoli · {r['observations']} osservazioni "
          f"(una a settimana) · verifica vs signals.metrics: differenza massima {r['checkMaxDiff']:.2f} · {r['elapsed']}s")
    for name, rows in r["results"].items():
        print(f"\n== {name} dopo il segnale   (rendimento medio, QQQ nello stesso periodo, extra vs QQQ, % volte meglio di QQQ)")
        for x in rows:
            print(f"  {x['band']:15} n={x['n']:6}  titolo {x['ret']:+6.2f}%  QQQ {x['qqq']:+6.2f}%  extra {x['excess']:+6.2f}%"
                  f"  (mediana {x['excessMedian']:+6.2f}%)  batte QQQ {x['beat']:5.1f}%  vs tutti {x['vsAll']:+6.2f}")
    print("\n== extra-rendimento medio a 3 mesi vs QQQ, per anno")
    print("  anno  " + "  ".join(f"{b[:10]:>10}" for b in BANDS) + "       tutti")
    for y in r["byYear"]:
        print(f"  {y['year']}  " + "  ".join(f"{y[b]:+10.2f}" if y[b] is not None else f"{'—':>10}" for b in BANDS) + f"  {y['all']:+10.2f}")


if __name__ == "__main__":
    print_report(run())
