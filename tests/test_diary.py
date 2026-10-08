"""Signal diary (diary.py) on made-up verdicts: a saved day is never rewritten, excluded days never count, the
"since" date, and the missing sessions (weekends and NYSE holidays are not missing)."""
import json
import os

import pandas as pd

import diary


def entry(ticker, cat, price=100.0, rules=None):
    return {"ticker": ticker, "price": price, "verdict": cat, "category": cat, "owned": False, "index": True,
            "rules": rules or [{"id": "D1", "ok": True}], "decidedBy": None}


def test_a_saved_day_is_never_rewritten(private_folder):
    assert diary.save("2026-10-05", [entry("AAA", "Entra ora", 100)])
    before = open(os.path.join(diary.DIR, "2026-10-05.json")).read()
    assert not diary.save("2026-10-05", [entry("AAA", "Evita", 50)])          # different data: refused
    assert open(os.path.join(diary.DIR, "2026-10-05.json")).read() == before
    assert not diary.save("2026-10-06", [])                                     # nothing to save: nothing written
    assert diary.days() == ["2026-10-05"]


def test_excluded_days_never_count(private_folder):
    sessions = pd.bdate_range("2026-10-01", periods=40)
    bench = pd.Series(range(100, 140), index=sessions, dtype=float)
    closes = {"AAA": pd.Series(range(200, 240), index=sessions, dtype=float), "BBB": pd.Series(100.0, index=sessions)}
    diary.save(str(sessions[0].date()), [entry("AAA", "Entra ora"), entry("BBB", "Attendi")])
    diary.save(str(sessions[1].date()), [entry("AAA", "Entra ora"), entry("BBB", "Attendi")])
    with open(diary.EXCLUDED, "w") as f:
        json.dump({str(sessions[1].date()): "giorno sbagliato"}, f)
    r = diary.results(closes, bench)
    assert r["days"] == 1 and r["excluded"][0]["date"] == str(sessions[1].date())
    rows = {x["category"]: x for x in r["horizons"]["1M"]["rows"]}
    assert rows["Entra ora"]["n"] == 1 and rows["Entra ora"]["days"] == 1        # only the day that is not excluded
    assert all(h != str(sessions[1].date()) for h, _, _ in diary.verdict_history("AAA"))


def test_results_by_deciding_rule_from_saved_rules(private_folder):
    sessions = pd.bdate_range("2026-10-01", periods=30)
    bench = pd.Series(100.0, index=sessions)
    closes = {"AAA": pd.Series(100.0, index=sessions), "BBB": pd.Series(100.0, index=sessions)}
    old_style = [entry("AAA", "Attendi", rules=[{"id": "D1", "ok": True}, {"id": "D2", "ok": False}]),
                 entry("BBB", "Attendi", rules=[{"id": "D1", "ok": True}, {"id": "D2", "ok": True}, {"id": "D3", "ok": False}])]
    diary.save(str(sessions[0].date()), old_style)
    by = {(x["category"], x["rule"]) for x in diary.results(closes, bench)["horizons"]["1M"]["byRule"]}
    assert by == {("Attendi", "D2"), ("Attendi", "D3")}


def test_since_and_at_least():
    hist = [("2026-10-07", "Entra ora", 350), ("2026-10-06", "Entra ora", 345), ("2026-10-05", "Attendi", 340)]
    s = diary.since("Entra ora", 352, "2026-10-08", hist, "2026-10-05")
    assert (s["date"], s["price"], s["today"], s["atLeast"]) == ("2026-10-06", 345, False, False)
    s = diary.since("Entra ora", 352, "2026-10-07", hist, "2026-10-05")       # today already saved: its saved price
    assert s["date"] == "2026-10-06"
    s = diary.since("Evita", 352, "2026-10-08", hist, "2026-10-05")
    assert s["today"] and s["date"] == "2026-10-08" and not s["atLeast"]
    s = diary.since("Entra ora", 352, "2026-10-08", hist[:2], "2026-10-06")   # the run reaches the first diary day
    assert s["atLeast"] and s["date"] == "2026-10-06"


def test_missing_sessions_skip_weekends_and_holidays(private_folder):
    for d in ("2026-11-20", "2026-11-23", "2026-11-25"):
        diary.save(d, [entry("AAA", "Attendi")])
    # 21-22 Nov weekend, 24 Nov missing, 26 Nov Thanksgiving (NYSE closed), 27 Nov missing
    assert diary.missing("2026-11-27") == ["2026-11-24", "2026-11-27"]
