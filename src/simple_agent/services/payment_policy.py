"""Validate payment actions against the same policy used by the agreement."""

from __future__ import annotations

import re

from simple_agent.services.offer_policy import fingerprint, money, validate_policy
from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.okf_validator import frontmatter


def resolve_payment_policy(
    state: dict,
    payment_type: str,
    installments: int,
    discount_percentage: str,
    method: str,
) -> str:
    """Resolve one applicable policy inside the session's pinned snapshot."""
    snapshot = state.get("snapshot_id")
    if not snapshot:
        raise ValueError("policy_not_found")
    root = PersistentOKFStore().bundle_root(snapshot)
    fixture = state["fixture"]
    receipts = state.setdefault("receipts", {})
    valid: list[str] = []
    errors: list[str] = []
    previous_receipts: dict[str, tuple[bool, dict | None]] = {}

    for source in sorted(root.rglob("*.md")):
        if source.name.casefold() in {"index.md", "log.md"}:
            continue
        content = source.read_text(encoding="utf-8")
        if not re.search(r"^negotiation\s*:", content, re.MULTILINE) or not re.search(
            r"^payment\s*:", content, re.MULTILINE
        ):
            continue
        metadata = frontmatter(content)
        if (
            metadata.get("institution") != fixture.get("institution")
            or metadata.get("product") != fixture.get("product")
            or not isinstance(metadata.get("negotiation"), dict)
            or not isinstance(metadata.get("payment"), dict)
        ):
            continue
        path = source.relative_to(root).as_posix()
        previous_receipts[path] = (path in receipts, receipts.get(path))
        receipts[path] = {"hash": fingerprint(content), "snapshot_id": snapshot}
        try:
            evidence = validate_policy(
                state,
                path,
                payment_type,
                1 if payment_type == "cash" else installments,
                money(discount_percentage),
            )
            validate_payment_policy(
                state,
                {
                    "policy_source": evidence,
                    "payment_type": payment_type,
                    "installments": 1 if payment_type == "cash" else installments,
                    "discount_percentage": discount_percentage,
                },
                method,
            )
        except (ValueError, ArithmeticError) as error:
            errors.append(str(error))
            _restore_receipt(receipts, path, previous_receipts[path])
        else:
            valid.append(path)

    if len(valid) > 1:
        for path in valid:
            _restore_receipt(receipts, path, previous_receipts[path])
        raise ValueError("policy_ambiguous")
    if not valid:
        raise ValueError(errors[0] if errors else "policy_not_found")
    return valid[0]


def _restore_receipt(
    receipts: dict, path: str, previous: tuple[bool, dict | None]
) -> None:
    existed, value = previous
    if existed:
        receipts[path] = value
    else:
        receipts.pop(path, None)


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
