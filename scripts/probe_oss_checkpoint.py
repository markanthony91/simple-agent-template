"""Exercise OSS LangGraph checkpoint migration in the isolated Railway canary.

This uses only synthetic messages and the canary's PostgreSQL database. It does
not invoke the configured model, business tools, or external channels.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from typing import Annotated, TypedDict
from uuid import uuid4

sys.path.insert(0, "/tmp/ossdeps")

import psycopg
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from psycopg.rows import dict_row


class State(TypedDict):
    messages: Annotated[list, add_messages]


def graph_for(checkpointer):
    builder = StateGraph(State)
    builder.add_node("reply", lambda state: {"messages": [AIMessage(content="synthetic-reply")]})
    builder.add_edge(START, "reply")
    builder.add_edge("reply", END)
    return builder.compile(checkpointer=checkpointer)


def migrate_thread(source, target, config):
    history = list(source.list(config))
    for item in reversed(history):
        parent = item.parent_config or {
            "configurable": {"thread_id": config["configurable"]["thread_id"], "checkpoint_ns": ""}
        }
        saved = target.put(parent, item.checkpoint, item.metadata, item.checkpoint["channel_versions"])
        writes_by_task = defaultdict(list)
        for task_id, channel, value in item.pending_writes:
            writes_by_task[task_id].append((channel, value))
        for task_id, writes in writes_by_task.items():
            target.put_writes(saved, writes, task_id)
    imported = list(target.list(config))
    if [item.checkpoint["id"] for item in imported] != [item.checkpoint["id"] for item in history]:
        raise ValueError("checkpoint_history_mismatch")
    return len(history)


def main():
    if os.getenv("RAILWAY_SERVICE_ID") != "accedeb1-4a8d-455e-a7ed-f4d2d7d92dec":
        raise ValueError("wrong_service")
    if os.getenv("SESSION_BACKEND") != "postgres":
        raise ValueError("wrong_backend")
    dsn = os.environ["SESSION_DATABASE_URL"]
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute("CREATE SCHEMA IF NOT EXISTS oss_checkpoint_probe")
    with psycopg.connect(
        dsn, autocommit=True, row_factory=dict_row,
        options="-c search_path=oss_checkpoint_probe",
    ) as db:
        target = PostgresSaver(db)
        target.setup()
        legacy = InMemorySaver()
        old_config = {"configurable": {"thread_id": "oss-probe-old-" + uuid4().hex}}
        graph_for(legacy).invoke({"messages": [HumanMessage(content="synthetic-one")]}, old_config)
        history_count = migrate_thread(legacy, target, old_config)
        resumed = graph_for(target).invoke(
            {"messages": [HumanMessage(content="synthetic-two")]}, old_config
        )
        old_ok = len(resumed["messages"]) == 4
        fresh_config = {"configurable": {"thread_id": "oss-probe-new-" + uuid4().hex}}
        graph_for(target).invoke({"messages": [HumanMessage(content="synthetic-one")]}, fresh_config)
        fresh = graph_for(target).invoke(
            {"messages": [HumanMessage(content="synthetic-two")]}, fresh_config
        )
        new_ok = len(fresh["messages"]) == 4
        target.delete_thread(old_config["configurable"]["thread_id"])
        target.delete_thread(fresh_config["configurable"]["thread_id"])
        if not old_ok or not new_ok:
            raise ValueError("conversation_continuity_failed")
        print(json.dumps({"synthetic_legacy_checkpoints": history_count,
                          "old_thread_resumed": old_ok, "new_thread_persisted": new_ok}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - suppress credentials in DB errors
        print(f"checkpoint_probe_failed:{type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
