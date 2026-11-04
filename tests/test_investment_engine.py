"""Phase 5A: fundamental analysis engine (investment_engine.py), statements cache (fundamentals.py), its diary
(investment_diary.py), the API and the page. Only made-up companies and numbers: no Yahoo, no personal data."""
import json
import os
import re
import sqlite3
import subprocess
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

import fundamentals as fu
import investment_diary as invd
import investment_engine as ie
import opportunity_diary as od
import opportunity_scanner as o

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ET = ie.ET
NOW = datetime(2026, 8, 20, 18, 0, tzinfo=ET)
Q_ENDS = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30"]
FY_ENDS = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]


def ann(end, days=30):
    return (date.fromisoformat(end) + timedelta(days=days)).isoformat() + "T16:05:00-04:00"


def company(rev=100.0, g=0.20, opm=0.30, npm=0.25, fcfm=0.25, sbc=0.02, capex=0.05, debt=20.0, cash=80.0, equity=200.0,
            interest=1.0, cur="USD", ysec="Technology", yind="Software - Application", quarters=True, eps=2.0,
            fy_ends=FY_ENDS, q_ends=Q_ENDS, earnings=True, cash_flow=True, extra_earnings=()):
    """A made-up company: quarterly revenue `rev` growing `g` a year, the same margins in every period."""
    def per(end, kind, r):
        oi = r * opm
        p = {"end": end, "kind": kind, "revenue": r, "grossProfit": r * 0.6, "operatingIncome": oi, "ebit": oi,
             "ebitda": oi + r * 0.05, "netIncome": r * npm, "dilutedEps": eps, "pretaxIncome": oi, "taxProvision": oi * 0.2,
             "interestExpense": interest * (4 if kind == "FY" else 1), "ocf": r * (fcfm + capex), "capex": -r * capex,
             "fcf": r * fcfm, "sbc": r * sbc, "totalDebt": debt, "cash": cash, "equity": equity, "totalAssets": 500.0,
             "investedCapital": equity + debt}
        if not cash_flow:
            p.update(ocf=None, capex=None, fcf=None, sbc=None)
        return p
    Q = [per(e, "Q", rev / (1 + g) ** (i / 4)) for i, e in enumerate(q_ends)] if quarters else []
    FY = [per(e, "FY", 4 * rev / (1 + g) ** (k + 0.75)) for k, e in enumerate(fy_ends)]
    E = []
    if earnings:
        ends = sorted(set(q_ends if quarters else fy_ends), reverse=True)
        E = [{"date": ann(e), "past": True} for e in ends] + [{"date": "2026-10-29T16:05:00-04:00", "past": False}]
        E += [{"date": d, "past": True} for d in extra_earnings]
        E.sort(key=lambda x: x["date"], reverse=True)
    return {"schema": fu.SCHEMA, "fields": fu.FIELDS, "fetchedAt": "2026-08-10T09:00:00-04:00", "source": "test",
            "info": {"currency": "USD", "financialCurrency": cur, "sector": ysec, "industry": yind}, "FY": FY, "Q": Q, "earnings": E}


TECH = {"date": "2026-08-20", "close": 110.0, "sma50": 105.0, "sma200": 100.0, "vs200": 10.0, "ret252": 20.0}
TREND = {"+1y": {"current": 1.05, "30daysAgo": 1.02, "90daysAgo": 1.0}}
ANALYST = {"epsTrend": TREND, "revisions": {"+1y": {"upLast30days": 5, "downLast30days": 1}}}


def info(mcap, fpe=25.0):
    return {"marketCap": mcap, "forwardPE": fpe, "recommendationKey": "buy", "recommendationMean": 2.0, "numberOfAnalystOpinions": 20}


