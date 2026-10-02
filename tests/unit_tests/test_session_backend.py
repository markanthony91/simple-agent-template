from pathlib import Path

import pytest

from simple_agent.services.session_store import SessionStore


def test_sqlite_remains_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SESSION_BACKEND", raising=False)
    assert SessionStore(tmp_path).database == Path(tmp_path) / "sessions.sqlite3"


def test_postgres_requires_explicit_dsn(monkeypatch):
    monkeypatch.setenv("SESSION_BACKEND", "postgres")
    monkeypatch.delenv("SESSION_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="SESSION_DATABASE_URL_required"):
        SessionStore()


def test_unknown_backend_fails_closed(monkeypatch):
    monkeypatch.setenv("SESSION_BACKEND", "redis")
    with pytest.raises(ValueError, match="unsupported_session_backend"):
        SessionStore()
