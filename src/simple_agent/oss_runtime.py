"""Small LangGraph SDK HTTP surface backed by OSS PostgreSQL checkpoints.

This is an isolated canary entrypoint. The existing ``langgraph dev`` command
does not import it, and no production traffic is routed here by default.
"""

from __future__ import annotations

import asyncio
import copy
import hmac
import json
import os
import threading
import time
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

import psycopg
import redis
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from simple_agent.admin_graph_v2 import graph as admin_graph
from simple_agent.managed_graph import graph as agent_graph
from simple_agent.raw_compiler_graph import graph as raw_graph

GRAPHS = {"agent": agent_graph, "okf_admin": admin_graph, "raw_compiler": raw_graph}
_RUN_KEY = "oss-runtime:v1"
_RUN_LEASE_SECONDS = 30
_run_worker_stop = threading.Event()
_run_worker = None


def _redis_enabled():
    return os.getenv("OSS_RUNTIME_REDIS_ENABLED") == "true"


def _redis():
    url = os.environ["OSS_RUNTIME_REDIS_URL"]
    parsed = urlsplit(url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise ValueError("invalid_redis_url")
    database = int(os.getenv("OSS_RUNTIME_REDIS_DB", "1"))
    if not 0 <= database <= 15:
        raise ValueError("invalid_redis_database")
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parsed.query) if key != "db"]
    )
    isolated_url = urlunsplit(parsed._replace(path=f"/{database}", query=query))
    return redis.Redis.from_url(
        isolated_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
    )


def _db(connect_timeout=10):
    return psycopg.connect(
        os.environ["SESSION_DATABASE_URL"],
        autocommit=True,
        row_factory=dict_row,
        options="-c search_path=langgraph",
        connect_timeout=connect_timeout,
    )


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (datetime, UUID)):
        return str(value)
    raise TypeError(type(value).__name__)


def _response(value, status=200):
    return JSONResponse(
        json.loads(json.dumps(value, default=_json)), status_code=status
    )


def _authorized(request: Request) -> bool:
    token = os.getenv("OSS_RUNTIME_API_TOKEN", "")
    supplied = request.headers.get("x-api-key", "")
    return len(token) >= 32 and hmac.compare_digest(token, supplied)


def _assistant(db, assistant_id):
    if assistant_id in GRAPHS:
        row = db.execute(
            """SELECT record FROM langgraph.legacy_assistants
               WHERE graph_id=%s ORDER BY (record->>'version')::integer DESC LIMIT 1""",
            (assistant_id,),
        ).fetchone()
    else:
        try:
            UUID(assistant_id)
        except ValueError:
            return None
        row = db.execute(
            "SELECT record FROM langgraph.legacy_assistants WHERE assistant_id=%s",
            (assistant_id,),
        ).fetchone()
    return row["record"] if row else None


def _thread(db, thread_id):
    row = db.execute(
        """SELECT thread_id,metadata,status,created_at,updated_at
           FROM langgraph.oss_threads WHERE thread_id=%s""",
        (thread_id,),
    ).fetchone()
    if row:
        return row
    return db.execute(
        """SELECT thread_id,metadata,status,created_at,updated_at
           FROM langgraph.legacy_thread_state WHERE thread_id=%s""",
        (thread_id,),
    ).fetchone()


def _state(db, thread_id):
    archived_error = db.execute(
        "SELECT state FROM langgraph.legacy_thread_state WHERE thread_id=%s AND status='error'",
        (thread_id,),
    ).fetchone()
    if archived_error:
        return {
            "values": archived_error["state"],
            "next": [],
            "tasks": [],
            "metadata": {"legacy_status": "error"},
            "created_at": None,
            "checkpoint": {"thread_id": thread_id},
            "parent_checkpoint": None,
        }
    graph = copy.copy(agent_graph)
    graph.checkpointer = PostgresSaver(db)
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    return {
        "values": snapshot.values,
        "next": list(snapshot.next),
        "tasks": list(snapshot.tasks),
        "metadata": snapshot.metadata,
        "created_at": snapshot.created_at,
        "checkpoint": snapshot.config.get("configurable", {}),
        "parent_checkpoint": (snapshot.parent_config or {}).get("configurable"),
    }


