"""Tier boundaries and the actual offer/payment path, using synthetic data only."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

import pytest
import yaml

from simple_agent.services.offer_policy import resolve_offer_discount, validate_policy
from simple_agent.services.session_store import SessionStore
from simple_agent.tools import payment_tools
from .test_collection_identity_gates import runtime, call, verify
from .test_pilot_journeys import seed, read_policy, PATH

TIERS = {
    "max_discount_percentage": "10",
    "discount_tiers": [
        {
            "min_days_overdue": 0,
            "max_days_overdue": 30,
            "offer_discount_percentage": "5",
        },
        {
            "min_days_overdue": 31,
            "max_days_overdue": 90,
            "offer_discount_percentage": "8",
        },
        {
            "min_days_overdue": 91,
            "max_days_overdue": 180,
            "offer_discount_percentage": "10",
        },
        {
            "min_days_overdue": 181,
            "max_days_overdue": None,
            "offer_discount_percentage": "10",
        },
    ],
}


@pytest.mark.parametrize(
    "days,discount,total",
    [
        (0, "5", "5579.75"),
        (30, "5", "5579.75"),
        (31, "8", "5403.55"),
        (90, "8", "5403.55"),
        (91, "10", "5286.08"),
        (180, "10", "5286.08"),
        (181, "10", "5286.08"),
    ],
)
@pytest.mark.parametrize("method", ["pix", "boleto"])
def test_tier_generates_correct_cash_payment(isolated, days, discount, total, method):
    seed(isolated, approve=True)
    source = isolated.bundle_root(isolated.active_bundle_id()) / PATH
    _, header, body = source.read_text().split("---", 2)
    meta = yaml.safe_load(header)
    meta["negotiation"].pop("offer_discount_percentage")
    meta["negotiation"].update(deepcopy(TIERS))
    source.write_text("---\n" + yaml.safe_dump(meta) + "---" + body)
    key = f"tier-{days}-{method}"
    rt = runtime(key, f"Quero pagar à vista por {method}")
    assert verify(rt)["verified"]
    with SessionStore().transaction(key) as state:
        state["fixture"]["debt"]["days_overdue"] = days
    read_policy(rt)
    args = dict(payment_type="cash", method=method, policy_path=PATH)
    result = call(payment_tools.generate_payment_offer, rt, **args)
    assert result["created"], result
    assert result["offer"]["discount_percentage"] == discount
    assert result["offer"]["negotiated_amount"] == total
    assert result["payment"]["amount"] == total
    assert result["payment"]["method"] == method
    assert call(payment_tools.generate_payment_offer, rt, **args) == result
    if days < 91:
        with SessionStore().transaction(key) as state:
            with pytest.raises(ValueError, match="policy_terms_exceeded"):
                validate_policy(state, PATH, "cash", 1, Decimal("10"))


def test_due_date_and_trusted_days():
    due = (date.today() - timedelta(days=31)).isoformat()
    assert resolve_offer_discount(TIERS, {"debt": {"due_date": due}}) == Decimal("8")
    assert resolve_offer_discount(
        TIERS, {"debt": {"due_date": due, "days_overdue": 30}}
    ) == Decimal("5")
    future = (date.today() + timedelta(days=1)).isoformat()
    assert resolve_offer_discount(TIERS, {"debt": {"due_date": future}}) == Decimal("5")


@pytest.mark.parametrize(
    "debt",
    [
        {},
        {"due_date": "invalid"},
        {"days_overdue": -1},
        {"days_overdue": True},
        {"days_overdue": "31"},
    ],
)
def test_missing_or_invalid_debt_never_defaults_to_a_discount(debt):
    with pytest.raises(ValueError, match="debt_context_required"):
        resolve_offer_discount(TIERS, {"debt": debt})


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(offer_discount_percentage="10"),
        lambda p: p.update(discount_tiers=[]),
        lambda p: p.update(discount_tiers={}),
        lambda p: p["discount_tiers"][1].update(min_days_overdue=30),
        lambda p: p["discount_tiers"][1].update(min_days_overdue=32),
        lambda p: p["discount_tiers"][1].update(max_days_overdue=None),
        lambda p: p["discount_tiers"][-1].update(max_days_overdue=365),
        lambda p: p["discount_tiers"][-1].update(offer_discount_percentage="11"),
        lambda p: p["discount_tiers"][-1].pop("max_days_overdue"),
        lambda p: p["discount_tiers"].reverse(),
    ],
)
def test_invalid_tier_table_fails_even_when_bad_row_is_not_selected(change):
    policy = deepcopy(TIERS)
    change(policy)
    with pytest.raises(ValueError, match="policy_terms_invalid"):
        resolve_offer_discount(policy, {"debt": {"days_overdue": 10}})
