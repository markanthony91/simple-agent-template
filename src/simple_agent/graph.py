"""LangGraph agent runtime with external prompts and OKF tools."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain_core.tools import tool

from simple_agent.prompt_loader import load_agent_prompt
from simple_agent.tools.okf_tools import OKF_TOOLS
from simple_agent.llm import create_llm


@tool
def utc_now() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(tz=timezone.utc).isoformat()


@tool
def calculator(expression: str) -> str:
    """Evaluate a simple arithmetic expression safely."""
    parsed = ast.parse(expression, mode="eval")
    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Load,
    )
    for node in ast.walk(parsed):
        if not isinstance(node, allowed_nodes):
            raise ValueError("Expression contains unsupported syntax")
    result: Any = eval(
        compile(parsed, "<calculator>", "eval"),
        {"__builtins__": {}},
        {},
    )
    return str(result)


@dynamic_prompt
def runtime_prompt(request: ModelRequest) -> str:
    """Use Assistant context system_prompt when configured, preserving operational rules."""
    context = request.runtime.context
    configured = None
    if isinstance(context, dict):
        configured = context.get("system_prompt")
    if isinstance(configured, str) and configured.strip():
        return load_agent_prompt(system_prompt=configured)
    return load_agent_prompt()


TOOLS = [utc_now, calculator, *OKF_TOOLS]

graph = create_agent(
    model=create_llm(),
    tools=TOOLS,
    middleware=[runtime_prompt],
    name="simple_agent",
)
