"""Consultation uses issuance rules, but leaves no financial records behind."""

import json

import pytest
import yaml
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from simple_agent.services.response_audit import audit_response
from simple_agent.services.session_store import SessionStore
from simple_agent.services.tool_registry import ToolRegistry
from simple_agent import tool_middleware
from simple_agent.tools import payment_tools
from .test_collection_identity_gates import call, runtime
from .test_direct_replies import CountingModel
from .test_modality_policy_contract import prepare
from .test_pilot_journeys import PATH, read_policy
from .test_canonical_policy_recovery import prepare as prepare_auxiliary, AUX


def preview(rt, **terms):
    return call(
        payment_tools.get_payment_offer_preview,
        rt,
        payment_type=terms.pop("payment_type", "cash"),
        policy_path=PATH,
        **terms,
    )


def change_policy(store, rt, change, *, reread=True):
    file = store.bundle_root(store.active_bundle_id()) / PATH
    _, header, body = file.read_text().split("---", 2)
    meta = yaml.safe_load(header)
    change(meta)
    file.write_text("---\n" + yaml.safe_dump(meta) + "---" + body)
    if reread:
        read_policy(rt)


@pytest.mark.parametrize(
    "days,discount,total",
    [(30, "5", "5579.75"), (31, "8", "5403.55"), (91, "10", "5286.08")],
)
@pytest.mark.parametrize("method", ["pix", "boleto"])
def test_quote_then_issuance_preserves_creditor_tiers_without_early_payment(
    isolated, days, discount, total, method
):
    rt, _ = prepare(isolated, "preview", days=days)
    store = SessionStore()
    before = store.read("preview")
    database = store.database.read_bytes()
    quoted = preview(rt)
    assert quoted["available"] and quoted["discount_percentage"] == discount
    assert quoted["negotiated_amount"] == total
    assert set(quoted["allowed_methods"]) == {"pix", "boleto"}
    assert store.read("preview") == before
    assert store.database.read_bytes() == database
    assert (
        not {"offer_id", "agreement_id", "payment_id", "payment_code", "created"}
        & quoted.keys()
    )
    issued = call(
        payment_tools.generate_payment_offer,
        runtime("preview", f"Prefiro {method}", "choice"),
        payment_type="cash",
        method=method,
        policy_path=PATH,
    )
    assert issued["created"] and issued["payment"]["method"] == method
    for field in (
        "debt_amount",
        "discount_percentage",
        "discount_amount",
        "negotiated_amount",
        "installment_schedule",
    ):
        assert issued["offer"][field] == quoted[field]
    assert len(store.read("preview")["payments"]) == 1


def test_repeated_preview_is_read_only_even_for_missing_sessions(isolated, monkeypatch):
    rt, _ = prepare(isolated, "read-only")
    store = SessionStore()
    before = store.database.read_bytes()

    def forbid_write(*args, **kwargs):
        raise AssertionError("Consultation must not enter a write transaction")

    monkeypatch.setattr(SessionStore, "transaction", forbid_write)
    results = [preview(rt) for _ in range(3)]
    assert results[0]["available"] and results[0] == results[1] == results[2]
    assert preview(runtime("missing"))["reason"] == "identity_verification_required"
    assert not store.exists("missing")
    assert store.database.read_bytes() == before


@pytest.mark.parametrize(
    "entry,expected",
    [
        ("0", ["1957.81", "1957.81", "1957.80"]),
        ("1000.00", ["1000.00", "2436.71", "2436.71"]),
    ],
)
def test_installment_preview_returns_boleto_and_cent_schedule(
    isolated, entry, expected
):
    rt, _ = prepare(isolated, "installment-preview")
    quoted = preview(
        rt, payment_type="installment", installments=3, down_payment_amount=entry
    )
    assert quoted["available"] and quoted["allowed_methods"] == ["boleto"]
    assert quoted["installment_schedule"] == expected
    assert not SessionStore().read("installment-preview")["agreements"]
    issued = call(
        payment_tools.generate_payment_offer,
        rt,
        payment_type="installment",
        installments=3,
        down_payment_amount=entry,
        method="boleto",
        policy_path=PATH,
    )
    assert issued["created"] and issued["offer"]["installment_schedule"] == expected


