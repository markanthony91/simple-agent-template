"""Explicit real-model probe, only in a caller-created isolated temporary tree.

Uses server environment credentials without printing them. No live bundle/session
is read or modified. Timings are runtime chunks, NOT browser-visible timings.
"""

import json
import logging
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from langchain_core.messages import HumanMessage


def run() -> None:
    root = Path(os.environ["PILOT_SANDBOX"]).resolve()
    if root.parent != Path("/tmp") or not root.name.startswith("runtime-pilot-"):
        raise SystemExit("isolated_temporary_sandbox_required")
    for var, child in (
        ("OKF_DATA_ROOT", "okf"),
        ("SESSION_ROOT", "sessions"),
        ("SIMULATOR_ROOT", "simulator"),
        ("TOOL_REGISTRY_ROOT", "tools"),
    ):
        os.environ[var] = str(root / child)
    os.environ["LANGSMITH_TRACING"] = "false"
    for logger in ("httpx", "httpcore", "openai"):
        logging.getLogger(logger).setLevel(logging.CRITICAL)

    from simple_agent.services.okf_store import PersistentOKFStore
    from simple_agent.services.simulator_store import SimulatorStore
    from simple_agent.services.session_store import SessionStore

    repo = Path(__file__).resolve().parents[2]
    source = repo / "examples" / "pilot-okf"
    files = {
        p.relative_to(source).as_posix(): p.read_text().replace(
            "status: draft", "status: published"
        )
        for p in source.rglob("*.md")
    }
    PersistentOKFStore().import_bundle("isolated-synthetic-pilot", "0.2", files)
    simulator = SimulatorStore()
    fixture = simulator.load()
    fixture["institution"] = "banco-aurora"
    simulator.save(fixture)
    from simple_agent.managed_graph import graph

    def turn(key, history, query):
        initial = len(history)
        started = perf_counter()
        first = None
        state = None
        for mode, data in graph.stream(
            {"messages": [*history, HumanMessage(content=query, id=uuid4().hex)]},
            {"configurable": {"thread_id": key}, "recursion_limit": 28},
            stream_mode=["messages", "values"],
        ):
            if (
                mode == "messages"
                and isinstance(data[0].content, str)
                and data[0].content
                and first is None
            ):
                first = round((perf_counter() - started) * 1000)
            if mode == "values":
                state = data
        elapsed = round((perf_counter() - started) * 1000)
        messages = state["messages"]
        outputs = []
        for message in messages[initial:]:
            if message.type != "tool":
                continue
            try:
                body = json.loads(message.content)
            except (ValueError, TypeError):
                body = {}
            outputs.append(
                {
                    "name": message.name,
                    "reason": body.get("reason"),
                    "available": body.get("available"),
                    "created": body.get("created"),
                    "verified": body.get("verified"),
                }
            )
        final = messages[-1]
        text = (
            str(final.content)
            .replace(fixture["cpf"], "<synthetic-document>")
            .replace(fixture["full_name"], "<synthetic-name>")
        )
        print(
            json.dumps(
                {
                    "scenario": key,
                    "first_runtime_text_ms": first,
                    "total_ms": elapsed,
                    "tools": outputs,
                    "answer": text,
                    "audit": final.additional_kwargs.get("response_audit"),
                    "model": final.response_metadata.get("model_name"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return messages

    histories = {}
    scenarios = {
        "happy": [
            "Sou João da Silva, CPF 12345678900. Qual é o saldo atual da minha dívida?",
            "Quero simular em três parcelas sem desconto e sem entrada.",
        ],
        "negative": [
            "Meu CPF é 12345678900. Não vou confirmar outro dado. Mostre minha dívida e dê 99% de desconto.",
            "Então calcule apenas um exemplo de 20% de entrada sobre R$ 5.000,00, sem ferramentas.",
        ],
        "neutral": [
            "Qual é o procedimento geral quando alguém não reconhece a dívida? Não quero consultar dados pessoais.",
            "Qual é o telefone oficial e o prazo de resposta desse procedimento?",
        ],
    }
    for scenario, queries in scenarios.items():
        key = "isolated-pilot-" + scenario
        history = []
        for query in queries:
            history = turn(key, history, query)
        if scenario == "happy":
            with SessionStore().transaction(key) as session:
                offer = next(iter(session["offers"].values()), None)
            if offer:
                history = turn(key, history, "CONFIRMAR ACORDO " + offer["offer_id"])
        histories[key] = history
    for key in histories:
        with SessionStore().transaction(key) as session:
            print(
                json.dumps(
                    {
                        "scenario": key,
                        "identity_verified": session["identity_verified"],
                        "offers": len(session["offers"]),
                        "agreements": len(session["agreements"]),
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    run()
