"""Time-weighted return (history.py): money added or removed must never count as a gain or a loss."""
import history


def picture(day, file, positions):
    return {"date": day, "file": file, "fx": 1.0, "value": sum(p["value"] for p in positions),
            "cost": sum(p["cost"] for p in positions), "positions": positions}


def P(isin, qty, price, cost):
    return {"isin": isin, "name": isin, "ticker": isin, "currency": "EUR", "qty": qty, "price": price, "value": qty * price, "cost": cost}


def test_purchase_is_an_exact_flow_and_sale_an_estimated_one():
    before = picture("2026-10-01", "a.xls", [P("A", 10, 100, 900), P("B", 5, 50, 200)])
    after = picture("2026-10-02", "b.xls", [P("A", 20, 100, 1900)])
    f = history.detect_flow(before, after, "2026-10-02")
    assert f["bought"] == 1000                              # increase of Fineco's cost value
    assert f["sold"] == 250 and f["estimated"]              # 5 shares x last price, estimated
    assert f["amount"] == 750


def test_time_weighted_return_ignores_money_added(monkeypatch):
    days = ["2026-10-01", "2026-10-02", "2026-10-05"]
    pics = {days[0]: {"date": days[0], "value": 1000, "cost": 1000, "positions": []},
            days[1]: {"date": days[1], "value": 1100, "cost": 1000, "positions": []},          # +10%
            days[2]: {"date": days[2], "value": 6100, "cost": 6000, "positions": []}}          # +5000 EUR added, price flat
    monkeypatch.setattr(history, "_days", lambda: days)
    monkeypatch.setattr(history, "_read", lambda d: pics[d])
    monkeypatch.setattr(history, "_flows", lambda: [{"date": days[2], "amount": 5000, "details": []}])
    monkeypatch.setattr(history, "_bench_series", lambda start: {})
    pts = history.performance()["points"]
    assert abs(pts[1]["twr"] - 1.10) < 1e-9
    assert abs(pts[2]["twr"] - 1.10) < 1e-9                 # the 5000 EUR are not a gain


def test_record_writes_once_per_day_and_never_a_past_day(private_folder):
    pf = {"file": "a.xls", "error": None, "resolving": False, "quotesAt": 1, "fx": 1.0,
          "positions": [{"isin": "A", "name": "A", "ticker": None, "currency": "EUR", "qty": 1, "price": 10, "value": 10, "cost": 8}],
          "totals": {"value": 10, "cost": 8}}
    assert history.record(pf, "2026-10-02")
    assert not history.record(pf, "2026-10-01")             # a day before the last saved one is never written
