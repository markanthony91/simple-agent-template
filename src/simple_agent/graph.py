"""LangGraph agent runtime with dynamic prompts and OKF tools."""

from __future__ import annotations

import ast
import os
from datetime import datetime, timezone
from typing import Any, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain_core.tools import tool

from simple_agent.prompt_loader import load_agent_prompt
from simple_agent.tools.okf_tools import OKF_TOOLS

DEFAULT_MODEL = os.getenv("SIMPLE_AGENT_MODEL", "openai:gpt-4.1-mini")


class AgentContext(TypedDict, total=False):
    system_prompt: str


@tool
def utc_now() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(tz=timezone.utc).isoformat()


@tool
def calculator(expression: str) -> str:
    """Evaluate a simple arithmetic expression safely.

    Supported operators: +, -, *, /, %, ** and parentheses.
    """
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
def runtime_system_prompt(request: ModelRequest) -> str:
    """Use the assistant's configured system prompt, with bundled rules appended."""
    context = request.runtime.context or {}
    configured_prompt = context.get("system_prompt")
    return load_agent_prompt(system_prompt=configured_prompt)


TOOLS = [utc_now, calculator, *OKF_TOOLS]

graph = create_agent(
    model=DEFAULT_MODEL,
    tools=TOOLS,
    middleware=[runtime_system_prompt],
    context_schema=AgentContext,
    name="simple_agent",
)
