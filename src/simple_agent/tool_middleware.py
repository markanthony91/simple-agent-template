from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage

from simple_agent.services.tool_registry import ToolRegistry
from simple_agent.tool_observability import sanitize_result, sanitize_tool_args

registry = ToolRegistry()
logger = logging.getLogger("simple_agent.tools")

RECOVERABLE_TOOL_ERRORS = (FileNotFoundError, ValueError, KeyError, PermissionError)


def _meta(request: ToolCallRequest) -> tuple[str, str, dict]:
    call = request.tool_call
    name = str(call.get("name") or "unknown")
    call_id = str(call.get("id") or "")
    raw_args = call.get("args")
    args = raw_args if isinstance(raw_args, dict) else {}
    return name, call_id, sanitize_tool_args(name, args)


def _log_event(request: ToolCallRequest, status: str, duration_ms: float | None = None, result=None, error: Exception | None = None) -> None:
    name, call_id, args = _meta(request)
    payload = {"event": "TOOL_CALL", "tool": name, "tool_call_id": call_id, "status": status, "args": args}
    if duration_ms is not None:
        payload["duration_ms"] = round(duration_ms, 2)
    if result is not None:
        payload["result"] = sanitize_result(name, result)
    if error is not None:
        payload["error_type"] = type(error).__name__
        payload["error_message"] = str(error)[:300]
    logger.info(json.dumps(payload, ensure_ascii=False))


def _tool_error_message(request: ToolCallRequest, error: Exception) -> ToolMessage:
    call = request.tool_call
    name = str(call.get("name") or "unknown")
    call_id = str(call.get("id") or "")
    return ToolMessage(
        content=json.dumps({"ok": False, "error": "tool_execution_failed", "tool": name, "error_type": type(error).__name__, "message": str(error), "recoverable": True}, ensure_ascii=False),
        tool_call_id=call_id,
    )


class FilterEnabledToolsMiddleware(AgentMiddleware):
    """Filter runtime tools, observe calls, and recover from expected failures."""

    def _filtered_request(self, request: ModelRequest) -> ModelRequest:
        enabled = registry.enabled_names()
        tools = [tool for tool in request.tools if getattr(tool, "name", None) in enabled]
        return request.override(tools=tools)

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelResponse:
        return handler(self._filtered_request(request))

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelResponse:
        return await handler(self._filtered_request(request))

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        started = perf_counter()
        _log_event(request, "start")
        try:
            result = handler(request)
        except RECOVERABLE_TOOL_ERRORS as error:
            _log_event(request, "recoverable_error", (perf_counter() - started) * 1000, error=error)
            return _tool_error_message(request, error)
        _log_event(request, "success", (perf_counter() - started) * 1000, result=result)
        return result

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        started = perf_counter()
        _log_event(request, "start")
        try:
            result = await handler(request)
        except RECOVERABLE_TOOL_ERRORS as error:
            _log_event(request, "recoverable_error", (perf_counter() - started) * 1000, error=error)
            return _tool_error_message(request, error)
        _log_event(request, "success", (perf_counter() - started) * 1000, result=result)
        return result


filter_enabled_tools = FilterEnabledToolsMiddleware()
