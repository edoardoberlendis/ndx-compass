"""Stato dei cinque diari prospettici (Fase 6C, diario delle decisioni dalla Fase 7A), SOLO LETTURA.

    .venv/bin/python diaries_status.py          # testo per il Terminale
    .venv/bin/python diaries_status.py --json   # lo stesso in JSON (è anche /api/diaries/status)

Per ogni diario: file e tabelle, dipendenze, condizioni di registrazione, versione attuale del modello, gestione delle
date e dei doppioni, registrazioni ufficiali ed escluse (prove, test, anteprime: restano nel file ma non entrano nelle
statistiche), ultima seduta registrata, sedute mancanti e prossimo aggiornamento. Ogni lettura apre il database in sola
lettura (mode=ro): questo comando non crea, non modifica e non blocca mai i diari."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import app_env
import opportunity_diary as od

ET = ZoneInfo("America/New_York")
ROME = ZoneInfo("Europe/Rome")
EVENING_PLIST = os.path.expanduser("~/Library/LaunchAgents/com.nasdaq100.daily.plist")

DIARIES = [
    {"key": "opportunity", "name": "Diario delle opportunità", "module": "opportunity_diary.py", "runs": "runs",
     "obs": "observations", "extra": ["outcomes", "universe_medians"], "calendar": "NYSE",
     "depends": "nessuno (è il primo: avvia il file)",
     "when": "dopo la chiusura NYSE + 15 minuti, con lo storico aggiornato dopo la chiusura; mai a mercato aperto o in pre-apertura",
     "dates": "seduta NYSE (ora di New York); ora del calcolo con fuso orario; prezzo = chiusura rettificata della seduta"},
    {"key": "investment", "name": "Diario dell'analisi fondamentale", "module": "investment_diary.py", "runs": "inv_runs",
     "obs": "inv_observations", "extra": [], "calendar": "NYSE",
     "depends": "diario delle opportunità della stessa seduta (registrato prima)",
     "when": "stessa seduta già registrata dal diario delle opportunità; trend con i prezzi di quella seduta",
     "dates": "seduta NYSE; date dei bilanci e di pubblicazione salvate per ogni titolo"},
    {"key": "valuation", "name": "Diario delle valutazioni", "module": "valuation_diary.py", "runs": "val_runs",
     "obs": "val_observations", "extra": [], "calendar": "NYSE",
     "depends": "diario delle opportunità della stessa seduta (registrato prima)",
     "when": "stessa seduta già registrata dal diario delle opportunità; solo prezzi di chiusura di quella seduta",
     "dates": "seduta NYSE; data del prezzo di chiusura e dei dati di base per ogni titolo"},
    {"key": "etf", "name": "Diario dello scanner ETF", "module": "etf_opportunity_diary.py", "runs": "etf_runs",
     "obs": "etf_observations", "extra": [], "calendar": "Borsa Italiana / Xetra (date della serie di riferimento VWCE)",
     "depends": "nessuno (ma richiede che il file del diario esista già)",
     "when": "prezzi ETF scaricati dopo le 18:00 (Roma) della seduta; seduta = ultima data della serie di VWCE; ogni serie "
             "deve arrivare alla stessa data (altrimenti l'esposizione porta la nota)",
     "dates": "seduta di Borsa Italiana; ora del download dei prezzi con fuso orario; data del prezzo per ogni classe; date "
              "di duration e rendimento degli obbligazionari separate da quella del prezzo"},
    {"key": "decision", "name": "Diario delle decisioni", "module": "decision_diary.py", "runs": "dec_runs",
     "obs": "dec_observations", "extra": [], "calendar": "NYSE (righe ETF solo con la stessa seduta dello scanner ETF)",
     "depends": "diario delle opportunità della stessa seduta (registrato prima); righe ETF solo se lo scanner ETF usa la "
                "stessa seduta con prezzi di chiusura definitivi",
     "when": "nella catena serale, dopo il diario delle valutazioni; una sola versione del Decision Desk per seduta",
     "dates": "seduta NYSE; per ogni decisione le date dei dati usati (prezzo, bilanci, stime, benchmark, duration)"},
]
DUPLICATES = ("chiave primaria (seduta, versione del modello) + controllo e inserimento nella stessa transazione "
              "BEGIN IMMEDIATE: la seconda registrazione della stessa seduta (anche se server e job serale partono insieme) "
              "trova la prima e non scrive nulla; un errore annulla tutta la giornata (nessun salvataggio parziale)")


def _ro(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _versions():
    out = {}
    for key, mod, attr in (("opportunity", "opportunity_scanner", "MODEL_VERSION"), ("investment", "investment_engine", "VERSION"),
                           ("valuation", "investment_valuation", "VERSION"), ("etf", "etf_opportunity", "VERSION"),
                           ("decision", "investment_decision_engine", "VERSION")):
        try:
            out[key] = getattr(__import__(mod), attr)
        except Exception as e:           # a broken module must not hide the state of the others
            out[key] = f"non leggibile ({type(e).__name__})"
    return out


READY_MIN = 20     # server.last_closed_session: a session counts as closed 20 minutes after the NYSE close


def ready_at(day):
    """When the server starts recording `day` (NYSE close + 20 minutes, ET)."""
    import market_calendar
    d = datetime.fromisoformat(day).replace(tzinfo=ET)
    return d + timedelta(minutes=market_calendar.close_minute(d) + READY_MIN)


def last_nyse_session(now):
    """The last NYSE session the server already treats as closed (close + 20 minutes, as server.last_closed_session)."""
    import market_calendar
    d = now.astimezone(ET).date()
    for _ in range(15):
        if market_calendar.is_trading_day(d) and now >= ready_at(d.isoformat()):
            return d.isoformat()
        d -= timedelta(days=1)
    return None


PRE_MARKET_MIN = 4 * 60    # NYSE pre-market from 04:00 ET: from then on the server no longer records the previous session


def recordable_until(day):
    """Last moment the server can still record `day`: the start of the pre-market of the next NYSE session. The evening
    chain never runs with the market open or in pre-market; between the next close and close + 20 minutes `day` is
    still the "last closed session", and from Phase 7C server.save_opportunity_diary refuses it there too (on 5 Nov
    2026 at 16:00 ET the decisions of 4 Nov had been recorded with the data of 5 Nov)."""
    import market_calendar
    d = datetime.fromisoformat(day).date() + timedelta(days=1)
    for _ in range(15):
        if market_calendar.is_trading_day(d):
            return datetime(d.year, d.month, d.day, tzinfo=ET) + timedelta(minutes=PRE_MARKET_MIN)
        d += timedelta(days=1)
    return None


def next_text(last, last_closed, now):
    """What the next record will be, said without promising what cannot happen: a session whose window has passed is
    never recorded later (no retroactive records)."""
    nxt = next_nyse_close(now) or "n.d."
    if not last_closed:
        return None
    if last and last["session"] == last_closed:
        return "prossima seduta: " + nxt
    until = recordable_until(last_closed)
    open_window = until is not None and now < until
    if not last:
        start = (f"la seduta {last_closed} si può ancora registrare con il server acceso entro le "
                 f"{until.astimezone(ET):%H:%M} di New York del {until.date().isoformat()}" if open_window else
                 f"la seduta {last_closed} non è stata registrata e non verrà recuperata (nessuna registrazione retroattiva)")
        return (f"nessuna registrazione ufficiale finora: il diario registra in avanti dalla prima seduta utile; {start}; "
                f"prossima seduta: {nxt}")
    if open_window:
        return (f"seduta {last_closed} non ancora registrata: la registra il server acceso entro le "
                f"{until.astimezone(ET):%H:%M} di New York del {until.date().isoformat()} (o il job serale)")
    return (f"seduta {last_closed} non registrata e non più recuperabile (nessuna registrazione retroattiva): "
            f"resta tra le sedute mancanti; prossima seduta: {nxt}")


def nyse_sessions(first, last):
    import market_calendar
    if not first or not last or first > last:
        return []
    d, end, out = datetime.fromisoformat(first).date(), datetime.fromisoformat(last).date(), []
    while d <= end:
        if market_calendar.is_trading_day(d):
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def next_nyse_close(now):
    import market_calendar
    d = now.astimezone(ET).date()
    for _ in range(15):
        if market_calendar.is_trading_day(d) and ready_at(d.isoformat()) > now:
            t = ready_at(d.isoformat())
            return f"{d.isoformat()} dopo le {t:%H:%M} di New York ({t.astimezone(ROME):%H:%M} in Italia)"
        d += timedelta(days=1)
    return None


def late_record(session, computed_at):
    """True when a NYSE session was recorded after its window (recordable_until): part of its inputs (statements,
    estimates, base market data) may be those of the moment of the record, not of the session. Read only:
    the record stays in the file as it is; it is only declared."""
    until = recordable_until(session)
    try:
        at = datetime.fromisoformat(computed_at)
    except (TypeError, ValueError):
        return False
    return until is not None and at.tzinfo is not None and at >= until


def _diary(con, d):
    runs_all = con.execute(f"SELECT session, model_version, computed_at, source FROM {d['runs']} ORDER BY session").fetchall()
    obs = {(r[0], r[1]): r[2] for r in con.execute(f"SELECT session, model_version, COUNT(*) FROM {d['obs']} GROUP BY 1, 2")}
    off = [r for r in runs_all if app_env.classify(r["source"]) == "produzione"]
    late = [] if d["key"] == "etf" else [r for r in off if late_record(r["session"], r["computed_at"])]
    exc = [r for r in runs_all if app_env.classify(r["source"]) != "produzione"]
    last = off[-1] if off else None
    return {"tables": [d["runs"], d["obs"]] + d["extra"],
            "official": {"runs": len(off), "observations": sum(obs.get((r["session"], r["model_version"]), 0) for r in off),
                         "sessions": sorted({r["session"] for r in off})},
            "excluded": {"runs": len(exc), "observations": sum(obs.get((r["session"], r["model_version"]), 0) for r in exc),
                         "items": [{"session": r["session"], "version": r["model_version"], "source": r["source"],
                                    "computedAt": r["computed_at"], "class": app_env.classify(r["source"]),
                                    "observations": obs.get((r["session"], r["model_version"]), 0)} for r in exc]},
            "last": {"session": last["session"], "version": last["model_version"], "computedAt": last["computed_at"],
                     "source": last["source"], "observations": obs.get((last["session"], last["model_version"]), 0)} if last else None,
            "versionsRecorded": sorted({r["model_version"] for r in runs_all}),
            "late": [{"session": r["session"], "version": r["model_version"], "computedAt": r["computed_at"],
                      "observations": obs.get((r["session"], r["model_version"]), 0)} for r in late],
            "incomplete": [f"{s} {v}: registrazione senza osservazioni" for (s, v) in
                           {(r["session"], r["model_version"]) for r in runs_all} if not obs.get((s, v))]}


def etf_sessions_after(first, prices):
    """Sessions of the ETF reference series (VWCE) after `first`, up to its last date: the calendar the ETF diary
    follows (holidays of Borsa Italiana are absent from the series, so they are never 'missing')."""
    import etf_opportunity as eo
    s = ((prices or {}).get("closes") or {}).get(eo.B_WORLD_ALL)
    if s is None or not len(s):
        return []
    return [str(t.date()) for t in s.index if str(t.date()) > first]


def status(now=None, path=None):
    """Read-only state of the five diaries (dict). Never writes."""
    now = now or datetime.now(ET)
    path = path or od.DB
    vers = _versions()
    out = {"generatedAt": now.isoformat(timespec="seconds"), "path": path, "environment": app_env.describe(),
           "officialSources": list(app_env.OFFICIAL_SOURCES), "duplicates": DUPLICATES,
           "eveningJob": "installato (launchd 22:45)" if os.path.exists(EVENING_PLIST) else
                         "non installato: si registra solo con la dashboard accesa",
           "diaries": [], "problems": []}
    exists = os.path.exists(path)
    data = {}
    if exists:
        with closing(_ro(path)) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for d in DIARIES:
                data[d["key"]] = _diary(con, d) if d["runs"] in tables else None
    for d in DIARIES:
        x = data.get(d["key"])
        row = {k: d[k] for k in ("key", "name", "module", "calendar", "depends", "when", "dates")}
        row.update(version=vers[d["key"]], started=bool(x and (x["official"]["runs"] or x["excluded"]["runs"])), state=None,
                   official={"runs": 0, "observations": 0}, excluded={"runs": 0, "observations": 0, "items": []}, last=None,
                   missing=[], next=None, errors=[])
        if x:
            row.update(tables=x["tables"], official={k: x["official"][k] for k in ("runs", "observations")}, excluded=x["excluded"],
                       last=x["last"], versionsRecorded=x["versionsRecorded"], late=x["late"])
            row["errors"] += x["incomplete"]
            row["notes"] = [f"seduta {i['session']} ({i['version']}, {i['observations']} osservazioni) registrata in ritardo, il "
                            f"{i['computedAt'][:16].replace('T', ' ')} (dopo la pre-apertura della seduta successiva): una parte "
                            "dei dati (bilanci, stime, dati di mercato di base) può essere quella del momento della "
                            "registrazione, non della seduta; resta nel file com'è, da leggere con questa avvertenza" for i in x["late"]]
        out["diaries"].append(row)
    by = {r["key"]: r for r in out["diaries"]}
    # NYSE diaries: missing official sessions from the first official one to the last closed session
    last_closed = last_nyse_session(now)
    opp = data.get("opportunity")
    if opp and opp["official"]["sessions"]:
        sessions = nyse_sessions(opp["official"]["sessions"][0], last_closed)
        by["opportunity"]["missing"] = [s for s in sessions if s not in set(opp["official"]["sessions"])]
        for k in ("investment", "valuation", "decision"):
            have = set((data.get(k) or {}).get("official", {}).get("sessions", []))
            first = min(have) if have else None
            by[k]["missing"] = [s for s in opp["official"]["sessions"] if first and s >= first and s not in have]
    for k in ("opportunity", "investment", "valuation", "decision"):
        r = by[k]
        r["next"] = next_text(r["last"], last_closed, now)
        if k != "opportunity" and r["last"] and r["last"]["version"] != vers[k]:
            r["errors"].append(f"ultima registrazione con la versione {r['last']['version']}, il modello attuale è {vers[k]}")
    # ETF diary: calendar of the reference series; a session taken by an excluded record is declared, never rewritten
    try:
        import etf_prices
        prices = etf_prices.load()
    except Exception:
        prices = None
    e = by["etf"]
    ex = data.get("etf")
    taken = {i["session"]: i["version"] for i in e["excluded"]["items"]}     # any version: a session is recorded once
    if ex and ex["official"]["sessions"]:
        e["missing"] = [s for s in etf_sessions_after(ex["official"]["sessions"][0], prices) if s not in set(ex["official"]["sessions"])
                        and s not in taken]
    if taken:
        e["notes"] = e.get("notes", []) + [f"seduta {s} occupata da una registrazione di prova con la versione {v}: resta nel file, "
                      "esclusa dalle statistiche; non si registra una seconda volta (idempotenza, anche con una versione "
                      f"più recente): il diario ufficiale riparte dalla prima seduta successiva" for s, v in sorted(taken.items())]
    fetched = (prices or {}).get("fetched")
    if not prices:
        e["next"] = "prezzi ETF non in cache: arrivano in background dopo la chiusura (server acceso)"
    else:
        due = etf_prices.due(prices, now.astimezone(ROME))
        mark = etf_prices.close_mark(now.astimezone(ROME))
        e["next"] = (f"prezzi scaricati il {fetched[:10]} alle {fetched[11:16]}: " + ("da riscaricare dopo la chiusura del " + str(mark.date()) if due else
                     "aggiornati all'ultima chiusura") + "; registrazione al primo giro del server dopo il download")
    for r in out["diaries"]:
        r["state"] = ("errori" if r["errors"] else "sedute mancanti" if r["missing"] else
                      "in funzione" if r["official"]["runs"] else "nessuna registrazione ufficiale")
    if not exists:
        out["problems"].append("diario delle opportunità non ancora avviato")
    out["summary"] = {"officialObservations": sum(r["official"]["observations"] for r in out["diaries"]),
                      "excludedObservations": sum(r["excluded"]["observations"] for r in out["diaries"]),
                      "missing": sum(len(r["missing"]) for r in out["diaries"]),
                      "lastSession": max((r["last"]["session"] for r in out["diaries"] if r["last"]), default=None)}
    return out


def text(s):
    lines = [f"Stato dei diari ({s['generatedAt']}) — ambiente {s['environment']['env']}, file {s['path']}",
             f"Job serale: {s['eveningJob']}", f"Origini ufficiali: {', '.join(s['officialSources'])}", ""]
    for r in s["diaries"]:
        lines.append(f"■ {r['name']} ({r['module']}) — {r['state']}, modello {r['version']}")
        lines.append(f"  ufficiali: {r['official']['runs']} sedute, {r['official']['observations']} osservazioni; "
                     f"escluse: {r['excluded']['runs']} sedute, {r['excluded']['observations']} osservazioni; "
                     f"versioni presenti: {', '.join(r.get('versionsRecorded') or []) or 'nessuna'}")
        if r["last"]:
            lines.append(f"  ultima ufficiale: {r['last']['session']} ({r['last']['source']}, {r['last']['computedAt']}, "
                         f"{r['last']['observations']} osservazioni)")
        for i in r["excluded"]["items"]:
            lines.append(f"  esclusa: {i['session']} {i['version']} origine «{i['source']}» ({i['class']}), {i['observations']} osservazioni")
        for n in r.get("notes", []):
            lines.append("  nota: " + n)
        if r["missing"]:
            lines.append("  sedute mancanti: " + ", ".join(r["missing"]))
        for er in r["errors"]:
            lines.append("  ⚠ " + er)
        if r["next"]:
            lines.append("  prossimo: " + r["next"])
        lines.append(f"  dipende da: {r['depends']}; registra: {r['when']}")
    lines += ["", "Doppioni: " + s["duplicates"]]
    return "\n".join(lines)


if __name__ == "__main__":
    st = status()
    print(json.dumps(st, ensure_ascii=False, indent=1) if "--json" in sys.argv else text(st))
