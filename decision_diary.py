"""Diario delle decisioni del Decision Desk (phase 7A, part J): a prospective record of the decision snapshots.

Additive and separate, like investment_diary.py and valuation_diary.py: two NEW tables (dec_runs, dec_observations)
in the same SQLite file of the opportunity diary (data/opportunita.sqlite3, public market data only, never
portafoglio/). Existing tables and rows are never touched.

Rules (the safety of phase 6C is reused, nothing new is invented):
- written only through opportunity_diary.connect (app_env gate: in production only an authorized process with an
  official origin; in test and preview never a production path); every read is read-only (mode=ro);
- a session is recorded only if the opportunity diary has already recorded it and only after the NYSE close
  (opportunity_diary.check_time): the decisions of the past are never rebuilt with today's data;
- the ETF rows are saved only when the ETF scanner uses the same session with final closes (etf_opportunity_diary.
  check_final); otherwise the run says why they are missing (never ETF data of another day mixed in silently);
- one run per (session, desk version): check and insert in one BEGIN IMMEDIATE transaction (idempotent, atomic: an
  error saves nothing); rows are never modified or deleted (SQLite triggers);
- every observation keeps state, rule, evidence for and against, main reason, risks, conditions of change, the dates
  of the data, the completeness, the validation text and the versions of every engine used.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from contextlib import closing

import opportunity_diary as od

SCHEMA = """
CREATE TABLE IF NOT EXISTS dec_runs (
  session TEXT NOT NULL, model_version TEXT NOT NULL, computed_at TEXT NOT NULL, source TEXT NOT NULL,
  sources TEXT NOT NULL, rules TEXT NOT NULL, counts TEXT, etf_note TEXT, rows INTEGER,
  PRIMARY KEY (session, model_version));
CREATE TABLE IF NOT EXISTS dec_observations (
  session TEXT NOT NULL, model_version TEXT NOT NULL, kind TEXT NOT NULL, instrument TEXT NOT NULL, horizon TEXT NOT NULL,
  name TEXT, code TEXT, state TEXT NOT NULL, rule TEXT NOT NULL, main TEXT, main_risk TEXT, favourable TEXT, contrary TEXT,
  risks TEXT, change TEXT, missing TEXT, dates TEXT, data_quality TEXT, validation TEXT, context TEXT,
  PRIMARY KEY (session, model_version, kind, instrument, horizon),
  FOREIGN KEY (session, model_version) REFERENCES dec_runs (session, model_version));
