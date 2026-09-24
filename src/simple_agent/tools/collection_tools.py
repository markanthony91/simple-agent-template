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
from simple_agent.services.identity_policy import matches, policy_for


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _mask_document(value: str) -> str:
    return f"***.***.***-{_digits(value)[-2:]}"


def _mask_phone(value: str) -> str:
    digits = _digits(value)
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _amount(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _customer_payload(state: dict, cpf: str = "") -> dict:
    fixture = state["fixture"]
    if cpf and _digits(cpf) != _digits(fixture["cpf"]):
        return {"found": False, "reason": "customer_not_found"}
    if not state["identity_verified"]:
        return {
            "found": False,
            "identity_validated": False,
            "financial_data_available": False,
            "reason": "identity_verification_required",
        }
    debt = fixture.get("debt", {})
    state["debt_read"] = True
    payload = {
        "found": True,
        "identity_validated": True,
        "customer_id": fixture["customer_id"],
        "full_name": fixture["full_name"],
        "cpf": _mask_document(fixture["cpf"]),
        "institution": fixture.get("institution"),
        "product": fixture.get("product"),
        "debt": {
            **debt,
            "days_overdue": debt.get("days_overdue")
            if isinstance(debt.get("days_overdue"), int)
            else SimulatorStore().days_overdue(debt.get("due_date")),
        },
    }
    if fixture.get("phone"):
        payload["phone"] = _mask_phone(fixture["phone"])
    return payload


def _verify_identity(
    state: dict, runtime: ToolRuntime, cpf: str, full_name: str, birth_date: str
) -> dict:
    fixture = state["fixture"]
    policy = policy_for(state)
    attempts = state.get("identity_attempts", 0)
    supplied_by_user = True
    if policy.cpf_mode == "first3" and policy.secondary == "none":
        _, user_text = latest_user_message(runtime)
        user_cpf = _digits(user_text)
        supplied_by_user = len(user_cpf) == 3
        if supplied_by_user:
            cpf = user_cpf
    verified = (
        attempts < policy.max_attempts
        and supplied_by_user
        and matches(state, cpf, full_name, birth_date)
    )
    state["identity_verified"] = verified
    if not verified:
        state["debt_read"] = False
        state.pop("verification_id", None)
        state["offers"] = {}
        # Retransmission of the same tool call cannot consume another attempt.
        seen = state.setdefault("identity_failed_calls", [])
        call_id = runtime.tool_call_id
        if attempts < policy.max_attempts and (not call_id or call_id not in seen):
            attempts += 1
            state["identity_attempts"] = attempts
            if call_id:
                seen.append(call_id)
        return {
            "verified": False,
            "reason": "identity_validation_failed",
            "attempts_remaining": max(0, policy.max_attempts - attempts),
            "requires_human": attempts >= policy.max_attempts,
        }
    state["verification_id"] = state.get("verification_id") or f"VER-{uuid4().hex}"
    return {
        "verified": True,
        "verification_id": state["verification_id"],
        "customer_id": fixture["customer_id"],
        "cpf": _mask_document(cpf),
    }


@tool
def get_customer(runtime: ToolRuntime, cpf: str = "") -> str:
    """Read the pinned session's synthetic debt only after identity verification.

    After verified=true, call with no arguments. Never guess the rest of a CPF.
    Optional cpf is for legacy full-CPF callers; it cannot select another customer.
    """
    with SessionStore().transaction(thread_id(runtime)) as state:
        return _json(_customer_payload(state, cpf))


@tool
def verify_customer_identity(
    cpf: str, runtime: ToolRuntime, full_name: str = "", birth_date: str = ""
) -> str:
    """Verify identity using the backend's pinned session policy.

    The session instructions specify full CPF, first3, first4 or last4, plus the
    configured optional secondary factors. Use only user-supplied data.
    Do not choose the method or guess missing digits. Only verified=true establishes
    identity. On requires_human=true stop attempts; never disclose expected values.
    """
    with SessionStore().transaction(thread_id(runtime)) as state:
        return _json(_verify_identity(state, runtime, cpf, full_name, birth_date))


@tool(return_direct=True)
def verify_and_get_customer(
    cpf: str, runtime: ToolRuntime, full_name: str = "", birth_date: str = ""
) -> str:
    """Verify identity and return the pinned synthetic debt in one atomic call.

    Use instead of separate verification and customer lookup. The session contract
    defines the required CPF segment and secondary factors. Only verified=true
    includes customer data; failures never expose financial data.
    """
    with SessionStore().transaction(thread_id(runtime)) as state:
        result = _verify_identity(state, runtime, cpf, full_name, birth_date)
        if result["verified"]:
            result["customer"] = _customer_payload(state)
        return _json(result)


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
    No separate down payment is supported; never calculate or promise an entry.
    A denied simulation is not proof that an entire payment modality is prohibited.
    """
    with SessionStore().transaction(thread_id(runtime)) as state:
        return _json(
            _generate_offer(
                state,
                payment_type,
                installments,
                discount_percentage,
                policy_path,
                runtime,
            )
        )


def _generate_offer(
    state: dict,
    payment_type: str,
    installments: int,
    discount_percentage: str,
    policy_path: str,
    runtime: ToolRuntime,
) -> dict:
    if not state["identity_verified"]:
        return {"available": False, "reason": "identity_verification_required"}
    fixture = state["fixture"]
    eligibility = fixture.get("eligibility", {})
    if eligibility.get("can_negotiate") is not True:
        return {"available": False, "reason": "customer_not_eligible"}
    count = 1 if payment_type == "cash" else installments
    try:
        discount = money(discount_percentage)
        if (
            not 1 <= count <= int(eligibility.get("max_installments", 1))
            or discount > money(eligibility.get("max_discount_percentage", 0))
            or discount > 100
        ):
            raise ValueError("customer_eligibility_exceeded")
        evidence = validate_policy(state, policy_path, payment_type, count, discount)
    except (ValueError, ArithmeticError) as exc:
        return {"available": False, "reason": str(exc)}
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
        return previous
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
    }
    state["offers"][key] = offer
    return offer


def _create_agreement(
    state: dict, offer_id: str, authorization_message_id: str, basis: str
) -> dict:
    existing = state["agreements"].get(offer_id)
    if existing:
        return existing
    offer = next(
        (x for x in state["offers"].values() if x["offer_id"] == offer_id), None
    )
    if not offer or offer["status"] != "available":
        return {"created": False, "reason": "valid_offer_required"}
    if datetime.now(timezone.utc) >= datetime.fromisoformat(offer["expires_at"]):
        return {"created": False, "reason": "offer_expired"}
    try:
        validate_policy(
            state,
            offer["policy_source"]["path"],
            offer["payment_type"],
            offer["installments"],
            money(offer["discount_percentage"]),
        )
    except ValueError as exc:
        return {"created": False, "reason": str(exc)}
    agreement = {
        "created": True,
        "agreement_id": f"AGR-{uuid4().hex}",
        "offer_id": offer_id,
        "status": "created",
        "is_simulation": True,
        "authorization_message_id": authorization_message_id,
        "authorization_basis": basis,
        **{
            k: offer[k]
            for k in (
                "customer_id",
                "debt_id",
                "negotiated_amount",
                "payment_type",
                "discount_percentage",
                "installments",
                "installment_schedule",
                "policy_source",
                "snapshot_id",
            )
        },
    }
    state["agreements"][offer_id] = agreement
    offer["status"] = "accepted"
    return agreement


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
        message_id, user_text = latest_user_message(runtime)
        if (
            explicit_confirmation is not True
            or user_text.strip() != f"CONFIRMAR ACORDO {offer_id}"
            or message_id == offer["source_message_id"]
        ):
            return _json(
                {"created": False, "reason": "explicit_user_confirmation_required"}
            )
        return _json(
            _create_agreement(state, offer_id, message_id, "explicit_confirmation")
        )


COLLECTION_TOOLS = [
    verify_and_get_customer,
]