def run(companies, sectors=None, infos=None, analysts=None, techs=None, fx=None, seen=None, now=NOW, pagella=None):
    """companies: {ticker: entry}. Everything else defaults to a healthy, covered, rising stock."""
    universe = [{"ticker": t, "name": f"{t} Inc.", "sector": (sectors or {}).get(t, "Tecnologia")} for t in companies]
    infos = infos if infos is not None else {t: info(4000.0) for t in companies}
    analysts = analysts if analysts is not None else {t: ANALYST for t in companies}
    techs = techs if techs is not None else {t: TECH for t in companies}
    fund = {"data": companies, "fx": fx or {}, "firstSeen": seen or {}, "savedAt": "2026-08-10T09:00:00-04:00"}
    return ie.analyze_all(universe, fund, infos, analysts, techs, now, q252=15.0, pagella=pagella,
                          infos_date="2026-08-20", analysts_date="2026-08-20")


def item(res, t):
    return next(x for x in res["items"] if x["ticker"] == t)


def ind(x, key):
    return next(i for i in x["indicators"] if i["key"] == key)


PEERS = {t: company() for t in "ABCDEF"}
PEER_INFOS = {t: info(1000.0 * (i + 1)) for i, t in enumerate("ABCDEF")}      # A the cheapest, F the most expensive


# ---------------------------------------------------------------- statements cache (fundamentals.py)

def test_periods_from_keeps_missing_as_none_and_computes_fcf():
    cols = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31"), pd.Timestamp("2023-12-31")]
    inc = pd.DataFrame({cols[0]: [100.0, 30.0], cols[1]: [90.0, None], cols[2]: [None, None]}, index=["Total Revenue", "Operating Income"])
    cash = pd.DataFrame({cols[0]: [40.0, -10.0], cols[1]: [35.0, None], cols[2]: [None, None]}, index=["Operating Cash Flow", "Capital Expenditure"])
    P = fu.periods_from({"income": inc, "cash": cash, "balance": None}, "FY")
    assert [p["end"] for p in P] == ["2025-12-31", "2024-12-31"]          # the empty column is dropped
    assert P[0]["fcf"] == 30.0 and P[0]["fcfComputed"] is True             # ocf + capex (capex negative)
    assert P[1]["operatingIncome"] is None and P[1]["fcf"] is None          # missing stays missing, never zero
    assert P[0]["totalDebt"] is None


def test_announcement_is_the_first_release_after_the_period_end():
    E = [{"date": "2026-07-30T16:05:00-04:00"}, {"date": "2026-04-29T16:05:00-04:00"}, {"date": "2026-12-01T16:05:00-05:00"}]
    assert fu.announced("2026-06-30", E) == "2026-07-30"                   # not the period end
    assert fu.announced("2026-03-31", E) == "2026-04-29"
    assert fu.announced("2025-06-30", E) is None                           # more than 100 days later: not this period


def test_refresh_rules():
    e = company()
    assert fu.needs_refresh(None, NOW) and fu.needs_refresh({**e, "schema": 0}, NOW)
    assert not fu.needs_refresh(e, datetime(2026, 8, 12, tzinfo=ET))
    assert fu.needs_refresh(e, datetime(2026, 8, 18, tzinfo=ET))           # 7 days after the download
    late = company(extra_earnings=["2026-08-11T16:05:00-04:00"])          # new results after the download
    assert fu.lagging(late, datetime(2026, 8, 14, tzinfo=ET))
    assert fu.needs_refresh(late, datetime(2026, 8, 14, tzinfo=ET))        # 2 days after the announcement


def test_first_seen_marks_the_initial_download():
    first = fu.first_seen({}, {"AAA": company()}, "2026-08-10")
    assert first["AAA"]["Q|2026-06-30"] == {"date": "2026-08-10", "initial": True}
    later = fu.first_seen(first, {"AAA": company(q_ends=["2026-09-30", *Q_ENDS[:7]])}, "2026-11-02")
    assert later["AAA"]["Q|2026-09-30"] == {"date": "2026-11-02", "initial": False}
    assert later["AAA"]["Q|2026-06-30"]["date"] == "2026-08-10"            # an old date is never rewritten


