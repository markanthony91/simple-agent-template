"""Validate payment actions against the same policy used by the agreement."""

from __future__ import annotations

from simple_agent.services.offer_policy import (
    money,
    resolve_offer_discount,
    validate_policy,
)
from simple_agent.services.okf_service import OKFService
from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.okf_validator import frontmatter


def validate_requested_payment_policy(
    state: dict,
    policy_path: str,
    payment_type: str,
    installments: int,
    method: str,
) -> tuple[str, str, bool]:
    """Validate the exact OKF policy selected and read by the agent."""
    snapshot = state.get("snapshot_id")
    if not snapshot:
        raise ValueError("policy_not_found")
    root = PersistentOKFStore().bundle_root(snapshot)
    try:
        canonical = OKFService(root).canonical_path(policy_path)
    except FileNotFoundError:
        raise ValueError("policy_not_found") from None
    metadata = frontmatter((root / canonical).read_text(encoding="utf-8"))
    negotiation = metadata.get("negotiation")
    if not isinstance(negotiation, dict):
        raise ValueError("policy_terms_undefined") from None
    configured_discount = resolve_offer_discount(negotiation, state["fixture"])
    count = 1 if payment_type == "cash" else installments
    evidence = validate_policy(
        state, canonical, payment_type, count, configured_discount
    )
    agreement = {
        "policy_source": evidence,
        "payment_type": payment_type,
        "installments": count,
        "discount_percentage": format(configured_discount.normalize(), "f"),
    }
    validate_payment_policy(state, agreement, method)
    allowed = metadata["payment"]["methods_by_payment_type"][payment_type]
    return canonical, agreement["discount_percentage"], len(allowed) == 1


def validate_payment_policy(
    state: dict, agreement: dict, method: str, channel: str = ""
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
    )
    root = PersistentOKFStore().bundle_root(evidence["snapshot_id"])
    meta = frontmatter((root / evidence["path"]).read_text(encoding="utf-8"))
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
        or not all(isinstance(item, str) and item in methods for item in allowed)
    ):
        raise ValueError("payment_terms_invalid")
    if method not in allowed:
        raise ValueError("payment_method_not_allowed")
    if channel and channel not in channels:
        raise ValueError("delivery_channel_not_allowed")
    return evidence
