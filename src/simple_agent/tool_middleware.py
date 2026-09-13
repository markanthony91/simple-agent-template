from __future__ import annotations

from typing import Callable

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call

from simple_agent.services.tool_registry import ToolRegistry

registry = ToolRegistry()


@wrap_model_call
def filter_enabled_tools(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    enabled = registry.enabled_names()
    tools = [tool for tool in request.tools if getattr(tool, "name", None) in enabled]
    return handler(request.override(tools=tools))
