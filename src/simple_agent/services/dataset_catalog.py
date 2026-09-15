"""Read-only operator catalog and literal content search of a published snapshot."""

import re
import unicodedata
from collections import Counter

from simple_agent.services.okf_validator import frontmatter


def read_document(store, bundle_id: str, path: str) -> str:
    root = store.bundle_root(bundle_id)
    relative = store._safe_relative(path)
    target = root / relative
    if not target.resolve().is_relative_to(root):
        raise ValueError("invalid_document_path")
    if any(
        item.is_symlink() for item in [target, *target.parents] if item != root.parent
    ):
        raise ValueError("bundle_symlinks_forbidden")
    if target.stat().st_size > 800_000:
        raise ValueError("oversized_document")
    content = target.read_text(encoding="utf-8")
    if len(content) > 200_000:
        raise ValueError("oversized_document")
    return content


def normalized(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value).casefold()
        if not unicodedata.combining(char)
    )


def catalog(store, query: str = "", bundle_id: str = "") -> dict:
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("search_query_limit_200")
    if not isinstance(bundle_id, str):
        raise ValueError("invalid_bundle_id")
    metadata = store.active_metadata()
    snapshot = bundle_id or metadata.get("bundle_id")
    if not snapshot:
        return {"documents": [], "total": 0, "type_counts": {}, "bundle_id": None}
    root = store.bundle_root(snapshot)
    paths = list(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("bundle_symlinks_forbidden")
    files = sorted(path for path in paths if path.is_file() and path.suffix == ".md")
    if len(files) > 2000 or sum(path.stat().st_size for path in files) > 40_000_000:
        raise ValueError("bundle_size_limit")
    needle = normalized(query.strip())
    documents = []
    counts = Counter()
    for path in files:
        content = path.read_text(encoding="utf-8")
        if len(content) > 200_000:
            raise ValueError("oversized_document")
        relative = path.relative_to(root).as_posix()
        invalid = False
        try:
            fields = frontmatter(content)
        except ValueError:
            fields = {}
            invalid = path.name not in {"index.md", "log.md"}
        title = fields.get("title")
        if not isinstance(title, str) or not title.strip():
            heading = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            title = (
                heading.group(1).strip()
                if heading
                else path.stem.replace("-", " ").replace("_", " ")
            )
        kind = fields.get("type")
        if path.name in {"index.md", "log.md"}:
            kind = path.stem.upper()
        elif not isinstance(kind, str) or not kind.strip():
            kind = "SEM TIPO"
            invalid = True
        kind = kind.strip().upper()[:60]
        counts[kind] += 1
        if needle and needle not in normalized(
            relative + "\n" + title + "\n" + content
        ):
            continue
        snippet = ""
        line_number = None
        if needle:
            for number, line in enumerate(content.splitlines(), 1):
                position = normalized(line).find(needle)
                if position >= 0:
                    start = max(0, position - 60)
                    snippet = ("…" if start else "") + line[start : start + 240]
                    line_number = number
                    break
        status = fields.get("status")
        documents.append(
            {
                "path": relative,
                "title": title[:180],
                "type": kind,
                "status": status[:60] if isinstance(status, str) else None,
                "metadata_warning": invalid,
                "snippet": snippet,
                "line": line_number,
            }
        )
    return {
        "documents": documents,
        "total": len(files),
        "type_counts": dict(counts),
        "bundle_id": snapshot,
        "bundle_name": metadata.get("bundle_name"),
        "bundle_version": metadata.get("bundle_version"),
    }
