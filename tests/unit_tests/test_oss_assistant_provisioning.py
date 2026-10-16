from contextlib import nullcontext
from uuid import uuid4

from starlette.testclient import TestClient

from simple_agent import oss_runtime


class FakeDB:
    def __init__(self):
        self.records = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def transaction(self):
        return nullcontext()

    def execute(self, query, params):
        self.query = query
        self.params = params
        if query.startswith("SELECT pg_advisory"):
            self.rows = []
        elif query.startswith("INSERT INTO langgraph.legacy_assistants"):
            self.records.append(params[2].obj)
            self.rows = []
        else:
            graph = params[0] if "(%s::text IS NULL" in query else "agent"
            metadata = (
                params[2].obj
                if "(%s::jsonb IS NULL" in query and params[2]
                else (params[0].obj if "record->'metadata' @> %s" in query else None)
            )
            self.rows = [
                {"record": record}
                for record in self.records
                if (graph is None or record["graph_id"] == graph)
                and (
                    metadata is None
                    or all(record["metadata"].get(k) == v for k, v in metadata.items())
                )
            ]
        return self

    def fetchall(self):
        return self.rows


def test_create_search_and_repeat_are_scoped_and_idempotent(monkeypatch):
    monkeypatch.setenv("OSS_RUNTIME_API_TOKEN", "x" * 64)
    db = FakeDB()
    monkeypatch.setattr(oss_runtime, "_db", lambda: db)
    client = TestClient(oss_runtime.app)
    headers = {"X-Api-Key": "x" * 64}
    tenant = str(uuid4())
    existing = {
        "assistant_id": str(uuid4()),
        "graph_id": "agent",
        "version": 3,
        "metadata": {"zerai_scope_id": "2", "zerai_tenant_id": str(uuid4())},
    }
    db.records.append(existing.copy())
    metadata = {"zerai_scope_id": "42", "zerai_tenant_id": tenant}
    payload = {
        "graph_id": "agent",
        "name": "Banco · Cartao",
        "metadata": metadata,
        "context": {
            "portfolio_context": {"scope_id": "42", "tenant_id": tenant},
            "agent_profile": {"name": "Assistente"},
            "allowed_tools": [],
        },
    }
    assert client.post("/assistants", json=payload).status_code == 401
    created = client.post("/assistants", json=payload, headers=headers)
    assert created.status_code == 200
    assert created.json()["version"] == 1
    assert created.json()["metadata"] == metadata
    assert len(db.records) == 2
    repeated = client.post("/assistants", json=payload, headers=headers)
    assert repeated.json()["assistant_id"] == created.json()["assistant_id"]
    assert len(db.records) == 2
    found = client.post(
        "/assistants/search",
        json={"graph_id": "agent", "metadata": metadata},
        headers=headers,
    )
    assert [item["assistant_id"] for item in found.json()] == [
        created.json()["assistant_id"]
    ]
    other = client.post(
        "/assistants/search",
        json={"graph_id": "agent", "metadata": {"zerai_scope_id": "2"}},
        headers=headers,
    )
    assert [item["assistant_id"] for item in other.json()] == [existing["assistant_id"]]
    assert db.records[0] == existing


def test_create_rejects_unscoped_or_mismatched_assistant(monkeypatch):
    monkeypatch.setenv("OSS_RUNTIME_API_TOKEN", "x" * 64)
    db = FakeDB()
    monkeypatch.setattr(oss_runtime, "_db", lambda: db)
    client = TestClient(oss_runtime.app)
    headers = {"X-Api-Key": "x" * 64}
    tenant = str(uuid4())
    payload = {
        "graph_id": "agent",
        "name": "Teste",
        "metadata": {"zerai_scope_id": "4", "zerai_tenant_id": tenant},
        "context": {
            "portfolio_context": {"scope_id": "4", "tenant_id": tenant},
            "agent_profile": {"name": "Teste"},
            "allowed_tools": [],
        },
    }
    assert (
        client.post(
            "/assistants", json={**payload, "graph_id": "okf_admin"}, headers=headers
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/assistants",
            json={**payload, "metadata": {"zerai_scope_id": "2"}},
            headers=headers,
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/assistants",
            json={
                **payload,
                "context": {
                    **payload["context"],
                    "portfolio_context": {"scope_id": "2", "tenant_id": tenant},
                },
            },
            headers=headers,
        ).status_code
        == 400
    )
    assert db.records == []
