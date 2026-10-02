"""Copy the current assistant definitions to the isolated migration canary."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import socket
import sys
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

CANARY_SERVICE_ID = "accedeb1-4a8d-455e-a7ed-f4d2d7d92dec"


def import_assistants(path: Path, expected_sha256: str) -> dict[str, int]:
    if os.getenv("RAILWAY_SERVICE_ID") != CANARY_SERVICE_ID:
        raise ValueError("wrong_service")
    if os.getenv("SESSION_BACKEND") != "postgres":
        raise ValueError("wrong_backend")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("snapshot_hash_mismatch")
    with gzip.open(path, "rt", encoding="utf-8") as source:
        assistants = json.load(source)
    if not isinstance(assistants, list) or len(assistants) != len(
        {record["assistant_id"] for record in assistants}
    ):
        raise ValueError("invalid_assistants")

    with psycopg.connect(os.environ["SESSION_DATABASE_URL"]) as db, db.transaction():
            db.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
            db.execute(
                """CREATE TABLE IF NOT EXISTS langgraph.legacy_assistants (
                    assistant_id uuid PRIMARY KEY,
                    graph_id text NOT NULL,
                    record jsonb NOT NULL,
                    source_sha256 text NOT NULL,
                    imported_at timestamptz NOT NULL DEFAULT now(),
                    hostname text NOT NULL
                )"""
            )
            if db.execute(
                "SELECT COUNT(*) FROM langgraph.legacy_assistants"
            ).fetchone()[0]:
                raise ValueError("assistants_not_empty")
            for record in assistants:
                db.execute(
                    """INSERT INTO langgraph.legacy_assistants
                    (assistant_id,graph_id,record,source_sha256,hostname)
                    VALUES (%s,%s,%s,%s,%s)""",
                    (
                        record["assistant_id"],
                        record["graph_id"],
                        Jsonb(record),
                        expected_sha256,
                        socket.gethostname(),
                    ),
                )
    return {"assistants": len(assistants)}


if __name__ == "__main__":
    try:
        print(json.dumps(import_assistants(Path(sys.argv[1]), sys.argv[2])))
    except Exception as exc:  # noqa: BLE001 - keep assistant context out of logs
        print(f"assistant_import_failed:{type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
