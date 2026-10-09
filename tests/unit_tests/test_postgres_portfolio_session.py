from contextlib import nullcontext

import pytest

from simple_agent.services import postgres_session_store as module


class FakeDB:
    def __init__(self):
        self.row = None

    def transaction(self):
        return nullcontext()

    def execute(self, sql, args):
        if sql.startswith("SELECT state FROM runtime.sessions"):
            return Result((self.row["state"],) if self.row else None)
        if sql.startswith("INSERT INTO runtime.sessions"):
            if self.row:
                return Result(None)
            self.row = {
                "tenant_id": args[1],
                "portfolio_id": args[2],
                "customer_id": args[3],
                "debt_id": args[4],
                "state": args[5].obj,
            }
            return Result((args[0],))
        if sql.startswith("UPDATE runtime.sessions"):
            self.row = {
                "tenant_id": args[0],
                "portfolio_id": args[1],
                "customer_id": args[2],
                "debt_id": args[3],
                "state": args[4].obj,
            }
            return Result(None)
        raise AssertionError(sql)


class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


def test_postgres_portfolio_session_is_scoped_and_never_uses_global_fixture(
    monkeypatch,
):
    db = FakeDB()

    class Pool:
        def connection(self):
            return nullcontext(db)

    class Simulator:
        def __init__(self, exists=False):
            self.present = exists

        def exists(self):
            return self.present

        def load(self):
            return {
                "customer_id": "customer-2",
                "identity_validated": True,
                "debt": {"debt_id": "debt-2"},
            }

    simulator = Simulator()
    monkeypatch.setenv("SESSION_DATABASE_URL", "postgresql://synthetic")
    monkeypatch.setattr(module, "_pool", lambda _dsn: Pool())
    monkeypatch.setattr(
        module.PersistentOKFStore, "active_bundle_id", lambda _self: "snapshot"
    )
    monkeypatch.setattr(
        module.SimulatorStore, "for_portfolio", lambda _scope: simulator
    )
    store = module.PostgresSessionStore()

    assert store.ensure_portfolio("thread-1", 2, " tenant-2 ") is True
    assert db.row["state"]["unbound_session"] is True
    assert "fixture" not in db.row["state"]
    assert db.row["portfolio_id"] == "2"
    assert store.ensure_portfolio("thread-1", 2, "tenant-2") is False

    original = db.row
    db.row = None
    assert (
        store.ensure_portfolio(
            "thread-2", 2, "tenant-2", snapshot_id="portfolio-release"
        )
        is True
    )
    assert db.row["state"]["snapshot_id"] == "portfolio-release"
    db.row = None
    assert store.ensure_portfolio("thread-3", 2, "tenant-2", snapshot_id=None) is True
    assert db.row["state"]["snapshot_id"] is None
    db.row = original
    with pytest.raises(ValueError, match="portfolio_scope_mismatch"):
        store.ensure_portfolio("thread-1", 3, "tenant-2")

    simulator.present = True
    db.row["state"] = {"fixture": {"customer_id": "global"}, "identity_verified": True}
    assert store.ensure_portfolio("thread-1", 2, "tenant-2") is True
    assert db.row["state"]["fixture"]["customer_id"] == "customer-2"
    assert "identity_validated" not in db.row["state"]["fixture"]
    assert db.row["state"]["identity_verified"] is False
    assert (db.row["customer_id"], db.row["debt_id"]) == ("customer-2", "debt-2")

    db.row["state"] = {"demo_session": True}
    assert store.ensure_portfolio("thread-1", 2, "tenant-2") is False
    assert db.row["state"] == {"demo_session": True}
