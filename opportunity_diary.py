"""Diario delle opportunità (plan phase O2): every closed session, both rankings of opportunity_scanner.py for EVERY
stock of the universe (selected or not), then the price results measured once each horizon has really passed.

    .venv/bin/python opportunity_diary.py status    # what is recorded and what has matured
    .venv/bin/python opportunity_diary.py update    # records the last closed session (if missing) and measures the
                                                    # matured results, from the data already in cache/ (no download)

Storage: SQLite in data/opportunita.sqlite3 - public market data only, separate from portafoglio/ and from the
other diaries, outside Git (data/ is in .gitignore). Nothing personal is read or written here.

Rules (phase O2, B2 "no future information"):
- a session is recorded only when it is closed and the daily history contains its final bar; the ranking uses
  closed sessions up to that day only (opportunity_scanner.cut); the time of the computation is saved with its zone;
- runs and observations are never modified or deleted (SQLite triggers): a new model version is a new run;
- analyst, valuation and news data are saved as they were at that moment: no history is rebuilt from today's values;
- a result is measured only when the session `horizon` trading days later exists in the closed history of QQQ (the
  session calendar); price returns use the adjusted closes of that moment at BOTH ends (splits and dividends);
- the same interval is used for the stock, for QQQ and for the median of the universe recorded that day.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics
import sys
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "data", "opportunita.sqlite3")
ET = ZoneInfo("America/New_York")
LISTS = ("trading", "invest")
HORIZONS = {"trading": (5, 10, 21), "invest": (63, 126)}       # trading sessions
ALL_HORIZONS = tuple(sorted({h for hs in HORIZONS.values() for h in hs}))
MIN_CASES, MIN_DAYS = 100, 20         # same minimum as the signal diary (diary.py): below it, no averages are shown
PRICE_TYPE = "chiusura rettificata della seduta (Yahoo Finance, dividendi e frazionamenti inclusi)"
CLOSE_MARGIN_MIN = 15                 # the daily history must be refreshed at least 15 minutes after the close
GROUPS = {"top": "Primi 10 della classifica", "selected": "Tutti i titoli in classifica", "others": "Titoli non in classifica"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  session TEXT NOT NULL, model_version TEXT NOT NULL, computed_at TEXT NOT NULL, source TEXT NOT NULL,
  price_type TEXT NOT NULL, params TEXT NOT NULL, market TEXT, universe INTEGER, evaluated INTEGER, coverage TEXT,
  not_evaluable TEXT, PRIMARY KEY (session, model_version));
CREATE TABLE IF NOT EXISTS observations (
  session TEXT NOT NULL, model_version TEXT NOT NULL, list TEXT NOT NULL, ticker TEXT NOT NULL, instrument TEXT,
  name TEXT, sector TEXT, ref_price REAL, rank INTEGER, in_top INTEGER NOT NULL, ok INTEGER, n INTEGER, status TEXT,
  met TEXT, not_met TEXT, missing TEXT, conditions TEXT, warnings TEXT, main TEXT, diag TEXT, metrics TEXT,
  PRIMARY KEY (session, model_version, list, ticker),
  FOREIGN KEY (session, model_version) REFERENCES runs (session, model_version));
CREATE TABLE IF NOT EXISTS outcomes (
  session TEXT NOT NULL, ticker TEXT NOT NULL, horizon INTEGER NOT NULL, end_session TEXT NOT NULL,
  status TEXT NOT NULL, ret REAL, qqq REAL, excess REAL, measured_at TEXT NOT NULL,
  PRIMARY KEY (session, ticker, horizon));
CREATE TABLE IF NOT EXISTS universe_medians (
  session TEXT NOT NULL, horizon INTEGER NOT NULL, end_session TEXT NOT NULL, median REAL, n INTEGER,
  PRIMARY KEY (session, horizon));
CREATE TRIGGER IF NOT EXISTS runs_no_update BEFORE UPDATE ON runs BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS runs_no_delete BEFORE DELETE ON runs BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS obs_no_update BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS obs_no_delete BEFORE DELETE ON observations BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
"""

