import pytest

from simple_agent.startup import prepare
from simple_agent.llm import create_llm


def test_checkpoint_directory_is_persistent_and_idempotent(tmp_path):
    work = tmp_path / "app"
    data = tmp_path / "data"
    work.mkdir()
    prepare(work, data)
    prepare(work, data)
    assert (work / ".langgraph_api").resolve() == (data / "langgraph").resolve()
    (data / "langgraph" / "checkpoint").write_text("survives")
    assert (work / ".langgraph_api" / "checkpoint").read_text() == "survives"


def test_never_overwrite_existing_checkpoints(tmp_path):
    (tmp_path / ".langgraph_api").mkdir()
    with pytest.raises(RuntimeError):
        prepare(tmp_path, tmp_path / "data")


def test_llm_config_is_shared(monkeypatch):
    create_llm.cache_clear()
    monkeypatch.setenv("LLM_MODEL", "synthetic-canonical")
    monkeypatch.setenv("SIMPLE_AGENT_MODEL", "wrong-legacy")
    model = create_llm()
    assert model.model_name == "synthetic-canonical"
    assert create_llm() is model
    assert model.streaming is True
    create_llm.cache_clear()


def test_request_config_cannot_replace_server_model(monkeypatch):
    import json
    import httpx

    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "server-pinned",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ok"},
                    }
                ],
            },
        )

    monkeypatch.setattr(
        httpx.Client, "send", lambda self, request, **kwargs: respond(request)
    )
    monkeypatch.setenv("LLM_MODEL", "server-pinned")
    create_llm.cache_clear()
    try:
        model = create_llm()
        model.streaming = False
        result = model.invoke(
            "hello",
            config={
                "configurable": {
                    "model": "client-override",
                    "model_name": "client-override",
                }
            },
        )
        assert result.content == "ok"
        assert calls[0]["model"] == "server-pinned"
    finally:
        create_llm.cache_clear()
