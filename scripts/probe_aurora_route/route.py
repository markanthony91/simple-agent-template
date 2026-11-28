"""Measure two synthetic agent turns in a separate Homologation Runtime process."""

import copy
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from simple_agent import oss_runtime as rt

logging.disable(logging.CRITICAL)
assistant_id = "a16e3888-891f-4c5e-8cdc-7d5d08321aca"
assert os.getenv("CHANNELS_LLM_CONTROL_ENABLED") == "true"
with rt._db() as db:
    db.execute("SET TRANSACTION READ ONLY")
    assistant = rt._assistant(db, assistant_id)
context = dict(assistant["context"])
assert str(context["portfolio_context"]["scope_id"]) == "7"
assert assistant["graph_id"] == "agent"
allowed = {"okf_index", "okf_search", "okf_list", "okf_read", "okf_read_section"}
context["allowed_tools"] = sorted(set(context["allowed_tools"]) & allowed)
graph = copy.copy(rt.GRAPHS["agent"])
graph.checkpointer = InMemorySaver()
out = {"at": datetime.now(timezone.utc).isoformat(), "scope": 7, "turns": []}
start = perf_counter()
routes = rt.resolve_routes(context, assistant_id)
out["resolve_ms"] = round((perf_counter() - start) * 1000)
context["_runtime_llm_routes"] = routes
out["model"] = routes["primary"]["model"].model_name
out["fallback"] = (
    routes["fallback"]["model"].model_name if routes.get("fallback") else None
)
base = urlsplit(str(routes["primary"]["model"].openai_api_base))
out["primary_bridge"] = (
    base.hostname.endswith(".supabase.co") and "/llm-bridge" in base.path
)
calls = []


def correlation(value):
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def request_hook(request):
    if len(calls) >= 6:
        raise RuntimeError("probe_call_limit")
    assert request.url.path.endswith("/chat/completions")
    body = json.loads(request.content)
    assert all(
        tool.get("function", {}).get("name") in allowed
        for tool in body.get("tools", [])
    )
    calls.append(
        {
            "model": body.get("model"),
            "since_turn_ms": round((perf_counter() - start) * 1000),
        }
    )
    request.extensions["probe_index"] = len(calls) - 1


def response_hook(response):
    call = calls[response.request.extensions["probe_index"]]
    now_ms = round((perf_counter() - start) * 1000)
    call.update(status=response.status_code, headers_ms=now_ms - call["since_turn_ms"])
    call["quota"] = {
        k: v
        for k, v in response.headers.items()
        if re.fullmatch(r"(?:x-)?rate-?limit[-\w]*|retry-after", k)
        and re.fullmatch(r"[\w.: ,;+=/-]{1,120}", v)
    }
    call["correlation_hash"] = {
        k: correlation(v)
        for k, v in response.headers.items()
        if k in {"x-request-id", "sb-request-id", "x-correlation-id", "cf-ray"}
    }


for route in (value for value in routes.values() if value):
    client = route["model"].http_client
    client.event_hooks["request"].append(request_hook)
    client.event_hooks["response"].append(response_hook)

for label, prompt in [
    (
        "saudacao",
        "Olá, estou testando este atendimento. Pode me cumprimentar em uma frase?",
    ),
    (
        "faq_publica",
        "Qual é o prazo da Consulta Lume na política pública da Aurora Sintética? Quero apenas a informação, sem atendimento de conta.",
    ),
]:
    thread = str(uuid4())
    start = perf_counter()
    offset = len(calls)
    row = {"case": label, "thread_hash": correlation(thread), "first_text_ms": None}
    out["turns"].append(row)
    try:
        config = {
            **(assistant.get("config") or {}),
            "configurable": {"thread_id": thread},
        }
        final = None
        for mode, value in graph.stream(
            {"messages": [{"type": "human", "content": prompt}]},
            config,
            context=context,
            stream_mode=["messages", "values"],
        ):
            if mode == "messages" and row["first_text_ms"] is None:
                text = rt._assistant_text_event(value)
                if text and text[0]["content"].strip():
                    row["first_text_ms"] = round((perf_counter() - start) * 1000)
            if mode == "values":
                final = value
        messages = final["messages"]
        row["tool_calls"] = [
            call["name"]
            for msg in messages
            if msg.type == "ai"
            for call in msg.tool_calls
        ]
        row["tool_results"] = [msg.name for msg in messages if msg.type == "tool"]
        assert set(row["tool_calls"]) <= allowed
        last = messages[-1]
        row["finished_with_text"] = (
            last.type == "ai" and bool(last.content) and not last.tool_calls
        )
        row["answer_chars"] = len(str(last.content)) if row["finished_with_text"] else 0
        row["observed_models"] = sorted(
            {
                msg.additional_kwargs.get("llm_route", {}).get("model")
                for msg in messages
                if msg.type == "ai"
            }
            - {None}
        )
    except Exception as e:
        row["error_type"] = type(e).__name__
    row["total_ms"] = round((perf_counter() - start) * 1000)
    row["provider_calls"] = calls[offset:]
    if row.get("error_type") or not row.get("finished_with_text"):
        break
print("SAFE " + json.dumps(out))
