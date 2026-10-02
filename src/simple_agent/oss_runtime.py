"""Small LangGraph SDK HTTP surface backed by OSS PostgreSQL checkpoints.

This is an isolated canary entrypoint. The existing ``langgraph dev`` command
does not import it, and no production traffic is routed here by default.
"""

from __future__ import annotations

import copy
import hmac
import json
import os
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from starlette.applications import Starlette
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


def _db():
    return psycopg.connect(
        os.environ["SESSION_DATABASE_URL"],
        autocommit=True,
        row_factory=dict_row,
        options="-c search_path=langgraph",
        connect_timeout=10,
    )


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (datetime, UUID)):
        return str(value)
    raise TypeError(type(value).__name__)


def _response(value, status=200):
    return JSONResponse(json.loads(json.dumps(value, default=_json)), status_code=status)


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
            "values": archived_error["state"], "next": [], "tasks": [],
            "metadata": {"legacy_status": "error"}, "created_at": None,
            "checkpoint": {"thread_id": thread_id}, "parent_checkpoint": None,
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
        PostgresSaver(db).setup()


async def info(_request):
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
    if any(key in body and not isinstance(body[key], dict) for key in ("context", "config", "metadata")):
        return _response({"detail": "invalid_request"}, 400)
    if any(key in body and not isinstance(body[key], str) for key in ("name", "description")):
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
            PostgresSaver(db).delete_thread(thread_id)
            db.execute("DELETE FROM langgraph.oss_threads WHERE thread_id=%s", (thread_id,))
            return True

    return Response(status_code=204) if await run_in_threadpool(remove) else _response(
        {"detail": "not_found_or_legacy"}, 404
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
    return _response(value) if value is not None else _response({"detail": "not_found"}, 404)


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
    return _response(value) if value is not None else _response({"detail": "not_found"}, 404)


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
                config = {**config, "configurable": {
                    **config.get("configurable", {}), "thread_id": thread_id
                }}
                db.execute(
                    """UPDATE langgraph.oss_threads SET
                       metadata=metadata || %s,updated_at=now()
                       WHERE thread_id=%s""",
                    (Jsonb({"assistant_id": assistant["assistant_id"], "graph_id": graph_id}), thread_id),
                )
            kwargs = {"context": assistant.get("context") or {}}
            if stream:
                yield from graph.stream(input_value, config, stream_mode="values", **kwargs)
            else:
                yield graph.invoke(input_value, config, **kwargs)
        finally:
            if thread_id:
                db.execute("SELECT pg_advisory_unlock(hashtext(%s))", (thread_id,))


async def run_wait(request):
    body = await request.json()
    thread_id = request.path_params.get("thread_id")

    def invoke():
        with closing(_run(body["assistant_id"], body.get("input") or {}, thread_id)) as run:
            return next(run)

    try:
        result = await run_in_threadpool(invoke)
    except KeyError:
        return _response({"detail": "invalid_request"}, 400)
    except ValueError as exc:
        reason = str(exc)
        known = {"assistant_not_found", "thread_not_found", "archived_error_thread",
                 "assistant_mismatch", "graph_mismatch", "thread_busy"}
        return _response({"detail": reason if reason in known else "run_failed"},
                         409 if reason in known else 500)
    return _response(result)


async def run_stream(request):
    body = await request.json()
    thread_id = request.path_params.get("thread_id")
    if not body.get("assistant_id") or not isinstance(body.get("input"), dict):
        return _response({"detail": "invalid_request"}, 400)

    def events():
        try:
            for value in _run(body["assistant_id"], body["input"], thread_id, stream=True):
                yield "event: values\ndata: " + json.dumps(value, default=_json) + "\n\n"
        except Exception:  # noqa: BLE001 - never leak conversation or provider details
            yield 'event: error\ndata: {"error":"run_failed"}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream")


async def auth(request, call_next):
    if request.url.path != "/info" and not _authorized(request):
        return _response({"detail": "unauthorized"}, 401)
    return await call_next(request)


@asynccontextmanager
async def lifespan(_app):
    _setup()
    yield


app = Starlette(
    lifespan=lifespan,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=[origin for origin in os.getenv("OSS_RUNTIME_CORS_ORIGINS", "").split(",") if origin],
            allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
            allow_headers=["X-Api-Key", "Content-Type"],
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
    ],
)
