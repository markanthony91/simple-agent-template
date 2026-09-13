from __future__ import annotations

from typing import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from simple_agent.services.tool_registry import ToolRegistry

registry = ToolRegistry()


class FilterEnabledToolsMiddleware(AgentMiddleware):
    """Filter runtime tools by registry state in both sync and async executions."""

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


filter_enabled_tools = FilterEnabledToolsMiddleware()
