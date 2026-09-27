from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlsplit

import httpx
from langchain_openai import ChatOpenAI

CONNECTIONS = {
    "default": "Servidor principal",
    "lovable": "Lovable (Gemini ou GPT)",
    "external": "Outro endpoint OpenAI-compatible",
}


def connection_config(connection: str = "default") -> dict:
    if connection not in CONNECTIONS:
        raise ValueError("Conexão LLM desconhecida")
    prefix = "LLM_" if connection == "default" else f"LLM_{connection.upper()}_"
    config = {
        "base_url": os.getenv(prefix + "BASE_URL", ""),
        "model": os.getenv(prefix + "MODEL", ""),
        "api_key": os.getenv(prefix + "API_KEY", ""),
        "proxy_url": os.getenv(prefix + "PROXY_URL", ""),
        "timeout": float(os.getenv(prefix + "READ_TIMEOUT_SECONDS", "120")),
    }
    if connection == "default":
        config["base_url"] = config["base_url"] or os.getenv("OPENAI_BASE_URL", "")
        config["model"] = config["model"] or os.getenv(
            "SIMPLE_AGENT_MODEL", ""
        ).removeprefix("openai:")
        config["api_key"] = config["api_key"] or os.getenv("OPENAI_API_KEY", "")
    return config


def connection_info(connection: str) -> dict:
    config = connection_config(connection)
    url = urlsplit(config["base_url"])
    # Never expose userinfo, query strings or fragments in the admin graph.
    endpoint = f"{url.scheme}://{url.hostname}" if url.hostname else ""
    if endpoint and url.port:
        endpoint += f":{url.port}"
    if endpoint:
        endpoint += url.path
    return {
        "id": connection,
        "label": CONNECTIONS[connection],
        "endpoint": endpoint,
        "model": config["model"],
        "configured": bool(
            all(config[key] for key in ("base_url", "model", "api_key"))
            and url.hostname
            and url.scheme in {"https", "http"}
        ),
        "credential_configured": bool(config["api_key"]),
        "proxy_enabled": bool(config["proxy_url"]),
        "timeout_seconds": config["timeout"],
    }


@lru_cache(maxsize=3)
def create_llm(connection: str = "default") -> ChatOpenAI:
    config = connection_config(connection)
    if not all(config[key] for key in ("base_url", "model", "api_key")):
        raise ValueError(
            f"Configure endpoint, modelo e credencial da conexão {connection} no servidor"
        )
    timeout = httpx.Timeout(config["timeout"], connect=10)
    return ChatOpenAI(
        model=config["model"],
        base_url=config["base_url"],
        api_key=config["api_key"],
        http_client=httpx.Client(proxy=config["proxy_url"] or None, timeout=timeout),
        http_async_client=httpx.AsyncClient(
            proxy=config["proxy_url"] or None, timeout=timeout
        ),
        streaming=True,
        max_retries=0,
        timeout=timeout,
    )
