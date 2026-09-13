from __future__ import annotations

import re
from pathlib import Path


class OKFService:
    def __init__(self, root: Path, max_chars_per_file: int = 15000, max_results: int = 10):
        self.root = root.resolve()
        self.max_chars_per_file = max_chars_per_file
        self.max_results = max_results

    def _files(self) -> list[Path]:
        return sorted(self.root.glob("OKF_*.md"))

    def list_files(self) -> str:
        files = [path.name for path in self._files()]
        return "\n".join(files) if files else "No OKF files available."

    def _safe_file(self, name: str) -> Path:
        candidate = (self.root / name).resolve()
        if candidate.parent != self.root or not candidate.name.startswith("OKF_") or candidate.suffix != ".md":
            raise ValueError("Invalid OKF file path")
        if not candidate.exists():
            raise FileNotFoundError(f"OKF file not found: {name}")
        return candidate

    def read_file(self, name: str) -> str:
        content = self._safe_file(name).read_text(encoding="utf-8")
        return content[: self.max_chars_per_file]

    def search(self, query: str) -> str:
        needle = query.strip().lower()
        if not needle:
            raise ValueError("Search query cannot be empty")

        matches: list[str] = []
        for path in self._files():
            lines = path.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, start=1):
                if needle in line.lower():
                    matches.append(f"{path.name}:{number}: {line.strip()}")
                    if len(matches) >= self.max_results:
                        return "\n".join(matches)
        return "\n".join(matches) if matches else "No OKF matches found."

    def read_section(self, name: str, heading: str) -> str:
        content = self.read_file(name)
        target = heading.strip().lower()
        if not target:
            raise ValueError("Heading cannot be empty")

        lines = content.splitlines()
        start: int | None = None
        start_level: int | None = None
        collected: list[str] = []

        for index, line in enumerate(lines):
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if not match:
                continue
            level = len(match.group(1))
            title = match.group(2).strip().lower()
            if start is None and title == target:
                start = index
                start_level = level
                collected.append(line)
                continue
            if start is not None and level <= int(start_level):
                break
            if start is not None:
                collected.extend(lines[index:index])

        if start is None:
            return f"Section not found: {heading}"

        collected = [lines[start]]
        for line in lines[start + 1 :]:
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match and len(match.group(1)) <= int(start_level):
                break
            collected.append(line)

        return "\n".join(collected)[: self.max_chars_per_file]
