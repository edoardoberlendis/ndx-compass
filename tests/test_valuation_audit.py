"""Phase 5C: audit of the valuation engine (model V2) against hand-computed financial cases, an independent DCF written
here from the textbook formulas, the frozen V1 model and the diary. Only made-up companies and numbers: no Yahoo, no
personal data, no network."""
import copy
import json
import os
import random
import re
import sqlite3
from datetime import datetime

import pytest

import investment_diary as invd
import investment_engine as ie
import investment_valuation as iv
import investment_valuation_v1 as v1
import opportunity_diary as od
import opportunity_scanner as o
import valuation_diary as vd
from test_investment_engine import NOW, ROOT, TECH
from test_valuation import BASE, CLOSE, EVENING, RATES, VPEERS, ZERO, api, one, val, vco, vinfo, write_cache  # noqa: F401

ET = ie.ET


def textbook_ev(rev0, m0, mT, g1, gT, wacc, tax, s2c, roicT, n=5, stub=0.0):
    """Independent DCF (not the production code): FCFF_t = EBIT_t (1 - t) - (Rev_t - Rev_t-1) / (sales/capital),
    growth fading linearly from g1 to gT, margin moving linearly from m0 to mT; Gordon terminal value on the year n+1
    flow with reinvestment rate gT / ROIC; every flow discounted (t - stub) years."""
    rev, pv = rev0, 0.0
    for t in range(1, n + 1):
        g = g1 + (gT - g1) * (t - 1) / n
        new = rev * (1 + g)
        ebit = new * (m0 + (mT - m0) * t / n)
        fcff = ebit * (1 - tax) - max(new - rev, 0) / s2c
        pv += fcff / (1 + wacc) ** (t - stub)
        rev = new
    fcff_next = rev * (1 + gT) * mT * (1 - tax) * (1 - gT / roicT)
    return pv + fcff_next / (wacc - gT) / (1 + wacc) ** (n - stub)


# ---------------------------------------------------------------- formulas (B1, C)

def test_dcf_matches_an_independent_textbook_implementation():
    rnd = random.Random(5)
    for _ in range(200):
        a = {"rev0": rnd.uniform(10, 1e5), "m0": rnd.uniform(0.02, 0.6), "mT": rnd.uniform(0.02, 0.6),
             "g1": rnd.uniform(-0.15, 0.5), "gT": 0.025, "wacc": rnd.uniform(0.06, 0.14), "rf": 0.045,
             "tax": rnd.uniform(0.1, 0.3), "s2c": rnd.uniform(0.5, 6), "years": 5, "stub": rnd.uniform(0, 1)}
        a["roicT"] = rnd.uniform(a["wacc"], 0.4)
        ref = textbook_ev(a["rev0"], a["m0"], a["mT"], a["g1"], a["gT"], a["wacc"], a["tax"], a["s2c"], a["roicT"],
                          stub=a["stub"])
        assert iv.project(a)["ev"] == pytest.approx(ref, rel=1e-12)


def test_hand_computed_one_year_case():
    # revenue 100 -> 110, margin 20%, tax 25%, sales-to-capital 2, WACC 10%, terminal growth 2%, terminal ROIC 10%
    a = {**BASE, "years": 1, "g1": 0.10, "gT": 0.02, "m0": 0.2, "mT": 0.2, "tax": 0.25, "s2c": 2.0, "wacc": 0.10,
         "roicT": 0.10}
    pr = iv.project(a)
    fcff1 = 110 * 0.2 * 0.75 - 10 / 2                       # 16.5 - 5 = 11.5
    tv = 110 * 1.02 * 0.2 * 0.75 * (1 - 0.02 / 0.10) / (0.10 - 0.02)   # 16.83 x 0.8 / 0.08 = 168.3
    assert pr["years"][0]["fcff"] == pytest.approx(11.5)
    assert pr["terminal"] == pytest.approx(tv) and tv == pytest.approx(168.3)
    assert pr["ev"] == pytest.approx((11.5 + 168.3) / 1.10)


