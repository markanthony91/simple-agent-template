"""Exercise operator endpoints through real temporary stores, never live APIs."""

import pytest


@pytest.fixture
def admin(isolated, monkeypatch, tmp_path):
    from simple_agent import admin_graph_v2 as module
    from simple_agent.services.simulator_store import SimulatorStore
    from simple_agent.services.tool_registry import ToolRegistry

    monkeypatch.setattr(module, "store", isolated)
    monkeypatch.setattr(module, "simulator", SimulatorStore())
    monkeypatch.setattr(module, "registry", ToolRegistry(tmp_path / "tools"))
    return module


def test_admin_edit_validate_publish_and_rollback(admin):
    def call(operation, **values):
        result = admin.execute({"operation": operation, **values})
        assert result["error"] == "", result
        return result["result"]

    first = call("import_bundle", approved=True, files={"index.md": "# Initial"})
    assert call("status")["file_count"] == 1
    assert call("list")["file_count"] == 1
    assert call("read", path="index.md")["content"].endswith("# Initial")
    draft = call("create_draft")
    draft_id = draft["draft_id"]
    assert call("list_drafts")
    assert call("draft_list", draft_id=draft_id)["file_count"] == 1
    call("draft_write", draft_id=draft_id, path="index.md", content="# Updated")
    assert (
        call("draft_read", draft_id=draft_id, path="index.md")["content"] == "# Updated"
    )
    assert call("validate_draft", draft_id=draft_id)
    call("publish_draft", draft_id=draft_id, approved=True)
    assert len(call("list_versions")) == 2
    call("activate_bundle", bundle_id=first["bundle_id"], approved=True)
    assert call("read", path="index.md")["content"].endswith("# Initial")


def test_admin_tools_and_fixture_contract(admin):
    assert admin.execute({"operation": "list_tools"})["result"]
    changed = admin.execute(
        {"operation": "set_tool_enabled", "tool_name": "okf_read", "enabled": False}
    )
    assert changed["result"]["enabled"] is False
    assert "okf_read" not in admin.registry.enabled_names()
    assert admin.execute({"operation": "reset_tools"})["result"]
    assert "okf_read" in admin.registry.enabled_names()
    fixture = admin.execute({"operation": "get_simulator_fixture"})["result"]
    result = admin.execute({"operation": "save_simulator_fixture", "fixture": fixture})
    assert not result["error"]
    assert isinstance(result["result"]["debt"]["current_amount"], str)


def test_tool_usage_matches_runtime_without_injected_arguments(admin):
    from simple_agent.managed_graph import ALL_TOOLS

    before = admin.registry.registry_file.read_bytes()
    response = admin.execute({"operation": "list_tools"})
    assert response["error"] == ""
    records = {item["name"]: item for item in response["result"]}
    assert set(records) == {tool.name for tool in ALL_TOOLS}
    for tool in ALL_TOOLS:
        record = records[tool.name]
        assert record["usage_description"] == tool.description
        assert record["parameters"] == tool.tool_call_schema.model_json_schema()
        assert "runtime" not in record["parameters"].get("properties", {})
    assert "cpf" in records["verify_customer_identity"]["parameters"]["required"]
    assert admin.registry.registry_file.read_bytes() == before


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"operation": "read"}, "path is required"),
        ({"operation": "import_bundle", "approved": True}, "files is required"),
        ({"operation": "draft_write"}, "content is required"),
        (
            {"operation": "set_tool_enabled", "enabled": "false"},
            "enabled must be boolean",
        ),
        ({"operation": "save_simulator_fixture"}, "fixture must be an object"),
        ({"operation": "unknown"}, "Unsupported admin operation"),
    ],
)
def test_admin_errors_never_retain_approval(admin, payload, expected):
    result = admin.execute(payload)
    assert expected in result["error"]
    assert result["result"] == {}
    assert result["approved"] is False


def test_missing_draft_document(admin):
    draft = admin.execute({"operation": "create_draft", "from_active": False})["result"]
    result = admin.execute(
        {"operation": "draft_read", "draft_id": draft["draft_id"], "path": "missing.md"}
    )
    assert "Draft file not found" in result["error"]


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({}, "raw_text is required"),
        ({"operation": "create_draft"}, "ingestion_id is required"),
        ({"operation": "save_agents"}, "agents_content is required"),
        ({"operation": "unknown"}, "Unsupported compiler operation"),
    ],
)
def test_raw_graph_rejects_invalid_inputs(payload, expected):
    from simple_agent.raw_compiler_graph import execute

    assert expected in execute(payload)["error"]


def test_raw_graph_dispatches_exact_inputs(monkeypatch):
    from simple_agent import raw_compiler_graph as module
    from unittest.mock import Mock

    compiler = Mock()
    monkeypatch.setattr(module, "compiler", compiler)
    cases = [
        (
            {"raw_text": "untrusted source"},
            "analyze",
            ("raw-source.txt", "untrusted source"),
        ),
        ({"operation": "create_draft", "ingestion_id": "id"}, "create_draft", ("id",)),
        ({"operation": "get_agents"}, "get_agents", ()),
        (
            {"operation": "get_agents_versions", "limit": 10, "offset": 2},
            "get_agents_versions",
            (10, 2),
        ),
        (
            {"operation": "save_agents", "agents_content": "instructions"},
            "save_agents",
            ("instructions",),
        ),
    ]
    for request, method, arguments in cases:
        getattr(compiler, method).return_value = {"synthetic": True}
        result = module.execute(request)
        assert result["result"] == {"synthetic": True}
        assert result["error"] == ""
        getattr(compiler, method).assert_called_once_with(*arguments)
