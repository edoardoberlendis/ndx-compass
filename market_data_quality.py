"""Controlli di qualità dei dati storici (phase 4A). Reproducible checks on daily price series: they REPORT, they never
correct. The only change ever made to a dataset is apply_verified(), which returns a COPY without the stretches that a
manual review with sources (data_quality_reviews.json) marked as verified errors with exclude=true.

    python market_data_quality.py [prezzi.pkl] [--report report.json] [--salva]

Every issue gets one of four statuses:
    errore    Errore verificato               contradicted by an independent or official source (manual review)
    sospetto  Dato sospetto, non verificato   found by an automatic check, nobody has confirmed it yet
    reale     Movimento reale confermato      an extreme move confirmed by independent news sources (manual review)
    mancante  Dato mancante                   a price, a volume or a session that is not there
An automatic check can only produce "sospetto" or "mancante": only a review with sources gives "errore" or "reale".
"""
from __future__ import annotations

import copy
import glob
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import market_calendar

ROOT = os.path.dirname(os.path.abspath(__file__))
REVIEWS = os.path.join(ROOT, "data_quality_reviews.json")
OUT_DIR = os.path.join(ROOT, "data", "validazione", "qualita")
BENCH = "QQQ"

STATUS = {"errore": "Errore verificato", "sospetto": "Dato sospetto, non verificato",
          "reale": "Movimento reale confermato", "mancante": "Dato mancante"}
JUMP = 40.0            # % in one session: extreme move, to be checked (same threshold as the lab's quality notes)
REVERSAL = 15.0        # % move followed the next session by an opposite move of at least the same size
STALE_RUN = 5          # sessions in a row with the same close and no volume: price not traded
ILLIQUID = 0.5         # share of sessions with zero volume in a calendar year above which the year is "illiquid"
SPLIT_RATIOS = (2, 3, 4, 5, 8, 10, 15, 20)
SPLIT_VOL = 3.0         # an unadjusted split does not move volumes: only days with volume below 3x the median
SPLIT_TOL = 0.03       # a one-day ratio within 3% of a split ratio (or its inverse) looks like an unadjusted split
INFLUENCE = (-35, 95)  # calendar days: a bad price on day d enters the forward returns of the decisions of the 21
                       # sessions before and the indicators (up to 63 sessions) of the decisions after


def load_reviews(path=None):
    try:
        with open(path or REVIEWS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"version": None, "reviews": [], "listings": [], "criteria": []}


