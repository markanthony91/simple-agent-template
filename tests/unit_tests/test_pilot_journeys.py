"""Three deterministic integration journeys using the proposed pilot documents."""

from pathlib import Path

import pytest
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage

from .test_collection_identity_gates import runtime, call, verify
from simple_agent.services.session_store import SessionStore
from simple_agent.services.channel_console import ChannelConsoleError
from simple_agent.services.simulator_store import SimulatorStore
from simple_agent.services.okf_validator import validate_okf_files
from simple_agent.tools import collection_tools as tools, okf_tools
from simple_agent.tools import payment_tools

ROOT = Path(__file__).resolve().parents[2] / "examples" / "pilot-okf"
PATH = "INSTITUTIONS/will_bank/cartao_de_credito/negotiation.md"


def conversation_runtime(key, *texts):
    return ToolRuntime(
        state={
            "messages": [
                HumanMessage(content=text, id=f"message-{index}")
                for index, text in enumerate(texts, 1)
            ]
        },
        context={},
        config={"configurable": {"thread_id": key}},
        stream_writer=lambda _: None,
        tool_call_id="call",
        store=None,
    )


def seed(store, approve=False):
    files = {p.relative_to(ROOT).as_posix(): p.read_text() for p in ROOT.rglob("*.md")}
    assert validate_okf_files(files)["valid"]
    if approve:
        files = {
            p: c.replace("status: draft", "status: published") for p, c in files.items()
        }
    store.import_bundle("synthetic-pilot", "0.2", files)
    fixture = SimulatorStore().load()
    fixture["institution"] = "Will Bank"
    SimulatorStore().save(fixture)


def assert_no_financial_action(key):
    with SessionStore().transaction(key) as state:
        assert not state["offers"]
        assert not state["agreements"]
        assert not state["payments"]
        assert not state["receipts"]


@pytest.mark.parametrize("method", ["pix", "boleto"])
def test_happy_pilot_generates_offer_agreement_and_payment(
    isolated, method, monkeypatch
):
    def channel_request(path, payload=None, timeout=15):
        if path.endswith("/channels"):
            return {
                "scope_id": 1,
                "scope_revision": 7,
                "channels": [
                    {
                        "channel": "email",
                        "enabled": True,
                        "template_id": "7ce8c81b-ed88-41c2-bd72-1a8d5d536aaa",
                        "template_revision": 2,
                        "required": [
                            "nome",
                            "forma_pagamento",
                            "valor",
                            "codigo_pagamento",
                            "aviso_simulacao",
                        ],
                    }
                ],
            }
        assert payload["to"] == "teste@example.com"
        assert payload["values"]["codigo_pagamento"].startswith("DUMMY-")
        return {
            "status": "accepted",
            "code": "accepted_not_delivery",
            "provider_id": "email-synthetic",
        }

    monkeypatch.setattr(payment_tools, "request_json", channel_request)
    seed(isolated, approve=True)
    key = f"pilot-happy-{method}"
    rt = runtime(key, f"Quero pagar em 3x por {method}")
    assert verify(rt)["verified"]
    assert (
        call(tools.get_customer, rt, cpf="12345678900")["debt"]["current_amount"]
        == "5873.42"
    )
    result = call(
        payment_tools.generate_payment_offer,
        rt,
        payment_type="installment",
        method=method,
        installments=3,
    )
    assert result["created"]
    offer = result["offer"]
    agreement = result["agreement"]
    payment = result["payment"]
    assert offer["installment_schedule"] == ["1957.81", "1957.81", "1957.80"]
    assert offer["discount_percentage"] == "0"
    assert agreement["created"] and agreement["is_simulation"]
    assert payment["payment_code"].startswith(f"DUMMY-{method.upper()}-")
    assert payment["amount"] == agreement["installment_schedule"][0]
    assert (
        call(
            payment_tools.generate_payment_offer,
            rt,
            payment_type="installment",
            method=method,
            installments=3,
        )
        == result
    )
    email_runtime = runtime(key, "Envie para teste@example.com.", "m3")
    assert (
        call(
            payment_tools.send_payment_instruction,
            rt,
            payment_id=payment["payment_id"],
            email="teste@example.com",
        )["reason"]
        == "explicit_email_required"
    )
    delivery = call(
        payment_tools.send_payment_instruction,
        email_runtime,
        payment_id=payment["payment_id"],
        email="teste@example.com",
    )
    assert delivery["sent"] and delivery["status"] == "accepted"
    assert delivery["recipient"] == "<redacted>"
    assert delivery["provider_id"] == "email-synthetic"
    assert b"teste@example.com" not in SessionStore().database.read_bytes()
    assert (
        call(
            payment_tools.send_payment_instruction,
            email_runtime,
            payment_id=payment["payment_id"],
            email="teste@example.com",
        )
        == delivery
    )
    assert (
        call(
            payment_tools.get_payment_status,
            runtime(key, "Já paguei", "m4"),
            payment_id=payment["payment_id"],
        )["status"]
        == "pending"
    )
    settled = payment_tools.simulate_payment_settled(key, payment["payment_id"])
    assert settled["status"] == "settled"
    assert (
        call(
            payment_tools.get_payment_status,
            email_runtime,
            payment_id=payment["payment_id"],
        )["status"]
        == "settled"
    )


def test_email_plan_rejects_untrusted_catalog_and_unknown_template_values(monkeypatch):
    monkeypatch.setattr(payment_tools, "request_json", lambda *args, **kwargs: {})
    with pytest.raises(ChannelConsoleError, match="email_catalog_invalid"):
        payment_tools._email_plan({})

    monkeypatch.setattr(
        payment_tools,
        "request_json",
        lambda *args, **kwargs: {
            "scope_id": 1,
            "scope_revision": 1,
            "channels": [
                {
                    "channel": "email",
                    "enabled": True,
                    "template_id": "template",
                    "template_revision": 1,
                    "required": ["vencimento"],
                }
            ],
        },
    )
    with pytest.raises(
        ChannelConsoleError, match="email_template_unsupported_variables"
    ):
        payment_tools._email_plan({"nome": "Cliente"})