def test_growth_at_a_return_equal_to_the_cost_of_capital_creates_no_value():
    """Textbook result: with ROIC = WACC in the terminal years, the terminal value is NOPAT(n+1) / WACC whatever the
    growth (growth needs exactly the reinvestment that its return pays back)."""
    a = {**BASE, "roicT": 0.09, "wacc": 0.09}
    lo, hi = iv.project({**a, "gT": 0.01}), iv.project({**a, "gT": 0.03})
    nopat6 = lambda p, g: p["revEnd"] * (1 + g) * a["mT"] * (1 - a["tax"])
    assert lo["terminal"] == pytest.approx(nopat6(lo, 0.01) / 0.09)
    assert hi["terminal"] == pytest.approx(nopat6(hi, 0.03) / 0.09)
    g = iv.project(BASE)
    assert g["terminalReinvestRate"] * BASE["roicT"] == pytest.approx(BASE["gT"])   # g = reinvestment rate x ROIC


def test_flows_are_discounted_from_the_end_of_the_base_period_to_today():
    a = dict(BASE)
    for s in (0.0, 0.25, 0.84):
        assert iv.project({**a, "stub": s})["ev"] == pytest.approx(iv.project(a)["ev"] * (1 + a["wacc"]) ** s)
    assert iv.project({**a, "stub": 3.0})["ev"] == pytest.approx(iv.project({**a, "stub": iv.P["stubMax"]})["ev"])
    assert iv.project({**a, "stub": -1.0})["ev"] == pytest.approx(iv.project(a)["ev"])
    _, res = val({"A": vco()})
    t = one(res, "A")["inputs"]["timing"]
    assert t["baseEnd"] == "2026-06-30" and t["valuationDate"] == "2026-08-20"
    assert t["stub"] == pytest.approx(51 / 365.25)
    assert one(res, "A")["scenarios"]["base"]["assumptions"] and "anno 1" in t["text"]


def test_historical_free_cash_flow_to_the_firm_two_ways_and_stock_based_pay():
    e = vco()
    R = sum(q["revenue"] for q in e["Q"][:4])
    _, res = val({"A": e})
    h = one(res, "A")["inputs"]["fcffHist"]
    # EBIT (1 - t) + D&A - capex - increase of working capital = R (0.30 x 0.8 + 0.03 - 0.05 - 0.01)
    assert h["fromEbit"] == pytest.approx(R * 0.21)
    # operating cash flow - capex + after-tax interest - stock-based pay = R (0.30 - 0.05 - 0.02) + 4 x 1 x 0.8
    assert h["fromOcf"] == pytest.approx(R * 0.23 + 3.2)
    more_sbc = vco()
    for p in more_sbc["Q"] + more_sbc["FY"]:
        p["sbc"] = p["revenue"] * 0.10
    _, res2 = val({"A": more_sbc})
    b1, b2 = (one(r, "A")["scenarios"]["base"]["perShare"] for r in (res, res2))
    assert b1 == pytest.approx(b2)                         # the operating income already has it as a cost
    assert one(res2, "A")["inputs"]["fcffHist"]["fromOcf"] == pytest.approx(h["fromOcf"] - R * 0.08)


def test_taxes_reduce_the_operating_profit_and_out_of_range_rates_are_disclosed():
    a = dict(BASE)
    assert iv.project({**a, "tax": 0.3})["years"][0]["nopat"] == pytest.approx(iv.project({**a, "tax": 0.0})["years"][0]["nopat"] * 0.7)
    e = vco()
    for p in e["FY"]:
        p["taxProvision"] = p["pretaxIncome"] * 0.05
    _, res = val({"A": e})
    x = one(res, "A")
    assert x["inputs"]["tax"] == iv.P["taxDefault"]
    c = next(c for c in x["limits"]["clamps"] if c["key"] == "tax")
    assert c["change"] > 0 and "5%" in c["text"]           # a 5% tax rate would give a higher value
    assert any("aliquota fiscale effettiva" in r for r in x["reasons"]) and x["status"] != "adeguata"


# ---------------------------------------------------------------- cost of capital (B2, B3)