def test_refresh_never_runs_on_read_and_read_tolerates_a_missing_cache():
    assert fu.read() == {"data": {}, "fx": {}, "firstSeen": {}}
    assert not os.path.exists(fu.CACHE)


# ---------------------------------------------------------------- periods: point in time, never the future

def test_ttm_needs_four_consecutive_complete_quarters():
    qs = company()["Q"]
    assert ie.ttm(qs, "revenue") == pytest.approx(sum(q["revenue"] for q in qs[:4]))
    assert ie.ttm([qs[0], qs[1], qs[3], qs[4]], "revenue") is None          # a quarter missing in between
    assert ie.ttm([{**qs[0], "revenue": None}, *qs[1:4]], "revenue") is None  # a missing figure is not zero
    assert ie.ttm(qs[:3], "revenue") is None


def test_periods_after_now_or_announced_later_are_not_used():
    e = company(q_ends=["2026-09-30", *Q_ENDS[:7]])                        # a quarter that ends after NOW
    P = ie.usable(e, NOW)
    assert P["Q"][0]["end"] == "2026-06-30"
    early = datetime(2026, 7, 15, 18, 0, tzinfo=ET)                        # quarter ended, results not yet out
    assert ie.usable(company(), early)["Q"][0]["end"] == "2026-03-31"
    seen = {"Q|2026-06-30": {"date": "2026-09-01", "initial": False}}        # first seen after NOW
    assert ie.usable(company(), NOW, seen)["Q"][0]["end"] == "2026-03-31"


def test_indicator_carries_period_end_and_announcement_date():
    x = item(run({"AAA": company()}), "AAA")
    p = ind(x, "revenue")["period"]
    assert p["type"] == "TTM" and p["end"] == "2026-06-30" and p["announced"] == "2026-07-30"
    assert p["end"] != p["announced"]
    no_cal = item(run({"AAA": company(earnings=False)}), "AAA")
    assert ind(no_cal, "revenue")["period"]["announced"] is None          # shown as "non verificabile", never guessed


# ---------------------------------------------------------------- indicators, units, currency

def test_indicators_have_value_unit_period_source_and_status():
    x = item(run({"AAA": company()}), "AAA")
    for i in x["indicators"]:
        assert {"key", "label", "value", "unit", "period", "source", "status"} <= set(i)
        assert i["status"] in ("ok", "mancante", "non applicabile", "non significativo")
        assert (i["value"] is None) == (i["status"] != "ok")
    assert ind(x, "opMargin")["value"] == pytest.approx(30.0) and ind(x, "opMargin")["unit"] == "%"
    assert ind(x, "revenue")["unit"] == "USD" and ind(x, "pe")["source"] == "calcolato"
    ttm_rev = sum(q["revenue"] for q in company()["Q"][:4])
    assert ind(x, "ps")["value"] == pytest.approx(4000.0 / ttm_rev)


def test_foreign_accounts_are_converted_and_forward_pe_is_not_used():
    e = company(cur="EUR")
    x = item(run({"EUR1": e}, fx={"EUR": {"rate": 1.1, "date": "2026-08-20"}}), "EUR1")
    ttm_rev = sum(q["revenue"] for q in e["Q"][:4])
    assert ind(x, "revenue")["unit"] == "EUR"
    assert ind(x, "ps")["value"] == pytest.approx(4000.0 / (ttm_rev * 1.1))
    assert ind(x, "fpe")["status"] == "non significativo" and "ADR" in ind(x, "fpe")["note"]
    assert any("EUR" in s for s in x["limits"]) and x["currency"] == {"accounts": "EUR", "price": "USD", "fx": {"rate": 1.1, "date": "2026-08-20"}}
    nofx = item(run({"EUR1": e}), "EUR1")                                  # no exchange rate: no multiple, never USD by default
    assert ind(nofx, "ps")["value"] is None and ind(nofx, "ps")["note"] == "cambio non disponibile"