def _setup():
    if os.getenv("SESSION_BACKEND") != "postgres":
        raise RuntimeError("postgres_backend_required")
    if len(os.getenv("OSS_RUNTIME_API_TOKEN", "")) < 32:
        raise RuntimeError("oss_runtime_token_required")
    if os.getenv("LANGGRAPH_STRICT_MSGPACK") != "true":
        raise RuntimeError("strict_serialization_required")
    with _db() as db:
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
        db.execute(
            """CREATE TABLE IF NOT EXISTS langgraph.oss_threads (
                thread_id uuid PRIMARY KEY,
                metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
                status text NOT NULL DEFAULT 'idle',
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS langgraph.oss_runs (
                run_id uuid PRIMARY KEY,
                thread_id uuid,
                assistant_id text NOT NULL,
                input jsonb NOT NULL,
                status text NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
                result jsonb,
                cancel_requested boolean NOT NULL DEFAULT false,
                lease_expires_at timestamptz,
                error_code text,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            )"""
        )
        db.execute(
            "ALTER TABLE langgraph.oss_runs ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz"
        )
        db.execute(
            "ALTER TABLE langgraph.oss_runs ADD COLUMN IF NOT EXISTS error_code text"
        )
        db.execute(
            """CREATE INDEX IF NOT EXISTS oss_runs_queued_idx
               ON langgraph.oss_runs(created_at) WHERE status='queued'"""
        )
        db.execute(
            """CREATE INDEX IF NOT EXISTS oss_runs_running_lease_idx
               ON langgraph.oss_runs(lease_expires_at) WHERE status='running'"""
        )
        PostgresSaver(db).setup()


async def info(_request):
    if _redis_enabled() and (_run_worker is None or not _run_worker.is_alive()):
        return _response({"detail": "worker_unavailable"}, 503)

    def ready():
        with _db(connect_timeout=2) as db:
            db.execute("SELECT 1")
        if _redis_enabled():
            client = _redis()
            try:
                client.ping()
            finally:
                client.close()

    try:
        await run_in_threadpool(ready)
    except (psycopg.Error, redis.RedisError, OSError):
        return _response({"detail": "dependency_unavailable"}, 503)
    return _response({"graphs": list(GRAPHS), "version": "oss-canary"})


async def assistant_get(request):
    with _db() as db:
        record = _assistant(db, request.path_params["assistant_id"])
    return _response(record) if record else _response({"detail": "not_found"}, 404)


async def assistant_update(request):
    body = await request.json()
    allowed = {"context", "config", "metadata", "name", "description"}
    if not isinstance(body, dict) or any(key not in allowed for key in body):
        return _response({"detail": "invalid_request"}, 400)
    if any(
        key in body and not isinstance(body[key], dict)
        for key in ("context", "config", "metadata")
    ):
        return _response({"detail": "invalid_request"}, 400)
    if any(
        key in body and not isinstance(body[key], str)
        for key in ("name", "description")
    ):
        return _response({"detail": "invalid_request"}, 400)
    assistant_id = request.path_params["assistant_id"]
    with _db() as db, db.transaction():
        row = db.execute(
            "SELECT record FROM langgraph.legacy_assistants WHERE assistant_id=%s FOR UPDATE",
            (assistant_id,),
        ).fetchone()
        if not row:
            return _response({"detail": "not_found"}, 404)
        record = row["record"]
        record.update(body)
        record["version"] += 1
        record["updated_at"] = datetime.now(UTC).isoformat()
        db.execute(
            "UPDATE langgraph.legacy_assistants SET record=%s WHERE assistant_id=%s",
            (Jsonb(record), assistant_id),
        )
    return _response(record)


