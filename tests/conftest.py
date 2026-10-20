import pytest

from app import main


@pytest.fixture(autouse=True)
def disable_database_startup(monkeypatch):
    monkeypatch.setattr(main, "init_db", lambda: None)
