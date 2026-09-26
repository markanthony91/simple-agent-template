"""Controlled provider-only comparison; no tool is executed and no session is created.

Requires the server's existing LLM configuration. Reads assistant instructions and
OKF documents; prints only aggregate timings. Forced tool choices isolate the cost
of one additional model round trip, not autonomous retrieval quality.
"""

import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from simple_agent.llm import create_llm
from simple_agent.prompt_loader import load_agent_prompt
from simple_agent.runtime_settings import AgentProfile
from simple_agent.services.okf_service import OKFService
from simple_agent.tools.payment_tools import generate_payment_offer


def measure(model, messages, tool_name, read_schema, settings):
    bound = model.bind_tools(
        [read_schema, generate_payment_offer], tool_choice=tool_name
    )
    start = time.perf_counter()
    first = None
    response = None
    for chunk in bound.stream(messages, **settings):
        if first is None and (chunk.content or chunk.tool_call_chunks):
            first = (time.perf_counter() - start) * 1000
        response = chunk if response is None else response + chunk
    elapsed = (time.perf_counter() - start) * 1000
    calls = response.tool_calls if response else []
    assert len(calls) == 1 and calls[0]["name"] == tool_name
    return response, {
        "tool": tool_name,
        "first_output_ms": round(first or elapsed, 2),
        "total_ms": round(elapsed, 2),
        "usage": response.usage_metadata,
    }


def main():
    url = "http://127.0.0.1:" + os.getenv("PORT", "2024")
    aid = "dd5766a7-2237-5e12-b949-7236c459698c"
    with urllib.request.urlopen(url + "/assistants/" + aid) as response:
        context = json.load(response)["context"]
    model = create_llm(context.get("llm_integration", {}).get("primary", "default"))
    prompt = load_agent_prompt(
        context["system_prompt"],
        context["agent_instructions"],
        context["active_workflow"],
    )
    prompt += AgentProfile.model_validate(
        context.get("agent_profile", {})
    ).instructions()
    data = Path(os.getenv("OKF_DATA_ROOT", "/data/okf"))
    bundle = json.loads((data / "active.json").read_text())["bundle_id"]
    service = OKFService(data / "bundles" / bundle)
    read_schema = {
        "name": "okf_read",
        "description": "Read a complete OKF policy previously located by search.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    }
    settings = {
        k: v
        for k, v in context.get("llm_settings", {}).items()
        if k in {"temperature", "top_p", "max_tokens"} and v is not None
    }
    results = []
    for repeat in range(3):
        for mode in (
            ["separate", "consolidated"]
            if repeat % 2 == 0
            else ["consolidated", "separate"]
        ):
            for modality, method, count, filename in [
                ("cash", "pix", 1, "politica-negociacao.md"),
                ("installment", "boleto", 3, "parcelamento.md"),
            ]:
                policy_path = (
                    "COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO/policies/"
                    + filename
                )
                body = service.read_file(policy_path)
                messages = [
                    SystemMessage(content=prompt),
                    HumanMessage(content="Quero negociar minha pendência."),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "verify_and_get_customer",
                                "args": {},
                                "id": "bench-identity",
                            }
                        ],
                    ),
                    ToolMessage(
                        tool_call_id="bench-identity",
                        content=json.dumps(
                            {
                                "verified": True,
                                "customer": {
                                    "institution": "will-bank",
                                    "product": "cartao_de_credito",
                                    "debt": {
                                        "current_amount": "1000.00",
                                        "days_overdue": 100,
                                    },
                                },
                            }
                        ),
                    ),
                    HumanMessage(
                        content="Quero pagar à vista por PIX."
                        if method == "pix"
                        else "Quero parcelar em 3 vezes no boleto."
                    ),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "okf_search",
                                "args": {
                                    "scope": "COMPANIES",
                                    "query": "will-bank cartao_de_credito " + modality,
                                },
                                "id": "bench-search",
                            }
                        ],
                    ),
                    ToolMessage(
                        tool_call_id="bench-search",
                        content=(
                            body
                            if mode == "consolidated"
                            else "OKF_CANONICAL_SCOPE: COMPANIES\n\n"
                            + policy_path
                            + ":1: Política aplicável à modalidade solicitada."
                        ),
                    ),
                ]
                steps = []
                if mode == "separate":
                    read, metric = measure(
                        model, messages, "okf_read", read_schema, settings
                    )
                    assert read.tool_calls[0]["args"]["path"] == policy_path
                    steps.append(metric)
                    messages.extend(
                        [
                            read,
                            ToolMessage(
                                tool_call_id=read.tool_calls[0]["id"], content=body
                            ),
                        ]
                    )
                offer, metric = measure(
                    model, messages, "generate_payment_offer", read_schema, settings
                )
                args = offer.tool_calls[0]["args"]
                correct = args == {
                    "payment_type": modality,
                    "method": method,
                    "installments": count,
                    "policy_path": policy_path,
                }
                assert correct, "Unexpected proposal arguments in controlled benchmark"
                steps.append(metric)
                record = {
                    "repeat": repeat,
                    "mode": mode,
                    "method": method,
                    "steps": steps,
                    "total_model_ms": round(sum(x["total_ms"] for x in steps), 2),
                    "correct_arguments": correct,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
                results.append(record)
                print(json.dumps({"progress": record}), flush=True)
    print(
        "RESULT "
        + json.dumps(
            {
                "model": model.model_name,
                "prompt_characters": len(prompt),
                "forced_tool_choices": True,
                "tool_executions": 0,
                "cases": results,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
