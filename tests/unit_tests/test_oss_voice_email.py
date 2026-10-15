from decimal import Decimal

from starlette.testclient import TestClient

from simple_agent import oss_runtime
from simple_agent.tools import payment_tools


def test_voice_email_endpoint_requires_runtime_key_and_scope(monkeypatch):
    monkeypatch.setenv("OSS_RUNTIME_API_TOKEN", "x" * 64)
    sent = []
    monkeypatch.setattr(
        oss_runtime,
        "send_voice_demo_email",
        lambda *args, **kwargs: sent.append((args, kwargs)) or {"sent": True, "status": "accepted"},
    )
    payload = {
        "scope_id": 2,
        "session_id": "11111111-1111-4111-8111-111111111111",
        "contact_name": "Pessoa Sintetica",
        "credor": "Usedigi",
        "produto": "Consignado",
        "valor_divida": "100.00",
        "email": "marcelo@example.test",
        "latest_user_message": "Envie para marcelo@example.test",
        "forma_pagamento": "PIX",
        "parcelas": 1,
        "valor_total": "100.00",
    }
    client = TestClient(oss_runtime.app)
    path = "/integrations/elevenlabs/send-demo-email"
    assert client.post(path, json=payload).status_code == 401
    headers = {"X-Api-Key": "x" * 64}
    assert client.post(path, json={**payload, "scope_id": 1}, headers=headers).status_code == 400
    assert client.post(path, json={**payload, "unexpected": 1}, headers=headers).status_code == 400
    result = client.post(path, json=payload, headers=headers)
    assert result.status_code == 200
    assert result.json()["success"] is True
    assert sent[0][1] == {"scope_id": 2, "product": "Consignado"}
    assert sent[0][0][8] == Decimal("100.00")


def test_usedigi_voice_email_selects_only_scope_two(monkeypatch):
    calls = []

    def request(path, payload=None, timeout=15, scope_id=1):
        calls.append((path, scope_id, payload))
        if path.endswith("/channels"):
            return {
                "scope_id": 2,
                "scope_revision": 4,
                "channels": [{
                    "channel": "email", "enabled": True,
                    "template_id": "usedigi-template", "template_revision": 2,
                    "required": ["nome", "credor", "produto", "forma_pagamento", "valor", "payment_date", "codigo_pagamento"],
                }],
            }
        return {"status": "accepted", "code": "accepted_not_delivery"}

    monkeypatch.setattr(payment_tools, "request_json", request)
    result = payment_tools.send_voice_demo_email(
        "11111111-1111-4111-8111-111111111111",
        "Pessoa Sintetica", "Usedigi", "100.00", "marcelo@example.test",
        "Envie para marcelo@example.test", "PIX", 1, Decimal("100.00"),
        scope_id=2, product="Consignado",
    )
    assert result["sent"] is True
    assert [scope for _, scope, _ in calls] == [2, 2]
    assert calls[1][2]["template_id"] == "usedigi-template"
    assert calls[1][2]["values"]["produto"] == "Consignado"
