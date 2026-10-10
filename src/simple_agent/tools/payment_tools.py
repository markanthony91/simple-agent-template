from __future__ import annotations

from simple_agent.tool_timing import timed_tool

import json
import hashlib
import re
import sqlite3
import psycopg
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from simple_agent.services.channel_console import ChannelConsoleError, request_json
from simple_agent.services.offer_policy import (
    CanonicalPolicyRequired,
    DownPaymentRequired,
    policy_document_scope,
)
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
    if agreement.get("down_payment_amount") and installment_number == 1:
        payment["is_down_payment"] = True
    agreement["status"] = "payment_pending"
    return _public(payment)


@tool
@timed_tool
def generate_payment_offer(
    payment_type: Literal["cash", "installment"],
    method: Literal["pix", "boleto"],
    policy_path: str,
    runtime: ToolRuntime,
    installments: int | None = None,
    down_payment_amount: str = "0",
    discount_percentage: str | None = None,
) -> str:
    """Generate and persist an offer, agreement and dummy PIX/boleto atomically.

    The indexed agreement and issued instruction are saved with the session.
    Future second-copy requests must retrieve them, not generate a new offer.

    policy_path must be the exact published OKF policy previously read by the
    agent. The backend validates its receipt, scope, lifecycle and terms and
    applies its creditor-defined discount. For policies with overdue discount
    ceilings, omit discount_percentage unless the customer explicitly requests
    a discount; then use only a percentage found in the policy. The backend
    checks it against the current overdue tier and an explicit current_amount
    discount basis. Policies without that basis
    cannot generate a positive discount.
    A customer-proposed percentage alone is not authorization; do not invent
    policy terms. No internal human approval or second confirmation is required.
    Interpret the customer's current choice from the whole conversation, including
    short confirmations and terms supplied in earlier turns. The latest change or
    refusal supersedes earlier choices. Never call for a refusal, an informational
    question or unclear intent. Ask only for missing terms; do not ask the customer
    to repeat known terms. Do not infer a payment method when policy allows several.
    For installments, always supply the selected count; absence is not one installment.
    down_payment_amount is optional, in BRL as a decimal string (e.g. "1000.00").
    Omit it unless the customer chose an entry. installments counts ALL payments,
    including the entry: entry plus three later payments means installments=4.
    The entry is the first payment; the remaining total is split among the others.
    Never invent an entry or calculate it with the model/calculator. If the policy
    requires one, down_payment_required returns minimum_down_payment_amount; ask
    whether the customer can pay that amount, then reuse it after confirmation.
    Only created=true authorizes presenting the exact returned schedule and code.
    An auxiliary policy is not executable. On canonical_policy_required, read
    canonical_policy_path with okf_read, then retry once with that exact path and
    the customer's existing choices. Never treat the navigation hint as approval.
    """
    if payment_type == "installment" and installments is None:
        return _json(
            {
                "created": False,
                "reason": "offer_terms_missing",
                "missing_fields": ["installments"],
            }
        )
    installments = 1 if installments is None else installments
    if (
        type(installments) is not int
        or installments < 1
        or (payment_type == "cash" and installments != 1)
    ):
        return _json({"created": False, "reason": "invalid_payment_terms"})
    try:
        with (
            policy_document_scope(),
            SessionStore().transaction(
                thread_id(runtime), persist_payments=True
            ) as state,
        ):
            if not state.get("identity_verified"):
                return _json(
                    {"created": False, "reason": "identity_verification_required"}
                )
            try:
                policy_path, discount_percentage, _sole_method = (
                    validate_requested_payment_policy(
                        state,
                        policy_path,
                        payment_type,
                        installments,
                        method,
                        down_payment_amount,
                        discount_percentage,
                    )
                )
            except DownPaymentRequired as exc:
                return _json(
                    {
                        "created": False,
                        "reason": "down_payment_required",
                        "minimum_down_payment_amount": exc.minimum,
                    }
                )
            except CanonicalPolicyRequired as exc:
                return _json(
                    {
                        "created": False,
                        "reason": "canonical_policy_required",
                        "canonical_policy_path": exc.path,
                    }
                )
            except (KeyError, ValueError, ArithmeticError) as exc:
                reason = (
                    "policy_terms_undefined" if isinstance(exc, KeyError) else str(exc)
                )
                return _json({"created": False, "reason": reason})
            message_id, _ = latest_user_message(runtime)
            offer = _generate_offer(
                state,
                payment_type,
                installments,
                discount_percentage,
                policy_path,
                runtime,
                down_payment_amount,
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
@timed_tool
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
    with SessionStore().transaction(thread_id(runtime), persist_payments=True) as state:
        if not state.get("identity_verified"):
            return _json({"created": False, "reason": "identity_verification_required"})
        agreement = _agreement(state, agreement_id)
        if not agreement:
            return _json({"created": False, "reason": "valid_agreement_required"})
        return _json(_create_payment(state, agreement, method, installment_number))


def _installment_date(first_date: date, months: int) -> date:
    year, month_index = divmod(first_date.year * 12 + first_date.month - 1 + months, 12)
    month = month_index + 1
    return date(year, month, min(first_date.day, monthrange(year, month)[1]))


def _upcoming_installments(schedule: list[str], current: int, sent_date: date) -> str:
    return (
        "\n".join(
            f"{number}ª parcela: R$ {format(Decimal(amount), ',.2f').translate(str.maketrans(',.', '.,'))}"
            f" — {_installment_date(sent_date, number - current).strftime('%d/%m/%Y')}"
            for number, amount in enumerate(schedule, 1)
            if number > current
        )
        or "none"
    )


def _email_context(state: dict, payment: dict, agreement: dict) -> dict[str, str]:
    fixture = state["fixture"]
    method = str(payment["method"])
    sent_date = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    return {
        "nome": str(fixture["full_name"]),
        "credor": str(fixture.get("creditor_name") or fixture.get("institution") or ""),
        "produto": str(fixture.get("product") or ""),
        "forma_pagamento": method.upper(),
        "valor": f"R$ {str(payment['amount']).replace('.', ',')}",
        "payment_date": sent_date.strftime("%d/%m/%Y"),
        "upcoming_installments": (
            _upcoming_installments(
                agreement["installment_schedule"],
                payment["installment_number"],
                sent_date,
            )
            if method == "boleto"
            else "none"
        ),
        "installment_display": "none" if method == "pix" else "table-row",
        "codigo_pagamento": str(payment["payment_code"]),
        "payment_id": str(payment["payment_id"]),
        "agreement_id": str(payment["agreement_id"]),
        "numero_parcela": (
            "1 (entrada)"
            if payment.get("is_down_payment")
            else str(payment["installment_number"])
        ),
        "parcelas": str(agreement["installments"]),
        "is_simulation": "true",
    }


def _email_plan(
    context: dict[str, str], scope_id: int = 1
) -> tuple[dict, dict[str, str]]:
    catalog = request_json(
        "/api/engine/v1/channels", timeout=5,
        **({"scope_id": scope_id} if scope_id > 1 else {}),
    )
    channels = catalog.get("channels")
    if (
        not isinstance(channels, list)
        or type(catalog.get("scope_id")) is not int
        or type(catalog.get("scope_revision")) is not int
    ):
        raise ChannelConsoleError("email_catalog_invalid")
    if catalog["scope_id"] != scope_id:
        raise ChannelConsoleError("email_catalog_scope_mismatch")
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


def _dispatch_email(
    catalog: dict,
    values: dict[str, str],
    address: str,
    request_id: str,
    decision_id: str,
    scope_id: int = 1,
) -> dict:
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
            **({"scope_id": scope_id} if scope_id > 1 else {}),
        )
        return {
            "sent": result.get("status") == "accepted",
            "status": result.get("status")
            if result.get("status") in {"accepted", "failed", "unknown"}
            else "unknown",
            "provider_id": result.get("provider_id"),
            "code": result.get("code", "channel_console_invalid_response"),
        }
    except ChannelConsoleError as exc:
        return {
            "sent": False,
            "status": "unknown" if exc.outcome_unknown else "failed",
            "code": exc.code,
        }