def reviews_hash(rev):
    return hashlib.sha256(json.dumps(rev, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def _naive(df):
    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


def _d(ts):
    return pd.Timestamp(ts).date().isoformat()


def _issue(ticker, kind, frm, to=None, status="sospetto", detail="", n=1, value=None):
    return {"ticker": ticker, "kind": kind, "from": frm, "to": to or frm, "status": status, "detail": detail, "n": int(n),
            "value": None if value is None else round(float(value), 2)}


# ---------------------------------------------------------------- the checks

def check_calendar(bench_index, last_day=None):
    """QQQ dates: duplicates, weekends, gaps, and the exact NYSE calendar for the years written in market_calendar."""
    idx = pd.DatetimeIndex(bench_index)
    out = {"duplicates": int(idx.duplicated().sum()), "weekend": int((idx.dayofweek >= 5).sum()),
           "unsorted": bool(not idx.is_monotonic_increasing), "maxGapDays": int(idx.to_series().diff().dt.days.max() or 0)}
    years = sorted(set(d.year for d in market_calendar.HOLIDAYS)) if hasattr(market_calendar, "HOLIDAYS") else []
    exact = {}
    have = set(idx.normalize().date)
    end = idx.max().date() if len(idx) else None
    for y in years:
        start = max(date(y, 1, 1), idx.min().date()) if len(idx) else date(y, 1, 1)
        if end is None or start > end:
            continue
        stop = min(date(y, 12, 31), end)
        want = {start + timedelta(days=k) for k in range((stop - start).days + 1)}
        want = {x for x in want if market_calendar.is_trading_day(x)}
        got = {x for x in have if start <= x <= stop}
        exact[str(y)] = {"missing": sorted(x.isoformat() for x in want - got), "extra": sorted(x.isoformat() for x in got - want)}
    out["nyse"] = exact
    # before the years written by hand: weekdays without a QQQ session per year (NYSE: usually 9-10 holidays)
    per_year = {}
    if len(idx):
        wd = pd.bdate_range(idx.min(), idx.max())
        miss = wd.difference(idx)
        for y in sorted(set(wd.year)):
            if str(y) not in exact:
                per_year[str(y)] = int((miss.year == y).sum())
    out["weekdaysWithoutSession"] = per_year
    return out


def check_series(t, df, cal, listing=None):
    """Issues of one stock (df: Open/High/Low/Close/Volume) against the QQQ calendar."""
    issues = []
    if df is None or len(df) == 0 or "Close" not in df:
        return [_issue(t, "serie assente", None, status="mancante", detail="nessun prezzo")]
    df = _naive(df).sort_index()
    dup = df.index.duplicated()
    if dup.any():
        issues.append(_issue(t, "date duplicate", _d(df.index[dup][0]), _d(df.index[dup][-1]), n=dup.sum()))
        df = df[~dup]
    nan = df["Close"].isna()
    if nan.any():
        issues.append(_issue(t, "prezzi mancanti", _d(df.index[nan][0]), _d(df.index[nan][-1]), "mancante",
                             "chiusura vuota", n=nan.sum()))
    df = df[~nan]
    first = df.index[0]
    own_cal = cal[cal >= first]
    miss = own_cal.difference(df.index)
    extra = df.index.difference(cal)
    if len(miss):
        issues.append(_issue(t, "sedute mancanti rispetto a QQQ", _d(miss[0]), _d(miss[-1]), "mancante",
                             f"{len(miss)} sedute di QQQ senza prezzo del titolo", n=len(miss)))
    if len(extra):
        issues.append(_issue(t, "sedute in più rispetto a QQQ", _d(extra[0]), _d(extra[-1]),
                             detail="giorni con prezzo del titolo ma senza seduta di QQQ", n=len(extra)))
    px = df[[c for c in ("Open", "High", "Low", "Close") if c in df]]
    bad = (px <= 0).any(axis=1)
    if bad.any():
        issues.append(_issue(t, "prezzo nullo o negativo", _d(df.index[bad][0]), _d(df.index[bad][-1]), n=bad.sum()))
    if {"Open", "High", "Low"} <= set(df):
        inc = ((df["High"] < df["Low"]) | (df["Close"] > df["High"] * 1.001) | (df["Close"] < df["Low"] * 0.999)
               | (df["Open"] > df["High"] * 1.001) | (df["Open"] < df["Low"] * 0.999))
        if inc.any():
            issues.append(_issue(t, "apertura, massimo, minimo e chiusura incoerenti", _d(df.index[inc][0]),
                                 _d(df.index[inc][-1]), n=inc.sum()))
        no_open = df["Open"].isna()
        if no_open.any():
            issues.append(_issue(t, "apertura mancante", _d(df.index[no_open][0]), _d(df.index[no_open][-1]), "mancante",
                                 n=no_open.sum()))
    if "Volume" in df:
        v = df["Volume"]
        if (v < 0).any():
            issues.append(_issue(t, "volume negativo", _d(v[v < 0].index[0]), _d(v[v < 0].index[-1]), n=(v < 0).sum()))
        zero = (v <= 0) | v.isna()
        flat = zero & (df["Close"] == df["Close"].shift())
        run = flat.groupby((~flat).cumsum()).cumsum()
        stale_days = run[run >= STALE_RUN].index
        share = zero.groupby(df.index.year).mean()
        illiquid = [int(y) for y, s in share.items() if s > ILLIQUID]
        for y in illiquid:
            m = zero & (df.index.year == y)
            issues.append(_issue(t, "periodo illiquido (volume a zero)", f"{y}-01-01" if df.index[0].year < y else _d(df.index[0]),
                                 _d(df.index[m][-1]), detail=f"{int(m.sum())} sedute su {int((df.index.year == y).sum())} "
                                 f"senza scambi, {int(((df.index.year == y) & flat).sum())} con prezzo fermo", n=m.sum()))
        rest = zero & ~np.isin(df.index.year, illiquid)
        if rest.any():
            issues.append(_issue(t, "volume a zero", _d(df.index[rest][0]), _d(df.index[rest][-1]), "mancante",
                                 "volume mancante in sedute isolate", n=rest.sum()))
        rest_stale = [d for d in stale_days if d.year not in illiquid]
        if rest_stale:
            issues.append(_issue(t, "prezzo fermo senza scambi", _d(rest_stale[0]), _d(rest_stale[-1]),
                                 detail=f"almeno {STALE_RUN} sedute di fila uguali e senza volume", n=len(rest_stale)))
    c = df["Close"]
    r = (c / c.shift() - 1) * 100
    vol_ratio = (df["Volume"] / df["Volume"].rolling(20).median().shift()) if "Volume" in df else None
    for day in r.index[r.abs() > JUMP]:
        i = df.index.get_loc(day)
        nxt = r.iloc[i + 1] if i + 1 < len(r) else np.nan
        vr = float(vol_ratio.iloc[i]) if vol_ratio is not None and np.isfinite(vol_ratio.iloc[i]) else None
        hint = [f"volume {vr:.0f} volte la mediana di 20 sedute" if vr else "volume precedente non disponibile"]
        if np.isfinite(nxt) and abs(nxt) > REVERSAL and np.sign(nxt) != np.sign(r.iloc[i]):
            hint.append(f"il giorno dopo {nxt:+.1f}% (inversione)")
        issues.append(_issue(t, "variazione estrema", _d(day), detail="; ".join(hint), value=r.iloc[i]))
    ratio = c / c.shift()
    for day in ratio.index[(r.abs() > 25)]:
        x = ratio[day]
        vr = vol_ratio[day] if vol_ratio is not None else np.nan
        if np.isfinite(vr) and vr >= SPLIT_VOL:
            continue
        for k in SPLIT_RATIOS:
            if abs(x * k - 1) < SPLIT_TOL or abs(x / k - 1) < SPLIT_TOL:
                issues.append(_issue(t, "possibile frazionamento non rettificato", _d(day),
                                     detail=f"prezzo moltiplicato per {x:.3f}, vicino al rapporto {k}", value=r[day]))
                break
    for day in r.index[(r.abs() > REVERSAL) & (r.abs() <= JUMP)]:
        i = df.index.get_loc(day)
        if i + 1 < len(r) and abs(r.iloc[i + 1]) > REVERSAL and np.sign(r.iloc[i + 1]) != np.sign(r.iloc[i]) \
                and abs(r.iloc[i + 1]) <= JUMP:
            issues.append(_issue(t, "inversione", _d(day), _d(df.index[i + 1]),
                                 detail=f"{r.iloc[i]:+.1f}% e poi {r.iloc[i + 1]:+.1f}%", value=r.iloc[i]))
    if listing and listing.get("regular") and first < pd.Timestamp(listing["regular"]):
        issues.append(_issue(t, "prezzi prima della quotazione regolare", _d(first),
                             (pd.Timestamp(listing["regular"]) - pd.Timedelta(days=1)).date().isoformat(),
                             detail=listing.get("note", ""), n=int((df.index < pd.Timestamp(listing["regular"])).sum())))
    return issues


def apply_reviews(issues, rev):
    """Status from the manual reviews: an issue overlapping a reviewed stretch of the same stock takes its status."""
    for x in issues:
        if not x["from"]:
            continue
        for r in rev.get("reviews", []):
            if r["ticker"] == x["ticker"] and r["from"] <= x["to"] and x["from"] <= r["to"]:
                if x["status"] == "mancante" and r["status"] == "reale":
                    continue
                x["status"] = r["status"]
                x["review"] = {"note": r["note"], "sources": r.get("sources", []), "exclude": bool(r.get("exclude"))}
                break
    return issues


def check(data, tickers, as_of=None, reviews=None, saved_at=None):
    """The full report on a dataset (no change to it). as_of: the day of the calculation: no row may come after it."""
    rev = reviews if reviews is not None else load_reviews()
    out = {"reviewsVersion": rev.get("version"), "reviewsHash": reviews_hash(rev), "criteria": rev.get("criteria", []),
           "thresholds": {"JUMP": JUMP, "REVERSAL": REVERSAL, "STALE_RUN": STALE_RUN, "ILLIQUID": ILLIQUID,
                          "SPLIT_TOL": SPLIT_TOL, "SPLIT_VOL": SPLIT_VOL}}
    b = data.get(BENCH)
    if b is None or len(b) == 0:
        out["benchmark"] = {"available": False}
        out["issues"] = [_issue(BENCH, "benchmark assente", None, status="mancante")]
        return out
    b = _naive(b).sort_index()
    cal = b.dropna(subset=["Close"]).index
    out["benchmark"] = {"available": True, "ticker": BENCH, "from": _d(cal[0]), "to": _d(cal[-1]), "sessions": len(cal),
                        "missingClose": int(b["Close"].isna().sum())}
    out["calendar"] = check_calendar(b.index)
    limit = pd.Timestamp(as_of) if as_of else None
    future = []
    for t in [BENCH] + list(tickers):
        df = data.get(t)
        if df is not None and len(df) and limit is not None and _naive(df).index.max() > limit:
            future.append({"ticker": t, "last": _d(_naive(df).index.max())})
    out["future"] = {"asOf": as_of, "savedAt": saved_at, "rows": future}
    listings = {x["ticker"]: x for x in rev.get("listings", [])}
    issues = check_series(BENCH, b, cal)
    issues = [i for i in issues if i["kind"] not in ("sedute mancanti rispetto a QQQ", "sedute in più rispetto a QQQ")]
    for t in tickers:
        issues += check_series(t, data.get(t), cal, listings.get(t))
    issues += [_issue(f["ticker"], "dati dopo la data del calcolo", f["last"], detail=f"ultima riga {f['last']}, calcolo del {as_of}")
               for f in future]
    issues = apply_reviews(issues, rev)
    for r in rev.get("reviews", []):      # a review with no automatic warning on its days is shown as well
        if r["ticker"] in tickers and not any(x["ticker"] == r["ticker"] and x.get("review") and x["from"] <= r["to"]
                                              and r["from"] <= x["to"] for x in issues):
            issues.append({**_issue(r["ticker"], "revisione manuale", r["from"], r["to"], r["status"]),
                           "review": {"note": r["note"], "sources": r.get("sources", []), "exclude": bool(r.get("exclude"))}})
    out["issues"] = issues
    out["counts"] = {k: sum(1 for i in out["issues"] if i["status"] == k) for k in STATUS}
    out["tickers"] = len(tickers)
    return out


def impact(issues, segments):
    """Which period of a study each issue can influence. segments: {name: {"from", "to", "sealed"}} of a lab report."""
    out = []
    for x in issues:
        if not x["from"]:
            out.append({**x, "periods": ["tutta la serie"]})
            continue
        a = (pd.Timestamp(x["from"]) + pd.Timedelta(days=INFLUENCE[0])).date().isoformat()
        z = (pd.Timestamp(x["to"]) + pd.Timedelta(days=INFLUENCE[1])).date().isoformat()
        hit = [n for n, s in segments.items() if n != "tutto" and s.get("from") and s["from"] <= z and a <= s["to"]]
        out.append({**x, "periods": hit})
    return out


def apply_verified(data, rev=None):
    """A COPY of the dataset without the stretches reviewed as verified errors with exclude=true (the original is never
    touched). A stretch at the start of a series makes the stock start later; a stretch in the middle drops those rows,
    so the lab excludes the stock (days different from QQQ) instead of filling prices. Returns (copy, removed)."""
    rev = rev if rev is not None else load_reviews()
    new = dict(data)
    removed = []
    for r in rev.get("reviews", []):
        if r.get("status") != "errore" or not r.get("exclude") or r["ticker"] not in data:
            continue
        df = _naive(data[r["ticker"]])
        m = (df.index >= pd.Timestamp(r["from"])) & (df.index <= pd.Timestamp(r["to"]))
        if m.any():
            new[r["ticker"]] = df.loc[~m].copy()
            middle = bool((df.index < pd.Timestamp(r["from"])).any() and (df.index > pd.Timestamp(r["to"])).any())
            removed.append({"ticker": r["ticker"], "from": r["from"], "to": r["to"], "rows": int(m.sum()), "middle": middle})
    return new, removed


# ---------------------------------------------------------------- terminal

def print_report(q, segments=None):
    print("\n=== RAPPORTO DI QUALITÀ DEI DATI STORICI ===")
    print(f"Revisioni manuali {q['reviewsVersion']} ({q['reviewsHash']}) · {q['tickers']} titoli · soglie: variazione estrema "
          f"oltre ±{JUMP:.0f}%, inversione oltre ±{REVERSAL:.0f}%, prezzo fermo {STALE_RUN} sedute, anno illiquido oltre "
          f"{ILLIQUID * 100:.0f}% di sedute senza scambi")
    b = q["benchmark"]
    if not b.get("available"):
        print("BENCHMARK QQQ ASSENTE: nessuna analisi è possibile.")
        return
    c = q["calendar"]
    print(f"Benchmark QQQ: {b['from']} → {b['to']}, {b['sessions']} sedute, chiusure mancanti {b['missingClose']}; "
          f"date duplicate {c['duplicates']}, nel fine settimana {c['weekend']}, buco massimo {c['maxGapDays']} giorni")
    for y, e in c["nyse"].items():
        same = not e["missing"] and not e["extra"]
        print(f"  calendario NYSE {y}: " + ("coincide" if same else f"mancano {e['missing']}, in più {e['extra']}"))
    print("  giorni feriali senza seduta per anno (festività NYSE di solito 9–10):",
          ", ".join(f"{y} {n}" for y, n in c["weekdaysWithoutSession"].items()))
    f = q["future"]
    print(f"Dati successivi al calcolo ({f['asOf']}): {'nessuno' if not f['rows'] else f['rows']}")
    print("Conteggio per stato:", ", ".join(f"{STATUS[k]} {v}" for k, v in q["counts"].items()))
    rows = impact(q["issues"], segments) if segments else [{**x, "periods": None} for x in q["issues"]]
    order = {"errore": 0, "sospetto": 1, "reale": 2, "mancante": 3}
    for k in ("errore", "sospetto", "reale", "mancante"):
        sel = [x for x in rows if x["status"] == k]
        if not sel:
            continue
        print(f"\n-- {STATUS[k]} ({len(sel)}) --")
        for x in sorted(sel, key=lambda x: (order[x["status"]], x["ticker"], x["from"] or "")):
            per = "" if x["periods"] is None else (" · può influenzare: " + (", ".join(
                p + (" (sigillato)" if segments.get(p, {}).get("sealed") else "") for p in x["periods"]) or "nessun periodo usato"))
            val = f" {x['value']:+.1f}%" if x["value"] is not None else ""
            span = x["from"] if x["from"] == x["to"] else f"{x['from']} → {x['to']}"
            print(f"  {x['ticker']:5s} {span}: {x['kind']}{val}{' — ' + x['detail'] if x['detail'] else ''}{per}")
            if x.get("review"):
                print(f"        revisione: {x['review']['note'][:220]}{'…' if len(x['review']['note']) > 220 else ''}")
    if segments:
        used = [x for x in rows if x["status"] in ("errore", "sospetto") and any(p in ("sviluppo", "verifica") for p in x["periods"])]
        print(f"\nProblemi (errori o sospetti) che possono influenzare i periodi usati dallo studio: {len(used)}")
        for x in used:
            print(f"  {x['ticker']} {x['from']}: {x['kind']} ({STATUS[x['status']]})")
    print("\nNessun dato è stato modificato: questo rapporto segnala e basta.\n")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    snaps = sorted(glob.glob(os.path.join(ROOT, "data", "validazione", "prezzi_*.pkl")))
    path = args[0] if args else (snaps[-1] if snaps else None)
    if not path:
        print("Nessun file di prezzi in data/validazione/: esegui prima opportunity_validation.py run --scarica")
        return
    s = pd.read_pickle(path)
    segments = None
    if "--report" in argv:
        rp = argv[argv.index("--report") + 1]
    else:
        reps = sorted(glob.glob(os.path.join(ROOT, "data", "validazione", "report_*.json")))
        rp = reps[0] if reps else None
    if rp:
        with open(rp) as f:
            segments = json.load(f)["period"]["segments"]
    q = check(s["data"], s["tickers"], as_of=s["saved"][:10], saved_at=s["saved"])
    print(f"Prezzi: {os.path.relpath(path, ROOT)} (salvati {s['saved']}) · periodi dello studio da {os.path.relpath(rp, ROOT) if rp else 'nessun report'}")
    print_report(q, segments)
    if "--salva" in argv:
        os.makedirs(OUT_DIR, exist_ok=True)
        out = os.path.join(OUT_DIR, f"qualita_{datetime.now():%Y-%m-%d_%H%M%S}.json")
        with open(out, "w") as f:
            json.dump({"prices": os.path.basename(path), "report": os.path.basename(rp) if rp else None, **q}, f,
                      ensure_ascii=False, indent=1, default=str)
        print("Rapporto salvato:", os.path.relpath(out, ROOT))


if __name__ == "__main__":
    main(sys.argv)
