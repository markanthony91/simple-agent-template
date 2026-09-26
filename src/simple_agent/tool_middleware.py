from __future__ import annotations

import json
import re
import asyncio
import logging
import socket
import unicodedata
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
from simple_agent.services.identity_policy import instructions, policy_for
from simple_agent.services.response_audit import audit_response
from langgraph.config import get_config
from simple_agent.runtime_settings import LLMSettings
from simple_agent.tool_timing import capture_timing, timed_phase, timing_summary

registry = ToolRegistry()
logger = logging.getLogger("simple_agent.tools")

RECOVERABLE_TOOL_ERRORS = (FileNotFoundError, ValueError, KeyError, PermissionError)
RESET_DEMO_REPLY = (
    "Conversa Demo reiniciada. O histórico foi preservado para auditoria e o "
    "estado operacional foi limpo."
)
RESET_DEMO_UNAVAILABLE = "Comando indisponível nesta sessão."
DIRECT_REPLY_TOOLS = {
    "generate_payment_offer",
    "send_payment_instruction",
}
FINANCIAL_TOOLS = {
    "verify_and_get_customer",
    "generate_payment_offer",
    "send_payment_instruction",
    "get_payment_status",
}
UNBOUND_SESSION_INSTRUCTION = """

# Sessão sem dívida vinculada (regra do backend)

Este contato iniciou a conversa sem uma sessão criada pelo formulário. Não há
cliente, CPF, saldo, dívida, proposta ou pagamento disponível. Não solicite dados
de identidade e não apresente valores. Responda apenas dúvidas institucionais pelas
tools OKF; para consultar ou negociar uma dívida, informe que é necessário iniciar
pelo formulário da demonstração. Esta regra prevalece sobre instruções conflitantes.
"""
IDENTITY_OBJECT = (
    r"(?:\bcpf\b|nome completo|data de nascimento|4 primeiros digitos|"
    r"quatro primeiros digitos|numero do documento|dados de identificacao|"
    r"validar sua identidade|protocolo de identificacao|\bidentificacao\b)"
)
IDENTITY_NEGATION = re.compile(
    rf"\bnao .{{0,50}}(?:necessario|preciso|permitido).{{0,80}}{IDENTITY_OBJECT}"
)
IDENTITY_REQUEST = re.compile(
    rf"(?:informe|forneca|envie|digite|mande|compartilhe|confirme|preciso que|"
    rf"precisarei que|necessito que).{{0,120}}{IDENTITY_OBJECT}"
)
IDENTITY_OFFER = re.compile(
    rf"(?:se desejar|caso queira|me avise|podemos|posso).{{0,180}}(?:{IDENTITY_OBJECT}|"
    r"acessar sua conta|consultar seu caso|verificar seu caso)"
)
IDENTITY_PROCESS = re.compile(
    r"(?:realizar|fazer|iniciar|prosseguir com).{0,80}"
    r"(?:\bidentificacao\b|\bverificacao (?:de seguranca|da? identidade)\b)"
)
ACTIVE_OPENING_ACCEPTANCE = re.compile(
    r"(?:podemos|pode|podem) falar|sim|claro|estou disponivel"
)
ACTIVE_IDENTITY_REPLY = (
    "Para que possamos conversar com segurança e eu possa confirmar sua identidade, "
    "você poderia me informar os 3 primeiros dígitos do seu CPF, por favor?"
)
UNBOUND_IDENTITY_REPLY = (
    "Para consultar ou negociar uma dívida, é necessário iniciar pelo formulário "
    "da demonstração."
)


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
        "offer_terms_missing": "Em quantas parcelas você deseja pagar?",
        "invalid_payment_terms": "A quantidade de parcelas informada é inválida para essa modalidade.",
        "customer_not_eligible": "Não há uma condição de negociação disponível para este cadastro.",
        "customer_eligibility_exceeded": "A condição solicitada está fora da elegibilidade deste cadastro. Informe outra opção.",
        "policy_not_found": "Não encontrei uma política publicada aplicável a esta negociação.",
        "policy_read_required": "Preciso consultar no OKF a política aplicável antes de gerar a proposta.",
        "policy_receipt_mismatch": "A política consultada mudou durante o atendimento. Preciso consultá-la novamente.",
        "policy_scope_mismatch": "A política consultada não corresponde à instituição e ao produto desta dívida.",
        "policy_ambiguous": "Há mais de uma política aplicável; a negociação foi bloqueada para evitar condição incorreta.",
        "policy_not_published": "A política encontrada ainda não está publicada e não autoriza uma proposta.",
        "policy_not_current": "A política encontrada não está vigente e não autoriza uma proposta.",
        "policy_terms_undefined": "As condições da política ainda não foram definidas.",
        "debt_context_required": "Não foi possível confirmar o atraso da dívida para aplicar as condições da proposta.",
        "policy_terms_invalid": "As condições publicadas estão inválidas e não autorizam uma proposta.",
        "policy_terms_exceeded": "A condição solicitada ultrapassa o limite da política publicada. Informe outra opção.",
        "payment_terms_undefined": "Os meios de pagamento da política ainda não foram definidos.",
        "payment_terms_invalid": "Os meios de pagamento publicados estão inválidos.",
        "payment_method_not_allowed": "O meio de pagamento solicitado não é permitido pela política aplicável.",
        "invalid_financial_value": "O valor informado é inválido.",
    }.get(
        reason, "Não foi possível gerar a proposta com segurança. Tente outra condição."
    )


