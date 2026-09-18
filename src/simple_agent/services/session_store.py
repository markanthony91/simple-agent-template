"""Transactional simulator state. Never reuse legacy global identity/agreements."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.simulator_store import SimulatorStore


def validate_thread_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("server_thread_id_required")
    return value.strip()


def thread_id(runtime) -> str:
    value = runtime.config.get("configurable", {}).get("thread_id")
    return validate_thread_id(value)


class SessionStore:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(os.getenv("SESSION_ROOT", "/data/sessions"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "sessions.sqlite3"
        with sqlite3.connect(self.database) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
            )

    def create(self, key: str, fixture: dict) -> None:
        """Create one form-backed session without changing the playground fixture."""
        key = validate_thread_id(key)
        state = {
            "fixture": fixture,
            "identity_verified": False,
            "offers": {},
            "agreements": {},
            "receipts": {},
            "snapshot_id": PersistentOKFStore().active_bundle_id(),
        }
        try:
            with sqlite3.connect(self.database, timeout=10) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO sessions(id, data) VALUES (?, ?)",
                    (key, json.dumps(state)),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("session_already_exists") from exc

    @contextmanager
    def transaction(self, key: str) -> Iterator[dict]:
        # One Railway replica: serialize short state changes, never LLM calls.
        with sqlite3.connect(self.database, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT data FROM sessions WHERE id = ?", (key,)
            ).fetchone()
            if row:
                state = json.loads(row[0])
            else:
                fixture = SimulatorStore().load()
                fixture.pop("_runtime", None)
                fixture.pop("identity_validated", None)
                state = {
                    "fixture": fixture,
                    "identity_verified": False,
                    "offers": {},
                    "agreements": {},
                    "receipts": {},
                    "snapshot_id": PersistentOKFStore().active_bundle_id(),
                }
            yield state
            db.execute(
                "INSERT INTO sessions(id, data) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (key, json.dumps(state)),
            )


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
