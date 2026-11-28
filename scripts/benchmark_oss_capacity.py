"""Loopback-only load test of the OSS graph, SQL queue, checkpoints and SSE.

With initdb, postgres and redis-server on PATH, run with the project Python:
  python scripts/benchmark_oss_capacity.py --output /tmp/oss-capacity.json

Outputs measured percentiles in seconds and returns nonzero on incorrect replies,
missing DB results or errors. The harness creates fresh local services and uses
a deterministic OpenAI-compatible stream. No external endpoint is configurable.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import AsyncExitStack, ExitStack, closing, contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from itertools import accumulate
import math
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[1]
MARKERS = ("scope-lab-A", "scope-lab-B")


class Model(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = [m["content"] for m in body["messages"] if m["role"] == "user"]
        system = " ".join(
            m["content"] for m in body["messages"] if m["role"] == "system"
        )
        scopes = [marker for marker in MARKERS if marker in system]
        tag = user[-1]
        if not (len(scopes) == 1 and re.fullmatch(r"[a-f0-9]{32}-[12]", tag)):
            self.send_error(400)
            return
        # Check that every previous turn received by the provider belongs to this thread.
        self.server.calls[tag] += 1
        scope = scopes[0] if all(t[:32] == tag[:32] for t in user) else "cross-thread"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for i, (delta, reason) in enumerate(
                [
                    ({"role": "assistant", "content": scope}, None),
                    ({"content": " " + tag}, None),
                    ({}, "stop"),
                ]
            ):
                if i == 1 and tag in self.server.gates:
                    self.server.gates[tag].wait(100)
                if i < 2:
                    time.sleep(self.server.delay / 2)
                chunk = {
                    "id": "chatcmpl-" + tag,
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "synthetic",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": reason}],
                }
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            return


def free_port():
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start(stack, cmd, env, path):
    log = stack.enter_context(path.open("ab"))
    process = subprocess.Popen(cmd, env=env, cwd=ROOT, stdout=log, stderr=log)

    def stop():
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    stack.callback(stop)
    return process


def wait_ready(check, process):
    until = time.monotonic() + 60
    while time.monotonic() < until and process.poll() is None:
        try:
            if check():
                return
        except (OSError, psycopg.Error, httpx.HTTPError):
            pass
        time.sleep(0.1)
    raise RuntimeError(f"local service startup failed (process {process.poll()})")


def stats(values):
    values = sorted(values)
    if not values:
        return {}
    return {
        f"p{p}": round(values[math.ceil(len(values) * p / 100) - 1], 3)
        for p in (50, 95, 99, 100)
    }


async def provision(client, base, i):
    scope = str(9001 + i)
    tenant = str(uuid4())
    response = await client.post(
        base + "/assistants",
        json={
            "graph_id": "agent",
            "name": MARKERS[i],
            "metadata": {"zerai_scope_id": scope, "zerai_tenant_id": tenant},
            "context": {
                "portfolio_context": {"scope_id": scope, "tenant_id": tenant},
                "agent_profile": {"name": MARKERS[i]},
                "system_prompt": "Teste local",
                "agent_instructions": "Responda ao teste.",
                "active_workflow": "",
                "allowed_tools": [],
            },
        },
    )
    response.raise_for_status()
    return response.json()["assistant_id"]


def open_stream(client, base, thread, assistant, tag, trace=None):
    return client.stream(
        "POST",
        f"{base}/threads/{thread}/runs/stream",
        extensions={"trace": trace} if trace else {},
        json={
            "assistant_id": assistant,
            "input": {"messages": [{"role": "user", "content": tag}]},
            "stream_mode": ["messages-tuple", "values"],
        },
    )


async def turn(client, base, thread, assistant, tag, scope):
    start_time = time.perf_counter()
    record = {"tag": tag, "scope": scope, "start_at": start_time}

    async def trace(event, _info):
        if event == "http11.send_request_body.complete":
            record["wire_at"] = time.perf_counter()

    first = None
    text = ""
    final = None
    try:
        async with open_stream(client, base, thread, assistant, tag, trace) as response:
            response.raise_for_status()
            record["run_id"] = response.headers["x-run-id"]
            record["accepted_at"] = time.perf_counter()
            event = ""
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
                    if event == "error":
                        record["error"] = data.get("error", "sse_error")
                    elif event == "messages" and data[0].get("content"):
                        text += data[0]["content"]
                        if first is None:
                            first = time.perf_counter() - start_time
                    elif event == "values":
                        final = data["messages"][-1]
        expected = f"{scope} {tag}"
        if not record.get("error") and not (
            text == expected
            and final
            and final.get("type") == "ai"
            and final.get("content") == expected
        ):
            record["error"] = "incorrect_stream_or_result"
    except httpx.HTTPStatusError as error:
        record["error"] = f"http_{error.response.status_code}"
    except (httpx.HTTPError, KeyError, ValueError) as error:
        record["error"] = type(error).__name__
    return {**record, "first": first, "end": time.perf_counter() - start_time}


@contextmanager
def observe_claims(dsn):
    # Isolated lab DB only. LISTEN/NOTIFY timestamps both committed transitions
    # on one monotonic clock, independently of wall-clock corrections on WSL.
    marks = {}
    stop = threading.Event()
    with psycopg.connect(dsn, autocommit=True) as listener:
        listener.execute("""
            CREATE FUNCTION lab_notify_run() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                PERFORM pg_notify('lab_run_state', NEW.run_id::text || ' ' || NEW.status);
                RETURN NEW;
            END $$;
            CREATE TRIGGER lab_enqueue AFTER INSERT ON langgraph.oss_runs
                FOR EACH ROW EXECUTE FUNCTION lab_notify_run();
            CREATE TRIGGER lab_claim AFTER UPDATE OF status ON langgraph.oss_runs
                FOR EACH ROW WHEN (NEW.status='running' AND OLD.status='queued')
                EXECUTE FUNCTION lab_notify_run();
            LISTEN lab_run_state""")

        def receive():
            while not stop.is_set():
                for message in listener.notifies(timeout=0.25):
                    run_id, status = message.payload.split()
                    marks.setdefault(run_id, {})[status] = time.monotonic()

        worker = threading.Thread(target=receive)
        worker.start()
        try:
            yield marks
        finally:
            stop.set()
            worker.join()


async def stage(client, bases, assistants, db, users, args, provider, marks):
    threads = [str(uuid4()) for _ in range(users)]
    # Provision sessions ahead of the measured window, as in an open chat.
    gate = asyncio.Semaphore(8)

    async def create(i, thread):
        async with gate:
            r = await client.post(
                bases[i % len(bases)] + "/threads",
                json={
                    "thread_id": thread,
                    "metadata": {"assistant_id": assistants[i % 2]},
                },
            )
            r.raise_for_status()

    await asyncio.gather(*(create(i, t) for i, t in enumerate(threads)))
    active = peak = peak_queued = peak_running = peak_db_connections = 0
    starts = []
    stage_start = time.perf_counter()
    utc_start = datetime.now(UTC).isoformat()

    async def observe():
        nonlocal peak_queued, peak_running, peak_db_connections
        while True:
            counts = dict(
                db.execute("""SELECT status,count(*) FROM langgraph.oss_runs
                              WHERE status IN ('queued','running') GROUP BY status""").fetchall()
            )
            peak_queued = max(peak_queued, counts.get("queued", 0))
            peak_running = max(peak_running, counts.get("running", 0))
            connections = db.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend'"
            ).fetchone()[0]
            peak_db_connections = max(peak_db_connections, connections)
            await asyncio.sleep(1)

    async def user(i, thread):
        nonlocal active, peak
        await asyncio.sleep(args.spread * i / users)
        items = []
        for n in range(args.turns):
            if n:
                await asyncio.sleep(args.think + i % 11)
            active += 1
            peak = max(peak, active)
            starts.append(int(time.perf_counter() - stage_start))
            tag = thread.replace("-", "") + "-" + str(n + 1)
            items.append(
                await turn(
                    client,
                    bases[(i + n) % len(bases)],
                    thread,
                    assistants[i % 2],
                    tag,
                    MARKERS[i % 2],
                )
            )
            active -= 1
        return items

    monitor = asyncio.create_task(observe())
    try:
        results = [
            row
            for group in await asyncio.gather(
                *(user(i, t) for i, t in enumerate(threads))
            )
            for row in group
        ]
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
    rows = db.execute(
        """SELECT run_id::text,status,extract(epoch from started_at-created_at),
                    result->'messages'->-1->>'content'
                    FROM langgraph.oss_runs WHERE thread_id=ANY(%s::uuid[])""",
        (threads,),
    ).fetchall()
    statuses = Counter(row[1] for row in rows)
    wall_queue = {row[0]: float(row[2]) for row in rows if row[2] is not None}
    queue = {
        run: marks[run]["running"] - marks[run]["queued"]
        for run in wall_queue
        if {"running", "queued"} <= marks.get(run, {}).keys()
    }
    by_id = {r[0]: (r[1], r[3]) for r in rows}
    errors = Counter()
    for item in results:
        err = item.get("error")
        if not err and by_id.get(item.get("run_id")) != (
            "succeeded",
            f"{item['scope']} {item['tag']}",
        ):
            err = "incorrect_durable_result"
        if not err and provider.calls[item["tag"]] != 1:
            err = "incorrect_model_call_count"
        if err:
            errors[err] += 1
    accepted = [r for r in results if "accepted_at" in r]
    sent = [r for r in results if "wire_at" in r]
    edges = [(r["accepted_at"], 1) for r in accepted] + [
        (r["start_at"] + r["end"], -1) for r in accepted
    ]
    return {
        "users": users,
        "started_utc": utc_start,
        "model_calls": sum(provider.calls[r["tag"]] for r in results),
        "turns": len(results),
        "seconds": round(time.perf_counter() - stage_start, 3),
        "peak_requests": peak,
        "http_bodies_sent": len(sent),
        "accepted_run_headers": len(accepted),
        "peak_accepted_open_streams": max(
            accumulate(change for _, change in sorted(edges)), default=0
        ),
        "client_send_seconds": stats(r["wire_at"] - r["start_at"] for r in sent),
        "accept_seconds": stats(r["accepted_at"] - r["start_at"] for r in accepted),
        "stage_to_last_body_seconds": round(
            max((r["wire_at"] - stage_start for r in sent), default=0), 3
        ),
        "stage_to_last_accept_seconds": round(
            max((r["accepted_at"] - stage_start for r in accepted), default=0), 3
        ),
        "peak_arrivals_one_second": max(Counter(starts).values()),
        "peak_queued_sampled": peak_queued,
        "peak_running_sampled": peak_running,
        "peak_db_client_connections_sampled": peak_db_connections,
        "db_statuses": statuses,
        "errors": errors,
        "queue_seconds": stats(queue.values()),
        "monotonic_queue_count": len(queue),
        "db_wall_queue_seconds": stats(wall_queue.values()),
        "db_wall_queue_diff_over_one_second": sum(
            abs(wall_queue[run] - value) > 1 for run, value in queue.items()
        ),
        "db_wall_queue_outside_client_bounds": sum(
            run in wall_queue and not (0 <= wall_queue[run] <= item["end"])
            for item in results
            if (run := item.get("run_id"))
        ),
        "first_text_seconds": stats(
            [r["first"] for r in results if r["first"] is not None]
        ),
        "first_text_count": sum(r["first"] is not None for r in results),
        "end_seconds": stats([r["end"] for r in results]),
        "unique_db_runs": len(by_id),
    }


async def run_load(bases, token, dsn, args, provider):
    async with httpx.AsyncClient(
        trust_env=False,
        timeout=360,
        headers={"X-Api-Key": token},
        limits=httpx.Limits(max_connections=1200, max_keepalive_connections=32),
    ) as client:
        assistants = [await provision(client, bases[0], i) for i in range(2)]
        result = {
            "workers_per_replica": args.workers,
            "runtime_sha256": sha256(
                (ROOT / "src/simple_agent/oss_runtime.py").read_bytes()
            ).hexdigest(),
            "replicas": len(bases),
            "spread_seconds": args.spread,
            "think_seconds_min": args.think,
            "think_jitter_seconds_max": 10,
            "synthetic_model_seconds": args.model_seconds,
            "stages": [],
        }
        with psycopg.connect(dsn, autocommit=True) as db, observe_claims(dsn) as marks:
            result["pg_max_connections"] = int(
                db.execute("SHOW max_connections").fetchone()[0]
            )
            for size in args.users:
                item = await stage(
                    client, bases, assistants, db, size, args, provider, marks
                )
                result["stages"].append(item)
                args.output.write_text(json.dumps(result, indent=2) + "\n")
                print(json.dumps(item), flush=True)
    return all(
        not t["errors"]
        and t["db_statuses"] == {"succeeded": t["turns"]}
        and t["monotonic_queue_count"]
        == t["http_bodies_sent"]
        == t["accepted_run_headers"]
        == t["turns"]
        for t in result["stages"]
    )


async def replica_loss(replica, provider, token, output):
    base_a, process_a = replica("a")
    async with (
        httpx.AsyncClient(
            trust_env=False, timeout=75, headers={"X-Api-Key": token}
        ) as client,
        AsyncExitStack() as streams,
    ):
        assistants = [await provision(client, base_a, i) for i in range(2)]

        async def hold(i):
            thread = uuid4()
            tag = thread.hex + "-1"
            provider.gates[tag] = threading.Event()
            streams.callback(provider.gates[tag].set)
            r = await client.post(
                base_a + "/threads",
                json={
                    "thread_id": str(thread),
                    "metadata": {"assistant_id": assistants[i]},
                },
            )
            r.raise_for_status()
            response = await streams.enter_async_context(
                open_stream(client, base_a, thread, assistants[i], tag)
            )
            response.raise_for_status()
            event = ""
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                if (
                    event == "messages"
                    and line.startswith("data: ")
                    and json.loads(line[6:])[0]["content"] == MARKERS[i]
                ):
                    return tag, response.headers["x-run-id"]
            raise RuntimeError("missing first token before replica loss")

        # Only A can claim this first run. It stays inside the provider while B starts.
        orphan_tag, orphan = await hold(0)
        base_b, _ = await asyncio.to_thread(replica, "b")
        healthy_tag, healthy = await hold(1)
        process_a.kill()
        process_a.wait(timeout=5)
        lost_at = time.monotonic()
        async with client.stream("GET", f"{base_b}/runs/{healthy}/stream") as resumed:
            resumed.raise_for_status()
            provider.gates[healthy_tag].set()
            healthy_events = (await resumed.aread()).decode()
        healthy_status = (await client.get(f"{base_b}/runs/{healthy}")).json()
        healthy_s = time.monotonic() - lost_at
        async with client.stream("GET", f"{base_b}/runs/{orphan}/stream") as resumed:
            resumed.raise_for_status()
            orphan_events = (await resumed.aread()).decode()
        orphan_status = (await client.get(f"{base_b}/runs/{orphan}")).json()
        expected = MARKERS[1] + " " + healthy_tag
        outcome = {
            "surviving_executor_status": healthy_status["status"],
            "surviving_executor_full_final_value": expected in healthy_events
            and healthy_status["result"]["messages"][-1]["content"] == expected,
            "surviving_executor_new_messages": "event: messages" in healthy_events,
            "surviving_executor_seconds": round(healthy_s, 3),
            "surviving_executor_model_calls": provider.calls[healthy_tag],
            "lost_executor_status": orphan_status["status"],
            "lost_executor_error": orphan_status["error_code"],
            "lost_executor_stream_error": "event: error" in orphan_events,
            "lost_executor_seconds": round(time.monotonic() - lost_at, 3),
            "lost_executor_model_calls": provider.calls[orphan_tag],
        }
        output.write_text(json.dumps(outcome, indent=2) + "\n")
        print(json.dumps(outcome), flush=True)
        return (
            outcome["surviving_executor_status"] == "succeeded"
            and outcome["surviving_executor_full_final_value"]
            and outcome["surviving_executor_new_messages"]
            and outcome["lost_executor_status"] == "failed"
            and outcome["lost_executor_error"] == "worker_lost"
            and outcome["lost_executor_stream_error"]
            and provider.calls[healthy_tag] == provider.calls[orphan_tag] == 1
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--replica-loss",
        action="store_true",
        help="kill the local ingress during two streams, with one worker per replica",
    )
    parser.add_argument("--users", nargs="+", type=int, default=[100, 250, 500, 1000])
    parser.add_argument("--turns", type=int, choices=(1, 2), default=2)
    parser.add_argument(
        "--spread",
        type=float,
        default=60,
        help="initial arrivals distributed over seconds",
    )
    parser.add_argument(
        "--think",
        type=float,
        default=35,
        help="minimum seconds after reading first reply",
    )
    parser.add_argument("--model-seconds", type=float, default=0.5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--replicas", type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    if (
        not all(1 <= n <= 1000 for n in args.users)
        or not 1 <= args.workers <= 40
        or min(args.spread, args.think, args.model_seconds) < 0
    ):
        parser.error("invalid local test dimensions")
    if args.output.exists():
        parser.error("output already exists")
    with (
        tempfile.TemporaryDirectory(prefix="oss-runtime-lab-") as directory,
        ExitStack() as stack,
    ):
        lab = Path(directory)
        # An allowlist prevents inherited DSNs, credentials, proxies and tracing.
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(lab),
            "LC_ALL": "C",
            "TZ": "UTC",
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        pgport = free_port()
        pgdir = lab / "pg"
        subprocess.run(
            ["initdb", "-D", str(pgdir), "-A", "trust", "-U", "lab", "--encoding=UTF8"],
            check=True,
            env=env,
            stdout=subprocess.DEVNULL,
        )
        # Dedicated workers plus the Runtime (8) and session (5) pools per replica.
        pg_connections = max(100, args.replicas * (args.workers + 8 + 5) + 12)
        pg = start(
            stack,
            [
                "postgres",
                "-D",
                str(pgdir),
                "-k",
                str(lab),
                "-h",
                "",  # Only the Unix socket inside the private temporary directory.
                "-p",
                str(pgport),
                "-c",
                f"max_connections={pg_connections}",
            ],
            env,
            lab / "postgres.log",
        )
        dsn = f"postgresql://lab@/postgres?host={lab}&port={pgport}"

        def pg_ready():
            with psycopg.connect(dsn, connect_timeout=2):
                return True

        wait_ready(pg_ready, pg)
        redisport = free_port()
        redis_process = start(
            stack,
            [
                "redis-server",
                "--bind",
                "127.0.0.1",
                "--port",
                str(redisport),
                "--save",
                "",
                "--appendonly",
                "no",
                "--dir",
                str(lab),
            ],
            env,
            lab / "redis.log",
        )

        def redis_ready():
            with socket.create_connection(("127.0.0.1", redisport), timeout=1):
                return True

        wait_ready(redis_ready, redis_process)
        provider = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        provider.delay = args.model_seconds
        provider.gates = {}
        provider.calls = Counter()
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        stack.callback(provider.server_close)
        stack.callback(provider.shutdown)
        token = secrets.token_hex(32)
        env.update(
            SESSION_DATABASE_URL=dsn,
            SESSION_BACKEND="postgres",
            LANGGRAPH_STRICT_MSGPACK="true",
            OSS_RUNTIME_API_TOKEN=token,
            OSS_RUNTIME_REDIS_ENABLED="true",
            OSS_RUNTIME_WORKERS=str(1 if args.replica_loss else args.workers),
            OSS_RUNTIME_REDIS_URL=f"redis://127.0.0.1:{redisport}",
            OSS_RUNTIME_REDIS_DB="1",
            LLM_BASE_URL=f"http://127.0.0.1:{provider.server_port}/v1",
            LLM_MODEL="synthetic",
            LLM_API_KEY="local-synthetic",
            LANGSMITH_TRACING="false",
        )
        for key in [
            "OKF_DATA_ROOT",
            "SIMULATOR_ROOT",
            "SESSION_ROOT",
            "TOOL_REGISTRY_ROOT",
        ]:
            env[key] = str(lab / key)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/apply_postgres_migrations.py")],
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )

        def replica(name):
            port = free_port()
            base = f"http://127.0.0.1:{port}"
            log = lab / f"runtime-{name}.log"
            process = start(
                stack,
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "simple_agent.oss_runtime:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                env,
                log,
            )
            try:
                with httpx.Client(trust_env=False, timeout=2) as check:
                    wait_ready(lambda: check.get(base + "/info").is_success, process)
            except RuntimeError:
                print(log.read_text()[-2000:], file=sys.stderr)
                raise
            return base, process

        if args.replica_loss:
            return asyncio.run(replica_loss(replica, provider, token, args.output))
        bases = [replica(str(i))[0] for i in range(args.replicas)]
        return asyncio.run(run_load(bases, token, dsn, args, provider))


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
