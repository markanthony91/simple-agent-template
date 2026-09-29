import json

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from simple_agent.message_delay import CashMessageDelay
from simple_agent.negotiation_continuation import (
    CONTINUE_REVIEW,
    MARKER,
    UNAVAILABLE,
    NegotiationContinuationMiddleware,
)
from .test_direct_replies import CountingModel
from .test_message_delay import FIRST, frame

FINAL = "Você prefere realizar o pagamento por PIX ou boleto?"


class ObservedModel(CountingModel):
    seen: list = []

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, *args, **kwargs)


def agent(responses, tools=()):
    model = ObservedModel(responses=responses)
    return model, create_agent(
        model=model,
        tools=list(tools),
        middleware=[NegotiationContinuationMiddleware()],
    )


@pytest.mark.anyio
@pytest.mark.parametrize("async_run", [False, True])
async def test_announcement_continues_without_fake_customer_or_extra_tool(async_run):
    model, graph = agent([AIMessage(content=FIRST), AIMessage(content=FINAL)])
    inp = {"messages": [HumanMessage(content="Só consigo pagar com desconto.")]}
    result = await graph.ainvoke(inp) if async_run else graph.invoke(inp)
    messages = result["messages"]
    assert [m.content for m in messages if m.type == "ai"] == [FIRST, FINAL]
    assert sum(m.type == "human" for m in messages) == 1
    assert model.calls == 2
    assert CONTINUE_REVIEW in model.seen[1][0].content
    assert model.seen[1][-1].type == "human"
    assert not any(m.type == "ai" for m in model.seen[1])
    assert not any(
        m.type == "system" for m in messages
    )  # Internal guidance is not saved.
    assert messages[-2].additional_kwargs[MARKER] is True


def test_retry_is_bounded_and_new_turn_has_its_own_budget():
    model, graph = agent(
        [
            AIMessage(content=FIRST),
            AIMessage(content=FIRST),
            AIMessage(content=FIRST),
            AIMessage(content=FINAL),
        ]
    )
    result = graph.invoke({"messages": [HumanMessage(content="Preciso de desconto.")]})
    assert model.calls == 2
    assert result["messages"][-1].content == UNAVAILABLE
    result = graph.invoke(
        {"messages": [*result["messages"], HumanMessage(content="Tente novamente.")]}
    )
    assert model.calls == 4
    assert result["messages"][-1].content == FINAL
    assert sum(m.type == "human" for m in result["messages"]) == 2


@pytest.mark.parametrize(
    "text", ["Olá!", FINAL, FIRST + "\n\n" + FINAL, "Vou verificar outra coisa."]
)
def test_complete_or_unrelated_responses_are_not_resumed(text):
    model, graph = agent([AIMessage(content=text)])
    result = graph.invoke({"messages": [HumanMessage(content="Teste")]})
    assert model.calls == 1
    assert result["messages"][-1].content == text


def test_existing_tool_call_is_not_duplicated_and_result_is_preserved():
    calls = []

    @tool
    def lookup() -> str:
        """Return a synthetic policy result."""
        calls.append(1)
        return "synthetic policy: ask for the payment method"

    tool_message = AIMessage(
        content=FIRST, tool_calls=[{"name": "lookup", "args": {}, "id": "read"}]
    )
    model, graph = agent([tool_message, AIMessage(content=FINAL)], [lookup])
    result = graph.invoke({"messages": [HumanMessage(content="Preciso de desconto.")]})
    assert calls == [1]
    assert model.calls == 2
    assert not any(m.additional_kwargs.get(MARKER) for m in result["messages"])
    assert result["messages"][-1].content == FINAL


def test_resumed_agent_can_consult_tools_without_another_resume():
    calls = []

    @tool
    def lookup() -> str:
        """Return a synthetic policy result."""
        calls.append(1)
        return "unavailable"

    model, graph = agent(
        [
            AIMessage(content=FIRST),
            AIMessage(
                content="", tool_calls=[{"name": "lookup", "args": {}, "id": "read"}]
            ),
            AIMessage(content=FIRST),
        ],
        [lookup],
    )
    result = graph.invoke({"messages": [HumanMessage(content="Preciso de desconto.")]})
    assert calls == [1] and model.calls == 3
    assert model.seen[2][-1].type == "tool"
    assert result["messages"][-1].content == UNAVAILABLE


