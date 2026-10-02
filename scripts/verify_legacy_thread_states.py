"""Read canary states in a new process and compare them with the live API archive."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, "/tmp/ossdeps")

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

from simple_agent.managed_graph import graph


def verify() -> dict:
    if os.getenv("RAILWAY_SERVICE_ID") != "accedeb1-4a8d-455e-a7ed-f4d2d7d92dec":
        raise ValueError("wrong_service")
    if os.getenv("LANGGRAPH_STRICT_MSGPACK") != "true":
        raise ValueError("strict_serialization_required")
    with psycopg.connect(
        os.environ["SESSION_DATABASE_URL"],
        autocommit=True,
        row_factory=dict_row,
        options="-c search_path=langgraph",
    ) as db:
        graph.checkpointer = PostgresSaver(db)
        rows = db.execute(
            "SELECT thread_id,status,state,source_sha256 FROM langgraph.legacy_thread_state"
        ).fetchall()
        if len({row["source_sha256"] for row in rows}) != 1:
            raise ValueError("mixed_snapshots")
        counts: Counter[str] = Counter()
        for row in rows:
            config = {"configurable": {"thread_id": row["thread_id"]}}
            if row["status"] == "error":
                if graph.get_state(config).values:
                    raise ValueError("error_thread_resumable")
                counts["error_archived_only"] += 1
                continue
            state = graph.get_state(config)
            old = row["state"]
            if state.next or state.values.get("jump_to") != old.get("jump_to"):
                raise ValueError("state_mismatch")
            current = state.values.get("messages") or []
            if len(current) != len(old["messages"]):
                raise ValueError("message_count_mismatch")
            for before, after in zip(old["messages"], current, strict=True):
                if any(
                    before.get(key) != getattr(after, key, None)
                    for key in ("id", "type", "content", "tool_calls")
                    if key in before
                ):
                    raise ValueError("message_mismatch")
            counts["resumable"] += 1
            counts["messages"] += len(current)
        counts["archived"] = len(rows)
        return dict(counts)


if __name__ == "__main__":
    try:
        print(json.dumps(verify()))
    except Exception as exc:  # noqa: BLE001 - suppress conversation data in failures
        print(f"legacy_verification_failed:{type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
