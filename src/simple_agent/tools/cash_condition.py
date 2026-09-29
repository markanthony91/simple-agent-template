"""Quote a policy-authorized cash condition without creating an agreement."""

import json

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from simple_agent.services.offer_policy import (
    CanonicalPolicyRequired,
    policy_document_scope,
)
from simple_agent.services.payment_policy import validate_requested_payment_policy
from simple_agent.services.session_store import SessionStore, thread_id
from simple_agent.tools.collection_tools import _generate_offer


@tool
def check_cash_payment_condition(policy_path: str, runtime: ToolRuntime) -> str:
    """Check a cash discount requested by the verified customer, before method selection.

    First read the applicable canonical policy through OKF. Call this tool ALONE,
    without accompanying text: the backend announces the check, waits five seconds
    and presents the exact approved condition. Never invent a special discount.
    This quotes an available offer only; it does not create an agreement, issue a
    payment or send anything. After the customer chooses a permitted method, use
    generate_payment_offer normally; its policy validations still apply.
    Do not use for general questions, installments or identity verification.
    """
    with (
        policy_document_scope(),
        SessionStore().transaction(thread_id(runtime)) as state,
    ):
        if not state.get("identity_verified"):
            return json.dumps(
                {"available": False, "reason": "identity_verification_required"}
            )
        methods = []
        try:
            for method in ("pix", "boleto"):
                try:
                    canonical, discount, _ = validate_requested_payment_policy(
                        state, policy_path, "cash", 1, method
                    )
                    methods.append(method)
                except ValueError as exc:
                    if str(exc) != "payment_method_not_allowed":
                        raise
            if not methods:
                raise ValueError("payment_method_not_allowed")
            offer = _generate_offer(state, "cash", 1, discount, canonical, runtime)
        except CanonicalPolicyRequired as exc:
            return json.dumps(
                {
                    "available": False,
                    "reason": "canonical_policy_required",
                    "canonical_policy_path": exc.path,
                }
            )
        except (KeyError, ValueError, ArithmeticError) as exc:
            return json.dumps(
                {
                    "available": False,
                    "reason": "policy_terms_undefined"
                    if isinstance(exc, KeyError)
                    else str(exc),
                }
            )
        if not offer.get("available"):
            return json.dumps(offer)
        return json.dumps(
            {
                "available": True,
                "offer": offer,
                "methods": methods,
                "full_name": state["fixture"].get("full_name", ""),
            },
            ensure_ascii=False,
        )
