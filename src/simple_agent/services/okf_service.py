from __future__ import annotations

import re
import unicodedata
from pathlib import Path


from simple_agent.services.okf_navigation import IndexNavigation


class OKFService(IndexNavigation):
    RESERVED_MARKDOWN = {"index.md", "log.md"}
    TOP_LEVEL_DIRECTORIES = {"GLOBAL", "INSTITUTIONS", "PRODUCTS"}
    SEARCH_STOP_WORDS = {
        "a",
        "as",
        "o",
        "os",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "em",
        "para",
        "por",
        "com",
    }
    SEARCH_ALIASES = {
        "installment": "parcela",
        "installments": "parcela",
        "parcelado": "parcela",
        "parcelada": "parcela",
        "parcelamento": "parcela",
        "parcelamentos": "parcela",
        "parcelas": "parcela",
        "negociar": "negociacao",
        "negociacao": "negociacao",
    }

    def __init__(
        self, root: Path, max_chars_per_file: int = 15000, max_results: int = 10
    ):
        self.root = root.resolve()
        self.max_chars_per_file = max_chars_per_file
        self.max_results = max_results

    def _markdown_files(self) -> list[Path]:
        return sorted(path for path in self.root.rglob("*.md") if path.is_file())

    @classmethod
    def _collapse_duplicate_root(cls, relative_path: str) -> str:
        """Collapse accidental repeated OKF roots from model-composed paths.

        Example:
        INSTITUTIONS/fastpay/INSTITUTIONS/fastpay/policy.md
        -> INSTITUTIONS/fastpay/policy.md
        """
        raw_parts = [
            part
            for part in relative_path.replace("\\", "/").split("/")
            if part not in {"", "."}
        ]
        if not raw_parts:
            return ""

        root_indexes = [
            index
            for index, part in enumerate(raw_parts)
            if part.upper() in cls.TOP_LEVEL_DIRECTORIES
        ]
        if len(root_indexes) > 1:
            first_root = raw_parts[root_indexes[0]].upper()
            matching = [
                index
                for index in root_indexes[1:]
                if raw_parts[index].upper() == first_root
            ]
            if matching:
                raw_parts = raw_parts[matching[-1] :]

        return "/".join(raw_parts)

    def _resolve_case_insensitive(
        self, relative_path: str, require_exists: bool = True
    ) -> Path:
        """Resolve an OKF path safely while preserving on-disk canonical casing."""
        if (
            Path(relative_path.replace("\\", "/")).is_absolute()
            or ".." in Path(relative_path.replace("\\", "/")).parts
        ):
            raise ValueError("Invalid OKF path")
        # Published bundles can legitimately contain repeated roots. Never redirect
        # an existing path to a different concept/parent just because it looks odd.
        cleaned = relative_path.replace("\\", "/")
        try:
            return self._walk_path(cleaned, require_exists)
        except FileNotFoundError:
            collapsed = self._collapse_duplicate_root(cleaned)
            if collapsed == cleaned:
                raise
            return self._walk_path(collapsed, require_exists)

    def _walk_path(self, relative_path: str, require_exists: bool) -> Path:
        parts = [part for part in relative_path.split("/") if part not in {"", "."}]
        current = self.root

        for index, part in enumerate(parts):
            if part == "..":
                raise ValueError("Invalid OKF path")

            exact = current / part
            if exact.exists():
                current = exact
                continue

            if not current.exists() or not current.is_dir():
                if require_exists:
                    raise FileNotFoundError(f"OKF path not found: {relative_path}")
                current = exact
                continue

            matches = [
                child
                for child in current.iterdir()
                if child.name.casefold() == part.casefold()
            ]
            if len(matches) == 1:
                current = matches[0]
                continue
            if len(matches) > 1:
                raise ValueError(f"Ambiguous OKF path segment: {part}")

            if require_exists:
                raise FileNotFoundError(f"OKF path not found: {relative_path}")

            current = exact
            for remaining in parts[index + 1 :]:
                current = current / remaining
            break

        resolved = current.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("Invalid OKF path")
        return resolved

    def canonical_directory(
        self, directory: str = "", require_exists: bool = True
    ) -> str:
        if (
            Path(directory.replace("\\", "/")).is_absolute()
            or ".." in Path(directory.replace("\\", "/")).parts
        ):
            raise ValueError("Invalid OKF directory")
        cleaned = directory.replace("\\", "/")
        if not cleaned:
            return ""
        resolved = self._resolve_case_insensitive(
            cleaned, require_exists=require_exists
        )
        if require_exists and (not resolved.exists() or not resolved.is_dir()):
            raise FileNotFoundError(f"OKF directory not found: {directory}")
        return str(resolved.relative_to(self.root)).replace("\\", "/")

    def canonical_path(self, relative_path: str, require_exists: bool = True) -> str:
        resolved = self._resolve_case_insensitive(
            relative_path, require_exists=require_exists
        )
        if resolved.suffix.lower() != ".md":
            raise ValueError("Only Markdown OKF files are supported")
        if require_exists and (not resolved.exists() or not resolved.is_file()):
            raise FileNotFoundError(f"OKF file not found: {relative_path}")
        return str(resolved.relative_to(self.root)).replace("\\", "/")

    def _safe_path(self, relative_path: str, require_exists: bool = True) -> Path:
        canonical = self.canonical_path(relative_path, require_exists=require_exists)
        return (self.root / canonical).resolve()

    def _relative(self, relative_path: str) -> str:
        return self.canonical_path(relative_path, require_exists=False)

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        without_marks = "".join(
            ch for ch in normalized if not unicodedata.combining(ch)
        )
        return re.sub(r"[^a-z0-9]+", " ", without_marks.lower()).strip()

    @classmethod
    def _search_tokens(cls, text: str) -> set[str]:
        tokens: set[str] = set()
        for token in cls._normalize(text).split():
            if token in cls.SEARCH_STOP_WORDS:
                continue
            installments = re.fullmatch(r"(\d+)x", token)
            if installments:
                tokens.update({installments.group(1), "parcela"})
            else:
                tokens.add(cls.SEARCH_ALIASES.get(token, token))
        return tokens

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
                result.add(self.canonical_path(path, require_exists=False))
            except ValueError:
                continue
        return result

    def _ensure_active(self, relative_path: str, active_files: set[str] | None) -> str:
        relative = self.canonical_path(relative_path)
        active = self._active(active_files)
        if active is not None and relative not in active:
            raise FileNotFoundError(
                f"OKF file not active in current bundle: {relative_path}"
            )
        return relative

    def _override(
        self, relative_path: str, overrides: dict[str, str] | None
    ) -> str | None:
        if not overrides:
            return None
        value = overrides.get(self._relative(relative_path))
        return value[: self.max_chars_per_file] if isinstance(value, str) else None

    def list_files(
        self,
        overrides: dict[str, str] | None = None,
        active_files: set[str] | None = None,
    ) -> str:
        active = self._active(active_files)
        if active is not None:
            files = active
        else:
            files = {
                str(path.relative_to(self.root)).replace("\\", "/")
                for path in self._markdown_files()
            }
            if overrides:
                for path in overrides:
                    try:
                        files.add(self._relative(path))
                    except ValueError:
                        pass
        return "\n".join(sorted(files)) if files else "No OKF files available."

    def read_file(
        self,
        relative_path: str,
        overrides: dict[str, str] | None = None,
        active_files: set[str] | None = None,
    ) -> str:
        relative = self._ensure_active(relative_path, active_files)
        overridden = self._override(relative, overrides)
        if overridden is not None:
            return f"OKF_CANONICAL_PATH: {relative}\n\n{overridden}"
        content = self._safe_path(relative).read_text(encoding="utf-8")[
            : self.max_chars_per_file
        ]
        return f"OKF_CANONICAL_PATH: {relative}\n\n{content}"

    def validate_edit(self, relative_path: str, content: str) -> str:
        relative = self._relative(relative_path)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("OKF file cannot be empty")
        if len(content) > 200_000:
            raise ValueError("OKF file exceeds the 200000 character edit limit")
        from simple_agent.services.okf_validator import validate_document

        validate_document(relative, content)
        return relative

    def search(
        self,
        query: str,
        scope: str = "",
        overrides: dict[str, str] | None = None,
        active_files: set[str] | None = None,
    ) -> str:
        query_tokens = self._search_tokens(query)
        if not query_tokens:
            raise ValueError("Search query cannot be empty")

        # Canonicalize scope: case-insensitive, collapse duplicates
        cleaned_scope = ""
        if scope:
            try:
                cleaned_scope = self.canonical_directory(scope)
            except FileNotFoundError:
                cleaned_scope = self._collapse_duplicate_root(scope.strip("/"))

        ranked: list[tuple[int, int, str, str]] = []
        for relative in self.list_files(overrides, active_files).splitlines():
            if (
                not relative.endswith(".md")
                or Path(relative).name.lower() in self.RESERVED_MARKDOWN
            ):
                continue
            if cleaned_scope and not relative.startswith(cleaned_scope + "/"):
                continue
            try:
                content = self.read_file(relative, overrides, active_files)
            except FileNotFoundError:
                continue
            document_score = len(
                query_tokens & self._search_tokens(f"{relative}\n{content}")
            )
            if not document_score:
                continue
            best_line = ""
            best_line_score = -1
            for number, line in enumerate(content.splitlines(), start=1):
                if line.startswith("OKF_CANONICAL_PATH:"):
                    continue
                line_score = len(query_tokens & self._search_tokens(line))
                if line_score > best_line_score:
                    best_line_score = line_score
                    best_line = f"{relative}:{number}: {line.strip()}"
            ranked.append((document_score, best_line_score, relative, best_line))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        matches = [text for _, _, _, text in ranked[: self.max_results]]

        # Always include OKF_CANONICAL_SCOPE even when no matches
        scope_marker = f"OKF_CANONICAL_SCOPE: {cleaned_scope or '<root>'}"
        if matches:
            return f"{scope_marker}\n\n" + "\n".join(matches)
        else:
            return f"{scope_marker}\n\nNo OKF matches found."

    def read_section(
        self,
        relative_path: str,
        heading: str,
        overrides: dict[str, str] | None = None,
        active_files: set[str] | None = None,
    ) -> str:
        """Read a section by exact heading only. Fuzzy resolution removed.

        If exact heading is missing, return canonical path plus available headings
        and instruct the agent to retry with one exact heading.
        """
        canonical = self.canonical_path(relative_path)
        content = self.read_file(canonical, overrides, active_files)

        # Normalize target for exact comparison
        target = self._normalize(heading)
        if not target:
            raise ValueError("Heading cannot be empty")

        lines = content.splitlines()
        headings = self._extract_headings(content)

        # EXACT MATCH ONLY: strict heading resolution
        start = None
        start_level = None
        resolved = None
        for index, title, level in headings:
            if self._normalize(title) == target:
                start, start_level, resolved = index, level, title
                break

        # No fuzzy fallback; report available headings and require exact retry
        if start is None:
            available = ", ".join(f'"{title}"' for _, title, _ in headings) or "none"
            return (
                f"OKF_CANONICAL_PATH: {canonical}\n\n"
                f"Section '{heading}' not found (no fuzzy match). Available headings in {canonical}: {available}. "
                "Retry with one of these exact headings."
            )

        # Extract section content
        collected = [lines[start]]
        for line in lines[start + 1 :]:
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match and len(match.group(1)) <= start_level:
                break
            collected.append(line)
        # Lifecycle/scope/conditions apply to every section. Dropping frontmatter
        # makes a published policy indistinguishable from unapproved prose.
        document = content.partition("\n\n")[2]
        metadata = ""
        if document.startswith("---\n") and "\n---" in document[4:]:
            metadata = document[: document.index("\n---", 4) + 4] + "\n\n"
        result = (metadata + "\n".join(collected))[: self.max_chars_per_file]
        prefix = f"OKF_CANONICAL_PATH: {canonical}\n\n"

        # Return with resolved heading note
        if resolved and self._normalize(resolved) != target:
            return f"{prefix}Resolved heading '{heading}' to '{resolved}'.\n\n{result}"
        return f"{prefix}{result}"