def test_negative_earnings_give_no_pe_and_no_misleading_growth():
    e = company(npm=-0.10)
    e["FY"][1]["operatingIncome"] = 0.5                                     # tiny base the year before
    x = item(run({"LOSS": e}), "LOSS")
    assert ind(x, "pe")["status"] == "non significativo" and ind(x, "pe")["value"] is None
    assert ind(x, "cashConversion")["status"] == "non significativo"
    assert ind(x, "oiGrowth")["status"] == "non significativo" and ind(x, "oiGrowth")["value"] is None
    assert "pe" not in [p["key"] for p in x["peers"]]


def test_without_cash_flow_the_fcf_is_missing_not_zero():
    x = item(run({"NOCF": company(cash_flow=False)}), "NOCF")
    assert ind(x, "fcf")["status"] == "mancante" and ind(x, "fcfMargin")["value"] is None
    q = x["dims"]["quality"]
    assert q["partial"] and "flusso di cassa libero non disponibile" in q["reasons"]
    assert x["completeness"]["state"] != "Completa"
    assert any(m["label"] == "Flusso di cassa libero" for m in x["missing"])


def test_financial_company_is_not_judged_with_industrial_leverage():
    x = item(run({"BANK": company(ysec="Financial Services", yind="Banks - Regional", debt=900.0, cash=10.0)},
                 sectors={"BANK": "Finanza"}), "BANK")
    assert x["model"]["id"] == "financial"
    assert ind(x, "netDebt")["status"] == "non applicabile" and ind(x, "ndEbitda")["status"] == "non applicabile"
    assert ind(x, "fcf")["status"] == "non applicabile"
    s = x["dims"]["solidity"]
    assert s["state"] == "Non valutabile" and s["partial"] and s.get("structural")
    assert x["profile"]["id"] != "fragilita" and x["completeness"]["state"] != "Insufficiente"
    assert "solidity" in x["completeness"]["sectorLimitedDims"]
    assert any("solidità non valutabile con questi dati" in s for s in x["limits"])


def test_sector_model_reads_italian_and_english_names():
    assert ie.sector_model("Finanza", None, None) == "financial" == ie.sector_model("Financials", None, None)
    assert ie.sector_model("Utility", None, None) == "utility"
    assert ie.sector_model("Tecnologia", None, None) == "tech"
    assert ie.sector_model("Sanità", "Healthcare", "Biotechnology") == "general"
    assert ie.sector_model("Tecnologia", "Financial Services", "Financial Data & Stock Exchanges") == "tech"


# ---------------------------------------------------------------- peers

def test_valuation_compares_only_with_same_model_peers_and_shows_group_size():
    res = run({**PEERS, "BANK": company(yind="Software - Application")}, sectors={"BANK": "Finanza"},
              infos={**PEER_INFOS, "BANK": info(3000.0)})
    a, f, bank = item(res, "A"), item(res, "F"), item(res, "BANK")
    assert a["dims"]["valuation"]["group"] == {"kind": "industria (Yahoo)", "name": "Software - Application", "size": 6}
    assert a["dims"]["valuation"]["state"] == "Contenuta" and f["dims"]["valuation"]["state"] == "Impegnativa"
    assert all(p["groupSize"] == 6 for p in a["peers"])                    # the financial company is not in the group
    assert bank["dims"]["valuation"]["state"] == "Non confrontabile" and bank["peers"] == []
    assert "meno di 5 società comparabili" in bank["dims"]["valuation"]["reasons"][0]
    # cheap is never "undervalued", expensive never "overvalued"
    assert "non significano «sottovalutata»" in " ".join(a["dims"]["valuation"]["reasons"])
    assert "non significano «sopravvalutata»" in " ".join(f["dims"]["valuation"]["reasons"])
    assert "meno cara di tutte le 6" in a["dims"]["valuation"]["reasons"][0]


