"""Queue ownership, FIFO and crash recovery against disposable Postgres and Redis."""

import os
import subprocess
import sys
import time
from uuid import uuid4

import pytest


def test_expired_owner_keeps_turn_and_a_lost_action_is_never_replayed(monkeypatch):
    dsn = os.getenv("OSS_REDIS_TEST_DATABASE_URL")
    redis_url = os.getenv("OSS_REDIS_TEST_URL")
    if not dsn or not redis_url:
        pytest.skip("requires disposable PostgreSQL and Redis")
    for key, value in {
        "SESSION_BACKEND": "postgres",
        "SESSION_DATABASE_URL": dsn,
        "OSS_RUNTIME_REDIS_URL": redis_url,
        "LANGGRAPH_STRICT_MSGPACK": "true",
        "OSS_RUNTIME_API_TOKEN": uuid4().hex,
    }.items():
        monkeypatch.setenv(key, value)
    from simple_agent import oss_runtime as runtime

    runtime._setup()
    aurora, other = str(uuid4()), str(uuid4())
    thread = str(uuid4())
    first, second, independent, other_run = [str(uuid4()) for _ in range(4)]
    with runtime._redis() as redis:
        runtime._enqueue_run(first, aurora, {}, thread, redis)
        runtime._enqueue_run(second, aurora, {}, thread, redis)
        runtime._enqueue_run(independent, aurora, {}, str(uuid4()), redis)
        runtime._enqueue_run(other_run, other, {}, str(uuid4()), redis)

    # A durable recorder stands in for a provider that accepted a side effect before a crash.
    with runtime._db() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS public.lab_action_receipts(run_id uuid, action text)"
        )
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
import sys,time
from simple_agent import oss_runtime as runtime
with runtime._dedicated_db() as db:
    row = runtime._claim_run(db, [sys.argv[1]])
    assert row["run_id"] == sys.argv[2]
    db.execute("INSERT INTO public.lab_action_receipts SELECT %s::uuid, unnest(%s::text[])",
               (row["run_id"], ["proposal", "payment", "email"]))
    time.sleep(60)
""",
            aurora,
            first,
        ]
    )
    try:
        with runtime._dedicated_db() as monitor:
            deadline = time.monotonic() + 20
            while not monitor.execute(
                "SELECT 1 FROM public.lab_action_receipts WHERE run_id=%s", (first,)
            ).fetchone():
                assert child.poll() is None and time.monotonic() < deadline
                time.sleep(0.05)
            monitor.execute(
                "UPDATE langgraph.oss_runs SET lease_expires_at=now()-interval '1 minute' WHERE run_id=%s",
                (first,),
            )
            assert first not in {row["run_id"] for row in runtime._expire_runs()}
            assert runtime._run_row(first)["status"] == "running"
            assert runtime._claim_run(monitor, [aurora])["run_id"] == independent
            assert runtime._claim_run(monitor, [aurora]) is None
            assert runtime._run_row(other_run)["status"] == "queued"

            child.kill()
            child.wait(timeout=10)
            deadline = time.monotonic() + 5
            while runtime._run_row(first)["status"] == "running":
                runtime._expire_runs()
                assert time.monotonic() < deadline
            assert runtime._run_row(first)["error_code"] == "worker_lost"
            assert runtime._claim_run(monitor, [aurora])["run_id"] == second
            assert runtime._claim_run(monitor, [aurora]) is None
            assert runtime._claim_run(monitor, [other])["run_id"] == other_run
            rows = monitor.execute(
                "SELECT action,count(*) n FROM public.lab_action_receipts WHERE run_id=%s GROUP BY action",
                (first,),
            ).fetchall()
            assert {r["action"]: r["n"] for r in rows} == {
                "proposal": 1,
                "payment": 1,
                "email": 1,
            }
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        with runtime._db() as db:
            db.execute(
                "DELETE FROM public.lab_action_receipts WHERE run_id=%s", (first,)
            )
            db.execute(
                "DELETE FROM langgraph.oss_runs WHERE assistant_id=ANY(%s)",
                ([aurora, other],),
            )