async def assistant_search(request):
    body = await request.json()
    limit = min(max(int(body.get("limit", 20)), 1), 100)
    offset = max(int(body.get("offset", 0)), 0)
    with _db() as db:
        rows = db.execute(
            """SELECT record FROM langgraph.legacy_assistants
               WHERE (%s::text IS NULL OR graph_id=%s)
               ORDER BY (record->>'updated_at') DESC LIMIT %s OFFSET %s""",
            (body.get("graph_id"), body.get("graph_id"), limit, offset),
        ).fetchall()
    return _response([row["record"] for row in rows])


async def thread_create(request):
    body = await request.json()
    try:
        thread_id = str(UUID(body.get("thread_id") or str(uuid4())))
    except ValueError:
        return _response({"detail": "invalid_thread_id"}, 400)
    metadata = body.get("metadata") or {}
    if not isinstance(metadata, dict):
        return _response({"detail": "invalid_metadata"}, 400)
    with _db() as db:
        existing = _thread(db, thread_id)
        if existing:
            if body.get("if_exists") == "do_nothing":
                return _response(existing)
            return _response({"detail": "thread_exists"}, 409)
        row = db.execute(
            """INSERT INTO langgraph.oss_threads (thread_id,metadata)
               VALUES (%s,%s) RETURNING thread_id,metadata,status,created_at,updated_at""",
            (thread_id, Jsonb(metadata)),
        ).fetchone()
    return _response(row)


async def thread_get(request):
    with _db() as db:
        row = _thread(db, request.path_params["thread_id"])
    return _response(row) if row else _response({"detail": "not_found"}, 404)


async def thread_delete(request):
    thread_id = request.path_params["thread_id"]

    def remove():
        with _db() as db:
            row = db.execute(
                "SELECT 1 FROM langgraph.oss_threads WHERE thread_id=%s", (thread_id,)
            ).fetchone()
            if not row:
                return False
            if (
                _redis_enabled()
                and db.execute(
                    """SELECT 1 FROM langgraph.oss_runs
                   WHERE thread_id=%s AND status IN ('queued','running') LIMIT 1""",
                    (thread_id,),
                ).fetchone()
            ):
                return "busy"
            PostgresSaver(db).delete_thread(thread_id)
            db.execute(
                "DELETE FROM langgraph.oss_threads WHERE thread_id=%s", (thread_id,)
            )
            return True

    result = await run_in_threadpool(remove)
    if result == "busy":
        return _response({"detail": "thread_busy"}, 409)
    return (
        Response(status_code=204)
        if result
        else _response({"detail": "not_found_or_legacy"}, 404)
    )


async def thread_search(request):
    body = await request.json()
    metadata = body.get("metadata") or {}
    if not isinstance(metadata, dict):
        return _response({"detail": "invalid_metadata"}, 400)
    limit = min(max(int(body.get("limit", 20)), 1), 1000)
    offset = max(int(body.get("offset", 0)), 0)
    with _db() as db:
        rows = db.execute(
            """SELECT thread_id::text,metadata,status,created_at,updated_at,
                      NULL::jsonb AS values
                 FROM langgraph.oss_threads WHERE metadata @> %s
               UNION ALL
               SELECT thread_id,metadata,status,created_at,updated_at,state AS values
                 FROM langgraph.legacy_thread_state WHERE metadata @> %s
               ORDER BY updated_at DESC LIMIT %s OFFSET %s""",
            (Jsonb(metadata), Jsonb(metadata), limit, offset),
        ).fetchall()
        for row in rows:
            if row["values"] is None:
                row["values"] = _state(db, str(row["thread_id"]))["values"]
    return _response(rows)


async def thread_state(request):
    def read():
        with _db() as db:
            if not _thread(db, request.path_params["thread_id"]):
                return None
            return _state(db, request.path_params["thread_id"])

    value = await run_in_threadpool(read)
    return (
        _response(value)
        if value is not None
        else _response({"detail": "not_found"}, 404)
    )


