"""Small authenticated client for the Zerai Channel Console."""

from __future__ import annotations

import json
import os

import httpx


class ChannelConsoleError(ValueError):
    def __init__(self, code: str, *, outcome_unknown: bool = False):
        super().__init__(code)
        self.code = code
        self.outcome_unknown = outcome_unknown


def request_json(path: str, payload: dict | None = None, timeout: int = 15) -> dict:
    base = (
        (
            os.getenv("CHANNEL_CONSOLE_URL")
            or os.getenv("RAILWAY_SERVICE_ZERAI_CHANNEL_CONSOLE_URL")
            or ""
        )
        .strip()
        .rstrip("/")
    )
    token = (
        os.getenv("CHANNEL_CONSOLE_AGENT_RUNTIME_TOKEN")
        or os.getenv("CHANNEL_CONSOLE_ENGINE_TOKEN")
        or ""
    ).strip()
    if not base or not token:
        raise ChannelConsoleError("channel_console_not_configured")
    if "://" not in base:
        base = ("http://" if base.endswith(".railway.internal") else "https://") + base
    if not path.startswith("/api/engine/v1/"):
        raise ChannelConsoleError("channel_console_invalid_path")
    try:
        response = httpx.request(
            "POST" if payload is not None else "GET",
            base + path,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            json=payload,
            timeout=timeout,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise ChannelConsoleError(
            "channel_console_unavailable", outcome_unknown=payload is not None
        ) from exc
    if not 200 <= response.status_code < 300:
        try:
            error = response.json().get("error")
        except (AttributeError, ValueError):
            error = None
        raise ChannelConsoleError(
            str(error or f"channel_console_http_{response.status_code}"),
            outcome_unknown=payload is not None and response.status_code >= 500,
        )
    if len(response.content) > 1_000_000:
        raise ChannelConsoleError("channel_console_invalid_response")
    try:
        result = json.loads(response.content)
    except (TypeError, ValueError) as exc:
        raise ChannelConsoleError("channel_console_invalid_response") from exc
    if not isinstance(result, dict):
        raise ChannelConsoleError("channel_console_invalid_response")
    return result