LIMITS = [
    ("Dati in raccolta", f"Le medie compaiono solo con almeno {MIN_CASES} osservazioni maturate in almeno {MIN_DAYS} giornate "
                         "diverse. Prima, qualsiasi numero può essere solo caso."),
    ("Non è un backtest", "Si misura da oggi in avanti cosa è successo ai prezzi dopo ogni classifica salvata: nessuna regola è "
                          "ancora validata e pochi casi positivi non dimostrano nulla."),
    ("Osservazioni non indipendenti", "Lo stesso titolo resta in classifica per molti giorni di fila e gli orizzonti si "
                                      "sovrappongono: le osservazioni davvero indipendenti sono molte meno di quelle contate."),
    ("Prezzo di riferimento", "Il rendimento parte dalla chiusura della seduta della classifica: nessun costo, nessuno spread, "
                              "e una classifica calcolata la sera non si può eseguire a quel prezzo."),
    ("Dati della sera", "Analisti, valutazione e notizie sono quelli disponibili al momento del calcolo, cioè dopo la chiusura: "
                        "una notizia uscita a mercato chiuso può essere già nel dato. L'ora del calcolo è salvata."),
    ("QQQ come riferimento", "QQQ è il primo riferimento per i titoli del Nasdaq-100, non per forza quello giusto per ogni "
                             "strategia futura; per questo c'è anche la mediana di tutti i titoli salvati lo stesso giorno."),
    ("Composizione dell'indice", "Si salvano i titoli dell'indice di quel giorno: da oggi in poi il diario conserva anche la "
                                 "composizione. Per il passato manca uno storico gratuito della composizione del Nasdaq-100."),
]


# ---------------------------------------------------------------- storage

def connect(path=None, source=None):
    """WRITE connection, the only one: it passes the gate of app_env (phase 6C). In production only an authorized
    process (server, evening job, manual command) with an official origin; in test and preview never a production
    path. Every read uses _ro (read only), so opening a page or an API never writes."""
    import app_env
    path = path or DB
    app_env.check_diary_write(path, source)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _ro(path=None):
    """Read-only connection (SQLite mode=ro): never creates, changes or locks the diary for writing."""
    con = sqlite3.connect(f"file:{path or DB}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _has(con, table):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def label(source, path=None):
    """The origin stored with a new record (app_env decides: in preview it is always "anteprima")."""
    import app_env
    return app_env.check_diary_write(path or DB, source)


def _j(x):
    return json.dumps(x, ensure_ascii=False, allow_nan=False, default=str)


def exists(session, version, path=None):
    if not os.path.exists(path or DB):
        return False
    with closing(_ro(path)) as con:
        if not _has(con, "runs"):
            return False
        return con.execute("SELECT 1 FROM runs WHERE session=? AND model_version=?", (session, version)).fetchone() is not None


def session_closed_at(session):
    """The moment (ET) after which the session's close is final: close time + CLOSE_MARGIN_MIN."""
    import market_calendar
    d = datetime.fromisoformat(session).replace(tzinfo=ET)
    return d + timedelta(minutes=market_calendar.close_minute(d) + CLOSE_MARGIN_MIN)


def check_time(session, computed_at):
    """None if a ranking of `session` computed at `computed_at` (ISO with zone) may be recorded, otherwise the reason."""
    t = datetime.fromisoformat(computed_at)
    if t.tzinfo is None:
        return "ora del calcolo senza fuso orario"
    if t < session_closed_at(session):
        return f"la seduta {session} non era ancora chiusa alle {t.isoformat(timespec='minutes')}"
    return None


def record(result, session, computed_at, source, path=None):
    """Saves one closed session (result: opportunity_scanner.scan(..., keep_all=True)). Returns (saved, reason).
    A second call for the same session and model version does nothing: the first record is never changed."""
    if result.get("asOf") != session:
        return False, f"le classifiche usano i prezzi del {result.get('asOf')}, non della seduta {session}"
    why = check_time(session, computed_at)
    if why:
        return False, why
    version = result["model"]["version"]
    rows = []
    for lst in LISTS:
        block = result[lst]
        if "all" not in block:
            return False, "mancano le osservazioni di tutti i titoli (keep_all)"
        for e in block["all"]:
            conds = e["conditions"]
            rows.append((session, version, lst, e["ticker"], f"yahoo:{e['ticker']}", e.get("name"), e.get("sector"),
                         (e.get("metrics") or {}).get("close"), e.get("rank"), int(bool(e.get("rank")) and e["rank"] <= len(block["items"])),
                         e["ok"], e["n"], e["status"],
                         _j([c["id"] for c in conds if c["state"] == "ok"]), _j([c["id"] for c in conds if c["state"] == "ko"]),
                         _j([c["id"] for c in conds if c["state"] == "na"]), _j(conds), _j(e.get("warnings")), e.get("main"),
                         _j(e.get("diag")), _j(e.get("metrics"))))
    source = label(source, path)
    with closing(connect(path, source)) as con, con:
        con.execute("BEGIN IMMEDIATE")             # check and insert in one write transaction: two writers never clash
        if con.execute("SELECT 1 FROM runs WHERE session=? AND model_version=?", (session, version)).fetchone():
            return False, "seduta già registrata con questa versione del modello"
        con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (session, version, computed_at, source, PRICE_TYPE, _j(result["model"]["params"]), _j(result.get("market")),
                     result.get("universe"), result.get("evaluated"),
                     _j({lst: result[lst].get("coverage") for lst in LISTS}), _j(result.get("notEvaluable"))))
        con.executemany("INSERT INTO observations VALUES (" + ",".join("?" * 21) + ")", rows)
    return True, f"{len(rows)} osservazioni salvate"


