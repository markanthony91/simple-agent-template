"""Opt-in check against disposable PostgreSQL and Redis instances."""

import os
import threading
from uuid import uuid4

import pytest
import redis
from starlette.testclient import TestClient


def test_redis_worker_and_stream(monkeypatch, tmp_path):
    database_url = os.getenv("OSS_REDIS_TEST_DATABASE_URL")
    redis_url = os.getenv("OSS_REDIS_TEST_URL")
    if not database_url or not redis_url:
        pytest.skip("set disposable OSS_REDIS_TEST_DATABASE_URL and OSS_REDIS_TEST_URL")

    monkeypatch.setenv("SESSION_BACKEND", "postgres")
    monkeypatch.setenv("SESSION_DATABASE_URL", database_url)
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    monkeypatch.setenv("OSS_RUNTIME_API_TOKEN", "synthetic-" + uuid4().hex)
    monkeypatch.setenv("OSS_RUNTIME_REDIS_ENABLED", "true")
    monkeypatch.setenv("OSS_RUNTIME_REDIS_URL", redis_url)
    monkeypatch.setenv("OSS_RUNTIME_REDIS_DB", "1")
    monkeypatch.setenv("OKF_DATA_ROOT", str(tmp_path / "okf"))
    monkeypatch.setenv("SIMULATOR_ROOT", str(tmp_path / "simulator"))
    monkeypatch.setenv("SESSION_ROOT", str(tmp_path / "sessions"))
    monkeypatch.setenv("TOOL_REGISTRY_ROOT", str(tmp_path / "tools"))

    from simple_agent import oss_runtime

    def fake_run(_assistant_id, input_value, _thread_id, stream=False):
        assert stream
        yield {"messages": [{"type": "ai", "content": input_value["message"]}]}

    monkeypatch.setattr(oss_runtime, "_run", fake_run)
    headers = {"X-Api-Key": os.environ["OSS_RUNTIME_API_TOKEN"]}
    with TestClient(oss_runtime.app) as client:
        response = client.post(
            "/runs/wait",
            json={"assistant_id": "synthetic", "input": {"message": "espera"}},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["messages"][0]["content"] == "espera"

        events = []
        with client.stream(
            "POST",
            "/threads/" + str(uuid4()) + "/runs/stream",
            json={"assistant_id": "synthetic", "input": {"message": "stream"}},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            run_id = response.headers["x-run-id"]
            events = [
                line for line in response.iter_lines() if line.startswith("data: ")
            ]
        assert any("stream" in event for event in events)
        status = client.get(f"/runs/{run_id}", headers=headers)
        assert status.status_code == 200
        assert status.json()["status"] == "succeeded"

        started = threading.Event()
        release = threading.Event()

        def slow_run(_assistant_id, _input_value, _thread_id, stream=False):
            assert stream
            started.set()
            assert release.wait(5)
            yield {"messages": [{"type": "ai", "content": "cancelar"}]}

        monkeypatch.setattr(oss_runtime, "_run", slow_run)
        cancelled_result = {}

        def submit_wait():
            cancelled_result["response"] = client.post(
                "/runs/wait",
                json={"assistant_id": "synthetic", "input": {"message": "cancelar"}},
                headers=headers,
            )

        submitter = threading.Thread(target=submit_wait)
        submitter.start()
        try:
            assert started.wait(5)
            with oss_runtime._db() as db:
                pending = db.execute(
                    """SELECT run_id::text FROM langgraph.oss_runs
                       WHERE status='running' ORDER BY created_at DESC LIMIT 1"""
                ).fetchone()
            assert pending
            cancellation = client.post(
                f"/runs/{pending['run_id']}/cancel", headers=headers
            )
            assert cancellation.status_code == 200
        finally:
            release.set()
            submitter.join(timeout=5)
        assert cancelled_result["response"].status_code == 409
        assert (
            client.get(f"/runs/{pending['run_id']}", headers=headers).json()["status"]
            == "cancelled"
        )

    # The integration uses database 1 and never writes the login/OTP database 0.
    default_database = redis.Redis.from_url(redis_url)
    assert default_database.dbsize() == 0
