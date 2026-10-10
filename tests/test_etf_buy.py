"""ETF tab, part C (verdict, plan, quantity cap, diary) and parts A-B (trend word, mini chart, periods): made-up data."""
from datetime import datetime

import numpy as np
import pandas as pd

import etf
import etf_buy


def row(**kw):
    r = {"isin": "IE0", "category": "Finta", "trend": "Rialzista", "sizeEurM": 500.0, "ter": 0.20,
         "late": {"level": "medio", "percentile": 80.0}, "mom12_1": 12.0, "leverage": 1,
         "planLevels": {"price": 100.0, "date": "2026-10-09", "atr": 2.0, "sma50": 96.0, "low": {"v": 95.0, "date": "2026-09-30"}, "listing": "FINT.MI"}}
    r.update(kw)
    return r


FIT = {"diversifica": {"verdict": "diversifica"}, "neutro": {"verdict": "neutro"}, "sovr": {"verdict": "si sovrappone"}}


def test_trend_word_strict_rule():
    assert etf.trend_word(110, 105, 100) == "Rialzista"
    assert etf.trend_word(102, 105, 100) == "Laterale"        # price below the 50-day average: not Rialzista
    assert etf.trend_word(90, 95, 100) == "Ribassista"
    assert etf.trend_word(97, 95, 100) == "Laterale"
    assert etf.trend_word(100, 95, float("nan")) is None


def test_rules_in_order_and_market_line():
    d = etf_buy.decide(row(), FIT["diversifica"], 10000, 1.0)
    assert d["verdict"] == "Entra ora" and d["market"]["verdict"] == "Entra ora"
    d = etf_buy.decide(row(), FIT["neutro"], 10000, 1.0)
    assert (d["verdict"], d["by"]) == ("Attendi", "A3") and d["market"]["verdict"] == "Entra ora"
    d = etf_buy.decide(row(), FIT["sovr"], 10000, 1.0)
    assert (d["verdict"], d["by"]) == ("Evita", "E3") and d["market"]["verdict"] == "Entra ora"
    assert etf_buy.decide(row(trend="Ribassista"), FIT["diversifica"])["by"] == "E2"
    assert etf_buy.decide(row(sizeEurM=80.0), FIT["diversifica"])["by"] == "E4"
    assert etf_buy.decide(row(trend="Laterale"), FIT["diversifica"])["by"] == "A1"
    assert etf_buy.decide(row(trend=None), FIT["diversifica"])["by"] == "A0"
    assert etf_buy.decide(row(ter=0.65), FIT["diversifica"])["by"] == "A2"
    d = etf_buy.decide(row(late={"level": "alto", "percentile": 95.0}), FIT["diversifica"], 10000, 1.0)
    assert d["verdict"] == "Entra su ritracciamento" and d["plan"]["entry"] == 96.0
    d = etf_buy.decide(row(leverage=3), FIT["diversifica"])
    assert d["verdict"] == "Solo informazione" and d["market"]["verdict"] == "Solo informazione" and "plan" not in d


def test_without_portfolio_only_the_market_line():
    d = etf_buy.decide(row(), None, None, 1.0)
    assert d["verdict"] is None and d["market"]["verdict"] == "Entra ora"
    assert d["planFor"] == "solo mercato" and d["plan"]["qty"] is None


def test_quantity_capped_at_ten_percent_with_the_sentence():
    q = etf_buy.quantity(100.0, 98.0, 10000, 1.0)            # 1% risk would need 50 shares = 50% of the portfolio
    assert q["qty"] == 10 and q["capped"] and round(q["weight"], 6) == 10.0
    assert round(q["wanted"], 6) == 50.0 and round(q["risk"], 6) == 0.2
    assert q["sentence"] == "quantità limitata al 10% del portafoglio: con questo stop l'1% di rischio richiederebbe il 50%; rischio effettivo 0,20% del portafoglio"
    q = etf_buy.quantity(100.0, 80.0, 10000, 1.0)            # wide stop: 5 shares = 5%, no cap
    assert q["qty"] == 5 and not q["capped"]
    assert etf_buy.quantity(100.0, 101.0, 10000, 1.0) is None


def test_plan_uses_euro_and_the_stock_stop_rule():
    p = etf_buy.plan(row(), "now", 10000, 1.0)
    assert p["entry"] == 100.0 and p["def"] in ("sma50", "low", "atr")
    assert all("€" in o["label"] or "ATR" in o["label"] for o in p["opts"]) and not any("$" in o["label"] for o in p["opts"])
    assert p["target"] == p["entry"] + 2 * (p["entry"] - p["stop"])