@pytest.mark.anyio
async def test_graph_continuation_keeps_existing_sse_pause(monkeypatch):
    _, graph = agent([AIMessage(content=FIRST), AIMessage(content=FINAL)])
    sent, waits = [], []

    async def wait(seconds):
        waits.append(seconds)
        assert FIRST.encode() in sent[-1]["body"]
        assert FINAL.encode() not in sent[-1]["body"]

    monkeypatch.setattr("simple_agent.message_delay.asyncio.sleep", wait)

    async def app(scope, receive, send):
        await receive()
        await send(
            {
                "type": "http.response.start",
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        async for state in graph.astream(
            {"messages": [HumanMessage(content="Preciso de desconto", id="u")]},
            stream_mode="values",
        ):
            await send(
                {
                    "type": "http.response.body",
                    "body": frame(
                        "values",
                        {"messages": [m.model_dump() for m in state["messages"]]},
                    ),
                    "more_body": True,
                }
            )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def receive():
        return {"type": "http.request", "body": b'{"input":{"messages":[{"id":"u"}]}}'}

    async def send(event):
        sent.append(event)

    await CashMessageDelay(app)(
        {"type": "http", "method": "POST", "path": "/threads/t/runs/stream"},
        receive,
        send,
    )
    assert waits == [5]
    states = [
        json.loads(line[6:])
        for e in sent
        for line in e.get("body", b"").splitlines()
        if line.startswith(b"data: ")
    ]
    final = states[-1]["messages"]
    assert [m["content"] for m in final if m["type"] == "ai"] == [FIRST, FINAL]
    assert sum(m["type"] == "human" for m in final) == 1


def test_separate_checkpointed_sessions_do_not_share_recovery_budget():
    from langgraph.checkpoint.memory import InMemorySaver

    model = ObservedModel(
        responses=[
            AIMessage(content=FIRST),
            AIMessage(content=FIRST),
            AIMessage(content=FIRST),
            AIMessage(content=FINAL),
        ]
    )
    graph = create_agent(
        model=model,
        tools=[],
        middleware=[NegotiationContinuationMiddleware()],
        checkpointer=InMemorySaver(),
    )
    for key, expected in [("session-a", UNAVAILABLE), ("session-b", FINAL)]:
        result = graph.invoke(
            {"messages": [HumanMessage(content="Preciso de desconto.")]},
            {"configurable": {"thread_id": key}},
        )
        assert result["messages"][-1].content == expected
        assert sum(m.type == "human" for m in result["messages"]) == 1
    assert model.calls == 4


def test_provider_failure_on_resume_is_not_reported_as_success():
    class FailingModel(ObservedModel):
        def _generate(self, messages, *args, **kwargs):
            if self.calls == 1:
                raise RuntimeError("synthetic provider unavailable")
            return super()._generate(messages, *args, **kwargs)

    model = FailingModel(responses=[AIMessage(content=FIRST)])
    graph = create_agent(
        model=model, tools=[], middleware=[NegotiationContinuationMiddleware()]
    )
    with pytest.raises(RuntimeError, match="synthetic provider unavailable"):
        graph.invoke({"messages": [HumanMessage(content="Preciso de desconto.")]})


def test_resume_does_not_bypass_existing_financial_identity_guard(isolated):
    from simple_agent.tools.payment_tools import generate_payment_offer
    from simple_agent.tool_middleware import direct_reply, filter_enabled_tools
    from .test_pilot_journeys import seed, PATH, assert_no_financial_action

    seed(isolated, approve=True)
    model = ObservedModel(
        responses=[
            AIMessage(content=FIRST, response_metadata={"finish_reason": "stop"}),
            AIMessage(
                content="",
                response_metadata={"finish_reason": "tool_calls"},
                tool_calls=[
                    {
                        "name": "generate_payment_offer",
                        "id": "offer",
                        "args": {
                            "payment_type": "cash",
                            "method": "boleto",
                            "installments": 1,
                            "policy_path": PATH,
                        },
                    }
                ],
            ),
        ]
    )
    graph = create_agent(
        model=model,
        tools=[generate_payment_offer],
        middleware=[
            NegotiationContinuationMiddleware(),
            filter_enabled_tools,
            direct_reply,
        ],
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="Quero desconto no boleto.")]},
        {"configurable": {"thread_id": "unverified-resume"}},
    )
    result_tool = next(m for m in result["messages"] if m.type == "tool")
    assert json.loads(result_tool.content)["created"] is False
    assert_no_financial_action("unverified-resume")
    assert model.calls == 2
    assert "Quero desconto no boleto." in [
        m.content for m in model.seen[-1] if m.type == "human"
    ]
