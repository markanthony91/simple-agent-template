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
    """Discover institutional knowledge through an OKF index.md.

    Use this as the normal first tool when a user asks about a company,
    institution, creditor, product, service, policy, procedure, collection
    rule, contract, support channel, official channel, or other information
    that may belong to the active institutional knowledge bundle. Start with
    the root index when the correct branch is not already known from retrieved
    OKF content, then follow the indexes progressively. Do not guess paths.
    """
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
    """List Markdown paths in the active persistent OKF bundle.

    Use only when progressive navigation through okf_index is unavailable,
    incomplete, or inconsistent. This is not the preferred discovery method.
    """
    started = perf_counter()
    files = store.list_files()
    result = "\n".join(files) if files else "No OKF files available."
    _log_call("okf_list", started, count=str(len(files)))
    return result


@tool
def okf_search(query: str, scope: str = "") -> str:
    """Fallback lexical search across active OKF concepts.

    Use this when progressive navigation with okf_index cannot locate the
    needed institutional information, or when indexes do not expose enough
    information to identify a concept. It may be scoped to a directory. Do
    not use it as the default replacement for index-based discovery.
    """
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
    """Read a complete OKF Markdown concept from the active bundle.

    Use after an index or search has identified the relevant path and broader
    concept context is needed. For a single known section, prefer
    okf_read_section. Preserve uncertainty, placeholders, and limitations
    found in the source instead of filling them from general model knowledge.
    """
    started = perf_counter()
    result = _service().read_file(path)
    _log_call("okf_read", started, path=path)
    return result


@tool
def okf_read_section(path: str, heading: str) -> str:
    """Read one exact Markdown section from an active OKF concept.

    Use this after OKF navigation has identified a relevant file and exact
    heading. It is preferred when one section is sufficient to answer the
    user's institutional question. Use headings exactly as exposed by the
    indexes or previous OKF tool output; do not invent or translate them.
    """
    started = perf_counter()
    result = _service().read_section(path, heading)
    _log_call("okf_read_section", started, path=path, heading=heading)
    return result


OKF_TOOLS = [okf_index, okf_list, okf_search, okf_read, okf_read_section]