@pytest.mark.parametrize(
    "terms,reason",
    [
        ({"payment_type": "installment"}, "offer_terms_missing"),
        ({"installments": 2}, "invalid_payment_terms"),
        ({"installments": False}, "invalid_payment_terms"),
        ({"installments": 0}, "invalid_payment_terms"),
        ({"down_payment_amount": "nan"}, "invalid_financial_value"),
        ({"payment_type": "installment", "installments": 11}, "policy_terms_exceeded"),
    ],
)
def test_bad_or_missing_terms_never_create_records(isolated, terms, reason):
    rt, _ = prepare(isolated, "bad-terms")
    before = SessionStore().read("bad-terms")
    result = preview(rt, **terms)
    assert result["available"] is False and result["reason"] == reason
    assert SessionStore().read("bad-terms") == before


@pytest.mark.parametrize(
    "change,reason,reread",
    [
        (lambda m: m.update(status="draft"), "policy_not_published", True),
        (
            lambda m: m.update(effective_until="2000-01-01T00:00:00+00:00"),
            "policy_not_current",
            True,
        ),
        (lambda m: m.update(institution="Other"), "policy_scope_mismatch", True),
        (lambda m: m.pop("negotiation"), "policy_terms_undefined", True),
        (lambda m: m.pop("payment"), "payment_terms_undefined", True),
        (
            lambda m: m["payment"]["methods_by_payment_type"].update(cash=[]),
            "payment_terms_invalid",
            True,
        ),
        (
            lambda m: m["negotiation"].update(max_installments=9),
            "policy_receipt_mismatch",
            False,
        ),
    ],
)
def test_same_policy_gates_as_issuance(isolated, change, reason, reread):
    rt, _ = prepare(isolated, "policy-failure")
    change_policy(isolated, rt, change, reread=reread)
    before = SessionStore().read("policy-failure")
    assert preview(rt) == {"available": False, "reason": reason}
    assert SessionStore().read("policy-failure") == before


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("identity_verified", False, "identity_verification_required"),
        ("unbound_session", True, "identity_verification_required"),
        ("receipts", {}, "policy_read_required"),
        ("snapshot_id", None, "policy_not_found"),
    ],
)
def test_session_guards(isolated, field, value, reason):
    rt, _ = prepare(isolated, "session-failure")
    with SessionStore().transaction("session-failure") as state:
        state[field] = value
    assert preview(rt) == {"available": False, "reason": reason}


@pytest.mark.parametrize(
    "eligibility,reason",
    [
        ({"can_negotiate": False}, "customer_not_eligible"),
        ({"max_discount_percentage": "0"}, "customer_eligibility_exceeded"),
    ],
)
def test_customer_eligibility_is_not_broadened(isolated, eligibility, reason):
    rt, _ = prepare(isolated, "eligibility")
    with SessionStore().transaction("eligibility") as state:
        state["fixture"]["eligibility"].update(eligibility)
    assert preview(rt) == {"available": False, "reason": reason}


def test_mandatory_entry_hint_without_generating_entry(isolated):
    rt, _ = prepare(isolated, "required-entry", days=181)
    change_policy(
        isolated,
        rt,
        lambda m: m["negotiation"].update(
            installment_overdue_rule={
                "min_days_overdue": 181,
                "max_installments": 12,
                "min_down_payment_percentage": "20",
            }
        ),
    )
    assert preview(rt, payment_type="installment", installments=3) == {
        "available": False,
        "reason": "down_payment_required",
        "minimum_down_payment_amount": "1174.69",
    }
    accepted = preview(
        rt, payment_type="installment", installments=3, down_payment_amount="1174.69"
    )
    assert accepted["available"] and accepted["installment_schedule"] == [
        "1174.69",
        "2349.37",
        "2349.36",
    ]
    assert not SessionStore().read("required-entry")["payments"]


