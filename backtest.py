"""Backtest of the technical part of the final signal (plan phase 8).

Every STEP trading days over the last ~10 years it recomputes, for each of TODAY's Nasdaq-100 stocks,
the same technical score the dashboard uses (signals.metrics: 20/40/60-day averages, RSI, strength vs
QQQ), puts it in the same bands as the final signal (score.level: Molto positivo … Molto negativo) and
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
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

import market_calendar
import score
import signals
from server import ET, ROOT, clean, download, load_constituents

BENCH = signals.BENCH                 # QQQ
MAS = signals.MAS                     # (20, 40, 60)
HORIZONS = {"1M": 21, "3M": 63, "6M": 126}
STEP = 5                              # one observation per stock per week
YEARS = "10y"
BANDS = ["Molto positivo", "Positivo", "Neutro", "Negativo", "Molto negativo"]
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


# ================================================================ technical patterns (plan phase 11)
# Which bullish technical patterns were followed by better returns than the average stock ON THE SAME DAY?
# Everything below (pattern rules, the "favourable" rule, the random control) was fixed BEFORE looking at the results
# and must not be tuned afterwards.
#
#     .venv/bin/python backtest.py --patterns     # ~1 min, writes reports/patterns.json (backtest.json is not touched)

PATTERNS_OUT = os.path.join(ROOT, "reports", "patterns.json")
P_START = "2015-10-01"       # the patterns look back 252 sessions: one more year of history than the trend backtest
P_FIRST_CASE = "2017-01-01"
P_HIST = 252                 # sessions of history a stock needs before its first case
P_PAUSE = 20                 # event patterns: sessions of silence for the same stock after a counted case
P_VOL = 1.5                  # "with volume": day volume >= 1.5 × the average of the 50 sessions before
P_RANDOM_RUNS = 200

PATTERNS = [
    {"key": "high52", "kind": "evento", "name": "Nuovo massimo a 52 settimane con volumi",
     "rule": "La chiusura supera il massimo delle 252 sedute precedenti (circa un anno) e il volume del giorno è almeno "
             "1,5 volte la media delle 50 sedute precedenti."},
    {"key": "near52", "kind": "stato", "name": "Vicino al massimo a 52 settimane",
     "rule": "La chiusura è entro il 5% dal massimo delle ultime 252 sedute."},
    {"key": "mom12_1", "kind": "stato", "name": "Momentum 12 mesi escluso l'ultimo",
     "rule": "Il rendimento da 12 mesi fa a 1 mese fa (252 → 21 sedute fa) è nel 20% migliore dei titoli quella settimana."},
    {"key": "pull50", "kind": "evento", "name": "Ritracciamento sulla media 50 in salita",
     "rule": "La media a 50 giorni è più alta di 10 sedute prima, il prezzo è sopra la media a 200 giorni, la chiusura è "
             "tra 0% e +2% sopra la media 50 e in almeno una delle 20 sedute precedenti era almeno il 5% sopra la media 50."},
    {"key": "range_break", "kind": "evento", "name": "Uscita da una fase laterale",
     "rule": "Nelle 30 sedute precedenti il massimo delle chiusure è al più il 12% sopra il minimo; oggi la chiusura "
             "supera quel massimo con un volume di almeno 1,5 volte la media delle 50 sedute precedenti."},
    {"key": "golden", "kind": "evento", "name": "Golden cross 50/200",
     "rule": "La media a 50 giorni passa sopra la media a 200 giorni (ieri era sotto o uguale)."},
    {"key": "leader", "kind": "evento", "name": "Leader di momentum",
     "rule": "Lo stesso setup «Leader di momentum» di signals.py (era nella vecchia scheda Idee): prezzo sopra le medie 20 > 40 > 60, almeno 4 punti "
             "meglio di QQQ in un mese, RSI tra 55 e 72, non più del 6% sopra la media 20."},
    {"key": "pullback", "kind": "evento", "name": signals.SETUP_PULLBACK,
     "rule": "Lo stesso setup «Ritracciamento in trend rialzista» di signals.py (era nella vecchia scheda Idee): prezzo sopra le medie 40 > 60 in "
             "salita, tornato vicino alla media 20 (da −1,5% a +2,5%), RSI tra 38 e 62."},
    {"key": "bull_x", "kind": "evento", "name": signals.SETUP_BULL_X,
     "rule": "Lo stesso setup «Incrocio rialzista» di signals.py (era nella vecchia scheda Idee): la media 20 ha superato la media 60 nelle ultime 5 "
             "sedute, prezzo sopra la media 20, volumi non in calo."},
]
SIGNALS_SETUPS = {"leader": "Leader di momentum", "pullback": signals.SETUP_PULLBACK, "bull_x": signals.SETUP_BULL_X}

P_RULE = [
    "la media dell'extra a 3 mesi è almeno +0,5 punti",
    "la mediana dell'extra a 3 mesi è sopra 0",
    "la media a 3 mesi è positiva in almeno 6 anni (contano solo gli anni con almeno 20 casi)",
    "la media a 3 mesi è positiva sia nel 2017–2021 sia nel 2022–2026",
    "a 6 mesi la media dell'extra non è negativa",
    "ci sono almeno 100 casi",
]

P_LIMITS = [
    ("Survivorship bias residuo",
     "Il test usa i titoli che sono nel Nasdaq-100 OGGI: mancano quelli usciti perché sono crollati e ci sono quelli entrati "
     "perché sono saliti molto. Il confronto con «tutti i titoli nello stesso giorno» toglie il vantaggio comune a tutti, ma "
     "non quello specifico dei pattern di forza (massimi, momentum): chi era forte e poi è crollato è uscito dall'indice e "
     "qui non si vede. I pattern di forza sono quindi ancora favoriti."),
    ("Test multipli",
     "Sono stati provati 9 pattern insieme: anche se nessuno funzionasse davvero, qualcuno potrebbe superare le condizioni "
     "per caso. Il controllo casuale dice quanto spesso succede a un pattern finto."),
    ("Casi sovrapposti",
     "I rendimenti coprono 1, 3 o 6 mesi e i casi sono vicini nel tempo (nei pattern di tipo «stato» lo stesso titolo "
     "compare ogni settimana): le osservazioni davvero indipendenti sono molte meno del numero di casi."),
    ("Nessun costo",
     "Non ci sono commissioni, spread, tasse né slittamenti di prezzo. I prezzi sono rettificati per dividendi e frazionamenti."),
    ("Un solo tipo di mercato",
     "Dal 2017 a oggi il mercato è stato soprattutto rialzista e guidato dalla tecnologia, con un solo anno negativo "
     "importante (2022). Non sappiamo come si comportano questi pattern in un lungo mercato ribassista."),
]


def _wide(frames, index, col):
    """One column per stock on the QQQ calendar (rows before a stock's listing are empty)."""
    return pd.DataFrame({t: df[col] for t, df in frames.items()}).reindex(index)


def _rsi_wide(C, n=14):
    """signals.rsi for every stock and day: EWM (adjust=False) over the last 3n daily changes only."""
    d = C.diff().to_numpy()
    win = np.lib.stride_tricks.sliding_window_view(d, n * 3, axis=0)        # (days − 41, stocks, 42)
    up, dn = np.clip(win[..., 0], 0, None), -np.clip(win[..., 0], None, 0)
    for j in range(1, win.shape[-1]):
        up = (1 - 1 / n) * up + np.clip(win[..., j], 0, None) / n
        dn = (1 - 1 / n) * dn - np.clip(win[..., j], None, 0) / n
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(dn == 0, 100.0, 100 - 100 / (1 + up / dn))
    r[np.isnan(up)] = np.nan
    out = np.full(C.shape, np.nan)
    out[n * 3 - 1:] = r
    return pd.DataFrame(out, index=C.index, columns=C.columns)


def setup_labels(C, H, L, V, bench):
    """The setup signals.classify() would give each stock on each day (only its first four rules, in the same order:
    Tirato, Incrocio rialzista, Ritracciamento, Leader), without calling signals.metrics() day by day."""
    s20, s40, s60 = (C.rolling(n).mean() for n in MAS)
    slope40, slope60 = (s40 / s40.shift(5) - 1) * 100, (s60 / s60.shift(5) - 1) * 100
    vs20 = (C / s20 - 1) * 100
    bull = (C > s20) & (s20 > s40) & (s40 > s60)
    rsi = _rsi_wide(C)
    b = bench.reindex(C.index).ffill()
    rs1m = ((C / C.shift(21) - 1) * 100).sub((b / b.shift(21) - 1) * 100, axis=0)
    v60 = V.rolling(60, min_periods=1).mean()
    vol_ratio = (V.rolling(20, min_periods=1).mean() / v60).where(v60 > 0, 0)
    sg = np.sign(s20 - s60)
    x_up = (sg != sg.shift(5)) & (sg > 0) & sg.shift(5).notna()             # signals.crossed(sma20, sma60) == 1
    pc = C.shift()
    tr = np.fmax(H - L, np.fmax((H - pc).abs(), (L - pc).abs()))
    has_levels = ~(tr.rolling(14).mean() == 0)                              # signals.levels() is None only when ATR is 0

    rules = [   # same order as signals.classify: the first matching rule wins
        (signals.SETUP_EXTENDED, bull & ((vs20 > 8) | (rsi > 75))),         # no levels needed for this one
        (signals.SETUP_BULL_X, x_up & (C > s20) & (vol_ratio >= 0.95)),
        (signals.SETUP_PULLBACK, (C > s40) & (s40 > s60) & (s20 > s60) & (slope40 > 0) & (slope60 > 0)
         & (vs20 >= -1.5) & (vs20 <= 2.5) & (rsi >= 38) & (rsi <= 62)),
        ("Leader di momentum", bull & (rs1m > 4) & (rsi >= 55) & (rsi <= 72) & (vs20 <= 6)),
    ]
    lab = np.full(C.shape, "", dtype=object)                                # "" = none of these setups
    for name, cond in reversed(rules):
        lab[cond.to_numpy(bool)] = name
    lab[~has_levels.to_numpy(bool) & (lab != signals.SETUP_EXTENDED)] = ""
    return pd.DataFrame(lab, index=C.index, columns=C.columns)


def check_setups(frames, bench, lab, hist_ok, n_random=2000, n_each=500):
    """Compare setup_labels with signals.metrics + signals.classify on random (stock, day) pairs and on random days
    of each of the three tested setups. Returns (pairs compared, list of differences): the list must be empty."""
    rnd = random.Random(11)
    names = set(SIGNALS_SETUPS.values()) | {signals.SETUP_EXTENDED}
    arr = lab.to_numpy()
    ok = np.argwhere(hist_ok)
    pairs = [tuple(ok[i]) for i in rnd.sample(range(len(ok)), n_random)]
    for name in SIGNALS_SETUPS.values():
        hits = np.argwhere((arr == name) & hist_ok)
        pairs += [tuple(hits[i]) for i in rnd.sample(range(len(hits)), min(n_each, len(hits)))]
    bad = []
    for i, j in pairs:
        t, day = lab.columns[j], lab.index[i]
        m = signals.metrics(frames[t].loc[:day], bench)
        cls = signals.classify(m) if m else None
        ref = cls[0] if cls and cls[2] is not None and cls[0] in names else ""
        if ref != arr[i, j]:
            bad.append({"ticker": t, "date": str(day.date()), "signals": ref, "backtest": arr[i, j]})
    return len(pairs), bad


def pattern_states(C, H, L, V, bench):
    """{pattern key: days × stocks table, True where the pattern's condition holds that day} (past data only)."""
    vol50 = V.shift(1).rolling(50).mean()
    hi_vol = (V >= P_VOL * vol50) & (vol50 > 0)
    sma50, sma200 = C.rolling(50).mean(), C.rolling(200).mean()
    d50 = C / sma50 - 1
    mom = C.shift(21) / C.shift(252) - 1
    hi30, lo30 = C.shift(1).rolling(30).max(), C.shift(1).rolling(30).min()
    st = {
        "high52": (C > C.shift(1).rolling(252).max()) & hi_vol,
        "near52": C >= 0.95 * C.rolling(252).max(),
        "mom12_1": mom.ge(mom.quantile(0.8, axis=1), axis=0),
        "pull50": (sma50 > sma50.shift(10)) & (C > sma200) & (d50 >= 0) & (d50 <= 0.02)
                  & (d50.shift(1).rolling(20).max() >= 0.05),
        "range_break": (hi30 / lo30 - 1 <= 0.12) & (C > hi30) & hi_vol,
        "golden": (sma50 > sma200) & (sma50.shift(1) <= sma200.shift(1)),
    }
    lab = setup_labels(C, H, L, V, bench)
    for key, name in SIGNALS_SETUPS.items():
        st[key] = lab == name
    return st, lab


def _events(state, allowed):
    """Event patterns: only the first day (true today, false yesterday), then P_PAUSE sessions of silence for that stock."""
    s = np.asarray(state, dtype=bool)
    onset = s & allowed
    onset[1:] &= ~s[:-1]
    out = np.zeros_like(s)
    for j in range(s.shape[1]):
        last = -10 ** 9
        for i in np.flatnonzero(onset[:, j]):
            if i - last > P_PAUSE:
                out[i, j], last = True, i
    return out


def _verdict(x3, x6, years):
    """The six fixed conditions on the extra return vs all stocks on the same day (x3: 3 months, x6: 6 months)."""
    if not len(x3):
        return {"checks": [False] * 6, "favorable": False, "yearsPositive": 0, "yearsCounted": 0, "early": None, "late": None}
    ys = [x3[years == y] for y in np.unique(years)]
    ys = [g for g in ys if len(g) >= 20]
    pos = sum(g.mean() > 0 for g in ys)
    early, late = x3[years <= 2021], x3[years >= 2022]
    checks = [bool(x3.mean() >= 0.5), bool(np.median(x3) > 0), bool(pos >= 6),
              bool(len(early) and len(late) and early.mean() > 0 and late.mean() > 0),
              bool(x6.mean() >= 0), bool(len(x3) >= 100)]
    return {"checks": checks, "favorable": all(checks), "yearsPositive": int(pos), "yearsCounted": len(ys),
            "early": float(early.mean()) if len(early) else None, "late": float(late.mean()) if len(late) else None}


def run_patterns(data=None):
    t0 = time.time()
    tickers = [c["ticker"] for c in load_constituents()]
    if data is None:
        data = download(tickers + [BENCH], start=P_START, interval="1d")
    bench = data[BENCH]["Close"].dropna()
    frames = {t: data[t].dropna(subset=["Close"]) for t in tickers if t in data}
    now = datetime.now(ET)
    if bench.index[-1].date() == now.date() and now.hour * 60 + now.minute < market_calendar.close_minute(now):
        bench = bench.iloc[:-1]         # session still open: the test uses closed sessions only
        frames = {t: df[df.index <= bench.index[-1]] for t, df in frames.items()}
    for t, df in frames.items():        # the tables below assume every stock trades on every QQQ day after its listing
        if not df.index.equals(bench.index[bench.index >= df.index[0]]):
            raise SystemExit(f"{t}: giorni di borsa diversi da QQQ, il calcolo veloce non è affidabile")
    C, H, L, V = (_wide(frames, bench.index, col) for col in ("Close", "High", "Low", "Volume"))
    states, lab = pattern_states(C, H, L, V, bench)

    c, q = C.to_numpy(), bench.to_numpy()
    days, years = bench.index, bench.index.year.to_numpy()
    nbars = np.cumsum(~np.isnan(c), axis=0) - 1                              # position of the day in the stock's own history
    hist_ok = (nbars >= P_HIST + 1) & ~np.isnan(c) & (days >= P_FIRST_CASE)[:, None]   # +1: yesterday is computable too
    max_h = max(HORIZONS.values())
    fut_ok = np.zeros_like(hist_ok)
    fut_ok[:-max_h] = ~np.isnan(c[max_h:])                                   # the full 6 months after are known
    base = hist_ok & fut_ok
    weekly = np.zeros(len(days), dtype=bool)
    weekly[::STEP] = True

    n_checked, bad = check_setups(frames, bench, lab, hist_ok)
    if bad:
        print(f"STOP: {len(bad)} differenze su {n_checked} confronti con signals.py (prime 10):")
        for b in bad[:10]:
            print("  ", b)
        raise SystemExit(1)

    R, Q, X = {}, {}, {}        # stock return, QQQ return, extra vs the average of all stocks that day (percent)
    for name, hz in HORIZONS.items():
        r = np.full(c.shape, np.nan)
        r[:-hz] = (c[hz:] / c[:-hz] - 1) * 100
        qq = np.full(len(q), np.nan)
        qq[:-hz] = (q[hz:] / q[:-hz] - 1) * 100
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)             # days with no eligible stock: empty average
            avg = np.nanmean(np.where(base, r, np.nan), axis=1)
        R[name], Q[name], X[name] = r, qq, r - avg[:, None]

    def stats(mask):
        ii, jj = np.nonzero(mask)
        yy = years[ii]
        out = {"n": int(len(ii)), "tickers": int(len(set(jj))), "horizons": {}, "byYear": []}
        for name in HORIZONS:
            r, qq, x = R[name][ii, jj], Q[name][ii], X[name][ii, jj]
            e = r - qq
            out["horizons"][name] = {
                "ret": float(r.mean()), "retMedian": float(np.median(r)), "qqq": float(qq.mean()),
                "excess": float(e.mean()), "excessMedian": float(np.median(e)), "beat": float((e > 0).mean() * 100),
                "vsAll": float(x.mean()), "vsAllMedian": float(np.median(x)), "beatAll": float((x > 0).mean() * 100),
            } if len(ii) else None
        for y in np.unique(years[hist_ok.any(axis=1) & fut_ok.any(axis=1)]):
            k = yy == y
            row = {"year": int(y), "n": int(k.sum())}
            for name in HORIZONS:
                row[f"vsAll{name}"] = float(X[name][ii, jj][k].mean()) if k.any() else None
                row[f"excess{name}"] = float((R[name][ii, jj] - Q[name][ii])[k].mean()) if k.any() else None
            out["byYear"].append(row)
        out.update(_verdict(X["3M"][ii, jj], X["6M"][ii, jj], yy))
        return out

    patterns, masks = [], {}
    for p in PATTERNS:
        s = states[p["key"]].to_numpy(bool)
        m = (_events(s, hist_ok) if p["kind"] == "evento" else s & hist_ok & weekly[:, None]) & fut_ok
        masks[p["key"]] = m
        patterns.append({**p, **stats(m)})
    everything = stats(base)

    # random control: a fake event pattern that picks stocks at random, as often as the real event patterns on average
    n_target = float(np.mean([m.sum() for p, m in zip(PATTERNS, masks.values()) if p["kind"] == "evento"]))
    f = n_target / base.sum()
    prob = f / (1 - P_PAUSE * f)                    # the pause removes some picks: draw a little more often
    runs = []
    for seed in range(P_RANDOM_RUNS):
        draw = np.random.default_rng(seed).random(c.shape) < prob
        ii, jj = np.nonzero(_events(draw, hist_ok) & fut_ok)
        v = _verdict(X["3M"][ii, jj], X["6M"][ii, jj], years[ii])
        runs.append({"seed": seed, "n": int(len(ii)), "vsAll3M": float(X["3M"][ii, jj].mean()), **v})
    passed = sum(r["favorable"] for r in runs)
    control = {
        "runs": P_RANDOM_RUNS, "casesTarget": round(n_target), "casesMean": float(np.mean([r["n"] for r in runs])),
        "passed": int(passed), "passedPct": passed / P_RANDOM_RUNS * 100,
        "passedEach": [int(sum(r["checks"][k] for r in runs)) for k in range(6)],
        "vsAll3M": {k: float(np.percentile([r["vsAll3M"] for r in runs], pc)) for k, pc in (("p5", 5), ("p50", 50), ("p95", 95))},
        "tooEasy": passed / P_RANDOM_RUNS > 0.05,
    }

    case_days = days[base.any(axis=1)]
    report = {
        "generated": datetime.now(ET).isoformat(timespec="seconds"),
        "from": str(case_days[0].date()), "to": str(case_days[-1].date()), "stocks": int(base.any(axis=0).sum()),
        "horizons": dict(HORIZONS), "stepDays": STEP, "pauseDays": P_PAUSE,
        "rule": P_RULE, "control": control, "patterns": patterns, "all": everything,
        "favorable": [p["key"] for p in patterns if p["favorable"]],
        "signalsCheck": {"compared": n_checked, "different": len(bad)},
        "limits": [{"title": a, "text": b} for a, b in P_LIMITS],
        "elapsed": round(time.time() - t0, 1),
    }
    with open(PATTERNS_OUT, "w") as fh:
        json.dump(report, fh, default=clean, allow_nan=False)
    return report


