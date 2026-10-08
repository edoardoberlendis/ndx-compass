"""Reaction day of an earnings report (earnings.py) on made-up prices: before the open -> that session, after the close
-> the next session, also across a weekend."""
import pandas as pd

import earnings

# Fri 2 Oct ... Wed 7 Oct 2026, one close per session
CLOSES = pd.Series([100.0, 110.0, 99.0, 102.0, 102.0], index=pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]))


def rep(ts):
    return {"ts": ts, "eps": 1.0, "reported": 1.1, "surprise": 10.0}


def test_before_the_open_is_the_same_session():
    m = earnings.reaction_moves([rep("2026-10-02T07:00:00-04:00")], CLOSES)
    assert m == [{"date": "2026-10-02", "move": 10.000000000000009}] or (m[0]["date"] == "2026-10-02" and abs(m[0]["move"] - 10) < 1e-9)


def test_after_the_close_is_the_next_session():
    m = earnings.reaction_moves([rep("2026-10-05T16:05:00-04:00")], CLOSES)
    assert m[0]["date"] == "2026-10-06" and abs(m[0]["move"] - (102 / 99 - 1) * 100) < 1e-9


def test_friday_after_the_close_reacts_on_monday():
    m = earnings.reaction_moves([rep("2026-10-02T16:00:00-04:00")], CLOSES)
    assert m[0]["date"] == "2026-10-05" and abs(m[0]["move"] - (99 / 110 - 1) * 100) < 1e-9


def test_monday_before_the_open_compares_with_friday():
    m = earnings.reaction_moves([rep("2026-10-05T08:00:00-04:00")], CLOSES)
    assert m[0]["date"] == "2026-10-05" and abs(m[0]["move"] - (99 / 110 - 1) * 100) < 1e-9


def test_usual_move_needs_at_least_four_reports():
    three = [rep(t) for t in ("2026-10-02T07:00:00-04:00", "2026-10-05T08:00:00-04:00", "2026-10-06T07:00:00-04:00")]
    assert earnings.usual_move(three, CLOSES) is None
    four = three + [rep("2026-10-07T07:00:00-04:00")]
    moves = [abs(m["move"]) for m in earnings.reaction_moves(four, CLOSES)]
    assert abs(earnings.usual_move(four, CLOSES) - sum(moves) / 4) < 1e-9
