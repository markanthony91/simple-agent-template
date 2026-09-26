import json

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from simple_agent.tool_middleware import (
    DIRECT_REPLY_TOOLS,
    direct_reply,
    render_direct_reply,
)


class CountingModel(FakeMessagesListChatModel):
    calls: int = 0

    def bind_tools(self, *args, **kwargs):
        return self

    def _generate(self, *args, **kwargs):
        self.calls += 1
        return super()._generate(*args, **kwargs)


def payment_result():
    return {
        "created": True,
        "offer": {
            "payment_type": "installment",
            "installments": 3,
            "negotiated_amount": "5873.42",
            "installment_schedule": ["1957.81", "1957.81", "1957.80"],
            "offer_id": "OFF-1",
            "expires_at": "2026-09-20T18:00:00+00:00",
        },
        "agreement": {"agreement_id": "AGR-1"},
        "payment": {
            "payment_id": "PAY-1",
            "method": "boleto",
            "payment_code": "DUMMY-BOLETO-1",
        },
    }


def test_transactional_result_is_rendered_without_second_model_call(isolated):
    @tool("generate_payment_offer")
    def synthetic_payment() -> str:
        """Return one backend-authorized synthetic payment."""
        return json.dumps(payment_result())

    model = CountingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "payment-1", "name": "generate_payment_offer", "args": {}}
                ],
            )
        ]
    )
    graph = create_agent(
        model=model, tools=[synthetic_payment], middleware=[direct_reply]
    )
    result = graph.invoke(
        {"messages": [{"role": "user", "content": "Quero boleto em 3x"}]},
        {"configurable": {"thread_id": "direct-reply"}},
    )

    assert model.calls == 1
    assert result["messages"][-1].response_metadata["finish_reason"] == "stop"
    assert result["messages"][-1].additional_kwargs["deterministic_reply"] is True
    audit = result["messages"][-1].additional_kwargs["response_audit"]
    assert audit["mode"] == "deterministic_backend"
    assert audit["semantic_fidelity"] == "backend_template"
    assert audit["pre_display_protection"] is True
    assert "1ª R$ 1.957,81" in result["messages"][-1].content
    assert "3ª R$ 1.957,80" in result["messages"][-1].content
    assert "- Parcela:" in result["messages"][-1].content
    assert "- Cronograma:" not in result["messages"][-1].content
    assert "- Acordo:" not in result["messages"][-1].content
    assert "- ID do pagamento:" not in result["messages"][-1].content
    assert "- Validade:" not in result["messages"][-1].content
    assert "- Proposta:" not in result["messages"][-1].content
    assert "informe o e-mail" in result["messages"][-1].content


def test_direct_failures_never_expose_financial_values():
    text = render_direct_reply(
        "generate_payment_offer",
        json.dumps({"created": False, "reason": "policy_terms_exceeded"}),
    )
    assert text == (
        "A condição solicitada ultrapassa o limite da política publicada. "
        "Informe outra opção."
    )
    assert "R$" not in text

    unread = render_direct_reply(
        "generate_payment_offer",
        json.dumps({"created": False, "reason": "policy_read_required"}),
    )
    assert "consultar no OKF" in unread


def test_identity_result_returns_to_model_for_workflow_response(isolated):
    @tool("verify_and_get_customer")
    def synthetic_identity() -> str:
        """Return one backend-verified synthetic customer."""
        return json.dumps({"verified": True, "customer": {"customer_id": "CUS-1"}})

    model = CountingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "identity-1", "name": "verify_and_get_customer", "args": {}}
                ],
            ),
            AIMessage(content="Resposta orientada pelo Workflow."),
        ]
    )
    graph = create_agent(
        model=model, tools=[synthetic_identity], middleware=[direct_reply]
    )

    result = graph.invoke(
        {"messages": [{"role": "user", "content": "123"}]},
        {"configurable": {"thread_id": "identity-workflow-reply"}},
    )

    assert "verify_and_get_customer" not in DIRECT_REPLY_TOOLS
    assert model.calls == 2
    assert result["messages"][-1].content == "Resposta orientada pelo Workflow."
    assert "deterministic_reply" not in result["messages"][-1].additional_kwargs


def test_email_reply_reports_success_after_provider_acceptance():
    accepted = render_direct_reply(
        "send_payment_instruction",
        json.dumps({"sent": True, "status": "accepted"}),
    )
    assert accepted == (
        "Sua proposta foi enviada com sucesso, verifique a caixa de entrada e a "
        "caixa de spam. Se precisar de qualquer coisa, é só me chamar!"
    )
    denied = render_direct_reply(
        "send_payment_instruction",
        json.dumps({"sent": False, "reason": "email_channel_not_configured"}),
    )
    assert "Não foi possível" in denied
