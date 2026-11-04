"""Diary of the positions' levels (pos_diary.py) and its fixed test. Made-up data only."""
from datetime import date, timedelta

import pos_diary


def p(isin, action, price, qty=10):
    return {"isin": isin, "ticker": isin[:3], "kind": "Azione", "qty": qty, "value": price * qty, "weight": 10.0,
            "action": {"action": action, "rules": [{"id": "V1", "state": "on" if action == "Valuta la vendita" else "off"}], "silenced": None},
            "pillars": {"draft": False, "score": {"n": 2, "ok": 2, "ko": 0, "na": 0}}}


def test_a_day_is_written_once_and_never_rewritten():
    assert pos_diary.save("2026-11-04", [p("XX01", "Mantieni", 10)])
    assert not pos_diary.save("2026-11-04", [p("XX01", "Accumula", 99)])
    e = pos_diary.load("2026-11-04")["positions"][0]
    assert e["action"] == "Mantieni" and e["priceEur"] == 10 and e["fired"] == []
    assert "name" not in e and "value" not in e                       # no names, no values in the diary


def test_not_enough_cases_says_so():
    pos_diary.save("2026-01-05", [p("XX01", "Valuta la vendita", 10), p("XX02", "Mantieni", 10)])
    pos_diary.save("2026-04-06", [p("XX01", "Mantieni", 8), p("XX02", "Mantieni", 11)])
    line = pos_diary.test_line()
    assert line["sell"]["cases"] == 1 and line["sell"]["verdict"] == "dati ancora insufficienti"
    assert line["add"]["verdict"] == "dati ancora insufficienti" and line["days"] == 2


def write_days(sell_moves, other_move=0.0):
    """Day 0: one "Valuta la vendita" position per move plus one other; 3 months later the prices have moved."""
    for i, m in enumerate(sell_moves):
        pos_diary.save(f"2025-{i // 28 + 1:02d}-{i % 28 + 1:02d}", [p("SELL", "Valuta la vendita", 100), p("REST", "Mantieni", 100)])
        later = date.fromisoformat(f"2025-{i // 28 + 1:02d}-{i % 28 + 1:02d}") + timedelta(days=91)
        pos_diary.save(later.isoformat(), [p("SELL", "Mantieni", 100 + m), p("REST", "Mantieni", 100 + other_move)])


def test_valuta_la_vendita_passes_only_with_60_percent_and_2_points():
    write_days([-5.0] * 20 + [1.0] * 12)          # 32 cases, 62.5% worse, median −5 points
    s = pos_diary.stats()["3 mesi"]["Valuta la vendita"]
    assert s["cases"] == 32 and s["verdict"] == "supera il test"


def test_valuta_la_vendita_fails_with_a_small_difference():
    write_days([-1.0] * 32)                       # always worse, but only by 1 point
    assert pos_diary.stats()["3 mesi"]["Valuta la vendita"]["verdict"] == "non supera il test"
