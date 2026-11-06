"""Diario dello scanner delle esposizioni ETF (phase 6B, part J).

Additive and separate, like investment_diary.py and valuation_diary.py: two NEW tables (etf_runs, etf_observations)
in the same SQLite file of the opportunity diary (data/opportunita.sqlite3, public market data only, never
portafoglio/). The existing tables and their rows are never touched.

Rules:
- one record per Borsa Italiana session and model version (etf_opportunity.VERSION), both modes, every exposure;
- only closes that are final: the price cache must have been downloaded after 18:00 (Rome) of that session, so a
  session is never recorded with prices taken during the trading day;
- only from today onwards: nothing is rebuilt on the past (no retroactive rows);
- the diary file must already exist (it is started by the opportunity diary): this module never creates it;
- rows are never modified or deleted (SQLite triggers); a second call for the same session does nothing (idempotent);
- saved from the server loop and from the evening job, never because the page was opened.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import datetime, time as dtime

import opportunity_diary as od

SCHEMA = """
CREATE TABLE IF NOT EXISTS etf_runs (
  session TEXT NOT NULL, model_version TEXT NOT NULL, computed_at TEXT NOT NULL, source TEXT NOT NULL,
  params TEXT NOT NULL, prices_fetched TEXT, prices_source TEXT, catalog_built TEXT, counts TEXT, exposures INTEGER,
  PRIMARY KEY (session, model_version));
CREATE TABLE IF NOT EXISTS etf_observations (
  session TEXT NOT NULL, model_version TEXT NOT NULL, mode TEXT NOT NULL, exposure TEXT NOT NULL, family TEXT,
  reference_isin TEXT, members TEXT, prices TEXT, benchmark TEXT, state TEXT, favourable TEXT, contrary TEXT,
  missing TEXT, indicators TEXT, bond TEXT, risk TEXT, data_status TEXT, reasons TEXT,
  PRIMARY KEY (session, model_version, mode, exposure),
  FOREIGN KEY (session, model_version) REFERENCES etf_runs (session, model_version));
