"""Three deterministic integration journeys using the proposed pilot documents."""

from pathlib import Path

import pytest

from .test_collection_identity_gates import runtime, call, verify
from simple_agent.services.session_store import SessionStore
from simple_agent.services.simulator_store import SimulatorStore
from simple_agent.services.okf_validator import validate_okf_files
from simple_agent.tools import collection_tools as tools, okf_tools
from simple_agent.tools import payment_tools

ROOT = Path(__file__).resolve().parents[2] / "examples" / "pilot-okf"
PATH = "INSTITUTIONS/will_bank/cartao_de_credito/negotiation.md"


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


@pytest.mark.parametrize("method", ["pix", "boleto"])
def test_happy_pilot_generates_offer_agreement_and_payment(isolated, method):
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
    assert delivery["captured"] and delivery["status"] == "captured"
    assert delivery["recipient"] == "<redacted>"
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
    rt = runtime("pilot-new-approved")
    verify(rt)
    assert (
        call(
            payment_tools.generate_payment_offer,
            runtime("pilot-new-approved", "Quero à vista com 10% por pix", "m2"),
            **args,
            discount_percentage="10",
        )["reason"]
        == "policy_terms_exceeded"
    )
    assert (
        call(
            payment_tools.generate_payment_offer,
            runtime("pilot-new-approved", "Quero pagar à vista", "m3"),
            **args,
        )["reason"]
        == "explicit_offer_terms_required"
    )
    assert (
        call(
            payment_tools.generate_payment_offer,
            runtime("pilot-new-approved", "Quero em 2x por pix", "m4"),
            payment_type="installment",
            method="pix",
            installments=3,
        )["reason"]
        == "explicit_offer_terms_required"
    )


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


def test_payment_policy_failure_rolls_back_offer(isolated, monkeypatch):
    seed(isolated, approve=True)
    key = "pilot-payment-policy-failure"
    rt = runtime(key, "Quero pagar em 3x por boleto")
    assert verify(rt)["verified"]
    okf_tools.okf_read.func(path=PATH, runtime=rt)

    def deny(*_args, **_kwargs):
        raise ValueError("payment_method_not_allowed")

    monkeypatch.setattr(payment_tools, "validate_payment_policy", deny)
    result = call(
        payment_tools.generate_payment_offer,
        rt,
        payment_type="installment",
        method="boleto",
        installments=3,
        policy_path=PATH,
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
