"""Shared fixtures for the tests. Rule: only made-up data, never the files in portafoglio/ (personal data).
Every module that reads or writes in portafoglio/ is pointed to a temporary folder before each test."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def private_folder(tmp_path, monkeypatch):
    """portafoglio/ is replaced by an empty temporary folder in every test."""
    import actions
    import diary
    import etf_buy
    import etf_holdings
    import history
    import pillars
    import portfolio
    import pos_diary
    import rules
    import stop_auto
    monkeypatch.setattr(portfolio, "PORTFOLIO_DIR", str(tmp_path))
    monkeypatch.setattr(actions, "FISCAL", str(tmp_path / "fiscale.json"))
    monkeypatch.setattr(pos_diary, "DIR", str(tmp_path / "diario_posizioni"))
    monkeypatch.setattr(pillars, "FILE", str(tmp_path / "dati_titoli.json"))
    monkeypatch.setattr(pillars, "LOG", str(tmp_path / "pagella.json"))
    monkeypatch.setattr(stop_auto, "FILE", str(tmp_path / "stop_auto.json"))
    monkeypatch.setattr(rules, "FILE", str(tmp_path / "regole.json"))
    monkeypatch.setattr(history, "DIR", str(tmp_path / "storico"))
    monkeypatch.setattr(history, "FLOWS", str(tmp_path / "storico" / "flussi.json"))
    monkeypatch.setattr(diary, "DIR", str(tmp_path / "diario"))
    monkeypatch.setattr(diary, "EXCLUDED", str(tmp_path / "diario" / "esclusi.json"))
    monkeypatch.setattr(etf_buy, "DIR", str(tmp_path / "diario_etf"))
    monkeypatch.setattr(etf_holdings, "PRIVATE", str(tmp_path / "etf_composizioni.json"))
    monkeypatch.setattr(etf_holdings, "PUBLIC", str(tmp_path / "etf_holdings.json"))
    import opportunity_diary   # phase O2: the opportunity diary (public data, data/) is never the real one in a test
    monkeypatch.setattr(opportunity_diary, "DB", str(tmp_path / "data" / "opportunita.sqlite3"))
    import market_data_quality        # phase 4A: lab reports, rechecks and quality reports never the real ones in a test
    import opportunity_validation
    monkeypatch.setattr(opportunity_validation, "OUT_DIR", str(tmp_path / "validazione"))
    monkeypatch.setattr(opportunity_validation, "LOG", str(tmp_path / "validazione" / "esperimenti.jsonl"))
    monkeypatch.setattr(opportunity_validation, "RECHECK_DIR", str(tmp_path / "validazione" / "rielaborazioni"))
    monkeypatch.setattr(opportunity_validation, "DIARY", str(tmp_path / "data" / "opportunita.sqlite3"))
    monkeypatch.setattr(market_data_quality, "OUT_DIR", str(tmp_path / "validazione" / "qualita"))
    import opportunity_strategies     # phase 4B: registration, reports and log of the strategies never the real ones
    monkeypatch.setattr(opportunity_strategies, "OUT_DIR", str(tmp_path / "strategie"))
    import fundamentals               # phase 5A: the statements cache is never the real one in a test
    monkeypatch.setattr(fundamentals, "CACHE", str(tmp_path / "cache" / "fundamentals.json"))
    return tmp_path
