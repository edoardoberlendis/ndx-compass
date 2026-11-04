"""Phase 5B: valuation and scenarios (investment_valuation.py), its diary (valuation_diary.py), the API, the page and the
currency labels. Only made-up companies and numbers: no Yahoo, no personal data."""
import copy
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime

import pytest

import fundamentals as fu
import investment_diary as invd
import investment_engine as ie
import investment_valuation as iv
import opportunity_diary as od
import opportunity_scanner as o
import valuation_diary as vd
from test_investment_engine import ANALYST, NOW, PEERS, ROOT, TECH, company, run

ET = ie.ET
RATES = {"rf": {"rate": 0.045, "date": "2026-08-19", "symbol": "^TNX", "source": "test"}}
CLOSE = TECH["close"]


def vco(mcap=4000.0, shares=None, **kw):
    """A made-up company with the rows added in phase 5B (diluted shares, depreciation, working capital)."""
    e = company(**kw)
    n = shares if shares is not None else mcap / CLOSE
    for kind in ("FY", "Q"):
        for p in e[kind]:
            r = p["revenue"]
            p.update(dilutedShares=n, da=r * 0.03, wcChange=-r * 0.01, minority=None, preferred=None)
    return e


def vinfo(mcap=4000.0, beta=1.2):
    out = {"marketCap": mcap, "forwardPE": 25.0, "recommendationKey": "buy", "recommendationMean": 2.0,
           "numberOfAnalystOpinions": 20}
    if beta is not None:
        out["beta"] = beta
    return out


def val(companies, infos=None, analysts=None, fx=None, rates=RATES, now=NOW, sectors=None, techs=None, quotes=None):
    infos = infos if infos is not None else {t: vinfo() for t in companies}
    analysts = analysts if analysts is not None else {t: ANALYST for t in companies}
    inv = run(companies, sectors=sectors, infos=infos, analysts=analysts, fx=fx, now=now, techs=techs)
    fund = {"data": companies, "fx": fx or {}, "firstSeen": {}, "rates": rates}
    closes = {x["ticker"]: {"close": x["price"], "date": x["priceDate"]} for x in inv["items"]}
    return inv, iv.analyze_all(inv, fund, infos, analysts, now, quotes=quotes, closes=closes)


def one(res, t):
    return next(x for x in res["items"] if x["ticker"] == t)


VPEERS = {t: vco() for t in "ABCDEF"}
BASE = {"rev0": 100.0, "m0": 0.20, "mT": 0.20, "g1": 0.10, "gT": 0.025, "wacc": 0.09, "rf": 0.045, "tax": 0.20, "s2c": 2.0,
        "roicT": 0.15, "years": 5}
ZERO = {"cash": 0.0, "debt": 0.0}


# ---------------------------------------------------------------- the DCF (pure functions)

def test_free_cash_flow_to_the_firm_is_nopat_minus_reinvestment():
    pr = iv.project(BASE)
    y1 = pr["years"][0]
    assert y1["revenue"] == pytest.approx(110.0) and y1["margin"] == pytest.approx(0.20)
    assert y1["nopat"] == pytest.approx(110 * 0.20 * 0.80)
    assert y1["reinvestment"] == pytest.approx(10 / 2.0)                    # new revenue / sales-to-capital
    assert y1["fcff"] == pytest.approx(17.6 - 5.0)
    assert y1["pv"] == pytest.approx(12.6 / 1.09)
    shrink = iv.project({**BASE, "g1": -0.10, "gT": -0.10})
    assert all(r["reinvestment"] == 0 for r in shrink["years"])             # no capital released when revenue falls


def test_dcf_is_coherent_with_the_perpetuity_formula():
    flat = {**BASE, "g1": 0.0, "gT": 0.0}
    pr = iv.project(flat)
    nopat = 100 * 0.20 * 0.80
    assert pr["ev"] == pytest.approx(nopat / 0.09)                         # no growth, no reinvestment: NOPAT / WACC
    assert pr["ev"] == pytest.approx(pr["pvExplicit"] + pr["pvTerminal"])  # enterprise value = explicit + terminal
    assert pr["tvShare"] == pytest.approx(pr["pvTerminal"] / pr["ev"])
    g = iv.project(BASE)
    assert g["terminalReinvestRate"] == pytest.approx(0.025 / 0.15)        # terminal growth needs reinvestment g / ROIC


