import json
from types import SimpleNamespace

import pytest

from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage

from simple_agent.services.session_store import SessionStore
from simple_agent.tools.collection_tools import verify_and_get_customer
from simple_agent.tools.okf_tools import okf_read, okf_search


def runtime(key: str, scope_id: int = 2) -> ToolRuntime:
    return ToolRuntime(
        state={"messages": [HumanMessage(content="123", id="human-1")]},
        context={
            "portfolio_context": {
                "scope_id": scope_id,
                "tenant_id": "tenant-test",
            }
        },
        config={"configurable": {"thread_id": key}},
        stream_writer=lambda _: None,
        tool_call_id="call-1",
        store=None,
    )


def test_empty_portfolio_returns_workflow_status_without_global_customer(isolated):
    isolated.import_bundle(
        "scoped",
        "1",
        {
            "index.md": "# Root",
            "GLOBAL/index.md": "# Global",
            "GLOBAL/atendimento.md": "---\ntype: Procedure\n---\n# Atendimento\nProcedimento global.",
            "COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO/policies/politica-negociacao.md": "---\ntype: Policy\n---\n# Will\nPolítica privada.",
        },
    )
    rt = runtime("empty-c6")
    SessionStore().ensure_portfolio("empty-c6", 2, "tenant-test")

    result = json.loads(verify_and_get_customer.func(cpf="123", runtime=rt))
    assert result == {
        "verified": False,
        "found": False,
        "financial_data_available": False,
        "reason": "customer_not_found",
    }
    assert "Procedimento global" in okf_search.func(query="Procedimento", runtime=rt)
    assert "Política privada" not in okf_search.func(query="Will", runtime=rt)

    denied = json.loads(
        okf_read.func(
            path="COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO/policies/politica-negociacao.md",
            runtime=rt,
        )
    )
    assert denied["reason"] == "knowledge_lookup_failed"
    assert denied["error_type"] == "PermissionError"


def test_portfolio_simulators_do_not_cross_sessions(isolated):
    fixture = {
        "customer_id": "CUS-C6",
        "full_name": "Cliente C6",
        "cpf": "12345678900",
        "birth_date": "1990-01-01",
        "institution": "C6",
        "product": "Cartao Black",
        "debt": {
            "debt_id": "DEBT-C6",
            "contract_id": "CTR-C6",
            "original_amount": "100.00",
            "current_amount": "100.00",
            "due_date": "2026-01-01",
            "status": "overdue",
        },
        "eligibility": {
            "can_negotiate": True,
            "max_installments": 1,
            "max_discount_percentage": "0",
        },
        "identity_policy": {
            "cpf_mode": "first3",
            "secondary": "none",
            "max_attempts": 3,
        },
    }
    from simple_agent.services.simulator_store import SimulatorStore

    SimulatorStore.for_portfolio(2).save(fixture)
    SessionStore().ensure_portfolio("c6", 2, "tenant-test")
    SessionStore().ensure_portfolio("usedigi", 3, "tenant-test")

    c6 = SessionStore().read("c6")
    usedigi = SessionStore().read("usedigi")
    assert c6["fixture"]["customer_id"] == "CUS-C6"
    assert usedigi.get("unbound_session") is True
    assert "fixture" not in usedigi


def test_model_request_pins_portfolio_before_exposing_tools(isolated, monkeypatch):
    from langchain.agents.middleware import ModelRequest
    from langgraph.runtime import Runtime
    from simple_agent import managed_graph, tool_middleware

    isolated.import_bundle("global-only", "1", {"index.md": "# Root"})
    monkeypatch.setattr(
        tool_middleware,
        "get_config",
        lambda: {"configurable": {"thread_id": "fresh-c6"}},
    )
    request = ModelRequest(
        model=managed_graph.create_llm(),
        messages=[],
        tools=managed_graph.ALL_TOOLS,
        runtime=Runtime(
            context={
                "portfolio_context": {
                    "scope_id": "3",
                    "tenant_id": "tenant-c6",
                }
            }
        ),
        state={"messages": []},
    )
    filtered = tool_middleware.filter_enabled_tools._filtered_request(request)
    state = SessionStore().read("fresh-c6")
    names = {tool.name for tool in filtered.tools}
    assert state["portfolio_scope_id"] == 3
    assert state["unbound_session"] is True
    assert "fixture" not in state
    assert "verify_and_get_customer" in names
    assert names.isdisjoint(tool_middleware.UNBOUND_BLOCKED_TOOLS)


def test_assistant_tool_allowlists_filter_and_guard_each_portfolio(
    isolated, monkeypatch
):
    from langchain.agents.middleware import ModelRequest
    from langgraph.runtime import Runtime
    from simple_agent import managed_graph, tool_middleware

    isolated.import_bundle("global-only", "1", {"index.md": "# Root"})
    for scope_id, allowed_name, denied_name in (
        (2, "okf_index", "verify_and_get_customer"),
        (3, "verify_and_get_customer", "okf_index"),
    ):
        key = f"allowlist-{scope_id}"
        monkeypatch.setattr(
            tool_middleware,
            "get_config",
            lambda key=key: {"configurable": {"thread_id": key}},
        )
        runtime = Runtime(
            context={
                "portfolio_context": {
                    "scope_id": scope_id,
                    "tenant_id": "tenant-test",
                },
                "allowed_tools": [allowed_name],
            }
        )
        request = ModelRequest(
            model=managed_graph.create_llm(),
            messages=[],
            tools=managed_graph.ALL_TOOLS,
            runtime=runtime,
            state={"messages": []},
        )
        filtered = tool_middleware.filter_enabled_tools._filtered_request(request)
        assert {tool.name for tool in filtered.tools} == {allowed_name}
        with pytest.raises(PermissionError, match="tool_not_allowed_for_assistant"):
            tool_middleware.filter_enabled_tools._assert_tool_allowed(
                denied_name, key, runtime
            )

        call = SimpleNamespace(
            tool_call={"name": denied_name, "id": "call-1", "args": {}},
            runtime=runtime,
        )
        result = tool_middleware.filter_enabled_tools.wrap_tool_call(
            call, lambda _: pytest.fail("disallowed tool executed")
        )
        assert json.loads(result.content)["message"] == "tool_not_allowed_for_assistant"


def test_explicit_empty_or_invalid_tool_allowlist(isolated, monkeypatch):
    from langchain.agents.middleware import ModelRequest
    from langgraph.runtime import Runtime
    from simple_agent import managed_graph, tool_middleware

    isolated.import_bundle("global-only", "1", {"index.md": "# Root"})
    monkeypatch.setattr(
        tool_middleware,
        "get_config",
        lambda: {"configurable": {"thread_id": "empty-allowlist"}},
    )
    request = ModelRequest(
        model=managed_graph.create_llm(),
        messages=[],
        tools=managed_graph.ALL_TOOLS,
        runtime=Runtime(context={"allowed_tools": []}),
        state={"messages": []},
    )
    assert not tool_middleware.filter_enabled_tools._filtered_request(request).tools
    with pytest.raises(ValueError, match="invalid_allowed_tools"):
        tool_middleware.filter_enabled_tools._filtered_request(
            request.override(runtime=Runtime(context={"allowed_tools": "okf_index"}))
        )
