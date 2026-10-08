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
EXCLUDED = os.path.join(DIR, "esclusi.json")     # {"AAAA-MM-GG": "reason"}: days left out of the statistics, never modified
READY_SESSIONS = 63                               # the Diario page is shown only with about 3 months of data (phase 21)
RULE_ORDER = ["D1", "D2", "D3", "D4", "D5", "D6", "D7"]   # D3 (weight limits) was removed in phase 21: kept for older days
RULE_NAMES = {"dati": "dati insufficienti", "D1": "azienda debole (D1)", "D2": "trimestrale vicina (D2)", "D3": "miei limiti di peso (D3, regola tolta)",
              "D4": "sotto la media 200 (D4)", "D5": "titolo tirato (D5)", "D6": "a ridosso del massimo (D6)", "D7": "azienda nella media, prezzo non a sconto (D7)",
              "tutte": "tutte le regole soddisfatte", "posizione": "regole delle mie posizioni"}
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


def excluded():
    """{day: reason} of the days left out of the statistics (the files themselves are never touched)."""
    try:
        with open(EXCLUDED) as f:
            return json.load(f)
    except Exception:
        return {}


def missing(last_session):
    """NYSE sessions from the first diary day to last_session (ISO dates) without a diary file."""
    import market_calendar
    from datetime import date, timedelta
    ds = days()
    if not ds:
        return []
    d, end, have, out = date.fromisoformat(ds[0]), date.fromisoformat(last_session), set(ds), []
    while d <= end:
        if market_calendar.is_trading_day(d) and d.isoformat() not in have:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


_index = {"key": None, "data": {}}


def verdict_history(ticker):
    """[(day, verdict label, price)] of one stock in the saved days, newest first, without the excluded days.
    The files are only read (an index is kept in memory and rebuilt when a day is added)."""
    ds, skip = days(), excluded()
    key = (tuple(ds), tuple(sorted(skip)))
    if _index["key"] != key:
        data = {}
        for d in ds:
            if d in skip:
                continue
            try:
                with open(_path(d)) as f:
                    for e in json.load(f)["entries"]:
                        data.setdefault(e["ticker"], []).append((d, e["verdict"], e["price"]))
            except Exception:
                continue
        for v in data.values():
            v.sort(reverse=True)
        _index.update(key=key, data=data)
    return _index["data"].get(ticker, [])


def since(label, price, today, history, first_day):
    """Since when the verdict is the same: the first day of the run of consecutive saved days with this label, going
    back from today (today's live verdict counts even if not saved yet). history: [(day, label, price)] newest first.
    Returns {"date", "price", "today": the run starts today, "atLeast": the run reaches the first day of the diary}."""
    start = (today, price)
    for d, lab, p in history:
        if d > today:
            continue
        if lab != label:
            break
        start = (d, p)
    return {"date": start[0], "price": start[1], "today": start[0] == today,
            "atLeast": bool(first_day) and start[0] == first_day and start[0] != today}


def decided_by(e):
    """The rule that decided a saved verdict: the first one not satisfied, in order (also for days saved before
    phase 21, from the rules stored that day; the files are only read)."""
    if e.get("decidedBy"):
        return e["decidedBy"]
    if e.get("owned"):
        return "posizione"
    rules = {r["id"]: r["ok"] for r in e.get("rules") or []}
    if not rules:
        return "dati"
    if rules.get("D1") is None:
        return "dati"
    for rid in RULE_ORDER:
        if rules.get(rid) is False:
            return rid
    return "tutte"


def entry(decision=None, position=None):
    """One line of the diary from a "Decisione" sheet (index stock) and/or one of my positions."""
    if decision:
        v = decision["verdict"]
        key = v.get("plan")
        plans = decision["plans"]
        p = (next((b for b in plans.get("breakouts") or [] if b["pattern"] == v.get("pattern")), None) if key == "breakout" else plans.get(key)) if key else None
        return {"ticker": decision["ticker"], "price": decision["price"], "verdict": v["label"], "category": v["category"], "owned": v["owned"],
                "index": True, "why": v["why"], "company": decision["company"]["summary"], "companyScore": decision["company"]["score"], "decidedBy": v.get("decidedBy"),
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
    skip = excluded()
    ds = [d for d in days() if d not in skip]
    out = {"days": len(ds), "first": ds[0] if ds else None, "last": ds[-1] if ds else None, "minCases": MIN_CASES, "minDays": MIN_DAYS,
           "excluded": [{"date": d, "why": w} for d, w in sorted(skip.items())],
           "horizons": {}, "byRule": {}, "pending": {}, "today": [], "limits": [{"title": a, "text": b} for a, b in LIMITS]}
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
    def stats(key, cs):
        ret, ex, va = [c[1] for c in cs], [c[2] for c in cs], [c[3] for c in cs]
        nd = len({c[0] for c in cs})
        return {**key, "n": len(cs), "days": nd, "enough": len(cs) >= MIN_CASES and nd >= MIN_DAYS,
                "ret": statistics.fmean(ret), "retMedian": statistics.median(ret),
                "excess": statistics.fmean(ex), "excessMedian": statistics.median(ex), "beat": sum(x > 0 for x in ex) / len(ex) * 100,
                "vsAll": statistics.fmean(va), "vsAllMedian": statistics.median(va), "beatAll": sum(x > 0 for x in va) / len(va) * 100}

    for name, h in HORIZONS.items():
        cases, by_rule = {}, {}
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
                    rows.append((e["category"], decided_by(e), (s[end] / s[d] - 1) * 100))
            if not rows:
                continue
            measured_days += 1
            rq = (q[end] / q[d] - 1) * 100
            avg = statistics.fmean(r for _, _, r in rows)
            for cat, rule, r in rows:
                case = (d, r, r - rq, r - avg)
                cases.setdefault(cat, []).append(case)
                by_rule.setdefault((cat, rule), []).append(case)
        table = [stats({"category": cat}, cases[cat]) for cat in ORDER if cases.get(cat)]
        rules_table = [stats({"category": cat, "rule": rule, "ruleName": RULE_NAMES.get(rule, rule)}, cs)
                       for (cat, rule), cs in sorted(by_rule.items(), key=lambda kv: (ORDER.index(kv[0][0]) if kv[0][0] in ORDER else 99, kv[0][1]))]
        out["horizons"][name] = {"sessions": h, "days": measured_days, "rows": table, "byRule": rules_table}
        k0 = pos.get(ds[0])
        out["pending"][name] = max(0, k0 + h - (len(cal) - 1)) if k0 is not None else h
    return out
