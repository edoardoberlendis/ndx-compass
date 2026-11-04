"""Proposed levels of my positions (actions.py, phase 26: only the analysis of the stock, no thesis) and the
indicative tax estimate, on made-up positions."""
from datetime import date, datetime, timedelta

import actions


def pos(name="AAA", kind="Azione", value=1000.0, price=50.0, cost_price=40.0, lev=1, ticker=None):
    return {"name": name, "isin": ("IT" + name * 4)[:12], "ticker": ticker or name, "kind": kind, "value": value,
            "cost": value * cost_price / price, "price": price, "costPrice": cost_price, "leverage": lev, "exposure": value * lev,
            "sector": "Tecnologia", "themes": [], "country": "USA", "currency": "USD"}


def pag(*states, since="2026-01-05", initial=False):
    """A pagella with the given states ("ok", "ko", "na")."""
    ids = ["ricavi", "stime", "consenso", "margine", "valutazione", "trend"]
    lst = [{"id": ids[i], "name": ids[i], "state": st} for i, st in enumerate(states)]
    return {"list": lst, "last": {x["id"]: {"state": x["state"], "since": since, "initial": initial} for x in lst if x["state"] != "na"}}


GOOD = {"verdict": "Entra ora", "label": "Entra ora", "why": ["tutte le regole sono soddisfatte"], "trendBase": True}


def run(positions, pillars=None, market=None, stops=None, sma=None, below=None, an=None, first=None, rows=None):
    pf = {"positions": positions, "totals": {"value": sum(p["value"] for p in positions)}}
    actions.evaluate(pf, {"rows": rows or {}, "sma200": sma or {}, "below200": below or {}, "analysts": an or {}, "firstSeen": first or {},
                          "pillars": pillars or {}, "market": market or {}, "stops": stops or {}})
    return {p["name"]: p["action"] for p in positions}


def rule(a, rid):
    return next(r for r in a["rules"] if r["id"] == rid)


def test_nothing_known_is_mantieni_and_old_ids_are_gone():
    a = run([pos()])["AAA"]
    assert a["action"] == "Mantieni" and a["todo"] == "Niente da fare."
    ids = {r["id"] for r in a["rules"]}
    assert not ids & {"R1", "A3", "V1", "V3", "V6", "V10", "A1", "A6"}          # removed rules: ids are not reused


def test_automatic_stop_broken_is_valuta_la_vendita_with_tax():
    p = pos(price=50)
    a = run([p], stops={p["isin"]: {"stop": 51, "since": "2026-11-01", "atr": 2}})["AAA"]
    assert a["action"] == "Valuta la vendita" and rule(a, "S1")["state"] == "on" and a["tax"] is not None
    assert a["until"] == [actions.UNTIL["S1"]]


def test_near_the_automatic_stop_is_attenzione():
    p = pos(price=50)
    a = run([p], stops={p["isin"]: {"stop": 49, "since": "2026-11-01", "atr": 2}})["AAA"]     # 0.5 ATR above
    assert a["action"] == "Attenzione" and rule(a, "T6")["state"] == "on"
    a = run([p], stops={p["isin"]: {"stop": 45, "since": "2026-11-01", "atr": 2}})["AAA"]     # 2.5 ATR above
    assert rule(a, "T6")["state"] == "off"


def test_half_the_computable_checks_fallen_is_valuta_la_vendita():
    p = pos()
    a = run([p], pillars={p["isin"]: pag("ko", "ko", "ok", "ok")})["AAA"]
    assert a["action"] == "Valuta la vendita" and rule(a, "S2")["state"] == "on"
    a = run([p], pillars={p["isin"]: pag("ko", "ok", "ok", "ok")})["AAA"]
    assert rule(a, "S2")["state"] == "off"
    a = run([p], pillars={p["isin"]: pag("ko", "ko", "na", "na", "ok", "ok")})["AAA"]      # 2 of 4 computable
    assert rule(a, "S2")["state"] == "on"


def test_missing_check_never_counts_as_fallen():
    p = pos()
    a = run([p], pillars={p["isin"]: pag("ko", "ko", "na", "na", "na", "na")})["AAA"]      # only 2 computable
    assert rule(a, "S2")["state"] == "na" and "dati insufficienti" in rule(a, "S2")["detail"] and a["action"] != "Valuta la vendita"
    a = run([p], pillars={p["isin"]: pag("ko", "ok", "na", "na", "na", "na")})["AAA"]
    assert rule(a, "S2")["state"] == "na"
    a = run([p], pillars={p["isin"]: pag("ko", "ok", "ok", "na", "na", "na")})["AAA"]      # 1 fallen of 3: the "?" do not add up
    assert rule(a, "S2")["state"] == "off"
    a = run([p], pillars={p["isin"]: pag("ok", "ok", "ok", "ok", "na", "na")}, market={p["isin"]: GOOD})["AAA"]
    assert rule(a, "B1")["state"] == "on"                                                    # 4 true, the "?" are not false


def test_evita_is_valuta_la_vendita():
    p = pos()
    a = run([p], market={p["isin"]: {"verdict": "Evita", "label": "Evita", "why": ["azienda debole"]}})["AAA"]
    assert a["action"] == "Valuta la vendita" and rule(a, "S4")["state"] == "on"