def test_too_small_group_gives_no_comparison():
    res = run({t: PEERS[t] for t in "ABC"}, infos={t: PEER_INFOS[t] for t in "ABC"})
    x = item(res, "A")
    assert x["dims"]["valuation"]["state"] == "Non confrontabile" and x["peers"] == []
    assert x["profile"]["id"] != "dati_insufficienti"                     # the multiples exist: what lacks is a group


# ---------------------------------------------------------------- missing and stale data

def test_stale_annual_report_makes_the_analysis_insufficient():
    old = company(fy_ends=["2024-06-30", "2023-06-30", "2022-06-30", "2021-06-30"], quarters=False)
    x = item(run({"OLD": old}), "OLD")
    assert any(s.startswith("Dati obsoleti") for s in x["dataIssues"])
    assert x["dims"]["quality"]["state"] == "Non valutabile" and x["profile"]["id"] == "dati_insufficienti"
    assert x["completeness"]["state"] == "Insufficiente"


def test_old_quarters_fall_back_to_the_annual_report():
    e = company(q_ends=["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30", "2024-06-30", "2024-03-31"],
                fy_ends=["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"])
    x = item(run({"HALF": e}), "HALF")
    assert ind(x, "revenue")["period"]["type"] == "FY"
    assert any("potrebbe pubblicare solo semestrali" in s for s in x["limits"])
    assert x["profile"]["id"] != "dati_insufficienti"


def test_results_announced_but_not_yet_in_the_statements_are_flagged():
    e = company(extra_earnings=["2026-08-18T16:05:00-04:00"])
    x = item(run({"LAG": e}), "LAG")
    assert x["lagging"] == "2026-08-18"
    assert "non ancora nei bilanci della fonte" in x["dataIssues"][0]
    assert any("non sono ancora nei bilanci" in m for m in x["monitor"])


def test_a_company_without_statements_is_insufficient_not_zero():
    res = run({"AAA": company()}, infos={"AAA": info(4000.0), "NONE": info(100.0)})
    res2 = ie.analyze_all([{"ticker": "NONE", "name": "None", "sector": "Tecnologia"}], {"data": {}}, {}, {}, {}, NOW)
    x = res2["items"][0]
    assert x["profile"]["id"] == "dati_insufficienti" and "Bilanci non ancora scaricati" in x["dataIssues"][0]
    assert all(i["value"] is None for i in x["indicators"])
    assert item(res, "AAA")["profile"]["id"] != "dati_insufficienti"


# ---------------------------------------------------------------- expectations: consensus vs revisions

def test_consensus_alone_does_not_make_expectations_improve():
    x = item(run({"AAA": company()}, analysts={"AAA": {}}), "AAA")
    e = x["dims"]["expectations"]
    assert e["state"] == "Revisione non verificabile" and e["partial"]
    assert any("consenso «Acquisto» di 20 analisti" in r for r in e["reasons"])     # shown, but not used as a revision
    assert any("storico delle revisioni non è disponibile" in m for m in x["monitor"])


@pytest.mark.parametrize("ago90,state", [(1.0, "In miglioramento"), (1.2, "In peggioramento"), (1.04, "Stabili")])
def test_revisions_drive_the_expectations(ago90, state):
    an = {"epsTrend": {"+1y": {"current": 1.05, "30daysAgo": 1.05, "90daysAgo": ago90}}}
    x = item(run({"AAA": company()}, analysts={"AAA": an}), "AAA")
    assert x["dims"]["expectations"]["state"] == state


# ---------------------------------------------------------------- dimensions, profiles, explanations

def dims(**s):
    base = {"quality": "Buona", "growth": "Positiva", "solidity": "Solida", "valuation": "Nella media del gruppo",
            "expectations": "Stabili", "trend": "Misto"}
    base.update(s)
    return {k: {"state": v} for k, v in base.items()}


