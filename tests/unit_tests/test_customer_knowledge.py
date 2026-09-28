import json

import pytest

from simple_agent.services.customer_knowledge import customer_knowledge
from simple_agent.services.session_store import SessionStore
from simple_agent.services.simulator_store import SimulatorStore
from simple_agent.tools.collection_tools import verify_and_get_customer, get_customer
from tests.unit_tests.test_collection_identity_gates import runtime


def bundle(store, companies=("fastpay",), product="CARTAO_DE_CREDITO"):
    files = {"index.md": "# Synthetic root", "COMPANIES/index.md": "# Companies"}
    for company in companies:
        base = f"COMPANIES/{company}/INSTITUTIONS/will-bank/{product}"
        parts = base.split("/")
        for size in range(2, len(parts) + 1):
            files["/".join(parts[:size]) + "/index.md"] = "# Synthetic index"
    return store.import_bundle("context-test", "0.2", files)["bundle_id"]


def state(snapshot, **fields):
    return {
        "snapshot_id": snapshot,
        "fixture": {
            "institution": "Will Bank",
            "product": "cartao_de_credito",
            **fields,
        },
    }


def test_unique_legacy_match_reports_knowledge_source_without_mutating_customer(
    isolated,
):
    session = state(bundle(isolated))
    result = customer_knowledge(session)
    assert result == {
        "company": "fastpay",
        "company_source": "okf_snapshot",
        "okf_directory": "COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO",
        "okf_context_status": "resolved",
    }
    assert "company" not in session["fixture"]
    assert "receipts" not in session
    assert "OKF_CANONICAL_DIRECTORY" in isolated.service().read_index(
        result["okf_directory"]
    )


def test_registered_company_disambiguates_and_preserves_display_name(isolated):
    snapshot = bundle(isolated, ("fastpay", "second-company"))
    assert customer_knowledge(state(snapshot))["okf_context_status"] == "ambiguous"
    result = customer_knowledge(state(snapshot, company="Second Company"))
    assert result["company"] == "Second Company"
    assert result["company_source"] == "customer"
    assert result["okf_directory"].startswith("COMPANIES/second-company/")
    missing = customer_knowledge(state(snapshot, company="Not Registered"))
    assert missing["okf_context_status"] == "not_found"
    assert missing["okf_directory"] is None


def test_case_collision_is_ambiguous(isolated):
    snapshot = bundle(isolated, ("fastpay", "FastPay"))
    assert (
        customer_knowledge(state(snapshot, company="fastpay"))["okf_context_status"]
        == "ambiguous"
    )


def test_snapshot_is_pinned_even_after_new_bundle(isolated):
    old = bundle(isolated, ("old-company",))
    new = bundle(isolated, ("new-company",))
    assert old != new
    assert customer_knowledge(state(old))["company"] == "old-company"
    assert customer_knowledge(state(new))["company"] == "new-company"


@pytest.mark.parametrize(
    "fields", [{"institution": "Other Bank"}, {"product": "loan"}, {"product": ""}]
)
def test_unknown_scope_does_not_select_another_branch(isolated, fields):
    result = customer_knowledge(state(bundle(isolated), **fields))
    assert result["okf_context_status"] == "not_found"
    assert result["okf_directory"] is None
    assert result["company"] is None


@pytest.mark.parametrize("snapshot", [None, "missing-snapshot", "../escape"])
def test_unavailable_snapshot_does_not_invent_company_or_directory(isolated, snapshot):
    result = customer_knowledge(state(snapshot))
    assert result["okf_context_status"] == "unavailable"
    assert result["okf_directory"] is None


def test_directory_escape_is_not_exposed(isolated, tmp_path):
    snapshot = bundle(isolated)
    root = isolated.bundle_root(snapshot)
    (root / "COMPANIES/escape").symlink_to(tmp_path, target_is_directory=True)
    assert customer_knowledge(state(snapshot))["okf_context_status"] == "unavailable"


def test_identity_tool_delivers_context_only_after_success(isolated):
    snapshot = bundle(isolated)
    key = "customer-context"
    with SessionStore().transaction(key) as session:
        session["snapshot_id"] = snapshot
        session["fixture"].update(institution="will-bank", product="cartao_de_credito")
        session["fixture"]["identity_policy"] = {
            "cpf_mode": "first3",
            "secondary": "none",
            "max_attempts": 3,
        }
    denied = json.loads(
        verify_and_get_customer.func(runtime=runtime(key, text="000"), cpf="000")
    )
    assert denied["verified"] is False
    assert "customer" not in denied
    accepted = json.loads(
        verify_and_get_customer.func(runtime=runtime(key, text="123"), cpf="123")
    )
    assert accepted["verified"] is True
    assert accepted["customer"]["company"] == "fastpay"
    assert accepted["customer"]["okf_context_status"] == "resolved"
    assert SessionStore().read(key)["receipts"] == {}


def test_demo_company_survives_relational_hydration_and_reset(isolated):
    bundle(isolated, ("fastpay", "other-company"))
    fixture = SimulatorStore().load()
    fixture.update(
        company="Fastpay",
        institution="will-bank",
        creditor_name="Will Bank",
        phone="+5511999999999",
    )
    fixture = SimulatorStore().save(fixture)
    sessions = SessionStore()
    sessions.create("company-demo", fixture, demo=True)
    assert sessions.read("company-demo")["fixture"]["company"] == "Fastpay"
    sessions.reset_demo("company-demo")
    assert sessions.read("company-demo")["fixture"]["company"] == "Fastpay"
    with sessions.transaction("company-demo") as current:
        current["identity_verified"] = True
    result = json.loads(get_customer.func(runtime=runtime("company-demo")))
    assert result["company_source"] == "customer"
    assert result["company"] == "Fastpay"
    assert result["okf_context_status"] == "resolved"
