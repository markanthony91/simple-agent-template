"""Exercise the deployed OSS canary over its localhost HTTP port."""

from __future__ import annotations

import json
import os
import sys
from urllib.request import Request, urlopen
from uuid import uuid4

CANARY_SERVICE_ID = "accedeb1-4a8d-455e-a7ed-f4d2d7d92dec"
AGENT_ID = "05fd1686-9a81-4975-bd3b-0b288391d109"


def main() -> None:
    if os.getenv("RAILWAY_SERVICE_ID") != CANARY_SERVICE_ID:
        raise ValueError("wrong_service")
    base = "http://127.0.0.1:" + os.getenv("PORT", "2024")
    token = os.environ["OSS_RUNTIME_API_TOKEN"]

    def post(path, body):
        request = Request(
            base + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Api-Key": token},
        )
        with urlopen(request, timeout=120) as response:
            return json.load(response)

    info = json.load(urlopen(base + "/info", timeout=5))
    assert info["version"] == "oss-canary", "info"
    assistants = post("/assistants/search", {"graph_id": "agent", "limit": 20})
    assert any(a["assistant_id"] == AGENT_ID for a in assistants), "assistant"
    thread_id = str(uuid4())
    admin = post("/runs/wait", {"assistant_id": "okf_admin", "input": {
        "operation": "ensure_whatsapp_session", "approved": True, "thread_id": thread_id,
    }})
    assert admin["result"]["thread_id"] == thread_id, "admin"
    created = post("/threads", {"thread_id": thread_id, "metadata": {"channel": "canary"}})
    assert created["thread_id"] == thread_id, "thread"
    first = post(f"/threads/{thread_id}/runs/wait", {
        "assistant_id": AGENT_ID, "input": {
            "messages": [{"id": str(uuid4()), "type": "human", "content": "Olá"}]
        },
    })
    assert len(first["messages"]) >= 2 and first["messages"][-1]["type"] == "ai", "run"
    request = Request(
        base + f"/threads/{thread_id}/runs/stream",
        data=json.dumps({"assistant_id": AGENT_ID, "stream_mode": ["values"], "input": {
            "messages": [{"id": str(uuid4()), "type": "human", "content": "Obrigado"}]
        }}).encode(),
        headers={"Content-Type": "application/json", "X-Api-Key": token},
    )
    with urlopen(request, timeout=120) as response:
        events = [json.loads(line[6:]) for line in response if line.startswith(b"data: ")]
    assert events and "__error__" not in events[-1], "stream"
    assert len(events[-1]["messages"]) > len(first["messages"]), "resume"
    print({"http": "ok", "assistants": len(assistants), "admin": "ok",
           "wait": "ok", "stream": "ok", "resume": "ok"})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - suppress conversation and configuration
        code = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
        print(f"oss_http_smoke_failed:{code}", file=sys.stderr)
        raise SystemExit(1) from None
