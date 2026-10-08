"""Raw numbers for the "Analisi tecnica" section of the stock detail (plan phase 12).

For every Nasdaq-100 stock, on CLOSED daily sessions: ATR, 50-day average, last significant low, resistances (52-week
high, top of the last 30 sessions), the tested patterns it shows (same code as the pattern test in backtest.py) and how
its sector and themes are doing against QQQ (same code as the report's rotation map, signals.group_stats).

The page (static/app.js) turns these numbers into the risk plan: entry is the live price and the risk percentage is
chosen there. Nothing here is a forecast or a recommendation: the levels only help decide the risk in advance.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

import market_calendar
from server import ET, ROOT

BENCH = "QQQ"
LOW_DAYS = 20        # "last significant low": lowest low of the last 20 sessions
RANGE_DAYS = 30      # sideways phase: the same 30 sessions as the "Uscita da una fase laterale" pattern
YEAR = 252


def closed_sessions(daily, now=None):
    """The daily history without today's bar while the session is still open."""
    now = now or datetime.now(ET)
    open_now = now.hour * 60 + now.minute < market_calendar.close_minute(now)
    out = {}
    for t, df in daily.items():
        df = df.dropna(subset=["Close"])
        if len(df) and open_now and df.index[-1].date() == now.date():
            df = df.iloc[:-1]
        out[t] = df
    return out


def levels(df):
    """Price levels of one stock (None with less than 60 sessions)."""
    if df is None or len(df) < 60:
        return None
    c, h, lo = df["Close"], df["High"], df["Low"]
    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    year, low, rng = c.iloc[-YEAR:], lo.iloc[-LOW_DAYS:], c.iloc[-RANGE_DAYS:]
    day = lambda ts: str(ts.date())
    return {
        "asOf": day(c.index[-1]), "close": float(c.iloc[-1]),
        "atr": float(tr.rolling(14).mean().iloc[-1]),                     # same ATR(14) as signals.metrics
        "sma50": float(c.rolling(50).mean().iloc[-1]),
        "low": {"v": float(low.min()), "date": day(low.idxmin()), "days": LOW_DAYS},
        "high52": {"v": float(year.max()), "date": day(year.idxmax()), "sessions": int(len(year))},   # highest CLOSE, as in the test
        "range": {"hi": float(rng.max()), "lo": float(rng.min()), "width": float(rng.max() / rng.min() - 1) * 100,
                  "days": RANGE_DAYS},
        "analysis": analysis(df),
    }


# ---------------------------------------------------------------- the "Analisi" box (plan phase 22)
TREND = {"5": 1.0, "21": 2.0, "63": 4.0}   # ▲ above +x%, ▼ below −x% over 5, 21 and 63 sessions (1 week, 1 month, 3 months)
SWING_DAYS, SWING_SIDE = 120, 5             # significant high/low: the extreme of the 5 sessions before and after, in the last 120
ZONE = 1.0                                  # levels less than 1% apart become one zone
BAND_DAYS = 63                              # daily volatility for the normal 5-day swing


def trends(closes):
    """[{"days", "pct", "arrow"}] for 1 week, 1 month, 3 months: ▲ / ▼ beyond the threshold, = in between."""
    c = closes.dropna()
    out = []
    for n, thr in ((5, TREND["5"]), (21, TREND["21"]), (63, TREND["63"])):
        if len(c) <= n:
            out.append({"days": n, "pct": None, "arrow": None, "threshold": thr})
            continue
        pct = float(c.iloc[-1] / c.iloc[-1 - n] - 1) * 100
        out.append({"days": n, "pct": pct, "arrow": "▲" if pct > thr else "▼" if pct < -thr else "=", "threshold": thr})
    return out


def band(closes, price, days=5):
    """Normal swing over `days` sessions from the daily volatility of the last BAND_DAYS sessions: ±1 and ±1.645
    standard deviations (about 68% and 90% of the weeks). Not targets: how much the stock usually moves."""
    r = closes.dropna().pct_change().dropna().iloc[-BAND_DAYS:]
    if len(r) < 20:
        return None
    return band_from_sd(float(r.std()) * 100, price, days)


def band_from_sd(daily_sd_pct, price, days=5):
    """The same swing from a daily standard deviation in percent (decision.py uses the one saved by analysis())."""
    sd = daily_sd_pct / 100 * days ** 0.5
    return {"sd": sd * 100, "p68": [price * (1 - sd), price * (1 + sd)], "p90": [price * (1 - 1.645 * sd), price * (1 + 1.645 * sd)]}


def pivots(high, low, close):
    """Classic floor pivots on yesterday's prices: very short-term levels, they change every day."""
    p = (high + low + close) / 3
    return {"S2": p - (high - low), "S1": 2 * p - high, "P": p, "R1": 2 * p - low, "R2": p + (high - low)}