def test_check_just_fallen_is_attenzione_but_not_the_first_day():
    p = pos()
    recent = (date.today() - timedelta(days=3)).isoformat()
    a = run([p], pillars={p["isin"]: pag("ko", "ok", "ok", "ok", since=recent)})["AAA"]
    assert a["action"] == "Attenzione" and rule(a, "T1")["state"] == "on"
    a = run([p], pillars={p["isin"]: pag("ko", "ok", "ok", "ok", since=recent, initial=True)})["AAA"]
    assert rule(a, "T1")["state"] == "off"                                                   # the first check is not a fall


def test_below_the_200_day_average_is_news_only_for_10_sessions():
    a = run([pos(price=50)], sma={"AAA": 55}, below={"AAA": 3})["AAA"]
    assert a["action"] == "Attenzione" and "da 3 sedute" in rule(a, "T2")["detail"]
    a = run([pos(price=50)], sma={"AAA": 55}, below={"AAA": 25})["AAA"]
    assert a["action"] == "Mantieni" and rule(a, "T2")["state"] == "off"


def test_earnings_within_5_days_is_attenzione():
    p = pos()
    soon = (datetime.now() + timedelta(days=2)).timestamp()
    a = run([p], market={p["isin"]: {"earningsTs": soon}})["AAA"]
    assert a["action"] == "Attenzione" and rule(a, "T5")["state"] == "on" and rule(a, "B4")["state"] == "off"


def test_accumula_needs_everything():
    p = pos()
    good = pag("ok", "ok", "ok", "ok", "ok", "ok")
    a = run([p], pillars={p["isin"]: good}, market={p["isin"]: GOOD})["AAA"]
    assert a["action"] == "Accumula"
    a = run([p], pillars={p["isin"]: pag("ok", "ok", "ok", "ok", "ok", "ko")}, market={p["isin"]: GOOD})["AAA"]
    assert a["action"] == "Mantieni" and rule(a, "B1")["state"] == "off"                    # one false check
    a = run([p], pillars={p["isin"]: good}, market={p["isin"]: {**GOOD, "verdict": "Entra su ritracciamento"}})["AAA"]
    assert a["action"] == "Accumula"                                                         # pullback verdict is fine
    a = run([p], pillars={p["isin"]: good}, market={p["isin"]: {**GOOD, "trendBase": False}})["AAA"]
    assert a["action"] == "Mantieni" and rule(a, "B2")["state"] == "off"
    a = run([pos(lev=3)], pillars={"ITAAAAAAAAAA": good}, market={"ITAAAAAAAAAA": GOOD})["AAA"]
    assert a["action"] != "Accumula"


def test_funds_need_both_checks_and_skip_analyst_rules():
    p = pos(kind="ETF")
    a = run([p], pillars={p["isin"]: pag("ok", "ok")}, market={p["isin"]: GOOD})["AAA"]
    assert a["action"] == "Accumula" and rule(a, "T3")["state"] == "na" and rule(a, "T5")["state"] == "na"
    a = run([p], pillars={p["isin"]: pag("ok", "na")}, market={p["isin"]: GOOD})["AAA"]
    assert a["action"] == "Mantieni"


def test_big_loss_is_only_a_note_and_never_suggests_selling():
    a = run([pos(price=20, cost_price=40)])["AAA"]
    assert a["action"] == "Mantieni"
    note = [n for n in a["notes"] if "prezzo di carico" in n][0]
    assert "non al prezzo pagato" in note and "vend" not in note.lower()


# ---------------------------------------------------------------- tax estimate

def test_tax_on_a_share_gain_without_zainetto():
    t = actions.tax_estimate(pos(value=1000, price=50, cost_price=40), 1000, True)
    assert round(t["gain"], 2) == 200 and round(t["tax"], 2) == 52 and "zainetto" in t["text"]


def test_zainetto_reduces_the_tax_on_shares_and_etc():
    fiscal = {"losses": 150.0, "expiry": "2027-12-31"}
    for kind in ("Azione", "ETC"):
        t = actions.tax_estimate(pos(kind=kind, value=1000, price=50, cost_price=40), 1000, True, fiscal)
        assert round(t["lossesUsed"], 2) == 150 and round(t["tax"], 2) == 13      # (200 - 150) x 26%


def test_zainetto_never_used_for_etf_gains():
    t = actions.tax_estimate(pos(kind="ETF", value=1000, price=50, cost_price=40), 1000, True, {"losses": 150.0, "expiry": None})
    assert t["lossesUsed"] == 0 and round(t["tax"], 2) == 52 and "reddito di capitale" in t["text"]


def test_a_loss_pays_no_tax():
    t = actions.tax_estimate(pos(value=1000, price=40, cost_price=50), 1000, True)
    assert t["gain"] < 0 and t["tax"] == 0


def test_fiscal_file_round_trip(private_folder):
    actions.save_fiscal(1200.5, "2028-12-31")
    assert actions.load_fiscal() == {"losses": 1200.5, "expiry": "2028-12-31"}
    actions.save_fiscal(None, None)
    assert actions.load_fiscal()["losses"] is None
