"""Giudizi del motore di analisi fondamentale nel Diario delle opportunità (phase 5A, part G).

Additive and separate: two NEW tables (inv_runs, inv_observations) in the same SQLite file of the opportunity diary
(data/opportunita.sqlite3). The existing tables, their rows and opportunity_diary.py are not changed. The price results
already measured by the opportunity diary (table outcomes, same session and ticker) will be the ones to compare the
profiles with, prospectively: nothing is rebuilt on the past.

Rules:
- a session is recorded only if the opportunity diary has already recorded it (never a diary started from here, never
  an artificial first day) and only after the close (opportunity_diary.check_time);
- the trend uses the closed sessions of that day; statements, analysts and market data are those available at the
  time of the computation, saved with their own dates (statements downloaded on..., quarter announced on...);
- rows are never modified or deleted (SQLite triggers); a new model version is a new run.
"""
from __future__ import annotations

import json
import os
from contextlib import closing

import opportunity_diary as od

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_runs (
  session TEXT NOT NULL, model_version TEXT NOT NULL, computed_at TEXT NOT NULL, source TEXT NOT NULL,
  params TEXT NOT NULL, data_dates TEXT, coverage TEXT, universe INTEGER, PRIMARY KEY (session, model_version));
CREATE TABLE IF NOT EXISTS inv_observations (
  session TEXT NOT NULL, model_version TEXT NOT NULL, ticker TEXT NOT NULL, name TEXT, sector TEXT, sector_model TEXT,
  profile TEXT, completeness TEXT, dims TEXT, indicators TEXT, strengths TEXT, weaknesses TEXT, data_dates TEXT,
  pagella TEXT, PRIMARY KEY (session, model_version, ticker),
  FOREIGN KEY (session, model_version) REFERENCES inv_runs (session, model_version));
CREATE TRIGGER IF NOT EXISTS inv_runs_no_update BEFORE UPDATE ON inv_runs BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS inv_runs_no_delete BEFORE DELETE ON inv_runs BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS inv_obs_no_update BEFORE UPDATE ON inv_observations BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS inv_obs_no_delete BEFORE DELETE ON inv_observations BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
"""


def _j(x):
    return json.dumps(x, ensure_ascii=False, allow_nan=False, default=str)


def connect(path=None):
    """Only an existing diary file is opened: this module never creates the diary."""
    path = path or od.DB
    if not os.path.exists(path):
        raise FileNotFoundError("diario delle opportunità non ancora avviato")
    con = od.connect(path)
    con.executescript(SCHEMA)
    return con


def exists(session, version, path=None):
    import sqlite3
    if not os.path.exists(path or od.DB):
        return False
    with closing(sqlite3.connect(f"file:{path or od.DB}?mode=ro", uri=True)) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='inv_runs'").fetchone():
            return False
        return con.execute("SELECT 1 FROM inv_runs WHERE session=? AND model_version=?", (session, version)).fetchone() is not None


def record(result, session, computed_at, source, opp_version, path=None):
    """Saves the analysis (investment_engine.analyze_all) of one closed session. Returns (saved, reason)."""
    if not od.exists(session, opp_version, path):
        return False, f"il diario delle opportunità non ha registrato la seduta {session}: nessun giudizio salvato"
    why = od.check_time(session, computed_at)
    if why:
        return False, why
    days = {x["priceDate"] for x in result["items"] if x.get("priceDate")}
    if days and max(days) != session:
        return False, f"il trend usa i prezzi del {max(days)}, non della seduta {session}"
    version = result["model"]["version"]
    rows = []
    for x in result["items"]:
        rows.append((session, version, x["ticker"], x["name"], x["sector"], x["model"]["id"], x["profile"]["id"],
                     _j(x["completeness"]), _j({k: {"state": v["state"], "partial": v["partial"], "reasons": v["reasons"]}
                                                 for k, v in x["dims"].items()}),
                     _j([{k: i[k] for k in ("key", "value", "unit", "status", "period", "source")} for i in x["indicators"]]),
                     _j(x["strengths"]), _j(x["weaknesses"]), _j(x["dataDates"]), _j(x.get("pagella"))))
    with closing(connect(path)) as con, con:
        if con.execute("SELECT 1 FROM inv_runs WHERE session=? AND model_version=?", (session, version)).fetchone():
            return False, "seduta già registrata con questa versione del motore"
        con.execute("INSERT INTO inv_runs VALUES (?,?,?,?,?,?,?,?)",
                    (session, version, computed_at, source, _j(result["model"]["params"]), _j(result.get("dataDates")),
                     _j(result.get("coverage")), len(result["items"])))
        con.executemany("INSERT INTO inv_observations VALUES (" + ",".join("?" * 14) + ")", rows)
    return True, f"{len(rows)} giudizi fondamentali salvati"


def stats(path=None):
    """Read only: the new tables are created only by the first record, never by a read."""
    import sqlite3
    empty = {"started": False, "days": 0}
    if not os.path.exists(path or od.DB):
        return empty
    with closing(sqlite3.connect(f"file:{path or od.DB}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='inv_runs'").fetchone():
            return empty
        runs = con.execute("SELECT session, model_version FROM inv_runs ORDER BY session").fetchall()
        if not runs:
            return empty
        n = con.execute("SELECT COUNT(*) FROM inv_observations").fetchone()[0]
        return {"started": True, "days": len({r["session"] for r in runs}), "first": runs[0]["session"],
                "last": runs[-1]["session"], "observations": n, "versions": sorted({r["model_version"] for r in runs})}
