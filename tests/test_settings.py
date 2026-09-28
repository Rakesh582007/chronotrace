"""Optional settings read from .env as well as the environment."""

from backend import config, db


def test_database_url_comes_from_the_environment_then_dotenv(monkeypatch):
    monkeypatch.delenv("CHRONOTRACE_DB", raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: {"CHRONOTRACE_DB": "sqlite:///from-dotenv.db"})
    assert db.database_url() == "sqlite:///from-dotenv.db"
    monkeypatch.setenv("CHRONOTRACE_DB", "sqlite:///from-env.db")
    assert db.database_url() == "sqlite:///from-env.db"
    monkeypatch.delenv("CHRONOTRACE_DB")
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: {"CHRONOTRACE_DB": ""})
    assert db.database_url() == f"sqlite:///{db.DEFAULT_DB}"                  # empty: the demo file
    assert db.database_url("sqlite://") == "sqlite://"
