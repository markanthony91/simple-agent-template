from __future__ import annotations

import os

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt

from simple_agent.graph import calculator, utc_now
from simple_agent.prompt_loader import load_agent_prompt
from simple_agent.tool_middleware import filter_enabled_tools
from simple_agent.tools.okf_tools import OKF_TOOLS

DEFAULT_MODEL = os.getenv("SIMPLE_AGENT_MODEL", "openai:gpt-4.1-mini")


@dynamic_prompt
def runtime_prompt(request: ModelRequest) -> str:
    context = request.runtime.context
    configured = context.get("system_prompt") if isinstance(context, dict) else None
    if isinstance(configured, str) and configured.strip():
        return load_agent_prompt(system_prompt=configured)
    return load_agent_prompt()


ALL_TOOLS = [utc_now, calculator, *OKF_TOOLS]

graph = create_agent(
    model=DEFAULT_MODEL,
    tools=ALL_TOOLS,
    middleware=[runtime_prompt, filter_enabled_tools],
    name="simple_agent",
)
