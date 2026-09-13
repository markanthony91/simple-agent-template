from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from simple_agent.services.okf_store import PersistentOKFStore


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
    result: dict[str, Any] | list[dict[str, Any]]
    error: str


store = PersistentOKFStore()


def execute(state: AdminState) -> AdminState:
    operation = state.get("operation", "status")
    try:
        if operation == "status":
            result: dict[str, Any] | list[dict[str, Any]] = store.status()
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
            path = state.get("path")
            if not isinstance(path, str) or not path:
                raise ValueError("path is required")
            result = {"path": path, "content": store.read_file(path)}
        elif operation == "write":
            path = state.get("path")
            content = state.get("content")
            if not isinstance(path, str) or not path:
                raise ValueError("path is required")
            if not isinstance(content, str):
                raise ValueError("content is required")
            result = store.write_file(path, content)
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
            draft_id = _draft_id(state)
            files = store.draft_files(draft_id)
            result = {"draft_id": draft_id, "files": sorted(files), "file_count": len(files)}
        elif operation == "draft_read":
            draft_id = _draft_id(state)
            path = _path(state)
            files = store.draft_files(draft_id)
            if path not in files:
                raise FileNotFoundError(f"Draft file not found: {path}")
            result = {"draft_id": draft_id, "path": path, "content": files[path]}
        elif operation == "draft_write":
            draft_id = _draft_id(state)
            path = _path(state)
            content = state.get("content")
            if not isinstance(content, str):
                raise ValueError("content is required")
            result = store.write_draft_file(draft_id, path, content)
        elif operation == "validate_draft":
            result = store.validate_draft(_draft_id(state))
        elif operation == "publish_draft":
            result = store.publish_draft(_draft_id(state))
        elif operation == "list_versions":
            result = store.list_versions()
        elif operation == "activate_bundle":
            result = store.activate_bundle(_bundle_id(state))
        else:
            raise ValueError(f"Unsupported OKF admin operation: {operation}")
        return {**state, "result": result, "error": ""}
    except Exception as exc:
        return {**state, "result": {}, "error": str(exc)}


def _draft_id(state: AdminState) -> str:
    value = state.get("draft_id")
    if not isinstance(value, str) or not value:
        raise ValueError("draft_id is required")
    return value


def _bundle_id(state: AdminState) -> str:
    value = state.get("bundle_id")
    if not isinstance(value, str) or not value:
        raise ValueError("bundle_id is required")
    return value


def _path(state: AdminState) -> str:
    value = state.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError("path is required")
    return value


builder = StateGraph(AdminState)
builder.add_node("execute", execute)
builder.add_edge(START, "execute")
builder.add_edge("execute", END)
graph = builder.compile()
