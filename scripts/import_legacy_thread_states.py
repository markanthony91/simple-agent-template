"""Import a verified live-state rehearsal into the isolated PostgreSQL canary."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import socket
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/tmp/ossdeps")

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from simple_agent.managed_graph import graph

CANARY_SERVICE_ID = "accedeb1-4a8d-455e-a7ed-f4d2d7d92dec"


def import_states(path: Path, expected_sha256: str) -> dict:
    if os.getenv("RAILWAY_SERVICE_ID") != CANARY_SERVICE_ID:
        raise ValueError("wrong_service")
    if os.getenv("SESSION_BACKEND") != "postgres":
        raise ValueError("wrong_backend")
    if os.getenv("LANGGRAPH_STRICT_MSGPACK") != "true":
        raise ValueError("strict_serialization_required")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("snapshot_hash_mismatch")
    with gzip.open(path, "rt", encoding="utf-8") as source:
        threads = [json.loads(line) for line in source]
    if len({thread["thread_id"] for thread in threads}) != len(threads):
        raise ValueError("duplicate_threads")
    if any(thread.get("metadata", {}).get("graph_id") != "agent" for thread in threads):
        raise ValueError("wrong_graph")

    dsn = os.environ["SESSION_DATABASE_URL"]
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as db:
        db.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
        db.execute(
            """CREATE TABLE IF NOT EXISTS langgraph.legacy_thread_state (
                thread_id text PRIMARY KEY,
                status text NOT NULL,
                metadata jsonb NOT NULL,
                state jsonb NOT NULL,
                created_at timestamptz,
                updated_at timestamptz,
                state_updated_at timestamptz,
                source_sha256 text NOT NULL,
                imported_at timestamptz NOT NULL DEFAULT now(),
                hostname text NOT NULL
            )"""
        )
        if db.execute("SELECT COUNT(*) AS n FROM langgraph.legacy_thread_state").fetchone()["n"]:
            raise ValueError("archive_not_empty")
        db.execute("SET search_path TO langgraph")
        saver = PostgresSaver(db)
        saver.setup()
        if db.execute("SELECT COUNT(*) AS n FROM langgraph.checkpoints").fetchone()["n"]:
            raise ValueError("checkpoints_not_empty")
        graph.checkpointer = saver
        counts: Counter[str] = Counter()
        with db.transaction():
            for thread in threads:
                db.execute(
                    """INSERT INTO langgraph.legacy_thread_state (
                        thread_id,status,metadata,state,created_at,updated_at,
                        state_updated_at,source_sha256,hostname
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        thread["thread_id"], thread["status"], Jsonb(thread["metadata"]),
                        Jsonb(thread["values"]), thread.get("created_at"),
                        thread.get("updated_at"), thread.get("state_updated_at"),
                        expected_sha256, socket.gethostname(),
                    ),
                )
                counts["archived"] += 1
        for thread in threads:
            if thread["status"] != "idle":
                counts["error_archived_only"] += 1
                continue
            config = {"configurable": {"thread_id": thread["thread_id"]}}
            graph.update_state(
                config, thread["values"], as_node="DirectReplyMiddleware.after_agent"
            )
            state = graph.get_state(config)
            old = thread["values"]
            if state.next or len(state.values["messages"]) != len(old["messages"]):
                raise ValueError("imported_state_mismatch")
            if [message.content for message in state.values["messages"]] != [
                message["content"] for message in old["messages"]
            ]:
                raise ValueError("imported_content_mismatch")
            counts["resumable"] += 1
            counts["messages"] += len(old["messages"])
        return dict(counts)


if __name__ == "__main__":
    try:
        print(json.dumps(import_states(Path(sys.argv[1]), sys.argv[2])))
    except Exception as exc:  # noqa: BLE001 - suppress conversation data in failures
        print(f"legacy_import_failed:{type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
