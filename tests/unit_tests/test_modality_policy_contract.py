"""One canonical document must not apply cash discounts to installments."""

from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from simple_agent.services.offer_policy import terms_for_payment_type, validate_policy
from simple_agent.services.session_store import SessionStore
from simple_agent.tools.payment_tools import (
    generate_payment_offer,
    get_boleto_second_copy,
)
from .test_collection_identity_gates import runtime, call, verify
from .test_discount_tiers import TIERS
from .test_pilot_journeys import seed, read_policy, PATH, assert_no_financial_action


def prepare(store, key, amount="5873.42", days=168):
    seed(store, approve=True)
    path = store.bundle_root(store.active_bundle_id()) / PATH
    _, header, body = path.read_text().split("---", 2)
    meta = yaml.safe_load(header)
    meta["policy_role"] = "canonical"
    meta["negotiation"] = {
        "payment_types": ["cash", "installment"],
        "max_installments": 10,
        "max_discount_percentage": "10",
        "min_negotiated_amount": "50.00",
        "min_installment_amount": "200.00",
        "down_payment": {"allowed": True, "min_percentage": "10"},
        "by_payment_type": {
            "cash": deepcopy(TIERS),
            "installment": {
                "max_discount_percentage": "0",
                "offer_discount_percentage": "0",
            },
        },
    }
    path.write_text("---\n" + yaml.safe_dump(meta) + "---" + body)
    rt = runtime(key, "Quero a proposta nas condições escolhidas")
    assert verify(rt)["verified"]
    with SessionStore().transaction(key) as state:
        state["fixture"]["debt"].update(current_amount=amount, days_overdue=days)
    read_policy(rt)
    return rt, meta["negotiation"]


@pytest.mark.parametrize(
    "days,discount",
    [(0, "5"), (30, "5"), (31, "8"), (90, "8"), (91, "10"), (180, "10"), (181, "10")],
)
def test_one_canonical_preserves_cash_tiers_and_zero_installment_discount(
    isolated, days, discount
):
    cash, _ = prepare(isolated, "cash", days=days)
    pix = call(
        generate_payment_offer,
        cash,
        payment_type="cash",
        method="pix",
        policy_path=PATH,
    )
    assert pix["created"] and pix["offer"]["discount_percentage"] == discount
    installment, _ = prepare(isolated, "installment", days=days)
    boleto = call(
        generate_payment_offer,
        installment,
        payment_type="installment",
        installments=3,
        method="boleto",
        policy_path=PATH,
    )
    assert boleto["created"] and boleto["offer"]["discount_percentage"] == "0"
    assert boleto["offer"]["installment_schedule"] == ["1957.81", "1957.81", "1957.80"]
    copy = call(get_boleto_second_copy, installment)
    assert (
        copy["found"]
        and copy["payment"]["payment_code"] == boleto["payment"]["payment_code"]
    )
    state = SessionStore().read("installment")
    assert len(state["agreements"]) == len(state["payments"]) == 1
    with pytest.raises(ValueError, match="policy_terms_exceeded"):
        validate_policy(state, PATH, "installment", 3, Decimal("1"))


@pytest.mark.parametrize(
    "kind,count,method,amount,reason",
    [
        ("installment", 3, "pix", "5873.42", "payment_method_not_allowed"),
        ("installment", 11, "boleto", "5873.42", "policy_terms_exceeded"),
        ("installment", 3, "boleto", "599.99", "installment_amount_below_minimum"),
        ("cash", 1, "pix", "50.00", "negotiated_amount_below_minimum"),
    ],
)
def test_rejected_terms_never_persist_offer(
    isolated, kind, count, method, amount, reason
):
    rt, _ = prepare(isolated, "rejected", amount=amount)
    result = call(
        generate_payment_offer,
        rt,
        payment_type=kind,
        installments=count,
        method=method,
        policy_path=PATH,
    )
    assert result == {"created": False, "reason": reason}
    assert_no_financial_action("rejected")


def test_minimum_installment_exact_boundary(isolated):
    rt, _ = prepare(isolated, "boundary", amount="600.00")
    result = call(
        generate_payment_offer,
        rt,
        payment_type="installment",
        installments=3,
        method="boleto",
        policy_path=PATH,
    )
    assert (
        result["created"] and result["offer"]["installment_schedule"] == ["200.00"] * 3
    )


