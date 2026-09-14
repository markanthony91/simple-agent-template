from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import uuid4

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from simple_agent.services.offer_policy import money, validate_policy
from simple_agent.services.session_store import (
    SessionStore,
    latest_user_message,
    thread_id,
)
from simple_agent.services.simulator_store import SimulatorStore


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _mask_document(value: str) -> str:
    return f"***.***.***-{_digits(value)[-2:]}"


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _amount(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@tool
def get_customer(cpf: str, runtime: ToolRuntime) -> str:
    """Read synthetic debt only after identity verification in this conversation."""
    with SessionStore().transaction(thread_id(runtime)) as state:
        fixture = state["fixture"]
        if not _digits(cpf) or _digits(cpf) != _digits(fixture["cpf"]):
            return _json({"found": False, "reason": "customer_not_found"})
        if not state["identity_verified"]:
            return _json(
                {
                    "found": True,
                    "identity_validated": False,
                    "financial_data_available": False,
                    "cpf": _mask_document(cpf),
                    "reason": "identity_verification_required",
                }
            )
        debt = fixture.get("debt", {})
        return _json(
            {
                "found": True,
                "identity_validated": True,
                "customer_id": fixture["customer_id"],
                "full_name": fixture["full_name"],
                "cpf": _mask_document(cpf),
                "institution": fixture.get("institution"),
                "product": fixture.get("product"),
                "debt": {
                    **debt,
                    "days_overdue": SimulatorStore().days_overdue(debt.get("due_date")),
                },
            }
        )


@tool
def verify_customer_identity(
    cpf: str, runtime: ToolRuntime, full_name: str = "", birth_date: str = ""
) -> str:
    """Verify document plus name or birth date. Every failure revokes this session only."""
    with SessionStore().transaction(thread_id(runtime)) as state:
        fixture = state["fixture"]
        checks = []
        if full_name.strip():
            checks.append(
                full_name.strip().casefold()
                == fixture.get("full_name", "").strip().casefold()
            )
        if birth_date.strip():
            checks.append(birth_date == fixture.get("birth_date"))
        matched = bool(_digits(cpf)) and _digits(cpf) == _digits(fixture["cpf"])
        verified = matched and bool(checks) and all(checks)
        state["identity_verified"] = verified
        if not verified:
            state.pop("verification_id", None)
            state["offers"] = {}
            reason = (
                "identity_not_matched"
                if not matched
                else "secondary_factor_not_matched"
                if checks
                else "secondary_factor_required"
            )
            return _json({"verified": False, "reason": reason})
        state["verification_id"] = state.get("verification_id") or f"VER-{uuid4().hex}"
        return _json(
            {
                "verified": True,
                "verification_id": state["verification_id"],
                "customer_id": fixture["customer_id"],
                "cpf": _mask_document(cpf),
            }
        )


@tool
def generate_offer(
    payment_type: Literal["cash", "installment"],
    runtime: ToolRuntime,
    installments: int = 1,
    discount_percentage: str = "0",
    policy_path: str = "",
) -> str:
    """Simulate an offer using a previously read, published OKF policy.

    policy_path comes from okf_read/okf_read_section. Decimal values are strings.
    Undefined policy is not authorization. Present the returned schedule exactly.
    """
    with SessionStore().transaction(thread_id(runtime)) as state:
        if not state["identity_verified"]:
            return _json(
                {"available": False, "reason": "identity_verification_required"}
            )
        fixture = state["fixture"]
        eligibility = fixture.get("eligibility", {})
        if eligibility.get("can_negotiate") is not True:
            return _json({"available": False, "reason": "customer_not_eligible"})
        count = 1 if payment_type == "cash" else installments
        try:
            discount = money(discount_percentage)
            if (
                not 1 <= count <= int(eligibility.get("max_installments", 1))
                or discount > money(eligibility.get("max_discount_percentage", 0))
                or discount > 100
            ):
                raise ValueError("customer_eligibility_exceeded")
            evidence = validate_policy(
                state, policy_path, payment_type, count, discount
            )
        except (ValueError, ArithmeticError) as exc:
            return _json({"available": False, "reason": str(exc)})
        message_id, user_text = latest_user_message(runtime)
        key = hashlib.sha256(
            json.dumps(
                [message_id or user_text, payment_type, count, str(discount), evidence],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        previous = state["offers"].get(key)
        if previous and datetime.now(timezone.utc) < datetime.fromisoformat(
            previous["expires_at"]
        ):
            return _json(previous)
        current = money(fixture.get("debt", {}).get("current_amount", 0))
        total = (current * (1 - discount / 100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        cents, remainder = divmod(int(total * 100), count)
        schedule = [
            _amount(Decimal(cents + (1 if i < remainder else 0)) / 100)
            for i in range(count)
        ]
        now = datetime.now(timezone.utc)
        offer = {
            "available": True,
            "offer_id": f"OFF-{uuid4().hex}",
            "status": "available",
            "customer_id": fixture["customer_id"],
            "debt_id": fixture.get("debt", {}).get("debt_id"),
            "payment_type": payment_type,
            "debt_amount": _amount(current),
            "discount_percentage": str(discount),
            "discount_amount": _amount(current - total),
            "negotiated_amount": _amount(total),
            "installments": count,
            "installment_amount": schedule[0],
            "installment_schedule": schedule,
            "created_at": now.isoformat(),
            "expires_at": (
                now + timedelta(seconds=int(os.getenv("OFFER_TTL_SECONDS", "900")))
            ).isoformat(),
            "policy_source": evidence,
            "snapshot_id": state["snapshot_id"],
            "source_message_id": message_id,
            "confirmation_instruction": "Use the simulator confirmation button or send CONFIRMAR ACORDO followed by this offer_id.",
        }
        state["offers"][key] = offer
        return _json(offer)


@tool
def create_agreement(
    offer_id: str,
    explicit_confirmation: bool,
    runtime: ToolRuntime,
    confirmation_text: str = "",
) -> str:
    """Register a simulated agreement only after the user confirms its exact offer ID.

    LLM arguments are not consent. The actual last user message must confirm the offer.
    Repeating the request returns the same agreement, never creates another.
    """
    with SessionStore().transaction(thread_id(runtime)) as state:
        if not state["identity_verified"]:
            return _json({"created": False, "reason": "identity_verification_required"})
        existing = state["agreements"].get(offer_id)
        if existing:
            return _json(existing)
        offer = next(
            (x for x in state["offers"].values() if x["offer_id"] == offer_id), None
        )
        if not offer or offer["status"] != "available":
            return _json({"created": False, "reason": "valid_offer_required"})
        if datetime.now(timezone.utc) >= datetime.fromisoformat(offer["expires_at"]):
            return _json({"created": False, "reason": "offer_expired"})
        message_id, user_text = latest_user_message(runtime)
        if (
            explicit_confirmation is not True
            or user_text.strip() != f"CONFIRMAR ACORDO {offer_id}"
            or message_id == offer["source_message_id"]
        ):
            return _json(
                {"created": False, "reason": "explicit_user_confirmation_required"}
            )
        try:
            validate_policy(
                state,
                offer["policy_source"]["path"],
                offer["payment_type"],
                offer["installments"],
                money(offer["discount_percentage"]),
            )
        except ValueError as exc:
            return _json({"created": False, "reason": str(exc)})
        agreement = {
            "created": True,
            "agreement_id": f"AGR-{uuid4().hex}",
            "offer_id": offer_id,
            "status": "created",
            "is_simulation": True,
            "confirmation_message_id": message_id,
            **{
                k: offer[k]
                for k in (
                    "customer_id",
                    "debt_id",
                    "negotiated_amount",
                    "installments",
                    "installment_schedule",
                    "snapshot_id",
                )
            },
        }
        state["agreements"][offer_id] = agreement
        offer["status"] = "accepted"
        return _json(agreement)


COLLECTION_TOOLS = [
    get_customer,
    verify_customer_identity,
    generate_offer,
    create_agreement,
]
