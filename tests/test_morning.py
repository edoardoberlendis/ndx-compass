"""Text of the morning summary (morning_job.py) on made-up data: nothing relevant -> no window."""
from datetime import date

import morning_job


def test_nothing_relevant_means_no_window():
    assert morning_job.summary_text(date(2026, 10, 9), [], [], 0, []) is None


def test_summary_text():
    t = morning_job.summary_text(date(2026, 10, 9), [("Inflazione CPI (09/2026)", "14:30")],
                                 [("NFLX", date(2026, 10, 13), "dopo la chiusura", "preferito")], 11, ["2026-10-07"])
    assert t.startswith("Nasdaq-100 Monitor · ven 9 ott")
    assert "· Inflazione CPI (09/2026) alle 14:30 ora italiana" in t
    assert "· NFLX mar 13 ott, dopo la chiusura (preferito)" in t
    assert "Posizioni in «Rivedi la tesi»: 11" in t and "manca 1 seduta (7 ott)" in t
    assert t.endswith("non è una consulenza finanziaria.")