@pytest.mark.parametrize("days", [0, 30, 31, 90, 91, 180, 181])
def test_initial_discount_does_not_erase_overdue_tiers(isolated, days):
    rt, _ = prepare(isolated, "initial", days=days)
    path = isolated.bundle_root(isolated.active_bundle_id()) / PATH
    _, header, body = path.read_text().split("---", 2)
    meta = yaml.safe_load(header)
    cash = meta["negotiation"]["by_payment_type"]["cash"]
    cash["initial_offer_discount_percentage"] = "3"
    path.write_text("---\n" + yaml.safe_dump(meta) + "---" + body)
    read_policy(rt)
    result = call(
        generate_payment_offer, rt, payment_type="cash", method="pix", policy_path=PATH
    )
    assert result["created"] and result["offer"]["discount_percentage"] == "3"
    assert result["offer"]["negotiated_amount"] == "5697.22"
    assert cash["discount_tiers"] == TIERS["discount_tiers"]
    with pytest.raises(ValueError, match="policy_terms_exceeded"):
        validate_policy(SessionStore().read("initial"), PATH, "cash", 1, Decimal("5"))


@pytest.mark.parametrize("days,created", [(180, True), (181, False)])
def test_mandatory_down_payment_never_becomes_equal_installments(
    isolated, days, created
):
    rt, _ = prepare(isolated, "entry", days=days)
    path = isolated.bundle_root(isolated.active_bundle_id()) / PATH
    _, header, body = path.read_text().split("---", 2)
    meta = yaml.safe_load(header)
    meta["negotiation"]["installment_overdue_rule"] = {
        "min_days_overdue": 181,
        "max_installments": 12,
        "min_down_payment_percentage": "20",
    }
    path.write_text("---\n" + yaml.safe_dump(meta) + "---" + body)
    read_policy(rt)
    result = call(
        generate_payment_offer,
        rt,
        payment_type="installment",
        installments=3,
        method="boleto",
        policy_path=PATH,
    )
    assert result["created"] is created
    if not created:
        assert result["reason"] == "down_payment_required"
        assert result["minimum_down_payment_amount"] == "1174.69"
        assert_no_financial_action("entry")
        accepted = call(
            generate_payment_offer,
            rt,
            payment_type="installment",
            installments=3,
            method="boleto",
            policy_path=PATH,
            down_payment_amount="1174.69",
        )
        assert accepted["created"]
        assert accepted["offer"]["installment_schedule"] == [
            "1174.69",
            "2349.37",
            "2349.36",
        ]
        assert accepted["payment"]["is_down_payment"] is True


def test_optional_entry_is_atomic_idempotent_and_retrievable(isolated):
    from simple_agent.tools.payment_tools import _email_context

    rt, _ = prepare(isolated, "optional")
    args = dict(
        payment_type="installment",
        installments=3,
        method="boleto",
        policy_path=PATH,
        down_payment_amount="1000.00",
    )
    result = call(generate_payment_offer, rt, **args)
    assert result["created"]
    assert result["offer"]["installment_schedule"] == ["1000.00", "2436.71", "2436.71"]
    assert result["offer"]["negotiated_amount"] == "5873.42"
    assert result["agreement"]["down_payment_amount"] == "1000.00"
    assert result["payment"]["amount"] == "1000.00"
    assert call(generate_payment_offer, rt, **args) == result
    copy = call(get_boleto_second_copy, rt)
    assert copy["found"] and copy["is_down_payment"]
    assert copy["payment"]["payment_code"] == result["payment"]["payment_code"]
    state = SessionStore().read("optional")
    assert (
        len(state["offers"]) == len(state["agreements"]) == len(state["payments"]) == 1
    )
    email = _email_context(state, result["payment"], result["agreement"])
    assert email["numero_parcela"] == "1 (entrada)"
    assert "2ª parcela: R$ 2.436,71" in email["upcoming_installments"]
    from simple_agent.tools.payment_tools import (
        simulate_payment_settled,
        create_payment_instruction,
    )
    from simple_agent.tool_middleware import render_direct_reply

    rendered = render_direct_reply("generate_payment_offer", result)
    assert "Entrada (1ª parcela): R$ 1.000,00" in rendered
    simulate_payment_settled("optional", result["payment"]["payment_id"])
    agreement = next(iter(SessionStore().read("optional")["agreements"].values()))
    assert agreement["status"] == "payment_pending"
    for number in (2, 3):
        later = call(
            create_payment_instruction,
            rt,
            agreement_id=agreement["agreement_id"],
            method="boleto",
            installment_number=number,
        )
        assert later["created"]
        simulate_payment_settled("optional", later["payment_id"])
    agreement = next(iter(SessionStore().read("optional")["agreements"].values()))
    assert agreement["status"] == "settled"