def render_direct_reply(tool_name: str, content: Any) -> str | None:
    """Render backend-authorized results without another model call."""
    try:
        payload = json.loads(content) if isinstance(content, str) else content
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if tool_name == "send_payment_instruction":
        if not payload.get("sent"):
            return (
                "Não foi possível solicitar o envio por e-mail com segurança. "
                "Confira o endereço e a configuração do canal."
            )
        return (
            "Sua proposta foi enviada com sucesso, verifique a caixa de entrada e a "
            "caixa de spam. Se precisar de qualquer coisa, é só me chamar!"
        )
    if tool_name != "generate_payment_offer":
        return None
    if not payload.get("created"):
        return _direct_failure(str(payload.get("reason") or ""))
    offer = payload["offer"]
    payment = payload["payment"]
    schedule = "; ".join(
        f"{index}ª {_brl(amount)}"
        for index, amount in enumerate(offer["installment_schedule"], 1)
    )
    schedule_lines = f"- Parcela: {schedule}"
    if offer["payment_type"] == "installment" and payment["method"] == "boleto":
        schedule_lines = "\n".join(
            f"- {index}ª parcela: {_brl(amount)}"
            for index, amount in enumerate(offer["installment_schedule"], 1)
        )
    payment_label = (
        "à vista"
        if offer["payment_type"] == "cash"
        else f"{offer['installments']} parcelas"
    )
    return (
        "Proposta simulada criada com sucesso.\n\n"
        f"- Total negociado: {_brl(offer['negotiated_amount'])}\n"
        f"- Forma: {payment_label}\n"
        f"{schedule_lines}\n"
        f"- Método: {str(payment['method']).upper()}\n"
        f"- Código dummy: {payment['payment_code']}\n"
        "\n"
        "Esta simulação não gera cobrança nem pagamento real.\n\n"
        "Para concluir, informe o e-mail que receberá a proposta e as instruções simuladas."
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
                "messages": [
                    AIMessage(
                        content=RESET_DEMO_UNAVAILABLE,
                        response_metadata={"finish_reason": "stop"},
                    )
                ],
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
                AIMessage(
                    content=RESET_DEMO_REPLY,
                    response_metadata={"finish_reason": "stop"},
                ),
            ],
        }

    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.before_model, state, runtime)