def test_profiles_keep_serious_risks_first():
    assert ie.profile(dims(quality="Elevata", growth="Forte", solidity="Fragile"), "Completa") == "fragilita"
    assert ie.profile(dims(valuation="Contenuta", quality="Debole"), "Completa") == "contenuta_rischi"
    assert ie.profile(dims(quality="Elevata", valuation="Impegnativa"), "Completa") == "qualita_cara"
    assert ie.profile(dims(quality="Elevata", growth="Forte"), "Completa") == "qualita_crescita"
    assert ie.profile(dims(quality="Elevata", growth="Forte", expectations="In peggioramento"), "Completa") != "qualita_crescita"
    assert ie.profile(dims(quality="Modesta", growth="Forte"), "Completa", "fcf_invest") == "crescita_investimenti"
    assert ie.profile(dims(quality="Debole", growth="Forte"), "Completa") == "crescita_debole"
    assert ie.profile(dims(growth="Modesta"), "Completa") == "solida_moderata"
    assert ie.profile(dims(growth="In calo", quality="Modesta"), "Completa") == "peggioramento"
    assert ie.profile(dims(quality="Modesta", growth="Modesta", trend="Favorevole"), "Completa") == "trend_da_approfondire"
    assert ie.profile(dims(quality="Elevata", growth="Forte"), "Insufficiente") == "dati_insufficienti"


def test_good_company_profile_and_explanations_use_the_measured_values():
    x = item(run({"AAA": company()}), "AAA")
    d = {k: v["state"] for k, v in x["dims"].items()}
    assert d == {"quality": "Elevata", "growth": "Forte", "solidity": "Solida", "expectations": "In miglioramento",
                 "trend": "Favorevole", "valuation": "Non confrontabile"}
    assert x["profile"]["id"] == "qualita_crescita"
    assert "margine operativo 30,0%" in x["mainStrength"]
    assert any("+20,0%" in s for s in x["strengths"])                      # the revenue growth actually measured
    assert any("+5,0% in 90 giorni" in s for s in x["strengths"])
    assert x["mainWeakness"] == "Nessuna criticità evidente nei dati disponibili."
    assert x["completeness"]["state"] == "Parziale"                        # no comparable group: said, not hidden


def test_high_margin_does_not_cancel_a_fragile_balance_sheet():
    e = company(debt=2000.0, cash=10.0, interest=25.0)
    x = item(run({"DEBT": e}), "DEBT")
    assert x["dims"]["quality"]["state"] in ("Elevata", "Buona") and x["dims"]["solidity"]["state"] == "Fragile"
    assert x["profile"]["id"] == "fragilita"
    assert x["weaknesses"][0].startswith("Solidità fragile") and "volte l'EBITDA" in x["weaknesses"][0]


def test_negative_fcf_with_good_margins_is_investment_not_weakness():
    x = item(run({"CAPX": company(fcfm=-0.05, capex=0.35)}), "CAPX")
    assert x["dims"]["quality"]["state"] == "Modesta"
    assert any("investimenti pari al 35,0% dei ricavi" in r for r in x["dims"]["quality"]["reasons"])
    assert x["profile"]["id"] == "crescita_investimenti"


def test_falling_margin_downgrades_quality():
    e = company()
    for y, m in zip(e["FY"], (0.20, 0.25, 0.30, 0.32)):
        y["operatingIncome"] = y["revenue"] * m
    x = item(run({"DROP": e}), "DROP")
    assert any("redditività in peggioramento" in r for r in x["dims"]["quality"]["reasons"])
    assert any("Margine operativo in calo" in w for w in x["weaknesses"])


def test_order_is_declared_experimental_and_trend_is_separate():
    res = run(PEERS, infos=PEER_INFOS)
    assert [x["order"] for x in res["items"]] == list(range(1, 7))
    assert "trend" not in ie.CORE
    texts = json.dumps(res, ensure_ascii=False)
    for word in ("Compra", "Vendi", "target price", "probabilità di", "prezzo obiettivo"):
        assert word not in texts