async def thread_history(request):
    body = await request.json()

    def read():
        with _db() as db:
            if not _thread(db, request.path_params["thread_id"]):
                return None
            error = db.execute(
                "SELECT 1 FROM langgraph.legacy_thread_state WHERE thread_id=%s AND status='error'",
                (request.path_params["thread_id"],),
            ).fetchone()
            if error:
                return [_state(db, request.path_params["thread_id"])]
            graph = copy.copy(agent_graph)
            graph.checkpointer = PostgresSaver(db)
            limit = min(max(int(body.get("limit", 10)), 1), 100)
            return [
                {
                    "values": item.values,
                    "next": list(item.next),
                    "tasks": list(item.tasks),
                    "metadata": item.metadata,
                    "created_at": item.created_at,
                    "checkpoint": item.config.get("configurable", {}),
                    "parent_checkpoint": (item.parent_config or {}).get("configurable"),
                }
                for item in graph.get_state_history(
                    {"configurable": {"thread_id": request.path_params["thread_id"]}},
                    limit=limit,
                )
            ]

    value = await run_in_threadpool(read)
    return (
        _response(value)
        if value is not None
        else _response({"detail": "not_found"}, 404)
    )


def _run(assistant_id, input_value, thread_id=None, stream=False):
    with _db() as db:
        assistant = _assistant(db, assistant_id)
        if not assistant:
            raise ValueError("assistant_not_found")
        graph_id = assistant["graph_id"]
        if thread_id:
            thread = _thread(db, thread_id)
            if not thread:
                raise ValueError("thread_not_found")
            if thread["status"] == "error":
                raise ValueError("archived_error_thread")
            prior = thread["metadata"]
            if prior.get("assistant_id") not in (None, assistant["assistant_id"]):
                raise ValueError("assistant_mismatch")
            if prior.get("graph_id") not in (None, graph_id):
                raise ValueError("graph_mismatch")
            if not db.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s)) AS locked", (thread_id,)
            ).fetchone()["locked"]:
                raise ValueError("thread_busy")
        try:
            graph = copy.copy(GRAPHS[graph_id])
            config = assistant.get("config") or {}
            if thread_id:
                graph.checkpointer = PostgresSaver(db)
                config = {
                    **config,
                    "configurable": {
                        **config.get("configurable", {}),
                        "thread_id": thread_id,
                    },
                }
                db.execute(
                    """UPDATE langgraph.oss_threads SET
                       metadata=metadata || %s,updated_at=now()
                       WHERE thread_id=%s""",
                    (
                        Jsonb(
                            {
                                "assistant_id": assistant["assistant_id"],
                                "graph_id": graph_id,
                            }
                        ),
                        thread_id,
                    ),
                )
            kwargs = {"context": assistant.get("context") or {}}
            if stream:
                yield from graph.stream(
                    input_value, config, stream_mode="values", **kwargs
                )
            else:
                yield graph.invoke(input_value, config, **kwargs)
        finally:
            if thread_id:
                db.execute("SELECT pg_advisory_unlock(hashtext(%s))", (thread_id,))


def _run_channel(run_id):
    return f"{_RUN_KEY}:events:{run_id}"


def _enqueue_run(run_id, assistant_id, input_value, thread_id, client):
    with _db() as db:
        db.execute(
            """INSERT INTO langgraph.oss_runs(run_id,thread_id,assistant_id,input)
               VALUES (%s,%s,%s,%s)""",
            (run_id, thread_id, assistant_id, Jsonb(input_value)),
        )
    # The queue contains only wake-up signals. PostgreSQL owns the run input.
    try:
        client.lpush(f"{_RUN_KEY}:wake", "1")
    except redis.RedisError:
        pass  # The worker also polls PostgreSQL after a bounded timeout.
    return run_id


def _run_row(run_id):
    with _db() as db:
        return db.execute(
            """SELECT run_id::text,status,result,cancel_requested,error_code
               FROM langgraph.oss_runs WHERE run_id=%s""",
            (run_id,),
        ).fetchone()