def test_equity_value_bridge_and_value_per_share():
    eq, ps = iv.per_share(1000.0, {"cash": 50.0, "debt": 200.0, "minority": 10.0, "preferred": 40.0}, 8.0)
    assert eq == pytest.approx(800.0) and ps == pytest.approx(100.0)


def test_flows_to_the_firm_are_discounted_with_the_cost_of_capital_of_the_firm():
    _, res = val({"A": vco(debt=1000.0, cash=80.0, interest=15.0)}, infos={"A": vinfo(4000.0)})
    d = one(res, "A")["inputs"]["discount"]
    assert d["wd"] == pytest.approx(1000 / 5000)
    assert d["ke"] == pytest.approx(0.045 + (0.67 * 1.2 + 0.33) * 0.045)
    assert d["kd"] == pytest.approx(60 / 1000)                              # interest of 12 months / debt
    tax = one(res, "A")["inputs"]["tax"]
    assert d["wacc"] == pytest.approx(0.8 * d["ke"] + 0.2 * d["kd"] * (1 - tax))
    assert one(res, "A")["scenarios"]["base"]["assumptions"]["wacc"] == pytest.approx(d["wacc"])
    assert "FCFF" in iv.PARAMS[0][1] and "WACC" in iv.PARAMS[0][1] and "FCFE" not in iv.PARAMS[0][1]


def test_inadmissible_assumptions_are_rejected():
    for bad, words in (({"wacc": 0.04}, "tasso di sconto"), ({"gT": 0.05, "rf": 0.045, "wacc": 0.09}, "tasso privo di rischio"),
                       ({"roicT": 0.02}, "rendimento del capitale"), ({"mT": 1.2}, "margine"), ({"s2c": 0.0}, "ricavi/capitale"),
                       ({"tax": 1.5}, "aliquota")):
        with pytest.raises(iv.Invalid, match=words):
            iv.project({**BASE, **bad})


def test_scenarios_change_the_assumptions_not_just_the_result():
    sc = iv.scenarios(BASE)
    p, b, f = (sc[k] for k in ("prudente", "base", "favorevole"))
    assert p["g1"] < b["g1"] < f["g1"] and p["mT"] < b["mT"] < f["mT"] and p["s2c"] < b["s2c"] < f["s2c"]
    assert p["wacc"] == b["wacc"] == f["wacc"] and p["gT"] == b["gT"] == f["gT"]
    assert p["roicT"] <= b["roicT"] <= f["roicT"]
    vp, vb, vf = (iv.value(sc[k], ZERO, 1.0) for k in ("prudente", "base", "favorevole"))
    assert vp < vb < vf
    assert abs(vp / vb - 0.8) > 0.02 and abs(vf / vb - 1.2) > 0.02         # not a 0.8 / 1.2 multiplier


def test_sensitivity_moves_in_the_economically_right_direction():
    v0, rows = iv.sensitivity(iv.scenarios(BASE)["base"], ZERO, 1.0)
    ch = {r["key"]: [c["change"] for c in r["cells"]] for r in rows}
    assert ch["wacc"][0] > 0 > ch["wacc"][1]                                 # higher discount rate, lower value
    assert ch["mT"][0] < 0 < ch["mT"][1] and ch["g1"][0] < 0 < ch["g1"][1]
    assert ch["gT"][0] < 0 < ch["gT"][1]


