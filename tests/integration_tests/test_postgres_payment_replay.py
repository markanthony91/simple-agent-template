"""Durable tool replay after the synthetic email transport accepts and the worker dies."""

import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest

from scripts.apply_postgres_migrations import main as migrate
from simple_agent.tools import payment_tools
from tests.unit_tests.test_offer_scenarios import call, generate, prepared, runtime


def send(key, payment_id):
    return call(
        payment_tools.send_payment_instruction,
        runtime(key, "Envie para test@example.com", "email"),
        payment_id=payment_id,
        email="test@example.com",
    )


def accept_until_killed(key, payment_id, ledger, accepted):
    def transport(path, payload=None, **kwargs):
        if path == "/api/engine/v1/channels":
            return {
                "scope_id": 1,
                "scope_revision": 1,
                "channels": [
                    {
                        "channel": "email",
                        "enabled": True,
                        "template_id": "test",
                        "template_revision": 1,
                        "required": ["codigo_pagamento"],
                    }
                ],
            }
        assert path == "/api/engine/v1/dispatch"
        assert payload["to"] == "test@example.com"
        assert payload["values"]["codigo_pagamento"].startswith("DUMMY-PIX-")
        with ledger.open("a") as file:
            print(payload["request_id"], file=file, flush=True)
            os.fsync(file.fileno())
        accepted.set()
        Event().wait(60)
        raise AssertionError("expected the test to terminate the worker")

    with patch.object(payment_tools, "request_json", transport):
        result = send(key, payment_id)
        raise AssertionError(f"worker returned before dispatch: {result.get('reason')}")


def test_parallel_offers_and_crash_after_email_acceptance(
    isolated, monkeypatch, tmp_path
):
    dsn = os.getenv("OSS_REDIS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("requires disposable PostgreSQL")
    monkeypatch.setenv("SESSION_BACKEND", "postgres")
    monkeypatch.setenv("SESSION_DATABASE_URL", dsn)
    monkeypatch.setattr(
        payment_tools,
        "request_json",
        lambda *a, **k: pytest.fail("retry attempted transport"),
    )
    migrate()
    key = f"payment-replay-{uuid4()}"
    rt = prepared(isolated, key)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: generate(rt, "cash", "pix", 1), range(4)))
    assert all(result == results[0] for result in results)
    payment_id = results[0]["payment"]["payment_id"]
    ctx = multiprocessing.get_context("spawn")
    accepted = ctx.Event()
    ledger = tmp_path / "fake-transport-accepts"
    worker = ctx.Process(
        target=accept_until_killed, args=(key, payment_id, ledger, accepted)
    )
    worker.start()
    try:
        assert accepted.wait(30), f"synthetic sender exited with {worker.exitcode}"
        with ThreadPoolExecutor(max_workers=4) as workers:
            replies = list(workers.map(lambda _: send(key, payment_id), range(4)))
    finally:
        worker.kill()
        worker.join(timeout=10)
    assert worker.exitcode is not None and worker.exitcode < 0
    retry = send(key, payment_id)
    assert all(reply == retry for reply in replies)
    assert retry["sent"] is False and retry["status"] == "processing"
    assert ledger.read_text().splitlines() == [retry["request_id"]]
    assert (
        call(payment_tools.get_payment_status, rt, payment_id=payment_id)["status"]
        == "pending"
    )

    with psycopg.connect(dsn) as db:
        state = db.execute(
            "SELECT state FROM runtime.sessions WHERE id=%s", (key,)
        ).fetchone()[0]
        counts = db.execute(
            """SELECT count(DISTINCT a.agreement_id),count(p.payment_id)
                 FROM runtime.payment_agreements a
                 LEFT JOIN runtime.payment_instructions p USING (agreement_id)
                WHERE a.origin_session_id=%s""",
            (key,),
        ).fetchone()
    assert [
        len(state[name]) for name in ("offers", "agreements", "payments", "deliveries")
    ] == [1, 1, 1, 1]
    assert (
        state["deliveries"][retry["delivery_id"]]["request_id"] == retry["request_id"]
    )
    assert counts == (1, 1)
