"""Valutazioni e scenari nel Diario delle opportunità (phase 5B, part G).

Additive and separate, like investment_diary.py: two NEW tables (val_runs, val_observations) in the same SQLite file
(data/opportunita.sqlite3). The existing tables (opportunity diary, phase 5A judgements) and their rows are never
changed. The price results that the opportunity diary measures later (same session and ticker) will be the ones to
check, prospectively, whether the valuation levels were informative: nothing is rebuilt on the past.

Rules:
- a session is recorded only after the opportunity diary has recorded it (never a diary started from here, never an
  artificial first day), only after the close (opportunity_diary.check_time), with the closing price of that session
  as the reference price;
- what is saved: time, reference price, statements and market data used (with their dates), model version and
  parameters, the three scenarios with their assumptions, range of values, reliability status, reasons, conditions to
  monitor, analytic group;
- rows are never modified or deleted (SQLite triggers); a new model version is a new run.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing

import opportunity_diary as od

SCHEMA = """
CREATE TABLE IF NOT EXISTS val_runs (
  session TEXT NOT NULL, model_version TEXT NOT NULL, fundamental_version TEXT, computed_at TEXT NOT NULL,
  source TEXT NOT NULL, params TEXT NOT NULL, rates TEXT, fx TEXT, data_dates TEXT, counts TEXT, universe INTEGER,
  PRIMARY KEY (session, model_version));
CREATE TABLE IF NOT EXISTS val_observations (
  session TEXT NOT NULL, model_version TEXT NOT NULL, ticker TEXT NOT NULL, price REAL, price_date TEXT, status TEXT,
  grp TEXT, position TEXT, value_prudent REAL, value_base REAL, value_favourable REAL, scenarios TEXT, inputs TEXT,
  reverse TEXT, sensitivity TEXT, reasons TEXT, blockers TEXT, monitor TEXT, fundamental TEXT, data_dates TEXT,
  PRIMARY KEY (session, model_version, ticker),
  FOREIGN KEY (session, model_version) REFERENCES val_runs (session, model_version));
CREATE TRIGGER IF NOT EXISTS val_runs_no_update BEFORE UPDATE ON val_runs BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS val_runs_no_delete BEFORE DELETE ON val_runs BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS val_obs_no_update BEFORE UPDATE ON val_observations BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS val_obs_no_delete BEFORE DELETE ON val_observations BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
"""


def _j(x):
    return json.dumps(x, ensure_ascii=False, allow_nan=False, default=str)


def connect(path=None, source=None):
    """Only an existing diary file is opened: this module never creates the diary. Write connection: through the gate
    of opportunity_diary.connect (phase 6C, app_env)."""
    path = path or od.DB
    if not os.path.exists(path):
        raise FileNotFoundError("diario delle opportunità non ancora avviato")
    con = od.connect(path, source)
    con.executescript(SCHEMA)
    return con


def _ro(path):
    return closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True))


def exists(session, version, path=None):
    path = path or od.DB
    if not os.path.exists(path):
        return False
    with _ro(path) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='val_runs'").fetchone():
            return False
        return con.execute("SELECT 1 FROM val_runs WHERE session=? AND model_version=?", (session, version)).fetchone() is not None


def _slim(sc):
    """The scenarios without the yearly rows (kept: assumptions, values, terminal share, reinvestment)."""
    return {k: {x: v[x] for x in ("assumptions", "growthPath", "revMultiple", "reinvestShare", "terminalReinvestRate", "ev",
                                  "equity", "perShare", "tvShare", "priceVsValue")} for k, v in (sc or {}).items()}


def record(result, session, computed_at, source, opp_version, path=None):
    """Saves the valuation (investment_valuation.analyze_all, computed with the closing prices) of one closed session.
    Returns (saved, reason)."""
    if not od.exists(session, opp_version, path):
        return False, f"il diario delle opportunità non ha registrato la seduta {session}: nessuna valutazione salvata"
    why = od.check_time(session, computed_at)
    if why:
        return False, why
    days = {(x["price"] or {}).get("date") for x in result["items"] if (x["price"] or {}).get("kind") == "chiusura"}
    if any((x["price"] or {}).get("kind") != "chiusura" for x in result["items"] if _num_price(x)):
        return False, "la valutazione del diario usa solo i prezzi di chiusura della seduta"
    days.discard(None)
    if days and max(days) != session:
        return False, f"i prezzi sono del {max(days)}, non della seduta {session}"
    version = result["model"]["version"]
    rows = []
    for x in result["items"]:
        sc = x.get("scenarios") or {}
        v = {k: (sc.get(k) or {}).get("perShare") for k in ("prudente", "base", "favorevole")}
        rows.append((session, version, x["ticker"], (x["price"] or {}).get("value"), (x["price"] or {}).get("date"),
                     x["status"], x["group"], (x.get("position") or {}).get("id"), v["prudente"], v["base"], v["favorevole"],
                     _j(_slim(sc)), _j(x.get("inputs")), _j(x.get("reverse")), _j(x.get("sensitivity")),
                     _j(x.get("reasons")), _j(x.get("blockers")), _j(x.get("monitor")), _j(x.get("fundamental")),
                     _j(x.get("dataDates"))))
    source = od.label(source, path)
    with closing(connect(path, source)) as con, con:
        con.execute("BEGIN IMMEDIATE")             # check and insert in one write transaction (phase 6C)
        if con.execute("SELECT 1 FROM val_runs WHERE session=? AND model_version=?", (session, version)).fetchone():
            return False, "seduta già registrata con questa versione del modello di valutazione"
        con.execute("INSERT INTO val_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (session, version, result["model"].get("fundamentalVersion"), computed_at, source,
                     _j({"values": result["model"]["values"], "text": result["model"]["params"]}), _j(result.get("rates")),
                     _j(result.get("fx")), _j(result.get("dataDates")), _j(result.get("counts")), len(result["items"])))
        con.executemany("INSERT INTO val_observations VALUES (" + ",".join("?" * 20) + ")", rows)
    return True, f"{len(rows)} valutazioni salvate"


def _num_price(x):
    v = (x.get("price") or {}).get("value")
    return isinstance(v, (int, float))


def stats(path=None):
    """Read only: the new tables are created only by the first record, never by a read."""
    empty = {"started": False, "days": 0}
    path = path or od.DB
    if not os.path.exists(path):
        return empty
    with _ro(path) as con:
        con.row_factory = sqlite3.Row
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='val_runs'").fetchone():
            return empty
        runs = con.execute("SELECT session, model_version FROM val_runs r WHERE " + od._official("r.source") + " ORDER BY session").fetchall()
        if not runs:
            return dict(empty, excluded=od.excluded(path, "val_runs", "val_observations"))
        n = con.execute("SELECT COUNT(*) FROM val_observations o JOIN val_runs r ON r.session=o.session AND r.model_version=o.model_version "
                        "WHERE " + od._official("r.source")).fetchone()[0]
        return {"started": True, "days": len({r["session"] for r in runs}), "first": runs[0]["session"],
                "last": runs[-1]["session"], "observations": n, "versions": sorted({r["model_version"] for r in runs}),
                "excluded": od.excluded(path, "val_runs", "val_observations")}