def patterns_today(data, bench, days=5):
    """For the report (signals.py): the stocks that show each pattern at the last close, with the same rules as the test.
    State patterns: true on the last day. Event patterns: counted (first day, then the pause) in the last `days`
    sessions, with the date. Needs about 2 years of daily history; stocks with less than P_HIST + 2 sessions, or with
    missing days compared with QQQ, are left out."""
    frames = {}
    for t, df in data.items():
        df = df.dropna(subset=["Close"])
        if t != BENCH and len(df) and df.index.equals(bench.index[bench.index >= df.index[0]]):
            frames[t] = df
    C, H, L, V = (_wide(frames, bench.index, col) for col in ("Close", "High", "Low", "Volume"))
    states, _ = pattern_states(C, H, L, V, bench)
    c = C.to_numpy()
    ok = (np.cumsum(~np.isnan(c), axis=0) - 1 >= P_HIST + 1) & ~np.isnan(c)
    stocks = {}
    for p in PATTERNS:
        s = states[p["key"]].to_numpy(bool)
        if p["kind"] == "evento":
            e = _events(s, ok)
            stocks[p["key"]] = [{"ticker": C.columns[j], "date": str(C.index[i].date())}
                                for i in range(len(c) - 1, max(len(c) - 1 - days, -1), -1) for j in np.flatnonzero(e[i])]
        else:
            stocks[p["key"]] = [{"ticker": t} for t in C.columns[s[-1] & ok[-1]]]
    return {"asOf": str(C.index[-1].date()), "days": days, "stocks": stocks}


