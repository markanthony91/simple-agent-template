"""Smoke the isolated OSS adapter using a synthetic, unbound conversation."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import sys
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from starlette.testclient import TestClient

CANARY_SERVICE_ID = "accedeb1-4a8d-455e-a7ed-f4d2d7d92dec"
DEFAULT_AGENT_ID = "05fd1686-9a81-4975-bd3b-0b288391d109"
ADMIN_ID = "5e8312e7-6e09-5ce6-80a8-040e86b35af1"


def main() -> None:
    if os.getenv("RAILWAY_SERVICE_ID") != CANARY_SERVICE_ID:
        raise ValueError("wrong_service")
    if os.getenv("SESSION_BACKEND") != "postgres":
        raise ValueError("wrong_backend")
    sys.path.insert(0, "/tmp/ossdeps")
    spec = importlib.util.spec_from_file_location("oss_runtime", "/tmp/oss_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token = secrets.token_hex(32)
    os.environ["OSS_RUNTIME_API_TOKEN"] = token
    os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
    headers = {"X-Api-Key": token}
    thread_id = str(uuid4())
    with TestClient(module.app) as client:
        assistant_id = str(uuid4())
        record = {
            "assistant_id": assistant_id, "graph_id": "agent", "version": 1,
            "config": {}, "context": {"system_prompt": "before"},
            "metadata": {"created_by": "canary-test"}, "name": "canary-test",
            "description": "", "created_at": "2026-10-02T00:00:00Z",
            "updated_at": "2026-10-02T00:00:00Z",
        }
        with psycopg.connect(os.environ["SESSION_DATABASE_URL"], autocommit=True) as db:
            db.execute(
                """INSERT INTO langgraph.legacy_assistants
                   (assistant_id,graph_id,record,source_sha256,hostname)
                   VALUES (%s,%s,%s,%s,%s)""",
                (assistant_id, "agent", Jsonb(record), "synthetic", "canary-test"),
            )
            try:
                changed = client.patch(
                    f"/assistants/{assistant_id}",
                    json={"context": {"system_prompt": "after"}}, headers=headers,
                )
                assert changed.status_code == 200 and changed.json()["version"] == 2, "assistant_update"
                assert client.get(f"/assistants/{assistant_id}", headers=headers).json()["context"]["system_prompt"] == "after", "assistant_readback"
            finally:
                db.execute("DELETE FROM langgraph.legacy_assistants WHERE assistant_id=%s", (assistant_id,))
        disposable = str(uuid4())
        blank = client.post("/threads", json={"thread_id": disposable}, headers=headers)
        assert blank.status_code == 200, "create_disposable"
        deleted = client.delete(f"/threads/{disposable}", headers=headers)
        assert deleted.status_code == 204, "delete_disposable"
        admin_thread = str(uuid4())
        assert client.post("/threads", json={"thread_id": admin_thread}, headers=headers).status_code == 200, "admin_thread"
        admin_events = []
        with client.stream(
            "POST", f"/threads/{admin_thread}/runs/stream",
            json={"assistant_id": ADMIN_ID, "input": {"operation": "status"}, "stream_mode": ["values"]},
            headers=headers,
        ) as admin_stream:
            assert admin_stream.status_code == 200, "admin_stream_status"
            for line in admin_stream.iter_lines():
                if line.startswith("data: "):
                    admin_events.append(json.loads(line[6:]))
        assert admin_events and admin_events[-1].get("error") == "", "admin_stream"
        assert client.delete(f"/threads/{admin_thread}", headers=headers).status_code == 204, "admin_delete"
        with psycopg.connect(os.environ["SESSION_DATABASE_URL"]) as db:
            archived = db.execute(
                "SELECT thread_id,jsonb_array_length(state->'messages') FROM langgraph.legacy_thread_state WHERE status='error' AND jsonb_array_length(state->'messages')>0 LIMIT 1"
            ).fetchone()
        archived_state = client.get(f"/threads/{archived[0]}/state", headers=headers)
        archived_history = client.post(f"/threads/{archived[0]}/history", json={"limit":10}, headers=headers)
        assert archived_state.status_code == 200 and len(archived_state.json()["values"]["messages"]) == archived[1], "archived_state"
        assert archived_history.status_code == 200 and len(archived_history.json()) == 1, "archived_history"
        listed = client.post("/threads/search", json={"metadata":{"graph_id":"agent"},"limit":1000}, headers=headers)
        assert listed.status_code == 200 and len(listed.json()) >= 460, "thread_search"
        assert all("values" in row for row in listed.json()), "thread_values"
        assert client.get("/assistants/" + DEFAULT_AGENT_ID).status_code == 401, "auth"
        agent = client.get("/assistants/" + DEFAULT_AGENT_ID, headers=headers)
        assert agent.status_code == 200 and agent.json()["graph_id"] == "agent", "assistant"
        admin = client.post(
            "/runs/wait",
            json={"assistant_id": "okf_admin", "input": {
                "operation": "ensure_whatsapp_session", "approved": True,
                "thread_id": thread_id,
            }},
            headers=headers,
        )
        assert admin.status_code == 200 and admin.json()["result"]["thread_id"] == thread_id, "admin"
        created = client.post(
            "/threads", json={"thread_id": thread_id, "metadata": {"channel": "canary"}},
            headers=headers,
        )
        assert created.status_code == 200, "thread"
        reply = client.post(
            f"/threads/{thread_id}/runs/wait",
            json={"assistant_id": DEFAULT_AGENT_ID, "input": {
                "messages": [{"id": str(uuid4()), "type": "human", "content": "Olá"}]
            }},
            headers=headers,
        )
        if reply.status_code != 200:
            reason = reply.json().get("detail")
            allowed = {"assistant_not_found", "thread_not_found", "archived_error_thread",
                       "assistant_mismatch", "graph_mismatch", "thread_busy"}
            if reason not in allowed:
                reason = re.sub(r"[A-Za-z0-9_-]{20,}", "[redacted]", str(reason))[:140]
            raise AssertionError(f"run_status_{reply.status_code}:{reason}")
        messages = reply.json().get("messages") or []
        assert len(messages) >= 2 and messages[-1]["type"] == "ai", "reply"
        assert messages[-1].get("response_metadata", {}).get("finish_reason") == "stop", "finish"
        state = client.get(f"/threads/{thread_id}/state", headers=headers)
        assert state.status_code == 200 and len(state.json()["values"]["messages"]) == len(messages), "state"
        events = []
        with client.stream(
            "POST", f"/threads/{thread_id}/runs/stream",
            json={"assistant_id": DEFAULT_AGENT_ID, "input": {
                "messages": [{"id": str(uuid4()), "type": "human", "content": "Obrigado"}]
            }, "stream_mode": ["values"]},
            headers=headers,
        ) as stream:
            assert stream.status_code == 200, "stream_status"
            assert "text/event-stream" in stream.headers["content-type"], "stream_type"
            for line in stream.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        assert events and "__error__" not in events[-1], "stream_events"
        final_messages = events[-1].get("messages") or []
        assert len(final_messages) > len(messages) and final_messages[-1]["type"] == "ai", "stream_reply"
        resumed = client.get(f"/threads/{thread_id}/state", headers=headers)
        assert len(resumed.json()["values"]["messages"]) == len(final_messages), "stream_state"
    print({"archive": "ok", "search": "ok", "assistant_update": "ok", "delete": "ok", "admin": "ok", "admin_stream": "ok", "new_thread": "ok",
           "agent_run": "ok", "state": "ok", "stream": "ok", "resume": "ok"})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - only fixed assertion labels are printed
        code = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
        print(f"oss_canary_smoke_failed:{code}", file=sys.stderr)
        raise SystemExit(1) from None
