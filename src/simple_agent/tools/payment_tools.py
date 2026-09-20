from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from simple_agent.services.offer_policy import money
from simple_agent.services.payment_policy import (
    resolve_payment_policy,
    validate_payment_policy,
)
from simple_agent.services.session_store import (
    SessionStore,
    latest_user_message,
    thread_id,
)
from simple_agent.tools.collection_tools import _create_agreement, _generate_offer

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


class _CompositeError(Exception):
    pass


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


def _terms_explicit(
    text: str, payment_type: str, method: str, installments: int, discount: str
) -> bool:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    if not re.search(rf"\b{method}\b", normalized):
        return False
    if payment_type == "cash":
        if not re.search(r"\b(a vista|de uma vez|quitar(?: tudo)?)\b", normalized):
            return False
    elif not re.search(rf"\b{installments}\s*(?:x|parcelas?)\b", normalized):
        return False
    try:
        percentage = money(discount)
    except (ValueError, ArithmeticError):
        return True  # The financial validator returns the precise error.
    if percentage and not re.search(
        rf"\b{re.escape(format(percentage.normalize(), 'f'))}\s*%", normalized
    ):
        return False
    return True


def _create_payment(
    state: dict, agreement: dict, method: str, installment_number: int
) -> dict:
    if agreement.get("status") == "settled":
        return {"created": False, "reason": "agreement_already_settled"}
    if type(installment_number) is not int or not 1 <= installment_number <= len(
        agreement["installment_schedule"]
    ):
        return {"created": False, "reason": "invalid_installment_number"}
    try:
        evidence = validate_payment_policy(state, agreement, method)
    except (ValueError, ArithmeticError) as exc:
        return {"created": False, "reason": str(exc)}
    key = f"{agreement['agreement_id']}:{method}:{installment_number}"
    previous = next(
        (item for item in state["payments"].values() if item["idempotency_key"] == key),
        None,
    )
    if previous:
        return _public(previous)
    payment_id = f"PAY-{uuid4().hex}"
    payment = {
        "created": True,
        "payment_id": payment_id,
        "agreement_id": agreement["agreement_id"],
        "method": method,
        "installment_number": installment_number,
        "amount": agreement["installment_schedule"][installment_number - 1],
        "status": "pending",
        "is_simulation": True,
        "payment_code": f"DUMMY-{method.upper()}-{uuid4().hex.upper()}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "policy_source": evidence,
        "idempotency_key": key,
    }
    state["payments"][payment_id] = payment
    agreement["status"] = "payment_pending"
    return _public(payment)


@tool(return_direct=True)
def generate_payment_offer(
    payment_type: Literal["cash", "installment"],
    method: Literal["pix", "boleto"],
    runtime: ToolRuntime,
    installments: int = 1,
    discount_percentage: str = "0",
    policy_path: str = "",
) -> str:
    """Generate an offer, agreement and dummy PIX/boleto in one transaction.

    Use only after the customer explicitly names PIX or boleto in the latest
    message. When policy_path is omitted, the backend resolves exactly one
    applicable policy from the pinned snapshot. No internal human approval or
    second confirmation is required.
    Only created=true authorizes presenting the exact returned schedule and code.
    """
    try:
        with SessionStore().transaction(thread_id(runtime)) as state:
            if not state.get("identity_verified"):
                return _json(
                    {"created": False, "reason": "identity_verification_required"}
                )
            message_id, user_text = latest_user_message(runtime)
            if not _terms_explicit(
                user_text, payment_type, method, installments, discount_percentage
            ):
                return _json(
                    {"created": False, "reason": "explicit_offer_terms_required"}
                )
            if not policy_path:
                try:
                    policy_path = resolve_payment_policy(
                        state,
                        payment_type,
                        installments,
                        discount_percentage,
                        method,
                    )
                except (ValueError, ArithmeticError) as exc:
                    return _json({"created": False, "reason": str(exc)})
            offer = _generate_offer(
                state,
                payment_type,
                installments,
                discount_percentage,
                policy_path,
                runtime,
            )
            if not offer.get("available"):
                return _json(
                    {"created": False, "reason": offer.get("reason"), "offer": offer}
                )
            candidate = {**offer, "agreement_id": "pending", "status": "created"}
            try:
                validate_payment_policy(state, candidate, method)
            except (ValueError, ArithmeticError) as exc:
                raise _CompositeError(str(exc)) from exc
            agreement = _create_agreement(
                state, offer["offer_id"], message_id, "customer_requested_terms"
            )
            if not agreement.get("created"):
                raise _CompositeError(agreement.get("reason"))
            payment = _create_payment(state, agreement, method, 1)
            if not payment.get("created"):
                raise _CompositeError(payment.get("reason"))
            return _json(
                {
                    "created": True,
                    "offer": offer,
                    "agreement": agreement,
                    "payment": payment,
                }
            )
    except _CompositeError as exc:
        return _json({"created": False, "reason": str(exc)})


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
        return _json(_create_payment(state, agreement, method, installment_number))


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
    generate_payment_offer,
    send_payment_instruction,
    get_payment_status,
]
