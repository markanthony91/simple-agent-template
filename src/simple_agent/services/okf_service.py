from __future__ import annotations

import re
import unicodedata
from pathlib import Path


class OKFService:
    def __init__(self, root: Path, max_chars_per_file: int = 15000, max_results: int = 10):
        self.root = root.resolve()
        self.max_chars_per_file = max_chars_per_file
        self.max_results = max_results

    def _markdown_files(self) -> list[Path]:
        return sorted(path for path in self.root.rglob("*.md") if path.is_file())

    def _safe_path(self, relative_path: str, require_exists: bool = True) -> Path:
        candidate = (self.root / relative_path).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("Invalid OKF path")
        if candidate.suffix != ".md":
            raise ValueError("Only Markdown OKF files are supported")
        if require_exists and (not candidate.exists() or not candidate.is_file()):
            raise FileNotFoundError(f"OKF file not found: {relative_path}")
        return candidate

    def _relative(self, relative_path: str) -> str:
        return str(self._safe_path(relative_path, require_exists=False).relative_to(self.root))

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9]+", " ", without_marks.lower()).strip()

    @staticmethod
    def _extract_headings(content: str) -> list[tuple[int, str, int]]:
        headings: list[tuple[int, str, int]] = []
        for index, line in enumerate(content.splitlines()):
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match:
                headings.append((index, match.group(2).strip(), len(match.group(1))))
        return headings

    def _active(self, active_files: set[str] | None) -> set[str] | None:
        if active_files is None:
            return None
        result: set[str] = set()
        for path in active_files:
            try:
                result.add(self._relative(path))
            except ValueError:
                continue
        return result

    def _ensure_active(self, relative_path: str, active_files: set[str] | None) -> str:
        relative = self._relative(relative_path)
        active = self._active(active_files)
        if active is not None and relative not in active:
            raise FileNotFoundError(f"OKF file not active in current bundle: {relative_path}")
        return relative

    def _override(self, relative_path: str, overrides: dict[str, str] | None) -> str | None:
        if not overrides:
            return None
        value = overrides.get(self._relative(relative_path))
        return value[: self.max_chars_per_file] if isinstance(value, str) else None

    def read_index(self, directory: str = "", overrides: dict[str, str] | None = None, active_files: set[str] | None = None) -> str:
        cleaned = directory.strip("/")
        relative = f"{cleaned}/index.md" if cleaned else "index.md"
        try:
            return self.read_file(relative, overrides, active_files)
        except FileNotFoundError:
            if cleaned:
                return f"No index.md found for OKF directory: {cleaned}. Use the parent index or okf_list/okf_search as fallback."
            return "No root index.md found in the OKF bundle. Use okf_list or okf_search as fallback."

    def list_files(self, overrides: dict[str, str] | None = None, active_files: set[str] | None = None) -> str:
        active = self._active(active_files)
        if active is not None:
            files = active
        else:
            files = {str(path.relative_to(self.root)) for path in self._markdown_files()}
            if overrides:
                for path in overrides:
                    try:
                        files.add(self._relative(path))
                    except ValueError:
                        pass
        return "\n".join(sorted(files)) if files else "No OKF files available."

    def read_file(self, relative_path: str, overrides: dict[str, str] | None = None, active_files: set[str] | None = None) -> str:
        relative = self._ensure_active(relative_path, active_files)
        overridden = self._override(relative, overrides)
        if overridden is not None:
            return overridden
        return self._safe_path(relative).read_text(encoding="utf-8")[: self.max_chars_per_file]

    def validate_edit(self, relative_path: str, content: str) -> str:
        relative = self._relative(relative_path)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("OKF file cannot be empty")
        if len(content) > 200_000:
            raise ValueError("OKF file exceeds the 200000 character edit limit")
        if Path(relative).name != "index.md" and not re.search(r"^type\s*:\s*.+$", content, flags=re.MULTILINE):
            raise ValueError("OKF concept must contain a 'type:' frontmatter field")
        return relative

    def search(self, query: str, scope: str = "", overrides: dict[str, str] | None = None, active_files: set[str] | None = None) -> str:
        query_tokens = set(self._normalize(query).split())
        if not query_tokens:
            raise ValueError("Search query cannot be empty")
        cleaned_scope = scope.strip("/")
        ranked: list[tuple[int, str]] = []
        for relative in self.list_files(overrides, active_files).splitlines():
            if not relative.endswith(".md") or Path(relative).name in {"index.md", "log.md"}:
                continue
            if cleaned_scope and not relative.startswith(cleaned_scope + "/"):
                continue
            try:
                content = self.read_file(relative, overrides, active_files)
            except FileNotFoundError:
                continue
            for number, line in enumerate(content.splitlines(), start=1):
                score = len(query_tokens & set(self._normalize(line).split()))
                if score:
                    ranked.append((score, f"{relative}:{number}: {line.strip()}"))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        matches = [text for _, text in ranked[: self.max_results]]
        return "\n".join(matches) if matches else "No OKF matches found."

    def read_section(self, relative_path: str, heading: str, overrides: dict[str, str] | None = None, active_files: set[str] | None = None) -> str:
        content = self.read_file(relative_path, overrides, active_files)
        target = self._normalize(heading)
        if not target:
            raise ValueError("Heading cannot be empty")
        lines = content.splitlines()
        headings = self._extract_headings(content)
        start = None
        start_level = None
        resolved = None
        for index, title, level in headings:
            if self._normalize(title) == target:
                start, start_level, resolved = index, level, title
                break
        if start is None:
            target_tokens = set(target.split())
            candidates = []
            for index, title, level in headings:
                score = len(target_tokens & set(self._normalize(title).split()))
                if score:
                    candidates.append((score, index, title, level))
            candidates.sort(key=lambda item: (-item[0], item[2]))
            if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
                _, start, resolved, start_level = candidates[0]
        if start is None or start_level is None:
            available = ", ".join(title for _, title, _ in headings) or "none"
            return f"Section not found: {heading}. Available headings in {relative_path}: {available}. Retry using one of these exact headings."
        collected = [lines[start]]
        for line in lines[start + 1:]:
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match and len(match.group(1)) <= start_level:
                break
            collected.append(line)
        result = "\n".join(collected)[: self.max_chars_per_file]
        if resolved and self._normalize(resolved) != target:
            return f"Resolved heading '{heading}' to '{resolved}'.\n\n{result}"
        return result