def test_reverse_dcf_finds_the_growth_the_price_implies_or_says_it_is_not_unique():
    base = iv.scenarios(BASE)["base"]
    price = iv.value(base, ZERO, 1.0) * 1.5
    r = iv.reverse(base, ZERO, 1.0, price)
    assert r["growth"] > base["g1"]
    assert iv.value({**base, "g1": r["growth"]}, ZERO, 1.0) == pytest.approx(price, rel=1e-4)
    assert r["margin"] > base["mT"]
    bad = {**base, "mT": 0.10, "m0": 0.10, "s2c": 0.5, "roicT": 0.04}       # return on new capital below the WACC
    r2 = iv.reverse(bad, ZERO, 1.0, price)
    assert r2["growth"] is None and "non è univoco" in r2["growthNote"]
    r3 = iv.reverse(base, ZERO, 1.0, 1e9)                                   # out of range: said, not forced
    assert r3["growth"] is None and "oltre il +95%" in r3["growthNote"]


def test_shares_dilution_and_adr_ratio():
    assert iv.shares_check(100.0, 100.0)[:3] == (100.0, 1, None)
    s, adr, prob, note = iv.shares_check(85.0, 100.0)                      # 15% apart: the higher count, said
    assert s == 100.0 and adr == 1 and prob is None and "numero più alto" in note
    s, adr, prob, note = iv.shares_check(400.0, 100.0)                     # 1 ADR = 4 ordinary shares
    assert s == 100.0 and adr == 4 and "4 azioni ordinarie" in note
    assert iv.shares_check(250.0, 100.0)[2] and iv.shares_check(None, 100.0)[2]   # 2.5: not a ratio -> not valued
    _, res = val({"A": vco(shares=4 * 4000 / CLOSE)})
    x = one(res, "A")
    assert x["inputs"]["adr"] == 4 and x["inputs"]["shares"] == pytest.approx(4000 / CLOSE)


def test_stock_based_pay_is_not_counted_twice():
    _, res = val({"A": vco(sbc=0.02), "B": vco(sbc=0.15)})
    a, b = one(res, "A"), one(res, "B")
    assert a["scenarios"]["base"]["perShare"] == pytest.approx(b["scenarios"]["base"]["perShare"])   # GAAP EBIT has it
    assert b["inputs"]["cash"]["fcfEconomic"] < a["inputs"]["cash"]["fcfEconomic"]
    assert b["inputs"]["cash"]["fcfEconomic"] == pytest.approx(b["inputs"]["cash"]["fcf"] - b["inputs"]["cash"]["sbc"])
    assert any("compensi in azioni" in r for r in b["risks"])
    doc = " ".join(iv.__doc__.split())
    assert "does not subtract it again" in doc and "not as a standard accounting figure" in doc


# ---------------------------------------------------------------- one company, real cases

def test_a_healthy_company_gets_three_scenarios_with_its_assumptions():
    inv, res = val(VPEERS)
    x = one(res, "A")
    assert x["status"] in iv.COMPUTED and x["scenarios"] and x["range"]["low"] < x["range"]["base"] < x["range"]["high"]
    assert x["price"]["value"] == CLOSE and x["price"]["kind"] == "chiusura" and x["price"]["date"] == "2026-08-20"
    assert x["fundamental"]["profile"] == next(i for i in inv["items"] if i["ticker"] == "A")["profile"]
    assert x["dataUsed"] and x["monitor"] and isinstance(x["risks"], list) and x["summary"].startswith("Prezzo")
    for k in ("prudente", "base", "favorevole"):
        s = x["scenarios"][k]
        assert set(s["assumptions"]) == {"g1", "gT", "m0", "mT", "tax", "s2c", "wacc", "roicT"}
        assert s["text"]["plausible"] and s["text"]["implausible"]
    assert all(isinstance(v, int) for v in x["range"]["display"] if abs(v) >= 10)   # no false precision
    assert res["model"]["version"] == iv.VERSION and res["model"]["values"] == iv.P


def test_margin_of_safety_and_levels_are_conditions_not_orders():
    _, res = val(VPEERS)
    for x in res["items"]:
        if not x["scenarios"]:
            continue
        vb, p = x["scenarios"]["base"]["perShare"], x["price"]["value"]
        assert x["marginOfSafety"]["base"] == pytest.approx((vb - p) / vb)
        for lv in x["levels"]:
            assert lv["price"] < p and "non un prezzo di acquisto" in lv["text"] and "purché" in lv["text"]
    assert not re.search(r"\b(Compra|Vendi|compra|vendi)\b", json.dumps(res, ensure_ascii=False))


