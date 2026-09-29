import asyncio
import json
from time import monotonic

import pytest

from simple_agent.message_delay import CashMessageDelay

FIRST = "Entendi, Eduardo. Vou verificar internamente se consigo uma condição especial para pagamento à vista hoje."
FINAL = FIRST + "\n\nA resposta existente continua aqui, sem alteração de valores."


def frame(kind, data):
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["values", "messages/partial", "messages/complete"])
async def test_delivery_splits_existing_text_then_restores_original(kind, monkeypatch):
    waits, sent = [], []

    async def wait(seconds):
        waits.append(seconds)
        assert FIRST.encode() in sent[-1]["body"]
        assert b"continua aqui" not in sent[-1]["body"]

    monkeypatch.setattr("simple_agent.message_delay.asyncio.sleep", wait)
    message = {"type": "ai", "id": "answer", "content": FINAL}
    data = (
        {"messages": [{"id": "user", "type": "human"}, message]}
        if kind == "values"
        else [message]
    )
    original = frame(kind, data)

    async def app(scope, receive, send):
        await receive()
        await send(
            {
                "type": "http.response.start",
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        # ASGI fragments are reassembled; original output is preserved byte-for-byte.
        for part in [original[:27], original[27:]]:
            await send({"type": "http.response.body", "body": part, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps({"input": {"messages": [{"id": "user"}]}}).encode(),
        }

    async def send(event):
        sent.append(event)

    await CashMessageDelay(app)(
        {"type": "http", "method": "POST", "path": "/threads/t/runs/stream"},
        receive,
        send,
    )
    bodies = [
        x["body"] for x in sent if x["type"] == "http.response.body" and x.get("body")
    ]
    assert waits == [5]
    assert len(bodies) == 2 and bodies[1] == original
    assert message["content"] == FINAL  # No application state was changed.


@pytest.mark.anyio
async def test_real_wait_is_async_and_historical_messages_are_ignored():
    timestamps, ticks = [], []
    current = {
        "messages": [{"id": "user", "type": "human"}, {"type": "ai", "content": FINAL}]
    }
    old = {
        "messages": [
            {"id": "previous", "type": "human"},
            {"type": "ai", "content": FINAL},
        ]
    }

    async def app(scope, receive, send):
        await receive()
        await send(
            {
                "type": "http.response.start",
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        for data in [old, current, current]:
            await send(
                {
                    "type": "http.response.body",
                    "body": frame("values", data),
                    "more_body": True,
                }
            )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def receive():
        return {
            "type": "http.request",
            "body": b'{"input":{"messages":[{"id":"user"}]}}',
        }

    async def send(event):
        if event.get("body"):
            timestamps.append(monotonic())

    async def other():
        await asyncio.sleep(0.1)
        ticks.append(monotonic())

    task = asyncio.create_task(other())
    await CashMessageDelay(app)(
        {"type": "http", "method": "POST", "path": "/threads/t/runs/stream"},
        receive,
        send,
    )
    await task
    assert len(timestamps) == 4
    assert timestamps[1] - timestamps[0] < 1
    assert timestamps[2] - timestamps[1] >= 4.95
    assert timestamps[3] - timestamps[2] < 1
    assert ticks[0] < timestamps[2]


@pytest.mark.anyio
async def test_other_routes_and_normal_text_are_unchanged():
    for path in ["/info", "/threads/t/runs/stream"]:
        sent = []
        original = frame(
            "values",
            {
                "messages": [
                    {"id": "u", "type": "human"},
                    {"type": "ai", "content": "Olá!"},
                ]
            },
        )

        async def receive():
            return {
                "type": "http.request",
                "body": b'{"input":{"messages":[{"id":"u"}]}}',
            }

        async def app(scope, receive, send):
            await receive()
            await send(
                {
                    "type": "http.response.start",
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )
            await send(
                {"type": "http.response.body", "body": original, "more_body": False}
            )

        async def send(event):
            sent.append(event)

        await CashMessageDelay(app)(
            {"type": "http", "method": "POST", "path": path}, receive, send
        )
        assert b"".join(x.get("body", b"") for x in sent) == original


@pytest.mark.anyio
@pytest.mark.parametrize(
    "chunk_size,message_type",
    [(1000, "ai"), (7, "AIMessageChunk"), (1, "AIMessageChunk")],
)
async def test_native_sdk_deltas_pause_before_continuation_without_duplicate_text(
    chunk_size, message_type, monkeypatch
):
    sent, waits = [], []
    metadata = {"langgraph_node": "model"}
    usage = {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}

    def messages():
        return [
            json.loads(line[6:])[0]
            for e in sent
            for line in e.get("body", b"").splitlines()
            if line.startswith(b"data: [")
        ]

    async def wait(seconds):
        waits.append(seconds)
        assert "".join(m.get("content", "") for m in messages()) == FIRST

    monkeypatch.setattr("simple_agent.message_delay.asyncio.sleep", wait)

    async def app(scope, receive, send):
        await receive()
        await send(
            {
                "type": "http.response.start",
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        for start in range(0, len(FINAL), chunk_size):
            chunk = {
                "id": "answer",
                "type": message_type,
                "content": FINAL[start : start + chunk_size],
            }
            if start + chunk_size >= len(FINAL):
                chunk.update(
                    usage_metadata=usage, response_metadata={"finish_reason": "stop"}
                )
            await send(
                {
                    "type": "http.response.body",
                    "body": frame("messages", [chunk, metadata]),
                    "more_body": True,
                }
            )
        # The final snapshot must not apply a second pause or duplicate the prefix.
        await send(
            {
                "type": "http.response.body",
                "body": frame(
                    "values",
                    {
                        "messages": [
                            {"id": "u", "type": "human"},
                            {"id": "answer", "type": "ai", "content": FINAL},
                        ]
                    },
                ),
                "more_body": False,
            }
        )

    async def receive():
        return {"type": "http.request", "body": b'{"input":{"messages":[{"id":"u"}]}}'}

    async def send(event):
        sent.append(event)

    await CashMessageDelay(app)(
        {"type": "http", "method": "POST", "path": "/threads/t/runs/stream"},
        receive,
        send,
    )
    assert waits == [5]
    assert "".join(m.get("content", "") for m in messages()) == FINAL
    assert [m["usage_metadata"] for m in messages() if m.get("usage_metadata")] == [
        usage
    ]
    assert [
        m["response_metadata"] for m in messages() if m.get("response_metadata")
    ] == [{"finish_reason": "stop"}]
