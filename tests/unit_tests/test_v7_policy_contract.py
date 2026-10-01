"""The v7 overdue limits authorize only the declared terms."""

import yaml

from simple_agent.services.session_store import SessionStore
from simple_agent.tools.payment_tools import generate_payment_offer

from .test_collection_identity_gates import call
from .test_modality_policy_contract import prepare
from .test_pilot_journeys import PATH, read_policy


def v7_offer(store, key, days, basis=None, **terms):
    rt, _ = prepare(store, key, days=days)
    path = store.bundle_root(store.active_bundle_id()) / PATH
    _, header, body = path.read_text().split("---", 2)
    meta = yaml.safe_load(header)
    meta["negotiation"] = {
        "payment_types": ["cash", "installment"],
        "max_installments": 4,
        "max_discount_percentage": "80",
        "min_negotiated_amount": "50.00",
        "min_installment_amount": "50.00",
        "down_payment": {"allowed": True, "min_amount": "50.00"},
        "installment_tiers": [
            {"min_days_overdue": 1, "max_days_overdue": 120, "max_installments": 2},
            {"min_days_overdue": 121, "max_days_overdue": 180, "max_installments": 4},
            {"min_days_overdue": 182, "max_days_overdue": None, "max_installments": 4},
        ],
        "by_payment_type": {
            "cash": {
                "max_discount_percentage": "80",
                "max_discount_tiers": [
                    {
                        "min_days_overdue": 1,
                        "max_days_overdue": 120,
                        "max_discount_percentage": "60",
                    },
                    {
                        "min_days_overdue": 121,
                        "max_days_overdue": 180,
                        "max_discount_percentage": "70",
                    },
                    {
                        "min_days_overdue": 182,
                        "max_days_overdue": None,
                        "max_discount_percentage": "80",
                    },
                ],
            },
            "installment": {
                "max_discount_percentage": "50",
                "max_discount_tiers": [
                    {
                        "min_days_overdue": 1,
                        "max_days_overdue": 120,
                        "max_discount_percentage": "30",
                    },
                    {
                        "min_days_overdue": 121,
                        "max_days_overdue": 180,
                        "max_discount_percentage": "40",
                    },
                    {
                        "min_days_overdue": 182,
                        "max_days_overdue": None,
                        "max_discount_percentage": "50",
                    },
                ],
            },
        },
    }
    meta["payment"] = {
        "methods": ["pix", "boleto"],
        "methods_by_payment_type": {
            "cash": ["pix", "boleto"],
            "installment": ["boleto"],
        },
        "delivery_channels": ["email"],
    }
    if basis:
        meta["negotiation"]["by_payment_type"]["cash"]["discount_basis"] = basis
    path.write_text("---\n" + yaml.safe_dump(meta) + "---" + body)
    with SessionStore().transaction(key) as state:
        state["fixture"]["eligibility"].update(max_discount_percentage=80)
    read_policy(rt)
    return call(generate_payment_offer, rt, policy_path=PATH, **terms)


def test_v7_pix_and_boleto_and_boundaries(isolated):
    pix = v7_offer(isolated, "v7-pix", 174, payment_type="cash", method="pix")
    assert pix["created"] and pix["offer"]["discount_percentage"] == "0"
    boleto = v7_offer(
        isolated,
        "v7-boleto",
        174,
        payment_type="installment",
        method="boleto",
        installments=4,
        down_payment_amount="50.00",
    )
    assert boleto["created"] and boleto["offer"]["installment_schedule"] == [
        "50.00",
        "1941.14",
        "1941.14",
        "1941.14",
    ]
    missing = v7_offer(
        isolated,
        "v7-entry",
        174,
        payment_type="installment",
        method="boleto",
        installments=4,
    )
    assert missing == {
        "created": False,
        "reason": "down_payment_required",
        "minimum_down_payment_amount": "50.00",
    }
    excess = v7_offer(
        isolated,
        "v7-too-many",
        50,
        payment_type="installment",
        method="boleto",
        installments=4,
        down_payment_amount="50.00",
    )
    assert excess == {"created": False, "reason": "policy_terms_exceeded"}
    missing_basis = v7_offer(
        isolated,
        "v7-discount",
        174,
        payment_type="cash",
        method="pix",
        discount_percentage="20",
    )
    assert missing_basis == {"created": False, "reason": "policy_terms_undefined"}
    discounted = v7_offer(
        isolated,
        "v7-discount-declared",
        174,
        basis="current_amount",
        payment_type="cash",
        method="pix",
        discount_percentage="20",
    )
    assert discounted["created"] and discounted["offer"]["discount_percentage"] == "20"
    out_of_range = v7_offer(
        isolated,
        "v7-discount-cap",
        174,
        basis="current_amount",
        payment_type="cash",
        method="pix",
        discount_percentage="71",
    )
    assert out_of_range == {"created": False, "reason": "policy_terms_exceeded"}
    day_181 = v7_offer(isolated, "v7-gap", 181, payment_type="cash", method="pix")
    assert day_181 == {"created": False, "reason": "policy_terms_undefined"}
