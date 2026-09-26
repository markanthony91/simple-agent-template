"""Validate declarative policy; never infer authorization from prose."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal

from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.okf_validator import frontmatter


def fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def money(value) -> Decimal:
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("invalid_financial_value")
    return number


def resolve_offer_discount(policy: dict, fixture: dict) -> Decimal:
    """Resolve creditor-owned terms from trusted debt context, never model input."""
    if "discount_tiers" not in policy:
        if "offer_discount_percentage" not in policy:
            raise ValueError("policy_terms_undefined")
        return money(policy["offer_discount_percentage"])
    tiers = policy["discount_tiers"]
    if (
        "offer_discount_percentage" in policy
        or not isinstance(tiers, list)
        or not tiers
    ):
        raise ValueError("policy_terms_invalid")
    maximum = money(policy.get("max_discount_percentage"))
    debt = fixture.get("debt", {})
    days = debt.get("days_overdue")
    if days is None:
        try:
            days = max(0, (date.today() - date.fromisoformat(debt["due_date"])).days)
        except (KeyError, TypeError, ValueError):
            raise ValueError("debt_context_required") from None
    if type(days) is not int or days < 0:
        raise ValueError("debt_context_required")
    expected_min = 0
    selected = None
    for index, tier in enumerate(tiers):
        if (
            not isinstance(tier, dict)
            or not {"min_days_overdue", "max_days_overdue", "offer_discount_percentage"}
            <= tier.keys()
        ):
            raise ValueError("policy_terms_invalid")
        lower, upper = tier["min_days_overdue"], tier["max_days_overdue"]
        if type(lower) is not int or lower != expected_min:
            raise ValueError("policy_terms_invalid")
        if upper is None:
            if index != len(tiers) - 1:
                raise ValueError("policy_terms_invalid")
        elif type(upper) is not int or upper < lower or index == len(tiers) - 1:
            raise ValueError("policy_terms_invalid")
        discount = money(tier["offer_discount_percentage"])
        if maximum > 100 or discount > maximum:
            raise ValueError("policy_terms_invalid")
        if lower <= days and (upper is None or days <= upper):
            selected = discount
        expected_min = upper + 1 if upper is not None else 0
    if selected is None:
        raise ValueError("policy_terms_invalid")
    return selected


def validate_policy(
    state: dict, path: str, payment_type: str, count: int, discount: Decimal
) -> dict:
    snapshot = state.get("snapshot_id")
    receipt = state.get("receipts", {}).get(path)
    if not snapshot or not receipt:
        raise ValueError("policy_read_required")
    store = PersistentOKFStore()
    root = store.bundle_root(snapshot)
    from simple_agent.services.okf_service import OKFService

    canonical = OKFService(root).canonical_path(path)
    content = (root / canonical).read_text(encoding="utf-8")
    if (
        receipt.get("hash") != fingerprint(content)
        or receipt.get("snapshot_id") != snapshot
    ):
        raise ValueError("policy_receipt_mismatch")
    meta = frontmatter(content)
    if meta.get("status") not in {"published", "stable", "active"}:
        raise ValueError("policy_not_published")
    now = datetime.now(timezone.utc)
    for key, expired in (
        ("effective_from", False),
        ("effective_until", True),
        ("stale_after", True),
    ):
        if meta.get(key):
            date = datetime.fromisoformat(str(meta[key]).replace("Z", "+00:00"))
            date = date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date
            if (expired and now >= date) or (not expired and now < date):
                raise ValueError("policy_not_current")
    fixture = state["fixture"]
    if meta.get("institution") != fixture.get("institution") or meta.get(
        "product"
    ) != fixture.get("product"):
        raise ValueError("policy_scope_mismatch")
    policy = meta.get("negotiation")
    if (
        not isinstance(policy, dict)
        or not {
            "max_installments",
            "max_discount_percentage",
            "payment_types",
        }
        <= policy.keys()
    ):
        raise ValueError("policy_terms_undefined")
    if (
        not isinstance(policy["payment_types"], list)
        or type(policy["max_installments"]) is not int
        or not 1 <= policy["max_installments"] <= 360
    ):
        raise ValueError("policy_terms_invalid")
    maximum = money(policy["max_discount_percentage"])
    offered = resolve_offer_discount(policy, fixture)
    if maximum > 100 or offered > maximum:
        raise ValueError("policy_terms_invalid")
    if (
        payment_type not in policy["payment_types"]
        or count > policy["max_installments"]
        or discount > maximum
        or ("discount_tiers" in policy and discount > offered)
    ):
        raise ValueError("policy_terms_exceeded")
    return {
        "path": canonical,
        "content_hash": receipt["hash"],
        "snapshot_id": snapshot,
        "offer_discount_percentage": format(offered.normalize(), "f"),
    }
