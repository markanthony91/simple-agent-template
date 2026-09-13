from __future__ import annotations

import os

import httpx
from langchain_openai import ChatOpenAI


def create_llm() -> ChatOpenAI:
    base_url = os.environ["LLM_BASE_URL"]
    model_name = os.environ["LLM_MODEL"]
    api_key = os.getenv("LLM_API_KEY", "dummy")
    proxy_url = os.getenv("LLM_PROXY_URL")

    sync_client = httpx.Client(proxy=proxy_url or None, timeout=60.0)
    async_client = httpx.AsyncClient(proxy=proxy_url or None, timeout=60.0)

    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        http_client=sync_client,
        http_async_client=async_client,
        streaming=True,
    )
