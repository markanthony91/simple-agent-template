from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from simple_agent.services.raw_okf_compiler import RawOKFCompiler


class RawCompilerState(TypedDict, total=False):
    operation: str
    source_name: str
    raw_text: str
    ingestion_id: str
    result: dict[str, Any]
    error: str


compiler = RawOKFCompiler()
raw_agents_path = Path(__file__).resolve().parents[2] / "config" / "RAW_AGENTS.md"


def execute(state: RawCompilerState) -> RawCompilerState:
    try:
        operation = state.get("operation", "analyze")
        if operation == "analyze":
            text = state.get("raw_text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("raw_text is required")
            result = compiler.analyze(str(state.get("source_name") or "raw-source.txt"), text)
        elif operation == "create_draft":
            ingestion_id = state.get("ingestion_id")
            if not isinstance(ingestion_id, str) or not ingestion_id:
                raise ValueError("ingestion_id is required")
            result = compiler.create_draft(ingestion_id)
        elif operation == "get_agents":
            if not raw_agents_path.exists():
                raise FileNotFoundError("RAW_AGENTS.md not found")
            result = {
                "content": raw_agents_path.read_text(encoding="utf-8"),
                "source": "config/RAW_AGENTS.md",
                "editable": False,
            }
        else:
            raise ValueError("Unsupported compiler operation")
        return {**state, "result": result, "error": ""}
    except Exception as exc:
        return {**state, "result": {}, "error": str(exc)}


builder = StateGraph(RawCompilerState)
builder.add_node("execute", execute)
builder.add_edge(START, "execute")
builder.add_edge("execute", END)
graph = builder.compile()
