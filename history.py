"""History of my portfolio and its performance against a reference (plan phase 16).

Personal data, only on this Mac: one file per day in portafoglio/storico/ (AAAA-MM-GG.json: value, cost, EUR/USD and
the positions) plus flussi.json (money added or removed, detected when a new Fineco export replaces the previous one).
Past days are never modified or deleted; today's file is rewritten at every price refresh, so it ends up holding the
last picture of the day. Days when the dashboard was off are rebuilt from the last saved positions and the closing
prices of those days, and marked "rebuilt".

Performance is TIME-WEIGHTED: each day's return is computed only on the money that was already there
(value at the end of the day minus the money added that day, divided by the value of the day before), and the daily
returns are chained. Money added or removed is therefore never counted as a gain or a loss.

Limits (LIMITS below, shown in the page): a purchase or sale is dated on the day the new file is loaded; the proceeds
of a sale are estimated; cash and cashed dividends are not in the Fineco export.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta

import pandas as pd

import portfolio

log = logging.getLogger("ndx")
DIR = os.path.join(portfolio.PORTFOLIO_DIR, "storico")
FLOWS = os.path.join(DIR, "flussi.json")
BENCH = {"qqq": ("QQQ", "USD", "QQQ in euro"), "world": ("VWCE.DE", "EUR", "VWCE (azionario mondiale)")}
SHORT_DAYS = 90           # below about 3 months the page says the history is too short to draw conclusions

LIMITS = [
    ("Storia corta", "Con poche settimane di storico i rendimenti dicono poco: differenze di qualche punto rispetto ai riferimenti possono essere solo caso."),
    ("Data dei movimenti", "Un acquisto o una vendita risulta nel giorno in cui carichi il nuovo file Fineco, non in quello in cui l'hai fatto: conviene caricare il file lo stesso giorno dell'operazione."),
    ("Vendite stimate", "Il file Fineco non dice a che prezzo hai venduto: l'incasso è stimato con il prezzo di mercato del nuovo file (o l'ultimo prezzo salvato, se la posizione è stata chiusa). Gli acquisti usano invece il «Valore di carico» di Fineco, che è la cifra spesa."),
    ("Niente liquidità né dividendi incassati", "L'export contiene solo i titoli. Un dividendo pagato sul conto non entra nel rendimento, mentre QQQ e VWCE lo includono: il confronto ti penalizza leggermente."),
    ("Giorni ricostruiti", "Nei giorni in cui la dashboard era spenta il valore è ricostruito con le quantità dell'ultimo salvataggio e i prezzi di chiusura di quei giorni."),
    ("Non è una previsione", "Il rendimento passato non dice nulla su quello futuro. Non è una consulenza finanziaria."),
]

_lock = threading.Lock()
_bench = {"at": 0, "start": None, "data": {}}


# ---------------------------------------------------------------- files

def _path(day):
    return os.path.join(DIR, f"{day}.json")


def _days():
    if not os.path.isdir(DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(DIR) if len(f) == 15 and f.endswith(".json") and f[:4].isdigit())


def _read(day):
    with open(_path(day)) as f:
        return json.load(f)


def _write(path, data):
    os.makedirs(DIR, exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(data, f)
    os.replace(path + ".tmp", path)


def _flows():
    try:
        with open(FLOWS) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


# ---------------------------------------------------------------- money added or removed

def detect_flow(prev, cur, today):
    """Flow between two daily pictures taken from different export files (None if quantities did not change).
    amount > 0 = money added. Purchases: increase of Fineco's cost value (exact). Sales: quantity sold × market price (estimated)."""
    old = {p["isin"]: p for p in prev["positions"]}
    new = {p["isin"]: p for p in cur["positions"]}
    details = []
    for isin in sorted(set(old) | set(new)):
        a, b = old.get(isin), new.get(isin)
        dq = (b["qty"] if b else 0) - (a["qty"] if a else 0)
        if abs(dq) < 1e-9:
            continue
        if dq > 0:
            amount, est = b["cost"] - (a["cost"] if a else 0), False
        else:
            ref = b or a                                     # still held: today's price; closed: the last saved price
            amount, est = dq * (ref["value"] / ref["qty"] if ref["qty"] else 0), True
        details.append({"name": (b or a)["name"], "isin": isin, "qty": dq, "amount": amount, "estimated": est})
    if not details:
        return None
    return {"date": today, "amount": sum(d["amount"] for d in details),
            "bought": sum(d["amount"] for d in details if d["amount"] > 0),
            "sold": -sum(d["amount"] for d in details if d["amount"] < 0),
            "estimated": any(d["estimated"] for d in details), "from": prev.get("file"), "to": cur.get("file"),
            "details": details}


# ---------------------------------------------------------------- daily picture

def _picture(pf, day, rebuilt=False):
    return {"date": day, "savedAt": datetime.now().isoformat(timespec="seconds"), "rebuilt": rebuilt, "file": pf.get("file"),
            "value": pf["totals"]["value"], "cost": pf["totals"]["cost"], "fx": pf.get("fx"),
            "positions": [{"isin": p["isin"], "name": p["name"], "ticker": p.get("ticker"), "currency": p["currency"],
                           "qty": p["qty"], "price": p["price"], "value": p["value"], "cost": p["cost"]} for p in pf["positions"]]}


