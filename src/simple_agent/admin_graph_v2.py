from __future__ import annotations

from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph
from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.simulator_store import SimulatorStore
from simple_agent.services.tool_registry import ToolRegistry


class AdminState(TypedDict, total=False):
    operation: str
    bundle_name: str
    bundle_version: str
    bundle_id: str
    files: dict[str, str]
    path: str
    content: str
    draft_id: str
    from_active: bool
    tool_name: str
    enabled: bool
    fixture: dict[str, Any]
    result: dict[str, Any] | list[dict[str, Any]]
    error: str
    approved: bool


store = PersistentOKFStore()
simulator = SimulatorStore()
registry = ToolRegistry()


def required_text(state: AdminState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} is required")
    return value


def execute(state: AdminState) -> AdminState:
    operation = state.get("operation", "status")
    try:
        if (
            operation in {"import_bundle", "publish_draft", "activate_bundle"}
            and state.get("approved") is not True
        ):
            raise ValueError("human_approval_required")
        if operation == "status":
            result = store.status()
        elif operation == "list":
            status = store.status()
            result = {
                "files": store.list_files(),
                "bundle_name": status.get("bundle_name"),
                "bundle_version": status.get("bundle_version"),
                "bundle_id": status.get("bundle_id"),
                "file_count": status.get("file_count", 0),
            }
        elif operation == "read":
            path = required_text(state, "path")
            result = {"path": path, "content": store.read_file(path)}
        elif operation == "import_bundle":
            files = state.get("files")
            if not isinstance(files, dict):
                raise ValueError("files is required")
            result = store.import_bundle(
                str(state.get("bundle_name") or "okf-bundle"),
                str(state.get("bundle_version") or "0.2"),
                files,
            )
        elif operation == "create_draft":
            result = store.create_draft(
                str(state.get("bundle_name") or "okf-draft"),
                str(state.get("bundle_version") or "0.2"),
                bool(state.get("from_active", True)),
            )
        elif operation == "list_drafts":
            result = store.list_drafts()
        elif operation == "draft_list":
            draft_id = required_text(state, "draft_id")
            files = store.draft_files(draft_id)
            result = {
                "draft_id": draft_id,
                "files": sorted(files),
                "file_count": len(files),
            }
        elif operation == "draft_read":
            draft_id = required_text(state, "draft_id")
            path = required_text(state, "path")
            files = store.draft_files(draft_id)
            if path not in files:
                raise FileNotFoundError(f"Draft file not found: {path}")
            result = {"draft_id": draft_id, "path": path, "content": files[path]}
        elif operation == "draft_write":
            content = state.get("content")
            if not isinstance(content, str):
                raise ValueError("content is required")
            result = store.write_draft_file(
                required_text(state, "draft_id"),
                required_text(state, "path"),
                content,
            )
        elif operation == "validate_draft":
            result = store.validate_draft(required_text(state, "draft_id"))
        elif operation == "publish_draft":
            result = store.publish_draft(required_text(state, "draft_id"))
        elif operation == "list_versions":
            result = store.list_versions()
        elif operation == "activate_bundle":
            result = store.activate_bundle(required_text(state, "bundle_id"))
        elif operation == "list_tools":
            from simple_agent.managed_graph import ALL_TOOLS

            contracts = {tool.name: tool for tool in ALL_TOOLS}
            result = registry.list_tools()
            for item in result:
                tool = contracts.get(item["name"])
                if tool is not None:
                    schema = tool.tool_call_schema
                    item["usage_description"] = tool.description
                    item["parameters"] = (
                        schema
                        if isinstance(schema, dict)
                        else schema.model_json_schema()
                    )
        elif operation == "set_tool_enabled":
            value = state.get("enabled")
            if not isinstance(value, bool):
                raise ValueError("enabled must be boolean")
            result = registry.set_enabled(required_text(state, "tool_name"), value)
        elif operation == "reset_tools":
            result = registry.reset()
        elif operation == "get_simulator_fixture":
            result = simulator.load()
        elif operation == "save_simulator_fixture":
            fixture = state.get("fixture")
            if not isinstance(fixture, dict):
                raise ValueError("fixture must be an object")
            result = simulator.save(fixture)
        else:
            raise ValueError(f"Unsupported admin operation: {operation}")
        return {**state, "result": result, "error": "", "approved": False}
    except Exception as exc:
        return {**state, "result": {}, "error": str(exc), "approved": False}


builder = StateGraph(AdminState)
builder.add_node("execute", execute)
builder.add_edge(START, "execute")
builder.add_edge("execute", END)
graph = builder.compile()
