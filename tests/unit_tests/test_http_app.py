from uuid import uuid4
from decimal import Decimal

from starlette.testclient import TestClient

from simple_agent.http_app import app
from simple_agent.services.session_store import SessionStore
from simple_agent.services.simulator_store import SimulatorStore


TOKEN = "a" * 64


def request(client, payload, token=TOKEN):
    return client.post(
        "/integrations/elevenlabs/send-payment-instruction",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


def demo_request(client, payload, token=TOKEN):
    return client.post(
        "/integrations/elevenlabs/send-demo-email",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_voice_email_bridge_is_authenticated_session_bound_and_shared(
    isolated, monkeypatch
):
    monkeypatch.setenv("ELEVENLABS_RUNTIME_API_TOKEN", TOKEN)
    session_id = str(uuid4())
    SessionStore().create(session_id, SimulatorStore().load())
    captured = {}

    def send(session, payment, email, message):
        captured.update(session=session, payment=payment, email=email, message=message)
        return {"sent": True, "status": "accepted", "recipient": "<redacted>"}

    monkeypatch.setattr(
        "simple_agent.http_app.send_payment_instruction_for_session", send
    )
    payload = {
        "session_id": session_id,
        "payment_id": f"PAY-{'b' * 32}",
        "email": "customer@example.com",
        "latest_user_message": "Envie para customer@example.com",
    }
    with TestClient(app) as client:
        assert request(client, payload, token="wrong").status_code == 401
        missing = request(client, {**payload, "session_id": str(uuid4())})
        assert missing.status_code == 404
        response = request(client, payload)

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "sent": True,
        "status": "accepted",
        "recipient": "<redacted>",
    }
    assert captured == {
        "session": session_id,
        "payment": payload["payment_id"],
        "email": payload["email"],
        "message": payload["latest_user_message"],
    }


def test_voice_email_bridge_rejects_unknown_fields_and_invalid_ids(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_RUNTIME_API_TOKEN", TOKEN)
    with TestClient(app) as client:
        response = request(
            client,
            {
                "session_id": "not-a-uuid",
                "payment_id": "PAY-1",
                "email": "customer@example.com",
                "latest_user_message": "customer@example.com",
                "amount": "850.00",
            },
        )
    assert response.status_code == 400
    assert response.json() == {"success": False, "error": "invalid_request"}


def test_voice_email_bridge_bounds_request_body(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_RUNTIME_API_TOKEN", TOKEN)
    with TestClient(app) as client:
        response = client.post(
            "/integrations/elevenlabs/send-payment-instruction",
            content=b"x" * 16_385,
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 413
    assert response.json() == {"success": False, "error": "payload_too_large"}


def test_voice_demo_email_uses_supplied_values_without_session_lookup(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_RUNTIME_API_TOKEN", TOKEN)
    captured = {}

    def send(*args):
        captured["args"] = args
        return {"sent": True, "status": "accepted", "recipient": "<redacted>"}

    monkeypatch.setattr("simple_agent.http_app.send_voice_demo_email", send)
    payload = {
        "session_id": str(uuid4()),
        "contact_name": "Marcelo",
        "credor": "Fastpay",
        "valor_divida": "R$ 850,00",
        "email": "cliente@example.com",
        "latest_user_message": "Envie para cliente@example.com",
        "forma_pagamento": "BOLETO",
        "parcelas": 3,
        "valor_total": 750,
        "valor_parcela": 250,
    }
    with TestClient(app) as client:
        assert demo_request(client, payload, token="wrong").status_code == 401
        response = demo_request(client, payload)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert captured["args"] == (
        payload["session_id"],
        "Marcelo",
        "Fastpay",
        "R$ 850,00",
        "cliente@example.com",
        "Envie para cliente@example.com",
        "BOLETO",
        3,
        Decimal("750"),
        Decimal("250"),
    )
