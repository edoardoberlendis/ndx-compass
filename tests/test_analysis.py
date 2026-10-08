"""Phase 22 calculations: trends, normal 5-day swing, levels, the 'since' date of the diary and the Analisi box."""
import math

import numpy as np
import pandas as pd

import decision
import diary
import technical


def closes(values):
    return pd.Series(values, index=pd.bdate_range("2026-01-01", periods=len(values)), dtype=float)


def test_trend_arrows_and_thresholds():
    c = closes([100.0] * 60 + [100.0, 100, 100, 101.5])          # +1.5% in a week, +1.5% in a month, +1.5% in 3 months
    t = {x["days"]: x for x in technical.trends(c)}
    assert t[5]["arrow"] == "▲"                                    # beyond +1%
    assert t[21]["arrow"] == "="                                   # within ±2%
    assert t[63]["arrow"] == "="                                   # within ±4%
    c = closes([100.0] * 60 + [110, 109, 108, 106])
    t = {x["days"]: x for x in technical.trends(c)}
    assert t[5]["arrow"] == "▲" and t[21]["arrow"] == "▲" and t[63]["arrow"] == "▲"
    c = closes(list(np.linspace(120, 100, 64)))
    assert all(x["arrow"] == "▼" for x in technical.trends(c))


def test_normal_swing_is_sd_times_root_5():
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.02, 70)
    c = closes(100 * np.cumprod(1 + r))
    b = technical.band(c, 100.0)
    sd = c.pct_change().dropna().iloc[-63:].std()
    assert abs(b["sd"] - sd * math.sqrt(5) * 100) < 1e-9
    assert abs(b["p68"][0] - 100 * (1 - sd * math.sqrt(5))) < 1e-9
    assert abs(b["p90"][1] - 100 * (1 + 1.645 * sd * math.sqrt(5))) < 1e-9


def test_zones_merge_close_levels_and_pick_two_each_side():
    lv = [{"v": 351.37, "name": "massimo del 24 ago"}, {"v": 350.85, "name": "minimo del 9 lug"}, {"v": 345.54, "name": "media 50"},
          {"v": 339.25, "name": "media 200"}, {"v": 364.17, "name": "massimo del 22 set"}, {"v": 375.03, "name": "massimo del 16 lug"},
          {"v": 408.10, "name": "massimo a 52 settimane"}]
    z = technical.zones(lv, 352.07)
    assert [x["names"] for x in z["above"]] == [["massimo del 22 set"], ["massimo del 16 lug"]]
    assert z["below"][0]["names"] == ["minimo del 9 lug", "massimo del 24 ago"] and z["below"][1]["names"] == ["media 50"]


def test_pivots_classic_formula():
    p = technical.pivots(110, 90, 100)
    assert p["P"] == 100 and p["R1"] == 110 and p["S1"] == 90 and p["R2"] == 120 and p["S2"] == 80


def test_since_runs_back_over_the_same_verdict():
    hist = [("2026-10-07", "Entra ora", 350), ("2026-10-06", "Entra ora", 345), ("2026-10-05", "Attendi", 340), ("2026-10-02", "Entra ora", 330)]
    s = diary.since("Entra ora", 352, "2026-10-08", hist, "2026-10-02")
    assert s["date"] == "2026-10-06" and s["price"] == 345 and not s["today"] and not s["atLeast"]
    s = diary.since("Attendi", 352, "2026-10-08", hist, "2026-10-02")
    assert s["today"] and s["date"] == "2026-10-08" and s["price"] == 352
    s = diary.since("Entra ora", 352, "2026-10-08", hist[:2], "2026-10-06")
    assert s["date"] == "2026-10-06" and s["atLeast"]                  # the run reaches the first day of the diary


def test_analysis_box_on_made_up_prices():
    rng = np.random.default_rng(3)
    c = 100 * np.cumprod(1 + rng.normal(0.001, 0.015, 300))
    idx = pd.bdate_range("2025-08-01", periods=300)
    df = pd.DataFrame({"Close": c, "High": c * 1.01, "Low": c * 0.99, "Volume": 1e6}, index=idx)
    ta = technical.levels(df)
    price = float(c[-1])
    row = {"price": price, "vsSma20": 1.0, "vsSma50": 2.0, "vsSma200": 5.0, "vsSma40": 1.0, "vsSma60": 1.0, "rsi": 55.0,
           "sma20": price / 1.01, "sma200": price / 1.05, "weight": 1.0, "sector": "Tecnologia", "earningsTs": None}
    info = {"revenueGrowth": 0.2, "earningsGrowth": 0.2, "profitMargins": 0.2, "freeCashflow": 20, "totalRevenue": 100, "totalDebt": 1, "totalCash": 5}
    d = decision.decide("TEST", row, info, {"label": "In linea"}, {"epsRev30": 0.0, "up30": 0, "down30": 0}, {**ta, "patterns": [], "groups": []},
                        None, [], None, 1.10, capital=10000,
                        extra={"recTrend": {"strongBuy": 13, "buy": 43, "hold": 5, "sell": 0, "strongSell": 0}, "target": price * 1.2, "targetN": 50,
                               "reports": [{"ts": "2026-07-22T16:00:00-04:00", "eps": 2.9, "reported": 9.11, "surprise": 214.2}]})
    A = d["analysis"]
    assert abs(A["consensus"]["mean"] - 114 / 61) < 1e-9 and A["consensus"]["surpriseHigh"]
    assert A["comment"]["text"].startswith("Tendenza ") and A["comment"]["end"].startswith("Commento generato da regole fisse")
    assert A["comment"]["owner"].startswith("Per chi possiede il titolo: ") and A["comment"]["notOwner"].startswith("Per chi non lo possiede: ")
    assert {o["kind"] for o in A["orders"]} >= {"now"} and all(o["qty"] is not None for o in A["orders"])
    now = next(o for o in A["orders"] if o["kind"] == "now")
    assert now["expiryNote"] == "giornaliero" and now["noSpreadQty"] >= now["qty"]
