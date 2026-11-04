"""Phase O2: screening diagnosis, data coverage, analyst cache version, the opportunity diary (opportunity_diary.py,
SQLite in a temporary folder: see conftest.py), its API and the navigation by hash. Only made-up data."""
import json
import os
import re
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

import opportunity_diary as od
import opportunity_scanner as o
from test_opportunities import END, GOOD, QQQ, RISING_VOL, TODAY, frame, path, stock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVENING = "2026-10-30T18:30:00-04:00"           # after the close of the session END (Friday 30 October 2026)


@pytest.fixture
def result():
    universe = [stock("AAA"), stock("BBB"), stock("CCC"), stock("GGG", "Finanza")]
    daily = {"AAA": frame(path(300, 0.004), RISING_VOL), "BBB": frame(path(300, 0.0025), RISING_VOL),
             "CCC": frame(path(300, -0.003), RISING_VOL), "GGG": frame(path(300, 0.001, 0.005), RISING_VOL)}
    return o.scan(universe, daily, QQQ, {"GGG": GOOD}, today=TODAY, keep_all=True)


def rows(sql, *args):
    with sqlite3.connect(od.DB) as con:
        con.row_factory = sqlite3.Row
        return con.execute(sql, args).fetchall()


# ---------------------------------------------------------------- A: diagnosis, coverage, parameters

def test_stronger_than_qqq_but_falling_is_flagged_not_ranked_differently():
    t = {"ret21": -2.0, "ret63": 3.0, "rs21": 7.0, "rs63": 5.0, "trend": "Laterale"}
    d = o.diagnose(t)
    assert d["abs21"] == -2.0 and d["rel21"] == 7.0 and d["direction"] == "misto"
    assert "Più forte di QQQ ma in calo a 1 mese" in d["flag"]
    assert o.diagnose({**t, "ret21": 2.0})["flag"] is None                       # rising and stronger: no flag
    assert "trend ribassista" in o.diagnose({**t, "ret21": 2.0, "trend": "Ribassista"})["flag"]
    assert o.diagnose(None)["flag"] is None
    # the falling market of the fixture: QQQ down, a stock down less is flagged but keeps its place by the rules
    qqq = frame(path(300, -0.003, 0.005))
    r = o.scan([stock("DWN"), stock("UPP")], {"DWN": frame(path(300, -0.001), RISING_VOL), "UPP": frame(path(300, 0.002), RISING_VOL)},
               qqq, today=TODAY, keep_all=True)
    by = {x["ticker"]: x for x in r["trading"]["all"]}
    assert by["DWN"]["diag"]["flag"] and by["UPP"]["diag"]["flag"] is None
    assert r["market"]["qqq1m"] < 0 and r["market"]["above200n"] == 2


def test_coverage_marks_an_incomplete_ranking(result):
    inv = result["invest"]
    i2 = next(c for c in inv["coverage"] if c["id"] == "I2")
    assert i2["available"] == 1 and i2["total"] == 4 and set(i2["missing"]) == {"AAA", "BBB", "CCC"}
    assert inv["complete"] is False and "I2" in inv["coverageNote"]
    assert result["trading"]["complete"] is True and result["trading"]["coverageNote"] is None


def test_experimental_parameters_are_declared(result):
    p = {x["key"]: x for x in result["model"]["params"]}
    assert result["model"]["version"] == o.MODEL_VERSION
    assert {k for k, x in p.items() if x["experimental"]} >= {"ATR_HIGH", "TRADING_MIN", "INVEST_MIN"}
    assert (p["ATR_HIGH"]["value"], p["TRADING_MIN"]["value"], p["INVEST_MIN"]["value"]) == (4.0, 4, 5)   # values unchanged


def test_keep_all_returns_every_stock(result):
    for lst in ("trading", "invest"):
        b = result[lst]
        assert len(b["all"]) == 4
        assert {x["ticker"] for x in b["all"] if x["rank"] is None} == {x["ticker"] for x in b["all"]} - {x["ticker"] for x in b["items"]}
    assert "CCC" in [x["ticker"] for x in result["trading"]["all"] if x["rank"] is None]


