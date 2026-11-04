"""Automatic stop of every position (phase 26, approved on 4 November 2026).

Every day the stop is computed from today's price with the rule of the purchase plan (decision.stops: the nearest
chart level at a reasonable distance, 50-day average or last low minus half an ATR, otherwise a multiple of the ATR),
and kept as the HIGHEST ever reached: it can only rise, never fall, like a stop that follows the price.
It starts the first day the position is seen (so it is below today's price, not below my purchase price) and
starts again from zero if I sell and buy back (a position missing at the last update).

Saved in portafoglio/stop_auto.json: {isin: {"stop", "since", "raised", "last", "how", "atr", "currency"}}.
"""
import json
import os
from datetime import date

import portfolio

FILE = os.path.join(portfolio.PORTFOLIO_DIR, "stop_auto.json")
NO_STOP = "volatile"
WHY_VOLATILE = ("non calcolabile: il titolo oscilla così tanto rispetto al suo prezzo che la regola del piano darebbe uno stop "
                "sotto zero")


def load():
    try:
        with open(FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def computed(price, lv, money=None):
    """(stop, label, atr) from today's price and the levels {"atr", "sma50", "low": {"v", "date"}}, or None."""
    from decision import stops, usd
    if not price or not lv or not lv.get("atr") or not lv.get("low"):
        return None
    opts, default, _ = stops(price, lv, money=money or usd)
    if not default:
        return None
    o = next(o for o in opts if o["id"] == default)
    if o["v"] <= 0:
        return NO_STOP                                  # volatility larger than the price: no meaningful stop
    return o["v"], o["label"], lv["atr"]


def trail(prev, new, today):
    """The stop of today: never lower than yesterday's. prev: the saved entry (or None); new: (stop, label, atr)."""
    today = today.isoformat()
    if not new:
        return prev
    if new == NO_STOP:
        return None
    v, label, atr = new
    if not prev:
        return {"stop": v, "since": today, "raised": 0, "last": today, "how": label, "atr": atr}
    out = dict(prev, last=today, atr=atr)
    if v > prev["stop"]:
        out.update(stop=v, raised=prev.get("raised", 0) + (prev.get("last") != today), how=label)
    return out


def update(positions, levels, today=None):
    """{isin: stop entry} for my positions. levels: {isin: (price, levels, money formatter)}. Writes the file when
    something changed; a position that disappeared is dropped (a new purchase starts from zero)."""
    today = today or date.today()
    old = load()
    if not positions:
        return old                                    # portfolio not loaded: keep everything
    new, shown = {}, {}                                   # shown: positions without a stop, with the reason (not saved)
    for p in positions:
        x = levels.get(p["isin"])
        prev = old.get(p["isin"])
        if prev and (prev.get("currency") and prev["currency"] != p.get("currency") or prev.get("stop", 0) <= 0):
            prev = None                                   # the listing changed (or an old stop below zero): start again
        c = computed(*x) if x else None
        if c == NO_STOP:
            shown[p["isin"]] = {"stop": None, "why": WHY_VOLATILE}
            continue
        e = trail(prev, c, today)
        if e:
            new[p["isin"]] = dict(e, currency=p.get("currency"))
    if new != old:
        os.makedirs(os.path.dirname(FILE), exist_ok=True)
        with open(FILE + ".tmp", "w") as f:
            json.dump(new, f, indent=1, ensure_ascii=False)
        os.replace(FILE + ".tmp", FILE)
    return {**new, **shown}
