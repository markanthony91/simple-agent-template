import json

import httpx
import pytest
from pydantic import ValidationError

from simple_agent.runtime_settings import AgentProfile, LLMSettings, validate_settings


@pytest.mark.parametrize(
    "value",
    [
        {"temperature": -0.1},
        {"temperature": 2.1},
        {"temperature": True},
        {"temperature": "0.2"},
        {"temperature": float("nan")},
        {"top_p": 0},
        {"top_p": 1.01},
        {"top_p": float("inf")},
        {"max_tokens": 0},
        {"max_tokens": 32769},
        {"max_tokens": 1.5},
        {"max_tokens": True},
        {"model": "override"},
        {"base_url": "http://other"},
    ],
)
def test_llm_settings_reject_invalid_or_unsafe_overrides(value):
    with pytest.raises(ValidationError):
        LLMSettings.model_validate(value)


def test_defaults_profile_and_admin_contract():
    from simple_agent.admin_graph_v2 import execute

    assert LLMSettings().model_dump(exclude_none=True) == {}
    assert AgentProfile().instructions() == ""
    assert AgentProfile(name="  Sofia  ").name == "Sofia"
    for invalid in ({"name": "n" * 81}, {"role": 1}, {"extra": "x"}):
        with pytest.raises(ValidationError):
            AgentProfile.model_validate(invalid)
    for invalid in ([], {"model": "another"}):
        with pytest.raises(ValueError):
            validate_settings(invalid)
    value = {"llm_settings": {"temperature": 0}, "agent_profile": {"name": "Sofia"}}
    result = execute({"operation": "validate_runtime_settings", "settings": value})
    assert not result["error"]
    assert result["result"]["llm_settings"] == {"temperature": 0}
    assert result["result"]["agent_profile"]["name"] == "Sofia"
    assert execute(
        {
            "operation": "validate_runtime_settings",
            "settings": {"llm_settings": {"temperature": 9}},
        }
    )["error"]
    config = execute({"operation": "get_llm_config"})["result"]
    assert config["model"] and config["hostname"]
    assert config["defaults"] == {
        "temperature": None,
        "top_p": None,
        "max_tokens": None,
    }
    assert set(config) == {
        "hostname",
        "provider",
        "model",
        "defaults",
        "limits",
        "connections",
    }


@pytest.mark.anyio
async def test_settings_reach_provider_on_every_tool_round_without_leaking(
    isolated, monkeypatch
):
    from simple_agent.managed_graph import graph

    requests = []

    async def respond(self, request, **kwargs):
        payload = json.loads(request.content)
        requests.append(payload)
        final = payload["messages"][-1]["role"] == "tool"
        delta = (
            {"content": "Resposta sintética."}
            if final
            else {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "clock-call",
                        "type": "function",
                        "function": {"name": "utc_now", "arguments": "{}"},
                    }
                ]
            }
        )

        def chunk(delta, finish=None):
            return {
                "id": "synthetic",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": payload["model"],
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }

        body = (
            "".join(
                "data: " + json.dumps(item) + "\n\n"
                for item in [chunk(delta), chunk({}, "stop" if final else "tool_calls")]
            )
            + "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            request=request,
            headers={"Content-Type": "text/event-stream"},
            content=body,
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", respond)
    context = {
        "system_prompt": "SYSTEM_MARKER",
        "agent_instructions": "AGENTS_MARKER",
        "active_workflow": "WORKFLOW_MARKER",
        "agent_profile": {"name": "Sofia", "role": "Atendimento", "tone": "Cordial"},
        "llm_settings": {"temperature": 0, "top_p": 0.8, "max_tokens": 1024},
    }
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "Hora?"}]},
        {"configurable": {"thread_id": "settings-one"}},
        context=context,
    )
    assert result["messages"][-1].content == "Resposta sintética."
    assert len(requests) == 2
    for payload in requests:
        assert payload["temperature"] == 0 and payload["top_p"] == 0.8
        assert payload.get("max_completion_tokens", payload.get("max_tokens")) == 1024
        system = payload["messages"][0]["content"]
        assert all(
            x in system
            for x in [
                "SYSTEM_MARKER",
                "AGENTS_MARKER",
                "WORKFLOW_MARKER",
                "Sofia",
                "Atendimento",
                "Cordial",
                "CPF completo",
            ]
        )
        assert payload["tools"]
    await graph.ainvoke(
        {"messages": [{"role": "user", "content": "Hora?"}]},
        {"configurable": {"thread_id": "settings-two"}},
        context={},
    )
    for payload in requests[2:]:
        assert (
            not {"temperature", "top_p", "max_tokens", "max_completion_tokens"}
            & payload.keys()
        )
        assert "Sofia" not in payload["messages"][0]["content"]
    with pytest.raises(ValidationError):
        await graph.ainvoke(
            {"messages": [{"role": "user", "content": "Oi"}]},
            {"configurable": {"thread_id": "settings-invalid"}},
            context={"llm_settings": {"temperature": 99}},
        )
    assert len(requests) == 4