def test_analyst_cache_written_by_older_code_is_not_fresh(tmp_path, monkeypatch):
    import analysts
    monkeypatch.setattr(analysts, "CACHE", str(tmp_path / "analysts.json"))
    (tmp_path / "analysts.json").write_text(json.dumps({"date": analysts.today_et(), "data": {"AAA": {}}}))
    assert analysts.is_fresh() is False                                         # no "schema": written before the margin field
    (tmp_path / "analysts.json").write_text(json.dumps({"date": analysts.today_et(), "schema": analysts.SCHEMA, "data": {"AAA": {}}}))
    assert analysts.is_fresh() is True
    assert analysts.cached_data() == {"AAA": {}}                                # the old copy still serves a fast start


# ---------------------------------------------------------------- B1: recording a day, duplicates, lists, missing data

def test_record_a_day(result):
    saved, msg = od.record(result, END, EVENING, "test")
    assert saved, msg
    run = rows("SELECT * FROM runs")[0]
    assert (run["session"], run["model_version"], run["source"]) == (END, o.MODEL_VERSION, "test")
    assert run["computed_at"].endswith("-04:00") and "rettificata" in run["price_type"]
    assert any(p["key"] == "ATR_HIGH" and p["experimental"] for p in json.loads(run["params"]))
    assert json.loads(run["market"])["date"] == END
    obs = rows("SELECT * FROM observations")
    assert len(obs) == 8                                                        # 4 stocks x 2 lists: not only the top 10
    a = next(x for x in obs if x["ticker"] == "AAA" and x["list"] == "trading")
    assert a["instrument"] == "yahoo:AAA" and a["rank"] == 1 and a["in_top"] == 1
    assert json.loads(a["met"]) == ["T1", "T2", "T3", "T4", "T5"] and json.loads(a["metrics"])["close"] == a["ref_price"]
    assert a["main"] and json.loads(a["diag"])["rel21"] > 0
    c = next(x for x in obs if x["ticker"] == "CCC" and x["list"] == "trading")
    assert c["rank"] is None and c["in_top"] == 0 and "T1" in json.loads(c["not_met"])


def test_no_duplicates_for_the_same_session_and_version(result):
    assert od.record(result, END, EVENING, "test")[0]
    saved, msg = od.record(result, END, "2026-10-30T22:45:00-04:00", "job serale")
    assert not saved and "già registrata" in msg
    assert len(rows("SELECT * FROM runs")) == 1 and len(rows("SELECT * FROM observations")) == 8
    assert od.exists(END, o.MODEL_VERSION)
    other = {**result, "model": {**result["model"], "version": "TEST-2"}}       # a new model version is a new run
    assert od.record(other, END, EVENING, "test")[0]
    assert len(rows("SELECT * FROM runs")) == 2


def test_trading_and_invest_are_kept_apart(result):
    od.record(result, END, EVENING, "test")
    for lst, prefix in (("trading", "T"), ("invest", "I")):
        for x in rows("SELECT conditions FROM observations WHERE list=?", lst):
            assert all(c["id"].startswith(prefix) for c in json.loads(x["conditions"]))
    tr = {x["ticker"]: x["rank"] for x in rows("SELECT ticker, rank FROM observations WHERE list='trading'")}
    iv = {x["ticker"]: x["rank"] for x in rows("SELECT ticker, rank FROM observations WHERE list='invest'")}
    assert tr["AAA"] == 1 and iv["AAA"] is None and iv["GGG"] is not None


def test_missing_data_is_recorded_as_missing(result):
    od.record(result, END, EVENING, "test")
    x = rows("SELECT * FROM observations WHERE list='invest' AND ticker='AAA'")[0]
    assert x["status"] == "Dati insufficienti" and set(json.loads(x["missing"])) == {"I1", "I2", "I3", "I4", "I5"}
    assert json.loads(x["metrics"])["epsRev90"] is None                          # never a made-up neutral value
    obs = od.observations(END, "invest")
    assert obs[0]["rank"] == 1 and isinstance(obs[0]["conditions"], list)        # enough to rebuild the selection