def test_wacc_hand_computed():
    # E = 4,000, D = 1,000: weights 80/20; Ke = 4.5% + 1.2 x 4.5% (raw beta chosen so the adjusted beta is 1.2);
    # Kd = 4 x 15 / 1,000 = 6%; tax 20% -> WACC = 0.8 x 9.9% + 0.2 x 6% x 0.8 = 8.88%
    raw = (1.2 - 0.33) / 0.67
    _, res = val({"A": vco(debt=1000.0, cash=80.0, interest=15.0)}, infos={"A": vinfo(4000.0, beta=raw)})
    d = one(res, "A")["inputs"]["discount"]
    assert d["beta"] == pytest.approx(1.2) and d["ke"] == pytest.approx(0.099)
    assert d["kd"] == pytest.approx(0.06) and d["wd"] == pytest.approx(0.2)
    assert d["wacc"] == pytest.approx(0.0888)


@pytest.mark.parametrize("interest, kd", [(30.0, 0.045 + 0.05), (0.01, 0.045), (None, 0.045 + 0.015)])
def test_cost_of_debt_bounds_and_default(interest, kd):
    e = vco(debt=100.0, interest=interest or 0.0)
    if interest is None:
        for p in e["Q"] + e["FY"]:
            p["interestExpense"] = None
    _, res = val({"A": e})
    assert one(res, "A")["inputs"]["discount"]["kd"] == pytest.approx(kd)


@pytest.mark.parametrize("raw, used, sign", [(3.5, 2.0, -1), (-0.1, 0.7, 1)])
def test_beta_limits_are_disclosed_with_the_value_without_them(raw, used, sign):
    _, res = val({"A": vco()}, infos={"A": vinfo(beta=raw)})
    x = one(res, "A")
    assert x["inputs"]["discount"]["beta"] == pytest.approx(used)
    c = next(c for c in x["limits"]["clamps"] if c["key"] == "beta")
    assert c["change"] * sign > 0 and "fuori dai limiti" in c["text"]
    assert any("beta di Yahoo" in r for r in x["reasons"]) and x["status"] != "adeguata"
    _, ok = val({"A": vco()}, infos={"A": vinfo(beta=1.1)})
    assert not one(ok, "A")["limits"]["clamps"]


def test_growth_limit_is_disclosed_with_its_effect():
    e = vco()
    fy0 = e["FY"][0]["revenue"]
    an = {"rev": {"0y": {"avg": fy0 * 1.8, "yearAgoRevenue": fy0, "numberOfAnalysts": 10},
                  "+1y": {"avg": fy0 * 3.2, "yearAgoRevenue": fy0 * 1.8, "numberOfAnalysts": 10}}}
    _, res = val({"A": e}, analysts={"A": an})
    x = one(res, "A")
    assert x["inputs"]["g1"] == iv.P["g1Max"] and x["inputs"]["g1Raw"] > iv.P["g1Max"]
    c = next(c for c in x["limits"]["clamps"] if c["key"] == "g1")
    assert c["change"] > 0


# ---------------------------------------------------------------- bridge, shares, currency (E)

def test_enterprise_to_equity_value_with_investments_and_leases():
    eq, ps = iv.per_share(1000.0, {"cash": 50.0, "investments": 30.0, "debt": 200.0, "minority": 10.0, "preferred": 40.0}, 8.0)
    assert eq == pytest.approx(830.0) and ps == pytest.approx(103.75)
    e = vco()
    for p in e["Q"] + e["FY"]:
        p["ltInvest"] = 400.0
        p["leases"] = 15.0
    _, with_inv = val({"A": e})
    _, without = val({"A": vco()})
    a, b = one(with_inv, "A"), one(without, "A")
    assert a["scenarios"]["base"]["perShare"] - b["scenarios"]["base"]["perShare"] == pytest.approx(400.0 / a["inputs"]["shares"])
    assert a["inputs"]["bridge"]["investments"] == 400.0 and a["inputs"]["bridge"]["leases"] == 15.0
    assert any(r.startswith("investimenti finanziari a lungo termine pari") for r in a["reasons"])
    assert any("non riportati dalla fonte" in n for n in b["notes"])    # missing stays missing, flagged


