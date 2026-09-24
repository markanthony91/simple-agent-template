import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, MessagesState, START, END
from simple_agent.tools.collection_tools import get_customer
from simple_agent.tool_middleware import filter_enabled_tools


def executor():
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([get_customer]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    return graph.compile()


def test_invalid_tool_arguments_do_not_read_customer(isolated):
    node = executor()
    result = node.invoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "bad", "name": "get_customer", "args": {"cpf": []}}
                    ],
                )
            ]
        },
        {"configurable": {"thread_id": "schema-test"}},
    )
    assert result["messages"][-1].status == "error"
    assert "debt" not in result["messages"][-1].content


def test_unknown_tool_is_rejected(isolated):
    node = executor()
    result = node.invoke(
        {
            "messages": [
                AIMessage(
                    content="", tool_calls=[{"id": "bad", "name": "shell", "args": {}}]
                )
            ]
        },
        {"configurable": {"thread_id": "schema-test"}},
    )
    assert result["messages"][-1].status == "error"


def test_incomplete_provider_response_is_not_marked_complete():
    with pytest.raises(RuntimeError, match="provider_response_incomplete"):
        filter_enabled_tools._completed(
            SimpleNamespace(result=[AIMessage(content="partial")])
        )


def test_publication_requires_new_approval(isolated, monkeypatch):
    from simple_agent import admin_graph_v2 as admin

    monkeypatch.setattr(admin, "store", isolated)
    request = {"operation": "import_bundle", "files": {"index.md": "# Synthetic"}}
    assert admin.execute(request)["error"] == "human_approval_required"
    result = admin.execute({**request, "approved": True})
    assert not result["error"]
    assert result["approved"] is False
    assert admin.execute(result)["error"] == "human_approval_required"


def test_disabled_tool_cannot_execute(monkeypatch):
    from simple_agent import tool_middleware

    monkeypatch.setattr(tool_middleware.registry, "enabled_names", lambda: set())
    request = SimpleNamespace(tool_call={"name": "get_customer", "id": "x", "args": {}})

    def unexpected(_):
        pytest.fail("disabled handler executed")

    result = tool_middleware.filter_enabled_tools.wrap_tool_call(request, unexpected)
    assert json.loads(result.content)["message"] == "tool_disabled"
