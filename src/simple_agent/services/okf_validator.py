from __future__ import annotations

import re
from pathlib import Path
import yaml


_RESERVED = {"index.md", "log.md"}
_FRONTMATTER_BOUNDARY = "---"
_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_OKF_VERSION_RE = re.compile(
    r"^okf_version\s*:\s*[\"']?0\.2[\"']?\s*$", flags=re.MULTILINE
)


def _frontmatter(content: str) -> str | None:
    lines = content.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_BOUNDARY:
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONTMATTER_BOUNDARY:
            return "\n".join(lines[1:index])
    return None


def frontmatter(content: str) -> dict:
    raw = _frontmatter(content)
    if raw is None:
        raise ValueError("missing_frontmatter")
    try:
        # Aliases and duplicate keys hide conflicting policy definitions.
        if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(raw)):
            raise ValueError("yaml_alias_not_allowed")
        node = yaml.compose(raw, Loader=yaml.SafeLoader)
        if not isinstance(node, yaml.MappingNode):
            raise ValueError("frontmatter_must_be_mapping")

        def check_keys(mapping):
            if isinstance(mapping, yaml.MappingNode):
                keys = [key.value for key, _ in mapping.value]
                if len(keys) != len(set(keys)):
                    raise ValueError("duplicate_yaml_key")
                for _, child in mapping.value:
                    check_keys(child)
            elif isinstance(mapping, yaml.SequenceNode):
                for child in mapping.value:
                    check_keys(child)

        check_keys(node)
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError("invalid_yaml") from exc


def validate_document(path: str, content: str) -> None:
    name = Path(path).name
    if not content.strip() or len(content) > 200_000:
        raise ValueError("empty_or_oversized_document")
    if name.lower() in _RESERVED:
        if name not in _RESERVED:
            raise ValueError("reserved_name_must_be_lowercase")
        if _frontmatter(content) is not None:
            if path != "index.md":
                raise ValueError("frontmatter_only_in_root_index")
            frontmatter(content)
        return
    value = frontmatter(content).get("type")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing_type")


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
    normalized = {
        Path(path).as_posix().lstrip("/"): content for path, content in files.items()
    }

    if not normalized:
        errors.append({"code": "empty_bundle", "message": "Draft has no files."})
    if "index.md" not in normalized:
        errors.append(
            {
                "code": "missing_root_index",
                "path": "index.md",
                "message": "Root index.md is required.",
            }
        )

    root_index = normalized.get("index.md", "")
    root_fm = _frontmatter(root_index)
    if root_fm and expected_version == "0.2" and not _OKF_VERSION_RE.search(root_fm):
        warnings.append(
            {
                "code": "root_version_missing",
                "path": "index.md",
                "message": "Root index.md frontmatter does not declare okf_version: 0.2.",
            }
        )

    for path, content in sorted(normalized.items()):
        if not content.strip():
            errors.append(
                {
                    "code": "empty_file",
                    "path": path,
                    "message": "Markdown file is empty.",
                }
            )
            continue
        try:
            validate_document(path, content)
        except ValueError as exc:
            errors.append(
                {"code": str(exc), "path": path, "message": "Invalid OKF document."}
            )

        parent = Path(path).parent
        for target in _LINK_RE.findall(content):
            resolved = _normalize_target(parent, target)
            if not resolved:
                continue
            if resolved not in normalized:
                warnings.append(
                    {
                        "code": "broken_relative_link",
                        "path": path,
                        "target": target,
                        "resolved": resolved,
                        "message": "Relative Markdown link does not resolve inside the draft.",
                    }
                )

    concept_dirs = {
        str(Path(path).parent).replace(".", "")
        for path in normalized
        if Path(path).name.lower() not in _RESERVED
    }
    for directory in sorted(concept_dirs):
        index_path = f"{directory}/index.md".lstrip("/") if directory else "index.md"
        if index_path not in normalized:
            warnings.append(
                {
                    "code": "missing_directory_index",
                    "path": index_path,
                    "message": "Directory contains concepts but no index.md for progressive disclosure.",
                }
            )

    return {
        "valid": not errors,
        "okf_version": expected_version,
        "file_count": len(normalized),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }
