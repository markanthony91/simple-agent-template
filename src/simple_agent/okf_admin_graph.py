from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from simple_agent.services.okf_store import PersistentOKFStore


class AdminState(TypedDict, total=False):
    operation: str
    bundle_name: str
    bundle_version: str
    files: dict[str, str]
    path: str
    content: str
    result: dict[str, Any]
    error: str


store = PersistentOKFStore()


def execute(state: AdminState) -> AdminState:
    operation = state.get("operation", "status")
    try:
        if operation == "status":
            result: dict[str, Any] = store.status()
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
        else:
            raise ValueError(f"Unsupported OKF admin operation: {operation}")
        return {**state, "result": result, "error": ""}
    except Exception as exc:
        return {**state, "result": {}, "error": str(exc)}


builder = StateGraph(AdminState)
builder.add_node("execute", execute)
builder.add_edge(START, "execute")
builder.add_edge("execute", END)
graph = builder.compile()