def test_large_leases_are_shown_as_a_limit_not_removed_from_the_debt():
    e = vco(debt=1500.0)
    for p in e["Q"] + e["FY"]:
        p["leases"] = 1400.0
    _, res = val({"A": e})
    x = one(res, "A")
    assert x["inputs"]["bridge"]["debt"] == 1500.0                   # prudent: still in the debt
    assert any(r.startswith("leasing pari al") for r in x["reasons"])


def test_adr_ratio_and_dilution():
    assert iv.shares_check(400.0, 100.0)[:2] == (100.0, 4)            # 1 quoted share = 4 ordinary shares
    sh, adr, prob, note = iv.shares_check(120.0, 100.0)
    assert sh == 120.0 and adr == 1 and not prob and "più alto" in note
    assert iv.shares_check(250.0, 100.0)[2]                           # 2.5: not an integer ratio -> incoherent


def test_foreign_accounts_keep_the_currency_and_country_risk_limits():
    _, res = val({"A": vco(cur="CNY")}, fx={"CNY": {"rate": 0.14, "date": "2026-08-19", "symbol": "CNYUSD=X"}})
    x = one(res, "A")
    assert x["inputs"]["rev0"] == pytest.approx(sum(q["revenue"] for q in vco()["Q"][:4]) * 0.14)
    assert any("rischio paese" in b for b in x["blockers"]) and x["group"] in ("incerta", "qualita_impegnativa", "altre")


# ---------------------------------------------------------------- periods (data limits)

def per(end, **kw):
    return {"end": end, "revenue": 100.0, "operatingIncome": 20.0, **kw}


def test_incomplete_newest_quarter_or_year_is_skipped():
    q = [{"end": "2026-09-30", "dilutedEps": 1.0}] + [per(e) for e in ("2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30")]
    fy = [{"end": "2025-12-31", "dilutedEps": 3.0}, per("2024-12-31")]
    Pf, skipped = iv.base_periods({"FY": fy, "Q": q})
    assert [x["end"] for x in Pf["Q"][:1]] == ["2026-06-30"] and Pf["FY"][0]["end"] == "2024-12-31"
    assert set(skipped) == {"2026-09-30", "2025-12-31"}
    hole = [per("2026-09-30"), {"end": "2026-06-30"}] + [per(e) for e in ("2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30")]
    Pf, _ = iv.base_periods({"FY": [per("2025-12-31")], "Q": hole})
    assert Pf["Q"][0]["end"] == "2026-03-31"                          # newest 4 complete consecutive quarters
    old = [per(e) for e in ("2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31")]
    Pf, _ = iv.base_periods({"FY": [per("2025-12-31")], "Q": old})
    assert Pf["Q"] == []                                              # the annual report is newer


def test_balance_sheet_at_the_date_of_the_flows_and_never_an_old_figure():
    P = {"Q": [{"end": "2026-09-30", "cash": 9.0}, {"end": "2026-06-30", "cash": 5.0, "totalDebt": 1.0}],
         "FY": [{"end": "2021-12-31", "totalDebt": 87.0}]}
    assert iv.balance(P, "cash", "2026-06-30", None, None)[0] == 5.0
    assert iv.balance(P, "totalDebt", "2026-09-30", None, None)[0] == 1.0     # 92 days before: accepted
    assert iv.balance({**P, "Q": P["Q"][:1]}, "totalDebt", "2026-09-30", None, None) == (None, None)


def test_debt_missing_from_the_source_stays_missing_even_if_an_old_report_has_it():
    e = vco()
    for p in e["Q"] + e["FY"][:-1]:
        p["totalDebt"] = None
    _, res = val({"A": e})
    assert one(res, "A")["status"] == "dati_insufficienti"


def test_old_base_data_is_not_presented_as_adequate():
    old = ["2025-03-31", "2024-03-31", "2023-03-31", "2022-03-31"]
    _, res = val({"A": vco(quarters=False, fy_ends=old)})
    x = one(res, "A")
    assert x["status"] != "adeguata"
    if x["scenarios"]:
        assert x["inputs"]["timing"]["stub"] == iv.P["stubMax"]


# ---------------------------------------------------------------- sensitivity and reverse DCF (F)

