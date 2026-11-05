"""Shared fixtures for the tests. Rule: only made-up data, never the files in portafoglio/ (personal data).

Phase 6C: the isolation list lives in app_env.isolate (the same one used by the preview), and the guard of app_env is
on for the whole test session: any write inside the project folder (diaries in data/, portafoglio/, cache/, reports/,
the catalogue...) and any non-local network connection fails BEFORE it happens, even if a path was not redirected."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_env  # noqa: E402

assert app_env.env() == "test"          # pytest is loaded: never production, whatever NDX_ENV says
app_env.install_guard()


@pytest.fixture(autouse=True)
def private_folder(tmp_path, monkeypatch):
    """portafoglio/, the diaries, the reports and the caches are replaced by temporary folders in every test."""
    app_env.isolate(tmp_path, monkeypatch.setattr)
    return tmp_path