# ---------------------------------------------------------------- B2: no future information

def test_a_session_is_recorded_only_after_its_close(result):
    assert "non era ancora chiusa" in od.check_time(END, "2026-10-30T15:59:00-04:00")
    assert "non era ancora chiusa" in od.check_time(END, "2026-10-30T16:05:00-04:00")      # within the 15-minute margin
    assert od.check_time(END, "2026-10-30T16:15:00-04:00") is None
    assert "fuso orario" in od.check_time(END, "2026-10-30T18:00:00")
    saved, msg = od.record(result, END, "2026-10-30T12:00:00-04:00", "test")
    assert not saved and not os.path.exists(od.DB)                             # nothing written, not even the file
    saved, msg = od.record(result, "2026-10-29", EVENING, "test")               # prices of another session
    assert not saved and "2026-10-30" in msg


def test_recorded_ranking_uses_no_price_after_the_session():
    universe = [stock("AAA"), stock("BBB")]
    past = {"AAA": frame(path(300, 0.004), RISING_VOL), "BBB": frame(path(300, 0.0025), RISING_VOL)}
    future = {t: pd.concat([df, frame(np.full(5, 1.0), end="2026-11-06").iloc[-5:]]) for t, df in past.items()}
    qqq_f = pd.concat([QQQ, frame(np.full(5, 999.0), end="2026-11-06").iloc[-5:]])
    a = o.scan(universe, future, qqq_f, as_of=END, today=TODAY, keep_all=True)
    b = o.scan(universe, past, QQQ, today=TODAY, keep_all=True)
    assert a == b
    od.record(a, END, EVENING, "test")
    x = rows("SELECT ref_price FROM observations WHERE ticker='AAA' AND list='trading'")[0]
    assert x["ref_price"] == pytest.approx(past["AAA"]["Close"].iloc[-1])


def test_original_rankings_can_never_be_changed(result):
    od.record(result, END, EVENING, "test")
    with sqlite3.connect(od.DB) as con:
        with pytest.raises(sqlite3.DatabaseError, match="non si modifica"):
            con.execute("UPDATE observations SET rank=99 WHERE ticker='CCC'")
        with pytest.raises(sqlite3.DatabaseError, match="non si modifica"):
            con.execute("DELETE FROM runs")
    better = json.loads(json.dumps(result))
    better["trading"]["all"][0]["rank"] = 42                                   # new data the next day: no rewrite
    od.record(better, END, "2026-10-31T10:00:00-04:00", "test")
    assert rows("SELECT rank FROM observations WHERE ticker='AAA' AND list='trading'")[0]["rank"] == 1


# ---------------------------------------------------------------- B3-B4: results on the right sessions

def calendar(n=40, start="2026-10-30"):
    """Trading days after `start` with the 3 November gap of a pretend holiday: the calendar is QQQ's own dates."""
    days = [d.date().isoformat() for d in pd.bdate_range(start=start, periods=n + 1)]
    return [d for d in days if d != "2026-11-03"]


def test_returns_use_the_sessions_of_the_calendar(result):
    od.record(result, END, EVENING, "test")
    cal = calendar()
    bench = {d: 100.0 + i for i, d in enumerate(cal)}
    closes = {t: {d: 50.0 * (1 + 0.01 * i) for i, d in enumerate(cal)} for t in ("AAA", "BBB", "CCC", "GGG")}
    new = od.update_outcomes(closes, bench, datetime.fromisoformat("2026-12-15T18:00:00-05:00"))
    assert new == 4 * 3                                                         # 5, 10 and 21 sessions matured; 63 and 126 not
    x = {r["horizon"]: r for r in rows("SELECT * FROM outcomes WHERE ticker='AAA'")}
    assert set(x) == {5, 10, 21}
    assert x[5]["end_session"] == cal[5] == "2026-11-09"                        # 5 sessions after 30 Oct, skipping the 3rd
    assert x[5]["ret"] == pytest.approx(5.0) and x[5]["qqq"] == pytest.approx(5.0)
    assert x[5]["excess"] == pytest.approx(x[5]["ret"] - x[5]["qqq"])           # relative return: same interval
    m = rows("SELECT * FROM universe_medians WHERE horizon=5")[0]
    assert m["median"] == pytest.approx(5.0) and m["n"] == 4 and m["end_session"] == "2026-11-09"
    assert od.update_outcomes(closes, bench) == 0                               # already measured: nothing new


