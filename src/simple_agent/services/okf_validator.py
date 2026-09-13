from __future__ import annotations

import re
from pathlib import Path


_RESERVED = {"index.md", "log.md"}
_FRONTMATTER_BOUNDARY = "---"
_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_TYPE_RE = re.compile(r"^type\s*:\s*(.+?)\s*$", flags=re.MULTILINE)
_OKF_VERSION_RE = re.compile(r"^okf_version\s*:\s*[\"']?0\.2[\"']?\s*$", flags=re.MULTILINE)


def _frontmatter(content: str) -> str | None:
    lines = content.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_BOUNDARY:
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONTMATTER_BOUNDARY:
            return "\n".join(lines[1:index])
    return None


def _normalize_target(base: Path, target: str) -> str | None:
    cleaned = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not cleaned or cleaned.startswith(("http://", "https://", "mailto:")):
        return None
    candidate = (base / cleaned).as_posix()
    parts: list[str] = []
    for part in Path(candidate).parts:
        if part == ".":
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    normalized = "/".join(parts)
    if cleaned.endswith("/"):
        normalized = f"{normalized}/index.md"
    return normalized


def validate_okf_files(files: dict[str, str], expected_version: str = "0.2") -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    normalized = {Path(path).as_posix().lstrip("/"): content for path, content in files.items()}

    if not normalized:
        errors.append({"code": "empty_bundle", "message": "Draft has no files."})
    if "index.md" not in normalized:
        errors.append({"code": "missing_root_index", "path": "index.md", "message": "Root index.md is required."})

    root_index = normalized.get("index.md", "")
    root_fm = _frontmatter(root_index)
    if root_fm and expected_version == "0.2" and not _OKF_VERSION_RE.search(root_fm):
        warnings.append({"code": "root_version_missing", "path": "index.md", "message": "Root index.md frontmatter does not declare okf_version: 0.2."})

    for path, content in sorted(normalized.items()):
        name = Path(path).name.lower()
        if not content.strip():
            errors.append({"code": "empty_file", "path": path, "message": "Markdown file is empty."})
            continue
        if name not in _RESERVED:
            fm = _frontmatter(content)
            if fm is None:
                errors.append({"code": "missing_frontmatter", "path": path, "message": "Concept document must contain YAML frontmatter."})
            elif not _TYPE_RE.search(fm):
                errors.append({"code": "missing_type", "path": path, "message": "Concept frontmatter must contain a non-empty type field."})

        parent = Path(path).parent
        for target in _LINK_RE.findall(content):
            resolved = _normalize_target(parent, target)
            if not resolved:
                continue
            if resolved not in normalized:
                warnings.append({"code": "broken_relative_link", "path": path, "target": target, "resolved": resolved, "message": "Relative Markdown link does not resolve inside the draft."})

    indexed_dirs = {str(Path(path).parent).replace(".", "") for path in normalized if Path(path).name.lower() == "index.md"}
    concept_dirs = {str(Path(path).parent).replace(".", "") for path in normalized if Path(path).name.lower() not in _RESERVED}
    for directory in sorted(concept_dirs):
        index_path = f"{directory}/index.md".lstrip("/") if directory else "index.md"
        if index_path not in normalized:
            warnings.append({"code": "missing_directory_index", "path": index_path, "message": "Directory contains concepts but no index.md for progressive disclosure."})

    return {
        "valid": not errors,
        "okf_version": expected_version,
        "file_count": len(normalized),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }
