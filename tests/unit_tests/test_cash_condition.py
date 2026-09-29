import asyncio
from time import perf_counter

import pytest
import yaml
from langchain.agents import create_agent
from langchain_core.messages import AIMessage

from simple_agent.services.session_store import SessionStore
from simple_agent.tool_middleware import (
    CashConditionPauseMiddleware,
    direct_reply,
    render_direct_reply,
)
from simple_agent.tools.cash_condition import check_cash_payment_condition
from .test_collection_identity_gates import call
from .test_direct_replies import CountingModel
from .test_modality_policy_contract import prepare
from .test_pilot_journeys import PATH, read_policy


def setup_condition(store, key, discount="3", methods=None):
    rt, _ = prepare(store, key)
    path = store.bundle_root(store.active_bundle_id()) / PATH
    _, header, body = path.read_text().split("---", 2)
    meta = yaml.safe_load(header)
    meta["negotiation"]["by_payment_type"]["cash"] = {
        "max_discount_percentage": "10",
        "offer_discount_percentage": discount,
    }
    if methods is not None:
        meta["payment"]["methods_by_payment_type"]["cash"] = methods
    path.write_text("---\n" + yaml.safe_dump(meta) + "---" + body)
    read_policy(rt)
    with SessionStore().transaction(key) as state:
        state["fixture"]["full_name"] = "Eduardo Teste"
    return rt


def test_quote_uses_policy_and_never_creates_agreement_or_payment(isolated):
    rt = setup_condition(isolated, "quote")
    result = call(check_cash_payment_condition, rt, policy_path=PATH)
    assert result["available"] is True
    assert result["offer"]["negotiated_amount"] == "5697.22"
    assert result["methods"] == ["pix", "boleto"]
    assert render_direct_reply("check_cash_payment_condition", result) == (
        "Eduardo, consegui uma condição especial para pagamento à vista hoje, com 3% de desconto. "
        "Com essa condição, o valor para quitação fica em R$ 5.697,22. Você prefere pagar por PIX ou boleto?"
    )
    session = SessionStore().read("quote")
    assert len(session["offers"]) == 1
    assert (
        not session["agreements"]
        and not session["payments"]
        and not session["deliveries"]
    )


def test_no_discount_and_single_method_do_not_invent_a_special_condition(isolated):
    rt = setup_condition(isolated, "no-discount", discount="0", methods=["boleto"])
    result = call(check_cash_payment_condition, rt, policy_path=PATH)
    text = render_direct_reply("check_cash_payment_condition", result)
    assert "não há desconto" in text and "R$ 5.873,42" in text
    assert "PIX" not in text and "especial" not in text


@pytest.mark.parametrize("missing", ["identity", "receipt"])
def test_quote_preserves_identity_and_policy_gates(isolated, missing):
    rt = setup_condition(isolated, missing)
    with SessionStore().transaction(missing) as state:
        if missing == "identity":
            state["identity_verified"] = False
        else:
            state["receipts"] = {}
    result = call(check_cash_payment_condition, rt, policy_path=PATH)
    assert result["available"] is False
    assert result["reason"] == (
        "identity_verification_required"
        if missing == "identity"
        else "policy_read_required"
    )
    assert not SessionStore().read(missing)["offers"]


@pytest.mark.parametrize("days,percentage", [(10, "5"), (60, "8"), (168, "10")])
def test_quote_preserves_policy_discount_tiers(isolated, days, percentage):
    rt, _ = prepare(isolated, "tiers", days=days)
    result = call(check_cash_payment_condition, rt, policy_path=PATH)
    assert result["available"] is True
    assert result["offer"]["discount_percentage"] == percentage


@pytest.mark.anyio
async def test_stream_announces_then_waits_five_seconds_without_blocking_other_work(
    isolated,
):
    setup_condition(isolated, "stream")
    model = CountingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "quote-1",
                        "name": "check_cash_payment_condition",
                        "args": {"policy_path": PATH},
                    }
                ],
            )
        ]
    )
    graph = create_agent(
        model=model,
        tools=[check_cash_payment_condition],
        middleware=[CashConditionPauseMiddleware(), direct_reply],
    )
    seen = []
    ticks = []

    async def unrelated_work():
        await asyncio.sleep(0.1)
        # There must be no open SQLite transaction during the deliberate pause.
        with SessionStore().transaction("stream") as state:
            state["test_pause_write"] = True
        ticks.append(perf_counter())

    other = asyncio.create_task(unrelated_work())
    async for state in graph.astream(
        {"messages": [{"role": "user", "content": "Consigo desconto à vista?"}]},
        {"configurable": {"thread_id": "stream"}},
        stream_mode="values",
    ):
        message = state["messages"][-1]
        if (
            message.type == "ai"
            and message.content
            and (not seen or message.content != seen[-1][1])
        ):
            seen.append((perf_counter(), message.content))
    await other
    assert len(seen) == 2
    assert (
        seen[0][1]
        == "Entendi, Eduardo. Vou verificar internamente se consigo uma condição especial para pagamento à vista hoje."
    )
    assert "R$ 5.697,22" in seen[1][1]
    assert seen[1][0] - seen[0][0] >= 4.95
    assert ticks[0] < seen[1][0]
    assert model.calls == 1
    assert not SessionStore().read("stream")["payments"]


@pytest.mark.anyio
async def test_cancellation_during_pause_does_not_quote_or_create_payment(isolated):
    setup_condition(isolated, "cancel")
    model = CountingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "quote-cancel",
                        "name": "check_cash_payment_condition",
                        "args": {"policy_path": PATH},
                    }
                ],
            )
        ]
    )
    graph = create_agent(
        model=model,
        tools=[check_cash_payment_condition],
        middleware=[CashConditionPauseMiddleware(), direct_reply],
    )
    announced = asyncio.Event()

    async def consume():
        async for state in graph.astream(
            {"messages": [{"role": "user", "content": "Consigo desconto?"}]},
            {"configurable": {"thread_id": "cancel"}},
            stream_mode="values",
        ):
            if state["messages"][-1].additional_kwargs.get("negotiation_stage"):
                announced.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(announced.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    state = SessionStore().read("cancel")
    assert not state["offers"] and not state["agreements"] and not state["payments"]


@pytest.mark.anyio
async def test_parallel_preview_is_rejected_before_calculation(isolated):
    setup_condition(isolated, "parallel")
    model = CountingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"parallel-{n}",
                        "name": "check_cash_payment_condition",
                        "args": {"policy_path": PATH},
                    }
                    for n in range(2)
                ],
            )
        ]
    )
    graph = create_agent(
        model=model,
        tools=[check_cash_payment_condition],
        middleware=[CashConditionPauseMiddleware(), direct_reply],
    )
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "Tem desconto?"}]},
        {"configurable": {"thread_id": "parallel"}},
    )
    assert not SessionStore().read("parallel")["offers"]
    assert all(
        "negotiation_stage" not in message.additional_kwargs
        for message in result["messages"]
    )
    assert model.calls == 1
