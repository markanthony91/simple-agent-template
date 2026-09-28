"""Real tools and temporary SQLite; no provider, real customer or live runtime."""

import json
import sqlite3
from datetime import datetime as RealDateTime
from unittest.mock import patch

import pytest

from simple_agent.services.session_store import SessionStore
from simple_agent.services.simulator_store import SimulatorStore
from simple_agent.services.tool_registry import ToolRegistry
from simple_agent.tools import payment_tools as tools
from simple_agent.tool_middleware import FINANCIAL_TOOLS, FilterEnabledToolsMiddleware
from simple_agent.tool_observability import sanitize_result
from .test_collection_identity_gates import call, runtime, verify
from .test_pilot_journeys import seed, read_policy, PATH


def generate(isolated, key="origin", demo=False, method="boleto"):
    seed(isolated, approve=True)
    if demo:
        fixture = SimulatorStore().load()
        fixture.update(creditor_name="Will Bank", phone="+5511900000000")
        SessionStore().create(key, fixture, demo=True)
    rt = runtime(key, "Quero pagar em 3 parcelas por boleto")
    assert verify(rt)["verified"]
    read_policy(rt)
    result = call(
        tools.generate_payment_offer,
        rt,
        payment_type="installment" if method == "boleto" else "cash",
        installments=3 if method == "boleto" else 1,
        method=method,
        policy_path=PATH,
    )
    assert result["created"]
    return rt, result


def bind_existing(source, target, **replace):
    """Emulate a trusted adapter, not an LLM argument or public endpoint."""
    store = SessionStore()
    store.ensure_unbound(target)
    with store._connect() as db:
        row = db.execute(
            "SELECT tenant_id,portfolio_id,customer_id,debt_id,created_at FROM session_contexts WHERE session_id=?",
            (source,),
        ).fetchone()
        assert row
        context = dict(
            zip(
                ("tenant_id", "portfolio_id", "customer_id", "debt_id", "created_at"),
                row,
            )
        )
        context.update(replace)
        db.execute(
            "INSERT INTO session_contexts VALUES(?,?,?,?,?,?)",
            (target, *context.values()),
        )
        raw = json.loads(
            db.execute("SELECT data FROM sessions WHERE id=?", (target,)).fetchone()[0]
        )
        raw.pop("unbound_session", None)
        raw["demo_session"] = True
        db.execute("UPDATE sessions SET data=? WHERE id=?", (json.dumps(raw), target))
    rt = runtime(target)
    assert verify(rt)["verified"]
    return rt


def retrieve(rt, **kwargs):
    return call(tools.get_boleto_second_copy, rt, **kwargs)


def test_persist_replay_and_read_without_reissuing(isolated):
    rt, issued = generate(isolated)
    store = SessionStore()
    before = store.read("origin")
    replay = call(
        tools.generate_payment_offer,
        rt,
        payment_type="installment",
        installments=3,
        method="boleto",
        policy_path=PATH,
    )
    assert replay == issued
    result = retrieve(rt)
    assert (
        result["found"]
        and result["payment"]["payment_code"] == issued["payment"]["payment_code"]
    )
    assert result["due_date"] is None and not result["due_date_available"]
    assert store.read("origin") == before
    with store._connect() as db:
        assert db.execute("SELECT count(*) FROM payment_agreements").fetchone()[0] == 1
        assert (
            db.execute("SELECT count(*) FROM payment_instructions").fetchone()[0] == 1
        )
    assert retrieve(rt, installment_number=2)["reason"] == "boleto_not_issued"
    assert retrieve(rt, agreement_id="' OR 1=1 --")["reason"] == "boleto_not_found"
    assert retrieve(runtime("unknown"))["reason"] == "identity_verification_required"
    assert not store.exists("unknown")
    assert (
        retrieve(rt, installment_number=True)["reason"] == "invalid_installment_number"
    )
    assert retrieve(rt, installment_number=0)["reason"] == "invalid_installment_number"
    assert retrieve(rt, agreement_id="x" * 201)["reason"] == "invalid_agreement_id"


