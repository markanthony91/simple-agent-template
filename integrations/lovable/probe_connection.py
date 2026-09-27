"""Explicit live, synthetic connection check; never update an Assistant or fallback."""

import asyncio
import json
import os
import socket
import tempfile

from langchain_core.callbacks import BaseCallbackHandler


class PromptCheck(BaseCallbackHandler):
    def __init__(self):
        self.calls = []

    def on_chat_model_start(self, serialized, messages, **kwargs):
        system = str(messages[0][0].content)
        params = kwargs.get("invocation_params", {})
        self.calls.append(
            {
                "all_layers": all(
                    marker in system
                    for marker in (
                        "SYSTEM_PROBE",
                        "AGENTS_PROBE",
                        "WORKFLOW_PROBE",
                        "BridgeProbe",
                    )
                ),
                "temperature_zero": params.get("temperature") == 0,
            }
        )


async def main():
    # Persistent business/identity state is isolated even though the provider is live.
    with tempfile.TemporaryDirectory(prefix="lovable-connection-probe-") as temporary:
        os.environ["SESSION_ROOT"] = temporary
        os.environ["LANGSMITH_TRACING"] = "false"
        from langchain.agents import create_agent
        from simple_agent.graph import utc_now
        from simple_agent.llm import create_llm
        from simple_agent.llm_fallback import LLMFallbackMiddleware
        from simple_agent.managed_graph import runtime_prompt
        from simple_agent.tool_middleware import filter_enabled_tools

        graph = create_agent(
            model=create_llm("lovable"),
            tools=[utc_now],
            middleware=[runtime_prompt, filter_enabled_tools, LLMFallbackMiddleware()],
        )
        check = PromptCheck()
        context = {
            "system_prompt": "SYSTEM_PROBE: Synthetic connection test. Call utc_now once when asked the current time and then answer briefly in English. No customer/business operations.",
            "agent_instructions": "AGENTS_PROBE: Only utc_now is available in this test.",
            "active_workflow": "WORKFLOW_PROBE: Read the time, then give a short final answer.",
            "agent_profile": {"name": "BridgeProbe"},
            "llm_settings": {"temperature": 0, "max_tokens": 2048},
            "llm_integration": {"primary": "lovable"},
        }
        result = await graph.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "What is the current UTC time? Use utc_now exactly once.",
                    }
                ]
            },
            {
                "configurable": {"thread_id": "synthetic-bridge-probe"},
                "callbacks": [check],
            },
            context=context,
        )
        messages = result["messages"]
        tool_messages = [m for m in messages if m.type == "tool"]
        final = messages[-1]
        assert len(tool_messages) == 1 and tool_messages[0].name == "utc_now"
        assert final.type == "ai" and final.content and not final.tool_calls
        assert final.response_metadata.get("finish_reason") == "stop"
        assert len(check.calls) == 2 and all(all(call.values()) for call in check.calls)
        route = final.additional_kwargs["llm_route"]
        assert route["connection"] == "lovable" and not route["fallback_used"]
        print(
            json.dumps(
                {
                    "hostname": socket.gethostname(),
                    "ok": True,
                    "configured_model": route["model"],
                    "reported_model": final.response_metadata.get("model_name"),
                    "model_calls": len(check.calls),
                    "tool_calls": len(tool_messages),
                    "prompt_layers_present": True,
                    "temperature_zero": True,
                    "fallback_enabled": False,
                    "persistent_assistant_changed": False,
                }
            )
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(error).__name__,
                    "status": getattr(error, "status_code", None),
                }
            )
        )
        raise SystemExit(1) from None
