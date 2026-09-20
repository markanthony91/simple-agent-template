from __future__ import annotations

import json
import re
import asyncio
import logging
import socket
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any, Awaitable, Callable

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
    hook_config,
)
from langchain_core.messages import AIMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from simple_agent.services.tool_registry import ToolRegistry
from simple_agent.tool_observability import (
    sanitize_result,
    sanitize_tool_args,
    tool_outcome,
)
from simple_agent.services.session_store import SessionStore
from simple_agent.services.identity_policy import instructions
from simple_agent.services.response_audit import audit_response
from langgraph.config import get_config
from simple_agent.runtime_settings import LLMSettings

registry = ToolRegistry()
logger = logging.getLogger("simple_agent.tools")

RECOVERABLE_TOOL_ERRORS = (FileNotFoundError, ValueError, KeyError, PermissionError)
RESET_DEMO_REPLY = (
    "Conversa Demo reiniciada. O histórico foi preservado para auditoria e o "
    "estado operacional foi limpo."
)
RESET_DEMO_UNAVAILABLE = "Comando indisponível nesta sessão."
DIRECT_REPLY_TOOLS = {"verify_and_get_customer", "generate_payment_offer"}


def _brl(value: Any) -> str:
    try:
        number = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return "valor indisponível"
    whole, cents = f"{number:,.2f}".split(".")
    return f"R$ {whole.replace(',', '.')},{cents}"


def _direct_failure(reason: str) -> str:
    return {
        "identity_verification_required": "Preciso confirmar sua identidade antes de negociar.",
        "explicit_offer_terms_required": (
            "Informe na mesma mensagem se deseja pagar à vista ou em quantas parcelas, "
            "e escolha PIX ou boleto."
        ),
        "customer_not_eligible": "Não há uma condição de negociação disponível para este cadastro.",
        "customer_eligibility_exceeded": "A condição solicitada está fora da elegibilidade deste cadastro. Informe outra opção.",
        "policy_not_found": "Não encontrei uma política publicada aplicável a esta negociação.",
        "policy_ambiguous": "Há mais de uma política aplicável; a negociação foi bloqueada para evitar condição incorreta.",
        "policy_not_published": "A política encontrada ainda não está publicada e não autoriza uma proposta.",
        "policy_not_current": "A política encontrada não está vigente e não autoriza uma proposta.",
        "policy_terms_undefined": "As condições da política ainda não foram definidas.",
        "policy_terms_invalid": "As condições publicadas estão inválidas e não autorizam uma proposta.",
        "policy_terms_exceeded": "A condição solicitada ultrapassa o limite da política publicada. Informe outra opção.",
        "payment_terms_undefined": "Os meios de pagamento da política ainda não foram definidos.",
        "payment_terms_invalid": "Os meios de pagamento publicados estão inválidos.",
        "payment_method_not_allowed": "O meio de pagamento solicitado não é permitido pela política aplicável.",
        "invalid_financial_value": "O valor informado é inválido.",
    }.get(reason, "Não foi possível gerar a proposta com segurança. Tente outra condição.")


def render_direct_reply(tool_name: str, content: Any) -> str | None:
    """Render backend-authorized results without another model call."""
    try:
        payload = json.loads(content) if isinstance(content, str) else content
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if tool_name == "verify_and_get_customer":
        if not payload.get("verified"):
            if payload.get("requires_human"):
                return "Não consegui confirmar os dados. Por segurança, esta sessão não pode continuar."
            remaining = int(payload.get("attempts_remaining", 0))
            return (
                "Não consegui confirmar os dados informados. Confira todos os dados e tente novamente. "
                f"Tentativas restantes: {remaining}."
            )
        customer = payload.get("customer", {})
        debt = customer.get("debt", {}) if isinstance(customer, dict) else {}
        institution = str(customer.get("institution") or "a instituição")
        return (
            f"Identidade confirmada. O saldo atual simulado com {institution} é "
            f"{_brl(debt.get('current_amount'))}.\n\n"
            "Para negociar, informe se deseja pagar à vista ou parcelado, a quantidade "
            "de parcelas e escolha PIX ou boleto."
        )
    if tool_name != "generate_payment_offer":
        return None
    if not payload.get("created"):
        return _direct_failure(str(payload.get("reason") or ""))
    offer = payload["offer"]
    agreement = payload["agreement"]
    payment = payload["payment"]
    schedule = "; ".join(
        f"{index}ª {_brl(amount)}"
        for index, amount in enumerate(offer["installment_schedule"], 1)
    )
    payment_label = (
        "à vista" if offer["payment_type"] == "cash" else f"{offer['installments']} parcelas"
    )
    return (
        "Proposta simulada criada com sucesso.\n\n"
        f"- Total negociado: {_brl(offer['negotiated_amount'])}\n"
        f"- Forma: {payment_label}\n"
        f"- Cronograma: {schedule}\n"
        f"- Método: {str(payment['method']).upper()}\n"
        f"- Código dummy: {payment['payment_code']}\n"
        f"- Proposta: {offer['offer_id']}\n"
        f"- Acordo: {agreement['agreement_id']}\n"
        f"- ID do pagamento: {payment['payment_id']}\n"
        f"- Validade: {offer['expires_at']}\n\n"
        "Esta simulação não gera cobrança nem pagamento real."
    )


