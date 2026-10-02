"""Transactional simulator state. Never reuse legacy global identity/agreements."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.simulator_store import SimulatorStore
from simple_agent.tool_timing import timed_phase
from simple_agent.services.boleto_store import SCHEMA, save_payments, second_copy


def validate_thread_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("server_thread_id_required")
    return value.strip()


def thread_id(runtime) -> str:
    value = runtime.config.get("configurable", {}).get("thread_id")
    return validate_thread_id(value)


def portfolio_context(runtime) -> tuple[int, str] | None:
    context = runtime.context if isinstance(runtime.context, dict) else {}
    value = context.get("portfolio_context")
    if not isinstance(value, dict):
        return None
    scope_id = value.get("scope_id")
    tenant_id = value.get("tenant_id")
    if isinstance(scope_id, str) and scope_id.isdigit():
        scope_id = int(scope_id)
    if type(scope_id) is not int or scope_id <= 0:
        raise ValueError("invalid_portfolio_scope")
    if not isinstance(tenant_id, str) or not tenant_id.strip() or len(tenant_id) > 200:
        raise ValueError("invalid_portfolio_tenant")
    return scope_id, tenant_id.strip()


class SessionStore:
    def __new__(cls, root: Path | None = None):
        backend = os.getenv("SESSION_BACKEND", "sqlite").strip().lower()
        if cls is SessionStore and root is None and backend == "postgres":
            from simple_agent.services.postgres_session_store import (
                PostgresSessionStore,
            )

            return PostgresSessionStore()
        if backend != "sqlite":
            raise ValueError("unsupported_session_backend")
        return super().__new__(cls)

    def __init__(self, root: Path | None = None):
        self.root = root or Path(os.getenv("SESSION_ROOT", "/data/sessions"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "sessions.sqlite3"
        with self._connect() as db, timed_phase("session_schema"):
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY,
                  data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tenants (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portfolios (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  creditor_name TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE(tenant_id, id),
                  FOREIGN KEY(tenant_id) REFERENCES tenants(id)
                );
                CREATE TABLE IF NOT EXISTS customers (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  full_name TEXT NOT NULL,
                  cpf TEXT NOT NULL,
                  phone TEXT NOT NULL,
                  birth_date TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE(tenant_id, id),
                  FOREIGN KEY(tenant_id) REFERENCES tenants(id)
                );
                CREATE TABLE IF NOT EXISTS debts (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  portfolio_id TEXT NOT NULL,
                  customer_id TEXT NOT NULL,
                  product TEXT NOT NULL,
                  current_amount TEXT NOT NULL,
                  days_overdue INTEGER NOT NULL,
                  data TEXT NOT NULL,
                  eligibility TEXT NOT NULL,
                  identity_policy TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE(tenant_id, id),
                  FOREIGN KEY(tenant_id, portfolio_id)
                    REFERENCES portfolios(tenant_id, id),
                  FOREIGN KEY(tenant_id, customer_id)
                    REFERENCES customers(tenant_id, id)
                );
                CREATE TABLE IF NOT EXISTS session_contexts (
                  session_id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  portfolio_id TEXT NOT NULL,
                  customer_id TEXT NOT NULL,
                  debt_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(session_id) REFERENCES sessions(id),
                  FOREIGN KEY(tenant_id, portfolio_id)
                    REFERENCES portfolios(tenant_id, id),
                  FOREIGN KEY(tenant_id, customer_id)
                    REFERENCES customers(tenant_id, id),
                  FOREIGN KEY(tenant_id, debt_id)
                    REFERENCES debts(tenant_id, id)
                );
                """
            )
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with timed_phase("session_connect"):
            db = sqlite3.connect(self.database, timeout=10)
        try:
            with db:
                journal = os.getenv("SESSION_SQLITE_JOURNAL_MODE", "").upper()
                synchronous = os.getenv("SESSION_SQLITE_SYNCHRONOUS", "").upper()
                if journal not in {"", "DELETE", "WAL"}:
                    raise ValueError("unsupported_sqlite_journal_mode")
                if synchronous not in {"", "FULL", "NORMAL"}:
                    raise ValueError("unsupported_sqlite_synchronous")
                if journal:
                    db.execute(f"PRAGMA journal_mode = {journal}")
                if synchronous:
                    db.execute(f"PRAGMA synchronous = {synchronous}")
                db.execute("PRAGMA foreign_keys = ON")
                yield db
                with timed_phase("session_commit"):
                    db.commit()
        finally:
            db.close()

    def read(self, key: str) -> dict:
        """Return a detached snapshot; initialize missing Playground state once.

        Existing sessions use a deferred read transaction for consistent fixture
        hydration, without reserving a writer or saving unchanged state.
        """
        key = validate_thread_id(key)
        with self._connect() as db:
            with timed_phase("session_read"):
                db.execute("BEGIN")
                row = db.execute(
                    "SELECT data FROM sessions WHERE id = ?", (key,)
                ).fetchone()
                if row:
                    state = self._state(db, key, row[0])
                    state.setdefault("payments", {})
                    state.setdefault("deliveries", {})
                    return state
        # Match transaction's existing initialization contract, after releasing
        # the read connection. transaction rechecks the row under its write lock.
        with self.transaction(key) as state:
            return state

    def exists(self, key: str) -> bool:
        key = validate_thread_id(key)
        with self._connect() as db:
            return (
                db.execute("SELECT 1 FROM sessions WHERE id = ?", (key,)).fetchone()
                is not None
            )

    @staticmethod
    def _fixture(db: sqlite3.Connection, key: str) -> dict | None:
        row = db.execute(
            """SELECT c.id,c.full_name,c.cpf,c.phone,c.birth_date,
                      p.creditor_name,d.product,d.data,d.eligibility,d.identity_policy
               FROM session_contexts s
               JOIN customers c ON (c.tenant_id,c.id)=(s.tenant_id,s.customer_id)
               JOIN portfolios p ON (p.tenant_id,p.id)=(s.tenant_id,s.portfolio_id)
               JOIN debts d ON (d.tenant_id,d.id)=(s.tenant_id,s.debt_id)
               WHERE s.session_id=?""",
            (key,),
        ).fetchone()
        if not row:
            return None
        fixture = {
            "customer_id": row[0],
            "full_name": row[1],
            "cpf": row[2],
            "phone": row[3],
            "birth_date": row[4],
            "institution": row[5],
            "creditor_name": row[5],
            "product": row[6],
            "debt": json.loads(row[7]),
            "eligibility": json.loads(row[8]),
            "identity_policy": json.loads(row[9]),
        }
        if fixture["debt"].get("company"):
            fixture["company"] = fixture["debt"]["company"]
        return fixture

    @classmethod
    def _state(cls, db: sqlite3.Connection, key: str, data: str) -> dict:
        state = json.loads(data)
        fixture = cls._fixture(db, key)
        if fixture:
            state["fixture"] = fixture
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
        """Create one form-backed session without changing the playground fixture."""
        key = validate_thread_id(key)
        state = {
            "identity_verified": False,
            "offers": {},
            "agreements": {},
            "payments": {},
            "deliveries": {},
            "receipts": {},
            "snapshot_id": PersistentOKFStore().active_bundle_id(),
        }
        if demo:
            state["demo_session"] = True
        else:
            state["fixture"] = fixture
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                previous = db.execute(
                    "SELECT data FROM sessions WHERE id=?", (key,)
                ).fetchone()
                if previous:
                    current = self._state(db, key, previous[0])
                    if (
                        demo
                        and current.get("demo_session") is True
                        and self._same_demo_input(current["fixture"], fixture)
                    ):
                        return False
                    if not demo and current.get("fixture") == fixture:
                        return False
                    raise ValueError("session_already_exists")
                db.execute(
                    "INSERT INTO sessions(id, data) VALUES (?, ?)",
                    (key, json.dumps(state)),
                )
                if demo:
                    now = datetime.now(timezone.utc).isoformat()
                    customer_id = str(fixture["customer_id"])
                    debt = dict(fixture["debt"])
                    if fixture.get("company"):
                        debt["company"] = fixture["company"]
                    debt_id = str(debt["debt_id"])
                    db.execute(
                        "INSERT INTO tenants(id,name,created_at) VALUES(?,?,?) "
                        "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
                        (tenant_id, tenant_name, now),
                    )
                    db.execute(
                        """INSERT INTO portfolios(id,tenant_id,name,creditor_name,created_at)
                           VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                           name=excluded.name,creditor_name=excluded.creditor_name""",
                        (
                            portfolio_id,
                            tenant_id,
                            portfolio_name,
                            fixture["creditor_name"],
                            now,
                        ),
                    )
                    db.execute(
                        """INSERT INTO customers(id,tenant_id,full_name,cpf,phone,birth_date,created_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (
                            customer_id,
                            tenant_id,
                            fixture["full_name"],
                            fixture["cpf"],
                            fixture["phone"],
                            fixture["birth_date"],
                            now,
                        ),
                    )
                    db.execute(
                        """INSERT INTO debts(id,tenant_id,portfolio_id,customer_id,product,
                           current_amount,days_overdue,data,eligibility,identity_policy,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            debt_id,
                            tenant_id,
                            portfolio_id,
                            customer_id,
                            fixture["product"],
                            debt["current_amount"],
                            int(debt.get("days_overdue", 0)),
                            json.dumps(debt),
                            json.dumps(fixture["eligibility"]),
                            json.dumps(fixture["identity_policy"]),
                            now,
                        ),
                    )
                    db.execute(
                        """INSERT INTO session_contexts(
                           session_id,tenant_id,portfolio_id,customer_id,debt_id,created_at
                           ) VALUES(?,?,?,?,?,?)""",
                        (key, tenant_id, portfolio_id, customer_id, debt_id, now),
                    )
        except sqlite3.IntegrityError as exc:
            raise ValueError("session_already_exists") from exc
        return True

    def ensure_unbound(self, key: str) -> bool:
        """Create a WhatsApp session with no customer or debt context."""
        key = validate_thread_id(key)
        state = {
            "unbound_session": True,
            "identity_verified": False,
            "offers": {},
            "agreements": {},
            "payments": {},
            "deliveries": {},
            "receipts": {},
            "snapshot_id": PersistentOKFStore().active_bundle_id(),
        }
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                previous = db.execute(
                    "SELECT data FROM sessions WHERE id=?", (key,)
                ).fetchone()
                if previous:
                    current = json.loads(previous[0])
                    if current.get("demo_session") or current.get("unbound_session"):
                        return False
                    raise ValueError("whatsapp_session_requires_reset")
                db.execute(
                    "INSERT INTO sessions(id,data) VALUES(?,?)",
                    (key, json.dumps(state)),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def ensure_portfolio(self, key: str, scope_id: int, tenant_id: str) -> bool:
        """Pin a Playground session to one portfolio without a global debtor fallback."""
        key = validate_thread_id(key)
        if type(scope_id) is not int or scope_id <= 0:
            raise ValueError("invalid_portfolio_scope")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("invalid_portfolio_tenant")
        tenant_id = tenant_id.strip()

        simulator = SimulatorStore.for_portfolio(scope_id)

        def fresh() -> dict:
            state = {
                "portfolio_scope_id": scope_id,
                "portfolio_tenant_id": tenant_id,
                "identity_verified": False,
                "offers": {},
                "agreements": {},
                "payments": {},
                "deliveries": {},
                "receipts": {},
                "snapshot_id": PersistentOKFStore().active_bundle_id(),
            }
            if simulator.exists():
                fixture = simulator.load()
                fixture.pop("_runtime", None)
                fixture.pop("identity_validated", None)
                state["fixture"] = fixture
            else:
                state["unbound_session"] = True
            return state

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT data FROM sessions WHERE id = ?", (key,)
            ).fetchone()
            if not row:
                db.execute(
                    "INSERT INTO sessions(id,data) VALUES(?,?)",
                    (key, json.dumps(fresh())),
                )
                return True

            state = self._state(db, key, row[0])
            current_scope = state.get("portfolio_scope_id")
            if current_scope is not None:
                if (
                    current_scope != scope_id
                    or state.get("portfolio_tenant_id") != tenant_id
                ):
                    raise ValueError("portfolio_scope_mismatch")
                return False

            # Legacy form-backed sessions are already pinned by session_contexts.
            if state.get("demo_session") is True:
                return False

            # Old Playground sessions were silently hydrated from the global fixture.
            # Replace only that tool state; LangGraph keeps the visible message history.
            db.execute(
                "UPDATE sessions SET data = ? WHERE id = ?",
                (json.dumps(fresh()), key),
            )
            return True

    def reset_demo(self, key: str) -> bool:
        """Reset an existing Demo session in place; never create or reset Playground."""
        key = validate_thread_id(key)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT data FROM sessions WHERE id = ?", (key,)
            ).fetchone()
            if not row:
                return False
            state = self._state(db, key, row[0])
            if state.get("demo_session") is not True:
                return False
            # Preserve reset semantics: delete only this demo's generated records.
            db.execute(
                "DELETE FROM payment_agreements WHERE origin_session_id=?",
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
            if self._fixture(db, key):
                reset.pop("fixture")
            db.execute(
                "UPDATE sessions SET data = ? WHERE id = ?",
                (json.dumps(reset), key),
            )
        return True

    @contextmanager
    def transaction(
        self, key: str, *, persist_payments: bool = False
    ) -> Iterator[dict]:
        key = validate_thread_id(key)
        # One Railway replica: serialize short state changes, never LLM calls.
        with self._connect() as db:
            with timed_phase("session_write_wait"):
                db.execute("BEGIN IMMEDIATE")
            with timed_phase("session_load"):
                row = db.execute(
                    "SELECT data FROM sessions WHERE id = ?", (key,)
                ).fetchone()
                if row:
                    state = self._state(db, key, row[0])
                else:
                    fixture = SimulatorStore().load()
                    fixture.pop("_runtime", None)
                    fixture.pop("identity_validated", None)
                    state = {
                        "fixture": fixture,
                        "identity_verified": False,
                        "offers": {},
                        "agreements": {},
                        "payments": {},
                        "deliveries": {},
                        "receipts": {},
                        "snapshot_id": PersistentOKFStore().active_bundle_id(),
                    }
                state.setdefault("payments", {})
                state.setdefault("deliveries", {})
            with timed_phase("session_body"):
                yield state
            with timed_phase("session_save"):
                stored = dict(state)
                if self._fixture(db, key):
                    stored.pop("fixture", None)
                db.execute(
                    "INSERT INTO sessions(id, data) VALUES (?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                    (key, json.dumps(stored)),
                )
                if persist_payments:
                    save_payments(db, key, state)

    def boleto_second_copy(
        self, key: str, agreement_id: str = "", installment_number: int | None = None
    ) -> dict:
        key = validate_thread_id(key)
        with self._connect() as db:
            db.execute("BEGIN")
            return second_copy(db, key, agreement_id, installment_number)


def latest_user_message(runtime) -> tuple[str, str]:
    for message in reversed(runtime.state.get("messages", [])):
        if getattr(message, "type", None) == "human":
            content = message.content
            if isinstance(content, list):
                content = " ".join(
                    x.get("text", "")
                    for x in content
                    if isinstance(x, dict) and x.get("type") == "text"
                )
            return str(message.id or ""), str(content)
    return "", ""
