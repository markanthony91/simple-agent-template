from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from langchain.tools import ToolRuntime

from simple_agent.services.okf_service import OKFService

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OKF_ROOT = PROJECT_ROOT / "knowledge" / "okf"
okf_service = OKFService(OKF_ROOT)


def _context(runtime: ToolRuntime) -> dict[str, Any]:
    if runtime is None:
        return {}
    context: Any = runtime.context
    return context if isinstance(context, dict) else {}


def _overrides(runtime: ToolRuntime) -> dict[str, str]:
    raw = _context(runtime).get("okf_overrides")
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _active_files(runtime: ToolRuntime) -> set[str] | None:
    raw = _context(runtime).get("okf_bundle_files")
    if not isinstance(raw, list):
        return None
    active = {item for item in raw if isinstance(item, str) and item.endswith(".md")}
    return active or None


@tool
def okf_index(directory: str = "", runtime: ToolRuntime = None) -> str:
    """Read an OKF index.md for progressive disclosure. Use this before opening concepts."""
    return okf_service.read_index(
        directory,
        overrides=_overrides(runtime),
        active_files=_active_files(runtime),
    )


@tool
def okf_list(runtime: ToolRuntime = None) -> str:
    """List all Markdown paths in the active OKF bundle."""
    return okf_service.list_files(
        overrides=_overrides(runtime),
        active_files=_active_files(runtime),
    )


@tool
def okf_search(query: str, scope: str = "", runtime: ToolRuntime = None) -> str:
    """Fallback lexical search across active OKF concepts, optionally scoped to a directory."""
    return okf_service.search(
        query,
        scope,
        overrides=_overrides(runtime),
        active_files=_active_files(runtime),
    )


@tool
def okf_read(path: str, runtime: ToolRuntime = None) -> str:
    """Read one concept or reserved Markdown file from the active OKF bundle."""
    return okf_service.read_file(
        path,
        overrides=_overrides(runtime),
        active_files=_active_files(runtime),
    )


@tool
def okf_read_section(path: str, heading: str, runtime: ToolRuntime = None) -> str:
    """Read one Markdown section from an active OKF concept by heading."""
    return okf_service.read_section(
        path,
        heading,
        overrides=_overrides(runtime),
        active_files=_active_files(runtime),
    )


OKF_TOOLS = [okf_index, okf_list, okf_search, okf_read, okf_read_section]
