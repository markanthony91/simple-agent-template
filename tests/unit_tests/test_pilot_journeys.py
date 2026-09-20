"""Three deterministic integration journeys using the proposed pilot documents."""

from pathlib import Path

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


def test_happy_pilot_full_simulation_and_confirmation(isolated):
    seed(isolated, approve=True)
    rt = runtime("pilot-happy")
    assert verify(rt)["verified"]
    assert (
        call(tools.get_customer, rt, cpf="12345678900")["debt"]["current_amount"]
        == "5873.42"
    )
    assert "INSTITUTIONS" in okf_tools.okf_index.func(runtime=rt)
    okf_tools.okf_read.func(path=PATH, runtime=rt)
    offer = call(
        tools.generate_offer,
        rt,
        payment_type="installment",
        installments=3,
        policy_path=PATH,
    )
    assert offer["installment_schedule"] == ["1957.81", "1957.81", "1957.80"]
    confirmation = runtime("pilot-happy", f"CONFIRMAR ACORDO {offer['offer_id']}", "m2")
    agreement = call(
        tools.create_agreement,
        confirmation,
        offer_id=offer["offer_id"],
        explicit_confirmation=True,
    )
    assert agreement["created"] and agreement["is_simulation"]
    assert (
        call(
            tools.create_agreement,
            confirmation,
            offer_id=offer["offer_id"],
            explicit_confirmation=True,
        )
        == agreement
    )
    pix = call(
        payment_tools.create_payment_instruction,
        confirmation,
        agreement_id=agreement["agreement_id"],
        method="pix",
    )
    boleto = call(
        payment_tools.create_payment_instruction,
        confirmation,
        agreement_id=agreement["agreement_id"],
        method="boleto",
    )
    assert pix["payment_code"].startswith("DUMMY-PIX-")
    assert boleto["payment_code"].startswith("DUMMY-BOLETO-")
    assert pix["amount"] == agreement["installment_schedule"][0]
    email_runtime = runtime("pilot-happy", "Envie para teste@example.com", "m3")
    assert (
        call(
            payment_tools.send_payment_instruction,
            confirmation,
            payment_id=pix["payment_id"],
            email="teste@example.com",
        )["reason"]
        == "explicit_email_required"
    )
    delivery = call(
        payment_tools.send_payment_instruction,
        email_runtime,
        payment_id=pix["payment_id"],
        email="teste@example.com",
    )
    assert delivery["captured"] and delivery["status"] == "captured"
    assert delivery["recipient"] == "<redacted>"
    assert (
        call(
            payment_tools.send_payment_instruction,
            email_runtime,
            payment_id=pix["payment_id"],
            email="teste@example.com",
        )
        == delivery
    )
    assert (
        call(
            payment_tools.get_payment_status,
            runtime("pilot-happy", "Já paguei", "m4"),
            payment_id=pix["payment_id"],
        )["status"]
        == "pending"
    )
    settled = payment_tools.simulate_payment_settled("pilot-happy", pix["payment_id"])
    assert settled["status"] == "settled"
    assert (
        call(
            payment_tools.get_payment_status,
            email_runtime,
            payment_id=pix["payment_id"],
        )["status"]
        == "settled"
    )


def test_negative_draft_identity_and_excess_terms(isolated):
    seed(isolated)
    rt = runtime("pilot-negative")
    args = {"payment_type": "cash", "policy_path": PATH}
    assert (
        call(tools.generate_offer, rt, **args)["reason"]
        == "identity_verification_required"
    )
    assert verify(rt)["verified"]
    okf_tools.okf_read.func(path=PATH, runtime=rt)
    assert call(tools.generate_offer, rt, **args)["reason"] == "policy_not_published"
    seed(isolated, approve=True)
    rt = runtime("pilot-new-approved")
    verify(rt)
    okf_tools.okf_read.func(path=PATH, runtime=rt)
    assert (
        call(tools.generate_offer, rt, **args, discount_percentage="10")["reason"]
        == "policy_terms_exceeded"
    )
    assert call(tools.generate_offer, rt, **args)["available"]
    assert (
        call(
            payment_tools.create_payment_instruction,
            rt,
            agreement_id="AGR-missing",
            method="pix",
        )["reason"]
        == "valid_agreement_required"
    )


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
