from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from simple_agent.services.payment_policy import validate_payment_policy
from simple_agent.services.session_store import (
    SessionStore,
    latest_user_message,
    thread_id,
)

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s.]+\.[^@\s]+")


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _public(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "idempotency_key"}


def _agreement(state: dict, agreement_id: str) -> dict | None:
    return next(
        (
            agreement
            for agreement in state.get("agreements", {}).values()
            if agreement.get("agreement_id") == agreement_id
        ),
        None,
    )


@tool
def create_payment_instruction(
    agreement_id: str,
    method: Literal["pix", "boleto"],
    runtime: ToolRuntime,
    installment_number: int = 1,
) -> str:
    """Create an unmistakably invalid dummy PIX or boleto for a simulated agreement.

    The backend revalidates the pinned OKF policy. Only created=true authorizes
    presenting the returned dummy code; it can never be used for a real payment.
    """
    with SessionStore().transaction(thread_id(runtime)) as state:
        if not state.get("identity_verified"):
            return _json({"created": False, "reason": "identity_verification_required"})
        agreement = _agreement(state, agreement_id)
        if not agreement:
            return _json({"created": False, "reason": "valid_agreement_required"})
        if agreement.get("status") == "settled":
            return _json({"created": False, "reason": "agreement_already_settled"})
        if type(installment_number) is not int or not 1 <= installment_number <= len(
            agreement["installment_schedule"]
        ):
            return _json({"created": False, "reason": "invalid_installment_number"})
        try:
            evidence = validate_payment_policy(state, agreement, method)
        except (ValueError, ArithmeticError) as exc:
            return _json({"created": False, "reason": str(exc)})
        key = f"{agreement_id}:{method}:{installment_number}"
        previous = next(
            (
                item
                for item in state["payments"].values()
                if item["idempotency_key"] == key
            ),
            None,
        )
        if previous:
            return _json(_public(previous))
        now = datetime.now(timezone.utc).isoformat()
        payment_id = f"PAY-{uuid4().hex}"
        payment = {
            "created": True,
            "payment_id": payment_id,
            "agreement_id": agreement_id,
            "method": method,
            "installment_number": installment_number,
            "amount": agreement["installment_schedule"][installment_number - 1],
            "status": "pending",
            "is_simulation": True,
            "payment_code": f"DUMMY-{method.upper()}-{uuid4().hex.upper()}",
            "created_at": now,
            "policy_source": evidence,
            "idempotency_key": key,
        }
        state["payments"][payment_id] = payment
        agreement["status"] = "payment_pending"
        return _json(_public(payment))


@tool
def send_payment_instruction(payment_id: str, email: str, runtime: ToolRuntime) -> str:
    """Capture a dummy payment instruction in the local outbox for an explicit email.

    No email is transmitted. The exact address must appear in the latest human
    message. Only captured=true confirms the simulated outbox record.
    """
    with SessionStore().transaction(thread_id(runtime)) as state:
        if not state.get("identity_verified"):
            return _json(
                {"captured": False, "reason": "identity_verification_required"}
            )
        payment = state["payments"].get(payment_id)
        if not payment:
            return _json({"captured": False, "reason": "valid_payment_required"})
        address = email.strip().casefold()
        _, user_text = latest_user_message(runtime)
        supplied = {match.group(0).casefold() for match in EMAIL_RE.finditer(user_text)}
        if (
            not 3 <= len(address) <= 254
            or not EMAIL_RE.fullmatch(address)
            or address not in supplied
        ):
            return _json({"captured": False, "reason": "explicit_email_required"})
        agreement = _agreement(state, payment["agreement_id"])
        try:
            validate_payment_policy(state, agreement or {}, payment["method"], "email")
        except (ValueError, ArithmeticError) as exc:
            return _json({"captured": False, "reason": str(exc)})
        key = f"{payment_id}:{address}"
        previous = next(
            (
                item
                for item in state["deliveries"].values()
                if item["idempotency_key"] == key
            ),
            None,
        )
        if previous:
            return _json(_public(previous))
        delivery_id = f"OUT-{uuid4().hex}"
        delivery = {
            "captured": True,
            "delivery_id": delivery_id,
            "payment_id": payment_id,
            "channel": "email",
            "recipient": "<redacted>",
            "status": "captured",
            "is_simulation": True,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": key,
        }
        state["deliveries"][delivery_id] = delivery
        return _json(_public(delivery))


@tool
def get_payment_status(payment_id: str, runtime: ToolRuntime) -> str:
    """Read the persisted status of a dummy payment in the current session."""
    with SessionStore().transaction(thread_id(runtime)) as state:
        if not state.get("identity_verified"):
            return _json({"found": False, "reason": "identity_verification_required"})
        payment = state["payments"].get(payment_id)
        if not payment:
            return _json({"found": False, "reason": "payment_not_found"})
        return _json(
            {
                "found": True,
                **{
                    key: payment[key]
                    for key in (
                        "payment_id",
                        "agreement_id",
                        "method",
                        "installment_number",
                        "amount",
                        "status",
                        "is_simulation",
                    )
                },
                **(
                    {"settled_at": payment["settled_at"]}
                    if payment.get("settled_at")
                    else {}
                ),
            }
        )


def simulate_payment_settled(session_id: str, payment_id: str) -> dict:
    """Operator-only settlement simulation; never registered as an agent tool."""
    with SessionStore().transaction(session_id) as state:
        payment = state["payments"].get(payment_id)
        if not payment:
            raise ValueError("payment_not_found")
        if payment["status"] != "settled":
            payment["status"] = "settled"
            payment["settled_at"] = datetime.now(timezone.utc).isoformat()
            agreement = _agreement(state, payment["agreement_id"])
            if agreement:
                agreement["status"] = "settled"
        return {
            "payment_id": payment_id,
            "status": payment["status"],
            "settled_at": payment["settled_at"],
            "is_simulation": True,
        }


PAYMENT_TOOLS = [
    create_payment_instruction,
    send_payment_instruction,
    get_payment_status,
]