def test_auxiliary_hint_requires_canonical_read(isolated):
    rt, _ = prepare_auxiliary(isolated)
    result = call(
        payment_tools.get_payment_offer_preview,
        rt,
        payment_type="cash",
        policy_path=AUX,
    )
    assert result == {
        "available": False,
        "reason": "canonical_policy_required",
        "canonical_policy_path": PATH,
    }
    assert preview(rt)["reason"] == "policy_read_required"
    read_policy(rt)
    assert preview(rt)["available"]
    assert not SessionStore().read("canonical-test")["payments"]
    assert (
        call(
            payment_tools.get_payment_offer_preview,
            rt,
            payment_type="cash",
            policy_path="no-such-file.md",
        )["reason"]
        == "policy_not_found"
    )


def test_manifest_enablement_and_execution_guards(isolated, tmp_path, monkeypatch):
    name = "get_payment_offer_preview"
    root = tmp_path / "registry"
    root.mkdir()
    (root / "registry.json").write_text(
        json.dumps({"tools": {"calculator": {"enabled": False}}})
    )
    registry = ToolRegistry(root)
    monkeypatch.setattr(tool_middleware, "registry", registry)
    metadata = next(x for x in registry.list_tools() if x["name"] == name)
    assert metadata["mode"] == "read_only" and metadata["requires_auth"]
    assert (
        name in registry.enabled_names()
        and "calculator" not in registry.enabled_names()
    )
    assert payment_tools.get_payment_offer_preview in payment_tools.PAYMENT_TOOLS
    assert (
        name in tool_middleware.FINANCIAL_TOOLS
        and name not in tool_middleware.DIRECT_REPLY_TOOLS
    )
    assert "method" not in payment_tools.get_payment_offer_preview.args
    assert (
        "runtime"
        not in payment_tools.get_payment_offer_preview.tool_call_schema.model_json_schema()[
            "properties"
        ]
    )
    with SessionStore().transaction("unbound-preview") as state:
        state["unbound_session"] = True
    with pytest.raises(PermissionError, match="demo_session_required"):
        tool_middleware.FilterEnabledToolsMiddleware._assert_tool_allowed(
            name, "unbound-preview"
        )
    registry.set_enabled(name, False)
    with pytest.raises(PermissionError, match="tool_disabled"):
        tool_middleware.FilterEnabledToolsMiddleware._assert_tool_allowed(
            name, "anything"
        )


def test_quote_audit_uses_only_successful_current_turn_tool_result(isolated):
    rt, _ = prepare(isolated, "audited", days=91)
    result = preview(rt)
    message = ToolMessage(
        content=json.dumps(result),
        tool_call_id="preview",
        name="get_payment_offer_preview",
    )
    session = SessionStore().read("audited")
    text = "Desconto 10%: R$ 587,34; total R$ 5.286,08."
    assert (
        audit_response(text, session, tool_messages=[message])["status"]
        == "no_numeric_mismatch_detected"
    )
    for messages in (
        [message, HumanMessage(content="outro turno")],
        [message.model_copy(update={"status": "error"})],
        [],
    ):
        assert (
            audit_response(text, session, tool_messages=messages)["status"]
            == "review_required"
        )
    for field, value in (
        ("available", False),
        ("snapshot_id", "other"),
        ("discount_amount", "invalid"),
    ):
        bad = message.model_copy(
            update={"content": json.dumps({**result, field: value})}
        )
        assert (
            audit_response(text, session, tool_messages=[bad])["status"]
            == "review_required"
        )


