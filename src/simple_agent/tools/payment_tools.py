from __future__ import annotations

import json
import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from simple_agent.services.channel_console import ChannelConsoleError, request_json
from simple_agent.services.payment_policy import (
    validate_requested_payment_policy,
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


def _normalized_text(content) -> str:
    if isinstance(content, list):
        content = " ".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", str(content).casefold())
        if not unicodedata.combining(char)
    )


def _normalized_human_messages(runtime: ToolRuntime) -> list[str]:
    return [
        _normalized_text(message.content)
        for message in runtime.state.get("messages", [])
        if getattr(message, "type", None) == "human"
    ]


def _confirms_previous_offer(runtime: ToolRuntime, explicit_count: re.Pattern) -> bool:
    messages = runtime.state.get("messages", [])
    latest_human = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if getattr(messages[index], "type", None) == "human"
        ),
        None,
    )
    if latest_human is None or not re.fullmatch(
        r"\s*(?:sim|confirmo|aceito|fechado|pode seguir|vamos seguir)[.!]?\s*",
        _normalized_text(messages[latest_human].content),
    ):
        return False
    previous = next(
        (
            _normalized_text(message.content)
            for message in reversed(messages[:latest_human])
            if getattr(message, "type", None) == "ai"
            and _normalized_text(message.content).strip()
        ),
        "",
    )
    return bool(explicit_count.search(previous))


def _terms_explicit(
    runtime: ToolRuntime,
    payment_type: str,
    method: str,
    installments: int,
    method_required: bool = True,
) -> bool:
    messages = _normalized_human_messages(runtime)
    method_ok = not method_required or any(
        re.search(rf"\b{method}\b", text) for text in messages
    )
    if payment_type == "cash":
        payment_ok = any(
            re.search(r"\b(a\s*vist(?:a)?|de uma vez|quitar(?: tudo)?)\b", text)
            for text in messages
        )
    else:
        words = {
            1: "um|uma",
            2: "dois|duas",
            3: "tres",
            4: "quatro",
            5: "cinco",
            6: "seis",
            7: "sete",
            8: "oito",
            9: "nove",
            10: "dez",
            11: "onze",
            12: "doze",
        }.get(installments)
        count = rf"(?:{installments}|{words})" if words else str(installments)
        installment_intent = re.compile(r"\b(?:parcel\w*|divid\w*)\b")
        explicit_count = re.compile(
            rf"(?:\b{count}\s*(?:x|vez(?:es)?|parcelas?)\b|"
            rf"\b(?:parcel\w*|divid\w*)\b.{{0,40}}\b{count}\b)"
        )
        payment_ok = bool(messages and explicit_count.search(messages[-1]))
        if not payment_ok and messages:
            latest = re.sub(r"[^\w]+", " ", messages[-1]).strip()
            payment_ok = bool(
                re.fullmatch(count, latest)
                and any(installment_intent.search(text) for text in messages[:-1])
            )
        if not payment_ok:
            payment_ok = _confirms_previous_offer(runtime, explicit_count)
    return method_ok and payment_ok


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
    policy_path: str,
    runtime: ToolRuntime,
    installments: int = 1,
) -> str:
    """Generate an offer, agreement and dummy PIX/boleto in one transaction.

    policy_path must be the exact published OKF policy previously read by the
    agent. The backend validates its receipt, scope, lifecycle and terms and
    applies its creditor-defined discount. No customer-supplied discount,
    internal human approval or second confirmation is required.
    Only created=true authorizes presenting the exact returned schedule and code.
    """
    try:
        with SessionStore().transaction(thread_id(runtime)) as state:
            if not state.get("identity_verified"):
                return _json(
                    {"created": False, "reason": "identity_verification_required"}
                )
            try:
                policy_path, discount_percentage, sole_method = (
                    validate_requested_payment_policy(
                        state,
                        policy_path,
                        payment_type,
                        installments,
                        method,
                    )
                )
            except (KeyError, ValueError, ArithmeticError) as exc:
                reason = (
                    "policy_terms_undefined" if isinstance(exc, KeyError) else str(exc)
                )
                return _json({"created": False, "reason": reason})
            message_id, _ = latest_user_message(runtime)
            if not _terms_explicit(
                runtime,
                payment_type,
                method,
                installments,
                method_required=not sole_method,
            ):
                return _json(
                    {"created": False, "reason": "explicit_offer_terms_required"}
                )
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


def _email_context(state: dict, payment: dict, agreement: dict) -> dict[str, str]:
    fixture = state["fixture"]
    method = str(payment["method"])
    return {
        "nome": str(fixture["full_name"]),
        "credor": str(fixture.get("creditor_name") or fixture.get("institution") or ""),
        "produto": str(fixture.get("product") or ""),
        "forma_pagamento": method.upper(),
        "valor": f"R$ {str(payment['amount']).replace('.', ',')}",
        "payment_date": datetime.now(ZoneInfo("America/Sao_Paulo")).strftime(
            "%d/%m/%Y"
        ),
        "installment_display": "none" if method == "pix" else "table-row",
        "codigo_pagamento": str(payment["payment_code"]),
        "payment_id": str(payment["payment_id"]),
        "agreement_id": str(payment["agreement_id"]),
        "numero_parcela": str(payment["installment_number"]),
        "parcelas": str(agreement["installments"]),
        "is_simulation": "true",
    }


