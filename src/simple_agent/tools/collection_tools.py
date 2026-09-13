from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import uuid4

from langchain_core.tools import tool
from simple_agent.services.simulator_store import SimulatorStore

store = SimulatorStore()


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


@tool
def get_customer(cpf: str) -> str:
    """Return the configured simulator customer and debt when the CPF matches."""
    fixture = store.load()
    requested = _digits(cpf)
    configured = _digits(str(fixture.get("cpf") or ""))
    if not requested or requested != configured:
        return json.dumps({"found": False, "reason": "customer_not_found"}, ensure_ascii=False)
    debt = fixture.get("debt") if isinstance(fixture.get("debt"), dict) else {}
    payload = {
        "found": True,
        "customer_id": fixture.get("customer_id"),
        "full_name": fixture.get("full_name"),
        "cpf": configured,
        "birth_date": fixture.get("birth_date"),
        "identity_validated": bool(fixture.get("identity_validated", False)),
        "institution": fixture.get("institution"),
        "product": fixture.get("product"),
        "debt": {**debt, "days_overdue": store.days_overdue(str(debt.get("due_date") or ""))},
        "eligibility": fixture.get("eligibility", {}),
    }
    return json.dumps(payload, ensure_ascii=False)


@tool
def generate_offer(payment_type: Literal["cash", "installment"], installments: int = 1, discount_percentage: float = 0.0) -> str:
    """Calculate a simulator offer from current debt and customer eligibility.

    Consult applicable OKF policy before choosing terms. This tool does not define institutional policy.
    """
    fixture = store.load()
    debt = fixture.get("debt") if isinstance(fixture.get("debt"), dict) else {}
    eligibility = fixture.get("eligibility") if isinstance(fixture.get("eligibility"), dict) else {}
    if not bool(eligibility.get("can_negotiate", False)):
        return json.dumps({"available": False, "reason": "customer_not_eligible"}, ensure_ascii=False)

    max_installments = int(eligibility.get("max_installments", 1) or 1)
    max_discount = Decimal(str(eligibility.get("max_discount_percentage", 0) or 0))
    discount = Decimal(str(discount_percentage))
    if payment_type == "cash":
        installments = 1
    if installments < 1 or installments > max_installments:
        return json.dumps({"available": False, "reason": "installments_exceed_customer_eligibility", "max_installments": max_installments}, ensure_ascii=False)
    if discount < 0 or discount > max_discount:
        return json.dumps({"available": False, "reason": "discount_exceeds_customer_eligibility", "max_discount_percentage": float(max_discount)}, ensure_ascii=False)

    current = Decimal(str(debt.get("current_amount", 0) or 0))
    discount_amount = current * discount / Decimal("100")
    total = current - discount_amount
    installment_value = total / Decimal(installments)
    return json.dumps({
        "available": True,
        "offer_id": f"OFF-{uuid4().hex[:8].upper()}",
        "customer_id": fixture.get("customer_id"),
        "debt_id": debt.get("debt_id"),
        "payment_type": payment_type,
        "debt_amount": _money(current),
        "discount_percentage": float(discount),
        "discount_amount": _money(discount_amount),
        "negotiated_amount": _money(total),
        "installments": installments,
        "installment_amount": _money(installment_value),
        "status": "available",
    }, ensure_ascii=False)


COLLECTION_TOOLS = [get_customer, generate_offer]
