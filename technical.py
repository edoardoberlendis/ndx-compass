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
    }


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
