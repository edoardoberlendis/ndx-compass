"""ETF tab (phase 24): pure calculations of etf.py with made-up prices and a made-up portfolio."""
import numpy as np
import pandas as pd

import etf


def days(n, end=None):
    end = end or pd.Timestamp.now().normalize()
    return pd.bdate_range(end=end, periods=n)


def series(values, end=None):
    return pd.Series(values, index=days(len(values), end), dtype=float)


LABELS = ("Borsa Italiana", "Xetra", "ETF americano in euro")


def test_pick_history_prefers_milan_then_xetra_then_us_proxy():
    full = series(np.linspace(100, 120, 400))
    holes = full.copy()
    holes.iloc[-100:-60] = np.nan                       # 40 missing sessions in the last year
    proxy = series(np.linspace(50, 60, 600))
    assert pick_label(full, full, proxy) == "Borsa Italiana"
    assert pick_label(holes, full, proxy) == "Xetra"
    assert pick_label(holes, holes, proxy) == "ETF americano in euro"
    assert pick_label(holes, None, None) == "Borsa Italiana (storico incompleto)"
    assert etf.pick_history(None, None, None, LABELS) == (None, None)


def pick_label(mi, de, proxy):
    return etf.pick_history(mi, de, proxy, LABELS)[1]


def test_old_series_is_not_complete():
    old = series(np.linspace(100, 120, 400), end=pd.Timestamp.now().normalize() - pd.Timedelta(days=30))
    assert not etf.complete(old)


def test_to_eur_uses_the_rate_of_the_same_day():
    usd = series([110.0, 120.0, 130.0])
    eurusd = pd.Series([1.10, 1.20, 1.30], index=usd.index)
    assert [round(x, 9) for x in etf.to_eur(usd, eurusd)] == [100.0, 100.0, 100.0]


def test_fx_effect_dollar_stronger_is_a_gain_in_euro():
    eurusd = series([1.20] + [1.15] * 20 + [1.00])      # EUR/USD from 1.20 to 1.00: the dollar strengthened
    assert round(etf.fx_effect(eurusd, 21), 6) == 20.0
    assert etf.fx_effect(eurusd, 50) is None


def test_returns_momentum_and_drawdown():
    s = series(np.linspace(100, 200, 300))
    assert round(etf.ret(s, 299), 6) == 100.0
    assert etf.ret(s, 300) is None
    assert etf.momentum_12_1(s) == float(s.iloc[-22] / s.iloc[-253] - 1) * 100
    assert etf.max_drawdown(series([100] * 10 + [50] * 10 + [100] * 10)) == -50.0


def test_late_risk_percentile_levels():
    rng = np.random.default_rng(1)
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 1500)))
    calm = series(base)
    hot = series(np.concatenate([base, base[-1] * np.linspace(1, 1.4, 60)]))    # a fast rise at the end
    r = etf.late_risk(hot)
    assert r["level"] == "alto" and r["percentile"] > 90 and r["years"] == 5.0
    assert etf.late_risk(calm)["level"] in ("basso", "medio", "alto")
    falling = series(np.concatenate([base, base[-1] * np.linspace(1, 0.7, 60)]))
    assert etf.late_risk(falling)["level"] == "basso"
    assert etf.late_risk(series(np.ones(100))) is None


def test_terciles_and_months_in_tercile():
    t = etf.terciles({"A": 30, "B": 20, "C": 10, "D": 0, "E": -10, "F": -20, "G": None})
    assert t["A"] == "forte" and t["F"] == "debole" and "G" not in t
    assert etf.terciles({"A": 1, "B": 2}) == {}
    hist = [{"A": "forte"}, {"A": "forte"}, {"A": "medio"}, {"A": "forte"}]   # newest first
    assert etf.months_in_tercile(hist, "A") == 2
    assert etf.months_in_tercile(hist, "Z") == 0


def test_overlap_takes_the_smaller_weight_and_matches_foreign_listings():
    pts, common = etf.overlap({"NVDA": 0.10, "ASML.AS": 0.05, "XYZ": 0.20}, {"NVDA": 0.04, "ASML": 0.08})
    assert round(pts, 6) == 9.0 and common == ["NVDA", "ASML"]


def conc(tech, usa):
    return {"tecnologia": tech, "USA": usa, "dollaro (stima)": usa}


def test_fit_verdict_rules():
    before = conc(40, 70)
    assert etf.fit_verdict(30, 0.5, before, before)[0] == "si sovrappone"                # overlap >= 25
    assert etf.fit_verdict(5, 0.9, before, before)[0] == "si sovrappone"                 # correlation >= 0.85
    assert etf.fit_verdict(5, 0.5, before, conc(40, 71.5))[0] == "si sovrappone"         # the highest (USA) rises by 1.5
    assert etf.fit_verdict(5, 0.5, before, conc(36, 66))[0] == "diversifica"
    assert etf.fit_verdict(5, 0.7, before, conc(36, 66))[0] == "neutro"                   # correlation not below 0.60
    assert etf.fit_verdict(5, 0.5, before, conc(40.8, 66))[0] == "neutro"                 # tech rises by more than 0.5
    verdict, why = etf.fit_verdict(None, None, before, before)
    assert verdict == "neutro" and "non calcolabile" in why