def _rebuild_gap(last, today):
    """Pictures for the weekdays between the last saved day and today, with the last saved quantities and each day's closes."""
    start = date.fromisoformat(last["date"])
    days = [start + timedelta(days=k) for k in range(1, (date.fromisoformat(today) - start).days)]
    days = [d for d in days if d.weekday() < 5]
    if not days:
        return
    from server import download   # local import: server imports this module's users
    tickers = sorted({p["ticker"] for p in last["positions"] if p.get("ticker")})
    data = download(tickers + [portfolio.FX], start=(start - timedelta(days=7)).isoformat(), interval="1d")
    closes = {t: df["Close"].dropna() for t, df in data.items() if "Close" in df}
    for c in closes.values():
        c.index = pd.to_datetime(c.index).tz_localize(None).normalize()

    def at(t, d):
        s = closes.get(t)
        s = s[s.index <= pd.Timestamp(d)] if s is not None else None
        return float(s.iloc[-1]) if s is not None and len(s) else None
    for d in days:
        fx = at(portfolio.FX, d) or last.get("fx")
        positions = []
        for p in last["positions"]:
            price = at(p.get("ticker"), d) if p.get("ticker") else None
            usd = p["currency"].upper() != "EUR"
            value = p["qty"] * price / (fx if usd else 1.0) if price and (fx or not usd) else p["value"]
            positions.append({**p, "price": price or p["price"], "value": value})
        _write(_path(d.isoformat()), {**last, "date": d.isoformat(), "savedAt": datetime.now().isoformat(timespec="seconds"),
                                      "rebuilt": True, "fx": fx, "value": sum(p["value"] for p in positions), "positions": positions})
    log.info("portfolio history: %d missing days rebuilt", len(days))


def record(pf, today=None):
    """Save today's picture (called after every price refresh). Returns True when a file was written."""
    if not pf.get("file") or pf.get("error") or pf.get("resolving") or not pf.get("quotesAt") or not pf.get("positions"):
        return False
    today = today or date.today().isoformat()
    with _lock:
        days = _days()
        if days and days[-1] > today:
            return False                                      # clock went backwards: never touch later days
        last = _read(days[-1]) if days else None
        if last and last["date"] < today:
            try:
                _rebuild_gap(last, today)
            except Exception:
                log.exception("portfolio history: gap not rebuilt")
            days = _days()
            last = _read(days[-1])
        cur = _picture(pf, today)
        if last and last.get("file") != cur["file"]:
            flows = _flows()
            if not any(f.get("from") == last.get("file") and f.get("to") == cur["file"] for f in flows):
                flow = detect_flow(last, cur, today)
                if flow:
                    _write(FLOWS, flows + [flow])
        _write(_path(today), cur)
    return True


def first_seen():
    """{isin: first day the position appears in the history} (the Fineco export has no purchase dates)."""
    out = {}
    with _lock:
        for d in _days():
            for p in _read(d)["positions"]:
                out.setdefault(p["isin"], d)
    return out


# ---------------------------------------------------------------- performance

def _bench_series(start):
    """{key: daily closes in EUR (dividends included)} from a few days before start; refreshed every 15 minutes."""
    if _bench["start"] == start and time.time() - _bench["at"] < 900 and _bench["data"]:
        return _bench["data"]
    from server import download
    tickers = [t for t, _, _ in BENCH.values()] + [portfolio.FX]
    data = download(tickers, start=(date.fromisoformat(start) - timedelta(days=10)).isoformat(), interval="1d")
    out = {}
    fx = data[portfolio.FX]["Close"].dropna() if portfolio.FX in data else None
    for key, (t, cur, _) in BENCH.items():
        if t not in data:
            continue
        c = data[t]["Close"].dropna()
        if cur == "USD":
            if fx is None:
                continue
            c = c / fx.reindex(c.index, method="ffill")
        c.index = pd.to_datetime(c.index).tz_localize(None).normalize()
        out[key] = c
    _bench.update(at=time.time(), start=start, data=out)
    return out


def performance():
    """For /api/portfolio/history: daily points with the time-weighted index of the portfolio and of the references."""
    with _lock:
        days = _days()
        pics = [_read(d) for d in days]
        flows = _flows()
    if not pics:
        return {"points": [], "flows": [], "limits": [{"title": a, "text": b} for a, b in LIMITS]}
    by_day = {}
    for f in flows:
        by_day[f["date"]] = by_day.get(f["date"], 0) + f["amount"]
    try:
        bench = _bench_series(days[0])
    except Exception:
        log.exception("portfolio history: references not available")
        bench = {}
    base = {}
    idx, prev, points = 1.0, None, []
    for p in pics:
        flow = by_day.get(p["date"], 0)
        if prev:                                             # the day's return on the money that was already there
            idx *= (p["value"] - flow) / prev["value"] if prev["value"] else 1
        pt = {"date": p["date"], "value": p["value"], "cost": p["cost"], "flow": flow, "rebuilt": bool(p.get("rebuilt")), "twr": idx}
        for key, s in bench.items():
            s = s[s.index <= pd.Timestamp(p["date"])]
            v = float(s.iloc[-1]) if len(s) else None
            base.setdefault(key, v)
            pt[key] = v / base[key] if v and base[key] else None
        points.append(pt)
        prev = p
    return {"points": points, "flows": [{k: v for k, v in f.items() if k != "details"} | {"n": len(f["details"])} for f in flows],
            "bench": {k: v[2] for k, v in BENCH.items()}, "short": len(points) < SHORT_DAYS, "shortDays": SHORT_DAYS,
            "limits": [{"title": a, "text": b} for a, b in LIMITS]}
