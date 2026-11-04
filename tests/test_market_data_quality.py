"""Phase 4A: data-quality checks (market_data_quality.py), the recheck of a saved study with verified data and the
reliability states shown in the Opportunità page. Only made-up prices, no network, never the real diary or reports."""
import json
import os

import numpy as np
import pandas as pd
import pytest

import market_data_quality as mq
import opportunity_diary as od
import opportunity_validation as v
from test_opportunity_validation import market, small_study

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_REVIEWS = {"version": "T0", "reviews": [], "listings": [], "criteria": ["prova"]}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import server

    def fail(*a, **k):
        raise AssertionError("nessun download nei test")
    monkeypatch.setattr(server, "download", fail)


def kinds(q, ticker):
    return {x["kind"] for x in q["issues"] if x["ticker"] == ticker}


def by_kind(q, ticker, kind):
    return [x for x in q["issues"] if x["ticker"] == ticker and x["kind"] == kind]


# ---------------------------------------------------------------- anomalies are recognised

def test_clean_data_has_no_anomalies():
    data, tickers = market()
    q = mq.check(data, tickers, reviews=NO_REVIEWS)
    assert q["benchmark"]["available"] and q["issues"] == []
    assert q["counts"] == {"errore": 0, "sospetto": 0, "reale": 0, "mancante": 0}


def test_extreme_move_reversal_and_split_are_flagged_not_corrected():
    data, tickers = market()
    df = data["S01"]
    before = {t: d.copy() for t, d in data.items()}
    i = 150
    df.iloc[i:, [0, 1, 2, 3]] /= 2                       # unadjusted 2:1 split: -50% with normal volume
    data["S02"].iloc[200, [0, 1, 2, 3]] *= 1.30          # one bad print: +30% then back
    q = mq.check(data, tickers, reviews=NO_REVIEWS)
    jump = by_kind(q, "S01", "variazione estrema")
    assert jump and jump[0]["value"] < -40 and jump[0]["status"] == "sospetto"
    assert by_kind(q, "S01", "possibile frazionamento non rettificato")
    rev = by_kind(q, "S02", "inversione")
    assert rev and rev[0]["from"] == data["S02"].index[200].date().isoformat()
    # a warning, never a correction: the data passed in are unchanged
    pd.testing.assert_frame_equal(data["S01"].iloc[:i], before["S01"].iloc[:i])
    assert data["S01"]["Close"].iloc[i] == pytest.approx(before["S01"]["Close"].iloc[i] / 2)


def test_big_real_move_with_huge_volume_is_not_called_a_split():
    data, tickers = market()
    df = data["S03"]
    df.iloc[180:, [0, 1, 2, 3]] *= 2.0                   # +100% with 30 times the volume: news, not a split
    df.iloc[180, 4] = df["Volume"].iloc[150:180].median() * 30
    q = mq.check(data, tickers, reviews=NO_REVIEWS)
    assert by_kind(q, "S03", "variazione estrema")
    assert not by_kind(q, "S03", "possibile frazionamento non rettificato")


def test_missing_prices_sessions_and_volumes():
    data, tickers = market()
    data["S01"] = data["S01"].drop(data["S01"].index[[40, 41]])          # sessions missing against QQQ
    data["S02"].iloc[60, 3] = np.nan                                   # empty close
    data["S03"].iloc[70, 4] = 0.0                                      # one volume missing
    data["S04"].iloc[80, 0] = np.nan                                   # open missing
    data["S05"] = data["S05"].iloc[:0]                                 # no series at all
    q = mq.check(data, tickers, reviews=NO_REVIEWS)
    for t, k in (("S01", "sedute mancanti rispetto a QQQ"), ("S02", "prezzi mancanti"), ("S03", "volume a zero"),
                 ("S04", "apertura mancante"), ("S05", "serie assente")):
        x = by_kind(q, t, k)
        assert x and x[0]["status"] == "mancante", (t, k)
    assert by_kind(q, "S01", "sedute mancanti rispetto a QQQ")[0]["n"] == 2


