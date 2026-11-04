"""Laboratorio di validazione (phase O3): opportunity_validation.py. Only made-up prices (tickers S00, S01, ...), no
network, never the real opportunity diary or the files in portafoglio/."""
import json
import os

import numpy as np
import pandas as pd
import pytest

import opportunity_diary as od
import opportunity_scanner as o
import opportunity_validation as v

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ohlcv(idx, closes, rng, vol=None):
    c = np.asarray(closes, dtype=float)
    op = c / (1 + rng.normal(0, 0.003, len(c)))
    vol = np.asarray(vol, dtype=float) if vol is not None else rng.integers(500_000, 2_000_000, len(c)).astype(float)
    return pd.DataFrame({"Open": op, "High": np.maximum(c, op) * 1.01, "Low": np.minimum(c, op) * 0.99, "Close": c,
                         "Volume": vol}, index=idx)


def market(n_days=260, n=8, seed=1):
    """QQQ and n stocks on a business-day calendar with one weekday missing (a holiday: no session)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n_days + 1).delete(100)
    walk = lambda d, s: 100 * np.cumprod(1 + rng.normal(d, s, len(idx)))
    data = {"QQQ": ohlcv(idx, walk(0.0005, 0.01), rng)}
    tickers = [f"S{i:02d}" for i in range(n)]
    for i, t in enumerate(tickers):
        data[t] = ohlcv(idx, walk(-0.001 + 0.0005 * i, 0.02), rng)
    return data, tickers


def small_study(data, tickers, **kw):
    return v.study(data, tickers, random_runs=kw.pop("random_runs", 5), check_n=kw.pop("check_n", 40), **kw)


@pytest.fixture
def mk():
    return market()


@pytest.fixture(autouse=True)
def lab_files(tmp_path, monkeypatch):
    """Reports, log and the diary path of the lab always in a temporary folder; no download possible."""
    monkeypatch.setattr(v, "OUT_DIR", str(tmp_path / "validazione"))
    monkeypatch.setattr(v, "LOG", str(tmp_path / "validazione" / "esperimenti.jsonl"))
    monkeypatch.setattr(v, "DIARY", str(tmp_path / "data" / "opportunita.sqlite3"))
    import server

    def no_network(*a, **k):
        raise AssertionError("nessun download nei test")
    monkeypatch.setattr(server, "download", no_network)


# ---------------------------------------------------------------- returns, benchmark, calendar

def test_forward_returns_and_qqq_same_interval(mk):
    data, tickers = mk
    P = v.prepare(data, tickers)
    lab = v.Lab(P, v.features(P))
    C, Q = P["close"].to_numpy(), P["bench"].to_numpy()
    for h in v.HORIZONS:
        assert lab.fwd[h][10, 3] == pytest.approx((C[10 + h, 3] / C[10, 3] - 1) * 100)
        assert lab.qf[h][10] == pytest.approx((Q[10 + h] / Q[10] - 1) * 100)
        assert np.isnan(lab.fwd[h][-1]).all() and np.isnan(lab.qf[h][-h:]).all()   # unknown future stays unknown


def test_horizon_counts_sessions_not_calendar_days(mk):
    data, tickers = mk
    P = v.prepare(data, tickers)
    cal = P["cal"]
    gap = np.nonzero(np.diff(cal.values).astype("timedelta64[D]").astype(int) == 2)[0]   # the missing weekday (holiday)
    assert len(gap) == 1
    i = gap[0] - 2
    lab = v.Lab(P, v.features(P))
    C = P["close"].to_numpy()
    assert lab.fwd[5][i, 0] == pytest.approx((C[i + 5, 0] / C[i, 0] - 1) * 100)
    assert (cal[i + 5] - cal[i]).days == 8          # 5 sessions across a weekend and the holiday


def test_benchmark_coherence(mk):
    data, tickers = mk
    P = v.prepare(data, tickers)
    lab = v.Lab(P, v.features(P))
    h = 10
    dl = lab.daily("C3", h)
    rows = np.nonzero((dl["n"] > 0) & (dl["n"] < lab.E.sum(axis=1)))[0]
    r = rows[0]
    n_sel, n_all = dl["n"][r], lab.E[r].sum()
    # the universe mean of a day is the weighted mean of selected and not selected stocks of THAT day
    assert dl["uni"][r] == pytest.approx((dl["sel"][r] * n_sel + dl["non"][r] * (n_all - n_sel)) / n_all)
    assert dl["qqq"][r] == lab.qf[h][r]
    sel_cols = np.nonzero(lab.masks["C3"][r])[0]
    assert dl["sel"][r] == pytest.approx(np.mean(lab.fwd[h][r, sel_cols]))


# ---------------------------------------------------------------- conditions: same as the scanner, never the future

def test_conditions_identical_to_scanner(mk):
    data, tickers = mk
    data["S07"]["Volume"] = data["S07"]["Volume"].where(np.arange(len(data["S07"])) % 9 != 0, 0.0)   # T5 not judgeable
    P = v.prepare(data, tickers)
    F = v.features(P)
    checked, bad = v.check_against_scanner(P, F, n=150)
    assert checked == 150 and bad == []
    assert F["state"]["T5"]["S07"].dropna().empty                   # volumes unreliable: never counted as met


def test_no_future_information(mk):
    data, tickers = mk
    P1 = v.prepare(data, tickers)
    F1 = v.features(P1)
    d = P1["cal"][150]
    changed = {t: df.copy() for t, df in data.items()}
    for df in changed.values():
        df.loc[df.index > d, ["Open", "High", "Low", "Close"]] *= 3.0     # a different future
        df.loc[df.index > d, "Volume"] *= 0.1
    F2 = v.features(v.prepare(changed, tickers))
    for c in v.CONDS:
        a, b = F1["state"][c].loc[:d], F2["state"][c].loc[:d]
        pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(F1["atr"].loc[:d], F2["atr"].loc[:d])


def test_single_and_combined_conditions(mk):
    data, tickers = mk
    P = v.prepare(data, tickers)
    F = v.features(P)
    lab = v.Lab(P, F)
    met = sum((F["state"][c].to_numpy() == 1).astype(int) for c in v.CONDS)
    E = lab.E
    assert (lab.masks["C3"] == ((met >= 3) & E)).all()
    assert (lab.masks["C4"] == ((met >= o.TRADING_MIN) & E)).all()
    assert (lab.masks["C5"] == ((met == 5) & E)).all()
    assert (lab.masks["T1"] == ((F["state"]["T1"].to_numpy() == 1) & E)).all()
    assert not (lab.masks["A_LO"] & lab.masks["A_HI"]).any()
    assert ((lab.masks["A_LO"] | lab.masks["A_HI"]) == lab.masks["C4"]).all()


def test_relative_versus_absolute_groups(mk):
    data, tickers = mk
    P = v.prepare(data, tickers)
    F = v.features(P)
    lab = v.Lab(P, F)
    m = lab.masks
    assert not (m["G1"] & m["G2"]).any() and not (m["G1"] & m["G4"]).any()
    r21, r63, rs21 = F["ret21"].to_numpy(), F["ret63"].to_numpy(), F["rs21"].to_numpy()
    assert (rs21[m["G2"]] > 0).all() and ((r21[m["G2"]] < 0) | (r63[m["G2"]] < 0)).all()
    assert (r21[m["G1"]] > 0).all() and (r63[m["G1"]] > 0).all()
    assert (rs21[m["G3"]] <= 0).all()


# ---------------------------------------------------------------- incomplete data and price conventions

def test_incomplete_data_and_late_listing(mk):
    data, tickers = mk
    data["S01"] = data["S01"].drop(data["S01"].index[50])             # one session missing: calendar differs from QQQ
    data["S02"] = data["S02"].iloc[120:]                              # listed later
    data["S03"] = data["S03"].iloc[:0]                                # no prices at all
    P = v.prepare(data, tickers)
    assert "S01" in P["excluded"] and "giorni di borsa" in P["excluded"]["S01"]
    assert P["excluded"]["S03"] == "nessun prezzo"
    assert "S02" in P["quality"]["lateListing"]
    F = v.features(P)
    first_valid = F["valid"]["S02"].idxmax()
    assert P["cal"].get_loc(first_valid) == 120 + o.MIN_SESSIONS - 1   # 70 sessions of its own history first


def test_corporate_action_conventions(mk):
    data, tickers = mk
    raw = data["S04"].copy()
    raw.loc[raw.index >= raw.index[150], ["Open", "High", "Low", "Close"]] /= 2     # unadjusted 2:1 split
    data["S04"] = raw
    P = v.prepare(data, tickers)
    assert any(j["ticker"] == "S04" and j["move"] < -40 for j in P["quality"]["jumps"])
    data2, _ = market()
    assert not [j for j in v.prepare(data2, tickers)["quality"]["jumps"] if j["ticker"] == "S04"]
    assert "rettificati" in v.PRICE_CONVENTION and "QQQ" in v.PRICE_CONVENTION


def test_closed_sessions_only(mk):
    data, tickers = mk
    last = data["QQQ"].index[-3]
    P = v.prepare(data, tickers, last_day=last.date().isoformat())
    assert P["cal"][-1] == last and P["close"].index[-1] == last


# ---------------------------------------------------------------- development / verification / final

def test_segments_in_time_order_with_purge(mk):
    data, tickers = market(n_days=400)
    P = v.prepare(data, tickers)
    lab = v.Lab(P, v.features(P))
    s = lab.segments
    dev, ver, fin = (np.nonzero(s[k])[0] for k in ("sviluppo", "verifica", "finale"))
    purge = max(v.HORIZONS)
    assert dev[-1] + purge < ver[0] and ver[-1] + purge < fin[0]
    assert not (s["tutto"] & s["finale"]).any()                       # the final period stays sealed
    lab2 = v.Lab(P, v.features(P), open_final=True)
    assert (lab2.segments["tutto"] & lab2.segments["finale"]).any()


def test_final_period_sealed_and_logged(mk, tmp_path):
    data, tickers = mk
    r = small_study(data, tickers, with_sim=False)
    assert r["period"]["segments"]["finale"]["sealed"] is True
    assert all("finale" not in g["h"]["21"] for g in r["groups"].values())
    v.save(r)
    h = r["configHash"]
    assert v.final_uses(h) == 0
    r2 = small_study(data, tickers, open_final=True, with_sim=False)
    v.save(r2)
    assert v.final_uses(h) == 1
    lines = open(v.LOG).read().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["finalOpened"] is True    # the log only grows


# ---------------------------------------------------------------- dependence and evidence

def test_overlapping_signals_statistics():
    rng = np.random.default_rng(3)
    x = np.convolve(rng.normal(0.2, 1, 600), np.ones(21) / 21, mode="valid")   # strongly overlapping, like 21-day returns
    naive = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    assert abs(v.nw_t(x, 21)) < abs(naive) / 2
    n, mean, t = v.independent(list(range(len(x))), x, 21)
    assert n == (len(x) - 1) // 21 + 1


def test_insufficient_sample_and_verdict_rules(mk):
    data, tickers = mk
    r = small_study(data, tickers, with_sim=False)
    assert {g["h"]["21"]["verdict"] for g in r["groups"].values() if g["judged"]} == {"Evidenza insufficiente"}
    dev = {"n": 500, "indep": 40, "vsOthers": 1.0, "tOthers": 3.0, "randomPct": 99.0}
    assert v.verdict(dev, {"n": 300, "indep": 15, "vsOthers": 0.5}).startswith("Differenza migliore credibile")
    assert "non confermata" in v.verdict(dev, {"n": 300, "indep": 15, "vsOthers": -0.5})
    assert "verifica non possibile" in v.verdict(dev, {"n": 300, "indep": 3, "vsOthers": 0.5})
    assert v.verdict({**dev, "tOthers": 1.2}, None) == "Differenza osservata, non credibile"
    assert v.verdict({**dev, "randomPct": 60.0}, None) == "Differenza osservata, non credibile"
    assert v.verdict({**dev, "n": 99}, None) == "Evidenza insufficiente"


# ---------------------------------------------------------------- simulation: never before the signal

def test_simulation_executes_after_signal(mk):
    data, tickers = market(n_days=300)
    P = v.prepare(data, tickers)
    F = v.features(P)
    cal = list(P["cal"])
    seg = np.zeros(len(cal), dtype=bool)
    seg[100:180] = True
    mask = np.zeros(P["close"].shape, dtype=bool)
    mask[100:180, :] = True                                           # every stock signalled every day
    res = v.simulate(P, F, mask, seg, cost_pct=0.0, max_pos=3, hold=5)
    O = P["open"].to_numpy()
    held = {}
    for tr in res["trades"]:
        s, e, x = cal.index(pd.Timestamp(tr["signal"])), cal.index(pd.Timestamp(tr["entry"])), cal.index(pd.Timestamp(tr["exit"]))
        assert e == s + 1 and x == e + 5                              # next open in, open 5 sessions later out
        col = P["names"].index(tr["ticker"])
        assert tr["ret"] == pytest.approx((O[x, col] / O[e, col] - 1) * 100)
        held.setdefault(tr["ticker"], []).append((e, x))
    for spans in held.values():                                       # the same stock is never held twice at once
        spans.sort()
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
    assert max(sum(1 for sp in held.values() for a, b in sp if a <= j < b) for j in range(len(cal))) <= 3


def test_simulation_equity_is_a_portfolio_not_a_sum(mk):
    data, tickers = market(n_days=300)
    P = v.prepare(data, tickers)
    F = v.features(P)
    seg = np.zeros(len(P["cal"]), dtype=bool)
    seg[100] = True
    mask = np.zeros(P["close"].shape, dtype=bool)
    mask[100, [0, 1]] = True
    res = v.simulate(P, F, mask, seg, cost_pct=0.25, capital=1000.0, max_pos=4, hold=5)
    O = P["open"].to_numpy()
    expect = 1000.0 / 2                                               # two slots of 250 used, 500 left in cash
    for c in (0, 1):
        expect += 250 / (O[101, c] * 1.0025) * O[106, c] * (1 - 0.0025)
    assert res["equity"][-1] == pytest.approx(expect)
    assert len(res["trades"]) == 2


def test_simulation_needs_open_prices(mk):
    data, tickers = mk
    for df in data.values():
        df["Open"] = np.nan
    r = small_study(data, tickers)
    assert r["simulation"]["available"] is False and "apertura" in r["simulation"]["reason"]
    assert r["groups"]["C4"]["h"]["21"]["tutto"]["n"] > 0             # the statistics still exist


# ---------------------------------------------------------------- reproducibility, files, the real diary untouched

def test_reproducible(mk):
    data, tickers = mk
    a, b = small_study(data, tickers), small_study(data, tickers)
    for r in (a, b):
        r.pop("createdAt"), r.pop("seconds"), r["summary"].pop("createdAt")
    assert json.dumps(v.finite(a), sort_keys=True) == json.dumps(v.finite(b), sort_keys=True)


def test_original_diary_never_touched(mk, tmp_path):
    data, tickers = mk
    r = small_study(data, tickers)
    assert not os.path.exists(v.DIARY) and not os.path.exists(od.DB)      # the lab never creates the diary
    x = v.invest_check()
    assert x["historicalTest"] is False and x["diary"]["exists"] is False and not os.path.exists(v.DIARY)
    con = od.connect(v.DIARY)                                         # a diary that already exists, with one day
    con.execute("INSERT INTO runs VALUES ('2026-10-30','O2.1','2026-10-30T16:30:00-04:00','test','p','[]',NULL,1,1,NULL,NULL)")
    con.commit()
    con.close()
    before = open(v.DIARY, "rb").read()
    x = v.invest_check()
    assert x["diary"]["sessions"] == 1 and x["firstResults"]["63"] > "2026-10-30"
    path = v.save(r)
    assert open(v.DIARY, "rb").read() == before
    assert os.path.dirname(path) == v.OUT_DIR and v.OUT_DIR != os.path.dirname(v.DIARY)   # separate folder


def test_report_wording_and_limits(mk):
    data, tickers = mk
    r = small_study(data, tickers)
    text = json.dumps(v.finite(r), ensure_ascii=False)
    assert r["label"] == "Studio esplorativo con survivorship bias" and r["summary"]["label"] == r["label"]
    for banned in ("Strategia vincente", "Probabilità di guadagno", "Compra", "validat"):
        assert banned not in text
    for key in ("version", "configHash", "config", "period", "universe", "observations", "limits", "quality", "priceConvention"):
        assert key in r
    assert r["config"]["scannerParams"]["TRADING_MIN"] == o.TRADING_MIN and r["config"]["scannerParams"]["ATR_HIGH"] == o.ATR_HIGH


def test_scanner_unchanged():
    """Phase O3 must not move the scanner: its model version and thresholds stay the ones of phase O2."""
    assert (o.MODEL_VERSION, o.TRADING_MIN, o.INVEST_MIN, o.ATR_HIGH, o.COVERAGE_MIN) == ("O2.1", 4, 5, 4.0, 0.80)


def test_reports_folder_ignored_by_git():
    """Reports, price snapshots and the experiment log go in data/validazione/, which Git ignores (data/)."""
    ignored = open(os.path.join(ROOT, ".gitignore")).read().split()
    source = open(os.path.join(ROOT, "opportunity_validation.py")).read()
    assert "data/" in ignored
    assert 'OUT_DIR = os.path.join(ROOT, "data", "validazione")' in source


def test_dashboard_only_reads_the_summary(mk):
    """The API never computes the study: it reads riepilogo.json, written by save()."""
    import server
    client = server.app.test_client()
    first = client.get("/api/opportunities/validation").get_json()
    assert first["available"] is False and first["recheck"] is None and first["diary"]["started"] is False
    assert {x["id"]: x["state"] for x in first["reliability"]["items"]} == {"C4": "non_validata", "C5": "non_validata",
                                                                            "INV": "non_validata"}
    data, tickers = mk
    v.save(small_study(data, tickers))
    x = client.get("/api/opportunities/validation").get_json()
    assert x["available"] is True and x["label"] == v.LABEL and len(x["rows"]) == 8 and x["limits"]
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    assert "/api/opportunities/validation" in js and 'data-k="lab"' in js