def test_cross_conversation_requires_trusted_binding_and_identity(isolated):
    rt, issued = generate(isolated, demo=True)
    other = bind_existing("origin", "other")
    found = retrieve(other)
    assert found["payment"]["payment_code"] == issued["payment"]["payment_code"]
    assert not SessionStore().read("other")["payments"]  # No stale copies imported.
    with SessionStore().transaction("other") as state:
        state["identity_verified"] = False
    assert retrieve(other)["reason"] == "identity_verification_required"
    # The same fixture/CPF in the Playground is not a trusted binding.
    copy = runtime("unbound-fixture")
    assert verify(copy)["verified"]
    assert (
        retrieve(copy, agreement_id=issued["agreement"]["agreement_id"])["reason"]
        == "boleto_not_found"
    )


@pytest.mark.parametrize(
    "field", ["tenant_id", "portfolio_id", "customer_id", "debt_id"]
)
def test_scope_filters_all_dimensions(isolated, field):
    _, issued = generate(isolated, demo=True)
    other = bind_existing("origin", "other")
    # Corrupt only the binding with FK checks off to independently exercise each SQL predicate.
    with sqlite3.connect(SessionStore().database) as db:
        db.execute(
            f"UPDATE session_contexts SET {field}=? WHERE session_id=?",
            ("different", "other"),
        )
    assert (
        retrieve(other, agreement_id=issued["agreement"]["agreement_id"])["reason"]
        == "boleto_not_found"
    )


def test_installment_and_agreement_selection(isolated):
    rt, issued = generate(isolated)
    call(
        tools.create_payment_instruction,
        rt,
        agreement_id=issued["agreement"]["agreement_id"],
        method="boleto",
        installment_number=2,
    )
    choices = retrieve(rt)
    assert choices["reason"] == "installment_selection_required"
    assert [p["installment_number"] for p in choices["installments"]] == [1, 2]
    assert "payment_code" not in json.dumps(choices)
    assert retrieve(rt, installment_number=2)["payment"]["amount"] == "1957.81"
    with SessionStore().transaction("origin", persist_payments=True) as state:
        a = dict(issued["agreement"], agreement_id="AGR-other")
        state["agreements"]["other"] = a
    assert retrieve(rt)["reason"] == "agreement_selection_required"
    assert retrieve(
        rt, agreement_id=issued["agreement"]["agreement_id"], installment_number=1
    )["found"]


@pytest.mark.parametrize("status", ["settled", "cancelled", "expired"])
def test_nonpayable_payment_has_no_code(isolated, status):
    rt, issued = generate(isolated)
    with SessionStore().transaction("origin", persist_payments=True) as state:
        state["payments"][issued["payment"]["payment_id"]]["status"] = status
    result = retrieve(rt)
    assert result == {"found": False, "reason": "payment_not_payable", "status": status}
    assert "DUMMY-" not in json.dumps(result)


def test_settlement_propagates_and_reset_removes_only_origin_records(isolated):
    rt, issued = generate(isolated, demo=True)
    other = bind_existing("origin", "other")
    unrelated, _ = generate(isolated, key="unrelated")
    tools.simulate_payment_settled("origin", issued["payment"]["payment_id"])
    assert retrieve(other)["reason"] == "payment_not_payable"
    assert SessionStore().reset_demo(
        "other"
    )  # Merely viewing does not transfer ownership.
    assert retrieve(rt)["reason"] == "payment_not_payable"
    assert SessionStore().reset_demo("origin")
    assert verify(other)["verified"]
    assert retrieve(other)["reason"] == "boleto_not_found"
    assert retrieve(rt)["reason"] == "identity_verification_required"
    assert retrieve(unrelated)["found"]
    assert not SessionStore().reset_demo("unrelated")


def test_failed_index_write_rolls_back_offer_and_session(isolated, monkeypatch):
    seed(isolated, approve=True)
    rt = runtime("rollback")
    assert verify(rt)["verified"]
    read_policy(rt)

    def fail(*args):
        raise sqlite3.OperationalError("synthetic failure")

    monkeypatch.setattr("simple_agent.services.session_store.save_payments", fail)
    with pytest.raises(sqlite3.OperationalError):
        call(
            tools.generate_payment_offer,
            rt,
            payment_type="installment",
            installments=3,
            method="boleto",
            policy_path=PATH,
        )
    state = SessionStore().read("rollback")
    assert not state["offers"] and not state["agreements"] and not state["payments"]


def test_query_failure_is_not_absence(isolated, monkeypatch):
    def fail(*args):
        raise sqlite3.OperationalError("private database path")

    monkeypatch.setattr(SessionStore, "boleto_second_copy", fail)
    assert retrieve(runtime("a")) == {"found": False, "reason": "query_failed"}


