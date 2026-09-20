"""Validate payment actions against the same policy used by the agreement."""

from __future__ import annotations

from simple_agent.services.offer_policy import money, validate_policy
from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.okf_validator import frontmatter


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
            "delivery_channels",
        }
        <= payment.keys()
    ):
        raise ValueError("payment_terms_undefined")
    methods = payment["methods"]
    channels = payment["delivery_channels"]
    if not isinstance(methods, list) or not isinstance(channels, list):
        raise ValueError("payment_terms_invalid")
    if method not in methods:
        raise ValueError("payment_method_not_allowed")
    if channel and channel not in channels:
        raise ValueError("delivery_channel_not_allowed")
    return evidence
