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
    import etf_holdings
    import history
    import portfolio
    import rules
    monkeypatch.setattr(portfolio, "PORTFOLIO_DIR", str(tmp_path))
    monkeypatch.setattr(actions, "FILE", str(tmp_path / "tesi.json"))
    monkeypatch.setattr(actions, "FISCAL", str(tmp_path / "fiscale.json"))
    monkeypatch.setattr(rules, "FILE", str(tmp_path / "regole.json"))
    monkeypatch.setattr(history, "DIR", str(tmp_path / "storico"))
    monkeypatch.setattr(history, "FLOWS", str(tmp_path / "storico" / "flussi.json"))
    monkeypatch.setattr(diary, "DIR", str(tmp_path / "diario"))
    monkeypatch.setattr(diary, "EXCLUDED", str(tmp_path / "diario" / "esclusi.json"))
    monkeypatch.setattr(etf_holdings, "PRIVATE", str(tmp_path / "etf_composizioni.json"))
    monkeypatch.setattr(etf_holdings, "PUBLIC", str(tmp_path / "etf_holdings.json"))
    return tmp_path
