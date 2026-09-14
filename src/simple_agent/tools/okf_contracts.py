from __future__ import annotations

import re
import unicodedata
from typing import Any

PLACEHOLDERS = (
    "a definir pela operacao",
    "a definir pela operação",
    "to be defined by operations",
    "to be defined by operation",
    "tbd by operations",
)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_marks.casefold()).strip()


def detect_placeholder(value: str) -> bool:
    normalized = normalize_text(value)
    return any(normalize_text(item) in normalized for item in PLACEHOLDERS)


def detect_concrete_terms(value: str) -> list[str]:
    patterns = {
        "percentage": r"\b\d{1,3}(?:[.,]\d+)?\s*%",
        "installments": r"\b(?:ate\s+|até\s+)?\d{1,3}\s*(?:x|parcelas?)\b",
        "money": r"\bR\$\s*\d[\d.]*?(?:,\d{2})?\b",
        "days": r"\b\d+\s+dias?\b",
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, value or "", re.IGNORECASE)]


def marker(text: str, name: str) -> str | None:
    match = re.search(rf"^{re.escape(name)}:\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    return "" if value == "<root>" else value


def marker_paths(text: str, name: str) -> list[str]:
    value = marker(text, name)
    if not value or value == "(none)":
        return []
    return [item.strip().strip("`") for item in value.split(",") if item.strip()]


def strip_markers(text: str) -> str:
    prefixes = (
        "OKF_CANONICAL_PATH:", "OKF_CANONICAL_DIRECTORY:", "OKF_CANONICAL_SCOPE:",
        "OKF_CHILD_DIRECTORIES:", "OKF_CONCEPT_PATHS:", "OKF_REQUESTED_DIRECTORY:",
        "OKF_CANONICAL_PARENT:",
    )
    return "\n".join(line for line in text.splitlines() if not line.startswith(prefixes)).strip()


def parse_index(text: str, requested: str) -> dict[str, Any]:
    missing = marker(text, "OKF_REQUESTED_DIRECTORY")
    return {
        "ok": missing is None,
        "requested_directory": requested,
        "canonical_directory": marker(text, "OKF_CANONICAL_DIRECTORY"),
        "canonical_parent": marker(text, "OKF_CANONICAL_PARENT"),
        "child_directories": marker_paths(text, "OKF_CHILD_DIRECTORIES"),
        "concept_paths": marker_paths(text, "OKF_CONCEPT_PATHS"),
        "content": strip_markers(text),
        "reason": "directory_or_index_not_found" if missing is not None else None,
    }


def parse_search(text: str, query: str, scope: str) -> dict[str, Any]:
    lines = [line for line in text.splitlines() if line and not line.startswith("OKF_CANONICAL_SCOPE:")]
    matches = [] if any("No OKF matches found" in line for line in lines) else lines
    return {
        "ok": True,
        "query": query,
        "requested_scope": scope,
        "canonical_scope": marker(text, "OKF_CANONICAL_SCOPE"),
        "matches": matches,
        "match_count": len(matches),
    }


def parse_read(text: str, requested_path: str) -> dict[str, Any]:
    canonical = marker(text, "OKF_CANONICAL_PATH")
    return {"ok": canonical is not None, "requested_path": requested_path, "canonical_path": canonical, "content": strip_markers(text)}


def parse_section(text: str, requested_path: str, heading: str) -> dict[str, Any]:
    canonical = marker(text, "OKF_CANONICAL_PATH")
    found = "not found (no fuzzy match)" not in text
    available: list[str] = []
    heading_match = re.search(r"Available headings.*?:\s*(.+?)\.\s*Retry", text, re.IGNORECASE | re.DOTALL)
    if heading_match:
        available = re.findall(r'"([^"]+)"', heading_match.group(1))
    return {
        "ok": canonical is not None and found,
        "requested_path": requested_path,
        "canonical_path": canonical,
        "requested_heading": heading,
        "available_headings": available,
        "content": strip_markers(text) if found else "",
        "reason": None if found else "heading_not_found",
    }
