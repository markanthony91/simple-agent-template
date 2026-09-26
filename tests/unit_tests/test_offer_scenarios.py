"""Expanded synthetic regression matrix; external delivery is always mocked."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from simple_agent.services.channel_console import ChannelConsoleError
from simple_agent.services.session_store import SessionStore
from simple_agent.tools import payment_tools
from .test_collection_identity_gates import runtime, verify, call
from .test_pilot_journeys import seed, read_policy, PATH, assert_no_financial_action


def prepared(store, key="matrix"):
    seed(store, approve=True)
    rt = runtime(key, "Quero pagar")
    assert verify(rt)["verified"]
    read_policy(rt)
    return rt


def generate(rt, kind="installment", method="boleto", count=3):
    return call(
        payment_tools.generate_payment_offer,
        rt,
        payment_type=kind,
        method=method,
        installments=count,
        policy_path=PATH,
    )


@pytest.mark.parametrize(
    "kind,method,count,reason",
    [
        ("cash", "pix", 1, None),
        ("cash", "boleto", 1, None),
        ("installment", "boleto", 1, None),
        ("installment", "boleto", 2, None),
        ("installment", "boleto", 3, None),
        ("installment", "boleto", 4, "policy_terms_exceeded"),
        ("installment", "boleto", 360, "policy_terms_exceeded"),
        ("installment", "pix", 2, "payment_method_not_allowed"),
        ("installment", "pix", 3, "payment_method_not_allowed"),
        ("cash", "pix", 2, "invalid_payment_terms"),
        ("installment", "boleto", None, "offer_terms_missing"),
    ],
)
def test_modality_matrix(isolated, kind, method, count, reason):
    rt = prepared(isolated)
    result = generate(rt, kind, method, count)
    if reason:
        assert result["created"] is False and result["reason"] == reason
        assert_no_financial_action("matrix")
    else:
        assert result["created"] is True
        assert result["offer"]["installments"] == count
        schedule = list(map(Decimal, result["offer"]["installment_schedule"]))
        assert sum(schedule) == Decimal(result["offer"]["negotiated_amount"])
        assert max(schedule) - min(schedule) <= Decimal("0.01")
        assert result["payment"]["method"] == method


@pytest.mark.parametrize(
    "before,after,reason",
    [
        ("status: published", "status: draft", "policy_not_published"),
        (
            'effective_from: "2026-01-01T00:00:00Z"',
            'effective_from: "2099-01-01T00:00:00Z"',
            "policy_not_current",
        ),
        (
            'effective_until: "2027-01-01T00:00:00Z"',
            'effective_until: "2000-01-01T00:00:00Z"',
            "policy_not_current",
        ),
        ("institution: Will Bank", "institution: Other", "policy_scope_mismatch"),
        ("product: cartao_de_credito", "product: other", "policy_scope_mismatch"),
        ('  offer_discount_percentage: "0"\n', "", "policy_terms_undefined"),
    ],
)
def test_policy_matrix(isolated, before, after, reason):
    rt = prepared(isolated)
    source = isolated.bundle_root(isolated.active_bundle_id()) / PATH
    source.write_text(source.read_text().replace(before, after))
    read_policy(rt)
    result = generate(rt)
    assert result["reason"] == reason
    assert_no_financial_action("matrix")


@pytest.mark.parametrize(
    "restriction,value,reason",
    [
        ("can_negotiate", False, "customer_not_eligible"),
        ("max_installments", 2, "customer_eligibility_exceeded"),
    ],
)
def test_individual_restriction_still_applies(isolated, restriction, value, reason):
    rt = prepared(isolated)
    with SessionStore().transaction("matrix") as state:
        state["fixture"]["eligibility"][restriction] = value
    assert generate(rt)["reason"] == reason
    assert_no_financial_action("matrix")


def test_parallel_replays_create_exactly_one_payment(isolated):
    rt = prepared(isolated)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: generate(rt), range(4)))
    assert all(result == results[0] for result in results)
    state = SessionStore().read("matrix")
    assert (
        len(state["offers"]) == len(state["agreements"]) == len(state["payments"]) == 1
    )


def test_payment_and_email_cannot_cross_sessions(isolated):
    rt = prepared(isolated)
    payment_id = generate(rt)["payment"]["payment_id"]
    other = runtime("other", "Envie para test@example.com")
    assert verify(other)["verified"]
    assert (
        call(payment_tools.get_payment_status, other, payment_id=payment_id)["reason"]
        == "payment_not_found"
    )
    assert (
        call(
            payment_tools.send_payment_instruction,
            other,
            payment_id=payment_id,
            email="test@example.com",
        )["reason"]
        == "valid_payment_required"
    )
    assert_no_financial_action("other")


@pytest.mark.parametrize("outcome", ["accepted", "failed", "unknown"])
def test_email_outcomes_and_replay_never_claim_false_success(
    isolated, monkeypatch, outcome
):
    rt = prepared(isolated)
    payment_id = generate(rt, "cash", "pix", 1)["payment"]["payment_id"]
    dispatched = []
    monkeypatch.setattr(payment_tools, "_email_plan", lambda context: ({}, context))

    def dispatch(*args):
        dispatched.append(1)
        return {"sent": outcome == "accepted", "status": outcome}

    monkeypatch.setattr(payment_tools, "_dispatch_email", dispatch)
    email_rt = runtime("matrix", "Envie para test@example.com", "email")
    args = {"payment_id": payment_id, "email": "test@example.com"}
    result = call(payment_tools.send_payment_instruction, email_rt, **args)
    assert result["sent"] is (outcome == "accepted")
    assert result["status"] == outcome
    assert call(payment_tools.send_payment_instruction, email_rt, **args) == result
    assert len(dispatched) == 1
    assert (
        call(payment_tools.get_payment_status, email_rt, payment_id=payment_id)[
            "status"
        ]
        == "pending"
    )


def test_email_catalog_failure_does_not_dispatch(isolated, monkeypatch):
    rt = prepared(isolated)
    payment_id = generate(rt)["payment"]["payment_id"]

    def fail(context):
        raise ChannelConsoleError("email_channel_not_configured")

    monkeypatch.setattr(payment_tools, "_email_plan", fail)
    email_rt = runtime("matrix", "test@example.com", "email")
    result = call(
        payment_tools.send_payment_instruction,
        email_rt,
        payment_id=payment_id,
        email="test@example.com",
    )
    assert result == {"sent": False, "reason": "email_channel_not_configured"}
    assert not SessionStore().read("matrix")["deliveries"]


@pytest.mark.xfail(
    strict=True,
    reason="Existing demo settlement closes the agreement after only its first installment; outside this release",
)
def test_partial_settlement_should_not_close_installment_agreement(isolated):
    rt = prepared(isolated)
    result = generate(rt)
    payment_tools.simulate_payment_settled("matrix", result["payment"]["payment_id"])
    agreement = SessionStore().read("matrix")["agreements"][result["offer"]["offer_id"]]
    assert agreement["status"] != "settled"