def test_negative_operating_income_is_not_valued():
    _, res = val({"A": vco(opm=-0.05, npm=-0.05)})
    x = one(res, "A")
    assert x["status"] == "non_affidabile" and x["scenarios"] is None and x["group"] == "nessuna_stima"
    assert "utile operativo negativo" in x["reasons"][0] and not x.get("levels")
    assert iv.compact(x)["values"] is None


def test_negative_operating_cash_flow_or_unstable_margins_are_not_valued():
    e = vco()
    for p in e["Q"] + e["FY"]:
        p["ocf"] = -abs(p["revenue"]) * 0.05
    _, res = val({"A": e})
    assert one(res, "A")["status"] == "non_affidabile" and "cassa operativo negativo" in one(res, "A")["reasons"][0]
    e = vco()
    e["FY"][2]["operatingIncome"] = e["FY"][2]["revenue"] * 0.02
    _, res = val({"A": e})
    assert one(res, "A")["status"] == "non_affidabile" and "instabili" in one(res, "A")["reasons"][0]


def test_negative_free_cash_flow_from_heavy_investment_is_flagged():
    e = vco(capex=0.60, fcfm=-0.20)
    _, res = val({"A": e})
    x = one(res, "A")
    assert x["scenarios"] and any("investimenti netti attuali" in b for b in x["blockers"])
    assert x["group"] != "qualita_approfondire"


def test_missing_data_is_never_zero():
    e = vco()
    for p in e["Q"] + e["FY"]:
        p["totalDebt"] = None
    _, res = val({"A": e})
    assert one(res, "A")["status"] == "dati_insufficienti" and "debito" in one(res, "A")["reasons"][0]
    _, res = val({"A": vco()}, rates={})
    assert one(res, "A")["status"] == "dati_insufficienti" and "Treasury" in one(res, "A")["reasons"][0]
    _, res = val({"A": vco()}, infos={"A": vinfo(beta=None)})
    x = one(res, "A")
    assert x["inputs"]["discount"]["beta"] == iv.P["betaMissing"] and any("beta non disponibile" in r for r in x["partial"])
    assert x["status"] in ("parziale", "sensibile")


def test_obsolete_or_late_statements_are_not_presented_as_reliable():
    old = vco(quarters=False, fy_ends=["2024-06-30", "2023-06-30", "2022-06-30", "2021-06-30"])
    _, res = val({"A": old})
    assert one(res, "A")["status"] == "dati_insufficienti" and "obsoleti" in one(res, "A")["reasons"][0]
    late = vco(extra_earnings=["2026-08-15T16:05:00-04:00"])                 # results out, not yet in the statements
    _, res = val({"A": late})
    x = one(res, "A")
    assert x["lagging"] == "2026-08-15" and x["status"] in ("parziale", "sensibile")
    assert any("non ancora nei bilanci" in b for b in x["blockers"]) and x["group"] != "qualita_approfondire"


@pytest.mark.parametrize("sector,ysec,yind", [("Finanza", "Financial Services", "Credit Services"),
                                               ("Utility", "Utilities", "Utilities - Regulated Electric")])
def test_financial_and_utility_companies_get_no_industrial_dcf(sector, ysec, yind):
    _, res = val({"A": vco(ysec=ysec, yind=yind)}, sectors={"A": sector})
    x = one(res, "A")
    assert x["status"] == "non_appropriato" and x["scenarios"] is None and not x.get("levels")
    assert x["statusLabel"] == iv.STATUS["non_appropriato"] == "Metodologia non appropriata per la società" and "DCF" in x["reasons"][0]


