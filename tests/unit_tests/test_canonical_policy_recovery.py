"""Auxiliary references guide the model; they never grant payment authorization."""

import asyncio
import json
from pathlib import PurePosixPath

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage

from simple_agent.services.session_store import SessionStore
from simple_agent.services.offer_policy import validate_policy, money
from simple_agent.tool_middleware import direct_reply
from simple_agent.tools.okf_tools import okf_read
from simple_agent.tools.payment_tools import generate_payment_offer
from .test_collection_identity_gates import runtime, verify, call
from .test_direct_replies import CountingModel
from .test_pilot_journeys import seed, PATH, assert_no_financial_action

AUX = str(PurePosixPath(PATH).parent / "limites-desconto.md")


def prepare(store, reference="negotiation.md"):
    seed(store, approve=True)
    root = store.bundle_root(store.active_bundle_id())
    # Local synthetic documents, never the published production bundle.
    source = root / AUX
    source.write_text(
        "---\npolicy_role: auxiliary\ncanonical_policy: "
        + json.dumps(reference)
        + "\n---\nAuxiliary discount guide.\n"
    )
    rt = runtime("canonical-test", "Quero pagar a vista por PIX")
    assert verify(rt)["verified"]
    okf_read.func(path=AUX, runtime=rt)
    return rt, root


def generate(rt, path=AUX):
    return call(
        generate_payment_offer,
        rt,
        payment_type="cash",
        method="pix",
        installments=1,
        policy_path=path,
    )


def offer(path, ident):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "generate_payment_offer",
                "id": ident,
                "args": {
                    "payment_type": "cash",
                    "method": "pix",
                    "installments": 1,
                    "policy_path": path,
                },
            }
        ],
    )


@pytest.mark.parametrize("async_run", [False, True])
def test_auxiliary_read_then_canonical_read_and_pix_without_new_question(
    isolated, async_run
):
    rt, _ = prepare(isolated)
    model = CountingModel(
        responses=[
            offer(AUX, "first"),
            AIMessage(
                content="",
                tool_calls=[{"name": "okf_read", "id": "read", "args": {"path": PATH}}],
            ),
            offer(PATH, "retry"),
        ]
    )
    graph = create_agent(
        model=model, tools=[generate_payment_offer, okf_read], middleware=[direct_reply]
    )
    args = (
        {"messages": [HumanMessage(content="Pix")]},
        {"configurable": {"thread_id": "canonical-test"}},
    )
    result = asyncio.run(graph.ainvoke(*args)) if async_run else graph.invoke(*args)
    messages = result["messages"]
    first = json.loads(next(m.content for m in messages if m.type == "tool"))
    assert first["reason"] == "canonical_policy_required"
    assert first["canonical_policy_path"] == PATH
    assert first["recoverable"] and "okf_read" in first["recovery"]
    assert "Proposta simulada criada com sucesso" in messages[-1].content
    assert [m.name for m in messages if m.type == "tool"] == [
        "generate_payment_offer",
        "okf_read",
        "generate_payment_offer",
    ]
    state = SessionStore().read("canonical-test")
    assert (
        len(state["offers"]) == len(state["agreements"]) == len(state["payments"]) == 1
    )
    payment = next(iter(state["payments"].values()))
    assert payment["method"] == "pix" and payment["policy_source"]["path"] == PATH


@pytest.mark.parametrize(
    "reference", ["negotiation.md", "./negotiation.md", PATH, PATH.upper()]
)
def test_reference_resolves_canonical_but_does_not_read_or_authorize(
    isolated, reference
):
    rt, _ = prepare(isolated, reference)
    assert generate(rt) == {
        "created": False,
        "reason": "canonical_policy_required",
        "canonical_policy_path": PATH,
    }
    state = SessionStore().read("canonical-test")
    assert PATH not in state["receipts"]
    assert generate(rt, PATH)["reason"] == "policy_read_required"
    assert_no_financial_action("canonical-test")
    with pytest.raises(ValueError, match="canonical_policy_required"):
        validate_policy(state, AUX, "cash", 1, money(0))


@pytest.mark.parametrize(
    "reference",
    [
        None,
        "",
        True,
        "../../outside.md",
        "/tmp/policy.md",
        "https://evil.invalid/p.md",
        "..\\outside.md",
        "negotiation.md#terms",
        "missing.md",
        "limites-desconto.md",
    ],
)
def test_unsafe_missing_self_references_are_terminal(isolated, reference):
    rt, _ = prepare(isolated, reference)
    assert generate(rt)["reason"] == "policy_reference_invalid"
    assert_no_financial_action("canonical-test")


def test_target_still_requires_valid_scope_and_defined_terms(isolated):
    rt, root = prepare(isolated)
    target = root / PATH
    source = target.read_text()
    target.write_text(source.replace("institution: Will Bank", "institution: Other"))
    okf_read.func(path=PATH, runtime=rt)
    assert generate(rt, PATH)["reason"] == "policy_scope_mismatch"
    target.write_text(source.replace('  offer_discount_percentage: "0"\n', ""))
    okf_read.func(path=PATH, runtime=rt)
    assert generate(rt, PATH)["reason"] == "policy_terms_undefined"
    assert_no_financial_action("canonical-test")


def test_stale_auxiliary_requires_reread(isolated):
    rt, root = prepare(isolated)
    (root / AUX).write_text((root / AUX).read_text() + "Changed\n")
    assert generate(rt)["reason"] == "policy_receipt_mismatch"
    with SessionStore().transaction("canonical-test") as state:
        state["receipts"].clear()
    assert generate(rt)["reason"] == "policy_read_required"


def test_auxiliary_cycle_stops_after_one_retry(isolated):
    rt, root = prepare(isolated)
    (root / PATH).write_text(
        "---\npolicy_role: auxiliary\ncanonical_policy: limites-desconto.md\n---\nCycle\n"
    )
    model = CountingModel(
        responses=[
            offer(AUX, "first"),
            AIMessage(
                content="",
                tool_calls=[{"name": "okf_read", "id": "read", "args": {"path": PATH}}],
            ),
            offer(PATH, "retry"),
        ]
    )
    graph = create_agent(
        model=model, tools=[generate_payment_offer, okf_read], middleware=[direct_reply]
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="Pix")]},
        {"configurable": {"thread_id": "canonical-test"}},
    )
    assert model.calls == 3
    assert "Proposta simulada criada" not in result["messages"][-1].content
    assert_no_financial_action("canonical-test")


def test_reference_cannot_escape_bundle_through_symlink(isolated, tmp_path):
    rt, root = prepare(isolated, "escape.md")
    outside = tmp_path / "outside.md"
    outside.write_text("# outside")
    (root / PurePosixPath(AUX).parent / "escape.md").symlink_to(outside)
    assert generate(rt)["reason"] == "policy_reference_invalid"
