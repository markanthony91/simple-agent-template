import json
from decimal import Decimal

import pytest
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage

from simple_agent.services.session_store import SessionStore
from simple_agent.tools import collection_tools as tools
from simple_agent.tools.okf_tools import okf_read


def runtime(key="a", text="Simule três parcelas", message_id="m1"):
    return ToolRuntime(
        state={"messages": [HumanMessage(content=text, id=message_id)]},
        context={},
        config={"configurable": {"thread_id": key}},
        stream_writer=lambda _: None,
        tool_call_id="call",
        store=None,
    )


def call(tool, rt, **args):
    return json.loads(tool.func(runtime=rt, **args))


POLICY = """---
type: Policy
status: published
institution: FastPay
product: cartao_de_credito
negotiation:
  max_installments: 10
  max_discount_percentage: "20"
  payment_types: [cash, installment]
---
# Synthetic policy
For tests only: up to ten installments, discount ceiling twenty percent.
"""
PATH = "INSTITUTIONS/fastpay/policy.md"


@pytest.fixture
def policy(isolated):
    isolated.import_bundle(
        "synthetic",
        "0.2",
        {
            "index.md": "# Test\n[Policy](INSTITUTIONS/fastpay/policy.md)",
            PATH: POLICY,
        },
    )
    return isolated


def verify(rt):
    return call(
        tools.verify_customer_identity, rt, cpf="12345678900", full_name="João da Silva"
    )


def test_data_hidden_and_verification_isolated(policy):
    a, b = runtime(), runtime("b")
    assert (
        call(tools.get_customer, a, cpf="12345678900")["financial_data_available"]
        is False
    )
    assert verify(a)["verified"]
    data = call(tools.get_customer, a, cpf="12345678900")
    assert data["debt"]["current_amount"] == "5873.42"
    assert "eligibility" not in data and "birth_date" not in data
    assert "debt" not in call(tools.get_customer, b, cpf="12345678900")
    assert call(tools.verify_customer_identity, a, cpf="wrong")["verified"] is False
    assert "debt" not in call(tools.get_customer, a, cpf="12345678900")


def test_offer_requires_identity_and_policy_receipt(policy):
    rt = runtime()
    args = {"payment_type": "installment", "installments": 3, "policy_path": PATH}
    assert (
        call(tools.generate_offer, rt, **args)["reason"]
        == "identity_verification_required"
    )
    verify(rt)
    assert call(tools.generate_offer, rt, **args)["reason"] == "policy_read_required"
    okf_read.func(path=PATH, runtime=rt)
    offer = call(tools.generate_offer, rt, **args)
    assert offer["available"]
    assert sum(map(Decimal, offer["installment_schedule"])) == Decimal(
        offer["negotiated_amount"]
    )
    assert call(tools.generate_offer, rt, **args)["offer_id"] == offer["offer_id"]
    denied = call(tools.generate_offer, rt, **{**args, "discount_percentage": "99"})
    assert denied["available"] is False


def test_explicit_confirmation_and_replay(policy):
    rt = runtime()
    verify(rt)
    okf_read.func(path=PATH, runtime=rt)
    offer = call(tools.generate_offer, rt, payment_type="cash", policy_path=PATH)
    args = {"offer_id": offer["offer_id"], "explicit_confirmation": True}
    assert (
        call(tools.create_agreement, rt, **args)["reason"]
        == "explicit_user_confirmation_required"
    )
    confirmed = runtime(text=f"CONFIRMAR ACORDO {offer['offer_id']}", message_id="m2")
    first = call(tools.create_agreement, confirmed, **args)
    assert first["created"]
    assert call(tools.create_agreement, confirmed, **args) == first
    assert call(tools.create_agreement, runtime("b"), **args)["created"] is False


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("expiry", "offer_expired"),
        ("hash", "policy_receipt_mismatch"),
        ("snapshot", "policy_receipt_mismatch"),
    ],
)
def test_stale_offer_blocked(policy, mutation, reason):
    rt = runtime()
    verify(rt)
    okf_read.func(path=PATH, runtime=rt)
    offer = call(tools.generate_offer, rt, payment_type="cash", policy_path=PATH)
    with SessionStore().transaction("a") as state:
        if mutation == "expiry":
            next(iter(state["offers"].values()))["expires_at"] = (
                "2000-01-01T00:00:00+00:00"
            )
        else:
            state["receipts"][PATH]["hash" if mutation == "hash" else "snapshot_id"] = (
                "incorrect"
            )
    result = call(
        tools.create_agreement,
        runtime(text=f"CONFIRMAR ACORDO {offer['offer_id']}", message_id="m2"),
        offer_id=offer["offer_id"],
        explicit_confirmation=True,
    )
    assert result["reason"] == reason


def test_snapshot_and_fixture_stay_pinned(policy):
    rt = runtime()
    verify(rt)
    with SessionStore().transaction("a") as old:
        snapshot = old["snapshot_id"]
    policy.import_bundle("new", "0.2", {"index.md": "# New"})
    assert "Synthetic policy" in okf_read.func(path=PATH, runtime=rt)
    with SessionStore().transaction("a") as state:
        assert state["snapshot_id"] == snapshot
    with SessionStore().transaction("b") as state:
        assert state["snapshot_id"] != snapshot
        assert not state["identity_verified"]


def test_runtime_hidden_from_model_schema():
    for tool in tools.COLLECTION_TOOLS:
        schema = tool.tool_call_schema.model_json_schema()
        assert "runtime" not in schema["properties"]
        assert "thread_id" not in schema["properties"]

    from simple_agent.tools.payment_tools import PAYMENT_TOOLS

    for tool in PAYMENT_TOOLS:
        schema = tool.tool_call_schema.model_json_schema()
        assert "runtime" not in schema["properties"]
        assert "thread_id" not in schema["properties"]
