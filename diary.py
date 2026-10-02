"""Signal diary (plan phase 19): a live check of the verdicts, from today onwards.

Analysts, valuation and news have no free point-in-time history, so the "Decisione" verdicts cannot be backtested.
Instead, after every close the dashboard saves the verdict of each Nasdaq-100 stock and of my positions in
portafoglio/diario/AAAA-MM-GG.json (date, price, verdict, levels and the rules that produced it), and after 1, 3 and
6 months measures how each kind of verdict did against QQQ and against all the stocks of the same day.

The diary is never modified afterwards: a day's file is written once and never rewritten, not even by a later version
of the rules. Personal data (it contains my positions): only in portafoglio/, outside Git.
"""
from __future__ import annotations

import json
import os
import statistics
from datetime import datetime

import portfolio

DIR = os.path.join(portfolio.PORTFOLIO_DIR, "diario")
HORIZONS = {"1M": 21, "3M": 63, "6M": 126}       # trading sessions, as in the backtests
MIN_CASES, MIN_DAYS = 100, 20                    # below this the page says the cases are too few to conclude anything
ORDER = ["Entra ora", "Entra su ritracciamento", "Entra su rottura", "Attendi", "Evita", "Accumula", "Mantieni", "Rivedi la tesi", "Riduci"]

LIMITS = [
    ("Casi ancora pochi", f"Finché una categoria ha meno di {MIN_CASES} casi o meno di {MIN_DAYS} giorni diversi, i numeri possono essere solo caso: la pagina lo segnala e non vanno usati per decidere."),
    ("Casi non indipendenti", "Lo stesso titolo riceve spesso lo stesso verdetto per molti giorni di fila e i periodi di 1, 3 e 6 mesi si sovrappongono: le osservazioni davvero indipendenti sono molte meno dei casi contati."),
    ("Un solo tipo di mercato", "Il diario parte da ottobre 2026: per mesi vedrà un solo tipo di mercato. Un verdetto può sembrare buono solo perché il mercato è salito, o cattivo perché è sceso: per questo conta il confronto con QQQ e con tutti i titoli."),
    ("Solo titoli del Nasdaq-100 di oggi", "I titoli sono quelli nell'indice nel giorno del verdetto. Le mie posizioni fuori dall'indice sono salvate ma non entrano nelle statistiche (mancano i prezzi storici in questa pagina)."),
    ("Nessun costo, e il verdetto non è un'operazione", "Si misura il prezzo dal giorno del verdetto, senza commissioni e senza controllare se un ordine limite o condizionato sarebbe scattato."),
    ("Regole che cambiano", "Se le regole del verdetto cambiano, i giorni già salvati restano con il verdetto di allora: il diario non si modifica mai a posteriori."),
]


def _path(day):
    return os.path.join(DIR, f"{day}.json")


def days():
    if not os.path.isdir(DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(DIR) if len(f) == 15 and f.endswith(".json") and f[:4].isdigit())


def exists(day):
    return os.path.exists(_path(day))


def entry(decision=None, position=None):
    """One line of the diary from a "Decisione" sheet (index stock) and/or one of my positions."""
    if decision:
        v = decision["verdict"]
        key = v.get("plan")
        plans = decision["plans"]
        p = (next((b for b in plans.get("breakouts") or [] if b["pattern"] == v.get("pattern")), None) if key == "breakout" else plans.get(key)) if key else None
        return {"ticker": decision["ticker"], "price": decision["price"], "verdict": v["label"], "category": v["category"], "owned": v["owned"],
                "index": True, "why": v["why"], "company": decision["company"]["summary"], "companyScore": decision["company"]["score"],
                "levels": {"entry": p["entry"], "stop": p["stop"], "target": p["target"]} if p else None,
                "rules": [{"id": c["id"], "ok": c["ok"]} for c in decision["checks"]],
                "positionRules": [r["id"] for r in position["action"]["rules"] if r["state"] == "on"] if position else None}
    a = position["action"]
    return {"ticker": position.get("ticker") or position["isin"], "price": position["price"], "verdict": a.get("label") or a["action"],
            "category": a["action"], "owned": True, "index": False, "why": a["reasons"], "company": None, "companyScore": None,
            "levels": None, "rules": None, "positionRules": [r["id"] for r in a["rules"] if r["state"] == "on"]}


def save(day, entries):
    """Write the diary of a session, once. Returns False if that day is already saved (it is never rewritten)."""
    if exists(day) or not entries:
        return False
    os.makedirs(DIR, exist_ok=True)
    with open(_path(day) + ".tmp", "w") as f:
        json.dump({"date": day, "savedAt": datetime.now().isoformat(timespec="seconds"), "entries": entries}, f, ensure_ascii=False)
    os.replace(_path(day) + ".tmp", _path(day))
    return True


def results(closes, bench):
    """For /api/diary: how each kind of verdict did after 1, 3 and 6 months.
    closes: {ticker: daily closes of the index stocks}; bench: QQQ closes (its dates are the session calendar)."""
    ds = days()
    out = {"days": len(ds), "first": ds[0] if ds else None, "last": ds[-1] if ds else None, "minCases": MIN_CASES, "minDays": MIN_DAYS,
           "horizons": {}, "pending": {}, "today": [], "limits": [{"title": a, "text": b} for a, b in LIMITS]}
    if not ds:
        return out
    cal = [str(d.date()) for d in bench.index]
    pos = {d: k for k, d in enumerate(cal)}
    series = {t: dict(zip((str(d.date()) for d in s.index), s.to_numpy())) for t, s in closes.items()}
    q = dict(zip(cal, bench.to_numpy()))
    files = {}
    for d in ds:
        with open(_path(d)) as f:
            files[d] = json.load(f)["entries"]
    last = files[ds[-1]]
    counts = {}
    for e in last:
        counts[e["category"]] = counts.get(e["category"], 0) + 1
    out["today"] = [{"category": c, "n": counts[c]} for c in ORDER if c in counts]
    for name, h in HORIZONS.items():
        cases = {}
        measured_days = 0
        for d in ds:
            k = pos.get(d)
            if k is None or k + h >= len(cal):
                continue
            end = cal[k + h]
            rows = []
            for e in files[d]:
                s = series.get(e["ticker"]) if e.get("index") else None
                if s and s.get(d) and s.get(end):
                    rows.append((e["category"], (s[end] / s[d] - 1) * 100))
            if not rows:
                continue
            measured_days += 1
            rq = (q[end] / q[d] - 1) * 100
            avg = statistics.fmean(r for _, r in rows)
            for cat, r in rows:
                cases.setdefault(cat, []).append((d, r, r - rq, r - avg))
        table = []
        for cat in ORDER:
            cs = cases.get(cat)
            if not cs:
                continue
            ret, ex, va = [c[1] for c in cs], [c[2] for c in cs], [c[3] for c in cs]
            nd = len({c[0] for c in cs})
            table.append({"category": cat, "n": len(cs), "days": nd, "enough": len(cs) >= MIN_CASES and nd >= MIN_DAYS,
                          "ret": statistics.fmean(ret), "retMedian": statistics.median(ret),
                          "excess": statistics.fmean(ex), "excessMedian": statistics.median(ex), "beat": sum(x > 0 for x in ex) / len(ex) * 100,
                          "vsAll": statistics.fmean(va), "vsAllMedian": statistics.median(va), "beatAll": sum(x > 0 for x in va) / len(va) * 100})
        out["horizons"][name] = {"sessions": h, "days": measured_days, "rows": table}
        k0 = pos.get(ds[0])
        out["pending"][name] = max(0, k0 + h - (len(cal) - 1)) if k0 is not None else h
    return out
