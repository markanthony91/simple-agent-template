from types import SimpleNamespace

import httpx
import pytest
from langchain.agents.middleware import ModelResponse
from langchain_core.messages import AIMessage

from simple_agent.llm_control_plane import resolve_routes
from simple_agent.llm_fallback import LLMFallbackMiddleware


def test_resolves_scoped_routes_without_putting_credentials_in_response(monkeypatch):
    tenant = "00000000-0000-4000-8000-000000000001"
    assistant = "00000000-0000-4000-8000-000000000002"
    monkeypatch.setenv("CHANNELS_LLM_RESOLVER_URL", "https://channels.invalid")
    monkeypatch.setenv("CHANNELS_LLM_RESOLVER_TOKEN", "ab" * 32)
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, json={
            "scope_id": 2, "tenant_id": tenant, "assistant_id": assistant,
            "primary": {
                "integration_id": "00000000-0000-4000-8000-000000000003",
                "model": "synthetic-model", "base_url": "https://llm.invalid/v1",
                "api_key": "synthetic-secret", "proxy_url": None,
            },
            "fallback": None,
        })

    monkeypatch.setattr(httpx, "get", get)
    routes = resolve_routes({"portfolio_context": {"scope_id": 2, "tenant_id": tenant}}, assistant)
    assert calls[0][0] == "https://channels.invalid/api/runtime/v1/llm"
    assert calls[0][1]["params"]["scope_id"] == 2
    assert routes["primary"]["model"].model_name == "synthetic-model"
    assert "synthetic-secret" not in str(routes["primary"]["connection"])

    class Request:
        runtime = SimpleNamespace(context={"_runtime_llm_routes": routes})

        def override(self, **kwargs):
            return SimpleNamespace(**kwargs)

    response = LLMFallbackMiddleware().wrap_model_call(
        Request(), lambda request: ModelResponse(result=[AIMessage(content=request.model.model_name)])
    )
    assert response.result[0].additional_kwargs["llm_route"] == {
        "connection": routes["primary"]["connection"],
        "model": "synthetic-model", "fallback_used": False,
    }
    with pytest.raises(ValueError, match="invalid_portfolio_scope"):
        resolve_routes({"portfolio_context": {"scope_id": 1, "tenant_id": tenant}}, assistant)
