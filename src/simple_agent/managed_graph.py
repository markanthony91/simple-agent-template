from __future__ import annotations

import os

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt

from simple_agent.graph import calculator, utc_now
from simple_agent.prompt_loader import load_agent_prompt
from simple_agent.tool_middleware import filter_enabled_tools, general_query_identity_guard
from simple_agent.tools.okf_tools import OKF_TOOLS
from simple_agent.tools.collection_tools import COLLECTION_TOOLS

DEFAULT_MODEL = os.getenv("SIMPLE_AGENT_MODEL", "openai:gpt-4.1-mini")


@dynamic_prompt
def runtime_prompt(request: ModelRequest) -> str:
    context = request.runtime.context
    configured = context if isinstance(context, dict) else {}
    system_prompt = configured.get("system_prompt")
    agent_instructions = configured.get("agent_instructions")
    active_workflow = configured.get("active_workflow")

    return load_agent_prompt(
        system_prompt=system_prompt if isinstance(system_prompt, str) else None,
        agent_instructions=agent_instructions if isinstance(agent_instructions, str) else None,
        workflow=active_workflow if isinstance(active_workflow, str) else None,
    )


ALL_TOOLS = [utc_now, calculator, *OKF_TOOLS, *COLLECTION_TOOLS]

graph = create_agent(
    model=DEFAULT_MODEL,
    tools=ALL_TOOLS,
    middleware=[runtime_prompt, filter_enabled_tools, general_query_identity_guard],
    name="simple_agent",
)