def test_incoherent_prices_duplicates_and_non_positive():
    data, tickers = market()
    data["S01"].iloc[90, 1] = data["S01"]["Low"].iloc[90] * 0.5         # high below low
    data["S02"].iloc[95, 3] = 0.0                                      # zero price
    data["S03"] = pd.concat([data["S03"], data["S03"].iloc[[100]]])    # a duplicated day
    q = mq.check(data, tickers, reviews=NO_REVIEWS)
    assert by_kind(q, "S01", "apertura, massimo, minimo e chiusura incoerenti")
    assert by_kind(q, "S02", "prezzo nullo o negativo")
    assert by_kind(q, "S03", "date duplicate")


def test_illiquid_stale_series_like_fer():
    data, tickers = market(n_days=520)
    df = data["S06"]
    stale = df.index.year == df.index[0].year                           # first year: price frozen, no trades
    df.loc[stale, ["Open", "High", "Low", "Close"]] = 20.0
    df.loc[stale, "Volume"] = 0.0
    q = mq.check(data, tickers, reviews=NO_REVIEWS)
    ill = by_kind(q, "S06", "periodo illiquido (volume a zero)")
    assert ill and ill[0]["status"] == "sospetto" and ill[0]["n"] == int(stale.sum())


def test_dates_benchmark_and_future_rows():
    data, tickers = market()
    q = mq.check(data, tickers, as_of=data["QQQ"].index[-1].date().isoformat(), reviews=NO_REVIEWS)
    assert q["future"]["rows"] == [] and q["calendar"]["weekend"] == 0 and q["calendar"]["duplicates"] == 0
    early = data["QQQ"].index[-5].date().isoformat()
    q2 = mq.check(data, tickers, as_of=early, reviews=NO_REVIEWS)
    assert {r["ticker"] for r in q2["future"]["rows"]} >= {"QQQ", "S00"}
    assert by_kind(q2, "S00", "dati dopo la data del calcolo")
    no_bench = {k: d for k, d in data.items() if k != "QQQ"}
    q3 = mq.check(no_bench, tickers, reviews=NO_REVIEWS)
    assert q3["benchmark"] == {"available": False} and q3["issues"][0]["kind"] == "benchmark assente"


def test_nyse_calendar_exact_for_written_years():
    idx = pd.bdate_range("2026-01-02", "2026-03-31")
    good = idx[[d.date() not in (pd.Timestamp("2026-01-19").date(), pd.Timestamp("2026-02-16").date()) for d in idx]]
    c = mq.check_calendar(good)
    assert c["nyse"]["2026"] == {"missing": [], "extra": []}
    c2 = mq.check_calendar(idx)                                        # two holidays traded: wrong calendar
    assert c2["nyse"]["2026"]["extra"] == ["2026-01-19", "2026-02-16"]


# ---------------------------------------------------------------- statuses: only a review confirms or rejects

def test_reviews_set_the_four_statuses():
    data, tickers = market()
    data["S01"].iloc[150:, [0, 1, 2, 3]] *= 2.5
    data["S02"].iloc[160:, [0, 1, 2, 3]] *= 0.4
    d1, d2 = (data[t].index[i].date().isoformat() for t, i in (("S01", 150), ("S02", 160)))
    rev = {"version": "T1", "listings": [], "criteria": [], "reviews": [
        {"ticker": "S01", "from": d1, "to": d1, "status": "reale", "note": "notizia confermata", "sources": ["fonte A"]},
        {"ticker": "S02", "from": d2, "to": d2, "status": "errore", "exclude": False, "note": "smentito", "sources": ["fonte B"]},
        {"ticker": "S03", "from": "2024-03-01", "to": "2024-03-01", "status": "sospetto", "note": "da guardare"}]}
    q = mq.check(data, tickers, reviews=rev)
    assert by_kind(q, "S01", "variazione estrema")[0]["status"] == "reale"
    assert by_kind(q, "S02", "variazione estrema")[0]["status"] == "errore"
    assert by_kind(q, "S03", "revisione manuale")[0]["status"] == "sospetto"     # a review without automatic warning
    assert set(mq.STATUS) == {"errore", "sospetto", "reale", "mancante"}


def test_listing_date_flags_prices_before_regular_trading():
    data, tickers = market()
    first_regular = data["S04"].index[120].date().isoformat()
    rev = {"version": "T2", "reviews": [], "criteria": [],
           "listings": [{"ticker": "S04", "regular": first_regular, "note": "quotazione regolare dal giorno 120"}]}
    q = mq.check(data, tickers, reviews=rev)
    x = by_kind(q, "S04", "prezzi prima della quotazione regolare")
    assert x and x[0]["n"] == 120 and x[0]["status"] == "sospetto"


