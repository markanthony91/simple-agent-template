from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from simple_agent.services.okf_service import OKFService

PROJECT_ROOT = Path(__file__).resolve().parents[3]
okf_service = OKFService(PROJECT_ROOT)


@tool
def okf_list() -> str:
    """List the OKF Markdown files available to the agent."""
    return okf_service.list_files()


@tool
def okf_search(query: str) -> str:
    """Search exact text fragments across OKF Markdown files."""
    return okf_service.search(query)


@tool
def okf_read(file_name: str) -> str:
    """Read one OKF Markdown file by file name."""
    return okf_service.read_file(file_name)


@tool
def okf_read_section(file_name: str, heading: str) -> str:
    """Read one Markdown section from an OKF file by heading."""
    return okf_service.read_section(file_name, heading)


OKF_TOOLS = [okf_list, okf_search, okf_read, okf_read_section]