def test_foreign_accounts_are_converted_with_the_recorded_rate():
    fx = {"CNY": {"rate": 0.14, "date": "2026-08-19", "symbol": "CNYUSD=X"}}
    usd_inv, usd = val({"A": vco()})
    cny_inv, cny = val({"A": vco(cur="CNY")}, fx=fx)
    a, c = one(usd, "A"), one(cny, "A")
    assert c["inputs"]["rev0"] == pytest.approx(a["inputs"]["rev0"] * 0.14)
    assert c["inputs"]["fx"] == {"currency": "CNY", "rate": 0.14, "date": "2026-08-19",
                                 "source": "Yahoo Finance, CNYUSD=X, chiusura giornaliera"}
    assert any("CNY" in b for b in c["blockers"]) and any("cambio del 19 ago 2026" in p for p in c["partial"])
    _, miss = val({"A": vco(cur="EUR")})
    assert one(miss, "A")["status"] == "dati_insufficienti" and "cambio EUR/USD" in one(miss, "A")["reasons"][0]


def test_no_future_information_is_used():
    e = vco()
    _, before = val({"A": e})
    fut = copy.deepcopy(e)
    fut["Q"].insert(0, {**fut["Q"][0], "end": "2026-09-30", "revenue": 1e6, "operatingIncome": 9e5})   # after NOW
    _, after = val({"A": fut})
    assert one(before, "A")["scenarios"]["base"]["perShare"] == one(after, "A")["scenarios"]["base"]["perShare"]


def test_valuations_are_reproducible():
    _, a = val(VPEERS)
    _, b = val(VPEERS)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def test_the_pagella_and_the_5a_analysis_are_only_read():
    pag = {"A": {"ok": 4, "n": 6, "status": "Da approfondire", "rank": None, "conditions": []}}
    inv = run(VPEERS, infos={t: vinfo() for t in VPEERS}, pagella=pag)
    before = json.dumps(inv, sort_keys=True, default=str)
    fund = {"data": VPEERS, "fx": {}, "firstSeen": {}, "rates": RATES}
    iv.analyze_all(inv, fund, {t: vinfo() for t in VPEERS}, {}, NOW)
    assert json.dumps(inv, sort_keys=True, default=str) == before
    assert ie.VERSION == "F1" and [k for k, _ in ie.DIMS] == ["quality", "growth", "solidity", "valuation", "expectations", "trend"]
    assert o.MODEL_VERSION == "O2.1" and [c[0] for c in o.TRADING] == ["T1", "T2", "T3", "T4", "T5"]
    assert (o.TRADING_MIN, o.INVEST_MIN) == (4, 5) and [c[0] for c in o.INVEST] == ["I1", "I2", "I3", "I4", "I5", "I6"]


def test_consensus_is_used_only_when_its_years_match_the_statements():
    e = vco()
    fy0 = e["FY"][0]["revenue"]
    good = {**ANALYST, "rev": {"0y": {"avg": fy0 * 1.2, "yearAgoRevenue": fy0, "numberOfAnalysts": 10},
                               "+1y": {"avg": fy0 * 1.44, "yearAgoRevenue": fy0 * 1.2, "numberOfAnalysts": 10}}}
    _, res = val({"A": e}, analysts={"A": good})
    assert "consenso di 10 analisti" in one(res, "A")["inputs"]["g1Src"]
    broken = copy.deepcopy(good)
    broken["rev"]["+1y"]["yearAgoRevenue"] = fy0 * 1.5                     # the two years of the source do not chain
    _, res = val({"A": e}, analysts={"A": broken})
    assert "ultima crescita" in one(res, "A")["inputs"]["g1Src"]


# ---------------------------------------------------------------- diary (new tables, prospective only)

EVENING = datetime(2026, 10, 30, 18, 30, tzinfo=ET)


def diary_result(day="2026-10-30", quotes=None):
    techs = {t: {**TECH, "date": day} for t in VPEERS}
    return val(VPEERS, techs=techs, now=EVENING, quotes=quotes)


