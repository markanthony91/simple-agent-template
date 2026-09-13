from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage

from simple_agent.services.tool_registry import ToolRegistry

registry = ToolRegistry()
logger = logging.getLogger("simple_agent.tools")

RECOVERABLE_TOOL_ERRORS = (FileNotFoundError, ValueError, KeyError, PermissionError)


def _tool_error_message(request: ToolCallRequest, error: Exception) -> ToolMessage:
    tool_call = request.tool_call
    tool_name = str(tool_call.get("name") or "unknown")
    tool_call_id = str(tool_call.get("id") or "")
    logger.warning(
        "TOOL_RECOVERABLE_ERROR name=%s type=%s message=%s",
        tool_name,
        type(error).__name__,
        str(error),
    )
    return ToolMessage(
        content=json.dumps(
            {
                "ok": False,
                "error": "tool_execution_failed",
                "tool": tool_name,
                "error_type": type(error).__name__,
                "message": str(error),
                "recoverable": True,
            },
            ensure_ascii=False,
        ),
        tool_call_id=tool_call_id,
    )


class FilterEnabledToolsMiddleware(AgentMiddleware):
    """Filter runtime tools and convert recoverable tool failures into tool results."""

    def _filtered_request(self, request: ModelRequest) -> ModelRequest:
        enabled = registry.enabled_names()
        tools = [tool for tool in request.tools if getattr(tool, "name", None) in enabled]
        return request.override(tools=tools)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._filtered_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._filtered_request(request))

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        try:
            return handler(request)
        except RECOVERABLE_TOOL_ERRORS as error:
            return _tool_error_message(request, error)

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        try:
            return await handler(request)
        except RECOVERABLE_TOOL_ERRORS as error:
            return _tool_error_message(request, error)


filter_enabled_tools = FilterEnabledToolsMiddleware()