def test_sensitivity_recomputes_the_terminal_return_with_the_discount_rate():
    base = iv.scenarios(BASE)["base"]
    _, rows = iv.sensitivity(base, ZERO, 1.0)
    cell = next(r for r in rows if r["key"] == "wacc")["cells"][1]
    a = {**base, "wacc": base["wacc"] + 0.01}
    a["roicT"] = iv.terminal_roic("base", a["mT"], a["tax"], a["s2c"], a["wacc"], a["gT"])
    assert cell["value"] == pytest.approx(iv.value(a, ZERO, 1.0))
    assert a["roicT"] != base["roicT"]


def test_reverse_dcf_gives_several_combinations_that_all_reproduce_the_price():
    base = iv.scenarios(BASE)["base"]
    price = iv.value(base, ZERO, 1.0) * 1.3
    rv = iv.reverse(base, ZERO, 1.0, price)
    assert len(rv["combinations"]) >= 3 and "esempi" in rv["identification"]
    assert iv.value({**base, "g1": rv["growth"]}, ZERO, 1.0) == pytest.approx(price, rel=1e-6)
    w = {**base, "wacc": rv["wacc"]}
    w["roicT"] = iv.terminal_roic("base", w["mT"], w["tax"], w["s2c"], w["wacc"], w["gT"])
    assert iv.value(w, ZERO, 1.0) == pytest.approx(price, rel=1e-6) and rv["wacc"] < base["wacc"]
    m = {**base, "mT": rv["margin"]}
    m["roicT"] = iv.terminal_roic("base", m["mT"], m["tax"], m["s2c"], m["wacc"], m["gT"])
    assert iv.value(m, ZERO, 1.0) == pytest.approx(price, rel=1e-6)
    far = iv.reverse(base, ZERO, 1.0, price * 100)
    assert far["wacc"] is None and "sotto il" in far["waccNote"]


def test_ten_year_horizon_is_shown_but_never_used():
    _, res = val({"A": vco()})
    x = one(res, "A")
    h = x["limits"]["horizon"]
    assert h["years"] == 10 and "non usata" in h["text"]
    assert x["range"]["base"] == x["scenarios"]["base"]["perShare"] != h["value"]


# ---------------------------------------------------------------- versions and reproducibility (G)

def test_v1_is_frozen_and_v2_changes_no_economic_parameter():
    assert v1.VERSION == "V1" and iv.VERSION == "V2" and iv.PREVIOUS == "V1"
    assert all(iv.P[k] == v for k, v in v1.P.items())                # thresholds and assumptions unchanged
    assert set(iv.P) - set(v1.P) == {"stubMax", "bridgeFlag", "altYears"}
    assert set(iv.STATUS) == set(v1.STATUS)                           # same ids: API and diary compatible


def test_v2_equals_v1_when_the_corrections_do_not_apply(monkeypatch):
    """No time between the base period and today, no long-term investment, complete periods: same values."""
    monkeypatch.setitem(iv.P, "stubMax", 0.0)
    inv, r2 = val(VPEERS)
    fund = {"data": VPEERS, "fx": {}, "firstSeen": {}, "rates": RATES}
    closes = {x["ticker"]: {"close": x["price"], "date": x["priceDate"]} for x in inv["items"]}
    infos = {t: vinfo() for t in VPEERS}
    from test_investment_engine import ANALYST
    r1 = v1.analyze_all(inv, fund, infos, {t: ANALYST for t in VPEERS}, NOW, closes=closes)
    for t in VPEERS:
        a, b = one(r1, t), one(r2, t)
        for k in ("prudente", "base", "favorevole"):
            assert a["scenarios"][k]["perShare"] == pytest.approx(b["scenarios"][k]["perShare"], rel=1e-12)


def test_valuations_are_reproducible_and_carry_the_disclaimer():
    _, r1 = val(VPEERS)
    _, r2 = val(VPEERS)
    assert json.dumps(r1, sort_keys=True, default=str) == json.dumps(r2, sort_keys=True, default=str)
    assert r1["model"]["version"] == "V2" and r1["model"]["corrections"] and "non un prezzo futuro" in r1["model"]["disclaimer"]
    assert all(x["disclaimer"] == iv.DISCLAIMER for x in r1["items"])
    assert "capacità predittiva" in iv.DISCLAIMER and "non è ancora dimostrata" in iv.DISCLAIMER