@pytest.mark.parametrize(
    "entry,count,kind,reason",
    [
        ("10.00", 3, "installment", "down_payment_required"),
        ("5873.42", 3, "installment", "invalid_down_payment"),
        ("1000.001", 3, "installment", "invalid_down_payment"),
        ("1000", 1, "cash", "invalid_down_payment"),
        ("1000", 1, "installment", "invalid_down_payment"),
        ("5800", 3, "installment", "installment_amount_below_minimum"),
    ],
)
def test_invalid_entry_never_creates_records(isolated, entry, count, kind, reason):
    rt, _ = prepare(isolated, "bad-entry")
    result = call(
        generate_payment_offer,
        rt,
        payment_type=kind,
        installments=count,
        method="boleto",
        policy_path=PATH,
        down_payment_amount=entry,
    )
    assert not result["created"] and result["reason"] == reason
    assert_no_financial_action("bad-entry")


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(offer_discount_percentage="10"),
        lambda p: p.update(by_payment_type=[]),
        lambda p: p["by_payment_type"].pop("installment"),
        lambda p: p["by_payment_type"]["cash"].update(max_discount_percentage="11"),
        lambda p: p["by_payment_type"]["cash"].update(interest_percentage="1"),
    ],
)
def test_ambiguous_or_unsupported_contract_fails(isolated, change):
    _, policy = prepare(isolated, "contract")
    change(policy)
    with pytest.raises(ValueError, match="policy_terms_invalid"):
        terms_for_payment_type(policy, "cash")


@pytest.mark.parametrize(
    "kind,entry,days,expected",
    [
        ("cash", "0", 168, "5697.22"),
        ("installment", "0", 168, "1957.81"),
        ("installment", "1000.00", 168, "1000.00"),
        ("installment", "1200.00", 181, "1200.00"),
    ],
)
def test_actual_candidate_document_with_runtime_tools(
    isolated, kind, entry, days, expected
):
    rt, _ = prepare(isolated, "candidate", days=days)
    candidate = (
        Path(__file__).resolve().parents[2]
        / "docs/policy-contract/will-bank/politica-negociacao.md"
    )
    content = candidate.read_text()
    meta = yaml.safe_load(content.split("---", 2)[1])
    assert meta["policy_role"] == "canonical"
    assert meta["product"] == "cartao_de_credito"
    (isolated.bundle_root(isolated.active_bundle_id()) / PATH).write_text(content)
    with SessionStore().transaction("candidate") as state:
        state["fixture"]["institution"] = meta["institution"]
        state["fixture"]["product"] = meta["product"]
    read_policy(rt)
    result = call(
        generate_payment_offer,
        rt,
        payment_type=kind,
        installments=1 if kind == "cash" else 3,
        method="pix" if kind == "cash" else "boleto",
        policy_path=PATH,
        down_payment_amount=entry,
    )
    assert result["created"], result
    assert result["payment"]["amount"] == expected


@pytest.mark.parametrize("legacy_customer_limit", [10, 12])
def test_canonical_overdue_override_follows_published_policy(
    isolated, legacy_customer_limit
):
    rt, _ = prepare(isolated, "overdue-limit", days=181)
    candidate = (
        Path(__file__).resolve().parents[2]
        / "docs/policy-contract/will-bank/politica-negociacao.md"
    )
    (isolated.bundle_root(isolated.active_bundle_id()) / PATH).write_text(
        candidate.read_text()
    )
    with SessionStore().transaction("overdue-limit") as state:
        state["fixture"].update(institution="will-bank", product="cartao_de_credito")
        state["fixture"]["eligibility"]["max_installments"] = legacy_customer_limit
    read_policy(rt)
    result = call(
        generate_payment_offer,
        rt,
        payment_type="installment",
        installments=12,
        method="boleto",
        policy_path=PATH,
        down_payment_amount="1200.00",
    )
    assert result["created"] is True
    schedule = result["offer"]["installment_schedule"]
    assert len(schedule) == 12 and schedule[0] == "1200.00"
    assert sum(map(Decimal, schedule)) == Decimal("5873.42")