def _expire_runs():
    # A lost worker may have completed an external action. Fail the run; never replay it.
    with _db() as db:
        return db.execute(
            """UPDATE langgraph.oss_runs
               SET status='failed',error_code='worker_lost',updated_at=now()
               WHERE status='running'
                 AND (lease_expires_at IS NULL OR lease_expires_at <= now())
               RETURNING run_id::text"""
        ).fetchall()


def _claim_run():
    with _db() as db, db.transaction():
        row = db.execute(
            """SELECT run_id::text,thread_id::text,assistant_id,input
               FROM langgraph.oss_runs WHERE status='queued'
               ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"""
        ).fetchone()
        if row:
            db.execute(
                """UPDATE langgraph.oss_runs
                   SET status='running',lease_expires_at=now() + %s * interval '1 second',
                       updated_at=now()
                   WHERE run_id=%s""",
                (_RUN_LEASE_SECONDS, row["run_id"]),
            )
        return row


def _lease_heartbeat(stop, run_id):
    while not stop.wait(5):
        try:
            with _db() as db:
                renewed = db.execute(
                    """UPDATE langgraph.oss_runs
                       SET lease_expires_at=now() + %s * interval '1 second'
                       WHERE run_id=%s AND status='running'
                         AND lease_expires_at > now()
                       RETURNING 1""",
                    (_RUN_LEASE_SECONDS, run_id),
                ).fetchone()
            if not renewed:
                return
        except psycopg.Error:
            pass  # A transient database error can recover before the lease expires.


def _publish(client, run_id, kind, value=None):
    try:
        client.publish(
            _run_channel(run_id),
            json.dumps({"kind": kind, "value": value}, default=_json),
        )
    except redis.RedisError:
        pass  # Final state remains queryable in PostgreSQL.


def _execute_queued_run(row, client):
    run_id = row["run_id"]
    result = None
    stored_result = None
    status = "succeeded"
    heartbeat_stop = threading.Event()
    heartbeat = threading.Thread(
        target=_lease_heartbeat, args=(heartbeat_stop, run_id), daemon=True
    )
    heartbeat.start()
    try:
        if _run_row(run_id)["cancel_requested"]:
            status = "cancelled"
        else:
            with closing(
                _run(row["assistant_id"], row["input"], row["thread_id"], stream=True)
            ) as execution:
                for result in execution:
                    _publish(client, run_id, "values", result)
                    with _db() as db:
                        current = db.execute(
                            """SELECT cancel_requested,status,lease_expires_at > now() AS lease_valid
                               FROM langgraph.oss_runs WHERE run_id=%s""",
                            (run_id,),
                        ).fetchone()
                    if (
                        current["cancel_requested"]
                        or current["status"] != "running"
                        or not current["lease_valid"]
                    ):
                        status = (
                            "cancelled" if current["cancel_requested"] else "failed"
                        )
                        break
            if status == "succeeded":
                stored_result = json.loads(json.dumps(result, default=_json))
    except Exception:  # noqa: BLE001 - provider and conversation data stay out of logs
        status = "failed"
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=2)
        with _db() as db, db.transaction():
            final = db.execute(
                "SELECT status,cancel_requested FROM langgraph.oss_runs WHERE run_id=%s FOR UPDATE",
                (run_id,),
            ).fetchone()
            if final["status"] == "running":
                if final["cancel_requested"] and status == "succeeded":
                    status = "cancelled"
                db.execute(
                    """UPDATE langgraph.oss_runs
                       SET status=%s,result=%s,lease_expires_at=NULL,updated_at=now()
                       WHERE run_id=%s""",
                    (
                        status,
                        Jsonb(stored_result) if status == "succeeded" else None,
                        run_id,
                    ),
                )
            else:
                status = final["status"]
    _publish(client, run_id, status)


def _worker_loop(stop, client):
    try:
        while not stop.is_set():
            try:
                client.brpop(f"{_RUN_KEY}:wake", timeout=1)
            except redis.RedisError:
                stop.wait(1)
            try:
                for expired in _expire_runs():
                    _publish(client, expired["run_id"], "failed")
                while row := _claim_run():
                    _execute_queued_run(row, client)
            except psycopg.Error:
                stop.wait(1)
    finally:
        client.close()


