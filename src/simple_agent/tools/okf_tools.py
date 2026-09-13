from __future__ import annotations

from langchain_core.tools import tool

from simple_agent.services.okf_store import PersistentOKFStore

store = PersistentOKFStore()


def _service():
    service = store.service()
    if service is None:
        raise FileNotFoundError("No active OKF bundle in persistent storage")
    return service


@tool
def okf_index(directory: str = "") -> str:
    """Read an OKF index.md for progressive disclosure. Use this before opening concepts."""
    service = store.service()
    if service is None:
        return "No active OKF bundle."
    return service.read_index(directory)


@tool
def okf_list() -> str:
    """List all Markdown paths in the active persistent OKF bundle."""
    files = store.list_files()
    return "\n".join(files) if files else "No OKF files available."


@tool
def okf_search(query: str, scope: str = "") -> str:
    """Fallback lexical search across active OKF concepts, optionally scoped to a directory."""
    service = store.service()
    if service is None:
        return "No OKF matches found."
    return service.search(query, scope)


@tool
def okf_read(path: str) -> str:
    """Read one concept or reserved Markdown file from the active persistent OKF bundle."""
    return _service().read_file(path)


@tool
def okf_read_section(path: str, heading: str) -> str:
    """Read one Markdown section from an active persistent OKF concept by heading."""
    return _service().read_section(path, heading)


OKF_TOOLS = [okf_index, okf_list, okf_search, okf_read, okf_read_section]
