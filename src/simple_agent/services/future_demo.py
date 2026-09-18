"""Create one isolated demo session from the future form."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Callable
from uuid import uuid4

from pydantic import BaseModel, Field, StrictInt, ValidationError, field_validator

from simple_agent.services.session_store import SessionStore, validate_thread_id
from simple_agent.services.simulator_schema import normalize_fixture
from simple_agent.services.simulator_store import SimulatorStore


def _digits(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def _valid_cpf(value: str) -> bool:
    digits = _digits(value)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(
            int(digit) * (size + 1 - index) for index, digit in enumerate(digits[:size])
        )
        check = (total * 10 % 11) % 10
        if check != int(digits[size]):
            return False
    return True


class FutureDemoForm(BaseModel):
    full_name: Annotated[str, Field(min_length=3, max_length=120)]
    cpf: str
    phone: Annotated[str, Field(pattern=r"^\+55\d{11}$")]
    amount: Annotated[Decimal, Field(gt=0, le=10_000_000, allow_inf_nan=False)]
    days_overdue: Annotated[StrictInt, Field(ge=0, le=3650)]

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("invalid_full_name")
        return cleaned

    @field_validator("cpf")
    @classmethod
    def valid_cpf(cls, value: str) -> str:
        if not _valid_cpf(value):
            raise ValueError("invalid_cpf")
        return _digits(value)

    @field_validator("amount")
    @classmethod
    def valid_amount_precision(cls, value: Decimal) -> Decimal:
        if value.as_tuple().exponent < -2:
            raise ValueError("invalid_amount_precision")
        return value


def channel_creditor() -> str:
    base = (
        (
            os.getenv("CHANNEL_CONSOLE_URL")
            or os.getenv("RAILWAY_SERVICE_ZERAI_CHANNEL_CONSOLE_URL")
            or ""
        )
        .strip()
        .rstrip("/")
    )
    token = os.getenv("CHANNEL_CONSOLE_ENGINE_TOKEN", "").strip()
    if not base or not token:
        raise ValueError("channel_catalog_not_configured")
    if "://" not in base:
        base = ("http://" if base.endswith(".railway.internal") else "https://") + base
    request = urllib.request.Request(
        f"{base}/api/engine/v1/channels",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.HTTPError) as exc:
        raise ValueError("channel_catalog_unavailable") from exc
    creditor = (
        str(payload.get("creditor_name") or "").strip()
        if isinstance(payload, dict)
        else ""
    )
    if not creditor or len(creditor) > 120:
        raise ValueError("channel_creditor_invalid")
    return creditor


def create_future_demo_session(
    thread: str,
    raw_form: dict,
    *,
    creditor_loader: Callable[[], str] = channel_creditor,
    session_store: SessionStore | None = None,
    simulator_store: SimulatorStore | None = None,
) -> dict:
    thread = validate_thread_id(thread)
    try:
        form = FutureDemoForm.model_validate(raw_form)
    except ValidationError as exc:
        raise ValueError("invalid_demo_form") from exc
    creditor = creditor_loader().strip()
    if not creditor or len(creditor) > 120:
        raise ValueError("channel_creditor_invalid")

    defaults = (simulator_store or SimulatorStore()).load()
    today = datetime.now(timezone.utc).date()
    fixture = normalize_fixture(
        {
            "customer_id": f"DEMO-{uuid4().hex[:12].upper()}",
            "full_name": form.full_name,
            "cpf": form.cpf,
            "phone": form.phone,
            "birth_date": "",
            "institution": creditor,
            "creditor_name": creditor,
            "product": defaults.get("product", "cobranca"),
            "debt": {
                "debt_id": f"DEBT-{uuid4().hex[:12].upper()}",
                "contract_id": f"CTR-{uuid4().hex[:12].upper()}",
                "original_amount": form.amount,
                "current_amount": form.amount,
                "due_date": (today - timedelta(days=form.days_overdue)).isoformat(),
                "days_overdue": form.days_overdue,
                "status": "overdue",
            },
            "eligibility": defaults.get("eligibility", {}),
            "identity_policy": {
                "cpf_mode": "first3",
                "secondary": "none",
                "max_attempts": 3,
            },
        }
    )
    (session_store or SessionStore()).create(thread, fixture)
    return {
        "thread_id": thread,
        "creditor": creditor,
        "cpf_masked": f"***.***.***-{form.cpf[-2:]}",
        "phone_masked": f"***{form.phone[-4:]}",
        "amount": str(form.amount.quantize(Decimal("0.01"))),
        "days_overdue": form.days_overdue,
        "identity_policy": "cpf_first3",
        "created": True,
    }
