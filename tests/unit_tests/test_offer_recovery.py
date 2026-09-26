"""Real tool/graph contracts with scripted model decisions and temporary data."""

import json
from pathlib import Path

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage

from simple_agent.services.offer_policy import (
    policy_document_scope,
    validate_policy,
    money,
)
from simple_agent.services.session_store import SessionStore
from simple_agent.tool_middleware import direct_reply, filter_enabled_tools
from simple_agent.tool_timing import capture_timing
from simple_agent.tools.payment_tools import generate_payment_offer
from simple_agent.tools.okf_tools import okf_read
from .test_collection_identity_gates import runtime, verify, call
from .test_direct_replies import CountingModel
from .test_pilot_journeys import PATH, seed, read_policy, assert_no_financial_action


def offer_call(call_id="offer"):
    return AIMessage(
        content="",
        response_metadata={"finish_reason": "tool_calls"},
        tool_calls=[
            {
                "id": call_id,
                "name": "generate_payment_offer",
                "args": {
                    "payment_type": "installment",
                    "method": "boleto",
                    "installments": 3,
                    "policy_path": PATH,
                },
            }
        ],
    )


@pytest.mark.parametrize("async_run", [False, True])
def test_unread_policy_recovers_without_customer_repeating_terms(isolated, async_run):
    seed(isolated, approve=True)
    key = "recover-policy"
    assert verify(runtime(key))["verified"]
    model = CountingModel(
        responses=[
            offer_call("first"),
            AIMessage(
                content="",
                tool_calls=[{"id": "read", "name": "okf_read", "args": {"path": PATH}}],
            ),
            offer_call("retry"),
        ]
    )
    graph = create_agent(
        model=model, tools=[generate_payment_offer, okf_read], middleware=[direct_reply]
    )
    args = (
        {"messages": [HumanMessage(content="Pode emitir")]},
        {"configurable": {"thread_id": key}},
    )
    if async_run:
        import asyncio

        result = asyncio.run(graph.ainvoke(*args))
    else:
        result = graph.invoke(*args)
        assert model.calls == 3  # No fourth LLM call after successful generation.
    first = next(m for m in result["messages"] if m.type == "tool")
    assert json.loads(first.content)["recoverable"] is True
    assert "okf_read" in json.loads(first.content)["recovery"]
    assert result["messages"][-1].additional_kwargs["deterministic_reply"] is True
    assert "Proposta simulada criada" in result["messages"][-1].content
    state = SessionStore().read(key)
    assert (
        len(state["offers"]) == len(state["agreements"]) == len(state["payments"]) == 1
    )


def test_recovery_stops_after_one_retry_and_resets_next_turn(isolated):
    seed(isolated, approve=True)
    key = "bounded-recovery"
    assert verify(runtime(key))["verified"]
    model = CountingModel(
        responses=[offer_call("first"), offer_call("retry"), offer_call("new-turn")]
    )
    graph = create_agent(
        model=model, tools=[generate_payment_offer], middleware=[direct_reply]
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="Pode emitir")]},
        {"configurable": {"thread_id": key}},
    )
    assert model.calls == 2
    assert "Preciso consultar" in result["messages"][-1].content
    assert_no_financial_action(key)
    read_policy(runtime(key))
    result = graph.invoke(
        {"messages": [*result["messages"], HumanMessage(content="Tente novamente")]},
        {"configurable": {"thread_id": key}},
    )
    assert model.calls == 3
    assert "Proposta simulada criada" in result["messages"][-1].content


def test_undefined_terms_are_not_retried(isolated):
    seed(isolated, approve=True)
    key = "undefined-terms"
    source = isolated.bundle_root(isolated.active_bundle_id()) / PATH
    source.write_text(
        source.read_text().replace('  offer_discount_percentage: "0"\n', "")
    )
    assert verify(runtime(key))["verified"]
    read_policy(runtime(key))
    model = CountingModel(responses=[offer_call()])
    graph = create_agent(
        model=model, tools=[generate_payment_offer], middleware=[direct_reply]
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="Pode emitir")]},
        {"configurable": {"thread_id": key}},
    )
    assert model.calls == 1
    assert "ainda não foram definidas" in result["messages"][-1].content
    assert_no_financial_action(key)


