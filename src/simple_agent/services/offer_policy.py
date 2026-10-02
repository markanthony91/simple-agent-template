"""Validate declarative policy; never infer authorization from prose."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from pathlib import PurePosixPath

from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.okf_validator import frontmatter
from simple_agent.tool_timing import count_event, timed_phase


# Only document bytes/metadata are reused, never authorization decisions.
_policy_documents: ContextVar[dict | None] = ContextVar(
    "policy_documents", default=None
)


@contextmanager
def policy_document_scope():
    """Reuse immutable policy documents only within one atomic offer operation."""
    token = _policy_documents.set({})
    try:
        yield
    finally:
        _policy_documents.reset(token)


def read_policy_document(snapshot: str, path: str) -> tuple[str, str, dict]:
    from simple_agent.services.okf_service import OKFService

    root = PersistentOKFStore().bundle_root(snapshot)
    cache = _policy_documents.get()
    key = (str(root), path)
    if cache is not None and key in cache:
        count_event("policy_document_reuses")
        return cache[key]
    with timed_phase("policy_document_read"):
        canonical = OKFService(root).canonical_path(path)
        content = (root / canonical).read_text(encoding="utf-8")
        result = (canonical, fingerprint(content), frontmatter(content))
    count_event("policy_document_reads")
    if cache is not None:
        cache[key] = cache[(str(root), canonical)] = result
    return result


class CanonicalPolicyRequired(ValueError):
    """Navigation hint only; the agent must read and validate the target policy."""

    def __init__(self, path: str):
        super().__init__("canonical_policy_required")
        self.path = path


class DownPaymentRequired(ValueError):
    def __init__(self, minimum: Decimal):
        super().__init__("down_payment_required")
        self.minimum = format(minimum, ".2f")


def require_canonical_policy(
    state: dict, source: str, content_hash: str, metadata: dict
) -> None:
    from simple_agent.services.okf_service import OKFService

    if metadata.get("policy_role") != "auxiliary":
        return
    receipt = state.get("receipts", {}).get(source)
    if not receipt:
        raise ValueError("policy_read_required")
    if (
        receipt.get("hash") != content_hash
        or receipt.get("snapshot_id") != state["snapshot_id"]
    ):
        raise ValueError("policy_receipt_mismatch")
    reference = metadata.get("canonical_policy")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("policy_reference_invalid")
    reference = reference.strip()
    path = PurePosixPath(reference)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(c in reference for c in ("\\", ":", "?", "#"))
    ):
        raise ValueError("policy_reference_invalid")
    if not path.parts or path.parts[0].upper() not in OKFService.TOP_LEVEL_DIRECTORIES:
        path = PurePosixPath(source).parent / path
    try:
        target = OKFService(
            PersistentOKFStore().bundle_root(state["snapshot_id"])
        ).canonical_path(str(path))
    except (FileNotFoundError, ValueError):
        raise ValueError("policy_reference_invalid") from None
    if target == source:
        raise ValueError("policy_reference_invalid")
    raise CanonicalPolicyRequired(target)


def fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def money(value) -> Decimal:
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("invalid_financial_value")
    return number


def terms_for_payment_type(policy: dict, payment_type: str) -> dict:
    """Select declared modality terms; preserve legacy single-modality policies."""
    if not isinstance(policy, dict):
        raise ValueError("policy_terms_undefined")
    if "by_payment_type" not in policy:
        return policy
    branches = policy["by_payment_type"]
    types = policy.get("payment_types")
    if (
        not isinstance(branches, dict)
        or not isinstance(types, list)
        or not all(isinstance(kind, str) for kind in types)
        or set(branches) != set(types)
        or any(
            key in policy
            for key in (
                "offer_discount_percentage",
                "initial_offer_discount_percentage",
                "discount_tiers",
            )
        )
        or not all(isinstance(branch, dict) for branch in branches.values())
    ):
        raise ValueError("policy_terms_invalid")
    if payment_type not in branches:
        raise ValueError("payment_type_not_allowed")
    branch = branches[payment_type]
    allowed = {
        "max_discount_percentage",
        "offer_discount_percentage",
        "initial_offer_discount_percentage",
        "discount_tiers",
        "max_discount_tiers",
        "discount_basis",
    }
    if not set(branch) <= allowed or "max_discount_percentage" not in branch:
        raise ValueError("policy_terms_invalid")
    if money(branch["max_discount_percentage"]) > money(
        policy.get("max_discount_percentage")
    ):
        raise ValueError("policy_terms_invalid")
    return {**policy, **branch}


def debt_days_overdue(fixture: dict) -> int:
    debt = fixture.get("debt", {})
    days = debt.get("days_overdue")
    if days is None:
        try:
            days = max(0, (date.today() - date.fromisoformat(debt["due_date"])).days)
        except (KeyError, TypeError, ValueError):
            raise ValueError("debt_context_required") from None
    if type(days) is not int or days < 0:
        raise ValueError("debt_context_required")
    return days


def resolve_offer_discount(policy: dict, fixture: dict) -> Decimal:
    """Resolve creditor-owned terms from trusted debt context, never model input."""
    if "max_discount_tiers" in policy:
        if any(
            key in policy
            for key in (
                "discount_tiers",
                "offer_discount_percentage",
                "initial_offer_discount_percentage",
            )
        ):
            raise ValueError("policy_terms_invalid")
        return Decimal("0")
    if "discount_tiers" not in policy:
        if "initial_offer_discount_percentage" in policy:
            raise ValueError("policy_terms_invalid")
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
    days = debt_days_overdue(fixture)
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
    if "initial_offer_discount_percentage" in policy:
        initial = money(policy["initial_offer_discount_percentage"])
        if any(initial > money(tier["offer_discount_percentage"]) for tier in tiers):
            raise ValueError("policy_terms_invalid")
        return initial
    return selected


def overdue_tier(tiers: list, days: int) -> dict:
    """Select one declared overdue interval; gaps and overlaps cannot authorize terms."""
    if not isinstance(tiers, list) or not tiers:
        raise ValueError("policy_terms_invalid")
    found = []
    for tier in tiers:
        if not isinstance(tier, dict):
            raise ValueError("policy_terms_invalid")
        lower, upper = tier.get("min_days_overdue"), tier.get("max_days_overdue")
        if (
            type(lower) is not int
            or lower < 0
            or (upper is not None and (type(upper) is not int or upper < lower))
        ):
            raise ValueError("policy_terms_invalid")
        if lower <= days and (upper is None or days <= upper):
            found.append(tier)
    if len(found) != 1:
        raise ValueError(
            "policy_terms_undefined" if not found else "policy_terms_invalid"
        )
    return found[0]


def validate_policy(
    state: dict,
    path: str,
    payment_type: str,
    count: int,
    discount: Decimal,
    down_payment_amount: str = "0",
) -> dict:
    snapshot = state.get("snapshot_id")
    receipt = state.get("receipts", {}).get(path)
    if not snapshot or not receipt:
        raise ValueError("policy_read_required")
    canonical, content_hash, meta = read_policy_document(snapshot, path)
    if receipt.get("hash") != content_hash or receipt.get("snapshot_id") != snapshot:
        raise ValueError("policy_receipt_mismatch")
    require_canonical_policy(state, canonical, content_hash, meta)
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
    policy = terms_for_payment_type(meta.get("negotiation"), payment_type)
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
    max_installments = policy["max_installments"]
    if "max_discount_tiers" in policy:
        tier = overdue_tier(policy["max_discount_tiers"], debt_days_overdue(fixture))
        if set(tier) != {
            "min_days_overdue",
            "max_days_overdue",
            "max_discount_percentage",
        }:
            raise ValueError("policy_terms_invalid")
        tier_maximum = money(tier["max_discount_percentage"])
        if tier_maximum > maximum:
            raise ValueError("policy_terms_invalid")
        if discount > tier_maximum:
            raise ValueError("policy_terms_exceeded")
        if discount and policy.get("discount_basis") != "current_amount":
            raise ValueError("policy_terms_undefined")
    entry_rule = policy.get("down_payment", {})
    if not isinstance(entry_rule, dict) or set(entry_rule) - {
        "allowed",
        "min_percentage",
        "min_amount",
    }:
        raise ValueError("policy_terms_invalid")
    allowed_entry = entry_rule.get("allowed", False)
    if type(allowed_entry) is not bool:
        raise ValueError("policy_terms_invalid")
    minimum_percentage = money(entry_rule.get("min_percentage", "0"))
    if minimum_percentage > 100:
        raise ValueError("policy_terms_invalid")
    entry_required = False
    if payment_type == "installment" and "installment_tiers" in policy:
        tier = overdue_tier(policy["installment_tiers"], debt_days_overdue(fixture))
        if (
            set(tier) != {"min_days_overdue", "max_days_overdue", "max_installments"}
            or type(tier["max_installments"]) is not int
            or not 2 <= tier["max_installments"] <= max_installments
        ):
            raise ValueError("policy_terms_invalid")
        max_installments = tier["max_installments"]
        entry_required = True
        allowed_entry = True
    if payment_type == "installment" and "installment_overdue_rule" in policy:
        rule = policy["installment_overdue_rule"]
        if (
            not isinstance(rule, dict)
            or set(rule)
            != {"min_days_overdue", "max_installments", "min_down_payment_percentage"}
            or type(rule["min_days_overdue"]) is not int
            or rule["min_days_overdue"] < 0
            or type(rule["max_installments"]) is not int
            or not 1 <= rule["max_installments"] <= 360
            or not 0 < money(rule["min_down_payment_percentage"]) <= 100
        ):
            raise ValueError("policy_terms_invalid")
        if debt_days_overdue(fixture) >= rule["min_days_overdue"]:
            max_installments = rule["max_installments"]
            minimum_percentage = money(rule["min_down_payment_percentage"])
            entry_required = True
            allowed_entry = True
    if (
        payment_type not in policy["payment_types"]
        or type(count) is not int
        or count < 1
        or count > max_installments
        or discount > maximum
        or (
            ("discount_tiers" in policy or "by_payment_type" in policy)
            and "max_discount_tiers" not in policy
            and discount > offered
        )
    ):
        raise ValueError("policy_terms_exceeded")
    # Compare the smallest actual installment after cent rounding, not an average.
    total = (
        money(fixture.get("debt", {}).get("current_amount", 0)) * (1 - discount / 100)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    entry = money(down_payment_amount)
    if entry != entry.quantize(Decimal("0.01")):
        raise ValueError("invalid_down_payment")
    if entry and (payment_type != "installment" or count < 2 or entry >= total):
        raise ValueError("invalid_down_payment")
    if entry and not allowed_entry:
        raise ValueError("down_payment_not_allowed")
    minimum_entry = (total * minimum_percentage / 100).quantize(
        Decimal("0.01"), rounding=ROUND_CEILING
    )
    minimum_entry = max(minimum_entry, money(entry_rule.get("min_amount", "0")))
    if (entry_required or entry > 0) and entry < minimum_entry:
        raise DownPaymentRequired(minimum_entry)
    if "min_negotiated_amount" in policy and total < money(
        policy["min_negotiated_amount"]
    ):
        raise ValueError("negotiated_amount_below_minimum")
    if payment_type == "installment" and "min_installment_amount" in policy:
        smallest = Decimal(int((total - entry) * 100) // (count - bool(entry))) / 100
        if smallest < money(policy["min_installment_amount"]):
            raise ValueError("installment_amount_below_minimum")
    return {
        "path": canonical,
        "content_hash": receipt["hash"],
        "snapshot_id": snapshot,
        "offer_discount_percentage": format(
            (discount if "max_discount_tiers" in policy else offered).normalize(), "f"
        ),
    }