def print_patterns(r):
    c = r["control"]
    print(f"Pattern {r['from']} → {r['to']} · {r['stocks']} titoli · verifica con signals.py: {r['signalsCheck']['compared']} "
          f"confronti, {r['signalsCheck']['different']} differenze · {r['elapsed']}s")
    print(f"\n== Controllo casuale: {c['runs']} pattern finti (in media {c['casesMean']:.0f} casi, come i pattern evento: {c['casesTarget']})")
    print(f"  superano tutte e 6 le condizioni: {c['passed']} su {c['runs']} ({c['passedPct']:.1f}%)"
          + ("   ← PIÙ DEL 5%: la regola è troppo facile da superare per caso" if c["tooEasy"] else ""))
    print("  superano la singola condizione 1…6: " + "  ".join(f"{k + 1}:{n}" for k, n in enumerate(c["passedEach"])))
    print(f"  extra vs tutti a 3 mesi dei pattern finti: 5° percentile {c['vsAll3M']['p5']:+.2f}, mediana {c['vsAll3M']['p50']:+.2f}, "
          f"95° {c['vsAll3M']['p95']:+.2f}")
    print("\n== Condizioni (sull'extra vs tutti i titoli nello stesso giorno)")
    for k, txt in enumerate(r["rule"]):
        print(f"  {k + 1}. {txt}")
    print(f"\n  {'pattern':40} {'tipo':6} {'casi':>6}  " + " ".join(str(k + 1) for k in range(6)) + "  esito")
    for p in r["patterns"]:
        print(f"  {p['name']:40} {p['kind']:6} {p['n']:6}  " + " ".join("✅" if x else "❌" for x in p["checks"])
              + ("  TEST SUPERATO" if p["favorable"] else "  no"))
    for name in r["horizons"]:
        print(f"\n== {name} dopo il segnale")
        print(f"  {'pattern':40} {'casi':>6} {'tit.':>4} {'rend.':>7} {'median':>7} {'QQQ':>7} {'extraQ':>7} {'medQ':>7} "
              f"{'>QQQ%':>6} {'vsTutti':>7} {'medTut':>7}")
        for p in r["patterns"] + [{**r["all"], "name": "Tutti i titoli (ogni giorno)"}]:
            h = p["horizons"][name]
            if h:
                print(f"  {p['name']:40} {p['n']:6} {p['tickers']:4} {h['ret']:+7.2f} {h['retMedian']:+7.2f} {h['qqq']:+7.2f} "
                      f"{h['excess']:+7.2f} {h['excessMedian']:+7.2f} {h['beat']:6.1f} {h['vsAll']:+7.2f} {h['vsAllMedian']:+7.2f}")
    print("\n== extra vs tutti i titoli a 3 mesi, per anno (tra parentesi il numero di casi; * = meno di 20 casi, non conta)")
    for p in r["patterns"]:
        print(f"  {p['name'][:38]:38} " + " ".join(
            f"{y['year'] % 100:02d}:{y['vsAll3M']:+5.1f}({y['n']}){'*' if y['n'] < 20 else ''}" if y["n"] else f"{y['year'] % 100:02d}:—"
            for y in p["byYear"]) + f"   positivi {p['yearsPositive']}/{p['yearsCounted']}")


if __name__ == "__main__":
    import sys
    if "--patterns" in sys.argv:
        print_patterns(run_patterns())
    else:
        print_report(run())
