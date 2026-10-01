"""PostgreSQL adapter contract against a dedicated local test database only."""

import os
from pathlib import Path

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from simple_agent.services.postgres_session_store import PostgresSessionStore


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def store():
    dsn = os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for the isolated integration test")
    with psycopg.connect(dsn) as db:
        if db.info.dbname != "pg_adapter_test":
            raise ValueError("test_database_must_be_pg_adapter_test")
        for name in (
            "001_postgres_session_okf.sql",
            "002_postgres_payments.sql",
            "003_sqlite_catalog.sql",
        ):
            db.execute((ROOT / "migrations" / name).read_text())
    adapter = PostgresSessionStore.__new__(PostgresSessionStore)
    adapter.pool = ConnectionPool(dsn, min_size=1, max_size=2, open=True)
    yield adapter
    adapter.pool.close()


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("OKF_DATA_ROOT", str(tmp_path / "okf"))
    return {
        "customer_id": "pg-test-customer",
        "full_name": "Cliente de Teste",
        "cpf": "12345678900",
        "phone": "+5511900000000",
        "birth_date": "2000-01-01",
        "institution": "Will Bank",
        "creditor_name": "Will Bank",
        "product": "cartao_de_credito",
        "debt": {
            "debt_id": "pg-test-debt",
            "contract_id": "pg-test-contract",
            "current_amount": "850.00",
            "days_overdue": 42,
            "status": "overdue",
        },
        "eligibility": {"can_negotiate": True, "max_installments": 10},
        "identity_policy": {"cpf_mode": "first3", "max_attempts": 3},
    }


def test_demo_catalog_hydration_payment_lookup_and_reset(store, fixture):
    assert store.create(
        "pg-test-origin",
        fixture,
        demo=True,
        tenant_id="pg-test-tenant",
        portfolio_id="pg-test-portfolio",
        tenant_name="Test Tenant",
        portfolio_name="Test Portfolio",
    )
    with store.pool.connection() as db:
        raw = db.execute(
            "SELECT state FROM runtime.sessions WHERE id=%s", ("pg-test-origin",)
        ).fetchone()[0]
        assert "fixture" not in raw
        assert (
            db.execute(
                "SELECT count(*) FROM runtime.session_contexts WHERE session_id=%s",
                ("pg-test-origin",),
            ).fetchone()[0]
            == 1
        )
    assert store.read("pg-test-origin")["fixture"] == fixture
    assert not store.create(
        "pg-test-origin",
        fixture,
        demo=True,
        tenant_id="pg-test-tenant",
        portfolio_id="pg-test-portfolio",
    )
    with pytest.raises(ValueError, match="session_already_exists"):
        changed = {**fixture, "debt": {**fixture["debt"], "current_amount": "851.00"}}
        store.create(
            "pg-test-origin",
            changed,
            demo=True,
            tenant_id="pg-test-tenant",
            portfolio_id="pg-test-portfolio",
        )

    agreement = {
        "agreement_id": "pg-test-agreement",
        "status": "created",
        "installments": 1,
        "is_simulation": True,
    }
    payment = {
        "payment_id": "pg-test-payment",
        "agreement_id": "pg-test-agreement",
        "method": "boleto",
        "installment_number": 1,
        "amount": "850.00",
        "status": "pending",
        "payment_code": "DUMMY-TEST",
        "is_simulation": True,
    }
    with store.transaction("pg-test-origin", persist_payments=True) as state:
        state["identity_verified"] = True
        state["agreements"][agreement["agreement_id"]] = agreement
        state["payments"][payment["payment_id"]] = payment
    assert (
        store.boleto_second_copy("pg-test-origin")["payment"]["payment_code"]
        == "DUMMY-TEST"
    )
    with store.pool.connection() as db:
        assert (
            "fixture"
            not in db.execute(
                "SELECT state FROM runtime.sessions WHERE id=%s", ("pg-test-origin",)
            ).fetchone()[0]
        )

    assert store.ensure_unbound("pg-test-bound")
    with store.pool.connection() as db:
        db.execute(
            """INSERT INTO runtime.session_contexts
               SELECT %s,tenant_id,portfolio_id,customer_id,debt_id,now()
               FROM runtime.session_contexts WHERE session_id=%s""",
            ("pg-test-bound", "pg-test-origin"),
        )
    with store.transaction("pg-test-bound") as state:
        state["identity_verified"] = True
    assert store.boleto_second_copy("pg-test-bound")["found"] is True
    assert store.reset_demo("pg-test-origin")
    assert store.read("pg-test-origin")["fixture"] == fixture
    assert store.read("pg-test-origin")["identity_verified"] is False
    assert store.boleto_second_copy("pg-test-bound")["reason"] == "boleto_not_found"
    with store.pool.connection() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM runtime.payment_instructions WHERE payment_id=%s",
                ("pg-test-payment",),
            ).fetchone()[0]
            == 0
        )


def test_duplicate_customer_and_cross_tenant_portfolio_roll_back(store, fixture):
    with pytest.raises(ValueError, match="session_already_exists"):
        store.create(
            "pg-test-duplicate",
            fixture,
            demo=True,
            tenant_id="pg-test-tenant",
            portfolio_id="pg-test-portfolio",
        )
    with pytest.raises(ValueError, match="portfolio_tenant_mismatch"):
        store.create(
            "pg-test-other-tenant",
            {
                **fixture,
                "customer_id": "pg-test-other-customer",
                "debt": {**fixture["debt"], "debt_id": "pg-test-other-debt"},
            },
            demo=True,
            tenant_id="pg-test-other-tenant",
            portfolio_id="pg-test-portfolio",
        )
    with store.pool.connection() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM runtime.sessions WHERE id IN (%s,%s)",
                ("pg-test-duplicate", "pg-test-other-tenant"),
            ).fetchone()[0]
            == 0
        )


def test_playground_and_unbound_sessions_remain_unlinked(store, fixture):
    assert store.create("pg-test-playground", fixture)
    assert store.ensure_unbound("pg-test-whatsapp")
    with store.pool.connection() as db:
        rows = db.execute(
            """SELECT id,tenant_id,portfolio_id,customer_id,debt_id
               FROM runtime.sessions WHERE id IN (%s,%s) ORDER BY id""",
            ("pg-test-playground", "pg-test-whatsapp"),
        ).fetchall()
        assert all(row[1:] == (None, None, None, None) for row in rows)
    assert store.read("pg-test-playground")["fixture"] == fixture
    assert "fixture" not in store.read("pg-test-whatsapp")
    assert (
        store.boleto_second_copy("pg-test-playground")["reason"]
        == "identity_verification_required"
    )