def test_valuation_diary_never_starts_the_diary():
    inv, res = diary_result()
    saved, why = vd.record(res, "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)
    assert not saved and "non ha registrato la seduta" in why and not os.path.exists(od.DB)
    assert vd.stats() == {"started": False, "days": 0} and not vd.exists("2026-10-30", iv.VERSION)


def test_valuation_diary_records_once_and_leaves_the_other_diaries_unchanged():
    from test_opportunities import QQQ, RISING_VOL, TODAY, frame, path, stock
    scan = o.scan([stock("AAA")], {"AAA": frame(path(300, 0.004), RISING_VOL)}, QQQ, {}, today=TODAY, keep_all=True)
    assert od.record(scan, "2026-10-30", EVENING.isoformat(), "test")[0]
    inv, res = diary_result()
    assert invd.record(inv, "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)[0]
    tables = ("runs", "observations", "inv_runs", "inv_observations")
    with sqlite3.connect(od.DB) as con:
        before = {t: con.execute(f"SELECT * FROM {t}").fetchall() for t in tables}
    assert vd.stats() == {"started": False, "days": 0}
    with sqlite3.connect(od.DB) as con:
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='val_runs'").fetchone()   # a read creates nothing
    _, live = diary_result(quotes={t: {"price": 111.0, "time": "2026-10-30T15:00:00-04:00"} for t in VPEERS})
    assert vd.record(live, "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)[0] is False   # only closes
    _, wrong = diary_result(day="2026-10-29")
    assert vd.record(wrong, "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)[0] is False
    early = datetime(2026, 10, 30, 15, 0, tzinfo=ET)
    assert vd.record(res, "2026-10-30", early.isoformat(), "test", o.MODEL_VERSION)[0] is False
    saved, why = vd.record(res, "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)
    assert saved and why == "6 valutazioni salvate"
    assert vd.record(res, "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)[0] is False
    with sqlite3.connect(od.DB) as con:
        assert {t: con.execute(f"SELECT * FROM {t}").fetchall() for t in tables} == before
        row = con.execute("SELECT price, price_date, status, value_base, scenarios, inputs, monitor FROM val_observations "
                          "WHERE ticker='A'").fetchone()
        assert row[0] == CLOSE and row[1] == "2026-10-30" and row[2] in iv.STATUS
        assert json.loads(row[4])["base"]["perShare"] == pytest.approx(row[3])
        assert json.loads(row[5])["discount"]["rfDate"] == "2026-08-19" and json.loads(row[6])
        params = json.loads(con.execute("SELECT params FROM val_runs").fetchone()[0])
        assert params["values"] == iv.P and params["text"]
        for sql in ("UPDATE val_observations SET status='x'", "DELETE FROM val_observations", "DELETE FROM val_runs",
                    "UPDATE val_runs SET source='x'"):
            with pytest.raises(sqlite3.DatabaseError):
                con.execute(sql)
    s = vd.stats()
    assert s["started"] and s["days"] == 1 and s["observations"] == 6 and s["versions"] == [iv.VERSION]


# ---------------------------------------------------------------- statements cache: new rows and the risk-free rate

def test_new_statement_rows_and_rates_do_not_force_old_servers_to_download():
    e = vco()
    assert not fu.needs_refresh({**e, "fields": fu.FIELDS}, datetime(2026, 8, 12, tzinfo=ET))
    assert fu.needs_refresh({**e, "fields": 1}, datetime(2026, 8, 12, tzinfo=ET))     # new code: one new download
    assert {k for k in e if k == "schema"} and e["schema"] == fu.SCHEMA == 1          # the 5A schema is unchanged
    assert "dilutedShares" in fu.ROWS["income"] and {"da", "wcChange"} <= set(fu.ROWS["cash"])
    assert fu.rates_stale({}, NOW) and not fu.rates_stale({"rates": RATES}, NOW)


# ---------------------------------------------------------------- API, currency labels and page

@pytest.fixture
def api(monkeypatch, tmp_path):
    import pandas as pd
    import server
    rows = [{"ticker": t, "name": f"{t} Inc.", "sector": "Tecnologia", "price": 110.0} for t in VPEERS]
    st = server.store
    idx = pd.bdate_range(end="2026-08-20", periods=260)
    df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": [100 + i * 0.1 for i in range(260)], "Volume": 1e6}, index=idx)
    monkeypatch.setattr(st, "snapshot", {"asOf": "2026-08-20T10:00:00-04:00", "stocks": rows})
    monkeypatch.setattr(st, "daily", {**{t: df for t in VPEERS}, "QQQ": df})
    monkeypatch.setattr(st, "analysts", {t: ANALYST for t in VPEERS})
    monkeypatch.setattr(st, "infos", {t: vinfo(4000.0 * 125.9 / 110) for t in VPEERS})
    monkeypatch.setattr(st, "error", None)
    monkeypatch.setattr(server, "opportunities", lambda keep_all=False, now=None: None)
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download when the page asks"))
    server._inv.update(key=None, data=None)
    server._val.update(key=None, data=None)
    yield server
    server._inv.update(key=None, data=None)
    server._val.update(key=None, data=None)


def write_cache(companies, rates=RATES):
    os.makedirs(os.path.dirname(fu.CACHE), exist_ok=True)
    with open(fu.CACHE, "w") as f:
        json.dump({"schema": 1, "savedAt": "2026-08-10T09:00:00-04:00", "data": companies, "fx": {}, "firstSeen": {},
                   "rates": rates}, f)


def test_valuation_api_unavailable_without_statements(api):
    c = api.app.test_client()
    d = json.loads(c.get("/api/valuation").data)
    assert d["available"] is False and d["reason"] and d["diary"] == {"started": False, "days": 0}
    assert c.get("/api/valuation/A").status_code == 503


def test_valuation_api_and_the_existing_investment_api(api):
    write_cache(VPEERS)
    c = api.app.test_client()
    d = json.loads(c.get("/api/valuation").data)
    assert d["available"] and d["model"]["version"] == iv.VERSION and len(d["items"]) == 6
    row = d["items"][0]
    assert {"status", "statusLabel", "group", "fundamental", "price", "values", "display", "summary"} <= set(row)
    assert "scenarios" not in row and row["price"]["kind"] == "quotazione"          # the page: current quote and time
    full = json.loads(c.get("/api/valuation/a").data)
    assert full["ticker"] == "A" and full["modelVersion"] == iv.VERSION and full["params"]
    assert c.get("/api/valuation/ZZZ").status_code == 404
    inv = json.loads(c.get("/api/investment").data)                                 # phase 5A API unchanged
    assert inv["available"] and inv["model"]["version"] == ie.VERSION
    assert set(inv["items"][0]) == {"ticker", "name", "sector", "industry", "model", "price", "priceDate", "balance", "profile",
                                    "view", "mainStrength", "mainWeakness", "completeness", "dataIssues", "lagging", "order",
                                    "currency", "dims", "pagella"}
    assert not os.path.exists(od.DB)


def test_accounts_currency_for_the_old_valuation_card(api):
    write_cache({"A": vco(cur="CNY"), "B": vco()})
    assert api.accounts_currency("A") == "CNY" and api.accounts_currency("B") == "USD"
    assert api.accounts_currency("ZZZ") is None


def test_page_has_the_valuation_section_and_currency_labels():
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    for needle in ("function valCardHTML", "function valDetailHTML", "/api/valuation", "Valutazione e scenari", "data-vfil",
                   "function accMoney", "accountsCurrency", "Non è un prezzo obiettivo"):
        assert needle in js
    assert '"$" + fBig(i.freeCashflow)' not in js and '"$" + fBig(i.totalRevenue)' not in js
    assert '"$" + fBig(o.avg)' not in js
    block = re.search(r"Valutazione e scenari \(phase 5B[\s\S]+?function renderOpps", js).group(0)
    assert not re.search(r"\b(Compra|Vendi)\b", block) and "probabilità" in block
    node = subprocess.run(["node", "--check", os.path.join(ROOT, "static", "app.js")], capture_output=True, text=True)
    if node.returncode == 127:
        pytest.skip("node non installato")
    assert node.returncode == 0, node.stderr
    server_src = open(os.path.join(ROOT, "server.py")).read()
    assert re.search(r'DASHBOARD_VERSION = "([^"]+)"', server_src).group(1) == re.search(r'PAGE_VERSION = "([^"]+)"', js).group(1)
