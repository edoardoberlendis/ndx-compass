"""ETF tab (phase 24): pure calculations of etf.py with made-up prices and a made-up portfolio."""
import numpy as np
import pandas as pd

import etf
import etf_holdings


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


def test_overlap_takes_the_smaller_weight_and_gives_the_share_already_owned():
    top = [{"key": "nvidia", "name": "NVIDIA", "weight": 0.10}, {"key": "asml", "name": "ASML", "weight": 0.05},
           {"key": "xyz", "name": "XYZ", "weight": 0.20}]
    pts, share, common = etf.overlap(top, {"nvidia": 0.04, "asml": 0.08})
    assert round(pts, 6) == 9.0 and round(share, 6) == 15.0
    assert [c["name"] for c in common] == ["NVIDIA", "ASML"] and round(common[0]["mine"], 6) == 4.0


def test_company_key_matches_names_of_different_sources():
    k = etf_holdings.company_key
    assert k("Samsung Electronics Co., Ltd.") == k("SAMSUNG ELECTRONICS LTD") == k("SAMSUNG ELECTRONICS NON VOTING PRE") == "samsung electronics"
    assert k("ALPHABET INC CLASS A") == k("Alphabet Inc. Class C") == "alphabet"
    assert k("NVIDIA Corp") == k("NVIDIA") == "nvidia"
    assert k("SIEMENS N AG") == "siemens"
    assert k("Taiwan Semiconductor Manufacturing Co Ltd ADR") == k("TAIWAN SEMICONDUCTOR MANUFACTURING") == "taiwan semiconductor"
    assert k("Petróleo Brasileiro SA") == "petroleo brasileiro"


def test_share_classes_of_one_company_are_merged():
    rows = [{"name": "Samsung Electronics Co., Ltd.", "isin": "KR1", "weight": 0.25},
            {"name": "SK hynix, Inc.", "isin": "KR2", "weight": 0.16},
            {"name": "Samsung Electronics Co., Ltd. Pref", "isin": "KR3", "weight": 0.03}]
    m = etf_holdings.merge_classes(rows)
    assert [x["key"] for x in m] == ["samsung electronics", "sk hynix"]
    assert round(m[0]["weight"], 6) == 0.28 and m[0]["isins"] == ["KR1", "KR3"]


def test_lookthrough_by_isin_name_index_and_leverage():
    import portfolio
    pf = {"totals": {"value": 1000}, "positions": [
        {"isin": "KR1", "name": "SAMSUNG ELEC", "kind": "Azione", "value": 100},                       # direct stock: matched by ISIN
        {"isin": "IE0", "name": "Fondo finto", "kind": "ETF", "value": 200, "leverage": 3},            # fund with holdings, 3x
        {"isin": "IE9", "name": "Fondo senza dati", "kind": "ETF", "value": 100},
        {"isin": "IE5", "name": "Nasdaq finto", "kind": "ETF", "value": 600, "sector": portfolio.LOOK_THROUGH_NDX}]}
    holdings = {"IE0": {"top": [{"key": "sk hynix", "name": "SK hynix", "weight": 0.5, "isins": ["KR2"]},
                                {"key": "samsung electronics", "name": "Samsung", "weight": 0.1, "isins": ["KR1"]}]}}
    mine, missing = etf.my_lookthrough(pf, {"NVDA": ("NVIDIA Corp", 10.0)}, holdings)
    assert round(mine["samsung electronics"], 6) == round(0.1 + 0.2 * 3 * 0.1, 6)
    assert round(mine["sk hynix"], 6) == 0.3 and round(mine["nvidia"], 6) == 0.06
    assert missing == ["IE9"]


def test_moves_with_only_above_070():
    assert etf.moves_with_text("Messico", 0.72).startswith("negli ultimi 6 mesi si è mosso come Messico")
    assert etf.moves_with_text("Messico", 0.39) == "non si muove in modo simile a nessun'altra categoria (correlazione massima 0,39 con Messico)"


def test_diversify_rules():
    before = conc(60, 70)
    def fit(tech, usa, usd):
        return {"before": before, "after": {"tecnologia": 0.9 * 60 + 0.1 * tech, "USA": 0.9 * 70 + 0.1 * usa, "dollaro (stima)": 0.9 * 70 + 0.1 * usd}}
    rows = [{"isin": "A", "category": "Europa", "group": "Aree e paesi", "ter": 0.12},
            {"isin": "B", "category": "Giappone", "group": "Aree e paesi", "ter": 0.20},
            {"isin": "C", "category": "Sanità USA", "group": "Settori", "ter": 0.15},           # raises USA: out
            {"isin": "D", "category": "Robotica", "group": "Temi", "ter": 0.40},                # theme: out
            {"isin": "E", "category": "Monetario euro", "group": "Obbligazionari", "ter": 0.10},
            {"isin": "F", "category": "Oro (ETC)", "group": "Oro e materie prime", "ter": 0.12},  # raises the dollar: out
            {"isin": "G", "category": "Argento (ETC)", "group": "Oro e materie prime", "ter": 0.20},
            {"isin": "H", "category": "Europa", "group": "Aree e paesi", "ter": 0.07}]           # same category as A
    fits = {"A": fit(5, 0, 0), "B": fit(10, 0, 0), "C": fit(0, 100, 100), "D": fit(0, 0, 0), "E": fit(0, 0, 0),
            "F": fit(0, 0, 100), "G": fit(0, 0, 0), "H": fit(5, 10, 10)}
    out = etf.diversify(rows, fits)
    assert [x["isin"] for x in out["equity"]] == ["A", "B"]          # A lowers USA and dollar more than H, same tech
    assert [x["isin"] for x in out["defensive"]] == ["E"]            # gold raises the dollar; silver is not defensive
    assert out["equity"][0]["top"] == "USA"


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


def test_holdings_entries_are_refreshed_by_source_age():
    from datetime import date
    today = date(2026, 10, 10)
    assert etf_holdings.stale(None, today)
    assert not etf_holdings.stale({"fetched": "2026-09-20", "kind": "emittente"}, today)
    assert etf_holdings.stale({"fetched": "2026-09-01", "kind": "emittente"}, today)
    assert not etf_holdings.stale({"fetched": "2026-06-01", "kind": "justETF"}, today)
    assert not etf_holdings.stale({"fetched": "2026-01-01", "none": etf_holdings.NO_STOCKS_REASON}, today)
    assert etf_holdings.stale({"fetched": "2026-10-01", "none": "composizione non disponibile"}, today)


def test_xlsx_reader_reads_shared_strings_and_numbers():
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/sharedStrings.xml", "<sst><si><t>ISIN</t></si><si><t>Percent of Fund</t></si><si><t>US0000000001</t></si></sst>")
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                                               '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>1.25</v></c></row></sheetData></worksheet>')
    assert etf_holdings.xlsx_rows(b.getvalue()) == [["ISIN", "Percent of Fund"], ["US0000000001", "1.25"]]


def test_launch_date_and_italian_dates():
    assert etf.launch_iso("24 October 2018") == "2018-10-24" and etf.launch_iso(None) is None
    assert etf_holdings._it_date("08/10/2026") == "2026-10-08" == etf_holdings._it_date("08-Oct-2026")
