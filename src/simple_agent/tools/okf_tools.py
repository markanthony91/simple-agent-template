from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from simple_agent.services.okf_service import OKFService

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OKF_ROOT = PROJECT_ROOT / "knowledge" / "okf"
okf_service = OKFService(OKF_ROOT)


@tool
def okf_index(directory: str = "") -> str:
    """Read an OKF index.md for progressive disclosure. Use this before opening concepts."""
    return okf_service.read_index(directory)


@tool
def okf_list() -> str:
    """List all Markdown paths in the OKF bundle."""
    return okf_service.list_files()


@tool
def okf_search(query: str, scope: str = "") -> str:
    """Fallback lexical search across OKF concepts, optionally scoped to a directory."""
    return okf_service.search(query, scope)


@tool
def okf_read(path: str) -> str:
    """Read one OKF concept or reserved Markdown file by relative path."""
    return okf_service.read_file(path)


@tool
def okf_read_section(path: str, heading: str) -> str:
    """Read one Markdown section from an OKF concept by heading."""
    return okf_service.read_section(path, heading)


OKF_TOOLS = [okf_index, okf_list, okf_search, okf_read, okf_read_section]
