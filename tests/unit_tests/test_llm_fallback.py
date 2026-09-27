import json
from types import SimpleNamespace

import httpx
import pytest
from langchain.agents.middleware import ModelResponse
from langchain_core.messages import AIMessage
from openai import APIConnectionError

from simple_agent.llm import connection_info, create_llm
from simple_agent.llm_fallback import LLMFallbackMiddleware
from simple_agent.runtime_settings import LLMIntegration, validate_settings


@pytest.fixture
def connections(monkeypatch):
    for name in ("LOVABLE", "EXTERNAL"):
        monkeypatch.setenv(f"LLM_{name}_BASE_URL", f"https://{name.lower()}.invalid/v1")
        monkeypatch.setenv(f"LLM_{name}_MODEL", f"synthetic-{name.lower()}")
        monkeypatch.setenv(f"LLM_{name}_API_KEY", "synthetic-secret")
    create_llm.cache_clear()
    yield
    create_llm.cache_clear()


def test_connections_validate_and_never_expose_credentials(connections, monkeypatch):
    assert validate_settings({"llm_integration": {"fallback": "lovable"}}) == {
        "llm_integration": {"primary": "default", "fallback": "lovable"}
    }
    for invalid in (
        {"primary": "arbitrary"},
        {"primary": "default", "fallback": "default"},
        {"base_url": "http://arbitrary"},
        {"fallback": True},
    ):
        with pytest.raises(ValueError):
            LLMIntegration.model_validate(invalid)
    monkeypatch.setenv(
        "LLM_LOVABLE_BASE_URL",
        "https://user:private@lovable.invalid/v1?key=private#private",
    )
    info = connection_info("lovable")
    assert info["endpoint"] == "https://lovable.invalid/v1"
    assert "private" not in json.dumps(info) and "synthetic-secret" not in json.dumps(
        info
    )
    monkeypatch.delenv("LLM_EXTERNAL_API_KEY")
    with pytest.raises(ValueError, match="pendente"):
        LLMIntegration.model_validate({"fallback": "external"})


