from __future__ import annotations


from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt

from simple_agent.graph import calculator, utc_now
from simple_agent.prompt_loader import load_agent_prompt
from simple_agent.tool_middleware import filter_enabled_tools
from simple_agent.tools.okf_tools import OKF_TOOLS
from simple_agent.tools.collection_tools import COLLECTION_TOOLS
from simple_agent.llm import create_llm
from simple_agent.runtime_settings import AgentProfile


@dynamic_prompt
def runtime_prompt(request: ModelRequest) -> str:
    context = request.runtime.context
    configured = context if isinstance(context, dict) else {}
    system_prompt = configured.get("system_prompt")
    agent_instructions = configured.get("agent_instructions")
    active_workflow = configured.get("active_workflow")

    return (
        load_agent_prompt(
            system_prompt=system_prompt if isinstance(system_prompt, str) else None,
            agent_instructions=agent_instructions
            if isinstance(agent_instructions, str)
            else None,
            workflow=active_workflow if isinstance(active_workflow, str) else None,
        )
        + AgentProfile.model_validate(
            configured.get("agent_profile", {})
        ).instructions()
    )


ALL_TOOLS = [utc_now, calculator, *OKF_TOOLS, *COLLECTION_TOOLS]

graph = create_agent(
    model=create_llm(),
    tools=ALL_TOOLS,
    middleware=[runtime_prompt, filter_enabled_tools],
    name="simple_agent",
)