def test_status_labels_separate_the_kinds_of_reliability():
    S = iv.STATUS
    assert S["adeguata"].startswith("Calcolo verificato") and S["parziale"].startswith("Calcolo verificato")
    assert "sensibile" in S["sensibile"] and "obsoleti o insufficienti" in S["dati_insufficienti"]
    assert "non appropriata" in S["non_appropriato"] and "sospesa per anomalie" in S["non_affidabile"]
    assert not any(re.search(r"\b(Compra|Vendi|validat)", v) for v in S.values())


# ---------------------------------------------------------------- diary (I) and API (compatibility)

def test_recorded_valuations_stay_unchanged_and_versions_are_kept_apart():
    from test_opportunities import QQQ, RISING_VOL, TODAY, frame, path, stock
    scan = o.scan([stock("AAA")], {"AAA": frame(path(300, 0.004), RISING_VOL)}, QQQ, {}, today=TODAY, keep_all=True)
    assert od.record(scan, "2026-10-30", EVENING.isoformat(), "test")[0]
    techs = {t: {**TECH, "date": "2026-10-30"} for t in VPEERS}
    inv, r2 = val(VPEERS, techs=techs, now=EVENING)
    assert invd.record(inv, "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)[0]
    fund = {"data": VPEERS, "fx": {}, "firstSeen": {}, "rates": RATES}
    closes = {x["ticker"]: {"close": x["price"], "date": x["priceDate"]} for x in inv["items"]}
    from test_investment_engine import ANALYST
    r1 = v1.analyze_all(inv, fund, {t: vinfo() for t in VPEERS}, {t: ANALYST for t in VPEERS}, EVENING, closes=closes)
    assert vd.record(r1, "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)[0]
    with sqlite3.connect(od.DB) as con:
        before = con.execute("SELECT * FROM val_observations WHERE model_version='V1' ORDER BY ticker").fetchall()
    assert vd.record(r2, "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)[0]
    assert vd.record(r2, "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)[0] is False   # idempotent
    with sqlite3.connect(od.DB) as con:
        assert con.execute("SELECT * FROM val_observations WHERE model_version='V1' ORDER BY ticker").fetchall() == before
        row = con.execute("SELECT inputs FROM val_observations WHERE model_version='V2' AND ticker='A'").fetchone()
        assert json.loads(row[0])["timing"]["baseEnd"] and "fcffHist" in json.loads(row[0])
        with pytest.raises(sqlite3.DatabaseError):
            con.execute("UPDATE val_observations SET value_base=1 WHERE model_version='V1'")
    assert vd.stats()["versions"] == ["V1", "V2"]


def test_api_stays_compatible_and_shows_the_audit(api):
    write_cache(VPEERS)
    c = api.app.test_client()
    d = json.loads(c.get("/api/valuation").data)
    assert d["model"]["version"] == "V2" and d["model"]["previous"] == "V1" and d["model"]["disclaimer"]
    assert {"ticker", "name", "status", "statusLabel", "group", "fundamental", "price", "position", "values", "display", "summary",
            "impliedGrowth", "baseGrowth", "tvShare", "reason", "lagging"} == set(d["items"][0])
    full = json.loads(c.get("/api/valuation/A").data)
    assert {"limits", "disclaimer", "scenarios", "sensitivity", "reverse", "inputs"} <= set(full)
    assert {"timing", "fcffHist"} <= set(full["inputs"]) and "combinations" in full["reverse"]
    assert not os.path.exists(od.DB)


def test_page_shows_the_disclaimer_and_the_separate_picture():
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    block = re.search(r"function valDetailHTML[\s\S]+?function renderOpps", js).group(0)
    for needle in ("X.disclaimer", "Capacità predittiva", "Qualità fondamentale", "Affidabilità di dati e metodo",
                   "Combinazioni che danno lo stesso prezzo", "Limite attivo", "fcffHist", "X.limits?.horizon"):
        assert needle in block
    assert not re.search(r"\b(Compra|Vendi)\b", block)
    assert "V.model.disclaimer" in js and "V.model.corrections" in js
