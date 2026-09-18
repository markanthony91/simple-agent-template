import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from simple_agent.services.identity_policy import instructions, matches
from simple_agent.services.session_store import SessionStore
from simple_agent.services.simulator_schema import IdentityPolicy
from simple_agent.services.simulator_store import SimulatorStore
from simple_agent.tools.collection_tools import get_customer, verify_customer_identity


def runtime(key="identity", call="call-1"):
    return SimpleNamespace(
        config={"configurable": {"thread_id": key}}, tool_call_id=call
    )


@pytest.mark.parametrize(
    "mode,cpf",
    [
        ("full", "123.456.789-00"),
        ("first3", "123"),
        ("first4", "1234"),
        ("last4", "8900"),
    ],
)
@pytest.mark.parametrize(
    "secondary,args",
    [
        ("full_name", {"full_name": "  JOAO   DA SILVA  "}),
        ("birth_date", {"birth_date": "1985-04-17"}),
        ("both", {"full_name": "João da Silva", "birth_date": "1985-04-17"}),
        ("either", {"full_name": "João da Silva"}),
        ("none", {}),
    ],
)
def test_methods_and_authorized_debt(isolated, mode, cpf, secondary, args):
    store = SimulatorStore()
    fixture = store.load()
    fixture["identity_policy"] = {
        "cpf_mode": mode,
        "secondary": secondary,
        "max_attempts": 3,
    }
    store.save(fixture)
    rt = runtime()
    assert "debt" not in json.loads(get_customer.func(runtime=rt))
    result = json.loads(verify_customer_identity.func(runtime=rt, cpf=cpf, **args))
    assert result["verified"] is True
    authorized = json.loads(get_customer.func(runtime=rt))
    assert "debt" in authorized
    assert "phone" not in authorized  # Existing Playground contract is unchanged.
    assert "debt" not in json.loads(get_customer.func(runtime=runtime("other")))
    assert "debt" not in json.loads(get_customer.func(runtime=rt, cpf="99999999999"))


def test_failure_generic_lock_and_replay(isolated):
    for n in range(1, 4):
        rt = runtime(call=f"attempt-{n}")
        result = json.loads(verify_customer_identity.func(runtime=rt, cpf="0000"))
        assert result == json.loads(
            verify_customer_identity.func(runtime=rt, cpf="0000")
        )
        assert result["attempts_remaining"] == 3 - n
        assert result["requires_human"] == (n == 3)
        assert result["reason"] == "identity_validation_failed"
    assert not json.loads(
        verify_customer_identity.func(
            runtime=runtime(call="correct"),
            cpf="12345678900",
            full_name="João da Silva",
        )
    )["verified"]
    assert "debt" not in json.loads(get_customer.func(runtime=runtime()))


def test_policy_pin_and_prompt_no_expected_values(isolated):
    with SessionStore().transaction("old") as old:
        assert "CPF completo" in instructions(old)
        assert "Contexto de apresentação" not in instructions(old)
    store = SimulatorStore()
    fixture = store.load()
    fixture["identity_policy"] = {"cpf_mode": "first4", "secondary": "full_name"}
    store.save(fixture)
    with SessionStore().transaction("new") as new:
        text = instructions(new)
        assert "4 primeiros dígitos" in text
        for field in ("cpf", "full_name", "birth_date"):
            assert fixture[field] not in text
        assert matches(new, "1234", "Joao da Silva", "")
        assert not matches(new, "1234", "João Silva", "")
        assert not matches(new, "1234", "", "")
        assert not matches(new, "12345678900", "Joao da Silva", "")
    with SessionStore().transaction("old") as old:
        assert "CPF completo" in instructions(old)


@pytest.mark.parametrize(
    "invalid",
    [
        {"cpf_mode": "none"},
        {"max_attempts": 0},
        {"max_attempts": 11},
        {"max_attempts": True},
        {"max_attempts": "3"},
        {"skip": True},
    ],
)
def test_invalid_policy_rejected(invalid):
    with pytest.raises(ValidationError):
        IdentityPolicy.model_validate(invalid)


