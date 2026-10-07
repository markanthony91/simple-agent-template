"""Resolve Homologation LLM routes from the private Channels control plane."""

from __future__ import annotations

import os
from uuid import UUID

import httpx

from simple_agent.llm import create_configured_llm


def resolve_routes(context: dict, assistant_id: str) -> dict:
    portfolio = context.get("portfolio_context")
    if not isinstance(portfolio, dict):
        raise ValueError("portfolio_context_required")
    scope_id = portfolio.get("scope_id")
    tenant_id = portfolio.get("tenant_id")
    if isinstance(scope_id, str) and scope_id.isdigit():
        scope_id = int(scope_id)
    if type(scope_id) is not int or scope_id <= 1:
        raise ValueError("invalid_portfolio_scope")
    try:
        UUID(tenant_id)
        UUID(assistant_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_portfolio_identity") from exc
    url = os.getenv("CHANNELS_LLM_RESOLVER_URL", "").rstrip("/")
    token = os.getenv("CHANNELS_LLM_RESOLVER_TOKEN", "")
    if not url.startswith("https://") or len(token) != 64:
        raise ValueError("llm_resolver_not_configured")
    response = httpx.get(
        url + "/api/runtime/v1/llm",
        params={
            "scope_id": scope_id,
            "tenant_id": tenant_id,
            "assistant_id": assistant_id,
        },
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=5,
        follow_redirects=False,
    )
    response.raise_for_status()
    if len(response.content) > 8192:
        raise ValueError("llm_resolver_response_too_large")
    value = response.json()
    if (
        value.get("scope_id"),
        value.get("tenant_id"),
        value.get("assistant_id"),
    ) != (scope_id, tenant_id, assistant_id):
        raise ValueError("llm_resolver_scope_mismatch")

    def route(item):
        if not isinstance(item, dict) or not isinstance(item.get("model"), str):
            raise ValueError("invalid_resolved_llm")
        return {
            "connection": item["integration_id"],
            "model": create_configured_llm(
                item["base_url"],
                item["model"],
                item["api_key"],
                item.get("proxy_url") or "",
            ),
        }

    return {
        "primary": route(value.get("primary")),
        "fallback": route(value["fallback"]) if value.get("fallback") else None,
    }
