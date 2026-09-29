"""Post-stream numeric checks for the synthetic Playground, NOT an output gate.

Only explicit BRL/percentage figures are checked. No semantic entailment claim.
Displayed text is never retracted or retried; action authorization stays in tools.
"""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from simple_agent.services.offer_policy import money

BRL = re.compile(r"R\$\s*([0-9]+(?:[.,][0-9]+)*)", re.IGNORECASE)
PERCENT = re.compile(r"(?<![\w.,])([0-9]+(?:[.,][0-9]+)?)\s*%")


def _number(text: str) -> Decimal:
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    return Decimal(text)


def audit_response(text: str, session: dict) -> dict:
    report = {
        "mode": "post_stream",
        "status": "not_evaluated",
        "issues": [],
        "checks": ["explicit_brl", "explicit_percentage"],
        "semantic_fidelity": "not_evaluated",
        "pre_display_protection": False,
    }
    try:
        amounts = {_number(m.group(1)) for m in BRL.finditer(text)}
        percentages = {_number(m.group(1)) for m in PERCENT.finditer(text)}
    except InvalidOperation:
        report["status"] = "review_required"
        report["issues"] = ["numeric_format_requires_review"]
        return report
    if not amounts and not percentages:
        return report
    allowed_amounts: set[Decimal] = set()
    allowed_percentages: set[Decimal] = set()
    if session.get("identity_verified"):
        debt = session.get("fixture", {}).get("debt", {})
        # A balance is a fact only after the customer tool has returned it.
        if session.get("debt_read"):
            allowed_amounts.update(
                money(debt[k])
                for k in ("current_amount", "original_amount")
                if k in debt
            )
        now = datetime.now(timezone.utc)
        for offer in session.get("offers", {}).values():
            if offer.get("snapshot_id") != session.get(
                "snapshot_id"
            ) or now >= datetime.fromisoformat(offer["expires_at"]):
                continue
            allowed_amounts.update(
                money(offer[k])
                for k in (
                    "debt_amount",
                    "discount_amount",
                    "negotiated_amount",
                    "installment_amount",
                )
            )
            allowed_amounts.update(map(money, offer["installment_schedule"]))
            allowed_percentages.add(money(offer["discount_percentage"]))
    if amounts - allowed_amounts:
        report["issues"].append("amount_without_matching_authorized_result")
    if percentages - allowed_percentages:
        # May be a perfectly valid policy quotation: flag for review, not a verdict.
        report["issues"].append("percentage_requires_source_review")
    report["status"] = (
        "review_required" if report["issues"] else "no_numeric_mismatch_detected"
    )
    return report
