"""Riepilogo del giorno e stato del sistema (Fase 8B). SOLO LETTURA.

Mette insieme ciò che esiste già: il registro degli alert (alert_engine.read), lo stato dei cinque diari
(diaries_status.status), i giri del job serale (job_status) e le date degli aggiornamenti. Nessun download, nessuna
scrittura, nessun nuovo modello, nessun punteggio, nessun compra/vendi, mai il portafoglio personale.

Regole:
- l'ultima seduta elaborata è l'ultima seduta NYSE registrata dal primo diario della catena (opportunità); il giorno è
  «completo» solo con tutti e cinque i diari registrati (ETF: la sua seduta di Borsa Italiana dello stesso giorno);
- gli eventi del riepilogo sono soltanto gli alert «nuovi» di quella seduta, critici o importanti, al massimo MAX_EVENTS
  (mai riempiti con altro); gli eventi storici rilevati all'attivazione del registro stanno a parte;
- «Nessun cambiamento rilevante rilevato nell'ultima seduta elaborata.» vale solo con il riepilogo aggiornato; altrimenti
  «Riepilogo non aggiornato» con il motivo: le due frasi non si confondono mai;
- problemi operativi e di dati separati dagli eventi finanziari;
- le registrazioni escluse (diary_exclusions.json) non entrano: gli alert leggono già solo quelle ammissibili.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

NO_CHANGE = "Nessun cambiamento rilevante rilevato nell'ultima seduta elaborata."
NOT_UPDATED = "Riepilogo non aggiornato"
MAX_EVENTS = 7
CHAIN = ("opportunity", "investment", "valuation", "decision")
FINANCIAL_FAMILIES = {"AZ-RISCHIO": "rischi", "ETF-RISCHIO": "rischi", "ETF-CONCENTRAZIONE": "rischi"}
DISCLAIMER = ("Riepilogo informativo di analisi già registrate: descrive cosa è cambiato, non cosa accadrà. Nessuna voce è un "
              "invito a comprare o vendere. Non è consulenza finanziaria.")
_fund = {"key": None, "value": None}


def _section(a):
    """azioni / etf / fondamentali e DCF / rischi / dati e aggiornamento, from the rule of the alert."""
    r = a.get("rule") or ""
    if a.get("kind") == "condizione" or a.get("scope") == "operativo" or r in ("AZ-DATI", "ETF-DATI", "ETF-PRODOTTO"):
        return "dati"
    if r in FINANCIAL_FAMILIES:
        return "rischi"
    if r.startswith("AZ-FOND") or r.startswith("AZ-DCF"):
        return "fondamentali"
    return "etf" if a.get("scope") == "etf" else "azioni"


def card(a):
    """One card of the brief: instrument, what changed, before/after, why, effective date of the data, limits, link."""
    t = a.get("timeline") or {}
    extra = a.get("extra") or {}
    c = {"id": a["id"], "rule": a["rule"], "priority": a["priority"], "instrument": a["instrument"], "name": a.get("name"),
         "what": a.get("title"), "before": a.get("previous"), "after": a.get("current"), "why": a.get("reason"),
         "session": a.get("session"), "previousSession": (a.get("model") or {}).get("previousSession"),
         "dataDate": {"session": a.get("session"), "period": t.get("period"), "published": t.get("published"),
                      "publishedVerified": False, "acquired": t.get("acquired"), "headline": t.get("headline")},
         "limits": list(a.get("limits") or []), "link": a.get("link") or {}, "section": _section(a),
         "model": a.get("model") or {}, "exploratory": bool(a.get("exploratory"))}
    if extra.get("causes"):                       # DCF: price effect and assumption/statement effect kept apart
        c["causes"] = {"prezzo": extra["causes"].get("prezzo"), "ipotesi e bilanci": extra["causes"].get("ipotesi e bilanci")}
    if a.get("rule") == "ETF-TREND" or a.get("exploratory"):
        c["limits"].append("trend esplorativo: condizioni non validate, non è un segnale")
    if extra.get("grouped"):
        c["grouped"] = (a.get("current") or {}).get("società")
    return c


def _diary_rows(diaries):
    return {r["key"]: r for r in (diaries or {}).get("diaries") or []}


def _chain_state(diaries, session):
    """State of each of the five diaries for `session` (ETF: its own calendar, same date)."""
    rows = _diary_rows(diaries)
    out = []
    for key in CHAIN + ("etf",):
        r = rows.get(key) or {}
        last = r.get("last") or {}
        adm = r.get("admissible") or {}
        sessions = set(adm.get("sessions") or [])
        if not r:
            state = "diario non disponibile"
        elif session and session in sessions:
            state = "registrata"
        elif key == "etf" and session and last.get("session") and last["session"] < session:
            state = "non registrata (seduta ETF ancora mancante o festiva in Italia)"
        elif session and key != "etf" and session in (r.get("missing") or []):
            state = "mancante"
        elif not last:
            state = "nessuna registrazione ufficiale"
        else:
            state = "non registrata"
        out.append({"key": key, "name": r.get("name") or key, "version": r.get("version"), "lastSession": last.get("session"),
                    "lastComputedAt": last.get("computedAt"), "lastSource": last.get("source"), "state": state,
                    "next": r.get("next"), "errors": list(r.get("errors") or []), "missing": list(r.get("missing") or []),
                    "official": r.get("official") or {}, "admissible": {"runs": adm.get("runs", 0), "observations": adm.get("observations", 0)},
                    "registryExcluded": [{"id": x.get("id"), "session": x.get("session"), "reason": x.get("reason"),
                                          "observations": x.get("observations")} for x in r.get("registryExcluded") or []]})
    return out


def build(now, alerts, diaries, runs=None, feeds=None):
    """The daily brief (dict). alerts = alert_engine.read(); diaries = diaries_status.status(now); runs = job_status.read();
    feeds = dates of the updates known to the server ({"prices", "fundamentals", "etfPrices", "alertCheck"})."""
    alerts = alerts or {}
    rows = _diary_rows(diaries)
    opp = rows.get("opportunity") or {}
    session = (opp.get("last") or {}).get("session")
    last_closed = None
    try:
        import diaries_status
        last_closed = diaries_status.last_nyse_session(now)
    except Exception:
        pass
    chain = _chain_state(diaries, session)
    complete = bool(session) and all(c["state"] == "registrata" for c in chain)
    reasons = []
    if not session:
        reasons.append("nessuna seduta registrata nei diari")
    elif last_closed and session < last_closed:
        nxt = opp.get("next")
        reasons.append(f"l'ultima seduta chiusa è il {last_closed}, i diari arrivano al {session}" + (f" ({nxt})" if nxt else ""))
    missing_now = [c["name"] for c in chain if c["state"] != "registrata"] if session else []
    if session and missing_now:
        reasons.append(f"seduta {session}: " + ("manca" if len(missing_now) == 1 else "mancano") + " " + ", ".join(missing_now))
    run = alerts.get("lastRun")
    if not alerts.get("started") or not run:
        reasons.append("registro degli alert non ancora avviato: nessun confronto disponibile")
    else:
        seen = {k: (v.get("last") or {}).get("session") for k, v in ((run.get("inputs") or {}).get("diaries") or {}).items()}
        if session and not any(v == session for v in seen.values() if v):
            reasons.append(f"il controllo degli alert ({run['at'][:16].replace('T', ' ')}) non ha ancora letto la seduta {session}")
    up_to_date = not reasons
    # events: new alerts of the latest processed session, never the historical ones found at activation
    act = [a for a in alerts.get("alerts") or [] if a.get("active")]
    of_session = [a for a in act if a.get("status") == "nuovo" and a.get("kind") == "evento" and a.get("session") == session]
    historical = [a for a in of_session if (a.get("timeline") or {}).get("atActivation")]
    current = [a for a in of_session if not (a.get("timeline") or {}).get("atActivation")]
    important = [a for a in current if a.get("priority") in ("critica", "importante")]
    ordinary = [a for a in current if a.get("priority") not in ("critica", "importante")]
    prio = {"critica": 0, "importante": 1}
    important.sort(key=lambda a: (prio.get(a["priority"], 2), _section(a) == "dati", a.get("name") or ""))
    events = [card(a) for a in important[:MAX_EVENTS]]
    data_issues = [card(a) for a in act if _section(a) == "dati" and a.get("status") in ("nuovo", "persistente", "baseline")]
    if up_to_date and not events:
        message = NO_CHANGE
    elif not up_to_date:
        message = NOT_UPDATED
    else:
        message = None
    counts = alerts.get("counts") or {}
    return {
        "generatedAt": now.isoformat(timespec="seconds"), "session": session, "lastClosedSession": last_closed,
        "complete": complete, "upToDate": up_to_date, "message": message, "reasons": reasons,
        "diaries": chain,
        "alerts": {"newOfSession": len(current), "important": len(important), "ordinary": len(ordinary),
                   "shown": len(events), "more": max(0, len(important) - MAX_EVENTS), "historicalAtActivation": len(historical),
                   "activeTotal": counts.get("active", 0), "lastCheck": run.get("at") if run else None},
        "events": events,
        "sections": {k: [e for e in events if e["section"] == k] for k in ("azioni", "etf", "fondamentali", "rischi")},
        "historical": [card(a) for a in historical[:MAX_EVENTS]], "historicalMore": max(0, len(historical) - MAX_EVENTS),
        "dataIssues": data_issues[:MAX_EVENTS], "dataIssuesMore": max(0, len(data_issues) - MAX_EVENTS),
        "health": health(now, alerts, diaries, runs, feeds, chain),
        "disclaimer": DISCLAIMER,
        "rules": {"maxEvents": MAX_EVENTS, "priorities": "solo alert «nuovi» critici o importanti della seduta elaborata; "
                  "la priorità dipende dal tipo di evento (regole degli alert), mai da un punteggio",
                  "noChange": NO_CHANGE, "notUpdated": NOT_UPDATED},
    }


def fundamentals_date(path=None):
    """Most recent download of statements (fetchedAt in cache/fundamentals.json), cached by file time; None if unknown."""
    try:
        import fundamentals
        p = path or fundamentals.CACHE
        mt = os.path.getmtime(p)
    except Exception:
        return None
    if _fund["key"] == (p, mt):
        return _fund["value"]
    try:
        with open(p, encoding="utf-8") as f:
            data = (json.load(f) or {}).get("data") or {}
        v = max((e.get("fetchedAt") for e in data.values() if isinstance(e, dict) and e.get("fetchedAt")), default=None)
    except (OSError, ValueError):
        v = None
    _fund.update(key=(p, mt), value=v)
    return v


OPEN_FILES_NA = "metrica di macOS/Linux, non disponibile su questo sistema (su Windows non esiste quel limite)"


def open_files():
    """(open, soft limit) of this process: the "Too many open files" errors of the past came from the default 256."""
    try:
        import resource
        soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    except Exception:
        soft = None
    try:
        n = len(os.listdir("/dev/fd"))
    except OSError:
        n = None
    return n, soft


def health(now, alerts, diaries, runs, feeds, chain=None):
    """Stato del sistema: operational facts only (no financial event), each with its date; missing = said, never zero."""
    import job_status
    runs = runs or []
    feeds = feeds or {}
    chain = chain if chain is not None else _chain_state(diaries, None)
    done = [r for r in runs if r.get("completed")]
    last_done = done[-1] if done else None
    last_started = runs[-1] if runs else None
    interrupted = [r for r in runs if not r.get("completed") and (r.get("finishedAt") or job_status.stale(r, now))]
    errors = []
    for r in runs[-10:]:
        for s in r.get("steps") or []:
            if s.get("outcome") != "ok":
                errors.append({"at": r.get("startedAt"), "mode": r.get("mode"), "step": s.get("name"), "error": s.get("error"),
                               "note": s.get("note")})
        for p in r.get("problems") or []:
            errors.append({"at": r.get("startedAt"), "mode": r.get("mode"), "step": "protezione", "error": None, "note": p})
    for r in interrupted[-3:]:
        errors.append({"at": r.get("startedAt"), "mode": r.get("mode"), "step": "giro del job",
                       "error": r.get("error") or "non completato", "note": "giro iniziato e mai completato (Mac spento o in stop, errore)"})
    chk = feeds.get("alertCheck") or {}
    if chk.get("msg") and "non riuscito" in str(chk.get("msg")):
        errors.append({"at": chk.get("at"), "mode": "server", "step": "alert", "error": None, "note": chk["msg"]})
    for c in chain:
        for e in c["errors"]:
            errors.append({"at": None, "mode": "diari", "step": c["name"], "error": None, "note": e})
    run = (alerts or {}).get("lastRun")
    n_open, limit = open_files()
    missing = [{"diary": c["name"], "sessions": c["missing"]} for c in chain if c["missing"]]
    excluded = [{"diary": c["name"], **x} for c in chain for x in c["registryExcluded"]]
    job = (diaries or {}).get("eveningJob")
    return {
        "lastJobCompleted": {"mode": last_done.get("mode"), "startedAt": last_done.get("startedAt"), "finishedAt": last_done.get("finishedAt"),
                             "session": last_done.get("session"),
                             "stepsWithErrors": [s["name"] for s in last_done.get("steps") or [] if s.get("outcome") != "ok"]} if last_done else None,
        "lastJobStarted": {"mode": last_started.get("mode"), "startedAt": last_started.get("startedAt"),
                           "completed": bool(last_started.get("completed")),
                           "state": "completato" if last_started.get("completed") else
                                    ("interrotto" if last_started.get("finishedAt") or job_status.stale(last_started, now) else "in corso")}
                          if last_started else None,
        "jobNote": None if runs else "nessun giro del job serale registrato: i diari sono stati scritti dalla dashboard accesa (o mai)",
        "scheduler": job,
        "lastSession": (diaries or {}).get("summary", {}).get("lastSession"),
        "prices": feeds.get("prices"), "fundamentals": feeds.get("fundamentals"), "etfPrices": feeds.get("etfPrices"),
        "diaries": [{"name": c["name"], "lastSession": c["lastSession"], "lastComputedAt": c["lastComputedAt"],
                     "lastSource": c["lastSource"], "official": c["official"], "admissible": c["admissible"]} for c in chain],
        "alertCheck": {"lastRun": run.get("at") if run else None, "server": chk.get("at"), "serverMsg": chk.get("msg")},
        "errors": errors[-12:], "missing": missing, "excluded": excluded,
        "openFiles": {"open": n_open, "limit": limit,
                      "note": "limite alzato a 4096 all'avvio del server (prima 256: causa dei vecchi «Too many open files»)"
                      if limit is not None else OPEN_FILES_NA},
    }