# ---------------------------------------------------------------- the Pagella and the scanners are unchanged

def test_pagella_is_only_shown_and_the_scanner_model_is_unchanged():
    pag = {"A": {"ok": 4, "n": 6, "status": "Da approfondire", "rank": None, "conditions": []}}
    before = json.dumps(pag)
    res = run(PEERS, infos=PEER_INFOS, pagella=pag)
    assert json.dumps(pag) == before and item(res, "A")["pagella"]["ok"] == 4
    assert ie.compact(item(res, "A"))["pagella"] == {"ok": 4, "n": 6, "status": "Da approfondire", "rank": None}
    assert o.MODEL_VERSION == "O2.1" and [c[0] for c in o.INVEST] == ["I1", "I2", "I3", "I4", "I5", "I6"]
    assert [c[0] for c in o.TRADING] == ["T1", "T2", "T3", "T4", "T5"] and (o.TRADING_MIN, o.INVEST_MIN) == (4, 5)


# ---------------------------------------------------------------- diary (new tables, prospective only)

EVENING = datetime(2026, 10, 30, 18, 30, tzinfo=ET)


def engine_result(day="2026-10-30"):
    techs = {t: {**TECH, "date": day} for t in PEERS}
    return run(PEERS, infos=PEER_INFOS, techs=techs, now=EVENING)


