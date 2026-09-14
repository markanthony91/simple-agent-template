import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage


def test_knowledge_wrappers_and_recoverable_errors(isolated):
    from simple_agent.tools import okf_tools as tools
    from simple_agent.services.session_store import SessionStore

    isolated.import_bundle(
        "test",
        "0.2",
        {
            "index.md": "# Test\n[Policy](policy.md)",
            "policy.md": "---\ntype: Policy\n---\n# Policy\n## Terms\nSynthetic rule.",
        },
    )
    runtime = SimpleNamespace(config={"configurable": {"thread_id": "wrappers"}})
    assert "Policy" in tools.okf_index.func(runtime=runtime)
    assert "policy.md" in tools.okf_list.func(runtime=runtime)
    assert "Synthetic" in tools.okf_search.func(query="Synthetic", runtime=runtime)
    assert "Synthetic" in tools.okf_read_section.func(
        path="policy.md", heading="Terms", runtime=runtime
    )
    with SessionStore().transaction("wrappers") as state:
        assert state["receipts"]["policy.md"]["hash"]
    for tool, kwargs in [
        (tools.okf_read, {"path": "../bad.md"}),
        (tools.okf_read_section, {"path": "../bad.md", "heading": "X"}),
        (tools.okf_search, {"query": "a", "scope": "../bad"}),
        (tools.okf_index, {"directory": "../bad"}),
    ]:
        assert json.loads(tool.func(runtime=runtime, **kwargs))["error"] is True
    with SessionStore().transaction("empty") as state:
        state["snapshot_id"] = None
    empty = SimpleNamespace(config={"configurable": {"thread_id": "empty"}})
    assert json.loads(tools.okf_list.func(runtime=empty))["error"] is True


@pytest.mark.anyio
async def test_async_tool_middleware_success_and_error(monkeypatch):
    from simple_agent.tool_middleware import filter_enabled_tools, registry

    monkeypatch.setattr(registry, "enabled_names", lambda: {"okf_read"})
    request = SimpleNamespace(
        tool_call={"name": "okf_read", "id": "call", "args": {"path": "x.md"}}
    )

    async def success(_):
        return ToolMessage(content="document", tool_call_id="call")

    async def failure(_):
        raise ValueError("safe_error")

    assert (
        await filter_enabled_tools.awrap_tool_call(request, success)
    ).content == "document"
    assert json.loads(
        (await filter_enabled_tools.awrap_tool_call(request, failure)).content
    )["recoverable"]


def test_observability_redacts_nested_sensitive_fields():
    from simple_agent.tool_observability import (
        sanitize_result,
        sanitize_tool_args,
        extract_trace_ids,
    )

    redacted = sanitize_tool_args(
        "get_customer",
        {"token": "secret", "nested": [{"full_name": "Synthetic"}], "cpf": "01"},
    )
    assert redacted["token"] == "<redacted>"
    assert redacted["nested"][0]["full_name"] == "<redacted>"
    assert redacted["cpf"] == "***.***.***-01"
    assert sanitize_result("okf_read", "private document") == {"content_length": 16}
    assert sanitize_result("get_customer", '{"password":"secret"}') == {
        "password": "<redacted>"
    }
    assert sanitize_result("get_customer", {"api_key": "secret"}) == {
        "api_key": "<redacted>"
    }
    assert sanitize_result("get_customer", "x" * 1000).endswith("<truncated>")
    assert sanitize_result("get_customer", "[1,2]") == [1, 2]
    assert sanitize_result("get_customer", 1) == "1"
    request = SimpleNamespace(
        config={"configurable": {"thread_id": "thread"}, "metadata": {"run_id": "run"}}
    )
    assert extract_trace_ids(request) == {"thread_id": "thread", "run_id": "run"}
