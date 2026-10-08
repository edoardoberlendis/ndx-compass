"""Momentum rules on ETF categories (plan phase 24, step 2): are they worth anything? Tested like the patterns of
phase 11, with every rule and condition fixed BEFORE looking at the results (approved by the user on 8 Oct 2026).

    .venv/bin/python etf_backtest.py        # ~1 minute, writes reports/etf_momentum.json

History: US ETFs (adjusted closes in USD, dividends included) used only as long price histories of each category,
never as products to buy. A category enters the test when it has 13 months of history (young themes enter late).
Observations once a month (first session of the month), from the first month with at least 15 categories, to the
last month with 6 full months after it.

Rules:
- M1: return from 12 months ago to 1 month ago (252 -> 21 sessions) in the best third of the categories that month;
- M2: price above its 200-day average.
Measure: the category's return 3 months later (63 sessions) minus the average of all categories that month
("extra vs tutte le categorie"). A rule passes only if, on that extra:
  1. the 3-month mean is at least +0.5 points;   2. the 3-month median is above 0;
  3. the 3-month mean is positive in at least 2/3 of the years with at least 10 cases;
  4. the 3-month mean is positive both in the first and in the second half of the period;
  5. the 6-month mean is not negative;           6. there are at least 100 cases.
Random control: 200 fake rules that pick categories at random with the same frequency each month; if more than 5%
of them pass all six conditions, the conditions are too easy (reported before the real results).
M2 extra measure (fixed before the test): holding a category only when M2 says "dentro" (checked monthly, cash at
0% otherwise) against holding it always, on every category with at least 5 years of history. M2 "reduces losses
in crashes (verified)" only if the maximum drawdown is reduced by at least one third in at least 2/3 of those
categories AND the volatility is lower in at least 2/3 of them. That alone never means "favorevole adesso".
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "reports", "etf_momentum.json")

# one US ETF per category, fixed before the test (the plan's list plus the proxies of the approved themes and countries)
CATEGORIES = {
    "Mondo": "ACWI", "USA": "SPY", "USA Nasdaq-100": "QQQ", "Europa": "VGK", "Eurozona": "EZU", "Italia": "EWI",
    "Giappone": "EWJ", "Emergenti": "EEM", "Cina": "FXI", "India": "INDA", "Corea del Sud": "EWY", "Taiwan": "EWT",
    "Brasile": "EWZ", "Messico": "EWW", "Regno Unito": "EWU", "Svizzera": "EWL", "Germania": "EWG",
    "Tecnologia": "XLK", "Semiconduttori": "SMH", "Sanità": "XLV", "Finanziari": "XLF", "Energia": "XLE",
    "Beni di prima necessità": "XLP", "Industriali": "XLI", "Utility": "XLU", "Difesa": "ITA", "Energia pulita": "ICLN",
    "Valore": "IWD", "Qualità": "QUAL", "Momentum": "MTUM", "Bassa volatilità": "USMV", "Dividendi": "DVY",
    "Small cap": "IWM", "USA equal weight": "RSP", "Governativi brevi": "SHY", "Governativi lunghi": "TLT",
    "Inflazione": "TIP", "Corporate": "LQD", "Oro": "GLD", "Argento": "SLV", "Materie prime": "DBC",
    "Uranio e nucleare": "URA", "Intelligenza artificiale": "AIQ", "Robotica e automazione": "BOTZ",
    "Cybersicurezza": "HACK", "Spazio": "UFO", "Infrastrutture": "IGF",
}
NOT_TESTABLE = {"Idrogeno": "nessun ETF americano con una storia lunga", "Chip di memoria": "nessun ETF americano con una storia lunga"}
H3, H6 = 63, 126
MIN_CATEGORIES, MIN_HISTORY = 15, 253
RANDOM_RUNS = 200
CONDITIONS = [
    "la media dell'extra a 3 mesi è almeno +0,5 punti",
    "la mediana dell'extra a 3 mesi è sopra 0",
    "la media a 3 mesi è positiva in almeno 2/3 degli anni con almeno 10 casi",
    "la media a 3 mesi è positiva sia nella prima sia nella seconda metà del periodo",
    "a 6 mesi la media dell'extra non è negativa",
    "ci sono almeno 100 casi",
]
DD_CUT, SHARE, MIN_YEARS = 1 / 3, 2 / 3, 5
LIMITS = [
    ("ETF americani come storico", "Le categorie sono misurate con ETF americani in dollari: per un investitore europeo cambiano il cambio e, per le obbligazioni, il mercato (titoli USA invece che europei). Il confronto tra categorie resta indicativo."),
    ("Poche categorie, molto legate", "Le categorie sono circa 45 e molte si muovono insieme (per esempio tecnologia, Nasdaq-100 e semiconduttori): i casi davvero indipendenti sono molti meno di quelli contati."),
    ("Casi sovrapposti", "Ogni mese si misurano i 3 e 6 mesi successivi: le finestre si sovrappongono."),
    ("Un solo lungo ciclo", "La storia comincia nei primi anni 2000: un solo grande ciclo di mercato, con la crisi del 2008 e quella del 2020."),
    ("Nessun costo", "Niente commissioni, spread, tasse o costi di cambio, che con cambi frequenti di categoria pesano."),
    ("Temi giovani", "Le categorie nate da poco (spazio, intelligenza artificiale, robotica…) entrano nel test solo quando hanno storia e pesano poco nei risultati."),
]


def verdict(x3, x6, years, dates):
    """The six conditions on the extra returns (numpy arrays) of one rule."""
    if not len(x3):
        return {"checks": [False] * 6, "pass": False}
    ys = [x3[years == y] for y in np.unique(years)]
    ys = [g for g in ys if len(g) >= 10]
    pos = sum(g.mean() > 0 for g in ys)
    mid = dates.min() + (dates.max() - dates.min()) / 2
    a, b = x3[dates <= mid], x3[dates > mid]
    checks = [bool(x3.mean() >= 0.5), bool(np.median(x3) > 0), bool(ys and pos >= len(ys) * SHARE),
              bool(len(a) and len(b) and a.mean() > 0 and b.mean() > 0), bool(x6.mean() >= 0), bool(len(x3) >= 100)]
    return {"checks": checks, "pass": all(checks), "yearsPositive": int(pos), "yearsCounted": len(ys),
            "firstHalf": float(a.mean()) if len(a) else None, "secondHalf": float(b.mean()) if len(b) else None}


def drawdown(r):
    v = (1 + r).cumprod()
    return float((v / v.cummax() - 1).min() * 100)


def run(prices=None):
    t0 = time.time()
    if prices is None:
        import yfinance as yf
        raw = yf.download(list(CATEGORIES.values()), period="max", interval="1d", auto_adjust=True, progress=False)["Close"]
        prices = raw.rename(columns={v: k for k, v in CATEGORIES.items()})
    px = prices.dropna(how="all").sort_index()
    nbars = px.notna().cumsum()
    months = px.index.to_series().groupby([px.index.year, px.index.month]).first().values
    obs = [d for d in months if (nbars.loc[d] >= MIN_HISTORY).sum() >= MIN_CATEGORIES]
    pos = {d: i for i, d in enumerate(px.index)}
    arr = px.to_numpy()
    rows = []
    sma200 = px.rolling(200).mean()
    for d in obs:
        i = pos[d]
        if i + H6 >= len(px):
            break
        ok = (nbars.loc[d] >= MIN_HISTORY) & px.iloc[i].notna() & px.iloc[i + H6].notna()
        cats = [c for c in px.columns if ok[c]]
        mom = {c: arr[i - 21, px.columns.get_loc(c)] / arr[i - 252, px.columns.get_loc(c)] - 1 for c in cats}
        cut = np.quantile(list(mom.values()), 2 / 3)
        r3 = {c: (arr[i + H3, px.columns.get_loc(c)] / arr[i, px.columns.get_loc(c)] - 1) * 100 for c in cats}
        r6 = {c: (arr[i + H6, px.columns.get_loc(c)] / arr[i, px.columns.get_loc(c)] - 1) * 100 for c in cats}
        a3, a6 = np.mean(list(r3.values())), np.mean(list(r6.values()))
        for c in cats:
            rows.append({"date": d, "cat": c, "m1": mom[c] >= cut, "m2": bool(px.loc[d, c] > sma200.loc[d, c]),
                         "x3": r3[c] - a3, "x6": r6[c] - a6, "r3": r3[c]})
    df = pd.DataFrame(rows)
    dates = df["date"].to_numpy()
    years = pd.DatetimeIndex(df["date"]).year.to_numpy()
    out_rules = {}
    for rule in ("m1", "m2"):
        m = df[rule].to_numpy()
        v = verdict(df["x3"].to_numpy()[m], df["x6"].to_numpy()[m], years[m], dates[m])
        out_rules[rule] = {"n": int(m.sum()), "categories": int(df.loc[m, "cat"].nunique()), "mean3": float(df["x3"][m].mean()),
                           "median3": float(df["x3"][m].median()), "mean6": float(df["x6"][m].mean()),
                           "beatAll": float((df["x3"][m] > 0).mean() * 100), "share": float(m.mean()), **v,
                           "byYear": [{"year": int(y), "n": int(((years == y) & m).sum()),
                                       "mean3": float(df["x3"][(years == y) & m].mean()) if ((years == y) & m).any() else None}
                                      for y in np.unique(years)]}
    # random control: the same share of categories picked at random each month
    control = {}
    for rule in ("m1", "m2"):
        share = df.groupby("date")[rule].mean()
        passed, each = 0, np.zeros(6, int)
        for seed in range(RANDOM_RUNS):
            rng = np.random.default_rng(1000 + seed)
            pick = np.zeros(len(df), bool)
            for d, idx in df.groupby("date").indices.items():
                k = int(round(share[d] * len(idx)))
                pick[rng.choice(idx, size=k, replace=False)] = True
            v = verdict(df["x3"].to_numpy()[pick], df["x6"].to_numpy()[pick], years[pick], dates[pick])
            passed += v["pass"]
            each += np.array(v["checks"])
        control[rule] = {"runs": RANDOM_RUNS, "passed": int(passed), "passedPct": passed / RANDOM_RUNS * 100,
                         "passedEach": [int(x) for x in each], "tooEasy": passed / RANDOM_RUNS > 0.05}
    # M2: maximum drawdown and volatility when "dentro" against always held (monthly check, cash at 0% otherwise)
    dd_rows = []
    rets = px.pct_change()
    for c in px.columns:
        s = px[c].dropna()
        if len(s) < MIN_YEARS * 252 + 200:
            continue
        ma = s.rolling(200).mean()
        first = ma.first_valid_index()
        s, ma = s.loc[first:], ma.loc[first:]
        r = rets[c].loc[first:].fillna(0)
        month_start = s.index.to_series().groupby([s.index.year, s.index.month]).transform("first")
        signal_at = (s > ma).reindex(month_start.values).to_numpy()   # the signal of the first session of the month
        held = pd.Series(signal_at, index=s.index).shift(1).fillna(False).astype(bool)   # act from the next session
        strat = r.where(held, 0.0)
        dd_b, dd_s = drawdown(r), drawdown(strat)
        vol_b, vol_s = float(r.std() * np.sqrt(252) * 100), float(strat.std() * np.sqrt(252) * 100)
        dd_rows.append({"cat": c, "years": round(len(s) / 252, 1), "ddHold": dd_b, "ddRule": dd_s, "volHold": vol_b, "volRule": vol_s,
                        "ddCut": bool(dd_s >= dd_b * (1 - DD_CUT)), "volLower": bool(vol_s < vol_b),
                        "retHold": float(((1 + r).prod() ** (252 / len(r)) - 1) * 100), "retRule": float(((1 + strat).prod() ** (252 / len(r)) - 1) * 100),
                        "timeIn": float(held.mean() * 100)})
    n_dd = len(dd_rows)
    dd_ok = sum(x["ddCut"] for x in dd_rows) >= n_dd * SHARE
    vol_ok = sum(x["volLower"] for x in dd_rows) >= n_dd * SHARE
    report = {
        "generated": datetime.now().isoformat(timespec="seconds"), "from": str(pd.Timestamp(dates.min()).date()), "to": str(pd.Timestamp(dates.max()).date()),
        "observations": int(len(df)), "months": int(df["date"].nunique()), "categories": CATEGORIES, "notTestable": NOT_TESTABLE,
        "conditions": CONDITIONS, "rules": out_rules, "control": control,
        "m2Protection": {"categories": dd_rows, "n": n_dd, "ddCutCount": int(sum(x["ddCut"] for x in dd_rows)),
                         "volLowerCount": int(sum(x["volLower"] for x in dd_rows)), "ddOk": bool(dd_ok), "volOk": bool(vol_ok),
                         "verified": bool(dd_ok and vol_ok),
                         "rule": "massima perdita ridotta di almeno un terzo in almeno 2/3 delle categorie con almeno 5 anni di storia, e volatilità più bassa in almeno 2/3"},
        "limits": [{"title": a, "text": b} for a, b in LIMITS], "elapsed": round(time.time() - t0, 1),
    }
    with open(OUT, "w") as f:
        json.dump(report, f, ensure_ascii=False, default=str)
    return report


if __name__ == "__main__":
    r = run()
    print(json.dumps({k: r[k] for k in ("from", "to", "observations", "months", "control")}, ensure_ascii=False))
