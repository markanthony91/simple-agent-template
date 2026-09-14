from datetime import datetime, timedelta, timezone
import json

from langchain_core.messages import ToolMessage

from simple_agent.services.response_audit import audit_response
from simple_agent.tool_observability import tool_outcome


def session():
    return {
        "identity_verified": True,
        "debt_read": True,
        "fixture": {
            "debt": {"current_amount": "5873.42", "original_amount": "5000.00"}
        },
        "snapshot_id": "snapshot",
        "offers": {},
    }


def test_missing_authorization_and_invented_amount_are_flagged():
    assert audit_response("R$ 5.873,42", {})["status"] == "review_required"
    result = audit_response("Entrada R$ 1.000,00 e desconto 20%", session())
    assert len(result["issues"]) == 2
    assert result["pre_display_protection"] is False
    assert result["semantic_fidelity"] == "not_evaluated"


def test_malformed_model_amount_does_not_crash_after_streaming():
    assert audit_response("Total R$ 1.2.3", {})["issues"] == [
        "numeric_format_requires_review"
    ]


def test_balance_and_no_numeric_response_are_not_false_approvals():
    result = audit_response("Saldo R$ 5.873,42", session())
    assert result["status"] == "no_numeric_mismatch_detected"
    assert result["semantic_fidelity"] == "not_evaluated"
    assert audit_response("Olá!", {})["status"] == "not_evaluated"
    data = session()
    data["debt_read"] = False
    assert audit_response("Saldo R$ 5.873,42", data)["status"] == "review_required"


def test_only_current_owned_simulation_matches():
    data = session()
    offer = {
        "snapshot_id": "snapshot",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "debt_amount": "5873.42",
        "discount_amount": "0.00",
        "negotiated_amount": "5873.42",
        "installment_amount": "1957.81",
        "installment_schedule": ["1957.81", "1957.81", "1957.80"],
        "discount_percentage": "0",
    }
    data["offers"]["offer"] = offer
    text = "R$ 1.957,81, R$ 1.957,81 e R$ 1.957,80, 0%."
    assert audit_response(text, data)["status"] == "no_numeric_mismatch_detected"
    offer["snapshot_id"] = "other"
    assert audit_response(text, data)["status"] == "review_required"
    offer["snapshot_id"] = "snapshot"
    offer["expires_at"] = "2000-01-01T00:00:00+00:00"
    assert audit_response(text, data)["status"] == "review_required"


def test_execution_and_domain_outcome_are_independent():
    message = ToolMessage(
        content=json.dumps({"available": False, "reason": "policy_not_published"}),
        tool_call_id="x",
    )
    assert tool_outcome(message) == {
        "execution_status": "completed",
        "domain_outcome": "denied",
    }
    message.content = '{"error": true}'
    assert tool_outcome(message)["domain_outcome"] == "error"
    message.content = "No OKF matches found."
    assert tool_outcome(message)["domain_outcome"] == "lookup_miss"
    message.status = "error"
    assert tool_outcome(message)["execution_status"] == "error"
