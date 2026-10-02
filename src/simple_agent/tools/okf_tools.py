from __future__ import annotations

import json
import logging
from time import perf_counter

from langchain_core.tools import tool
from langchain.tools import ToolRuntime

from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.okf_service import OKFService
from simple_agent.services.session_store import SessionStore, thread_id
from simple_agent.services.customer_knowledge import customer_knowledge
from simple_agent.services.offer_policy import fingerprint
from simple_agent.tool_timing import timed_phase, timed_tool

logger = logging.getLogger("simple_agent.okf")
store = PersistentOKFStore()


def _service(runtime):
    state = SessionStore().read(thread_id(runtime))
    snapshot = state.get("snapshot_id")
    if not snapshot:
        raise FileNotFoundError(
            "No OKF bundle pinned to this conversation; start a new conversation after publication"
        )
    service = OKFService(store.bundle_root(snapshot), immutable_bundle=True)
    if "portfolio_scope_id" not in state:
        return service, None
    allowed = ["GLOBAL"]
    if "fixture" in state:
        directory = customer_knowledge(state).get("okf_directory")
        if isinstance(directory, str) and directory:
            allowed.append(service.canonical_directory(directory))
    return service, tuple(dict.fromkeys(allowed))


def _targets(service: OKFService, allowed: tuple[str, ...] | None, scope: str):
    if allowed is None:
        return [scope]
    requested = service.canonical_directory(scope) if scope else ""
    if not requested:
        return list(allowed)
    targets = []
    for root in allowed:
        if requested == root or requested.startswith(f"{root}/"):
            targets.append(requested)
        elif root.startswith(f"{requested}/"):
            targets.append(root)
    if not targets:
        raise PermissionError("okf_scope_not_allowed")
    return list(dict.fromkeys(targets))


def _authorized_path(
    service: OKFService, allowed: tuple[str, ...] | None, path: str
) -> str:
    canonical = service.canonical_path(path)
    if allowed is not None and not any(
        canonical == root or canonical.startswith(f"{root}/") for root in allowed
    ):
        raise PermissionError("okf_scope_not_allowed")
    return canonical


def _receipt(runtime, service, path, result):
    canonical = service.canonical_path(path)
    if "not found (no fuzzy match)" in result:
        return
    with (
        timed_phase("okf_receipt"),
        SessionStore().transaction(thread_id(runtime)) as state,
    ):
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
@timed_tool
def okf_index(runtime: ToolRuntime, directory: str = "") -> str:
    """Discover institutional knowledge through an OKF index.md."""
    started = perf_counter()
    try:
        service, allowed = _service(runtime)
        if allowed is None:
            result = service.read_index(directory)
        else:
            targets = _targets(service, allowed, directory)
            requested = service.canonical_directory(directory) if directory else ""
        if allowed is not None and (not requested or targets != [requested]):
            result = "OKF_ALLOWED_DIRECTORIES:\n" + "\n".join(
                f"- {target}" for target in targets
            )
        elif allowed is not None:
            result = service.read_index(targets[0])
    except (FileNotFoundError, ValueError, KeyError, PermissionError) as error:
        result = _recoverable_error("okf_index", error, directory=directory)
    _log_call("okf_index", started, directory=directory)
    return result


@tool
@timed_tool
def okf_list(runtime: ToolRuntime) -> str:
    """List Markdown paths in the active persistent OKF bundle."""
    started = perf_counter()
    try:
        service, allowed = _service(runtime)
        files = service.list_files().splitlines()
        if allowed is not None:
            files = [
                path
                for path in files
                if any(path == root or path.startswith(f"{root}/") for root in allowed)
            ]
        result = "\n".join(files) if files else "No OKF files available."
        count = str(len(files))
    except (FileNotFoundError, ValueError, KeyError, PermissionError) as error:
        result = _recoverable_error("okf_list", error)
        count = "0"
    _log_call("okf_list", started, count=count)
    return result


@tool
@timed_tool
def okf_search(query: str, runtime: ToolRuntime, scope: str = "") -> str:
    """Fallback lexical search across active OKF concepts."""
    started = perf_counter()
    try:
        service, allowed = _service(runtime)
        result = "\n\n".join(
            service.search(query, target)
            for target in _targets(service, allowed, scope)
        )
    except (FileNotFoundError, ValueError, KeyError, PermissionError) as error:
        result = _recoverable_error("okf_search", error, query=query, scope=scope)
    _log_call("okf_search", started, query=query, scope=scope)
    return result


@tool
@timed_tool
def okf_read(path: str, runtime: ToolRuntime) -> str:
    """Read a complete OKF Markdown concept from the active bundle."""
    started = perf_counter()
    try:
        service, allowed = _service(runtime)
        canonical = _authorized_path(service, allowed, path)
        with timed_phase("okf_document_read"):
            result = service.read_file(canonical)
        _receipt(runtime, service, canonical, result)
    except (FileNotFoundError, ValueError, KeyError, PermissionError) as error:
        result = _recoverable_error("okf_read", error, path=path)
    _log_call("okf_read", started, path=path)
    return result


@tool
@timed_tool
def okf_read_section(path: str, heading: str, runtime: ToolRuntime) -> str:
    """Read an exact section plus its YAML lifecycle, scope and policy metadata."""
    started = perf_counter()
    try:
        service, allowed = _service(runtime)
        canonical = _authorized_path(service, allowed, path)
        with timed_phase("okf_document_read"):
            result = service.read_section(canonical, heading)
        _receipt(runtime, service, canonical, result)
    except (FileNotFoundError, ValueError, KeyError, PermissionError) as error:
        result = _recoverable_error(
            "okf_read_section", error, path=path, heading=heading
        )
    _log_call("okf_read_section", started, path=path, heading=heading)
    return result


OKF_TOOLS = [okf_index, okf_list, okf_search, okf_read, okf_read_section]
