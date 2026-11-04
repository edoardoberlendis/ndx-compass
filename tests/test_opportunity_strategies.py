"""Ricerca controllata delle strategie (phase 4B): opportunity_strategies.py. Only made-up prices (S00, S01, ...), no
network, never the real reports, the diary or the files in portafoglio/."""
import copy
import json
import os

import numpy as np
import pandas as pd
import pytest

import opportunity_scanner as o
import opportunity_strategies as s
import opportunity_validation as v
from test_opportunity_validation import ohlcv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEG = {"sviluppo": ("2015-03-02", "2017-06-30"), "verifica": ("2017-08-01", "2018-12-31")}
FINAL = "2019-03-01"
NO_REVIEWS = {"version": "R0", "reviews": [], "listings": []}


def big_market(seed=3, n=14, days=1400):
    """QQQ with a fall in the middle and n stocks in two made-up sectors (8 'Tech', the rest 'Health')."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2014-01-02", periods=days)
    walk = lambda d, sd: 100 * np.cumprod(1 + rng.normal(d, sd, len(idx)))
    q = walk(0.0004, 0.012)
    if days > 800:
        q[700:800] *= np.linspace(1, 0.75, 100)
        q[800:] *= 0.75
    data = {"QQQ": ohlcv(idx, q, rng)}
    tickers = [f"S{i:02d}" for i in range(n)]
    for i, t in enumerate(tickers):
        data[t] = ohlcv(idx, walk(-0.0005 + 0.0001 * i, 0.02), rng)
    sectors = {t: ("Tech" if i < 8 else "Health") for i, t in enumerate(tickers)}
    return data, tickers, sectors


@pytest.fixture
def periods(monkeypatch):
    monkeypatch.setattr(s, "SEGMENTS", SEG)
    monkeypatch.setattr(s, "FINAL_START", FINAL)


def run(data, tickers, sectors, **kw):
    return s.run_all(s.cut_final(data), tickers, sectors, {"removed": []}, random_runs=kw.pop("random_runs", 3),
                     check_n=kw.pop("check_n", 10), reviews=kw.pop("reviews", NO_REVIEWS), **kw)


@pytest.fixture(scope="module")
def study():
    mp = pytest.MonkeyPatch()
    mp.setattr(s, "SEGMENTS", SEG)
    mp.setattr(s, "FINAL_START", FINAL)
    data, tickers, sectors = big_market()
    reps = run(data, tickers, sectors)
    yield data, tickers, sectors, reps
    mp.undo()


# ---------------------------------------------------------------- A: momentum relative to the sector

def test_sector_momentum_12_1_and_rank_within_sector(study):
    data, tickers, sectors, _ = study
    P = v.prepare(s.cut_final(data), tickers)
    I = s.indicators(P, sectors)
    C = P["close"]
    d = 400
    t = "S03"
    want = (C[t].iloc[d - 21] / C[t].iloc[d - 252] - 1) * 100
    assert I["mom"][t].iloc[d] == pytest.approx(want)
    tech = [x for x in tickers if sectors[x] == "Tech"]
    row = I["mom"].iloc[d][tech]
    assert I["pctSector"].iloc[d][t] == pytest.approx(row.rank(pct=True)[t])
    assert I["srm"].iloc[d][t] == pytest.approx(row[t] - row.median())
    # A_TOP is the top third of its own sector, A_BOT the bottom third: never both
    m = s.masks_a(I)
    assert not (m["A_TOP"] & m["A_BOT"]).to_numpy().any()
    assert (m["A_TOP"].iloc[d][tech].sum()) == (I["pctSector"].iloc[d][tech] > 2 / 3).sum()


def test_missing_or_small_sector_gets_no_value(study):
    data, tickers, sectors, _ = study
    P = v.prepare(s.cut_final(data), tickers)
    sec = dict(sectors)
    sec["S00"] = None                                    # classification missing: never invented
    for t in ("S08", "S09", "S10", "S11"):
        sec[t] = "Tiny"                                  # 4 stocks: below the 5 peers needed
    I = s.indicators(P, sec)
    assert I["pctSector"]["S00"].isna().all() and I["srm"]["S00"].isna().all()
    assert I["pctSector"][["S08", "S09", "S10", "S11"]].isna().all().all()
    m = s.masks_a(I)
    assert not m["A_TOP"]["S00"].any() and not m["A_BOT"]["S00"].any()   # not counted as weak either


def test_indicators_use_no_future_prices(study):
    data, tickers, sectors, _ = study
    P = v.prepare(s.cut_final(data), tickers)
    I = s.indicators(P, sectors)
    d = 500
    cut = {t: df[df.index <= P["cal"][d]] for t, df in s.cut_final(data).items()}
    I2 = s.indicators(v.prepare(cut, tickers), sectors)
    for k in ("mom", "pctSector", "pctUniverse", "trend", "pctRs21", "dd252", "ret126", "atr"):
        a, b = I[k].iloc[d], I2[k].iloc[d]
        assert ((a == b) | (a.isna() & b.isna())).all(), k
    assert (s.regimes(P["bench"]).iloc[: d + 1].to_numpy() == s.regimes(P["bench"].iloc[: d + 1]).to_numpy()).all()


def test_additional_information_and_sector_return_reported(study):
    A = study[3]["A"]
    assert set(A["pairs"]) == {"A_TOP − A_BOT", "A_TOP − A_NDX", "A_INC − altri", "A_TOP − C4"}
    assert isinstance(A["additionalInformation"]["credible"], bool)
    assert set(A["vsSector"]) == {"sviluppo", "verifica", "tutto"}
    assert "oggi" in A["dataLimit"] and A["sectorsUsed"] == {"Health": 6, "Tech": 8}


# ---------------------------------------------------------------- B: pullback in the structural trend

def test_pullback_needs_trend_weak_month_and_no_crash(study):
    data, tickers, sectors, _ = study
    P = v.prepare(s.cut_final(data), tickers)
    I = s.indicators(P, sectors)
    m = s.masks_b(I)
    C = P["close"]
    trend = (C > C.rolling(200).mean()) & (C.rolling(50).mean() > C.rolling(200).mean())
    assert (I["trend"] == trend).all().all()
    B = m["B"].to_numpy()
    assert (I["trend"].to_numpy()[B]).all()
    assert (I["pctRs21"].to_numpy()[B] <= 0.20).all()
    assert (I["dd252"].to_numpy()[B] > -25).all()
    assert not (m["B"] & m["B_TNP"]).to_numpy().any()          # the two comparison groups never overlap B
    assert not (m["B"] & m["B_PNT"]).to_numpy().any()
    assert (m["B_CONF"] <= m["B"]).all().all() and (m["B_ATR"] <= m["B"]).all().all()


def test_b_report_declares_it_was_born_from_the_data(study):
    B = study[3]["B"]
    assert B["dataGenerated"] is True and "NON sono una prova indipendente" in B["dataLimit"]
    assert set(B["sensitivity"]) == {"B_CONF", "B_ATR", "WINSOR", "SUSPECT"}


# ---------------------------------------------------------------- C: market context

def test_regimes_from_qqq_only():
    idx = pd.bdate_range("2020-01-01", periods=500)
    q = pd.Series(np.r_[np.linspace(100, 150, 250), np.linspace(150, 110, 50), np.linspace(110, 250, 200)], index=idx)
    r = s.regimes(q)
    assert (r.iloc[:199] == "n.d.").all()
    assert r.iloc[249] == "rialzista"
    ma = q.rolling(200).mean()
    below = np.nonzero((q < ma).to_numpy())[0]
    assert (r.iloc[below] == "ribassista").all()
    first_up = below[-1] + 1
    assert len(below) and first_up + 63 < len(q) and (q > ma).iloc[first_up:].all()
    assert r.iloc[first_up] == "recupero" and r.iloc[first_up + 62] == "recupero"
    assert r.iloc[first_up + 63] == "rialzista"


def test_episodes_merge_close_spells():
    rows = np.arange(100)
    flags = np.zeros(100, dtype=bool)
    flags[[5, 6, 7, 20, 60, 61]] = True
    assert s.episodes(rows, flags, gap=21) == 2
    assert s.episodes(rows, flags, gap=5) == 3
    assert s.episodes(rows, np.zeros(100, dtype=bool)) == 0


def test_context_report_separates_timing_from_selection(study):
    Cr = study[3]["C"]
    assert Cr["state"] == "Evidenza insufficiente"               # one fall only: fewer episodes than required
    assert "breadth" in Cr and "survivorship" in Cr["breadth"]
    for x in Cr["filter"]:
        assert x["beyondTiming"] == pytest.approx((x["netWith"] - x["netWithout"]) - (x["qqqFiltered"] - x["qqq"]), abs=0.02)
        assert x["exposureWith"] <= x["exposureWithout"] and x["missedTrades"] >= 0
    assert set(Cr["secondaryTwoStates"]["B"]["tutto"]) == {"rialzista", "ribassista"}


# ---------------------------------------------------------------- final period, periods, benchmarks

def test_final_period_never_loaded(periods):
    data, tickers, sectors = big_market()
    cut = s.cut_final(data)
    assert all(df.index.max() < pd.Timestamp(FINAL) for df in cut.values())
    with pytest.raises(RuntimeError, match="periodo finale"):
        s.run_all(data, tickers, sectors, {"removed": []}, random_runs=0, with_sim=False, check_n=5, reviews=NO_REVIEWS)


def test_fixed_periods_without_final_segment(study):
    data, tickers, sectors, reps = study
    P = v.prepare(s.cut_final(data), tickers)
    lab = s.StratLab(P, s.indicators(P, sectors)["elig"], {"X": np.ones((len(P["cal"]), len(P["names"])), dtype=bool)})
    assert set(lab.segments) == {"sviluppo", "verifica", "tutto"}
    days = lab.cal[lab.segments["sviluppo"]]
    assert days[0] >= pd.Timestamp(SEG["sviluppo"][0]) and days[-1] <= pd.Timestamp(SEG["sviluppo"][1])
    assert not (lab.segments["sviluppo"] & lab.segments["verifica"]).any()
    assert (lab.masks["X"] <= lab.E).all()
    assert reps["A"]["period"]["finalRead"] is False


def test_pair_is_mean_of_same_day_differences(study):
    data, tickers, sectors, _ = study
    P = v.prepare(s.cut_final(data), tickers)
    I = s.indicators(P, sectors)
    lab = s.StratLab(P, I["elig"], s.masks_b(I, extra=False))
    seg = lab.segments["tutto"]
    p = s.pair(lab, "B", "B_TNP", 21, seg)
    f, E = lab.fwd[21], lab.E
    diffs = []
    for i in np.nonzero(seg)[0]:
        a, b = lab.masks["B"][i], lab.masks["B_TNP"][i]
        if a.any() and b.any():
            diffs.append(f[i, a].mean() - f[i, b].mean())
    assert p["days"] == len(diffs) and p["mean"] == pytest.approx(np.mean(diffs), abs=1e-3)
    # against the non-selected: the same number as the phase 3 summary
    q = s.pair(lab, "B", None, 21, seg)
    assert q["mean"] == pytest.approx(lab.summary("B", 21, seg)["vsOthers"], abs=1e-3)


def test_forward_returns_and_qqq_benchmark_same_window(study):
    data, tickers, sectors, _ = study
    P = v.prepare(s.cut_final(data), tickers)
    I = s.indicators(P, sectors)
    lab = s.StratLab(P, I["elig"], s.masks_b(I, extra=False))
    C, Q = P["close"].to_numpy(), P["bench"].to_numpy()
    assert lab.fwd[10][300, 2] == pytest.approx((C[310, 2] / C[300, 2] - 1) * 100)
    assert lab.qf[10][300] == pytest.approx((Q[310] / Q[300] - 1) * 100)


def test_simulation_enters_next_open_never_at_signal_close(study):
    for k in ("A", "B"):
        sim = study[3][k]["simulation"]
        assert sim["available"] and sim["random"]["runs"] == v.SIM["random_runs"]
        assert {x["cost"] for x in sim["senza filtro"]} == set(v.SIM["costs"])
        assert all(x["exposure"] <= 100 for x in sim["senza filtro"])
    data, tickers, sectors, _ = study
    P = v.prepare(s.cut_final(data), tickers)
    I = s.indicators(P, sectors)
    lab = s.StratLab(P, I["elig"], s.masks_b(I, extra=False))
    r = v.simulate(P, None, np.asarray(lab._given["B"]) & np.asarray(lab.F["valid"]), lab.segments["tutto"], 0.1)
    for t in r["trades"][:20]:
        assert pd.Timestamp(t["entry"]) > pd.Timestamp(t["signal"])


def test_reproducible(study):
    data, tickers, sectors, reps = study
    mp = pytest.MonkeyPatch()
    mp.setattr(s, "SEGMENTS", SEG)
    mp.setattr(s, "FINAL_START", FINAL)
    again = run(data, tickers, sectors)
    mp.undo()
    for k in reps:
        a, b = (json.loads(json.dumps(v.finite({x: y for x, y in r[k].items() if x not in ("createdAt", "seconds")})))
                for r in (reps, again))
        assert a == b


# ---------------------------------------------------------------- data quality

def test_suspect_window_excluded_only_in_sensitivity(study):
    data, tickers, sectors, _ = study
    P = v.prepare(s.cut_final(data), tickers)
    I = s.indicators(P, sectors)
    lab = s.StratLab(P, I["elig"], s.masks_b(I, extra=False))
    d = lab.cal[600].date().isoformat()
    keep, n = s.suspect_keep(lab, [{"status": "sospetto", "ticker": "S04", "from": d},
                                   {"status": "reale", "ticker": "S05", "from": d},
                                   {"status": "sospetto", "ticker": "S06", "from": None}])
    col = P["names"].index("S04")
    assert n == 1
    assert not keep[600 - 21:600 + 253, col].any() and keep[600 - 22, col] and keep[600 + 253, col]
    assert keep[:, P["names"].index("S05")].all()             # a confirmed real move is never removed


def test_verified_errors_removed_on_a_copy_and_counted(periods):
    data, tickers, sectors = big_market()
    rev = {"version": "R1", "reviews": [{"ticker": "S02", "from": "2014-01-01", "to": "2015-06-30", "status": "errore",
                                         "exclude": True}]}
    import market_data_quality as mq
    before = copy.deepcopy(data["S02"])
    treated, removed = mq.apply_verified(data, rev)
    assert data["S02"].equals(before) and removed[0]["rows"] > 0      # the original series is untouched
    lost = s.excluded_observations(s.cut_final(data), s.cut_final(treated), tickers)
    assert lost == removed[0]["rows"]


def test_load_frozen_refuses_other_prices_and_other_review(tmp_path, monkeypatch):
    data, tickers, sectors = big_market(days=300)
    pd.to_pickle({"saved": "x", "start": "x", "tickers": tickers, "data": data}, tmp_path / s.SNAPSHOT)
    with pytest.raises(SystemExit, match="congelato"):
        s.load_frozen(prices_dir=str(tmp_path), out_dir=str(tmp_path), reviews=NO_REVIEWS)
    monkeypatch.setattr(s, "SNAPSHOT_SHA", s._sha(tmp_path / s.SNAPSHOT))
    with pytest.raises(SystemExit, match="revisione"):
        s.load_frozen(prices_dir=str(tmp_path), out_dir=str(tmp_path), reviews=NO_REVIEWS)


# ---------------------------------------------------------------- registration, immutability, states

def test_register_once_and_run_refused_if_config_changed(tmp_path, monkeypatch, capsys):
    rec = s.register()
    assert rec["configHash"] == s.config_hash() and rec["version"] == s.VERSION and "cieco" in rec["exposure"]
    with pytest.raises(SystemExit, match="già registrata"):
        s.register()
    monkeypatch.setitem(s.B, "pullback_pct", 0.25)               # a change after the registration
    with pytest.raises(SystemExit, match="cambiata"):
        s.main(["x", "run"])
    monkeypatch.setitem(s.B, "pullback_pct", 0.20)
    s.main(["x", "config"])
    assert "registrata: sì" in capsys.readouterr().out


def test_run_refused_without_registration():
    with pytest.raises(SystemExit, match="registra"):
        s.main(["x", "run"])


def test_saved_reports_separate_from_phase3_and_append_only_log(study, tmp_path):
    reps = study[3]
    d1 = s.save_reports(reps)
    assert d1.startswith(s.OUT_DIR) and not d1.startswith(v.OUT_DIR)
    assert sorted(os.listdir(d1)) == ["strategia_A.json", "strategia_B.json", "strategia_C.json"]
    log = os.path.join(s.OUT_DIR, "registro.jsonl")
    first = open(log).read()
    s.save_reports(reps)
    assert open(log).read().startswith(first) and len(open(log).read().splitlines()) == 2
    summ = s.read_summary()
    assert [r["id"] for r in summ["rows"]] == ["A", "B", "C"] and all(r["state"] in s.STATES for r in summ["rows"])
    assert not os.path.exists(v.LOG)                              # phase 3 log never written


def test_states_follow_the_registered_rules():
    def block(verdict, dev_t=2.5, ver_t=1.5):
        return {"21": {"verdict": verdict, "sviluppo": {"tOthers": dev_t}, "verifica": {"tOthers": ver_t}}}
    good_sim = {"senza filtro": [{"cost": 0.1, "total": 50}], "random": {"median": 20}}
    sens = [{"mean": 1, "t": 2.5}]
    assert s.state_of(block("x"), sens, good_sim, verifiable=False)[0] == "Ipotesi non verificabile"
    assert s.state_of(block("Evidenza insufficiente"), sens, good_sim)[0] == "Evidenza insufficiente"
    assert s.state_of(block("Differenza peggiore credibile"), sens, good_sim)[0] == "Nessun vantaggio rilevato"
    assert s.state_of(block("Differenza migliore credibile"), sens, good_sim)[0] == "Risultato esplorativo promettente"
    assert s.state_of(block("Differenza migliore credibile", 3.2), sens, good_sim)[0] == "Candidato a verifica prospettica"
    assert s.state_of(block("Differenza migliore credibile", 3.2), [{"mean": -1, "t": 2.5}], good_sim)[0] == \
        "Risultato esplorativo promettente"
    bad_sim = {"senza filtro": [{"cost": 0.1, "total": 10}], "random": {"median": 20}}
    assert s.state_of(block("Differenza migliore credibile", 3.2), sens, bad_sim)[0] == "Risultato esplorativo promettente"
    assert "Strategia validata" not in s.STATES


def test_comparison_with_old_rule_present(study):
    reps = study[3]
    assert "C4" in reps["A"]["groups"] and "C4" in reps["B"]["groups"]
    assert "A_TOP − C4" in reps["A"]["pairs"] and "B − C4" in reps["B"]["pairs"]


# ---------------------------------------------------------------- no effect on the operational scanner

def test_scanner_untouched():
    before = (o.TRADING_MIN, o.INVEST_MIN, o.ATR_HIGH, o.MODEL_VERSION)
    import importlib
    importlib.reload(s)
    assert (o.TRADING_MIN, o.INVEST_MIN, o.ATR_HIGH, o.MODEL_VERSION) == before
    for f in ("opportunity_scanner.py", "score.py", "decision.py", "opportunity_diary.py", "daily_job.py"):
        assert "opportunity_strategies" not in open(os.path.join(ROOT, f)).read(), f


def test_api_reads_summary_only(tmp_path):
    import server
    client = server.app.test_client()
    r = client.get("/api/opportunities/strategies")
    assert r.status_code == 200 and r.get_json() == {"available": False}
    os.makedirs(s.OUT_DIR, exist_ok=True)
    with open(os.path.join(s.OUT_DIR, "riepilogo.json"), "w") as f:
        json.dump({"rows": [{"id": "A", "state": "Evidenza insufficiente"}]}, f)
    r = client.get("/api/opportunities/strategies").get_json()
    assert r["available"] is True and r["summary"]["rows"][0]["id"] == "A"
