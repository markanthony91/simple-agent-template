"""Hydrate one completed legacy conversation in the isolated OSS canary.

This verifies message continuity only; it does not migrate intermediate
checkpoints or execute the LLM, tools, channels, or payment actions.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, "/tmp/ossdeps")

import psycopg
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

from simple_agent.managed_graph import graph


def main(source_path: Path) -> None:
    if os.getenv("RAILWAY_SERVICE_ID") != "accedeb1-4a8d-455e-a7ed-f4d2d7d92dec":
        raise ValueError("wrong_service")
    source = json.loads(source_path.read_text())
    if source.get("next") or source.get("tasks"):
        raise ValueError("legacy_thread_not_idle")
    messages = source["values"]["messages"]
    if not isinstance(messages, list) or not messages:
        raise ValueError("legacy_messages_missing")
    dsn = os.environ["SESSION_DATABASE_URL"]
    with psycopg.connect(
        dsn, autocommit=True, row_factory=dict_row,
        options="-c search_path=oss_checkpoint_probe",
    ) as db:
        saver = PostgresSaver(db)
        graph.checkpointer = saver
        thread_id = "oss-probe-hydrated-" + uuid4().hex
        config = {"configurable": {"thread_id": thread_id}}
        try:
            graph.update_state(config, {"messages": messages}, as_node="DirectReplyMiddleware.after_agent")
            state = graph.get_state(config)
            restored = state.values["messages"]
            if state.next or len(restored) != len(messages):
                raise ValueError("legacy_state_mismatch")
            if [item.content for item in restored] != [item["content"] for item in messages]:
                raise ValueError("legacy_content_mismatch")
            graph.update_state(
                config,
                {"messages": [HumanMessage(content="synthetic-follow-up"),
                              AIMessage(content="synthetic-reply")]},
                as_node="DirectReplyMiddleware.after_agent",
            )
            continued = graph.get_state(config)
            if continued.next or len(continued.values["messages"]) != len(messages) + 2:
                raise ValueError("legacy_continuation_mismatch")
            print(json.dumps({"legacy_messages": len(messages),
                              "hydrated": True, "continued_without_llm": True}))
        finally:
            saver.delete_thread(thread_id)


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001 - suppress conversation content in errors
        print(f"hydration_probe_failed:{type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
