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


def _mask_document(value: str) -> str:
    digits = _digits(value)
    return f"***.***.***-{digits[-2:]}" if len(digits) >= 2 else "***"


def _runtime_state(fixture: dict) -> dict:
    state = fixture.get("_runtime")
    return state if isinstance(state, dict) else {}


@tool
def get_customer(cpf: str) -> str:
    """Return the configured simulator customer and debt when the document matches."""
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
        "cpf": _mask_document(configured),
        "birth_date": fixture.get("birth_date"),
        "identity_validated": bool(_runtime_state(fixture).get("identity_verified", fixture.get("identity_validated", False))),
        "institution": fixture.get("institution"),
        "product": fixture.get("product"),
        "debt": {**debt, "days_overdue": store.days_overdue(str(debt.get("due_date") or ""))},
        "eligibility": fixture.get("eligibility", {}),
    }
    return json.dumps(payload, ensure_ascii=False)


@tool
def verify_customer_identity(cpf: str, full_name: str = "", birth_date: str = "") -> str:
    """Verify a simulator customer using document plus at least one secondary field."""
    fixture = store.load()
    requested = _digits(cpf)
    configured = _digits(str(fixture.get("cpf") or ""))
    if not requested or requested != configured:
        return json.dumps({"verified": False, "reason": "identity_not_matched"}, ensure_ascii=False)

    checks = []
    if full_name.strip():
        checks.append(full_name.strip().casefold() == str(fixture.get("full_name") or "").strip().casefold())
    if birth_date.strip():
        checks.append(birth_date.strip() == str(fixture.get("birth_date") or "").strip())
    if not checks:
        return json.dumps({"verified": False, "reason": "secondary_factor_required"}, ensure_ascii=False)
    if not any(checks):
        return json.dumps({"verified": False, "reason": "secondary_factor_not_matched"}, ensure_ascii=False)

    runtime = _runtime_state(fixture)
    runtime["identity_verified"] = True
    runtime["verification_id"] = f"VER-{uuid4().hex[:10].upper()}"
    fixture["_runtime"] = runtime
    store.save(fixture)
    return json.dumps({
        "verified": True,
        "verification_id": runtime["verification_id"],
        "customer_id": fixture.get("customer_id"),
        "cpf": _mask_document(configured),
    }, ensure_ascii=False)


@tool
def generate_offer(payment_type: Literal["cash", "installment"], installments: int = 1, discount_percentage: float = 0.0) -> str:
    """Calculate and persist a simulator offer from current debt and eligibility.

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
    offer = {
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
    }
    runtime = _runtime_state(fixture)
    offers = runtime.get("offers") if isinstance(runtime.get("offers"), dict) else {}
    offers[offer["offer_id"]] = offer
    runtime["offers"] = offers
    fixture["_runtime"] = runtime
    store.save(fixture)
    return json.dumps(offer, ensure_ascii=False)


@tool
def create_agreement(offer_id: str, explicit_confirmation: bool, confirmation_text: str = "") -> str:
    """Create a simulated agreement from a previously generated offer after explicit confirmation."""
    if explicit_confirmation is not True:
        return json.dumps({"created": False, "reason": "explicit_confirmation_required"}, ensure_ascii=False)
    fixture = store.load()
    runtime = _runtime_state(fixture)
    if not bool(runtime.get("identity_verified", fixture.get("identity_validated", False))):
        return json.dumps({"created": False, "reason": "identity_verification_required"}, ensure_ascii=False)
    offers = runtime.get("offers") if isinstance(runtime.get("offers"), dict) else {}
    offer = offers.get(offer_id)
    if not isinstance(offer, dict) or offer.get("status") != "available":
        return json.dumps({"created": False, "reason": "valid_offer_required"}, ensure_ascii=False)

    agreements = runtime.get("agreements") if isinstance(runtime.get("agreements"), dict) else {}
    existing = agreements.get(offer_id)
    if isinstance(existing, dict):
        return json.dumps(existing, ensure_ascii=False)

    agreement = {
        "created": True,
        "agreement_id": f"AGR-{uuid4().hex[:10].upper()}",
        "offer_id": offer_id,
        "customer_id": offer.get("customer_id"),
        "debt_id": offer.get("debt_id"),
        "status": "created",
        "payment_type": offer.get("payment_type"),
        "negotiated_amount": offer.get("negotiated_amount"),
        "installments": offer.get("installments"),
        "installment_amount": offer.get("installment_amount"),
        "confirmation_text": confirmation_text[:200] if confirmation_text else "explicit_confirmation=true",
    }
    agreements[offer_id] = agreement
    runtime["agreements"] = agreements
    offers[offer_id] = {**offer, "status": "accepted"}
    runtime["offers"] = offers
    fixture["_runtime"] = runtime
    store.save(fixture)
    return json.dumps(agreement, ensure_ascii=False)


COLLECTION_TOOLS = [get_customer, verify_customer_identity, generate_offer, create_agreement]