class DirectReplyMiddleware(AgentMiddleware):
    """Append a user-facing AI message after a return-direct transactional tool."""

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime) -> dict[str, Any] | None:
        # A success still uses the backend renderer without another model call.
        # Recoverable policy lookup errors get at most one retry per user turn.
        attempts = []
        for message in reversed(state.get("messages", [])):
            if getattr(message, "type", None) == "human":
                break
            if (
                getattr(message, "type", None) == "tool"
                and message.name == "generate_payment_offer"
            ):
                attempts.append(message)
        if not attempts:
            return None
        latest = attempts[0]
        try:
            payload = json.loads(latest.content)
        except (ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        recovery = {
            "offer_terms_missing": "Use the installment count already chosen in this conversation. If it is still missing or ambiguous, ask only for that field; never invent it.",
            "policy_read_required": "Read the selected canonical policy with okf_read or okf_read_section, then retry with the customer's existing choices.",
            "policy_receipt_mismatch": "Read the policy again in this session before retrying. Do not reuse stale evidence.",
            "policy_not_found": "Navigate OKF indexes to find and read the applicable policy. Never guess a path.",
            "policy_scope_mismatch": "Locate and read the policy matching the institution and product returned by identity verification.",
        }.get(payload.get("reason"))
        if not payload.get("created") and recovery and len(attempts) < 2:
            if not payload.get("recovery"):
                payload.update(recoverable=True, recovery=recovery)
                return {
                    "messages": [
                        latest.model_copy(update={"content": json.dumps(payload)})
                    ]
                }
            return None
        # Reuse the same renderer and audit metadata for success and terminal failure.
        result = self.after_agent({"messages": [latest]}, runtime)
        if result:
            return {**result, "jump_to": "end"}
        return None

    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.before_model, state, runtime)

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
        session = SessionStore().read(key)
        report = audit_response(reply, session)
        report.update(
            mode="deterministic_backend",
            semantic_fidelity="backend_template",
            pre_display_protection=True,
        )
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
                    response_metadata={"finish_reason": "stop"},
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
        payload.update(timing_summary())
    if result is not None:
        payload["result"] = sanitize_result(name, result)
        payload.update(tool_outcome(result))
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error_message"] = str(error)[:300]
    logger.info(json.dumps(payload, ensure_ascii=False))


def _plain_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            part.get("text", "") for part in value if isinstance(part, dict)
        )
    return ""


def _normalize(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.lower())
        if not unicodedata.combining(character)
    )


def _asks_for_identity(text: str) -> bool:
    normalized = _normalize(text)
    if IDENTITY_NEGATION.search(normalized):
        return False
    return bool(
        IDENTITY_REQUEST.search(normalized)
        or IDENTITY_OFFER.search(normalized)
        or IDENTITY_PROCESS.search(normalized)
    )


def _sanitize_identity_request(
    text: str, session: dict, latest_human_text: str = ""
) -> str:
    """Render the active CPF-only contract deterministically."""
    if session.get("identity_verified"):
        return text
    if session.get("unbound_session") is True:
        return UNBOUND_IDENTITY_REPLY if _asks_for_identity(text) else text
    policy = policy_for(session)
    if policy.cpf_mode != "first3" or policy.secondary != "none":
        return text
    accepted = _normalize(latest_human_text).strip(" .,!?;:")
    if session.get(
        "unbound_session"
    ) is not True and ACTIVE_OPENING_ACCEPTANCE.fullmatch(accepted):
        return ACTIVE_IDENTITY_REPLY
    if not _asks_for_identity(text):
        return text
    return (
        "Para consultar sua dívida, preciso validar sua identidade. "
        "Informe apenas os 3 primeiros dígitos do seu CPF."
    )


def _latest_human_text(request: ModelRequest) -> str:
    messages = request.state.get("messages", request.messages)
    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            return _plain_text(message.content)
    return ""


