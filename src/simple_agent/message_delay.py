"""Delay delivery after the existing cash-check sentence; never run business logic."""

import asyncio
import json
import re

ANNOUNCEMENT = re.compile(
    r"^\s*(?:Entendi(?:,\s*[^.\n]{1,80})?\.\s*)?"
    r"Vou verificar internamente se consigo uma condição especial "
    r"para pagamento à vista hoje[.!]",
    re.IGNORECASE,
)


class CashMessageDelay:
    """Split an outgoing SSE snapshot, without changing stored messages or prompts."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path", "").endswith("/runs/stream")
        ):
            return await self.app(scope, receive, send)
        request_body = bytearray()
        input_ids = set()
        enabled = False
        streaming = False
        paused = False
        buffer = b""

        async def read():
            nonlocal enabled
            event = await receive()
            if event["type"] == "http.request":
                request_body.extend(event.get("body", b""))
                if len(request_body) > 65536:
                    request_body.clear()
                elif not event.get("more_body"):
                    try:
                        request = json.loads(request_body)
                        messages = request.get("input", {}).get("messages", [])
                        input_ids.update(m["id"] for m in messages if m.get("id"))
                        enabled = bool(input_ids)
                    except (ValueError, TypeError, AttributeError):
                        pass
                    request_body.clear()
            return event

        def preview(frame):
            if b"Vou verificar internamente" not in frame:
                return None
            lines = frame.splitlines()
            kind = next(
                (line[6:].strip() for line in lines if line.startswith(b"event:")), b""
            )
            if kind not in (b"values", b"messages/partial", b"messages/complete"):
                return None
            try:
                data = json.loads(
                    b"\n".join(
                        line[5:].lstrip() for line in lines if line.startswith(b"data:")
                    )
                )
                messages = data.get("messages", []) if kind == b"values" else data
                if kind == b"values":
                    human = next(
                        (m for m in reversed(messages) if m.get("type") == "human"), {}
                    )
                    if human.get("id") not in input_ids:
                        return None
                message = messages[-1] if messages else {}
                text = message.get("content")
                if message.get("type") not in (
                    "ai",
                    "AIMessageChunk",
                ) or not isinstance(text, str):
                    return None
                match = ANNOUNCEMENT.match(text)
                if not match:
                    return None
                message["content"] = text[: match.end()]
                message["additional_kwargs"] = {
                    **message.get("additional_kwargs", {}),
                    "negotiation_stage": "cash_message_pause",
                }
                # This marker exists only on the wire. The original snapshot follows.
                head = [
                    line for line in lines if not line.startswith(b"data:") and line
                ]
                return (
                    b"\n".join(
                        head
                        + [b"data: " + json.dumps(data, ensure_ascii=False).encode()]
                    )
                    + b"\n\n"
                )
            except (ValueError, TypeError, AttributeError, IndexError):
                return None

        async def write(event):
            nonlocal streaming, paused, buffer
            if event["type"] == "http.response.start":
                streaming = any(
                    k.lower() == b"content-type" and b"text/event-stream" in v
                    for k, v in event.get("headers", [])
                )
            if (
                event["type"] != "http.response.body"
                or not streaming
                or not enabled
                or paused
            ):
                return await send(event)
            buffer += event.get("body", b"")
            # Bound the extra delivery buffer; do not retain historical snapshots.
            if len(buffer) > 8 * 1024 * 1024:
                raise ValueError("cash_delay_event_too_large")
            while boundary := re.search(rb"\r?\n\r?\n", buffer):
                frame, buffer = buffer[: boundary.end()], buffer[boundary.end() :]
                first = preview(frame)
                if first is not None and not paused:
                    await send(
                        {"type": "http.response.body", "body": first, "more_body": True}
                    )
                    paused = True
                    await asyncio.sleep(5)
                await send(
                    {"type": "http.response.body", "body": frame, "more_body": True}
                )
            if paused or not event.get("more_body"):
                await send({**event, "body": buffer})
                buffer = b""

        await self.app(scope, read, write)