def test_investment_diary_never_starts_the_diary():
    saved, why = invd.record(engine_result(), "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)
    assert not saved and "non ha registrato la seduta" in why
    assert not os.path.exists(od.DB)                                        # no file, no artificial first day
    assert invd.stats() == {"started": False, "days": 0} and not invd.exists("2026-10-30", ie.VERSION)


def test_investment_diary_records_once_after_the_opportunity_diary_and_is_immutable():
    from test_opportunity_diary import result as _r  # noqa: F401  (fixture module imported for its helpers)
    from test_opportunities import QQQ, RISING_VOL, TODAY, frame, path, stock
    scan = o.scan([stock("AAA")], {"AAA": frame(path(300, 0.004), RISING_VOL)}, QQQ, {}, today=TODAY, keep_all=True)
    ok, _ = od.record(scan, "2026-10-30", EVENING.isoformat(), "test")
    assert ok
    with sqlite3.connect(od.DB) as con:
        before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("runs", "observations")}
    assert invd.stats() == {"started": False, "days": 0}                    # a read never creates the new tables
    with sqlite3.connect(od.DB) as con:
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='inv_runs'").fetchone()
    wrong = engine_result(day="2026-10-29")                                 # trend not of that session
    assert invd.record(wrong, "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)[0] is False
    early = datetime(2026, 10, 30, 15, 0, tzinfo=ET)                         # before the close
    assert invd.record(engine_result(), "2026-10-30", early.isoformat(), "test", o.MODEL_VERSION)[0] is False
    saved, why = invd.record(engine_result(), "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)
    assert saved and why == "6 giudizi fondamentali salvati"
    assert invd.record(engine_result(), "2026-10-30", EVENING.isoformat(), "test", o.MODEL_VERSION)[0] is False
    with sqlite3.connect(od.DB) as con:
        assert {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("runs", "observations")} == before
        row = con.execute("SELECT model_version, profile, dims, indicators, data_dates FROM inv_observations WHERE ticker='A'").fetchone()
        assert row[0] == ie.VERSION and row[1] in dict(ie.PROFILES)
        assert json.loads(row[2])["valuation"]["state"] == "Contenuta"
        assert json.loads(row[3])[0]["period"]["end"] == "2026-06-30" and "statements" in json.loads(row[4])
        for sql in ("UPDATE inv_observations SET profile='x'", "DELETE FROM inv_observations", "DELETE FROM inv_runs"):
            with pytest.raises(sqlite3.DatabaseError):
                con.execute(sql)
    s = invd.stats()
    assert s["started"] and s["days"] == 1 and s["observations"] == 6 and s["versions"] == [ie.VERSION]


# ---------------------------------------------------------------- API and page

@pytest.fixture
def api(monkeypatch, tmp_path):
    import server
    rows = [{"ticker": t, "name": f"{t} Inc.", "sector": "Tecnologia", "price": 110.0} for t in PEERS]
    st = server.store
    idx = pd.bdate_range(end="2026-08-20", periods=260)
    df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": [100 + i * 0.1 for i in range(260)], "Volume": 1e6}, index=idx)
    monkeypatch.setattr(st, "snapshot", {"asOf": "2026-08-20T10:00:00-04:00", "stocks": rows})
    monkeypatch.setattr(st, "daily", {**{t: df for t in PEERS}, "QQQ": df})
    monkeypatch.setattr(st, "analysts", {t: ANALYST for t in PEERS})
    monkeypatch.setattr(st, "infos", PEER_INFOS)
    monkeypatch.setattr(st, "error", None)
    monkeypatch.setattr(server, "opportunities", lambda keep_all=False, now=None: None)
    monkeypatch.setattr(server, "download", lambda *a, **k: pytest.fail("no download when the page asks"))
    server._inv.update(key=None, data=None)
    yield server
    server._inv.update(key=None, data=None)


def write_cache(companies):
    os.makedirs(os.path.dirname(fu.CACHE), exist_ok=True)
    with open(fu.CACHE, "w") as f:
        json.dump({"schema": 1, "savedAt": "2026-08-10T09:00:00-04:00", "data": companies, "fx": {}, "firstSeen": {}}, f)


def test_api_without_statements_says_why_and_starts_the_background_download(api, monkeypatch):
    asked = []
    monkeypatch.setattr(api, "refresh_fundamentals", lambda tickers, force=False: asked.append((len(tickers), force)))
    monkeypatch.setattr(api.store, "constituents", [{"ticker": t} for t in PEERS])
    r = api.app.test_client().get("/api/investment")
    d = json.loads(r.data)
    assert r.status_code == 200 and d["available"] is False and "bilanci non ancora scaricati" in d["reason"]
    assert asked == [(6, True)]
    assert api.app.test_client().get("/api/investment/A").status_code == 503


def test_api_returns_compact_rows_and_the_full_analysis(api):
    write_cache(PEERS)
    c = api.app.test_client()
    d = json.loads(c.get("/api/investment").data)
    assert d["available"] and d["model"]["version"] == ie.VERSION and len(d["items"]) == 6
    row = next(x for x in d["items"] if x["ticker"] == "A")
    assert set(row["dims"]) == {k for k, _ in ie.DIMS} and "indicators" not in row
    assert row["dims"]["valuation"]["state"] == "Contenuta" and row["priceDate"] == "2026-08-20"
    full = json.loads(c.get("/api/investment/a").data)
    assert full["ticker"] == "A" and full["engineVersion"] == ie.VERSION and full["model"]["id"] == "tech"
    assert full["indicators"] and full["peers"] and full["monitor"]
    assert c.get("/api/investment/ZZZ").status_code == 404
    assert d["diary"] == {"started": False, "days": 0} and not os.path.exists(od.DB)


def test_page_has_the_investment_panel_and_valid_javascript():
    js = open(os.path.join(ROOT, "static", "app.js")).read()
    for needle in ("function invCardHTML", "function invDetailHTML", "/api/investment", "Analisi investimento", "data-ifil", "data-isort"):
        assert needle in js
    assert "Compra" not in re.search(r"const INV_FILTERS[\s\S]+?function invDetailHTML", js).group(0)
    node = subprocess.run(["node", "--check", os.path.join(ROOT, "static", "app.js")], capture_output=True, text=True)
    if node.returncode == 127:
        pytest.skip("node non installato")
    assert node.returncode == 0, node.stderr
