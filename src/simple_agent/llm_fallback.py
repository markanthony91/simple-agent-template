"""Retry only a failed model inference, before any response chunk is emitted."""

import json
import logging
import socket

import httpx
from langchain.agents.middleware import AgentMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from openai import APIConnectionError, APIStatusError

from simple_agent.llm import create_llm
from simple_agent.runtime_settings import LLMIntegration

logger = logging.getLogger("simple_agent.llm")


class StreamStarted(BaseCallbackHandler):
    run_inline = True

    def __init__(self):
        self.started = False

    def on_llm_new_token(self, token, **kwargs):
        # Even an empty/tool chunk may already have reached a stream consumer.
        self.started = True


def retryable(error, guard):
    return not guard.started and (
        isinstance(error, (APIConnectionError, httpx.TransportError))
        or isinstance(error, APIStatusError)
        and (error.status_code in {408, 429} or error.status_code >= 500)
    )


def routed_request(request, connection, guard, fallback=False):
    model = create_llm() if connection == "default" else create_llm(connection)
    return request.override(
        model=model.model_copy(
            update={
                "callbacks": [guard],
                "metadata": {"llm_connection": connection, "fallback_used": fallback},
            }
        )
    )


def annotate(response, connection, fallback):
    for message in response.result:
        message.additional_kwargs["llm_route"] = {
            "connection": connection,
            "model": (
                create_llm() if connection == "default" else create_llm(connection)
            ).model_name,
            "fallback_used": fallback,
        }
    return response


def log_fallback(settings, error):
    logger.warning(
        json.dumps(
            {
                "event": "LLM_FALLBACK",
                "hostname": socket.gethostname(),
                "primary": settings.primary,
                "fallback": settings.fallback,
                "error_type": type(error).__name__,
                "status_code": getattr(error, "status_code", None),
            }
        )
    )


class LLMFallbackMiddleware(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        context = request.runtime.context
        settings = LLMIntegration.model_validate(
            (context if isinstance(context, dict) else {}).get("llm_integration", {})
        )
        guard = StreamStarted()
        try:
            response = handler(routed_request(request, settings.primary, guard))
        except Exception as error:
            if not settings.fallback or not retryable(error, guard):
                raise
            log_fallback(settings, error)
            response = handler(
                routed_request(request, settings.fallback, StreamStarted(), True)
            )
            return annotate(response, settings.fallback, True)
        return annotate(response, settings.primary, False)

    async def awrap_model_call(self, request, handler):
        context = request.runtime.context
        settings = LLMIntegration.model_validate(
            (context if isinstance(context, dict) else {}).get("llm_integration", {})
        )
        guard = StreamStarted()
        try:
            response = await handler(routed_request(request, settings.primary, guard))
        except Exception as error:
            if not settings.fallback or not retryable(error, guard):
                raise
            log_fallback(settings, error)
            response = await handler(
                routed_request(request, settings.fallback, StreamStarted(), True)
            )
            return annotate(response, settings.fallback, True)
        return annotate(response, settings.primary, False)
