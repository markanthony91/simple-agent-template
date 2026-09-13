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

    def _safe_path(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("Invalid OKF path")
        if candidate.suffix != ".md":
            raise ValueError("Only Markdown OKF files can be read")
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(f"OKF file not found: {relative_path}")
        return candidate

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

    def read_index(self, directory: str = "") -> str:
        relative = f"{directory.strip('/')}/index.md" if directory.strip("/") else "index.md"
        return self.read_file(relative)

    def list_files(self) -> str:
        files = [str(path.relative_to(self.root)) for path in self._markdown_files()]
        return "\n".join(files) if files else "No OKF files available."

    def read_file(self, relative_path: str) -> str:
        content = self._safe_path(relative_path).read_text(encoding="utf-8")
        return content[: self.max_chars_per_file]

    def search(self, query: str, scope: str = "") -> str:
        query_tokens = set(self._normalize(query).split())
        if not query_tokens:
            raise ValueError("Search query cannot be empty")

        scope_root = (self.root / scope).resolve() if scope else self.root
        if not scope_root.is_relative_to(self.root) or not scope_root.exists():
            raise ValueError("Invalid OKF search scope")

        ranked: list[tuple[int, str]] = []
        for path in sorted(scope_root.rglob("*.md")):
            if path.name in {"index.md", "log.md"}:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, start=1):
                line_tokens = set(self._normalize(line).split())
                score = len(query_tokens & line_tokens)
                if score:
                    rel = path.relative_to(self.root)
                    ranked.append((score, f"{rel}:{number}: {line.strip()}"))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        matches = [text for _, text in ranked[: self.max_results]]
        return "\n".join(matches) if matches else "No OKF matches found."

    def read_section(self, relative_path: str, heading: str) -> str:
        content = self.read_file(relative_path)
        target = self._normalize(heading)
        if not target:
            raise ValueError("Heading cannot be empty")

        lines = content.splitlines()
        headings = self._extract_headings(content)
        start: int | None = None
        start_level: int | None = None
        resolved_heading: str | None = None

        # Prefer an exact normalized heading match.
        for index, title, level in headings:
            if self._normalize(title) == target:
                start = index
                start_level = level
                resolved_heading = title
                break

        # If the caller used a partial form, accept a unique token-overlap match.
        if start is None:
            target_tokens = set(target.split())
            candidates: list[tuple[int, int, str, int]] = []
            for index, title, level in headings:
                title_tokens = set(self._normalize(title).split())
                score = len(target_tokens & title_tokens)
                if score:
                    candidates.append((score, index, title, level))
            candidates.sort(key=lambda item: (-item[0], item[2]))
            if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
                _, start, resolved_heading, start_level = candidates[0]

        if start is None or start_level is None:
            available = [title for _, title, _ in headings]
            available_text = ", ".join(available) if available else "none"
            return (
                f"Section not found: {heading}. "
                f"Available headings in {relative_path}: {available_text}. "
                "Retry using one of these exact headings, preferably the heading exposed by index.md."
            )

        collected = [lines[start]]
        for line in lines[start + 1 :]:
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match and len(match.group(1)) <= start_level:
                break
            collected.append(line)

        result = "\n".join(collected)[: self.max_chars_per_file]
        if resolved_heading and self._normalize(resolved_heading) != target:
            return f"Resolved heading '{heading}' to '{resolved_heading}'.\n\n{result}"
        return result
