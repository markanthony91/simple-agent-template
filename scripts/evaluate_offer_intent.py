# ruff: noqa: E402
# Environment isolation must precede importing runtime services.
"""Opt-in provider evaluation: synthetic messages; never executes a tool or writes a session.

Run with the existing server LLM environment. Fetches assistant instructions read-only.
Compares the previous and current tool contract with automatic (not forced) tool choice.
Only aggregate case outcomes and timings are printed; no prompts or credentials.
"""

import ast
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
_sandbox = tempfile.TemporaryDirectory(prefix="offer-intent-eval-")
for name in ("OKF_DATA_ROOT", "SESSION_ROOT", "SIMULATOR_ROOT", "TOOL_REGISTRY_ROOT"):
    os.environ[name] = str(Path(_sandbox.name) / name)

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from simple_agent.llm import create_llm
from simple_agent.prompt_loader import load_agent_prompt
from simple_agent.tools.payment_tools import generate_payment_offer

PATH = "INSTITUTIONS/will_bank/cartao_de_credito/negotiation.md"
CASES = [
    ("together", ["Quero em 3 parcelas no boleto"], ("installment", "boleto", 3)),
    (
        "method_later",
        [
            "Quero em 3 parcelas",
            ("ai", "O parcelamento é por boleto. Podemos seguir?"),
            "Boleto",
        ],
        ("installment", "boleto", 3),
    ),
    (
        "confirm_sim",
        [("ai", "Seguimos em 3 parcelas no boleto?"), "Sim"],
        ("installment", "boleto", 3),
    ),
    (
        "confirm_emitir",
        [("ai", "Seguimos em 3 parcelas no boleto?"), "Pode emitir"],
        ("installment", "boleto", 3),
    ),
    (
        "changed_count",
        [
            "Quero em 3 parcelas",
            ("ai", "Seguimos em 3 parcelas no boleto?"),
            "Melhor em 2 parcelas",
        ],
        ("installment", "boleto", 2),
    ),
    (
        "pix_later",
        ["Quero à vista", ("ai", "Prefere PIX ou boleto?"), "PIX"],
        ("cash", "pix", 1),
    ),
    (
        "refusal",
        [("ai", "Seguimos em 3 parcelas no boleto?"), "Não quero em 3 parcelas"],
        None,
    ),
    (
        "cancel",
        [
            "Quero em 3 parcelas no boleto",
            ("ai", "Vou preparar a proposta."),
            "Esquece, não quero negociar agora",
        ],
        None,
    ),
    (
        "question",
        ["Posso parcelar em 3 vezes? Só quero saber, não gere nada ainda."],
        None,
    ),
    ("missing_count", ["Quero parcelar, mas ainda não sei em quantas vezes"], None),
]


def main():
    base = "https://langgraph-simple-agent-clean-production.up.railway.app"
    with urllib.request.urlopen(
        base + "/assistants/dd5766a7-2237-5e12-b949-7236c459698c", timeout=20
    ) as response:
        context = json.load(response)["context"]
    model = create_llm(context.get("llm_integration", {}).get("primary", "default"))
    prompt = load_agent_prompt(
        context["system_prompt"],
        context["agent_instructions"],
        context["active_workflow"],
    )
    old_source = subprocess.check_output(
        ["git", "show", "4232d55:src/simple_agent/tools/payment_tools.py"], text=True
    )
    old_doc = next(
        ast.get_docstring(node)
        for node in ast.parse(old_source).body
        if isinstance(node, ast.FunctionDef) and node.name == "generate_payment_offer"
    )
    before = convert_to_openai_tool(generate_payment_offer)
    before["function"]["description"] = old_doc
    before["function"]["parameters"]["properties"]["installments"] = {
        "type": "integer",
        "default": 1,
    }
    policy = (
        Path("examples/pilot-okf/" + PATH)
        .read_text()
        .replace("status: draft", "status: published")
    )
    prefix = [
        SystemMessage(content=prompt),
        HumanMessage(content="Quero negociar minha pendência."),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "verify_and_get_customer",
                    "args": {"cpf": "123"},
                    "id": "identity",
                }
            ],
        ),
        ToolMessage(
            tool_call_id="identity",
            content=json.dumps(
                {
                    "verified": True,
                    "customer": {
                        "full_name": "Cliente Teste",
                        "institution": "Will Bank",
                        "product": "cartao_de_credito",
                        "debt": {"current_amount": "1000.00"},
                    },
                }
            ),
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "okf_read", "args": {"path": PATH}, "id": "policy"}],
        ),
        ToolMessage(
            tool_call_id="policy", content="OKF_CANONICAL_PATH: " + PATH + "\n" + policy
        ),
    ]
    passed = {}
    for mode, tool in [("before", before), ("after", generate_payment_offer)]:
        bound = model.bind_tools([tool])
        passed[mode] = 0
        for name, turns, expected in CASES:
            messages = prefix + [
                (
                    AIMessage(content=t[1])
                    if isinstance(t, tuple)
                    else HumanMessage(content=t)
                )
                for t in turns
            ]
            start = time.perf_counter()
            result = bound.invoke(messages)
            calls = result.tool_calls
            if expected is None:
                correct = not calls
            else:
                correct = (
                    len(calls) == 1 and calls[0]["name"] == "generate_payment_offer"
                )
                if correct:
                    args = calls[0]["args"]
                    correct = (
                        args.get("payment_type"),
                        args.get("method"),
                        args.get("installments", 1),
                    ) == expected and args.get("policy_path") == PATH
            passed[mode] += int(correct)
            print(
                json.dumps(
                    {
                        "mode": mode,
                        "case": name,
                        "passed": correct,
                        "tool_calls": len(calls),
                        "ms": round((time.perf_counter() - start) * 1000),
                    }
                ),
                flush=True,
            )
    print(
        json.dumps(
            {
                "passed": passed,
                "cases_per_mode": len(CASES),
                "tool_executions": 0,
                "production_writes": 0,
                "model": model.model_name,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