def sse(payload, tool=False, repeat_finish=1):
    delta = (
        {"content": "Synthetic answer"}
        if not tool
        else {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "one-clock",
                    "type": "function",
                    "function": {"name": "utc_now", "arguments": "{}"},
                }
            ]
        }
    )

    def chunk(delta, finish=None):
        return (
            "data: "
            + json.dumps(
                {
                    "id": "synthetic",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": payload["model"],
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
            )
            + "\n\n"
        )

    return (
        chunk(delta)
        + chunk({}, "tool_calls" if tool else "stop") * repeat_finish
        + "data: [DONE]\n\n"
    ).encode()


@pytest.mark.anyio
@pytest.mark.parametrize("fallback", ["lovable", "external"])
@pytest.mark.parametrize("fail_before_tool", [False, True])
async def test_real_graph_fallback_after_tool_does_not_repeat_tool_or_change_context(
    isolated, connections, monkeypatch, fallback, fail_before_tool
):
    from simple_agent.managed_graph import graph
    from simple_agent import tool_middleware

    calls, executions = [], []
    monkeypatch.setattr(
        tool_middleware,
        "_log_event",
        lambda request, status, *args, **kwargs: executions.append(status),
    )

    async def send(self, request, **kwargs):
        payload = json.loads(request.content)
        calls.append((request.url.host, payload))
        final = payload["messages"][-1]["role"] == "tool"
        if (final != fail_before_tool) and request.url.host == "127.0.0.1":
            return httpx.Response(
                503, request=request, json={"error": {"message": "synthetic"}}
            )
        return httpx.Response(
            200,
            request=request,
            headers={"Content-Type": "text/event-stream"},
            content=sse(
                payload,
                tool=not final,
                repeat_finish=2 if request.url.host == "lovable.invalid" else 1,
            ),
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    context = {
        "system_prompt": "SYSTEM_MARKER",
        "agent_instructions": "AGENTS_MARKER",
        "active_workflow": "WORKFLOW_MARKER",
        "agent_profile": {"name": "Sofia"},
        "llm_settings": {"temperature": 0, "top_p": 0.8, "max_tokens": 1024},
        "llm_integration": {"fallback": fallback},
    }
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "Hora?"}]},
        {"configurable": {"thread_id": f"fallback-{fallback}"}},
        context=context,
    )
    assert len(calls) == 3
    assert executions == ["start", "success"]
    primary, backup = (
        (calls[0][1], calls[1][1]) if fail_before_tool else (calls[1][1], calls[2][1])
    )
    assert {k: v for k, v in primary.items() if k != "model"} == {
        k: v for k, v in backup.items() if k != "model"
    }
    if not fail_before_tool:
        assert backup["messages"][-1]["tool_call_id"] == "one-clock"
    assert backup["temperature"] == 0
    assert all(
        x in backup["messages"][0]["content"]
        for x in [
            "SYSTEM_MARKER",
            "AGENTS_MARKER",
            "WORKFLOW_MARKER",
            "Sofia",
            "CPF completo",
        ]
    )
    assert result["messages"][1 if fail_before_tool else -1].additional_kwargs[
        "llm_route"
    ] == {
        "connection": fallback,
        "model": f"synthetic-{fallback}",
        "fallback_used": True,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure,enabled,expected",
    [
        (429, True, 2),
        (500, True, 2),
        (408, True, 2),
        ("timeout", True, 2),
        (400, True, 1),
        (401, True, 1),
        (403, True, 1),
        (402, True, 1),
        (503, False, 1),
        ("partial", True, 1),
        ("partial_tool", True, 1),
        ("cancel", True, 1),
    ],
)
async def test_fallback_boundaries_with_actual_http_stream(
    isolated, connections, monkeypatch, failure, enabled, expected
):
    import asyncio
    from simple_agent.managed_graph import graph

    calls = []

    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                sse(calls[0], tool=failure == "partial_tool").split(b"\n\n")[0]
                + b"\n\n"
            )
            raise httpx.ReadError("synthetic interrupted stream")

    async def send(self, request, **kwargs):
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic", request=request)
            if failure == "cancel":
                raise asyncio.CancelledError()
            if failure in {"partial", "partial_tool"}:
                return httpx.Response(
                    200,
                    request=request,
                    headers={"Content-Type": "text/event-stream"},
                    stream=BrokenStream(),
                )
            return httpx.Response(
                failure, request=request, json={"error": {"message": "synthetic"}}
            )
        return httpx.Response(
            200,
            request=request,
            headers={"Content-Type": "text/event-stream"},
            content=sse(payload),
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    call = graph.ainvoke(
        {"messages": [{"role": "user", "content": "Oi"}]},
        {"configurable": {"thread_id": f"failure-{failure}"}},
        context={"llm_integration": {"fallback": "lovable"} if enabled else {}},
    )
    if expected == 2:
        result = await call
        assert result["messages"][-1].content == "Synthetic answer"
    else:
        with pytest.raises((Exception, asyncio.CancelledError)):
            await call
    assert len(calls) == expected


def test_sync_fallback_and_primary_selection(connections):
    class Request:
        runtime = SimpleNamespace(
            context={"llm_integration": {"primary": "external", "fallback": "lovable"}}
        )

        def override(self, **kwargs):
            return SimpleNamespace(**kwargs)

    calls = []

    def handler(request):
        calls.append(request.model.model_name)
        if len(calls) == 1:
            raise APIConnectionError(
                request=httpx.Request("POST", "https://external.invalid")
            )
        return ModelResponse(result=[AIMessage(content="ok")])

    response = LLMFallbackMiddleware().wrap_model_call(Request(), handler)
    assert calls == ["synthetic-external", "synthetic-lovable"]
    assert response.result[0].additional_kwargs["llm_route"]["fallback_used"]


@pytest.mark.parametrize(
    "reason,canonical",
    [
        ("stop", "stop"),
        ("stopstop", "stop"),
        ("tool_calls", "tool_calls"),
        ("tool_callstool_calls", "tool_calls"),
        ("tool_callstool_callstool_calls", "tool_calls"),
    ],
)
def test_identical_finish_markers_are_normalized(reason, canonical):
    from simple_agent.tool_middleware import FilterEnabledToolsMiddleware

    response = ModelResponse(
        result=[
            AIMessage(content="synthetic", response_metadata={"finish_reason": reason})
        ]
    )
    result = FilterEnabledToolsMiddleware._completed(response)
    assert result.result[0].response_metadata["finish_reason"] == canonical


@pytest.mark.parametrize(
    "reason",
    [
        None,
        "",
        "length",
        "lengthlength",
        "content_filter",
        "stoplength",
        "tool_callsstop",
    ],
)
def test_incomplete_or_mixed_finish_markers_are_rejected(reason):
    from simple_agent.tool_middleware import FilterEnabledToolsMiddleware

    response = ModelResponse(
        result=[
            AIMessage(content="synthetic", response_metadata={"finish_reason": reason})
        ]
    )
    with pytest.raises(RuntimeError, match="provider_response_incomplete"):
        FilterEnabledToolsMiddleware._completed(response)