CREATE TRIGGER IF NOT EXISTS etf_runs_no_update BEFORE UPDATE ON etf_runs BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS etf_runs_no_delete BEFORE DELETE ON etf_runs BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS etf_obs_no_update BEFORE UPDATE ON etf_observations BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS etf_obs_no_delete BEFORE DELETE ON etf_observations BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
"""
CLOSE_ROME = dtime(18, 0)


def _clean(x):
    """NaN/inf never reach the diary (JSON without NaN): they become None, like every missing value."""
    if isinstance(x, float):
        return None if math.isnan(x) or math.isinf(x) else x
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def _j(x):
    return json.dumps(_clean(x), ensure_ascii=False, allow_nan=False, default=str)


def connect(path=None, source=None):
    """Only an existing diary file is opened: this module never starts the diary. Write connection: it passes the gate
    of app_env (phase 6C) like the other diaries."""
    import app_env
    path = path or od.DB
    if not os.path.exists(path):
        raise FileNotFoundError("diario delle opportunità non ancora avviato")
    app_env.check_diary_write(path, source)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _ro(path):
    return closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True))


def _has_tables(con):
    return con.execute("SELECT 1 FROM sqlite_master WHERE name='etf_runs'").fetchone() is not None


def exists(session, version, path=None):
    path = path or od.DB
    if not os.path.exists(path):
        return False
    with _ro(path) as con:
        if not _has_tables(con):
            return False
        return con.execute("SELECT 1 FROM etf_runs WHERE session=? AND model_version=?", (session, version)).fetchone() is not None


def run_of(session, version, path=None):
    """{session, version, source, class} of a recorded run, or None. Read only."""
    import app_env
    path = path or od.DB
    if not os.path.exists(path):
        return None
    with _ro(path) as con:
        if not _has_tables(con):
            return None
        r = con.execute("SELECT source, computed_at FROM etf_runs WHERE session=? AND model_version=?", (session, version)).fetchone()
    return {"session": session, "version": version, "source": r[0], "computedAt": r[1], "class": app_env.classify(r[0])} if r else None


def runs_of_session(session, path=None):
    """Every recorded run of one session, whatever the model version: [{version, source, class}]. Read only. A session
    already recorded with a version (also a test record, excluded) is not recorded again with a newer version: a new
    version applies from the next session (no second reading of the same day, idempotency never bypassed)."""
    import app_env
    path = path or od.DB
    if not os.path.exists(path):
        return []
    with _ro(path) as con:
        if not _has_tables(con):
            return []
        rows = con.execute("SELECT model_version, source FROM etf_runs WHERE session=? ORDER BY model_version", (session,)).fetchall()
    return [{"version": r[0], "source": r[1], "class": app_env.classify(r[1])} for r in rows]


def check_final(session, prices_fetched):
    """None when the closes of `session` were final when the prices were downloaded, else the reason."""
    if not session or not prices_fetched:
        return "seduta o ora dei prezzi sconosciute"
    t = datetime.fromisoformat(prices_fetched)
    if t.tzinfo is None:
        return "ora dei prezzi senza fuso orario"
    from zoneinfo import ZoneInfo
    t = t.astimezone(ZoneInfo("Europe/Rome"))
    if t.date().isoformat() < session or (t.date().isoformat() == session and t.time() < CLOSE_ROME):
        return f"prezzi scaricati alle {t.isoformat(timespec='minutes')}: la seduta {session} non era ancora chiusa"
    return None


def record(results, session, computed_at, source, path=None):
    """Saves the scan of one closed session (results: {"lungo": scan(...), "breve": scan(...)} computed with
    as_of=session). Returns (saved, reason)."""
    path = path or od.DB
    if not os.path.exists(path):
        return False, "diario delle opportunità non ancora avviato: nessuna registrazione degli ETF"
    any_r = next(iter(results.values()))
    if any(r.get("session") != session or r.get("asOf") != session for r in results.values()):
        return False, f"lo scanner usa i prezzi del {any_r.get('session')}, non della seduta {session}"
    why = check_final(session, any_r.get("pricesFetched"))
    if why:
        return False, why
    version = any_r["version"]
    rows = []
    for mode, r in results.items():
        for o in r["rows"]:
            m = o.get("measures") or {}
            ind = {k: m.get(k) for k in ("returns", "rel", "relPrev", "trend", "vol1m", "vol3m", "vol12m", "dd3m", "dd12m", "aligned", "date")}
            rows.append((session, version, mode, o["key"], o["family"], o.get("reference"), _j(o["members"]), _j(o.get("prices")),
                         o.get("benchmarkName"), o["state"], _j(o["favourable"]), _j(o["contrary"]), _j(o["missing"]), _j(ind),
                         _j(o.get("bond")), _j(o.get("risk")), _j(o.get("completeness")), _j(o.get("why"))))
    source = od.label(source, path)
    with closing(connect(path, source)) as con, con:
        con.execute("BEGIN IMMEDIATE")             # check and insert in one write transaction (phase 6C)
        if con.execute("SELECT 1 FROM etf_runs WHERE session=? AND model_version=?", (session, version)).fetchone():
            return False, "seduta già registrata con questa versione dello scanner ETF"
        other = con.execute("SELECT model_version, source FROM etf_runs WHERE session=? LIMIT 1", (session,)).fetchone()
        if other:                                  # a new model version starts from the next session (E1 → E2)
            return False, (f"seduta già registrata con il modello {other[0]} (origine «{other[1]}»): il modello {version} "
                           "si registra dalla seduta successiva")
        con.execute("INSERT INTO etf_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (session, version, computed_at, source, _j(any_r.get("params")), any_r.get("pricesFetched"),
                     any_r.get("pricesSource"), any_r.get("catalogBuilt"), _j({m: r["overview"]["counts"] for m, r in results.items()}),
                     len(any_r["rows"])))
        con.executemany("INSERT INTO etf_observations VALUES (" + ",".join("?" * 18) + ")", rows)
    return True, f"{len(rows)} osservazioni ETF salvate"


def previous(before=None, version=None, path=None):
    """{exposure: {session, bond}} of the latest OFFICIAL session before `before` (mode lungo), for "evoluzione
    rispetto alla rilevazione precedente" of the bond data. Read only; {} when nothing was recorded. Records of tests
    or previews (phase 6C) are never used as the previous reading."""
    path = path or od.DB
    if not os.path.exists(path):
        return {}
    with _ro(path) as con:
        con.row_factory = sqlite3.Row
        if not _has_tables(con):
            return {}
        q = "SELECT session FROM etf_runs r WHERE " + od._official("r.source", "etf") + (" AND session < ?" if before else "") + (" AND model_version = ?" if version else "")
        args = [a for a in (before, version) if a]
        last = con.execute(q.replace("SELECT session", "SELECT session, model_version") + " ORDER BY session DESC LIMIT 1", args).fetchone()
        if not last:
            return {}
        rows = con.execute("SELECT exposure, bond FROM etf_observations WHERE session=? AND model_version=? AND mode='lungo'",
                           (last["session"], last["model_version"])).fetchall()
        return {r["exposure"]: {"session": last["session"], "bond": json.loads(r["bond"]) if r["bond"] else None} for r in rows}


def stats(path=None):
    """Read only: the tables are created only by the first record, never by a read. Official records only; records of
    tests or previews are counted apart in "excluded" (phase 6C)."""
    path = path or od.DB
    empty = {"started": False, "days": 0}
    if not os.path.exists(path):
        return dict(empty, note="diario delle opportunità non ancora avviato")
    with _ro(path) as con:
        con.row_factory = sqlite3.Row
        if not _has_tables(con):
            return empty
        exc = od.excluded(path, "etf_runs", "etf_observations")
        runs = con.execute("SELECT session, model_version, computed_at, source FROM etf_runs r WHERE " + od._official("r.source", "etf") +
                           " ORDER BY session").fetchall()
        if not runs:
            return dict(empty, excluded=exc)
        n = con.execute("SELECT COUNT(*) FROM etf_observations o JOIN etf_runs r ON r.session=o.session AND "
                        "r.model_version=o.model_version WHERE " + od._official("r.source", "etf")).fetchone()[0]
        return {"started": True, "days": len({r["session"] for r in runs}), "first": runs[0]["session"], "last": runs[-1]["session"],
                "lastAt": runs[-1]["computed_at"], "lastSource": runs[-1]["source"], "observations": n,
                "versions": sorted({r["model_version"] for r in runs}), "excluded": exc}


if __name__ == "__main__":
    print(json.dumps(stats(), ensure_ascii=False, indent=1))
