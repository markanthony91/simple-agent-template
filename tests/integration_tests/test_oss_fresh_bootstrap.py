"""Opt-in bootstrap check against a disposable, empty PostgreSQL database."""

import os
from operator import add
from typing import Annotated, TypedDict
from uuid import uuid4

import psycopg
import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.types.json import Jsonb
from starlette.testclient import TestClient


class Counter(TypedDict):
    count: Annotated[int, add]


def test_oss_boots_without_legacy_history(monkeypatch):
    dsn = os.getenv("OSS_FRESH_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set OSS_FRESH_TEST_DATABASE_URL to a disposable empty database")
    with psycopg.connect(dsn) as db:
        assert db.execute("SELECT to_regnamespace('langgraph')").fetchone()[0] is None

    monkeypatch.setenv("SESSION_BACKEND", "postgres")
    monkeypatch.setenv("SESSION_DATABASE_URL", dsn)
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    monkeypatch.setenv("OSS_RUNTIME_API_TOKEN", "synthetic-test-token-" + uuid4().hex)

    from scripts.apply_postgres_migrations import main as apply_migrations
    from simple_agent import oss_runtime

    apply_migrations()
    with psycopg.connect(dsn) as db:
        assert (
            db.execute(
                "SELECT to_regclass('langgraph.legacy_thread_state')"
            ).fetchone()[0]
            is None
        )

    headers = {"X-Api-Key": os.environ["OSS_RUNTIME_API_TOKEN"]}
    assistant_id = str(uuid4())
    record = {
        "assistant_id": assistant_id,
        "graph_id": "agent",
        "version": 1,
        "config": {},
        "context": {},
        "metadata": {},
        "name": "synthetic",
    }
    with TestClient(oss_runtime.app) as client:
        oss_runtime._setup()  # Startup is safe to repeat.
        with psycopg.connect(dsn) as db:
            db.execute(
                """INSERT INTO langgraph.legacy_assistants
                   (assistant_id,graph_id,record,source_sha256,hostname)
                   VALUES (%s,%s,%s,%s,%s)""",
                (assistant_id, "agent", Jsonb(record), "synthetic", "test"),
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM langgraph.legacy_thread_state"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute("SELECT count(*) FROM langgraph.checkpoints").fetchone()[0]
                == 0
            )
        assert (
            client.get(f"/assistants/{assistant_id}", headers=headers).json()["name"]
            == "synthetic"
        )
        versions_url = f"/assistants/{assistant_id}/versions"
        assert [
            row["version"]
            for row in client.post(versions_url, json={}, headers=headers).json()
        ] == [1]
        saved = client.patch(
            f"/assistants/{assistant_id}",
            json={"expected_version": 1, "context": {"system_prompt": "second"}},
            headers=headers,
        )
        assert saved.status_code == 200
        assert saved.json()["version"] == 2
        assert (
            client.patch(
                f"/assistants/{assistant_id}",
                json={"expected_version": 1, "context": {"system_prompt": "stale"}},
                headers=headers,
            ).status_code
            == 409
        )
        versions = client.post(
            versions_url, json={"limit": 2, "offset": 0}, headers=headers
        ).json()
        assert [row["version"] for row in versions] == [2, 1]
        assert versions[0]["context"]["system_prompt"] == "second"
        assert versions[1]["context"] == {}
        assert client.post("/threads/search", json={}, headers=headers).json() == []
        thread = client.post("/threads", json={}, headers=headers)
        assert thread.status_code == 200
        thread_id = thread.json()["thread_id"]
        assert client.get(f"/threads/{thread_id}", headers=headers).status_code == 200
        with psycopg.connect(
            dsn, autocommit=True, options="-c search_path=langgraph"
        ) as db:
            builder = StateGraph(Counter)
            builder.add_node("reply", lambda _state: {"count": 1})
            builder.add_edge(START, "reply")
            builder.add_edge("reply", END)
            graph = builder.compile(checkpointer=PostgresSaver(db))
            config = {"configurable": {"thread_id": thread_id}}
            assert graph.invoke({"count": 1}, config)["count"] == 2
            assert graph.invoke({"count": 1}, config)["count"] == 4
        assert (
            client.delete(f"/threads/{thread_id}", headers=headers).status_code == 204
        )
        with psycopg.connect(dsn) as db:
            assert (
                db.execute("SELECT count(*) FROM langgraph.checkpoints").fetchone()[0]
                == 0
            )
