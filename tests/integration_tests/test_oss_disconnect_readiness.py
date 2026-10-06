"""Real HTTP disconnect and readiness checks with disposable PostgreSQL/Redis."""

import os
import socket
import threading
import time
from uuid import uuid4

import httpx
import psycopg
import pytest
import redis
import uvicorn


def test_disconnect_cancel_and_readiness(monkeypatch, tmp_path):
    database_url = os.getenv("OSS_REDIS_TEST_DATABASE_URL")
    redis_url = os.getenv("OSS_REDIS_TEST_URL")
    if not database_url or not redis_url:
        pytest.skip("set disposable OSS_REDIS_TEST_DATABASE_URL and OSS_REDIS_TEST_URL")

    for key, value in {
        "SESSION_BACKEND": "postgres",
        "SESSION_DATABASE_URL": database_url,
        "LANGGRAPH_STRICT_MSGPACK": "true",
        "OSS_RUNTIME_API_TOKEN": "synthetic-" + uuid4().hex,
        "OSS_RUNTIME_REDIS_ENABLED": "true",
        "OSS_RUNTIME_REDIS_URL": redis_url,
        "OSS_RUNTIME_REDIS_DB": "1",
    }.items():
        monkeypatch.setenv(key, value)
    for key, directory in {
        "OKF_DATA_ROOT": "okf",
        "SIMULATOR_ROOT": "simulator",
        "SESSION_ROOT": "sessions",
        "TOOL_REGISTRY_ROOT": "tools",
    }.items():
        monkeypatch.setenv(key, str(tmp_path / directory))

    from simple_agent import oss_runtime

    started = threading.Event()
    release = threading.Event()

    def slow_run(_assistant_id, _input_value, _thread_id, stream=False):
        assert stream
        started.set()
        yield {"messages": [{"type": "ai", "content": "FIRST"}]}
        assert release.wait(10)
        yield {"messages": [{"type": "ai", "content": "FINAL"}]}

    monkeypatch.setattr(oss_runtime, "_run", slow_run)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            oss_runtime.app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
        )
    )
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        client_options = {
            "base_url": f"http://127.0.0.1:{port}",
            "headers": {"X-Api-Key": os.environ["OSS_RUNTIME_API_TOKEN"]},
            "timeout": 15,
        }
        with httpx.Client(**client_options) as client:
            assert client.get("/info").status_code == 200
            with httpx.Client(**client_options) as stream_client:
                with stream_client.stream(
                    "POST",
                    f"/threads/{uuid4()}/runs/stream",
                    json={
                        "assistant_id": "synthetic",
                        "input": {},
                        "on_disconnect": "cancel",
                    },
                ) as response:
                    assert response.status_code == 200
                    run_id = response.headers["x-run-id"]
                    assert next(
                        line
                        for line in response.iter_lines()
                        if line.startswith("data: ")
                    )
            assert started.wait(2)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                row = client.get(f"/runs/{run_id}").json()
                if row["cancel_requested"]:
                    break
                time.sleep(0.1)
            assert row["cancel_requested"] is True
            release.set()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                row = client.get(f"/runs/{run_id}").json()
                if row["status"] == "cancelled":
                    break
                time.sleep(0.1)
            assert row["status"] == "cancelled"

            started.clear()
            release.clear()
            with httpx.Client(**client_options) as stream_client:
                with stream_client.stream(
                    "POST",
                    f"/threads/{uuid4()}/runs/stream",
                    json={"assistant_id": "synthetic", "input": {}},
                ) as response:
                    rejoin_id = response.headers["x-run-id"]
                    assert next(
                        line
                        for line in response.iter_lines()
                        if line.startswith("data: ")
                    )
            release.set()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                row = client.get(f"/runs/{rejoin_id}").json()
                if row["status"] == "succeeded":
                    break
                time.sleep(0.1)
            assert row["status"] == "succeeded"
            assert row["result"]["messages"][0]["content"] == "FINAL"

            original_db = oss_runtime._db

            def unavailable_db(**_kwargs):
                raise psycopg.OperationalError("synthetic outage")

            monkeypatch.setattr(oss_runtime, "_db", unavailable_db)
            assert client.get("/info").status_code == 503
            monkeypatch.setattr(oss_runtime, "_db", original_db)
            original_redis = oss_runtime._redis

            def unavailable_redis():
                raise redis.ConnectionError("synthetic outage")

            monkeypatch.setattr(oss_runtime, "_redis", unavailable_redis)
            assert client.get("/info").status_code == 503
            monkeypatch.setattr(oss_runtime, "_redis", original_redis)
            assert client.get("/info").status_code == 200
    finally:
        release.set()
        server.should_exit = True
        server_thread.join(timeout=5)