@pytest.mark.parametrize(
    "text",
    ["Não quero em 3 parcelas", "Posso parcelar em 3 vezes?", "Quero em 3 parcelas"],
)
def test_backend_never_invents_offer_call_when_model_does_not_call(isolated, text):
    seed(isolated, approve=True)
    key = "no-forced-handoff"
    assert verify(runtime(key))["verified"]
    read_policy(runtime(key))
    model = CountingModel(
        responses=[
            AIMessage(
                content="Resposta do modelo.",
                response_metadata={"finish_reason": "stop"},
            )
        ]
    )
    graph = create_agent(
        model=model,
        tools=[generate_payment_offer],
        middleware=[filter_enabled_tools, direct_reply],
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content=text)]}, {"configurable": {"thread_id": key}}
    )
    assert model.calls == 1
    assert result["messages"][-1].content == "Resposta do modelo."
    assert_no_financial_action(key)


def test_one_policy_read_per_operation_and_no_cache_between_operations(
    isolated, monkeypatch
):
    seed(isolated, approve=True)
    rt = runtime("policy-reuse", "Quero em 3 parcelas no boleto")
    assert verify(rt)["verified"]
    read_policy(rt)
    original = Path.read_text
    reads = []

    def counted(path, *args, **kwargs):
        if str(path).endswith(PATH):
            reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    args = dict(
        payment_type="installment", method="boleto", installments=3, policy_path=PATH
    )
    with capture_timing() as timing:
        first = call(generate_payment_offer, rt, **args)
    assert first["created"] and len(reads) == 1
    assert timing["counters"]["policy_document_reads"] == 1
    assert timing["counters"]["policy_document_reuses"] == 9
    assert call(generate_payment_offer, rt, **args) == first
    assert len(reads) == 2
    source = isolated.bundle_root(isolated.active_bundle_id()) / PATH
    source.write_text(original(source) + "\nChanged outside the operation\n")
    assert (
        call(generate_payment_offer, rt, **args)["reason"] == "policy_receipt_mismatch"
    )
    assert len(reads) == 3


def test_document_reuse_never_reuses_authorization(isolated):
    seed(isolated, approve=True)
    key = "per-state-validation"
    assert verify(runtime(key))["verified"]
    read_policy(runtime(key))
    state = SessionStore().read(key)
    with policy_document_scope():
        validate_policy(state, PATH, "installment", 3, money(0))
        other = {**state, "receipts": {}}
        with pytest.raises(ValueError, match="policy_read_required"):
            validate_policy(other, PATH, "installment", 3, money(0))
        with pytest.raises(ValueError, match="policy_terms_exceeded"):
            validate_policy(state, PATH, "installment", 4, money(0))
        other = {**state, "fixture": {**state["fixture"], "institution": "Different"}}
        with pytest.raises(ValueError, match="policy_scope_mismatch"):
            validate_policy(other, PATH, "installment", 3, money(0))


def test_missing_installments_are_not_silently_defaulted(isolated):
    seed(isolated, approve=True)
    rt = runtime("missing-count", "Quero parcelar")
    assert verify(rt)["verified"]
    read_policy(rt)
    result = call(
        generate_payment_offer,
        rt,
        payment_type="installment",
        method="boleto",
        policy_path=PATH,
    )
    assert result == {
        "created": False,
        "reason": "offer_terms_missing",
        "missing_fields": ["installments"],
    }
    assert_no_financial_action("missing-count")


@pytest.mark.parametrize(
    "kind,count", [("cash", 3), ("installment", 0), ("installment", True)]
)
def test_invalid_structured_count_is_rejected(isolated, kind, count):
    result = call(
        generate_payment_offer,
        runtime("invalid-count"),
        payment_type=kind,
        method="boleto",
        policy_path=PATH,
        installments=count,
    )
    assert result == {"created": False, "reason": "invalid_payment_terms"}
