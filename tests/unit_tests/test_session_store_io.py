import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from simple_agent.services.session_store import SessionStore


def test_connections_close_on_success_and_rollback(isolated, monkeypatch):
    connect = sqlite3.connect
    connections = []

    def tracked(*args, **kwargs):
        db = connect(*args, **kwargs)
        connections.append(db)
        return db

    monkeypatch.setattr(sqlite3, "connect", tracked)
    store = SessionStore()
    store.read("a")
    assert store.exists("a")
    with store.transaction("a") as state:
        state["identity_verified"] = True
    with pytest.raises(ValueError, match="rollback"):
        with store.transaction("a") as state:
            state["identity_verified"] = False
            raise ValueError("rollback")
    assert store.read("a")["identity_verified"] is True
    for db in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            db.execute("SELECT 1")


def test_existing_read_never_updates_or_reserves_writer(isolated, monkeypatch):
    store = SessionStore()
    original = store.read("a")
    statements = []
    connect = sqlite3.connect

    def traced(*args, **kwargs):
        db = connect(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(sqlite3, "connect", traced)
    snapshot = store.read("a")
    snapshot["identity_verified"] = True
    snapshot["payments"]["synthetic"] = {}
    assert store.read("a") == original
    assert not any(
        sql.lstrip()
        .upper()
        .startswith(("INSERT", "UPDATE", "DELETE", "BEGIN IMMEDIATE"))
        for sql in statements
    )


def test_new_store_can_read_while_another_session_has_writer(isolated):
    store = SessionStore()
    store.read("a")
    store.read("b")
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.transaction("a") as state:
            state["identity_verified"] = True
            # Both __init__ and read must avoid requesting the writer lock.
            future = pool.submit(lambda: SessionStore().read("b"))
            assert future.result(timeout=2)["identity_verified"] is False
    assert store.read("a")["identity_verified"] is True


def test_first_read_preserves_initialization_and_snapshot(isolated):
    store = SessionStore()
    assert not store.exists("new")
    first = store.read("new")
    assert first["identity_verified"] is False
    assert store.exists("new")
    assert store.read("new") == first
    with pytest.raises(ValueError, match="server_thread_id_required"):
        store.read("")
