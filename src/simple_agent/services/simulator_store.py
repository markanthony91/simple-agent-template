from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from simple_agent.services.simulator_schema import normalize_fixture


DEFAULT_FIXTURE: dict[str, Any] = {
    "customer_id": "CUS-001",
    "full_name": "João da Silva",
    "cpf": "12345678900",
    "birth_date": "1985-04-17",
    "identity_validated": False,
    "institution": "FastPay",
    "product": "cartao_de_credito",
    "debt": {
        "debt_id": "DEBT-001",
        "contract_id": "CTR-93821",
        "original_amount": "5000.00",
        "current_amount": "5873.42",
        "due_date": "2026-04-10",
        "status": "overdue",
    },
    "eligibility": {
        "can_negotiate": True,
        "max_installments": 10,
        "max_discount_percentage": "20",
    },
}


class SimulatorStore:
    """Persistent fixture used only by the debt-collection simulator tools."""

    def __init__(self, root: Path | None = None):
        configured = os.getenv("SIMULATOR_ROOT", "/data/simulator")
        self.root = (root or Path(configured)).resolve()
        self.file = self.root / "customer.json"
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.file.exists():
            self.save(DEFAULT_FIXTURE)

    def _write_atomic(self, payload: dict[str, Any]) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix="customer", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.file)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("simulator_fixture_unavailable") from exc
        return normalize_fixture(payload)

    def save(self, fixture: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(fixture, dict):
            raise ValueError("fixture must be an object")
        payload = normalize_fixture(fixture)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_atomic(payload)
        return payload

    def days_overdue(self, due_date: str | None) -> int | None:
        if not due_date:
            return None
        try:
            due = date.fromisoformat(due_date)
        except ValueError:
            return None
        return max(0, (datetime.now(timezone.utc).date() - due).days)