def _cancel_run(run_id, client):
    with _db() as db:
        row = db.execute(
            """UPDATE langgraph.oss_runs SET cancel_requested=true,
                      status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,
                      updated_at=now()
               WHERE run_id=%s AND status IN ('queued','running')
               RETURNING status""",
            (run_id,),
        ).fetchone()
    if row:
        _publish(client, run_id, "cancel_requested")
    return row


async def run_wait(request):
    body = await request.json()
    thread_id = request.path_params.get("thread_id")

    if _redis_enabled():
        if not body.get("assistant_id") or not isinstance(body.get("input"), dict):
            return _response({"detail": "invalid_request"}, 400)

        def wait_for_run():
            client = _redis()
            try:
                run_id = str(uuid4())
                _enqueue_run(
                    run_id, body["assistant_id"], body["input"], thread_id, client
                )
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    row = _run_row(run_id)
                    if row["status"] in {"succeeded", "failed", "cancelled"}:
                        return run_id, row
                    time.sleep(0.25)
                return run_id, None
            finally:
                client.close()

        run_id, row = await run_in_threadpool(wait_for_run)
        if row is None:
            return _response({"detail": "run_timeout", "run_id": run_id}, 504)
        if row["status"] != "succeeded":
            return _response({"detail": "run_" + row["status"], "run_id": run_id}, 409)
        return _response(row["result"])

    def invoke():
        with closing(
            _run(body["assistant_id"], body.get("input") or {}, thread_id)
        ) as run:
            return next(run)

    try:
        result = await run_in_threadpool(invoke)
    except KeyError:
        return _response({"detail": "invalid_request"}, 400)
    except ValueError as exc:
        reason = str(exc)
        known = {
            "assistant_not_found",
            "thread_not_found",
            "archived_error_thread",
            "assistant_mismatch",
            "graph_mismatch",
            "thread_busy",
        }
        return _response(
            {"detail": reason if reason in known else "run_failed"},
            409 if reason in known else 500,
        )
    return _response(result)


async def run_stream(request):
    body = await request.json()
    thread_id = request.path_params.get("thread_id")
    if not body.get("assistant_id") or not isinstance(body.get("input"), dict):
        return _response({"detail": "invalid_request"}, 400)

    if _redis_enabled():
        client = _redis()
        run_id = str(uuid4())
        pubsub = client.pubsub()
        try:
            await run_in_threadpool(pubsub.subscribe, _run_channel(run_id))
            await run_in_threadpool(
                pubsub.get_message, ignore_subscribe_messages=True, timeout=1
            )
            await run_in_threadpool(
                _enqueue_run,
                run_id,
                body["assistant_id"],
                body["input"],
                thread_id,
                client,
            )
        except Exception:
            pubsub.close()
            client.close()
            return _response({"detail": "run_unavailable"}, 503)

        finished = False

        async def events_from_redis():
            nonlocal finished
            last_value = None
            pubsub_healthy = True
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                message = None
                if pubsub_healthy:
                    try:
                        message = await run_in_threadpool(
                            pubsub.get_message,
                            ignore_subscribe_messages=True,
                            timeout=0.5,
                        )
                    except redis.RedisError:
                        pubsub_healthy = False
                if message and message["type"] == "message":
                    event = json.loads(message["data"])
                    if event["kind"] == "values":
                        last_value = event["value"]
                        yield "event: values\ndata: " + json.dumps(last_value) + "\n\n"
                row = await run_in_threadpool(_run_row, run_id)
                if row["status"] in {"succeeded", "failed", "cancelled"}:
                    finished = True
                    if row["status"] == "succeeded" and row["result"] != last_value:
                        yield (
                            "event: values\ndata: " + json.dumps(row["result"]) + "\n\n"
                        )
                    elif row["status"] != "succeeded":
                        yield 'event: error\ndata: {"error":"run_failed"}\n\n'
                    return
                if not pubsub_healthy:
                    await asyncio.sleep(0.5)
            yield 'event: error\ndata: {"error":"run_timeout"}\n\n'

        def after_stream():
            try:
                if body.get("on_disconnect") == "cancel" and not finished:
                    _cancel_run(run_id, client)
            finally:
                pubsub.close()
                client.close()

        return StreamingResponse(
            events_from_redis(),
            media_type="text/event-stream",
            headers={"X-Run-Id": run_id},
            background=BackgroundTask(after_stream),
        )

    def events():
        try:
            for value in _run(
                body["assistant_id"], body["input"], thread_id, stream=True
            ):
                yield (
                    "event: values\ndata: " + json.dumps(value, default=_json) + "\n\n"
                )
        except Exception:  # noqa: BLE001 - never leak conversation or provider details
            yield 'event: error\ndata: {"error":"run_failed"}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream")


