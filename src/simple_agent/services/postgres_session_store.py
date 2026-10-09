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
from simple_agent.services.boleto_store import second_copy_result
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

    def ensure_portfolio(
        self, key: str, scope_id: int, tenant_id: str, snapshot_id: str | None = ""
    ) -> bool:
        """Pin a Playground session without falling back to the global fixture."""
        key = validate_thread_id(key)
        if type(scope_id) is not int or scope_id <= 0:
            raise ValueError("invalid_portfolio_scope")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("invalid_portfolio_tenant")
        tenant_id = tenant_id.strip()

        def fresh() -> dict:
            state = self._initial_state()
            if snapshot_id != "":
                state["snapshot_id"] = snapshot_id
            state["portfolio_scope_id"] = scope_id
            state["portfolio_tenant_id"] = tenant_id
            simulator = SimulatorStore.for_portfolio(scope_id)
            if simulator.exists():
                fixture = simulator.load()
                fixture.pop("_runtime", None)
                fixture.pop("identity_validated", None)
                state["fixture"] = fixture
            else:
                state["unbound_session"] = True
            return state

        with self.pool.connection() as db, db.transaction():
            row = db.execute(
                "SELECT state FROM runtime.sessions WHERE id=%s FOR UPDATE", (key,)
            ).fetchone()
            if not row:
                state = fresh()
                created = db.execute(
                    """INSERT INTO runtime.sessions(
                           id,tenant_id,portfolio_id,customer_id,debt_id,state
                       ) VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(id) DO NOTHING RETURNING id""",
                    (
                        key,
                        tenant_id,
                        str(scope_id),
                        state.get("fixture", {}).get("customer_id"),
                        state.get("fixture", {}).get("debt", {}).get("debt_id"),
                        Jsonb(state),
                    ),
                ).fetchone()
                if created:
                    return True
                row = db.execute(
                    "SELECT state FROM runtime.sessions WHERE id=%s FOR UPDATE", (key,)
                ).fetchone()
            current = self._state(row[0])
            if current.get("portfolio_scope_id") is not None:
                if (
                    current["portfolio_scope_id"] != scope_id
                    or current.get("portfolio_tenant_id") != tenant_id
                ):
                    raise ValueError("portfolio_scope_mismatch")
                return False
            if current.get("demo_session") is True:
                return False
            state = fresh()
            db.execute(
                """UPDATE runtime.sessions SET
                       tenant_id=%s,portfolio_id=%s,customer_id=%s,debt_id=%s,
                       state=%s,version=version+1,updated_at=now()
                   WHERE id=%s""",
                (
                    tenant_id,
                    str(scope_id),
                    state.get("fixture", {}).get("customer_id"),
                    state.get("fixture", {}).get("debt", {}).get("debt_id"),
                    Jsonb(state),
                    key,
                ),
            )
            return True

    def reset_demo(self, key: str) -> bool:
        key = validate_thread_id(key)
        with self.pool.connection() as db, db.transaction():
            row = db.execute(
                "SELECT state FROM runtime.sessions WHERE id = %s FOR UPDATE", (key,)
            ).fetchone()
            if not row or row[0].get("demo_session") is not True:
                return False
            state = self._state(row[0])
            db.execute(
                "DELETE FROM runtime.payment_agreements WHERE origin_session_id=%s",
                (key,),
            )
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
                if persist_payments:
                    self._save_payments(db, key, state)

    @staticmethod
    def _save_payments(db, key: str, state: dict) -> None:
        for agreement in state.get("agreements", {}).values():
            saved = db.execute(
                """INSERT INTO runtime.payment_agreements(
                       agreement_id,origin_session_id,data
                   ) VALUES (%s,%s,%s)
                   ON CONFLICT (agreement_id) DO UPDATE SET
                     data=excluded.data,updated_at=now()
                   WHERE runtime.payment_agreements.origin_session_id=
                         excluded.origin_session_id
                   RETURNING agreement_id""",
                (agreement["agreement_id"], key, Jsonb(agreement)),
            ).fetchone()
            if not saved:
                raise ValueError("agreement_origin_mismatch")
        for payment in state.get("payments", {}).values():
            owner = db.execute(
                """SELECT origin_session_id FROM runtime.payment_agreements
                   WHERE agreement_id=%s""",
                (payment["agreement_id"],),
            ).fetchone()
            if not owner or owner[0] != key:
                raise ValueError("payment_origin_mismatch")
            saved = db.execute(
                """INSERT INTO runtime.payment_instructions(
                       payment_id,agreement_id,method,installment_number,data
                   ) VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (payment_id) DO UPDATE SET
                     data=excluded.data,updated_at=now()
                   WHERE runtime.payment_instructions.agreement_id=
                         excluded.agreement_id
                     AND runtime.payment_instructions.method=excluded.method
                     AND runtime.payment_instructions.installment_number=
                         excluded.installment_number
                   RETURNING payment_id""",
                (
                    payment["payment_id"],
                    payment["agreement_id"],
                    payment["method"],
                    payment["installment_number"],
                    Jsonb(payment),
                ),
            ).fetchone()
            if not saved:
                raise ValueError("payment_origin_mismatch")

    def boleto_second_copy(
        self, key: str, agreement_id: str = "", installment_number: int | None = None
    ) -> dict:
        key = validate_thread_id(key)
        with self.pool.connection() as db, db.transaction():
            session = db.execute(
                """SELECT state,tenant_id,portfolio_id,customer_id,debt_id
                   FROM runtime.sessions WHERE id=%s FOR SHARE""",
                (key,),
            ).fetchone()
            if not session or session[0].get("identity_verified") is not True:
                return {"found": False, "reason": "identity_verification_required"}
            context = session[1:]
            if all(context):
                rows = db.execute(
                    """SELECT a.data FROM runtime.payment_agreements a
                       JOIN runtime.sessions s ON s.id=a.origin_session_id
                       WHERE (s.tenant_id,s.portfolio_id,s.customer_id,s.debt_id)=
                             (%s,%s,%s,%s)
                         AND (%s='' OR a.agreement_id=%s)
                       ORDER BY a.agreement_id LIMIT 21 FOR SHARE OF s""",
                    (*context, agreement_id, agreement_id),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT data FROM runtime.payment_agreements
                       WHERE origin_session_id=%s
                         AND (%s='' OR agreement_id=%s)
                       ORDER BY agreement_id LIMIT 21""",
                    (key, agreement_id, agreement_id),
                ).fetchall()
            agreements = [row[0] for row in rows]
            payments = []
            if len(agreements) == 1:
                payments = [
                    row[0]
                    for row in db.execute(
                        """SELECT data FROM runtime.payment_instructions
                           WHERE agreement_id=%s AND method='boleto'
                             AND (%s::integer IS NULL OR installment_number=%s)
                           ORDER BY installment_number LIMIT 21""",
                        (
                            agreements[0]["agreement_id"],
                            installment_number,
                            installment_number,
                        ),
                    ).fetchall()
                ]
            return second_copy_result(agreements, payments)