# ---------------------------------------------------------------- results

def _close_on(series, day):
    """Close of `day` in a {date ISO: close} mapping, or None."""
    v = series.get(day) if series else None
    return v if v is not None and not (isinstance(v, float) and math.isnan(v)) and v > 0 else None


def as_map(s):
    """pandas Series of closes (DatetimeIndex) -> {date ISO: close}."""
    if s is None:
        return {}
    s = s.dropna()
    return {ts.date().isoformat(): float(v) for ts, v in s.items()}


def update_outcomes(closes, bench, now=None, path=None):
    """Measures the results that have matured. closes: {ticker: {date ISO: adjusted close}} of CLOSED sessions;
    bench: {date ISO: QQQ close} of closed sessions (its dates are the session calendar). Returns the new rows count."""
    if not os.path.exists(path or DB) or not bench:
        return 0
    now = (now or datetime.now(ET)).isoformat(timespec="seconds")
    cal = sorted(bench)
    pos = {d: i for i, d in enumerate(cal)}
    new = 0
    with closing(connect(path)) as con, con:
        done = {(r["session"], r["ticker"], r["horizon"]) for r in con.execute("SELECT session, ticker, horizon FROM outcomes WHERE status='ok'")}
        pairs = con.execute("SELECT DISTINCT o.session, o.ticker FROM observations o JOIN runs r ON r.session=o.session "
                            "AND r.model_version=o.model_version WHERE " + _official("r.source")).fetchall()
        touched = set()
        for p in pairs:
            day, tk = p["session"], p["ticker"]
            if day not in pos:
                continue                                   # the calendar does not reach that day (yet, or any more)
            for h in ALL_HORIZONS:
                if (day, tk, h) in done or pos[day] + h >= len(cal):
                    continue                               # already measured, or not matured: "in attesa"
                end = cal[pos[day] + h]
                q0, q1 = _close_on(bench, day), _close_on(bench, end)
                s0, s1 = _close_on(closes.get(tk), day), _close_on(closes.get(tk), end)
                if q0 is None or q1 is None:
                    row = (day, tk, h, end, "benchmark mancante", None, None, None, now)
                elif s0 is None or s1 is None:
                    row = (day, tk, h, end, "prezzo mancante", None, (q1 / q0 - 1) * 100, None, now)
                else:
                    r, q = (s1 / s0 - 1) * 100, (q1 / q0 - 1) * 100
                    row = (day, tk, h, end, "ok", r, q, r - q, now)
                con.execute("""INSERT INTO outcomes VALUES (?,?,?,?,?,?,?,?,?)
                               ON CONFLICT (session, ticker, horizon) DO UPDATE SET end_session=excluded.end_session,
                               status=excluded.status, ret=excluded.ret, qqq=excluded.qqq, excess=excluded.excess,
                               measured_at=excluded.measured_at WHERE outcomes.status != 'ok'""", row)
                new += row[4] == "ok"
                touched.add((day, h, end))
        for day, h, end in touched:                        # median of the whole universe recorded that day, same interval
            rets = [r["ret"] for r in con.execute(
                "SELECT ret FROM outcomes WHERE session=? AND horizon=? AND status='ok' AND ticker IN "
                "(SELECT DISTINCT o.ticker FROM observations o JOIN runs r ON r.session=o.session AND "
                "r.model_version=o.model_version WHERE o.session=? AND " + _official("r.source") + ")", (day, h, day))]
            con.execute("INSERT OR REPLACE INTO universe_medians VALUES (?,?,?,?,?)",
                        (day, h, end, statistics.median(rets) if rets else None, len(rets)))
    return new


