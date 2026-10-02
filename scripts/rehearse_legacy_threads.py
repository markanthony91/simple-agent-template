"""Validate legacy agent states against the real graph without LLM or DB writes."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from simple_agent.managed_graph import graph

CANARY_SERVICE_ID = "accedeb1-4a8d-455e-a7ed-f4d2d7d92dec"


def rehearse(path: Path, expected_sha256: str) -> dict:
    if os.getenv("RAILWAY_SERVICE_ID") != CANARY_SERVICE_ID:
        raise ValueError("wrong_service")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("snapshot_hash_mismatch")
    graph.checkpointer = InMemorySaver()
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in source:
            thread = json.loads(line)
            thread_id = thread["thread_id"]
            if thread_id in seen or thread.get("metadata", {}).get("graph_id") != "agent":
                raise ValueError("duplicate_or_mismatched_thread")
            seen.add(thread_id)
            status = thread["status"]
            values = thread["values"]
            if not isinstance(values.get("messages"), list) or not values["messages"]:
                raise ValueError("missing_messages")
            counts[status] += 1
            counts["messages"] += len(values["messages"])
            if status != "idle":
                continue
            config = {"configurable": {"thread_id": thread_id}}
            graph.update_state(config, values, as_node="DirectReplyMiddleware.after_agent")
            restored = graph.get_state(config)
            if restored.next or len(restored.values["messages"]) != len(values["messages"]):
                raise ValueError("state_shape_mismatch")
            if restored.values.get("jump_to") != values.get("jump_to"):
                raise ValueError("routing_state_mismatch")
            for old, new in zip(values["messages"], restored.values["messages"], strict=True):
                if any(
                    old.get(key) != getattr(new, key, None)
                    for key in ("id", "type", "content", "tool_calls")
                    if key in old
                ):
                    raise ValueError("message_mismatch")
            counts["resumable"] += 1
    return dict(counts)


if __name__ == "__main__":
    try:
        print(json.dumps(rehearse(Path(sys.argv[1]), sys.argv[2])))
    except Exception as exc:  # noqa: BLE001 - suppress conversation data in failures
        print(f"legacy_rehearsal_failed:{type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
