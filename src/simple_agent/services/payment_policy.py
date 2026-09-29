"""Validate payment actions against the same policy used by the agreement."""

from __future__ import annotations

from simple_agent.services.offer_policy import (
    require_canonical_policy,
    money,
    read_policy_document,
    resolve_offer_discount,
    terms_for_payment_type,
    validate_policy,
)


def resolve_requested_payment_policy(
    state: dict,
    policy_path: str,
    payment_type: str,
    installments: int,
    down_payment_amount: str = "0",
) -> tuple[str, str, list[str]]:
    """Validate the exact OKF policy selected and read by the agent."""
    snapshot = state.get("snapshot_id")
    if not snapshot:
        raise ValueError("policy_not_found")
    try:
        canonical, content_hash, metadata = read_policy_document(snapshot, policy_path)
    except FileNotFoundError:
        raise ValueError("policy_not_found") from None
    require_canonical_policy(state, canonical, content_hash, metadata)
    negotiation = terms_for_payment_type(metadata.get("negotiation"), payment_type)
    configured_discount = resolve_offer_discount(negotiation, state["fixture"])
    count = 1 if payment_type == "cash" else installments
    evidence = validate_policy(
        state, canonical, payment_type, count, configured_discount, down_payment_amount
    )
    agreement = {
        "policy_source": evidence,
        "payment_type": payment_type,
        "installments": count,
        "discount_percentage": format(configured_discount.normalize(), "f"),
        "down_payment_amount": down_payment_amount,
    }
    validate_payment_policy(state, agreement, None)
    allowed = metadata["payment"]["methods_by_payment_type"][payment_type]
    return canonical, agreement["discount_percentage"], allowed


def validate_requested_payment_policy(
    state: dict,
    policy_path: str,
    payment_type: str,
    installments: int,
    method: str,
    down_payment_amount: str = "0",
) -> tuple[str, str, bool]:
    canonical, discount, allowed = resolve_requested_payment_policy(
        state, policy_path, payment_type, installments, down_payment_amount
    )
    if method not in allowed:
        raise ValueError("payment_method_not_allowed")
    return canonical, discount, len(allowed) == 1


def validate_payment_policy(
    state: dict, agreement: dict, method: str | None, channel: str = ""
) -> dict:
    source = agreement.get("policy_source")
    if not isinstance(source, dict) or not source.get("path"):
        raise ValueError("payment_policy_required")
    evidence = validate_policy(
        state,
        source["path"],
        agreement["payment_type"],
        agreement["installments"],
        money(agreement["discount_percentage"]),
        agreement.get("down_payment_amount", "0"),
    )
    _, _, meta = read_policy_document(evidence["snapshot_id"], evidence["path"])
    payment = meta.get("payment")
    if (
        not isinstance(payment, dict)
        or not {
            "methods",
            "methods_by_payment_type",
            "delivery_channels",
        }
        <= payment.keys()
    ):
        raise ValueError("payment_terms_undefined")
    methods = payment["methods"]
    methods_by_type = payment["methods_by_payment_type"]
    channels = payment["delivery_channels"]
    allowed = (
        methods_by_type.get(agreement["payment_type"])
        if isinstance(methods_by_type, dict)
        else None
    )
    if (
        not isinstance(methods, list)
        or not isinstance(channels, list)
        or not isinstance(allowed, list)
        or not allowed
        or not all(isinstance(item, str) and item in methods for item in allowed)
    ):
        raise ValueError("payment_terms_invalid")
    if method is not None and method not in allowed:
        raise ValueError("payment_method_not_allowed")
    if channel and channel not in channels:
        raise ValueError("delivery_channel_not_allowed")
    return evidence
