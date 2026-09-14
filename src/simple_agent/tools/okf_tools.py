from __future__ import annotations

import json
import logging
from time import perf_counter
from uuid import uuid4

from langchain_core.tools import tool

from simple_agent.services.okf_store import PersistentOKFStore
from simple_agent.services.simulator_store import SimulatorStore
from simple_agent.tools.okf_contracts import (
    detect_concrete_terms,
    detect_placeholder,
    parse_index,
    parse_read,
    parse_search,
    parse_section,
)

logger = logging.getLogger("simple_agent.okf")
okf_store = PersistentOKFStore()
simulator_store = SimulatorStore()


def _service():
    service = okf_store.service()
    if service is None:
        raise FileNotFoundError("No active OKF bundle in persistent storage")
    return service


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _log_result(name: str, started: float, payload: dict) -> None:
    summary = {
        "tool": name,
        "elapsed_ms": round((perf_counter() - started) * 1000, 2),
        "ok": payload.get("ok"),
        "canonical_directory": payload.get("canonical_directory"),
        "canonical_parent": payload.get("canonical_parent"),
        "canonical_scope": payload.get("canonical_scope"),
        "canonical_path": payload.get("canonical_path"),
        "child_count": len(payload.get("child_directories") or []),
        "concept_count": len(payload.get("concept_paths") or []),
        "match_count": payload.get("match_count"),
        "policy_state": payload.get("policy_state"),
    }
    logger.info("OKF_RESULT %s", json.dumps({k: v for k, v in summary.items() if v is not None}, ensure_ascii=False))


def _error(name: str, error: Exception, **details) -> str:
    payload = {
        "ok": False,
        "tool": name,
        "reason": "knowledge_lookup_failed",
        "error_type": type(error).__name__,
        "details": details,
        "instruction": "Use canonical destinations returned by OKF tools; do not invent paths or headings.",
    }
    logger.warning("OKF_TOOL_ERROR %s", json.dumps(payload, ensure_ascii=False))
    return _dump(payload)


@tool
def okf_index(directory: str = "") -> str:
    """Discover OKF destinations using structured canonical navigation data."""
    started = perf_counter()
    try:
        payload = parse_index(_service().read_index(directory), directory)
        _log_result("okf_index", started, payload)
        return _dump(payload)
    except (FileNotFoundError, ValueError, KeyError) as error:
        return _error("okf_index", error, directory=directory)


@tool
def okf_list() -> str:
    """Last-resort listing of Markdown paths in the active OKF bundle."""
    started = perf_counter()
    try:
        files = okf_store.list_files()
        payload = {"ok": True, "paths": files, "count": len(files)}
        _log_result("okf_list", started, payload)
        return _dump(payload)
    except (FileNotFoundError, ValueError, KeyError) as error:
        return _error("okf_list", error)


@tool
def okf_search(query: str, scope: str = "") -> str:
    """Fallback lexical search returning canonical scope and structured matches."""
    started = perf_counter()
    try:
        payload = parse_search(_service().search(query, scope), query, scope)
        _log_result("okf_search", started, payload)
        return _dump(payload)
    except (FileNotFoundError, ValueError, KeyError) as error:
        return _error("okf_search", error, query=query, scope=scope)


@tool
def okf_read(path: str) -> str:
    """Read a complete OKF concept and return canonical structured JSON."""
    started = perf_counter()
    try:
        payload = parse_read(_service().read_file(path), path)
        _log_result("okf_read", started, payload)
        return _dump(payload)
    except (FileNotFoundError, ValueError, KeyError) as error:
        return _error("okf_read", error, path=path)


@tool
def okf_read_section(path: str, heading: str) -> str:
    """Read one exact section. Missing headings return available exact alternatives."""
    started = perf_counter()
    try:
        payload = parse_section(_service().read_section(path, heading), path, heading)
        _log_result("okf_read_section", started, payload)
        return _dump(payload)
    except (FileNotFoundError, ValueError, KeyError) as error:
        return _error("okf_read_section", error, path=path, heading=heading)


@tool
def okf_evaluate_policy(policy_text: str, canonical_paths: list[str] | None = None) -> str:
    """Classify retrieved policy evidence and persist a gate for offer generation."""
    started = perf_counter()
    paths = [str(path) for path in (canonical_paths or []) if str(path).strip()]
    text = (policy_text or "").strip()

    if not text:
        state = "POLICY_NOT_FOUND"
        missing = ["policy_evidence"]
    elif detect_placeholder(text):
        state = "POLICY_FOUND_UNDEFINED"
        missing = ["operational_terms"]
    else:
        concrete = detect_concrete_terms(text)
        state = "POLICY_FOUND_DEFINED" if concrete else "POLICY_FOUND_UNDEFINED"
        missing = [] if concrete else ["concrete_commercial_terms"]

    evaluation_id = f"EVAL-{uuid4().hex[:10].upper()}"
    fixture = simulator_store.load()
    runtime = fixture.get("_runtime") if isinstance(fixture.get("_runtime"), dict) else {}
    evaluations = runtime.get("policy_evaluations") if isinstance(runtime.get("policy_evaluations"), dict) else {}
    evaluations[evaluation_id] = {
        "policy_state": state,
        "canonical_paths": paths,
        "missing_parameters": missing,
    }
    runtime["policy_evaluations"] = evaluations
    fixture["_runtime"] = runtime
    simulator_store.save(fixture)

    payload = {
        "ok": True,
        "policy_evaluation_id": evaluation_id,
        "policy_state": state,
        "canonical_paths": paths,
        "missing_parameters": missing,
        "offer_generation_allowed": state == "POLICY_FOUND_DEFINED",
    }
    _log_result("okf_evaluate_policy", started, payload)
    return _dump(payload)


OKF_TOOLS = [okf_index, okf_list, okf_search, okf_read, okf_read_section, okf_evaluate_policy]