# ---------------------------------------------------------------- what the page shows

def _summary(rows):
    """Figures of a group of matured observations; averages only with enough cases and days."""
    n, days = len(rows), len({r["session"] for r in rows})
    out = {"n": n, "days": days, "enough": n >= MIN_CASES and days >= MIN_DAYS}
    if out["enough"]:
        ret = [r["ret"] for r in rows]
        exc = [r["excess"] for r in rows]
        vs_u = [r["ret"] - r["median"] for r in rows if r["median"] is not None]
        out.update(mean=statistics.fmean(ret), median=statistics.median(ret), qqq=statistics.fmean(r["qqq"] for r in rows),
                   excess=statistics.fmean(exc), excessMedian=statistics.median(exc),
                   vsUniverse=statistics.fmean(vs_u) if vs_u else None, vsUniverseN=len(vs_u))
    return out


def _official(col="source"):
    import app_env
    return app_env.official_sql(col)


def excluded(path=None, runs_table="runs", obs_table="observations"):
    """Records kept in the diary but left out of the official statistics (origin not official: prova, test, anteprima),
    with their sessions and origins. Read only."""
    import app_env
    if not os.path.exists(path or DB):
        return {"runs": 0, "observations": 0, "items": []}
    with closing(_ro(path)) as con:
        if not _has(con, runs_table):
            return {"runs": 0, "observations": 0, "items": []}
        rows = con.execute(f"SELECT r.session, r.model_version, r.source, r.computed_at, (SELECT COUNT(*) FROM {obs_table} o "
                           f"WHERE o.session=r.session AND o.model_version=r.model_version) AS n FROM {runs_table} r "
                           f"WHERE NOT ({_official('r.source')}) ORDER BY r.session").fetchall()
    items = [{"session": r["session"], "version": r["model_version"], "source": r["source"], "computedAt": r["computed_at"],
              "observations": r["n"], "class": app_env.classify(r["source"])} for r in rows]
    return {"runs": len(items), "observations": sum(i["observations"] for i in items), "items": items}


def stats(path=None):
    """Everything the "Monitoraggio risultati" panel shows, ONLY from official records (phase 6C: records of tests or
    previews stay in the file but are counted apart in "excluded"). Empty structure when the diary has not started."""
    empty = {"started": False, "days": 0, "minCases": MIN_CASES, "minDays": MIN_DAYS, "horizons": HORIZONS,
             "limits": [{"title": a, "text": b} for a, b in LIMITS], "groups": GROUPS, "excluded": excluded(path)}
    if not os.path.exists(path or DB):
        return empty
    with closing(_ro(path)) as con:
        if not _has(con, "runs"):
            return empty
        off = _official("r.source")
        runs = con.execute("SELECT session, model_version, computed_at, source, universe, evaluated FROM runs r WHERE " + off +
                           " ORDER BY session").fetchall()
        if not runs:
            return empty
        out = {**empty, "started": True, "first": runs[0]["session"], "last": runs[-1]["session"],
               "lastComputedAt": runs[-1]["computed_at"], "lastSource": runs[-1]["source"], "days": len({r["session"] for r in runs}),
               "versions": sorted({r["model_version"] for r in runs}), "lists": {}}
        for lst in LISTS:
            j = " FROM observations o JOIN runs r ON r.session=o.session AND r.model_version=o.model_version WHERE " + off + " AND o.list=?"
            obs_n = con.execute("SELECT COUNT(*)" + j, (lst,)).fetchone()[0]
            sel_n = con.execute("SELECT COUNT(*)" + j + " AND o.rank IS NOT NULL", (lst,)).fetchone()[0]
            insuff = con.execute("SELECT COUNT(*)" + j + " AND o.status='Dati insufficienti'", (lst,)).fetchone()[0]
            hz = {}
            for h in HORIZONS[lst]:
                rows = con.execute("""SELECT o.session, o.rank, o.in_top, x.status, x.ret, x.qqq, x.excess, m.median
                                      FROM observations o JOIN runs r ON r.session=o.session AND r.model_version=o.model_version
                                      LEFT JOIN outcomes x ON x.session=o.session AND x.ticker=o.ticker AND x.horizon=?
                                      LEFT JOIN universe_medians m ON m.session=o.session AND m.horizon=?
                                      WHERE o.list=? AND """ + off, (h, h, lst)).fetchall()
                ok = [r for r in rows if r["status"] == "ok"]
                hz[h] = {"observations": len(rows), "matured": sum(r["status"] is not None for r in rows),
                         "pending": sum(r["status"] is None for r in rows),
                         "missingPrice": sum(r["status"] == "prezzo mancante" for r in rows),
                         "missingBench": sum(r["status"] == "benchmark mancante" for r in rows),
                         "groups": {"top": _summary([r for r in ok if r["in_top"]]),
                                    "selected": _summary([r for r in ok if r["rank"] is not None]),
                                    "others": _summary([r for r in ok if r["rank"] is None])}}
            out["lists"][lst] = {"observations": obs_n, "selected": sel_n, "insufficient": insuff, "horizons": hz}
        return out


