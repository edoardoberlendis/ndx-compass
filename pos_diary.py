"""Diary of the positions' levels (phase 26, step 2): every evening after the NYSE close, the level of each of my
positions (Valuta la vendita / Attenzione / Accumula / Mantieni), the rules that fired, the pillars and the price in
EUR, in portafoglio/diario_posizioni/AAAA-MM-GG.json. Written once per session and NEVER modified afterwards.

The test was fixed by the user on 4 November 2026, before any result (as in phase 11), and is not changed after
seeing the results. At 3 months:
  - "Valuta la vendita" works if the flagged positions did worse than the other positions of the same day in at
    least 60% of the cases and the median difference is at least 2 points worse;
  - "Accumula" works in the opposite case (better in at least 60%, median at least 2 points better);
  - with fewer than 30 cases: "dati ancora insufficienti".
Positions sold before the horizon drop out (their later price is not in the diary): a small bias, said in the page.
Every day carries the version of the rules (RULES_VERSION): the test counts only the days saved with the rules in force,
so a day saved with older rules stays in the diary, untouched, but out of the count.
"""
import json
import os
from datetime import date, timedelta
from statistics import median

import portfolio

DIR = os.path.join(portfolio.PORTFOLIO_DIR, "diario_posizioni")
HORIZONS = {"1 mese": 30, "3 mesi": 91, "6 mesi": 182}   # calendar days
TEST_HORIZON = "3 mesi"
MIN_CASES = 30
SHARE = 60.0
MEDIAN_POINTS = 2.0
TOLERANCE_DAYS = 7          # the first saved day at most a week after the horizon
RULES_VERSION = "2026-11-04 senza tesi"   # the test counts only the days saved with the rules in force (actions.py)


def path(day):
    return os.path.join(DIR, f"{day}.json")


def exists(day):
    return os.path.exists(path(day))


def entry(p):
    """One position of one day (no names, no values: ISIN, level, rules and price per unit in EUR)."""
    a = p.get("action") or {}
    P = p.get("pillars") or {}
    return {"isin": p["isin"], "ticker": p.get("ticker"), "kind": p.get("kind"), "action": a.get("action"),
            "fired": [r["id"] for r in a.get("rules") or [] if r["state"] == "on"],
            "pillars": P.get("score"), "verdict": (p.get("market") or {}).get("verdict"),
            "priceEur": p["value"] / p["qty"] if p.get("qty") and p.get("value") and p.get("live", True) else None, "weight": p.get("weight")}


def save(day, positions):
    """Write the day once; an existing day is never rewritten. True if written."""
    entries = [entry(p) for p in positions or [] if p.get("action")]
    if exists(day) or not entries:
        return False
    os.makedirs(DIR, exist_ok=True)
    tmp = path(day) + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"day": day, "saved": date.today().isoformat(), "rules": RULES_VERSION, "positions": entries}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path(day))
    return True


def days():
    if not os.path.isdir(DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(DIR) if f.endswith(".json") and len(f) == 15)


def load(day):
    with open(path(day)) as f:
        return json.load(f)


def later_day(all_days, day, n):
    """The first saved day at least n calendar days after `day` (at most a week later), or None."""
    target = date.fromisoformat(day) + timedelta(days=n)
    for d in all_days:
        if target <= date.fromisoformat(d) <= target + timedelta(days=TOLERANCE_DAYS):
            return d
    return None


def stats():
    """{horizon: {level: {"cases", "worse", "better", "median", "verdict"}}}: each position's return against the mean
    of the other positions of the same day (difference in points)."""
    all_days = days()
    files = {d: load(d) for d in all_days}
    cache = {d: {e["isin"]: e for e in f["positions"]} for d, f in files.items()}
    start = [d for d in all_days if files[d].get("rules") == RULES_VERSION]   # only the days with the rules in force
    out = {}
    for h, n in HORIZONS.items():
        diffs = {}
        for d in start:
            d2 = later_day(all_days, d, n)
            if not d2:
                continue
            moves = {}
            for isin, e in cache[d].items():
                f = cache[d2].get(isin)
                if e.get("priceEur") and f and f.get("priceEur"):
                    moves[isin] = (f["priceEur"] / e["priceEur"] - 1) * 100
            if len(moves) < 2:
                continue
            for isin, m in moves.items():
                others = [v for k, v in moves.items() if k != isin]
                diffs.setdefault(cache[d][isin]["action"], []).append(m - sum(others) / len(others))
        out[h] = {lvl: summary(lvl, xs) for lvl, xs in diffs.items()}
    return out


def summary(level, xs):
    n = len(xs)
    worse = sum(x < 0 for x in xs) / n * 100 if n else 0
    med = median(xs) if n else None
    s = {"cases": n, "worse": worse, "better": 100 - worse if n else 0, "median": med}
    if n < MIN_CASES:
        s["verdict"] = "dati ancora insufficienti"
    elif level == "Valuta la vendita":
        s["verdict"] = "supera il test" if worse >= SHARE and med <= -MEDIAN_POINTS else "non supera il test"
    elif level == "Accumula":
        s["verdict"] = "supera il test" if 100 - worse >= SHARE and med >= MEDIAN_POINTS else "non supera il test"
    else:
        s["verdict"] = "solo informazione"
    return s


def test_line():
    """Short summary of the fixed test for the page: {"days", "sell": {...}, "add": {...}}."""
    st = stats().get(TEST_HORIZON) or {}
    blank = {"cases": 0, "verdict": "dati ancora insufficienti"}
    ds = [d for d in days() if load(d).get("rules") == RULES_VERSION]
    return {"days": len(ds), "since": (ds or [None])[0],
            "sell": st.get("Valuta la vendita", blank), "add": st.get("Accumula", blank)}