def test_apply_verified_returns_a_copy_and_only_verified_exclusions():
    data, tickers = market()
    start = data["S01"].index[100].date().isoformat()
    rev = {"version": "T3", "listings": [], "criteria": [], "reviews": [
        {"ticker": "S01", "from": "2000-01-01", "to": start, "status": "errore", "exclude": True, "note": "x"},
        {"ticker": "S02", "from": "2000-01-01", "to": start, "status": "sospetto", "exclude": True, "note": "y"},
        {"ticker": "S03", "from": "2000-01-01", "to": start, "status": "errore", "exclude": False, "note": "z"}]}
    n_before = len(data["S01"])
    new, removed = mq.apply_verified(data, rev)
    assert [r["ticker"] for r in removed] == ["S01"] and removed[0]["rows"] == 101 and removed[0]["middle"] is False
    assert len(data["S01"]) == n_before and new["S01"].index[0] == data["S01"].index[101]
    assert new["S02"] is data["S02"] and new["S03"] is data["S03"]     # suspicious or not excluded: untouched


def test_impact_maps_issues_to_study_periods():
    segs = {"sviluppo": {"from": "2016-01-11", "to": "2022-05-13"}, "verifica": {"from": "2022-06-15", "to": "2024-07-10"},
            "finale": {"from": "2024-08-09", "to": "2026-10-05", "sealed": True}, "tutto": {"from": "2016-01-11", "to": "2024-07-10"}}
    issues = [{"ticker": "A", "from": "2018-05-23", "to": "2018-05-23"}, {"ticker": "B", "from": "2026-08-19", "to": "2026-08-19"},
              {"ticker": "C", "from": "2024-07-26", "to": "2024-07-26"}]
    got = {x["ticker"]: x["periods"] for x in mq.impact(issues, segs)}
    assert got == {"A": ["sviluppo"], "B": ["finale"], "C": ["verifica", "finale"]}


def test_real_reviews_file_is_coherent():
    rev = mq.load_reviews()
    assert rev["version"] and rev["criteria"]
    for r in rev["reviews"]:
        assert r["status"] in mq.STATUS and r["from"] <= r["to"] and r["note"]
        if r["status"] in ("errore", "reale"):
            assert r.get("sources"), r["ticker"]                   # confirmed or rejected only with a source
        if r.get("exclude"):
            assert r["status"] == "errore"
    statuses = {(r["ticker"], r["status"]) for r in rev["reviews"]}
    assert ("FER", "errore") in statuses and ("MRNA", "reale") in statuses


# ---------------------------------------------------------------- recheck: originals kept, results reproducible

def test_recheck_keeps_originals_and_reproduces(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "RANDOM_RUNS", 5)
    data, tickers = market(n_days=320)
    os.makedirs(v.OUT_DIR, exist_ok=True)
    snap = "prezzi_prova.pkl"
    pd.to_pickle({"saved": "2025-03-20T09:00:00-04:00", "start": "x", "tickers": tickers, "data": data},
                 os.path.join(v.OUT_DIR, snap))
    r = v.study(data, tickers, source={"kind": "prova", "file": snap}, random_runs=5, check_n=30)
    path = v.save(r)
    before = {f: open(os.path.join(v.OUT_DIR, f), "rb").read() for f in os.listdir(v.OUT_DIR) if os.path.isfile(os.path.join(v.OUT_DIR, f))}
    cut = data["S02"].index[60].date().isoformat()
    rev = {"version": "T9", "listings": [], "criteria": ["prova"], "reviews": [
        {"ticker": "S02", "from": "2000-01-01", "to": cut, "status": "errore", "exclude": True, "note": "prova", "sources": ["x"]}]}
    monkeypatch.setattr(v, "study", lambda *a, **k: _study(*a, **{**k, "random_runs": 5, "check_n": 30}))
    out, new, reproduced = v.recheck(path, reviews=rev)
    assert reproduced is True                                           # same prices, same results
    after = {f: open(os.path.join(v.OUT_DIR, f), "rb").read() for f in before}
    assert after == before                                              # original report, log, summary, prices untouched
    assert os.path.dirname(out) == v.RECHECK_DIR != v.OUT_DIR
    assert new["dataTreatment"]["removed"][0]["ticker"] == "S02" and new["period"]["finalOpened"] is False
    assert new["comparison"]["observations"][1] < new["comparison"]["observations"][0]
    summary = v.read_recheck()
    assert summary["reproducedOriginal"] is True and summary["reviews"] == "T9" and "C4" in summary["verdicts"]
    lines = open(os.path.join(v.RECHECK_DIR, "registro.jsonl")).read().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["finalOpened"] is False


