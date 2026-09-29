"""Twice-daily trend & rotation report for the Nasdaq-100.

Rule-based technical screening: 20/40/60-day moving-average structure, relative
strength vs QQQ, and sector / theme rotation (AI chips, memory, power, ...).
Output is a JSON report in reports/ that the dashboard's Ideas tab reads.

    python3 signals.py              # run now (session inferred from US time)
    python3 signals.py --notify     # ...and post a macOS notification (used by launchd)

These are mechanical screening signals, not investment advice.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
import pandas as pd

from server import ET, ROOT, clean, download, load_constituents, load_infos

REPORT_DIR = os.path.join(ROOT, "reports")
os.makedirs(REPORT_DIR, exist_ok=True)
BENCH = "QQQ"
MAS = (20, 40, 60)
CHART_BARS = 120


# ---------------------------------------------------------------- per-stock metrics

def rsi(close: pd.Series, n=14) -> float | None:
    d = close.diff().iloc[-(n * 3):]
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if dn == 0:
        return 100.0
    return float(100 - 100 / (1 + up / dn))


def crossed(a: pd.Series, b: pd.Series, bars=5) -> int:
    """+1 if a crossed above b within the last `bars` sessions, -1 if below, else 0."""
    diff = np.sign((a - b).iloc[-(bars + 1):].dropna())
    if len(diff) < 2 or diff.iloc[0] == diff.iloc[-1]:
        return 0
    return 1 if diff.iloc[-1] > 0 else -1


def ret(c: pd.Series, n: int) -> float | None:
    return float(c.iloc[-1] / c.iloc[-1 - n] - 1) * 100 if len(c) > n else None


def metrics(df: pd.DataFrame, bench: pd.Series) -> dict | None:
    df = df.dropna(subset=["Close"])
    if len(df) < 70:
        return None
    c, h, lo, v = df["Close"], df["High"], df["Low"], df["Volume"]
    sma = {n: c.rolling(n).mean() for n in MAS}
    price = float(c.iloc[-1])
    s20, s40, s60 = (float(sma[n].iloc[-1]) for n in MAS)
    slope = {n: float(sma[n].iloc[-1] / sma[n].iloc[-6] - 1) * 100 for n in MAS}   # % per week
    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])

    if price > s20 > s40 > s60:
        stack = "bull"
    elif price < s20 < s40 < s60:
        stack = "bear"
    else:
        stack = "mixed"

    b = bench.reindex(c.index).ffill()
    rs1m = (ret(c, 21) or 0) - (ret(b, 21) or 0)
    rs3m = (ret(c, 63) or 0) - (ret(b, 63) or 0)
    rs1w = (ret(c, 5) or 0) - (ret(b, 5) or 0)
    vol_ratio = float(v.iloc[-20:].mean() / v.iloc[-60:].mean()) if v.iloc[-60:].mean() else None
    r = rsi(c)

    # ---- trend score, roughly -100..+100
    order = [price > s20, s20 > s40, s40 > s60]
    score = sum(8.33 if o else -8.33 for o in order)                        # MA structure ±25
    score += sum(5 * math.tanh(slope[n] / 1.0) for n in MAS)                 # MA slopes ±15
    score += max(-20, min(20, rs1m * 1.5)) + max(-15, min(15, rs3m * 0.5))   # relative strength ±35
    score += max(-10, min(10, (r - 50) * 0.5))                               # momentum ±10
    if vol_ratio and vol_ratio > 1.1:
        score += 5 if stack == "bull" else -5 if stack == "bear" else 0      # volume confirmation ±5
    vs20 = (price / s20 - 1) * 100
    if vs20 > 10:
        score -= 10                                                          # over-extension penalty

    tail = df.iloc[-CHART_BARS:]
    return {
        "price": price, "sma20": s20, "sma40": s40, "sma60": s60,
        "vs20": vs20, "vs40": (price / s40 - 1) * 100, "vs60": (price / s60 - 1) * 100,
        "slope20": slope[20], "slope40": slope[40], "slope60": slope[60],
        "stack": stack, "rsi": r, "atr": atr, "atrPct": atr / price * 100,
        "rs1w": rs1w, "rs1m": rs1m, "rs3m": rs3m,
        "ret1d": ret(c, 1), "ret1w": ret(c, 5), "ret1m": ret(c, 21), "ret3m": ret(c, 63),
        "volRatio": vol_ratio,
        "high20": float(h.iloc[-20:].max()), "low20": float(lo.iloc[-20:].min()),
        "x20_60": crossed(sma[20], sma[60]), "xP_40": crossed(c, sma[40]),
        "score": round(max(-100, min(100, score)), 1),
        "_chart": {
            "t": [int(pd.Timestamp(x).timestamp()) for x in tail.index],
            "c": [round(float(x), 2) for x in tail["Close"]],
            **{f"s{n}": [None if pd.isna(x) else round(float(x), 2) for x in sma[n].iloc[-CHART_BARS:]] for n in MAS},
        },
    }


# ---------------------------------------------------------------- groups (sectors / themes)

def quadrant(level, mom):
    if level >= 0:
        return "Leading" if mom >= 0 else "Weakening"
    return "Improving" if mom >= 0 else "Lagging"


def group_stats(name, members, kind):
    ms = [m for m in members if m]
    if not ms:
        return None
    level = float(np.mean([m["rs1m"] for m in ms]))
    mom = float(np.mean([m["rs1w"] for m in ms]))
    return {
        "name": name, "kind": kind, "n": len(ms), "tickers": [m["ticker"] for m in ms],
        "score": round(float(np.mean([m["score"] for m in ms])), 1),
        "bull": sum(m["stack"] == "bull" for m in ms) / len(ms) * 100,
        "bear": sum(m["stack"] == "bear" for m in ms) / len(ms) * 100,
        "above20": sum(m["vs20"] > 0 for m in ms) / len(ms) * 100,
        "above40": sum(m["vs40"] > 0 for m in ms) / len(ms) * 100,
        "above60": sum(m["vs60"] > 0 for m in ms) / len(ms) * 100,
        "rs1m": level, "rs1w": mom, "ret1m": float(np.mean([m["ret1m"] or 0 for m in ms])),
        "quadrant": quadrant(level, mom),
        "leaders": [m["ticker"] for m in sorted(ms, key=lambda m: -m["score"])[:3]],
    }


# ---------------------------------------------------------------- setups

def levels(m, side, entry, stop, target_hint=None):
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target = target_hint if target_hint and (target_hint - entry) * (1 if side == "long" else -1) >= 1.5 * risk \
        else entry + (2 * risk if side == "long" else -2 * risk)
    return {"entry": round(entry, 2), "stop": round(stop, 2), "target": round(target, 2),
            "rr": round(abs(target - entry) / risk, 1), "riskPct": round(risk / entry * 100, 1)}


def stop_near(m, side, entry, ref):
    """Stop just beyond a reference MA, but never tighter than 1 ATR or wider than 2.5 ATR."""
    atr = m["atr"]
    dist = max(atr, min(2.5 * atr, abs(entry - ref) + 0.5 * atr))
    return entry - dist if side == "long" else entry + dist


def classify(m):
    """Return (setup, side, levels) for the first matching rule, or None."""
    p, s20, s40, s60, atr = m["price"], m["sma20"], m["sma40"], m["sma60"], m["atr"]
    up_ma = m["slope40"] > 0 and m["slope60"] > 0
    dn_ma = m["slope20"] < 0 and m["slope40"] < 0

    if m["stack"] == "bull" and (m["vs20"] > 8 or m["rsi"] > 75):
        return SETUP_EXTENDED, "manage", {"entry": None, "stop": round(s20, 2), "target": None, "rr": None, "riskPct": None}
    if m["x20_60"] == 1 and p > s20 and (m["volRatio"] or 0) >= 0.95:
        return SETUP_BULL_X, "long", levels(m, "long", p, stop_near(m, "long", p, s60), m["high20"])
    if (p > s40 > s60 and s20 > s60) and up_ma and -1.5 <= m["vs20"] <= 2.5 and 38 <= m["rsi"] <= 62:
        entry = max(s20, p - 0.5 * atr) if p >= s20 else p
        return SETUP_PULLBACK, "long", levels(m, "long", entry, stop_near(m, "long", entry, s40), m["high20"])
    if m["stack"] == "bull" and m["rs1m"] > 4 and 55 <= m["rsi"] <= 72 and m["vs20"] <= 6:
        entry = max(s20, p - 1.0 * atr)
        return "Leader di momentum", "long", levels(m, "long", entry, stop_near(m, "long", entry, s40))
    if p > s60 and m["slope60"] > 0 and p < s20 and m["rsi"] < 38:
        return "Ipervenduto in trend rialzista", "watch", levels(m, "long", p, stop_near(m, "long", p, s60), s20)
    if m["x20_60"] == -1 and p < s20:
        return SETUP_BEAR_X, "avoid", levels(m, "short", p, stop_near(m, "short", p, s60), m["low20"])
    if m["stack"] == "bear" and dn_ma and m["rs1m"] < -3:
        entry = min(s20, p + 0.5 * atr)
        return "Trend ribassista", "avoid", levels(m, "short", entry, stop_near(m, "short", entry, s40), m["low20"])
    return None


SETUP_EXTENDED, SETUP_BULL_X, SETUP_BEAR_X = "Tirato", "Incrocio rialzista", "Incrocio ribassista"
SETUP_PULLBACK = "Ritracciamento in trend rialzista"
# reports saved before the Italian translation carry English setup names: translate them before comparing
SETUP_OLD_EN = {"Extended": SETUP_EXTENDED, "Bullish crossover": SETUP_BULL_X, "Bearish crossover": SETUP_BEAR_X,
                "Pullback in uptrend": SETUP_PULLBACK, "Momentum leader": "Leader di momentum",
                "Oversold in uptrend": "Ipervenduto in trend rialzista", "Downtrend": "Trend ribassista"}
QUADRANT_IT = {"Leading": "leader", "Weakening": "in indebolimento", "Lagging": "in ritardo", "Improving": "in miglioramento"}


def it(x, fmt):
    """Format a number with an Italian decimal comma."""
    return format(x, fmt).replace(".", ",")


def rationale(m, sec, themes, setup):
    out = []
    stack_txt = {"bull": "Prezzo sopra le medie 20 > 40 > 60 giorni, tutte in salita",
                 "bear": "Prezzo sotto le medie 20 < 40 < 60 giorni, tutte in discesa",
                 "mixed": "Medie mobili miste (nessun ordine chiaro)"}[m["stack"]]
    out.append(stack_txt)
    out.append(f"{it(m['vs20'], '+.1f')}% vs media 20 · {it(m['vs40'], '+.1f')}% vs media 40 · {it(m['vs60'], '+.1f')}% vs media 60")
    if setup == SETUP_PULLBACK:
        out.append("Tornato sulla media a 20 giorni mentre le medie a 40/60 continuano a salire")
    if setup == SETUP_BULL_X:
        out.append("La media a 20 giorni ha superato quella a 60 nelle ultime 5 sedute")
    if setup == SETUP_BEAR_X:
        out.append("La media a 20 giorni è scesa sotto quella a 60 nelle ultime 5 sedute")
    if setup == SETUP_EXTENDED:
        out.append("Molto sopra la media a 20 giorni: rischio di ritorno verso la media, non inseguire")
    word = "Fa meglio di" if m["rs1m"] >= 0 else "Fa peggio di"
    out.append(f"{word} QQQ di {it(abs(m['rs1m']), '.1f')} punti in 1 mese ({it(m['rs3m'], '+.1f')} punti in 3 mesi)")
    out.append(f"RSI {m['rsi']:.0f}" + (" (ipercomprato)" if m["rsi"] > 70 else " (ipervenduto)" if m["rsi"] < 30 else ""))
    if m["volRatio"]:
        out.append(f"Volumi 20 g / 60 g {it(m['volRatio'], '.2f')}×" + (": accumulo" if m["volRatio"] > 1.15 and m["stack"] == "bull" else ""))
    ctx = [f"{sec['name']}: {QUADRANT_IT[sec['quadrant']]}"] if sec else []
    ctx += [f"{t['name']}: {QUADRANT_IT[t['quadrant']]}" for t in themes]
    if ctx:
        out.append("Contesto dei gruppi: " + " · ".join(ctx))
    return out


def conviction(m, side, sec, themes, regime):
    s = abs(m["score"])
    groups = ([sec] if sec else []) + themes
    good = {"long": ("Leading", "Improving"), "watch": ("Leading", "Improving"), "avoid": ("Lagging", "Weakening")}.get(side, ())
    if groups:
        s += 15 * sum(g["quadrant"] in good for g in groups) / len(groups)
    if side in ("long", "watch") and regime["bias"] == "long":
        s += 10
    if side == "avoid" and regime["bias"] == "defensive":
        s += 10
    if m.get("levels_rr", 0) >= 2:
        s += 5
    return int(max(0, min(100, s)))


# ---------------------------------------------------------------- report

def session_label(now):
    """morning = pre-market plan, close = after the 16:00 ET close (13:00 on early-close days), intraday = manual run during the session."""
    import market_calendar
    t = now.hour * 60 + now.minute
    if t < 9 * 60 + 30:
        return "morning"
    return "close" if t >= market_calendar.close_minute(now) else "intraday"


def previous_report(current_id):
    """Most recent saved report other than the one being (re)generated."""
    for rid in list_reports():
        if rid < current_id:
            with open(os.path.join(REPORT_DIR, rid + ".json")) as f:
                return json.load(f)
    return None


def add_final_signals(rows, infos):
    """Final signal (score.py: analysts + valuation + news; the trend is returned apart), the same one the dashboard shows.
    Sets m["signal"], m["sigScore"] and the full detail in m["_signal"]."""
    import analysts
    import score
    from server import news, pct
    anl = analysts.load(list(rows))              # today's cached copy, or a ~15 s download
    base = []
    for t, m in rows.items():
        info = infos.get(t) or {}
        r = {"ticker": t, "name": m["name"], "sector": m["sector"], "price": m["price"],
             "mcap": clean(info.get("marketCap")), "pe": clean(info.get("trailingPE")), "fpe": clean(info.get("forwardPE")),
             "ps": clean(info.get("priceToSalesTrailing12Months")), "evEbitda": clean(info.get("enterpriseToEbitda")),
             "recMean": clean(info.get("recommendationMean")), "upside": pct(info.get("targetMeanPrice"), m["price"])}
        r.update(analysts.analyst_summary(anl.get(t)))
        base.append(r)
    medians = analysts.peer_medians(base)
    with ThreadPoolExecutor(4) as ex:
        items = dict(zip(rows, ex.map(lambda t: news(t, 40), rows)))
    for r in base:
        t = r["ticker"]
        sig = score.for_stock(r, rows[t], analysts.valuation(r, anl.get(t), medians), items.get(t))
        rows[t].update(signal=sig and sig["signal"], sigScore=sig and sig["score"], _signal=sig)


def build_report():
    t0 = time.time()
    now = datetime.now(ET)
    cons = load_constituents()
    tickers = [c["ticker"] for c in cons]
    infos = load_infos(tickers)
    with open(os.path.join(ROOT, "themes.json")) as f:
        theme_def = json.load(f)

    data = download(tickers + [BENCH], period="1y", interval="1d")
    if BENCH not in data:
        raise RuntimeError("benchmark download failed")
    bench = data[BENCH]["Close"].dropna()
    last_bar = bench.index[-1].date()
    intraday = last_bar == now.date() and now.hour * 60 + now.minute >= 9 * 60 + 30

    rows = {}
    for c in cons:
        df = data.get(c["ticker"])
        m = metrics(df, bench) if df is not None else None
        if m:
            m.update(ticker=c["ticker"], sector=c["sector"], industry=c["industry"],
                     name=(infos.get(c["ticker"]) or {}).get("shortName") or c["name"])
            rows[c["ticker"]] = m
    add_final_signals(rows, infos)

    bm = metrics(data[BENCH], bench)
    breadth = {k: sum(r[f"vs{k}"] > 0 for r in rows.values()) / len(rows) * 100 for k in MAS}
    bull_share = sum(r["stack"] == "bull" for r in rows.values()) / len(rows) * 100
    bear_share = sum(r["stack"] == "bear" for r in rows.values()) / len(rows) * 100
    if bm["stack"] == "bull" and breadth[60] >= 55:
        regime = {"label": "Trend rialzista, partecipazione ampia", "bias": "long",
                  "text": "QQQ è sopra le medie a 20/40/60 giorni in salita e la maggior parte dei titoli è sopra la propria media a 60. I ritorni verso la media a 20 nei gruppi leader hanno le probabilità migliori."}
    elif bm["vs60"] > 0 and bm["slope60"] > 0 and breadth[60] < 55:
        regime = {"label": "Trend rialzista, sempre più ristretto", "bias": "selective",
                  "text": "L'indice sale ma meno di metà dei titoli lo conferma. Resta sui titoli più forti, riduci le posizioni ed evita i ritardatari."}
    elif bm["stack"] == "bear" or (bm["vs60"] < 0 and bm["slope60"] < 0):
        regime = {"label": "Trend ribassista", "bias": "defensive",
                  "text": "QQQ è sotto medie in discesa. Tieni più liquidità, posizioni rialziste piccole, e aspetta che la media a 20 superi quella a 60 prima di aumentare il rischio."}
    else:
        regime = {"label": "Laterale / fase di transizione", "bias": "selective",
                  "text": "Segnali contrastanti tra le medie. Preferisci i titoli con forza relativa e usa stop più stretti."}
    regime.update(qqq={k: clean(bm[k]) for k in ("price", "sma20", "sma40", "sma60", "vs20", "vs40", "vs60", "slope20", "slope60", "rsi", "stack", "ret1d", "ret1w", "ret1m")},
                  breadth=breadth, bullShare=bull_share, bearShare=bear_share, qqqChart=bm["_chart"])

    sectors = {}
    for sec in sorted({r["sector"] for r in rows.values()}):
        g = group_stats(sec, [r for r in rows.values() if r["sector"] == sec], "sector")
        if g:
            sectors[sec] = g
    themes = {}
    for name, tks in theme_def.items():
        g = group_stats(name, [rows.get(t) for t in tks], "theme")
        if g and g["n"] >= 1:
            themes[name] = g
    ticker_themes = {t: [themes[n] for n in themes if t in themes[n]["tickers"]] for t in rows}

    ideas = []
    for t, m in rows.items():
        cls = classify(m)
        if not cls or cls[2] is None:
            continue
        setup, side, lv = cls
        sec, th = sectors.get(m["sector"]), ticker_themes[t]
        m["setup"] = setup
        m["levels_rr"] = lv.get("rr") or 0
        ideas.append({
            "ticker": t, "name": m["name"], "sector": m["sector"], "themes": [x["name"] for x in th],
            "setup": setup, "side": side, "levels": lv, "price": m["price"], "score": m["score"],
            "conviction": conviction(m, side, sec, th, regime),
            "why": rationale(m, sec, th, setup),
            "chart": m["_chart"],
            "stats": {k: clean(m[k]) for k in ("vs20", "vs40", "vs60", "rsi", "rs1m", "rs3m", "volRatio", "atrPct", "ret1d", "ret1w", "ret1m")},
            "signal": m.get("_signal"),
        })
    ideas.sort(key=lambda i: -i["conviction"])

    rid = f"{now:%Y-%m-%d}_{session_label(now)}"
    prev = previous_report(rid)
    changes = diff_reports(prev, rows, ideas, sectors, themes) if prev else None

    longs = [i for i in ideas if i["side"] == "long"]
    lead = sorted(themes.values(), key=lambda g: -g["score"])
    headline = (f"{regime['label']}. Temi più forti: {', '.join(g['name'] for g in lead[:3])}. "
                f"Più deboli: {', '.join(g['name'] for g in lead[-2:])}. "
                f"{len(longs)} setup di acquisto, {sum(i['side'] == 'avoid' for i in ideas)} da evitare.")

    report = {
        "id": rid,
        "generated": now.isoformat(timespec="seconds"),
        "session": session_label(now),
        "dataAsOf": str(last_bar), "intraday": intraday,
        "headline": headline,
        "regime": regime,
        "sectors": sorted(sectors.values(), key=lambda g: -g["score"]),
        "themes": sorted(themes.values(), key=lambda g: -g["score"]),
        "ideas": ideas,
        "stocks": [{k: clean(v) if not isinstance(v, str) else v for k, v in m.items() if not k.startswith("_") and k != "levels_rr"}
                   for m in sorted(rows.values(), key=lambda r: -r["score"])],
        "changes": changes,
        "prevId": prev["id"] if prev else None,
        "elapsed": round(time.time() - t0, 1),
        "disclaimer": "Screening tecnico automatico a scopo di studio. Non è una consulenza finanziaria: fai le tue verifiche e dimensiona le posizioni in base alla tua tolleranza al rischio.",
    }
    return report


def diff_reports(prev, rows, ideas, sectors, themes):
    prev_ideas = {i["ticker"]: SETUP_OLD_EN.get(i["setup"], i["setup"]) for i in prev.get("ideas", [])}
    now_ideas = {i["ticker"]: i["setup"] for i in ideas}
    prev_scores = {s["ticker"]: s["score"] for s in prev.get("stocks", [])}
    prev_groups = {g["name"]: g for g in prev.get("sectors", []) + prev.get("themes", [])}
    movers = sorted(((t, r["score"] - prev_scores[t]) for t, r in rows.items() if t in prev_scores and abs(r["score"] - prev_scores[t]) >= 1), key=lambda x: -abs(x[1]))[:10]
    rotations = []
    for g in list(sectors.values()) + list(themes.values()):
        p = prev_groups.get(g["name"])
        if p and p["quadrant"] != g["quadrant"]:
            rotations.append({"name": g["name"], "from": p["quadrant"], "to": g["quadrant"]})
        g["dScore"] = round(g["score"] - p["score"], 1) if p else None
    return {
        "since": prev["id"],
        "newIdeas": [{"ticker": t, "setup": s} for t, s in now_ideas.items() if prev_ideas.get(t) != s],
        "dropped": [{"ticker": t, "setup": s} for t, s in prev_ideas.items() if t not in now_ideas],
        "scoreMovers": [{"ticker": t, "delta": round(d, 1), "score": rows[t]["score"]} for t, d in movers],
        "rotations": rotations,
    }


def save(report):
    path = os.path.join(REPORT_DIR, report["id"] + ".json")
    for p in (path, os.path.join(REPORT_DIR, "latest.json")):
        with open(p, "w") as f:
            json.dump(report, f, default=clean, allow_nan=False)
    return path


def list_reports():
    out = []
    for fn in sorted(os.listdir(REPORT_DIR), reverse=True):
        if fn.endswith(".json") and fn != "latest.json":
            out.append(fn[:-5])
    return out


def notify(report):
    longs = [i["ticker"] for i in report["ideas"] if i["side"] == "long"][:5]
    session = {"morning": "del mattino", "close": "della sera"}.get(report["session"], "intraday")
    title = f"Report Nasdaq-100 {session}"
    msg = f"{report['regime']['label']} · Migliori acquisti: {', '.join(longs) or 'nessuno'}"
    # Pass text as argv, not spliced into the script: no quoting issues and non-ASCII (·) survives launchd.
    script = ('on run argv\n'
              'display notification (item 1 of argv) with title (item 2 of argv) subtitle "Apri localhost:8100/#ideas"\n'
              'end run')
    subprocess.run(["osascript", "-e", script, msg, title], check=False)


def run(notify_user=False):
    report = build_report()
    path = save(report)
    print(f"[{report['generated']}] {report['id']}: {report['headline']} -> {path} ({report['elapsed']}s)")
    if notify_user:
        notify(report)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--notify", action="store_true", help="post a macOS notification when done")
    args = ap.parse_args()
    now = datetime.now(ET)
    # scheduled runs (launchd, no terminal) skip weekends and US market holidays; a run from the Terminal always goes
    if now.weekday() >= 5 and not sys.stdin.isatty():
        print("weekend — skipping scheduled run")
        sys.exit(0)
    import market_calendar
    if market_calendar.holiday(now) and not sys.stdin.isatty():
        print(f"US market holiday ({market_calendar.holiday(now)}) — skipping scheduled run")
        sys.exit(0)
    run(args.notify)
