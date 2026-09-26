from __future__ import annotations

import json
import logging
from time import perf_counter

from langchain_core.tools import tool
from langchain.tools import ToolRuntime

from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.okf_service import OKFService
from simple_agent.services.session_store import SessionStore, thread_id
from simple_agent.services.offer_policy import fingerprint

logger = logging.getLogger("simple_agent.okf")
store = PersistentOKFStore()


def _service(runtime):
    snapshot = SessionStore().read(thread_id(runtime)).get("snapshot_id")
    if not snapshot:
        raise FileNotFoundError(
            "No OKF bundle pinned to this conversation; start a new conversation after publication"
        )
    return OKFService(store.bundle_root(snapshot))


def _receipt(runtime, service, path, result):
    canonical = service.canonical_path(path)
    if "not found (no fuzzy match)" in result:
        return
    with SessionStore().transaction(thread_id(runtime)) as state:
        state["receipts"][canonical] = {
            "hash": fingerprint((service.root / canonical).read_text(encoding="utf-8")),
            "snapshot_id": state["snapshot_id"],
        }


def _log_call(name: str, started: float, **fields: str) -> None:
    elapsed_ms = round((perf_counter() - started) * 1000, 2)
    details = " ".join(f"{key}={value!r}" for key, value in fields.items() if value)
    logger.info("OKF_TOOL name=%s elapsed_ms=%s %s", name, elapsed_ms, details)


def _recoverable_error(name: str, error: Exception, **details: str) -> str:
    logger.warning(
        "OKF_TOOL_RECOVERABLE name=%s error=%s details=%s",
        name,
        type(error).__name__,
        details,
    )
    return json.dumps(
        {
            "error": True,
            "tool": name,
            "reason": "knowledge_lookup_failed",
            "error_type": type(error).__name__,
            "details": details,
            "instruction": "Recover by navigating from okf_index or okf_search instead of inventing a path or heading.",
        },
        ensure_ascii=False,
    )


@tool
def okf_index(runtime: ToolRuntime, directory: str = "") -> str:
    """Discover institutional knowledge through an OKF index.md."""
    started = perf_counter()
    try:
        result = _service(runtime).read_index(directory)
    except (FileNotFoundError, ValueError, KeyError) as error:
        result = _recoverable_error("okf_index", error, directory=directory)
    _log_call("okf_index", started, directory=directory)
    return result


@tool
def okf_list(runtime: ToolRuntime) -> str:
    """List Markdown paths in the active persistent OKF bundle."""
    started = perf_counter()
    try:
        files = _service(runtime).list_files().splitlines()
        result = "\n".join(files) if files else "No OKF files available."
        count = str(len(files))
    except (FileNotFoundError, ValueError, KeyError) as error:
        result = _recoverable_error("okf_list", error)
        count = "0"
    _log_call("okf_list", started, count=count)
    return result


@tool
def okf_search(query: str, runtime: ToolRuntime, scope: str = "") -> str:
    """Fallback lexical search across active OKF concepts."""
    started = perf_counter()
    try:
        result = _service(runtime).search(query, scope)
    except (FileNotFoundError, ValueError, KeyError) as error:
        result = _recoverable_error("okf_search", error, query=query, scope=scope)
    _log_call("okf_search", started, query=query, scope=scope)
    return result


@tool
def okf_read(path: str, runtime: ToolRuntime) -> str:
    """Read a complete OKF Markdown concept from the active bundle."""
    started = perf_counter()
    try:
        service = _service(runtime)
        result = service.read_file(path)
        _receipt(runtime, service, path, result)
    except (FileNotFoundError, ValueError, KeyError) as error:
        result = _recoverable_error("okf_read", error, path=path)
    _log_call("okf_read", started, path=path)
    return result


@tool
def okf_read_section(path: str, heading: str, runtime: ToolRuntime) -> str:
    """Read an exact section plus its YAML lifecycle, scope and policy metadata."""
    started = perf_counter()
    try:
        service = _service(runtime)
        result = service.read_section(path, heading)
        _receipt(runtime, service, path, result)
    except (FileNotFoundError, ValueError, KeyError) as error:
        result = _recoverable_error(
            "okf_read_section", error, path=path, heading=heading
        )
    _log_call("okf_read_section", started, path=path, heading=heading)
    return result


OKF_TOOLS = [okf_index, okf_list, okf_search, okf_read, okf_read_section]
