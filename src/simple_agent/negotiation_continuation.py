"""Resume an announcement-only turn once, using the existing agent and tools."""

import json
import logging
import socket

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import SystemMessage

from simple_agent.message_delay import ANNOUNCEMENT

MARKER = "negotiation_review_resumed"
UNAVAILABLE = "Não consegui concluir a verificação da condição especial neste momento."
CONTINUE_REVIEW = """
A abertura da verificação já foi enviada ao cliente. Continue agora, na mesma
sessão, sem repetir a abertura e sem esperar nova mensagem ou evento externo.
Use apenas as tools existentes necessárias e os resultados já disponíveis.
Respeite a política, a identidade validada e os termos escolhidos pelo cliente.
Não gere proposta apenas para descobrir desconto. Não escolha PIX ou boleto:
se faltar o meio de pagamento ou outro dado obrigatório, pergunte somente o que
falta. Não invente autorização, percentual ou valor nem faça cálculos financeiros.
Conclua com o resultado comprovado, a pergunta necessária ou uma explicação
breve da impossibilidade de concluir. Não responda somente com uma promessa de
verificar. A camada de entrega já cuida da pausa; não solicite outra espera.
"""


def resumed_in_current_turn(messages):
    for message in reversed(messages):
        if message.type == "human":
            break
        if message.type == "ai" and message.additional_kwargs.get(MARKER) is True:
            return True
    return False


class NegotiationContinuationMiddleware(AgentMiddleware):
    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):
        messages = state.get("messages", [])
        if not messages:
            return None
        last = messages[-1]
        if (
            last.type != "ai"
            or last.tool_calls
            or not isinstance(last.content, str)
            or not ANNOUNCEMENT.fullmatch(last.content.strip())
        ):
            return None
        resumed = resumed_in_current_turn(messages)
        logging.getLogger(__name__).info(
            json.dumps(
                {
                    "event": "NEGOTIATION_REVIEW_CONTINUATION",
                    "hostname": socket.gethostname(),
                    "message_id": last.id,
                    "status": "exhausted" if resumed else "resumed",
                }
            )
        )
        if resumed:
            return {"messages": [last.model_copy(update={"content": UNAVAILABLE})]}
        marked = last.model_copy(
            update={
                "additional_kwargs": {**last.additional_kwargs, MARKER: True},
            }
        )
        return {"messages": [marked], "jump_to": "model"}

    async def aafter_model(self, state, runtime):
        return self.after_model(state, runtime)

    def _request(self, request):
        if not resumed_in_current_turn(request.state.get("messages", [])):
            return request
        message = request.system_message or SystemMessage(content="")
        content = message.content
        content = (
            content + CONTINUE_REVIEW
            if isinstance(content, str)
            else [*content, {"type": "text", "text": CONTINUE_REVIEW}]
        )
        return request.override(
            system_message=message.model_copy(update={"content": content})
        )

    def wrap_model_call(self, request, handler):
        return handler(self._request(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._request(request))
