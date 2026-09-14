from __future__ import annotations

import os
from functools import lru_cache

import httpx
from langchain_openai import ChatOpenAI


@lru_cache(maxsize=1)
def create_llm() -> ChatOpenAI:
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model_name = os.getenv("LLM_MODEL") or os.getenv(
        "SIMPLE_AGENT_MODEL", ""
    ).removeprefix("openai:")
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not base_url or not model_name or not api_key:
        raise ValueError(
            "Configure LLM_BASE_URL, LLM_MODEL and LLM_API_KEY on the server"
        )
    proxy_url = os.getenv("LLM_PROXY_URL")

    timeout = httpx.Timeout(
        float(os.getenv("LLM_READ_TIMEOUT_SECONDS", "120")), connect=10
    )
    sync_client = httpx.Client(proxy=proxy_url or None, timeout=timeout)
    async_client = httpx.AsyncClient(proxy=proxy_url or None, timeout=timeout)

    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        http_client=sync_client,
        http_async_client=async_client,
        streaming=True,
        max_retries=0,
        timeout=timeout,
    )