def test_diary_written_once_and_statistics():
    day1, day2 = "2026-10-01", "2026-10-02"
    rows = [dict(row(isin="A"), category="A"), dict(row(isin="B"), category="B")]
    dec = {"A": etf_buy.decide(rows[0], FIT["diversifica"], 10000, 1.0), "B": etf_buy.decide(rows[1], FIT["neutro"], 10000, 1.0)}
    assert etf_buy.save(day1, [etf_buy.entry(r, dec[r["isin"]]) for r in rows])
    assert not etf_buy.save(day1, [etf_buy.entry(rows[0], dec["A"])])          # never rewritten
    assert len(etf_buy.load(day1)["etfs"]) == 2
    etf_buy.save(day2, [etf_buy.entry(r, dec[r["isin"]]) for r in rows])
    idx = pd.bdate_range("2026-10-01", periods=40)
    closes = {"A": pd.Series(np.linspace(100, 120, 40), index=idx), "B": pd.Series(np.linspace(100, 100, 40), index=idx)}
    st = etf_buy.stats(closes, "verdict")["1 mese"]
    assert st["Entra ora"]["cases"] == 2 and st["Entra ora"]["extra"] > 0 and st["Attendi"]["extra"] < 0
    assert not st["Entra ora"]["enough"]
    assert etf_buy.stats(closes, "market")["1 mese"]["Entra ora"]["cases"] == 4
    assert etf_buy.stats(closes)["3 mesi"] == {}


def test_session_closed_after_six_in_rome():
    rome = etf.ROME
    assert not etf.session_closed("2026-10-09", datetime(2026, 10, 9, 17, 0, tzinfo=rome))
    assert etf.session_closed("2026-10-09", datetime(2026, 10, 9, 18, 5, tzinfo=rome))
    assert etf.session_closed("2026-10-08", datetime(2026, 10, 9, 9, 0, tzinfo=rome))
    assert not etf.session_closed(None, datetime(2026, 10, 9, 20, 0, tzinfo=rome))


def test_spark_and_plan_levels():
    idx = pd.bdate_range("2025-01-01", periods=300)
    s = pd.Series(np.linspace(50, 80, 300), index=idx)
    sp = etf.spark(s)
    assert len(sp["p"]) == 126 and len(sp["ma200"]) == 126 and sp["ma200"][-1] is not None and sp["d"][1] == str(idx[-1].date())
    df = pd.DataFrame({"Close": s, "High": s + 1, "Low": s - 1})
    lv = etf.plan_levels(df)
    assert lv["price"] == 80.0 and round(lv["atr"], 6) == 2.0 and lv["low"]["v"] < 80
    assert etf.plan_levels(df.iloc[:30]) is None


def test_contribution_of_the_first_holdings():
    idx = pd.bdate_range("2026-01-01", periods=30)
    px = {"AAA": pd.Series(np.linspace(100, 150, 30), index=idx), "BBB": pd.Series(np.linspace(100, 100, 30), index=idx),
          "PROXY": pd.Series(np.linspace(100, 110, 30), index=idx)}
    two, share, move = etf.contribution({"AAA": 0.10, "BBB": 0.05}, px, "PROXY", 21)
    assert two[0] == "AAA" and share > 10 and move > 0
    assert etf.contribution({"BBB": 0.05}, px, "PROXY", 21) is None


def test_plan_listing_follows_the_history_and_flags_price_mismatch():
    idx = pd.bdate_range("2026-01-01", periods=80)
    mk = lambda v: pd.DataFrame({"Close": pd.Series(v, index=idx), "High": pd.Series(v, index=idx) + 1, "Low": pd.Series(v, index=idx) - 1})
    data = {"AAA.MI": mk(np.full(80, 54.0)), "AAA.DE": mk(np.full(80, 60.0))}
    j = {"tickerMI": "AAA", "tickerDE": "AAA"}
    assert etf.plan_listing("Xetra (AAA.DE)", j, data)[0] == "AAA.DE"
    assert etf.plan_listing("Borsa Italiana (AAA.MI)", j, data)[0] == "AAA.MI"
    assert etf.plan_listing("ETF americano XYZ", {"tickerMI": None, "tickerDE": "AAA"}, data)[0] == "AAA.DE"
    close = {k: v["Close"] for k, v in data.items()}
    assert round(etf.listing_mismatch(close, j), 1) == -10.0
    assert etf.listing_mismatch({"AAA.MI": close["AAA.MI"], "AAA.DE": close["AAA.MI"] * 1.01}, j) is None


def test_percentile_text_near_thresholds():
    assert etf_buy.pct_text(90.4) == "90,4" and etf_buy.pct_text(79.2) == "79" and etf_buy.pct_text(69.6) == "69,6"
