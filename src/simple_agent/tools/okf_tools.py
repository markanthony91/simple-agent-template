from __future__ import annotations

import logging
from time import perf_counter

from langchain_core.tools import tool

from simple_agent.services.okf_store import PersistentOKFStore

logger = logging.getLogger("simple_agent.okf")
store = PersistentOKFStore()


def _service():
    service = store.service()
    if service is None:
        raise FileNotFoundError("No active OKF bundle in persistent storage")
    return service


def _log_call(name: str, started: float, **fields: str) -> None:
    elapsed_ms = round((perf_counter() - started) * 1000, 2)
    details = " ".join(f"{key}={value!r}" for key, value in fields.items() if value)
    logger.info("OKF_TOOL name=%s elapsed_ms=%s %s", name, elapsed_ms, details)


@tool
def okf_index(directory: str = "") -> str:
    """Read an OKF index.md for progressive disclosure. Use this before opening concepts."""
    started = perf_counter()
    service = store.service()
    if service is None:
        result = "No active OKF bundle."
    else:
        result = service.read_index(directory)
    _log_call("okf_index", started, directory=directory)
    return result


@tool
def okf_list() -> str:
    """List all Markdown paths in the active persistent OKF bundle."""
    started = perf_counter()
    files = store.list_files()
    result = "\n".join(files) if files else "No OKF files available."
    _log_call("okf_list", started, count=str(len(files)))
    return result


@tool
def okf_search(query: str, scope: str = "") -> str:
    """Fallback lexical search across active OKF concepts, optionally scoped to a directory."""
    started = perf_counter()
    service = store.service()
    if service is None:
        result = "No OKF matches found."
    else:
        result = service.search(query, scope)
    _log_call("okf_search", started, query=query, scope=scope)
    return result


@tool
def okf_read(path: str) -> str:
    """Read one concept or reserved Markdown file from the active persistent OKF bundle."""
    started = perf_counter()
    result = _service().read_file(path)
    _log_call("okf_read", started, path=path)
    return result


@tool
def okf_read_section(path: str, heading: str) -> str:
    """Read one Markdown section from an active persistent OKF concept by heading."""
    started = perf_counter()
    result = _service().read_section(path, heading)
    _log_call("okf_read_section", started, path=path, heading=heading)
    return result


OKF_TOOLS = [okf_index, okf_list, okf_search, okf_read, okf_read_section]