def zones(levels, price, n=2):
    """Merge levels less than ZONE% apart, then the n nearest zones above and below the price.
    levels: [{"v", "name"}]; returns {"above": [...], "below": [...]} with {"lo", "hi", "v", "names", "pct"}."""
    out = []
    for lv in sorted(levels, key=lambda x: x["v"]):
        if out and (lv["v"] / out[-1]["hi"] - 1) * 100 < ZONE:
            z = out[-1]
            z["hi"] = lv["v"]
            z["names"].append(lv["name"])
        else:
            out.append({"lo": lv["v"], "hi": lv["v"], "names": [lv["name"]]})
    for z in out:
        z["v"] = (z["lo"] + z["hi"]) / 2
        z["pct"] = (z["v"] / price - 1) * 100
    above = sorted((z for z in out if z["lo"] > price), key=lambda z: z["lo"])[:n]
    below = sorted((z for z in out if z["hi"] <= price), key=lambda z: -z["hi"])[:n]
    return {"above": above, "below": below}


def key_levels(df):
    """Significant highs and lows of the last 120 sessions, 52-week high and low, 50- and 200-day averages."""
    c, h, lo = df["Close"], df["High"], df["Low"]
    d = lambda ts: f"{ts.day} {['gen','feb','mar','apr','mag','giu','lug','ago','set','ott','nov','dic'][ts.month - 1]}"
    out = []
    H, L = h.iloc[-SWING_DAYS:], lo.iloc[-SWING_DAYS:]
    k = SWING_SIDE
    for i in range(k, len(H) - k):
        if H.iloc[i] == H.iloc[i - k:i + k + 1].max():
            out.append({"v": float(H.iloc[i]), "name": f"massimo del {d(H.index[i])}"})
        if L.iloc[i] == L.iloc[i - k:i + k + 1].min():
            out.append({"v": float(L.iloc[i]), "name": f"minimo del {d(L.index[i])}"})
    y_h, y_l = h.iloc[-252:], lo.iloc[-252:]
    out.append({"v": float(y_h.max()), "name": "massimo a 52 settimane"})
    out.append({"v": float(y_l.min()), "name": "minimo a 52 settimane"})
    for n in (50, 200):
        if len(c) >= n:
            out.append({"v": float(c.rolling(n).mean().iloc[-1]), "name": f"media {n}"})
    return out


def analysis(df):
    """Everything of the "Analisi" box that depends only on the daily prices (closed sessions)."""
    c, h, lo, v = df["Close"], df["High"], df["Low"], df["Volume"]
    last = float(c.iloc[-1])
    ret = lambda n: float(c.iloc[-1] / c.iloc[-1 - n] - 1) * 100 if len(c) > n else None
    vola = lambda n: float(c.pct_change().iloc[-n:].std()) * 252 ** 0.5 * 100 if len(c) > n else None
    v5, v21 = float(v.iloc[-5:].mean()), float(v.iloc[-21:].mean())
    return {"close": last, "trends": trends(c), "levels": key_levels(df),
            "pivots": pivots(float(h.iloc[-1]), float(lo.iloc[-1]), last),
            "data": {"vol5": v5, "vol21": v21, "volRatio": v5 / v21 if v21 else None, "chg1": ret(1), "chg5": ret(5), "chg21": ret(21),
                     "vola5": vola(5), "vola10": vola(10), "vola21": vola(21)},
            "dailySd": float(c.pct_change().dropna().iloc[-BAND_DAYS:].std()) * 100}


def group_table(constituents, tech):
    """{ticker: [sector, theme, ...]} with each group's rotation phase and the stock's return minus the group's."""
    import signals  # local import: signals imports server
    rows = {t: {**m, "ticker": t} for t, m in tech.items()}
    with open(os.path.join(ROOT, "themes.json")) as f:
        theme_def = json.load(f)
    members = {}
    for c in constituents:
        members.setdefault(("sector", c["sector"]), []).append(c["ticker"])
    for name, tks in theme_def.items():
        members[("theme", name)] = list(tks)
    out = {}
    for (kind, name), tks in members.items():
        ms = [rows[t] for t in tks if t in rows]
        g = signals.group_stats(name, ms, kind)
        if not g:
            continue
        rs3m = float(np.mean([m["rs3m"] for m in ms]))
        for m in ms:
            out.setdefault(m["ticker"], []).append({
                "kind": kind, "name": name, "n": g["n"], "quadrant": g["quadrant"],
                "rs1w": g["rs1w"], "rs1m": g["rs1m"], "rs3m": rs3m,                 # group vs QQQ (points)
                "vs1m": m["rs1m"] - g["rs1m"], "vs3m": m["rs3m"] - rs3m,            # stock vs group (points)
            })
    for gs in out.values():
        gs.sort(key=lambda g: g["kind"] != "sector")      # sector first, then themes
    return out


def build(daily, constituents, tech):
    """{ticker: levels + patterns + groups} for the stocks of the index."""
    import backtest  # local import: backtest imports server
    tickers = [c["ticker"] for c in constituents]
    closed = closed_sessions({t: daily[t] for t in tickers + [BENCH] if t in daily})
    out = {t: lv for t in tickers if (lv := levels(closed.get(t)))}
    patterns = {}
    if BENCH in closed:
        today = backtest.patterns_today(closed, closed[BENCH]["Close"])
        for key, items in today["stocks"].items():
            for x in items:
                patterns.setdefault(x["ticker"], []).append({"key": key, "date": x.get("date")})
    groups = group_table(constituents, tech)
    for t, lv in out.items():
        lv["patterns"] = patterns.get(t, [])
        lv["groups"] = groups.get(t, [])
    return out