def _demo_amount(value: Decimal | None, fallback: str) -> Decimal:
    try:
        if value is not None:
            amount = value
        else:
            normalized = re.sub(r"[^0-9,.-]", "", fallback)
            if "," in normalized:
                normalized = normalized.replace(".", "").replace(",", ".")
            amount = Decimal(normalized)
        if not Decimal("0") < amount <= Decimal("1000000000"):
            raise ValueError("invalid_amount")
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("invalid_amount") from exc


def send_voice_demo_email(
    session_id: str,
    contact_name: str,
    creditor: str,
    debt_amount: str,
    email: str,
    latest_user_message: str,
    payment_method: str,
    installments: int,
    total_amount: Decimal | None = None,
    installment_amount: Decimal | None = None,
    *,
    scope_id: int = 1,
    product: str = "cartao_de_credito",
) -> dict:
    """Send the voice DEMO values directly, without identity or session lookup."""
    if not contact_name.strip() or not creditor.strip():
        return {"sent": False, "reason": "invalid_demo_context"}
    address = email.strip().casefold()
    supplied = {
        match.group(0).casefold() for match in EMAIL_RE.finditer(latest_user_message)
    }
    if not EMAIL_RE.fullmatch(address) or address not in supplied:
        return {"sent": False, "reason": "explicit_email_required"}
    method = payment_method.strip().casefold()
    if method not in {"pix", "boleto"} or not 1 <= installments <= 10:
        return {"sent": False, "reason": "invalid_payment_terms"}
    if method == "pix" and installments != 1:
        return {"sent": False, "reason": "invalid_payment_terms"}
    try:
        total = _demo_amount(total_amount, debt_amount)
        instruction = (
            _demo_amount(installment_amount, "")
            if installment_amount is not None
            else (total / installments).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
    except ValueError as exc:
        return {"sent": False, "reason": str(exc)}
    fingerprint = hashlib.sha256(
        f"{session_id}:{address}:{method}:{installments}:{total}".encode()
    ).hexdigest()
    payment_id = f"PAY-{fingerprint[:32]}"
    context = {
        "nome": contact_name.strip(),
        "upcoming_installments": "none",
        "credor": creditor.strip(),
        "produto": product,
        "forma_pagamento": method.upper(),
        "valor": f"R$ {str(instruction).replace('.', ',')}",
        "payment_date": datetime.now(ZoneInfo("America/Sao_Paulo")).strftime(
            "%d/%m/%Y"
        ),
        "installment_display": "none" if method == "pix" else "table-row",
        "codigo_pagamento": f"DUMMY-{method.upper()}-{fingerprint.upper()[:32]}",
        "payment_id": payment_id,
        "agreement_id": f"AGR-{fingerprint[32:64]}",
        "numero_parcela": "1",
        "parcelas": str(installments),
        "is_simulation": "true",
    }
    try:
        catalog, values = _email_plan(context, scope_id)
    except ChannelConsoleError as exc:
        return {"sent": False, "reason": exc.code}
    result = _dispatch_email(
        catalog,
        values,
        address,
        str(uuid5(NAMESPACE_URL, f"voice-demo:{fingerprint}")),
        str(uuid5(NAMESPACE_URL, f"voice-demo-decision:{fingerprint}")),
        scope_id,
    )
    return {
        **result,
        "recipient": "<redacted>",
        "is_simulation": True,
    }


@tool(return_direct=True)
@timed_tool
def send_payment_instruction(payment_id: str, email: str, runtime: ToolRuntime) -> str:
    """Send a simulated payment instruction to an explicitly supplied email.

    The exact address must appear in the latest human message. The backend uses
    the saved Zerai Channels email template and never persists the address.
    Only sent=true confirms provider acceptance; it does not confirm delivery.
    """
    session_id = thread_id(runtime)
    _, user_text = latest_user_message(runtime)
    return _json(
        send_payment_instruction_for_session(session_id, payment_id, email, user_text)
    )


def send_payment_instruction_for_session(
    session_id: str, payment_id: str, email: str, user_text: str
) -> dict:
    """Shared session-bound email action for chat and trusted voice adapters."""
    address = email.strip().casefold()
    supplied = {match.group(0).casefold() for match in EMAIL_RE.finditer(user_text)}
    if (
        not 3 <= len(address) <= 254
        or not EMAIL_RE.fullmatch(address)
        or address not in supplied
    ):
        return {"sent": False, "reason": "explicit_email_required"}
    key = hashlib.sha256(f"{payment_id}:{address}".encode()).hexdigest()
    with SessionStore().transaction(session_id) as state:
        if not state.get("identity_verified"):
            return {"sent": False, "reason": "identity_verification_required"}
        payment = state["payments"].get(payment_id)
        if not payment:
            return {"sent": False, "reason": "valid_payment_required"}
        agreement = _agreement(state, payment["agreement_id"])
        try:
            validate_payment_policy(state, agreement or {}, payment["method"], "email")
        except (ValueError, ArithmeticError) as exc:
            return {"sent": False, "reason": str(exc)}
        previous = next(
            (
                item
                for item in state["deliveries"].values()
                if item["idempotency_key"] == key
            ),
            None,
        )
        if previous:
            return _public(previous)
        context = _email_context(state, payment, agreement)
        scope_id = state.get("portfolio_scope_id", 1)
    try:
        catalog, values = (
            _email_plan(context, scope_id)
            if scope_id > 1 else _email_plan(context)
        )
    except ChannelConsoleError as exc:
        return {"sent": False, "reason": exc.code}
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
            return _public(previous)
        state["deliveries"][delivery_id] = delivery
    update = (
        _dispatch_email(catalog, values, address, request_id, decision_id, scope_id)
        if scope_id > 1
        else _dispatch_email(catalog, values, address, request_id, decision_id)
    )
    with SessionStore().transaction(session_id) as state:
        stored = state["deliveries"].get(delivery_id)
        if stored is None:
            return {**_public(delivery), **update}
        stored.update(
            {key: value for key, value in update.items() if value is not None}
        )
        return _public(stored)


@tool
@timed_tool
def get_boleto_second_copy(
    runtime: ToolRuntime,
    agreement_id: str = "",
    installment_number: int | None = None,
) -> str:
    """Retrieve an EXISTING simulated boleto after identity verification.

    Use for 'segunda via', 'reenviar boleto' or a lost boleto. No policy_path is
    needed: this reads saved terms, never recalculates, issues or sends anything.
    The server chooses customer/debt/company scope; never pass a CPF or customer ID.
    Call without selectors when unknown; reuse agreement_id from results and ask
    only for the missing selection on agreement_selection_required or
    installment_selection_required. Only found=true authorizes returning the exact
    payment_code and amount, always identified as simulated. due_date=null means
    unavailable, not today's date. Do not claim provider acceptance or delivery.
    boleto_not_found / boleto_not_issued do not authorize a new negotiation.
    query_failed means the lookup failed, not that there is no boleto. A paid,
    cancelled or expired boleto cannot be reissued by this tool.
    """
    if not isinstance(agreement_id, str) or len(agreement_id) > 200:
        return _json({"found": False, "reason": "invalid_agreement_id"})
    if installment_number is not None and (
        type(installment_number) is not int or not 1 <= installment_number <= 360
    ):
        return _json({"found": False, "reason": "invalid_installment_number"})
    try:
        result = SessionStore().boleto_second_copy(
            thread_id(runtime), agreement_id, installment_number
        )
    except (sqlite3.Error, psycopg.Error, OSError, ValueError, KeyError, TypeError):
        result = {"found": False, "reason": "query_failed"}
    return _json(result)


@tool
@timed_tool
def get_payment_status(payment_id: str, runtime: ToolRuntime) -> str:
    """Read the persisted status of a dummy payment in the current session."""
    state = SessionStore().read(thread_id(runtime))
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
    with SessionStore().transaction(session_id, persist_payments=True) as state:
        payment = state["payments"].get(payment_id)
        if not payment:
            raise ValueError("payment_not_found")
        if payment["status"] != "settled":
            payment["status"] = "settled"
            payment["settled_at"] = datetime.now(timezone.utc).isoformat()
            agreement = _agreement(state, payment["agreement_id"])
            if agreement:
                settled = {
                    item["installment_number"]
                    for item in state["payments"].values()
                    if item["agreement_id"] == agreement["agreement_id"]
                    and item["status"] == "settled"
                }
                if settled == set(range(1, len(agreement["installment_schedule"]) + 1)):
                    agreement["status"] = "settled"
        return {
            "payment_id": payment_id,
            "status": payment["status"],
            "settled_at": payment["settled_at"],
            "is_simulation": True,
        }


PAYMENT_TOOLS = [
    generate_payment_offer,
    get_boleto_second_copy,
    send_payment_instruction,
    get_payment_status,
]