_study = v.study


def test_recheck_refuses_an_opened_final_period(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"period": {"finalOpened": True}, "source": {"file": "x.pkl"}}))
    with pytest.raises(SystemExit):
        v.recheck(str(p), reviews=NO_REVIEWS)


def test_same_results_detects_any_change():
    data, tickers = market()
    a = v.finite(small_study(data, tickers))
    b = json.loads(json.dumps(a))
    b["createdAt"], b["seconds"] = "altro", 99
    assert v.same_results(a, b)
    b["groups"]["C4"]["h"]["21"]["tutto"]["n"] += 1
    assert not v.same_results(a, b)


# ---------------------------------------------------------------- reliability states in the dashboard

SUMMARY = {"horizon": 21, "rows": [
    {"id": "C4", "vsOthers": -0.12, "verdicts": {"5": "Differenza osservata, non credibile", "10": "Differenza osservata, non credibile",
                                                   "21": "Differenza osservata, non credibile"}},
    {"id": "C5", "vsOthers": -0.09, "verdicts": {"5": "Evidenza insufficiente", "10": "Evidenza insufficiente",
                                                   "21": "Differenza peggiore credibile nello studio esplorativo (confermata nel periodo di verifica)"}}]}


def test_reliability_states_today():
    R = v.reliability(SUMMARY, None, {"started": False, "days": 0})
    st = {x["id"]: x["state"] for x in R["items"]}
    assert st == {"C4": "non_validata", "C5": "non_validata", "INV": "non_validata"}
    assert R["screening"] == "Screening esplorativo" and "non è una previsione di rendimento" in R["note"]
    assert set(R["states"].values()) == {"Screening esplorativo", "Strategia in fase di verifica",
                                         "Strategia validata secondo criteri documentati",
                                         "Strategia non validata o con risultati insufficienti"}
    inv = next(x for x in R["items"] if x["id"] == "INV")
    assert "point-in-time" in inv["reason"]


def test_reliability_follows_documented_criteria():
    better = {"horizon": 21, "rows": [{"id": "C4", "vsOthers": 0.8, "verdicts": {
        "21": "Differenza migliore credibile nello studio esplorativo (confermata nel periodo di verifica)"}}]}
    R = v.reliability(better, None, {"started": True, "days": 3})
    st = {x["id"]: x["state"] for x in R["items"]}
    assert st["C4"] == "in_verifica"                     # never "validata" without the final period and the diary
    assert st["INV"] == "in_verifica" and "3 giornate registrate" in next(x for x in R["items"] if x["id"] == "INV")["reason"]
    assert "validata" not in st.values()
    # the recheck with verified data takes precedence over the original verdicts
    recheck = {"verdicts": {"C4": {"21": "Differenza osservata, non credibile"}}, "rows21": {"C4": 0.1}}
    assert next(x for x in v.reliability(better, recheck, None)["items"] if x["id"] == "C4")["state"] == "non_validata"
    assert all(x["state"] == "non_validata" for x in v.reliability(None, None, None)["items"])


def test_dashboard_shows_states_without_touching_rankings():
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    assert "oppStateLine(trading)" in js and "Stato di affidabilità" in js
    assert "Diario prospettico" in js and "Studio storico esplorativo" in js
    assert "non è una prova di redditività" in js
    for banned in ("Strategia vincente", "Compra ora", "Probabilità di guadagno"):
        assert banned not in js
    import opportunity_scanner as o
    assert (o.MODEL_VERSION, o.TRADING_MIN, o.INVEST_MIN, o.ATR_HIGH) == ("O2.1", 4, 5, 4.0)


def test_api_reliability_and_no_diary_created():
    import server
    x = server.app.test_client().get("/api/opportunities/validation").get_json()
    assert x["reliability"]["items"][0]["state"] == "non_validata" and x["diary"]["started"] is False
    assert not os.path.exists(od.DB) and not os.path.exists(v.DIARY)    # reading the state never creates the diary