def test_selected_factors_and_revocation(isolated):
    store = SimulatorStore()
    fixture = store.load()
    fixture["identity_policy"] = {"cpf_mode": "last4", "secondary": "both"}
    store.save(fixture)
    rt = runtime()
    result = json.loads(
        verify_customer_identity.func(
            runtime=rt, cpf="8900", full_name="Joao da Silva", birth_date="1985-04-17"
        )
    )
    assert result["verified"]
    with SessionStore().transaction("identity") as state:
        state["offers"] = {"offer": {}}
        assert not matches(state, "8900", "Joao da Silva", "")
        assert not matches(state, "8900", "", "1985-04-17")
    assert not json.loads(
        verify_customer_identity.func(
            runtime=rt, cpf="8900", full_name="Joao da Silva", birth_date="2000-01-01"
        )
    )["verified"]
    with SessionStore().transaction("identity") as state:
        assert not state["offers"] and not state["debt_read"]
        assert "verification_id" not in state


def test_runtime_appends_pinned_policy_without_replacing_prompts(isolated, monkeypatch):
    from langchain.agents.middleware import ModelRequest
    from langgraph.runtime import Runtime
    from simple_agent import managed_graph, tool_middleware

    monkeypatch.setattr(
        tool_middleware,
        "get_config",
        lambda: {"configurable": {"thread_id": "prompt-test"}},
    )
    fixture = SimulatorStore().load()
    fixture["creditor_name"] = "Fastpay"
    SessionStore().create("prompt-test", fixture)
    request = ModelRequest(
        model=managed_graph.create_llm(),
        messages=[],
        runtime=Runtime(
            context={
                "system_prompt": "CUSTOM_SYSTEM",
                "agent_instructions": "CUSTOM_AGENTS",
                "active_workflow": "CUSTOM_WORKFLOW",
                "agent_profile": {"name": "Sophia"},
            }
        ),
        state={"messages": []},
    )
    text = managed_graph.runtime_prompt.wrap_model_call(
        request,
        lambda req: (
            tool_middleware.filter_enabled_tools._filtered_request(
                req
            ).system_message.content
        ),
    )
    assert all(
        s in text
        for s in (
            "CUSTOM_SYSTEM",
            "CUSTOM_AGENTS",
            "CUSTOM_WORKFLOW",
            "Sophia",
            '"creditor": "Fastpay"',
            "CPF completo",
            "Tentativas restantes: 3",
        )
    )
    monkeypatch.setattr(tool_middleware, "get_config", lambda: {})
    with pytest.raises(ValueError, match="server_thread_id_required"):
        tool_middleware.filter_enabled_tools._filtered_request(request)


@pytest.mark.anyio
async def test_policy_io_is_off_event_loop(isolated, monkeypatch):
    import threading
    from langchain.agents.middleware import ModelRequest, ModelResponse
    from langchain_core.messages import AIMessage
    from langgraph.runtime import Runtime
    from simple_agent import tool_middleware
    from simple_agent.llm import create_llm

    original = tool_middleware.instructions

    def check_thread(state):
        assert threading.current_thread() is not threading.main_thread()
        return original(state)

    monkeypatch.setattr(tool_middleware, "instructions", check_thread)
    monkeypatch.setattr(
        tool_middleware,
        "get_config",
        lambda: {"configurable": {"thread_id": "async-policy"}},
    )
    request = ModelRequest(
        model=create_llm(),
        messages=[],
        runtime=Runtime(context={}),
        state={"messages": []},
    )

    async def handler(req):
        assert "CPF completo" in req.system_message.content
        return ModelResponse(
            result=[
                AIMessage(content="ok", response_metadata={"finish_reason": "stop"})
            ]
        )

    response = await tool_middleware.filter_enabled_tools.awrap_model_call(
        request, handler
    )
    assert response.result[0].content == "ok"