@pytest.mark.parametrize("method", ["pix", "boleto"])
def test_agent_consults_then_waits_for_method_before_issuance(isolated, method):
    prepare(isolated, "agent-preview", days=91)
    model = CountingModel(
        responses=[
            AIMessage(
                content="Entendi. Vou verificar internamente se consigo uma condição especial para pagamento à vista hoje.",
                tool_calls=[
                    {
                        "id": "preview",
                        "name": "get_payment_offer_preview",
                        "args": {"payment_type": "cash", "policy_path": PATH},
                    }
                ],
            ),
            AIMessage(
                content="O total para quitação é R$ 5.286,08 com 10% de desconto. Você prefere PIX ou boleto?"
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "issue",
                        "name": "generate_payment_offer",
                        "args": {
                            "payment_type": "cash",
                            "method": method,
                            "policy_path": PATH,
                        },
                    }
                ],
            ),
        ]
    )
    graph = create_agent(
        model=model,
        tools=[
            payment_tools.get_payment_offer_preview,
            payment_tools.generate_payment_offer,
        ],
        middleware=[tool_middleware.direct_reply],
    )
    config = {"configurable": {"thread_id": "agent-preview"}}
    first = graph.invoke(
        {"messages": [HumanMessage(content="Quero desconto à vista", id="request")]},
        config,
    )
    assert [m.name for m in first["messages"] if m.type == "tool"] == [
        "get_payment_offer_preview"
    ]
    assert first["messages"][-1].content.endswith("PIX ou boleto?")
    assert not SessionStore().read("agent-preview")["payments"]
    final = graph.invoke(
        {
            "messages": [
                *first["messages"],
                HumanMessage(content=f"Prefiro {method}", id="choice"),
            ]
        },
        config,
    )
    assert "Resumo da sua negociação" in final["messages"][-1].content
    state = SessionStore().read("agent-preview")
    assert (
        len(state["payments"]) == 1
        and next(iter(state["payments"].values()))["method"] == method
    )


@pytest.mark.anyio
async def test_preview_with_real_five_second_stream_pause_and_no_payment(isolated):
    from time import monotonic
    from simple_agent.message_delay import CashMessageDelay
    from .test_message_delay import FIRST, frame

    prepare(isolated, "preview-stream", days=91)
    model = CountingModel(
        responses=[
            AIMessage(
                content=FIRST,
                tool_calls=[
                    {
                        "id": "preview-stream-call",
                        "name": "get_payment_offer_preview",
                        "args": {"payment_type": "cash", "policy_path": PATH},
                    }
                ],
            ),
            AIMessage(content="O total é R$ 5.286,08. Você prefere PIX ou boleto?"),
        ]
    )
    graph = create_agent(model=model, tools=[payment_tools.get_payment_offer_preview])
    sent = []

    async def app(scope, receive, send):
        await receive()
        await send(
            {
                "type": "http.response.start",
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        async for update in graph.astream(
            {
                "messages": [
                    HumanMessage(content="Quero desconto", id="preview-request")
                ]
            },
            {"configurable": {"thread_id": "preview-stream"}},
            stream_mode="updates",
        ):
            for node in update.values():
                for message in node.get("messages", []):
                    await send(
                        {
                            "type": "http.response.body",
                            "body": frame(
                                "messages", [message.model_dump(mode="json"), {}]
                            ),
                            "more_body": True,
                        }
                    )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def receive():
        return {
            "type": "http.request",
            "body": b'{"input":{"messages":[{"id":"preview-request"}]}}',
        }

    async def send(event):
        if event.get("body"):
            sent.append((monotonic(), event["body"]))

    await CashMessageDelay(app)(
        {"type": "http", "method": "POST", "path": "/threads/t/runs/stream"},
        receive,
        send,
    )
    opening = next(t for t, body in sent if b"Vou verificar internamente" in body)
    continuation = next(t for t, body in sent if b"O total" in body)
    assert continuation - opening >= 4.9
    assert any(
        b"get_payment_offer_preview" in body and b"5286.08" in body for _, body in sent
    )
    assert not SessionStore().read("preview-stream")["payments"]