async def run_status(request):
    try:
        run_id = str(UUID(request.path_params["run_id"]))
    except ValueError:
        return _response({"detail": "invalid_run_id"}, 400)
    row = await run_in_threadpool(_run_row, run_id)
    return _response(row) if row else _response({"detail": "not_found"}, 404)


async def run_cancel(request):
    if not _redis_enabled():
        return _response({"detail": "not_available"}, 404)
    try:
        run_id = str(UUID(request.path_params["run_id"]))
    except ValueError:
        return _response({"detail": "invalid_run_id"}, 400)
    client = _redis()
    try:
        row = await run_in_threadpool(_cancel_run, run_id, client)
    finally:
        client.close()
    return (
        _response({"run_id": run_id, "status": row["status"]})
        if row
        else _response({"detail": "not_found_or_finished"}, 404)
    )


async def auth(request, call_next):
    if request.url.path != "/info" and not _authorized(request):
        return _response({"detail": "unauthorized"}, 401)
    return await call_next(request)


@asynccontextmanager
async def lifespan(_app):
    global _run_worker
    _setup()
    if _redis_enabled():
        client = _redis()
        client.ping()
        client.close()
        _run_worker_stop.clear()
        _run_worker = threading.Thread(
            target=_worker_loop,
            args=(_run_worker_stop, _redis()),
            daemon=True,
            name="oss-run-worker",
        )
        _run_worker.start()
    try:
        yield
    finally:
        if _run_worker is not None:
            _run_worker_stop.set()
            _run_worker.join(timeout=3)
            _run_worker = None


app = Starlette(
    lifespan=lifespan,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=[
                origin
                for origin in os.getenv("OSS_RUNTIME_CORS_ORIGINS", "").split(",")
                if origin
            ],
            allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
            allow_headers=["X-Api-Key", "Content-Type"],
            expose_headers=["X-Run-Id"],
        ),
        Middleware(BaseHTTPMiddleware, dispatch=auth),
    ],
    routes=[
        Route("/info", info),
        Route("/assistants/search", assistant_search, methods=["POST"]),
        Route("/assistants/{assistant_id}", assistant_get),
        Route("/assistants/{assistant_id}", assistant_update, methods=["PATCH"]),
        Route("/threads", thread_create, methods=["POST"]),
        Route("/threads/search", thread_search, methods=["POST"]),
        Route("/threads/{thread_id}", thread_get),
        Route("/threads/{thread_id}", thread_delete, methods=["DELETE"]),
        Route("/threads/{thread_id}/state", thread_state),
        Route("/threads/{thread_id}/history", thread_history, methods=["POST"]),
        Route("/runs/wait", run_wait, methods=["POST"]),
        Route("/threads/{thread_id}/runs/wait", run_wait, methods=["POST"]),
        Route("/threads/{thread_id}/runs/stream", run_stream, methods=["POST"]),
        Route("/runs/{run_id}", run_status),
        Route("/runs/{run_id}/cancel", run_cancel, methods=["POST"]),
        Route(
            "/threads/{thread_id}/runs/{run_id}/cancel", run_cancel, methods=["POST"]
        ),
    ],
)