def test_results_wait_until_the_horizon_has_passed(result):
    od.record(result, END, EVENING, "test")
    cal = calendar(7)                                                           # only 6 sessions after the record
    od.update_outcomes({"AAA": {d: 10.0 for d in cal}}, {d: 10.0 for d in cal})
    assert {r["horizon"] for r in rows("SELECT horizon FROM outcomes WHERE ticker='AAA'")} == {5}
    s = od.stats()
    H = s["lists"]["trading"]["horizons"]
    assert H[10]["matured"] == 0 and H[10]["pending"] == 4
    assert H[5]["groups"]["selected"]["enough"] is False and "mean" not in H[5]["groups"]["selected"]


def test_missing_price_or_benchmark(result):
    od.record(result, END, EVENING, "test")
    cal = calendar(7)
    bench = {d: 10.0 for d in cal}
    closes = {"AAA": {d: 10.0 for d in cal if d != cal[5]}}                    # AAA without the end close; others absent
    od.update_outcomes(closes, bench)
    st = {r["ticker"]: r["status"] for r in rows("SELECT ticker, status FROM outcomes WHERE horizon=5")}
    assert st == {"AAA": "prezzo mancante", "BBB": "prezzo mancante", "CCC": "prezzo mancante", "GGG": "prezzo mancante"}
    closes["AAA"][cal[5]] = 11.0                                               # the price arrives later: measured then
    od.update_outcomes(closes, bench)
    assert rows("SELECT status, ret FROM outcomes WHERE ticker='AAA' AND horizon=5")[0]["status"] == "ok"
    bench2 = {d: (None if d == cal[5] else 10.0) for d in cal}
    os.remove(od.DB)
    od.record(result, END, EVENING, "test")
    od.update_outcomes({"AAA": {d: 10.0 for d in cal}}, bench2)
    assert rows("SELECT status FROM outcomes WHERE ticker='AAA' AND horizon=5")[0]["status"] == "benchmark mancante"
    assert od.update_outcomes({}, {}) == 0


def test_aggregates_only_with_enough_cases(result, monkeypatch):
    od.record(result, END, EVENING, "test")
    cal = calendar()
    od.update_outcomes({t: {d: 10.0 * (1.02 if d != END else 1) for d in cal} for t in ("AAA", "BBB", "CCC", "GGG")},
                       {d: 10.0 * (1.01 if d != END else 1) for d in cal})
    g = od.stats()["lists"]["trading"]["horizons"][5]["groups"]["selected"]
    assert g["n"] >= 2 and g["enough"] is False and "mean" not in g             # 100 cases in 20 days are needed
    monkeypatch.setattr(od, "MIN_CASES", 2)
    monkeypatch.setattr(od, "MIN_DAYS", 1)
    g = od.stats()["lists"]["trading"]["horizons"][5]["groups"]["selected"]
    assert g["enough"] and g["mean"] == pytest.approx(2.0) and g["qqq"] == pytest.approx(1.0) and g["excess"] == pytest.approx(1.0)
    assert g["vsUniverse"] == pytest.approx(0.0) and g["vsUniverseN"] == g["n"]


# ---------------------------------------------------------------- API, server and command

def test_diary_api(result):
    import server
    c = server.app.test_client()
    d = json.loads(c.get("/api/opportunities/diary").data)
    assert d["started"] is False and d["minCases"] == 100
    od.record(result, END, EVENING, "test")
    d = json.loads(c.get("/api/opportunities/diary").data)
    assert d["started"] and d["days"] == 1 and d["first"] == END
    assert d["lists"]["trading"]["observations"] == 4 and set(d["lists"]["invest"]["horizons"]) == {"63", "126"}