def is_reset_demo_command(content: Any) -> bool:
    if isinstance(content, list):
        content = " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return isinstance(content, str) and content.strip().casefold() == "/reset-demo"


class DemoResetMiddleware(AgentMiddleware):
    """Handle the exact Demo reset command without invoking tools or a model."""

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages or getattr(messages[-1], "type", None) != "human":
            return None
        if not is_reset_demo_command(messages[-1].content):
            return None
        key = get_config().get("configurable", {}).get("thread_id")
        if not key:
            raise ValueError("server_thread_id_required")
        if not SessionStore().reset_demo(key):
            return {
                "jump_to": "end",
                "messages": [AIMessage(content=RESET_DEMO_UNAVAILABLE)],
            }
        logger.info(
            json.dumps(
                {
                    "event": "DEMO_RESET",
                    "hostname": socket.gethostname(),
                    "thread_id": key,
                    "status": "success",
                }
            )
        )
        return {
            "jump_to": "end",
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                AIMessage(content=RESET_DEMO_REPLY),
            ],
        }

    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.before_model, state, runtime)


class DirectReplyMiddleware(AgentMiddleware):
    """Append a user-facing AI message after a return-direct transactional tool."""

    def after_agent(self, state, runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages or getattr(messages[-1], "type", None) != "tool":
            return None
        tool_message = messages[-1]
        if getattr(tool_message, "name", None) not in DIRECT_REPLY_TOOLS:
            return None
        reply = render_direct_reply(tool_message.name, tool_message.content)
        if not reply:
            return None
        key = get_config().get("configurable", {}).get("thread_id")
        with SessionStore().transaction(key) as session:
            report = audit_response(reply, session)
        logger.info(
            json.dumps(
                {
                    "event": "DIRECT_REPLY",
                    "hostname": socket.gethostname(),
                    "thread_id": key,
                    "tool": tool_message.name,
                    "audit_status": report["status"],
                }
            )
        )
        return {
            "messages": [
                AIMessage(
                    content=reply,
                    additional_kwargs={
                        "deterministic_reply": True,
                        "response_audit": report,
                    },
                )
            ]
        }

    async def aafter_agent(self, state, runtime) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.after_agent, state, runtime)


def _meta(request: ToolCallRequest) -> tuple[str, str, dict]:
    call = request.tool_call
    name = str(call.get("name") or "unknown")
    call_id = str(call.get("id") or "")
    raw_args = call.get("args")
    args = raw_args if isinstance(raw_args, dict) else {}
    return name, call_id, sanitize_tool_args(name, args)


def _log_event(
    request: ToolCallRequest,
    status: str,
    duration_ms: float | None = None,
    result=None,
    error: Exception | None = None,
) -> None:
    name, call_id, args = _meta(request)
    payload = {
        "event": "TOOL_CALL",
        "hostname": socket.gethostname(),
        "tool": name,
        "tool_call_id": call_id,
        "status": status,
        "args": args,
    }
    if duration_ms is not None:
        payload["duration_ms"] = round(duration_ms, 2)
    if result is not None:
        payload["result"] = sanitize_result(name, result)
        payload.update(tool_outcome(result))
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error_message"] = str(error)[:300]
    logger.info(json.dumps(payload, ensure_ascii=False))


