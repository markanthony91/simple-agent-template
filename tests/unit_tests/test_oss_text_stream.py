from contextlib import nullcontext

from langchain_core.messages import AIMessageChunk, ToolMessage

from simple_agent import oss_runtime
from simple_agent.oss_runtime import _assistant_text_event


def test_only_assistant_text_leaves_runtime_stream():
    chunk = AIMessageChunk(content="Resposta ", tool_call_chunks=[{"name": "private"}])
    assert _assistant_text_event((chunk, {"private": "metadata"})) == [
        {"type": "ai", "content": "Resposta "},
        {},
    ]
    assert _assistant_text_event(
        (
            AIMessageChunk(
                content=[
                    {"type": "text", "text": "final"},
                    {"type": "image", "url": "private"},
                ]
            ),
            {},
        )
    ) == [{"type": "ai", "content": "final"}, {}]
    assert (
        _assistant_text_event((ToolMessage(content="private", tool_call_id="1"), {}))
        is None
    )
    assert _assistant_text_event((AIMessageChunk(content=""), {})) is None


def test_oss_graph_requests_messages_and_final_values(monkeypatch):
    class Graph:
        def stream(self, _input, _config, *, stream_mode, **_kwargs):
            assert stream_mode == ["messages", "values"]
            yield "messages", (AIMessageChunk(content="oi"), {})
            yield "values", {"messages": []}

    monkeypatch.setattr(oss_runtime, "_db", lambda: nullcontext(object()))
    monkeypatch.setattr(
        oss_runtime,
        "_assistant",
        lambda _db, _id: {
            "graph_id": "agent",
            "assistant_id": "synthetic",
            "config": {},
            "context": {},
        },
    )
    monkeypatch.setattr(oss_runtime, "GRAPHS", {"agent": Graph()})
    monkeypatch.delenv("CHANNELS_LLM_CONTROL_ENABLED", raising=False)
    assert [kind for kind, _ in oss_runtime._run("synthetic", {}, stream=True)] == [
        "messages",
        "values",
    ]
