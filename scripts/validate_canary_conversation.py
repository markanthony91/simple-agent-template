"""Run one synthetic negotiation against the isolated Railway canary."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from uuid import uuid4


def main() -> None:
    if os.getenv("CANARY_VALIDATION") != "1":
        raise SystemExit("CANARY_VALIDATION=1_required")
    if os.getenv("SESSION_BACKEND") != "postgres":
        raise SystemExit("postgres_canary_required")

    base = f"http://127.0.0.1:{os.getenv('PORT', '2024')}"

    def request(path: str, payload: dict | None = None, method: str = "POST") -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            base + path,
            data=body,
            headers={"content-type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=180) as response:
            body = response.read()
            return json.loads(body) if body else {}

    source = Path(__file__).parents[1] / "examples" / "pilot-okf"
    files = {
        path.relative_to(source).as_posix(): path.read_text().replace(
            "status: draft", "status: published"
        )
        for path in source.rglob("*.md")
    }
    imported = request(
        "/runs/wait",
        {
            "assistant_id": "okf_admin",
            "input": {
                "operation": "import_bundle",
                "approved": True,
                "bundle_name": "isolated-canary-validation",
                "bundle_version": "0.2",
                "files": files,
            },
        },
    )
    if imported.get("error"):
        raise RuntimeError("synthetic_okf_import_failed")

    from simple_agent.services.session_store import SessionStore
    from simple_agent.services.simulator_store import SimulatorStore

    thread = str(uuid4())
    fixture = SimulatorStore().load()
    fixture.update(
        institution="Will Bank",
        creditor_name="Will Bank",
        identity_policy={"cpf_mode": "first3", "secondary": "none", "max_attempts": 3},
    )
    store = SessionStore()
    store.create(thread, fixture, demo=True)
    request("/threads", {"thread_id": thread})
    turns = []
    tools = []
    try:
        for text in (
            "Quero consultar e negociar minha dívida.",
            "123",
            "Quero parcelar em 3 vezes pelo boleto.",
        ):
            started = time.perf_counter()
            result = request(
                f"/threads/{thread}/runs/wait",
                {
                    "assistant_id": "agent",
                    "input": {"messages": [{"role": "user", "content": text}]},
                },
            )
            turns.append(round((time.perf_counter() - started) * 1000, 2))
            tools.extend(
                message.get("name")
                for message in result.get("messages", [])
                if message.get("type") == "tool" and message.get("name")
            )
        state = store.read(thread)
        agreement = next(iter(state["agreements"].values()), {})
        payment = next(iter(state["payments"].values()), {})
        if not state["identity_verified"] or not agreement:
            raise RuntimeError("synthetic_negotiation_incomplete")
        if payment.get("method") != "boleto" or agreement.get("installments") != 3:
            raise RuntimeError("synthetic_negotiation_terms_mismatch")
        if "send_payment_instruction" in tools:
            raise RuntimeError("unexpected_external_channel_tool")
        print(
            json.dumps(
                {
                    "thread": "<synthetic>",
                    "turns_ms": turns,
                    "tools": tools,
                    "identity_verified": True,
                    "agreement_created": True,
                    "method": "boleto",
                    "installments": 3,
                },
                ensure_ascii=False,
            )
        )
    finally:
        try:
            request(f"/threads/{thread}", method="DELETE")
        finally:
            import psycopg

            with psycopg.connect(os.environ["SESSION_DATABASE_URL"]) as db:
                db.execute("DELETE FROM runtime.sessions WHERE id=%s", (thread,))


if __name__ == "__main__":
    main()