def _audit_final(request: ModelRequest, response: ModelResponse) -> ModelResponse:
    """Enforce the configured identity factors, then annotate the final response."""
    key = get_config().get("configurable", {}).get("thread_id")
    latest_human_text = _latest_human_text(request)
    session = SessionStore().read(key)
    for message in response.result:
        if (
            message.type != "ai"
            or message.tool_calls
            or not isinstance(message.content, str)
        ):
            continue
        message.content = _sanitize_identity_request(
            message.content, session, latest_human_text
        )
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

    @staticmethod
    def _assert_tool_allowed(tool_name: str, key: str) -> None:
        if tool_name not in registry.enabled_names():
            raise PermissionError("tool_disabled")
        if tool_name not in FINANCIAL_TOOLS:
            return
        session = SessionStore().read(key)
        if session.get("unbound_session") is True:
            raise PermissionError("demo_session_required")

    def _filtered_request(self, request: ModelRequest) -> ModelRequest:
        context = request.runtime.context
        configured = context if isinstance(context, dict) else {}
        settings = LLMSettings.model_validate(configured.get("llm_settings", {}))
        key = get_config().get("configurable", {}).get("thread_id")
        if not key:
            raise ValueError("server_thread_id_required")
        session = SessionStore().read(key)
        unbound = session.get("unbound_session") is True
        contract = UNBOUND_SESSION_INSTRUCTION if unbound else instructions(session)
        creditor = (
            ""
            if unbound
            else str(session["fixture"].get("creditor_name") or "").strip()
        )
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
            tool
            for tool in request.tools
            if getattr(tool, "name", None) in enabled
            and (not unbound or getattr(tool, "name", None) not in FINANCIAL_TOOLS)
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
        filtered = self._filtered_request(request)
        response = self._completed(handler(filtered))
        return _audit_final(filtered, response)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        filtered = await asyncio.to_thread(self._filtered_request, request)
        response = self._completed(await handler(filtered))
        return await asyncio.to_thread(_audit_final, filtered, response)

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        with capture_timing():
            started = perf_counter()
            _log_event(request, "start")
            try:
                tool_name = str(request.tool_call.get("name") or "")
                key = (
                    get_config().get("configurable", {}).get("thread_id")
                    if tool_name in FINANCIAL_TOOLS
                    else ""
                )
                with timed_phase("tool_guard"):
                    self._assert_tool_allowed(tool_name, key)
                with timed_phase("tool_handler"):
                    result = handler(request)
            except RECOVERABLE_TOOL_ERRORS as error:
                _log_event(
                    request,
                    "recoverable_error",
                    (perf_counter() - started) * 1000,
                    error=error,
                )
                return _tool_error_message(request, error)
            except Exception as error:
                _log_event(
                    request, "error", (perf_counter() - started) * 1000, error=error
                )
                raise
            _log_event(
                request, "success", (perf_counter() - started) * 1000, result=result
            )
            return result

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        with capture_timing():
            started = perf_counter()
            _log_event(request, "start")
            try:
                tool_name = str(request.tool_call.get("name") or "")
                key = (
                    get_config().get("configurable", {}).get("thread_id")
                    if tool_name in FINANCIAL_TOOLS
                    else ""
                )
                with timed_phase("tool_guard"):
                    await asyncio.to_thread(self._assert_tool_allowed, tool_name, key)
                with timed_phase("tool_handler"):
                    result = await handler(request)
            except RECOVERABLE_TOOL_ERRORS as error:
                _log_event(
                    request,
                    "recoverable_error",
                    (perf_counter() - started) * 1000,
                    error=error,
                )
                return _tool_error_message(request, error)
            except Exception as error:
                _log_event(
                    request, "error", (perf_counter() - started) * 1000, error=error
                )
                raise
            _log_event(
                request, "success", (perf_counter() - started) * 1000, result=result
            )
            return result


filter_enabled_tools = FilterEnabledToolsMiddleware()
demo_reset = DemoResetMiddleware()
direct_reply = DirectReplyMiddleware()