@pytest.fixture
def live(monkeypatch, result):
    """server.store with made-up data, the market closed and the session END the last closed one."""
    import server
    import test_opportunities as t
    universe, daily, fund = [stock("AAA"), stock("BBB")], {"AAA": frame(path(300, 0.004), RISING_VOL), "BBB": frame(path(300, 0.0025), RISING_VOL)}, {}
    st = server.store
    monkeypatch.setattr(st, "snapshot", {"asOf": EVENING, "lastQuote": EVENING, "stocks": [{**u, "price": 1.0} for u in universe]})
    monkeypatch.setattr(st, "daily", {**daily, "QQQ": QQQ})
    for k, v in (("analysts", {}), ("infos", {}), ("valuations", {}), ("signals", {}), ("ta", {}), ("news_all", None), ("error", None)):
        monkeypatch.setattr(st, k, v)
    monkeypatch.setattr(st, "last_daily", datetime.fromisoformat(EVENING).timestamp())
    monkeypatch.setattr(server, "market_status", lambda now=None: "closed")
    monkeypatch.setattr(server, "last_closed_session", lambda now=None: END)
    monkeypatch.setattr(server, "patterns_test", lambda: {})
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download for the diary"))
    server._od["measured"] = None
    return server


def test_server_saves_once_and_never_blocks(live, monkeypatch):
    msg = live.save_opportunity_diary(source="test")
    assert od.exists(END, o.MODEL_VERSION) and "osservazioni salvate" in msg
    assert "già registrata" in live.save_opportunity_diary(source="test")
    assert len(rows("SELECT * FROM runs")) == 1
    monkeypatch.setattr(od, "record", lambda *a, **k: 1 / 0)                  # a failing diary never raises
    os.remove(od.DB)
    assert live.save_opportunity_diary().startswith("errore")


def test_server_waits_for_the_final_close(live, monkeypatch):
    monkeypatch.setattr(live.store, "last_daily", datetime.fromisoformat("2026-10-30T15:00:00-04:00").timestamp())
    assert "prima della chiusura" in live.save_opportunity_diary()
    monkeypatch.setattr(live, "last_closed_session", lambda now=None: "2026-11-02")
    assert "non ancora alla seduta" in live.save_opportunity_diary()
    monkeypatch.setattr(live, "market_status", lambda now=None: "open")
    assert "mercato aperto" in live.save_opportunity_diary()
    assert not os.path.exists(od.DB) or not rows("SELECT * FROM runs")


def test_daily_job_and_dashboard_loop_call_the_diary_safely():
    src = open(os.path.join(ROOT, "server.py")).read()
    job = src[src.index("def run_daily_job"):src.index("def save_signal_diary")]
    assert 'save_opportunity_diary(source="job serale")' in job
    loop = src[src.index("def worker"):src.index("# ---------------------------------------------------------------- per-stock detail")]
    assert "save_opportunity_diary()" in loop


# ---------------------------------------------------------------- A4: navigation by hash

def test_hash_change_opens_the_page_without_reload():
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    m = re.search(r'addEventListener\("hashchange", \(\) => \{(.*?)\n\}\);', js, re.S)
    assert m and "viewFromHash(h)" in m.group(1) and "setView(v)" in m.group(1)
    assert "pushState" not in js                                                # the page never adds history entries itself


def test_dataset_for_future_tests(result):
    od.record(result, END, EVENING, "test")
    cal = calendar()
    od.update_outcomes({"AAA": {d: 10.0 * (1.1 if d != END else 1) for d in cal}}, {d: 10.0 for d in cal})
    rows_ = od.dataset("trading", 5)
    assert len(rows_) == 4 and rows_[0]["ticker"] == "AAA" and rows_[0]["rank"] == 1
    assert rows_[0]["ret"] == pytest.approx(10.0) and rows_[0]["market"]["date"] == END and rows_[0]["model_version"] == o.MODEL_VERSION
    assert next(r for r in rows_ if r["ticker"] == "BBB")["result"] == "prezzo mancante"
