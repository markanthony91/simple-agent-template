"""PostgreSQL canary backend for durable session and OKF receipt state."""

from __future__ import annotations

import copy
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from typing import Iterator

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.session_store import validate_thread_id
from simple_agent.services.simulator_store import SimulatorStore
from simple_agent.tool_timing import timed_phase


@lru_cache(maxsize=4)
def _pool(dsn: str) -> ConnectionPool:
    size = int(os.getenv("SESSION_DATABASE_POOL_SIZE", "5"))
    return ConnectionPool(dsn, min_size=1, max_size=size, open=True)


class PostgresSessionStore:
    def __init__(self):
        dsn = os.getenv("SESSION_DATABASE_URL", "").strip()
        if not dsn:
            raise ValueError("SESSION_DATABASE_URL_required")
        self.pool = _pool(dsn)

    @staticmethod
    def _initial_state(*, fixture: dict | None = None, demo: bool = False) -> dict:
        state = {
            "identity_verified": False,
            "offers": {},
            "agreements": {},
            "payments": {},
            "deliveries": {},
            "receipts": {},
            "snapshot_id": PersistentOKFStore().active_bundle_id(),
        }
        if fixture is not None:
            state["fixture"] = fixture
        if demo:
            state["demo_session"] = True
        return state

    @staticmethod
    def _same_demo_input(current: dict, candidate: dict) -> bool:
        return all(
            current.get(field) == candidate.get(field)
            for field in ("full_name", "cpf", "phone")
        ) and all(
            current.get("debt", {}).get(field) == candidate.get("debt", {}).get(field)
            for field in ("current_amount", "days_overdue")
        )

    @staticmethod
    def _state(value: dict) -> dict:
        state = copy.deepcopy(value)
        state.setdefault("payments", {})
        state.setdefault("deliveries", {})
        state.setdefault("receipts", {})
        return state

    def read(self, key: str) -> dict:
        key = validate_thread_id(key)
        with self.pool.connection() as db, timed_phase("session_read"):
            row = db.execute(
                "SELECT state FROM runtime.sessions WHERE id = %s", (key,)
            ).fetchone()
        if row:
            return self._state(row[0])
        with self.transaction(key) as state:
            return copy.deepcopy(state)

    def exists(self, key: str) -> bool:
        key = validate_thread_id(key)
        with self.pool.connection() as db:
            return (
                db.execute(
                    "SELECT 1 FROM runtime.sessions WHERE id = %s", (key,)
                ).fetchone()
                is not None
            )

    def create(
        self,
        key: str,
        fixture: dict,
        *,
        demo: bool = False,
        tenant_id: str = "willbank-visualizer",
        portfolio_id: str = "demo",
        tenant_name: str = "Will Bank Visualizer",
        portfolio_name: str = "Demonstração",
    ) -> bool:
        del tenant_name, portfolio_name
        key = validate_thread_id(key)
        state = self._initial_state(fixture=fixture, demo=demo)
        debt = fixture.get("debt", {})
        with self.pool.connection() as db, db.transaction():
            created = db.execute(
                """INSERT INTO runtime.sessions(
                       id,tenant_id,portfolio_id,customer_id,debt_id,state
                   ) VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO NOTHING RETURNING id""",
                (
                    key,
                    tenant_id if demo else None,
                    portfolio_id if demo else None,
                    str(fixture.get("customer_id") or "") or None,
                    str(debt.get("debt_id") or "") or None,
                    Jsonb(state),
                ),
            ).fetchone()
            if created:
                return True
            current = self._state(
                db.execute(
                    "SELECT state FROM runtime.sessions WHERE id = %s FOR UPDATE",
                    (key,),
                ).fetchone()[0]
            )
            if (
                demo
                and current.get("demo_session") is True
                and self._same_demo_input(current["fixture"], fixture)
            ):
                return False
            if not demo and current.get("fixture") == fixture:
                return False
            raise ValueError("session_already_exists")

    def ensure_unbound(self, key: str) -> bool:
        key = validate_thread_id(key)
        state = self._initial_state()
        state["unbound_session"] = True
        with self.pool.connection() as db, db.transaction():
            created = db.execute(
                """INSERT INTO runtime.sessions(id,state) VALUES (%s,%s)
                   ON CONFLICT (id) DO NOTHING RETURNING id""",
                (key, Jsonb(state)),
            ).fetchone()
            if created:
                return True
            current = db.execute(
                "SELECT state FROM runtime.sessions WHERE id = %s FOR UPDATE", (key,)
            ).fetchone()[0]
            if current.get("demo_session") or current.get("unbound_session"):
                return False
            raise ValueError("whatsapp_session_requires_reset")

    def reset_demo(self, key: str) -> bool:
        key = validate_thread_id(key)
        with self.pool.connection() as db, db.transaction():
            row = db.execute(
                "SELECT state FROM runtime.sessions WHERE id = %s FOR UPDATE", (key,)
            ).fetchone()
            if not row or row[0].get("demo_session") is not True:
                return False
            state = self._state(row[0])
            reset = {
                "fixture": state["fixture"],
                "identity_verified": False,
                "offers": {},
                "agreements": {},
                "payments": {},
                "deliveries": {},
                "receipts": {},
                "snapshot_id": state["snapshot_id"],
                "demo_session": True,
                "reset_count": int(state.get("reset_count", 0)) + 1,
                "last_reset_at": datetime.now(timezone.utc).isoformat(),
            }
            db.execute(
                """UPDATE runtime.sessions
                   SET state=%s,version=version+1,updated_at=now() WHERE id=%s""",
                (Jsonb(reset), key),
            )
            db.execute("DELETE FROM okf.receipts WHERE session_id=%s", (key,))
        return True

    @contextmanager
    def transaction(
        self, key: str, *, persist_payments: bool = False
    ) -> Iterator[dict]:
        if persist_payments:
            raise RuntimeError("postgres_payment_persistence_not_enabled")
        key = validate_thread_id(key)
        with self.pool.connection() as db, db.transaction():
            with timed_phase("session_write_wait"):
                row = db.execute(
                    "SELECT state FROM runtime.sessions WHERE id = %s FOR UPDATE",
                    (key,),
                ).fetchone()
            with timed_phase("session_load"):
                if row:
                    state = self._state(row[0])
                else:
                    fixture = SimulatorStore().load()
                    fixture.pop("_runtime", None)
                    fixture.pop("identity_validated", None)
                    state = self._initial_state(fixture=fixture)
                original_receipts = copy.deepcopy(state["receipts"])
            with timed_phase("session_body"):
                yield state
            with timed_phase("session_save"):
                db.execute(
                    """INSERT INTO runtime.sessions(id,state) VALUES (%s,%s)
                       ON CONFLICT (id) DO UPDATE SET
                         state=excluded.state,
                         version=runtime.sessions.version+1,
                         updated_at=now()""",
                    (key, Jsonb(state)),
                )
                if state["receipts"] != original_receipts:
                    db.execute("DELETE FROM okf.receipts WHERE session_id=%s", (key,))
                    with db.cursor() as cursor:
                        cursor.executemany(
                            """INSERT INTO okf.receipts(
                                   session_id,snapshot_id,path,content_hash
                               ) VALUES (%s,%s,%s,%s)""",
                            [
                                (key, receipt["snapshot_id"], path, receipt["hash"])
                                for path, receipt in state["receipts"].items()
                            ],
                        )

    def boleto_second_copy(
        self, key: str, agreement_id: str = "", installment_number: int | None = None
    ) -> dict:
        del key, agreement_id, installment_number
        raise RuntimeError("postgres_payment_persistence_not_enabled")