def observations(session, lst, path=None):
    """The rows saved for one session and list, ranked first (to rebuild why a stock was selected that day)."""
    if not os.path.exists(path or DB):
        return []
    with closing(_ro(path)) as con:
        rows = con.execute("SELECT * FROM observations WHERE session=? AND list=? ORDER BY rank IS NULL, rank, ticker",
                           (session, lst)).fetchall()
    keys = ("met", "not_met", "missing", "conditions", "warnings", "diag", "metrics")
    return [{k: (json.loads(r[k]) if k in keys and r[k] else r[k]) for k in r.keys()} for r in rows]


# ---------------------------------------------------------------- data for future tests (phase O2, part D)

def dataset(lst, horizon, path=None):
    """One row per observation of `lst` with its matured result at `horizon` sessions (None while waiting), the market
    context of that day and the model version: the table the future tests start from (selected vs the rest of the
    same day, configurations of the ranking, rising and falling markets, out-of-sample by date or model version)."""
    if not os.path.exists(path or DB):
        return []
    with closing(_ro(path)) as con:
        rs = con.execute("""SELECT o.session, o.model_version, o.ticker, o.sector, o.rank, o.in_top, o.ok, o.n, o.status,
                                   o.met, o.missing, o.metrics, o.diag, r.market, r.computed_at,
                                   x.status AS result, x.end_session, x.ret, x.qqq, x.excess, m.median AS universe_median
                            FROM observations o JOIN runs r ON r.session=o.session AND r.model_version=o.model_version
                            LEFT JOIN outcomes x ON x.session=o.session AND x.ticker=o.ticker AND x.horizon=?
                            LEFT JOIN universe_medians m ON m.session=o.session AND m.horizon=?
                            WHERE o.list=? AND """ + _official("r.source") + """
                            ORDER BY o.session, o.rank IS NULL, o.rank, o.ticker""", (horizon, horizon, lst)).fetchall()
    keys = ("met", "missing", "metrics", "diag", "market")
    return [{k: (json.loads(r[k]) if k in keys and r[k] else r[k]) for k in r.keys()} for r in rs]


# ---------------------------------------------------------------- command line

def _print_status():
    s = stats()
    if not s["started"]:
        print(f"Diario delle opportunità non ancora avviato ({DB}).")
        return
    print(f"Diario delle opportunità: {s['days']} sedute dal {s['first']} al {s['last']} "
          f"(ultimo calcolo {s['lastComputedAt']}, {s['lastSource']}; versioni {', '.join(s['versions'])})")
    for lst, L in s["lists"].items():
        print(f"\n{lst}: {L['observations']} osservazioni, {L['selected']} in classifica, {L['insufficient']} con dati insufficienti")
        for h, H in L["horizons"].items():
            sel = H["groups"]["selected"]
            print(f"  {h:>3} sedute: maturate {H['matured']}, in attesa {H['pending']}, prezzo mancante {H['missingPrice']}; "
                  f"in classifica {sel['n']} casi su {sel['days']} giorni" + ("" if sel["enough"] else " (dati in raccolta)"))


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "update":
        import server
        print(server.update_opportunity_diary_offline())
        _print_status()
    elif cmd == "status":
        _print_status()
    else:
        print(__doc__)
        sys.exit(2)