def _email_plan(context: dict[str, str]) -> tuple[dict, dict[str, str]]:
    catalog = request_json("/api/engine/v1/channels", timeout=5)
    channels = catalog.get("channels")
    if (
        not isinstance(channels, list)
        or type(catalog.get("scope_id")) is not int
        or type(catalog.get("scope_revision")) is not int
    ):
        raise ChannelConsoleError("email_catalog_invalid")
    channel = next(
        (
            item
            for item in channels
            if isinstance(item, dict) and item.get("channel") == "email"
        ),
        None,
    )
    if not channel or channel.get("enabled") is not True:
        raise ChannelConsoleError("email_channel_not_configured")
    required = channel.get("required")
    if (
        not isinstance(channel.get("template_id"), str)
        or type(channel.get("template_revision")) is not int
        or not isinstance(required, list)
        or not all(isinstance(x, str) for x in required)
    ):
        raise ChannelConsoleError("email_template_invalid")
    missing = [name for name in required if name not in context]
    if missing:
        raise ChannelConsoleError("email_template_unsupported_variables")
    return catalog, {name: context[name] for name in required}


@tool(return_direct=True)
def send_payment_instruction(payment_id: str, email: str, runtime: ToolRuntime) -> str:
    """Send a simulated payment instruction to an explicitly supplied email.

    The exact address must appear in the latest human message. The backend uses
    the saved Zerai Channels email template and never persists the address.
    Only sent=true confirms provider acceptance; it does not confirm delivery.
    """
    session_id = thread_id(runtime)
    address = email.strip().casefold()
    _, user_text = latest_user_message(runtime)
    supplied = {match.group(0).casefold() for match in EMAIL_RE.finditer(user_text)}
    if (
        not 3 <= len(address) <= 254
        or not EMAIL_RE.fullmatch(address)
        or address not in supplied
    ):
        return _json({"sent": False, "reason": "explicit_email_required"})
    key = hashlib.sha256(f"{payment_id}:{address}".encode()).hexdigest()
    with SessionStore().transaction(session_id) as state:
        if not state.get("identity_verified"):
            return _json({"sent": False, "reason": "identity_verification_required"})
        payment = state["payments"].get(payment_id)
        if not payment:
            return _json({"sent": False, "reason": "valid_payment_required"})
        agreement = _agreement(state, payment["agreement_id"])
        try:
            validate_payment_policy(state, agreement or {}, payment["method"], "email")
        except (ValueError, ArithmeticError) as exc:
            return _json({"sent": False, "reason": str(exc)})
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
        context = _email_context(state, payment, agreement)
    try:
        catalog, values = _email_plan(context)
    except ChannelConsoleError as exc:
        return _json({"sent": False, "reason": exc.code})
    delivery_id = f"OUT-{uuid4().hex}"
    request_id = str(uuid4())
    decision_id = str(uuid5(NAMESPACE_URL, f"{session_id}:{payment_id}:email"))
    delivery = {
        "sent": False,
        "delivery_id": delivery_id,
        "payment_id": payment_id,
        "channel": "email",
        "recipient": "<redacted>",
        "status": "processing",
        "is_simulation": True,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "idempotency_key": key,
    }
    with SessionStore().transaction(session_id) as state:
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
        state["deliveries"][delivery_id] = delivery
    channel = next(item for item in catalog["channels"] if item["channel"] == "email")
    try:
        result = request_json(
            "/api/engine/v1/dispatch",
            {
                "dry_run": False,
                "request_id": request_id,
                "decision_id": decision_id,
                "scope_id": catalog["scope_id"],
                "scope_revision": catalog["scope_revision"],
                "channel": "email",
                "template_id": channel["template_id"],
                "template_revision": channel["template_revision"],
                "to": address,
                "values": values,
            },
        )
        accepted = result.get("status") == "accepted"
        update = {
            "sent": accepted,
            "status": result.get("status")
            if result.get("status") in {"accepted", "failed", "unknown"}
            else "unknown",
            "provider_id": result.get("provider_id"),
            "code": result.get("code", "channel_console_invalid_response"),
        }
    except ChannelConsoleError as exc:
        update = {
            "sent": False,
            "status": "unknown" if exc.outcome_unknown else "failed",
            "code": exc.code,
        }
    with SessionStore().transaction(session_id) as state:
        stored = state["deliveries"].get(delivery_id)
        if stored is None:
            return _json({**_public(delivery), **update})
        stored.update(
            {key: value for key, value in update.items() if value is not None}
        )
        return _json(_public(stored))


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