def _audit_final(response: ModelResponse) -> ModelResponse:
    """Evaluate after streaming, annotate the same message without rewriting it."""
    key = get_config().get("configurable", {}).get("thread_id")
    with SessionStore().transaction(key) as session:
        for message in response.result:
            if (
                message.type != "ai"
                or message.tool_calls
                or not isinstance(message.content, str)
            ):
                continue
            report = audit_response(message.content, session)
            message.additional_kwargs["response_audit"] = report
            logger.info(
                json.dumps(
                    {
                        "event": "RESPONSE_AUDIT",
                        "hostname": socket.gethostname(),
                        "thread_id": key,
                        "message_id": message.id,
                        **report,
                    }
                )
            )
    return response


def _tool_error_message(request: ToolCallRequest, error: Exception) -> ToolMessage:
    call = request.tool_call
    name = str(call.get("name") or "unknown")
    call_id = str(call.get("id") or "")
    return ToolMessage(
        content=json.dumps(
            {
                "ok": False,
                "error": "tool_execution_failed",
                "tool": name,
                "error_type": type(error).__name__,
                "message": str(error),
                "recoverable": True,
            },
            ensure_ascii=False,
        ),
        tool_call_id=call_id,
    )


class FilterEnabledToolsMiddleware(AgentMiddleware):
    """Filter runtime tools, observe calls, and recover from expected failures."""

    @staticmethod
    def _completed(response: ModelResponse) -> ModelResponse:
        for message in response.result:
            reason = message.response_metadata.get("finish_reason")
            # Some gateways repeat finish markers; LangChain concatenates strings.
            # Accept only identical complete markers, never mixed/truncated reasons.
            match = (
                re.fullmatch(r"(stop|tool_calls)\1*", reason)
                if isinstance(reason, str)
                else None
            )
            if not match:
                raise RuntimeError("provider_response_incomplete")
            message.response_metadata["finish_reason"] = match.group(1)
        return response

    def _filtered_request(self, request: ModelRequest) -> ModelRequest:
        context = request.runtime.context
        configured = context if isinstance(context, dict) else {}
        settings = LLMSettings.model_validate(configured.get("llm_settings", {}))
        key = get_config().get("configurable", {}).get("thread_id")
        if not key:
            raise ValueError("server_thread_id_required")
        with SessionStore().transaction(key) as session:
            contract = instructions(session)
            creditor = str(session["fixture"].get("creditor_name") or "").strip()
        message = request.system_message or SystemMessage(content="")
        profile = configured.get("agent_profile", {})
        agent_name = (
            str(profile.get("name") or "").strip() if isinstance(profile, dict) else ""
        )
        content = message.content
        if creditor and isinstance(content, str):
            content = content.replace("{{credor}}", creditor)
            if agent_name:
                content = content.replace("{{nome_agente}}", agent_name)
        content = (
            content + contract
            if isinstance(content, str)
            else [*content, {"type": "text", "text": contract}]
        )
        enabled = registry.enabled_names()
        tools = [
            tool for tool in request.tools if getattr(tool, "name", None) in enabled
        ]
        return request.override(
            tools=tools,
            system_message=message.model_copy(update={"content": content}),
            model_settings={
                **request.model_settings,
                **settings.model_dump(exclude_none=True),
            },
        )

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        return _audit_final(self._completed(handler(self._filtered_request(request))))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        response = self._completed(
            await handler(await asyncio.to_thread(self._filtered_request, request))
        )
        return await asyncio.to_thread(_audit_final, response)

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        started = perf_counter()
        _log_event(request, "start")
        try:
            if request.tool_call.get("name") not in registry.enabled_names():
                raise PermissionError("tool_disabled")
            result = handler(request)
        except RECOVERABLE_TOOL_ERRORS as error:
            _log_event(
                request,
                "recoverable_error",
                (perf_counter() - started) * 1000,
                error=error,
            )
            return _tool_error_message(request, error)
        _log_event(request, "success", (perf_counter() - started) * 1000, result=result)
        return result

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        started = perf_counter()
        _log_event(request, "start")
        try:
            if request.tool_call.get("name") not in await asyncio.to_thread(
                registry.enabled_names
            ):
                raise PermissionError("tool_disabled")
            result = await handler(request)
        except RECOVERABLE_TOOL_ERRORS as error:
            _log_event(
                request,
                "recoverable_error",
                (perf_counter() - started) * 1000,
                error=error,
            )
            return _tool_error_message(request, error)
        _log_event(request, "success", (perf_counter() - started) * 1000, result=result)
        return result


filter_enabled_tools = FilterEnabledToolsMiddleware()
demo_reset = DemoResetMiddleware()
direct_reply = DirectReplyMiddleware()
