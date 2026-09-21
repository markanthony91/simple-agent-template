from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYS = {
    "cpf",
    "document",
    "document_number",
    "birth_date",
    "full_name",
    "confirmation_text",
    "password",
    "token",
    "api_key",
    "authorization",
    "secret",
    "email",
    "recipient",
}

OKF_METADATA_KEYS = {"directory", "path", "heading", "query", "scope"}
MAX_TEXT = 600
MAX_RESULT_TEXT = 900


def tool_outcome(result: Any) -> dict[str, str]:
    """Separate handler completion from lookup/identity/business decisions."""
    if getattr(result, "status", None) == "error":
        return {"execution_status": "error", "domain_outcome": "error"}
    content = getattr(result, "content", result)
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except (json.JSONDecodeError, TypeError):
        data = None
    outcome = "not_applicable"
    if isinstance(data, dict):
        if data.get("error") or data.get("ok") is False:
            outcome = "error"
        elif any(data.get(key) is False for key in ("available", "created", "captured", "sent", "verified", "found", "financial_data_available")):
            outcome = "denied"
        else:
            outcome = "allowed"
    elif isinstance(content, str) and any(marker in content for marker in ("No OKF matches found", "not found (no fuzzy match)", "OKF_REQUESTED_DIRECTORY:")):
        outcome = "lookup_miss"
    return {"execution_status": "completed", "domain_outcome": outcome}


def _mask_document(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 2:
        return f"***.***.***-{digits[-2:]}"
    return "***"


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…<truncated>"


def _sanitize_scalar(key: str, value: Any) -> Any:
    normalized = key.casefold()
    if normalized in SENSITIVE_KEYS:
        if normalized in {"cpf", "document", "document_number"} and value is not None:
            return _mask_document(str(value))
        return "<redacted>"
    if isinstance(value, str):
        return _truncate(value, MAX_TEXT)
    return value


def sanitize_mapping(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    result: dict[str, Any] = {}
    for key, value in payload.items():
        name = str(key)
        if isinstance(value, Mapping):
            result[name] = sanitize_mapping(value)
        elif isinstance(value, list):
            result[name] = [
                sanitize_mapping(item) if isinstance(item, Mapping) else _sanitize_scalar(name, item)
                for item in value[:20]
            ]
        else:
            result[name] = _sanitize_scalar(name, value)
    return result


def sanitize_tool_args(tool_name: str, args: Mapping[str, Any] | None) -> dict[str, Any]:
    if tool_name.startswith("okf_"):
        source = args or {}
        return {
            key: _sanitize_scalar(key, source.get(key))
            for key in OKF_METADATA_KEYS
            if key in source
        }
    return sanitize_mapping(args)


def sanitize_result(tool_name: str, result: Any) -> Any:
    """Return log-safe result metadata without exposing document bodies or PII."""
    if tool_name.startswith("okf_"):
        text = getattr(result, "content", result)
        return {"content_length": len(str(text))}

    content = getattr(result, "content", result)
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            return _truncate(content, MAX_RESULT_TEXT)
        if isinstance(decoded, Mapping):
            return sanitize_mapping(decoded)
        return decoded
    if isinstance(content, Mapping):
        return sanitize_mapping(content)
    return _truncate(str(content), MAX_RESULT_TEXT)


def extract_trace_ids(request: Any) -> dict[str, str]:
    """Best-effort extraction of run/thread identifiers without depending on internals."""
    found: dict[str, str] = {}
    candidates = [
        getattr(request, "runtime", None),
        getattr(request, "context", None),
        getattr(request, "config", None),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, Mapping):
            mappings = [candidate]
            configurable = candidate.get("configurable")
            metadata = candidate.get("metadata")
            if isinstance(configurable, Mapping):
                mappings.append(configurable)
            if isinstance(metadata, Mapping):
                mappings.append(metadata)
        else:
            mappings = []
            for attr in ("context", "config", "metadata"):
                value = getattr(candidate, attr, None)
                if isinstance(value, Mapping):
                    mappings.append(value)
        for mapping in mappings:
            for source_key, output_key in (("thread_id", "thread_id"), ("run_id", "run_id")):
                value = mapping.get(source_key)
                if value and output_key not in found:
                    found[output_key] = str(value)
    return found
