from __future__ import annotations

from typing import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from simple_agent.services.tool_registry import ToolRegistry

registry = ToolRegistry()


class FilterEnabledToolsMiddleware(AgentMiddleware):
    """Middleware to filter tools by enabled status, supporting both sync and async contexts."""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Synchronous wrapper for model calls."""
        enabled = registry.enabled_names()
        tools = [tool for tool in request.tools if getattr(tool, "name", None) in enabled]
        return handler(request.override(tools=tools))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Asynchronous wrapper for model calls."""
        enabled = registry.enabled_names()
        tools = [tool for tool in request.tools if getattr(tool, "name", None) in enabled]
        return await handler(request.override(tools=tools))


filter_enabled_tools = FilterEnabledToolsMiddleware()