def test_real_boleto_pix_and_dates(isolated):
    rt, issued = generate(isolated)
    pid = issued["payment"]["payment_id"]
    with SessionStore().transaction("origin", persist_payments=True) as state:
        state["payments"][pid]["is_simulation"] = False
    assert retrieve(rt)["reason"] == "real_boleto_not_supported"
    with SessionStore().transaction("origin", persist_payments=True) as state:
        state["payments"][pid]["is_simulation"] = True
        state["payments"][pid]["due_date"] = "2026-09-28"

    class Clock:
        @staticmethod
        def now(tz):
            return RealDateTime.fromisoformat("2026-09-29T01:00:00+00:00").astimezone(
                tz
            )

    with patch("simple_agent.services.boleto_store.datetime", Clock):
        assert retrieve(rt)["found"]  # Still Sep 28 in Sao Paulo, already Sep 29 UTC.
    with SessionStore().transaction("origin", persist_payments=True) as state:
        state["payments"][pid]["due_date"] = "2000-01-01"
    assert retrieve(rt)["reason"] == "boleto_reissue_required"
    with SessionStore().transaction("origin", persist_payments=True) as state:
        state["payments"][pid]["due_date"] = "bad-date"
    assert retrieve(rt)["reason"] == "query_failed"
    pix, _ = generate(isolated, key="pix", method="pix")
    assert retrieve(pix)["reason"] == "boleto_not_issued"


def test_registry_disable_unbound_and_log_redaction(isolated, monkeypatch, tmp_path):
    from simple_agent import tool_middleware

    registry = ToolRegistry(tmp_path / "registry")
    monkeypatch.setattr(tool_middleware, "registry", registry)
    name = tools.get_boleto_second_copy.name
    assert name in registry.enabled_names() and name in FINANCIAL_TOOLS
    assert tools.get_boleto_second_copy in tools.PAYMENT_TOOLS
    SessionStore().ensure_unbound("unbound")
    with pytest.raises(PermissionError, match="demo_session_required"):
        FilterEnabledToolsMiddleware._assert_tool_allowed(name, "unbound")
    registry.set_enabled(name, False)
    with pytest.raises(PermissionError, match="tool_disabled"):
        FilterEnabledToolsMiddleware._assert_tool_allowed(name, "any")
    assert (
        sanitize_result(name, {"payment": {"payment_code": "secret-code"}})["payment"][
            "payment_code"
        ]
        == "<redacted>"
    )


def test_cross_session_result_is_recognized_by_numeric_audit(isolated):
    from langchain_core.messages import ToolMessage, HumanMessage
    from simple_agent.services.response_audit import audit_response

    _, _ = generate(isolated, demo=True)
    other = bind_existing("origin", "other")
    result = retrieve(other)
    messages = [
        HumanMessage(content="segunda via"),
        ToolMessage(
            content=json.dumps(result),
            name="get_boleto_second_copy",
            tool_call_id="copy",
        ),
    ]
    session = SessionStore().read("other")
    assert (
        audit_response("Valor: R$ 1.957,81", session, tool_messages=messages)["status"]
        == "no_numeric_mismatch_detected"
    )
    assert (
        audit_response("Valor: R$ 1.957,82", session, tool_messages=messages)["status"]
        == "review_required"
    )
    assert (
        audit_response(
            "Valor: R$ 1.957,81",
            session,
            tool_messages=[*messages, HumanMessage(content="outra pergunta")],
        )["status"]
        == "review_required"
    )
    messages[-1].content = "bad JSON"
    assert (
        audit_response("Valor: R$ 1.957,81", session, tool_messages=messages)["status"]
        == "review_required"
    )


def test_payment_records_cannot_be_overwritten_by_another_origin(isolated):
    _, issued = generate(isolated)
    store = SessionStore()
    with pytest.raises(ValueError, match="agreement_origin_mismatch"):
        with store.transaction("attacker", persist_payments=True) as state:
            state["agreements"]["copy"] = issued["agreement"]
    assert not store.exists("attacker")
    with pytest.raises(ValueError, match="payment_origin_mismatch"):
        with store.transaction("attacker", persist_payments=True) as state:
            state["payments"]["copy"] = issued["payment"]
    assert not store.exists("attacker")