def test_negative_draft_identity_and_excess_terms(isolated):
    seed(isolated)
    rt = runtime("pilot-negative", "Quero pagar à vista por pix")
    args = {"payment_type": "cash", "method": "pix"}
    assert (
        call(payment_tools.generate_payment_offer, rt, **args)["reason"]
        == "identity_verification_required"
    )
    assert verify(rt)["verified"]
    assert (
        call(payment_tools.generate_payment_offer, rt, **args)["reason"]
        == "policy_not_published"
    )
    seed(isolated, approve=True)
    key = "pilot-new-approved"
    verify(runtime(key))
    creditor_offer = call(
        payment_tools.generate_payment_offer,
        conversation_runtime(
            key,
            "Quero pagar à vista",
            "Quero 10% de desconto",
            "Prefiro PIX",
        ),
        **args,
    )
    assert creditor_offer["created"]
    assert creditor_offer["offer"]["discount_percentage"] == "0"
    assert "discount_percentage" not in payment_tools.generate_payment_offer.args
    assert (
        call(
            payment_tools.generate_payment_offer,
            runtime("pilot-missing-method", "Quero pagar à vista", "m3"),
            **args,
        )["reason"]
        == "identity_verification_required"
    )
    verify(runtime("pilot-missing-method"))
    assert (
        call(
            payment_tools.generate_payment_offer,
            runtime("pilot-missing-method", "Quero pagar à vista", "m4"),
            **args,
        )["reason"]
        == "explicit_offer_terms_required"
    )
    assert_no_financial_action("pilot-missing-method")
    verify(runtime("pilot-mismatched-installments"))
    assert (
        call(
            payment_tools.generate_payment_offer,
            runtime("pilot-mismatched-installments", "Quero em 2x por pix", "m5"),
            payment_type="installment",
            method="pix",
            installments=3,
        )["reason"]
        == "explicit_offer_terms_required"
    )
    assert_no_financial_action("pilot-mismatched-installments")

    key = "pilot-missing-installment-count"
    verify(runtime(key))
    assert call(
        payment_tools.generate_payment_offer,
        runtime(key, "Quero parcelar por pix", "m6"),
        payment_type="installment",
        method="pix",
    ) == {"created": False, "reason": "explicit_offer_terms_required"}
    assert_no_financial_action(key)


def test_automatic_policy_resolution_fails_closed_when_ambiguous(isolated):
    seed(isolated, approve=True)
    root = isolated.bundle_root(isolated.active_bundle_id())
    duplicate = "INSTITUTIONS/will_bank/cartao_de_credito/duplicate.md"
    (root / duplicate).write_text((root / PATH).read_text(), encoding="utf-8")
    rt = runtime("pilot-ambiguous", "Quero pagar em 3x por pix")
    assert verify(rt)["verified"]
    result = call(
        payment_tools.generate_payment_offer,
        rt,
        payment_type="installment",
        method="pix",
        installments=3,
    )
    assert result == {"created": False, "reason": "policy_ambiguous"}
    with SessionStore().transaction("pilot-ambiguous") as state:
        assert not state["receipts"]


@pytest.mark.parametrize(
    "missing_line",
    ['  offer_discount_percentage: "0"\n', "  max_installments: 3\n"],
)
def test_payment_policy_without_creditor_terms_fails_closed(isolated, missing_line):
    seed(isolated, approve=True)
    root = isolated.bundle_root(isolated.active_bundle_id())
    source = root / PATH
    source.write_text(
        source.read_text().replace(missing_line, ""),
        encoding="utf-8",
    )
    key = "pilot-missing-creditor-discount"
    rt = runtime(key, "Quero pagar à vista por pix")
    assert verify(rt)["verified"]
    assert call(
        payment_tools.generate_payment_offer,
        rt,
        payment_type="cash",
        method="pix",
    ) == {"created": False, "reason": "policy_terms_undefined"}
    assert_no_financial_action(key)


def test_payment_policy_failure_rolls_back_offer(isolated, monkeypatch):
    seed(isolated, approve=True)
    key = "pilot-payment-policy-failure"
    rt = runtime(key, "Quero pagar em 3x por boleto")
    assert verify(rt)["verified"]

    def deny(*_args, **_kwargs):
        raise ValueError("payment_method_not_allowed")

    monkeypatch.setattr(payment_tools, "validate_payment_policy", deny)
    result = call(
        payment_tools.generate_payment_offer,
        rt,
        payment_type="installment",
        method="boleto",
        installments=3,
    )
    assert result == {"created": False, "reason": "payment_method_not_allowed"}
    with SessionStore().transaction(key) as state:
        assert not state["offers"] and not state["agreements"]
        assert not state["payments"]


def test_neutral_global_consultation_does_not_verify_or_negotiate(isolated):
    seed(isolated, approve=True)
    rt = runtime("pilot-neutral")
    assert "GLOBAL" in okf_tools.okf_index.func(runtime=rt)
    assert "nao_reconhece_divida.md" in okf_tools.okf_index.func(
        directory="GLOBAL", runtime=rt
    )
    result = okf_tools.okf_read.func(path="GLOBAL/nao_reconhece_divida.md", runtime=rt)
    assert "A DEFINIR PELA OPERAÇÃO" in result
    with SessionStore().transaction("pilot-neutral") as state:
        assert not state["identity_verified"]
        assert not state["offers"] and not state["agreements"]
        assert not state["payments"] and not state["deliveries"]