CREATE TRIGGER IF NOT EXISTS dec_runs_no_update BEFORE UPDATE ON dec_runs BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS dec_runs_no_delete BEFORE DELETE ON dec_runs BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS dec_obs_no_update BEFORE UPDATE ON dec_observations BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
CREATE TRIGGER IF NOT EXISTS dec_obs_no_delete BEFORE DELETE ON dec_observations BEGIN SELECT RAISE(ABORT, 'il diario non si modifica'); END;
"""


def _clean(x):
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
    """Only an existing diary file is opened (this module never starts the diary); write gate of phase 6C."""
    path = path or od.DB
    if not os.path.exists(path):
        raise FileNotFoundError("diario delle opportunità non ancora avviato")
    con = od.connect(path, source)
    con.executescript(SCHEMA)
    return con


def _ro(path):
    return closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True))


def _has(con):
    return con.execute("SELECT 1 FROM sqlite_master WHERE name='dec_runs'").fetchone() is not None


def exists(session, version, path=None):
    path = path or od.DB
    if not os.path.exists(path):
        return False
    with _ro(path) as con:
        return _has(con) and con.execute("SELECT 1 FROM dec_runs WHERE session=? AND model_version=?",
                                         (session, version)).fetchone() is not None


def etf_ready(result, session):
    """(True, None) when the ETF rows of the snapshot belong to `session` with final closes, else (False, reason)."""
    import etf_opportunity_diary as ed
    src = (result.get("sources") or {}).get("etf_lungo")
    if not src:
        return False, "scanner ETF non disponibile"
    if src.get("session") != session:
        return False, f"lo scanner ETF usa la seduta {src.get('session')}, non {session}: righe ETF non registrate"
    why = ed.check_final(session, src.get("prices"))
    return (False, "ETF: " + why) if why else (True, None)


def record(result, session, computed_at, source, opp_version, path=None):
    """Saves one decision snapshot (investment_decision_engine.decide). Returns (saved, reason)."""
    path = path or od.DB
    if not os.path.exists(path):
        return False, "diario delle opportunità non ancora avviato: nessuna decisione registrata"
    if not od.exists(session, opp_version, path):
        return False, f"il diario delle opportunità non ha registrato la seduta {session}: nessuna decisione salvata"
    why = od.check_time(session, computed_at)
    if why:
        return False, why
    if result.get("session") != session:
        return False, f"le decisioni usano la seduta {result.get('session')}, non {session}"
    late = [r["id"] for r in result["rows"] if r["kind"] == "azione" and r["dates"].get("price") and r["dates"]["price"] > session]
    if late:
        return False, f"prezzi successivi alla seduta {session} ({late[0]}): nessuna decisione salvata"
    ok_etf, etf_note = etf_ready(result, session)
    rows = []
    for r in result["rows"]:
        if r["kind"] == "etf" and not ok_etf:
            continue
        rows.append((session, result["version"], r["kind"], r["key"], r["horizon"], r["name"], r.get("code"), r["state"],
                     r["rule"], r["main"], r["mainRisk"], _j(r["favourable"]), _j(r["contrary"]), _j(r["risks"]),
                     _j(r["change"]), _j(r["missing"]), _j(r["dates"]), r["dataQuality"], r["validation"], _j(r.get("context"))))
    if not rows:
        return False, "nessuna decisione da registrare"
    source = od.label(source, path)
    with closing(connect(path, source)) as con, con:
        con.execute("BEGIN IMMEDIATE")             # check and insert in one write transaction (phase 6C)
        if con.execute("SELECT 1 FROM dec_runs WHERE session=? AND model_version=?", (session, result["version"])).fetchone():
            return False, "seduta già registrata con questa versione del Decision Desk"
        con.execute("INSERT INTO dec_runs VALUES (?,?,?,?,?,?,?,?,?)",
                    (session, result["version"], computed_at, source, _j(result.get("sources")), _j(result.get("rules")),
                     _j(result.get("counts")), etf_note, len(rows)))
        con.executemany("INSERT INTO dec_observations VALUES (" + ",".join("?" * 20) + ")", rows)
    return True, f"{len(rows)} decisioni salvate" + (f" ({etf_note})" if etf_note else "")


def stats(path=None):
    """Read only: official runs only; test or preview records counted apart (phase 6C)."""
    path = path or od.DB
    empty = {"started": False, "days": 0}
    if not os.path.exists(path):
        return empty
    with _ro(path) as con:
        con.row_factory = sqlite3.Row
        if not _has(con):
            return empty
        exc = od.excluded(path, "dec_runs", "dec_observations")
        runs = con.execute("SELECT session, model_version, computed_at, source, etf_note FROM dec_runs r WHERE "
                           + od._official("r.source") + " ORDER BY session").fetchall()
        if not runs:
            return dict(empty, excluded=exc)
        n = con.execute("SELECT COUNT(*) FROM dec_observations o JOIN dec_runs r ON r.session=o.session AND "
                        "r.model_version=o.model_version WHERE " + od._official("r.source")).fetchone()[0]
        return {"started": True, "days": len({r["session"] for r in runs}), "first": runs[0]["session"],
                "last": runs[-1]["session"], "lastAt": runs[-1]["computed_at"], "lastSource": runs[-1]["source"],
                "lastEtfNote": runs[-1]["etf_note"], "observations": n,
                "versions": sorted({r["model_version"] for r in runs}), "excluded": exc}


if __name__ == "__main__":
    print(json.dumps(stats(), ensure_ascii=False, indent=1))
