from __future__ import annotations

import re
import unicodedata
from pathlib import Path


class OKFService:
    RESERVED_MARKDOWN = {"index.md", "log.md"}
    TOP_LEVEL_DIRECTORIES = {"GLOBAL", "INSTITUTIONS", "PRODUCTS"}

    def __init__(self, root: Path, max_chars_per_file: int = 15000, max_results: int = 10):
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
        raw_parts = [part for part in relative_path.replace("\\", "/").split("/") if part not in {"", "."}]
        if not raw_parts:
            return ""

        root_indexes = [
            index
            for index, part in enumerate(raw_parts)
            if part.upper() in cls.TOP_LEVEL_DIRECTORIES
        ]
        if len(root_indexes) > 1:
            first_root = raw_parts[root_indexes[0]].upper()
            matching = [index for index in root_indexes[1:] if raw_parts[index].upper() == first_root]
            if matching:
                raw_parts = raw_parts[matching[-1]:]

        return "/".join(raw_parts)

    def _resolve_case_insensitive(self, relative_path: str, require_exists: bool = True) -> Path:
        """Resolve an OKF path safely while preserving on-disk canonical casing."""
        collapsed = self._collapse_duplicate_root(relative_path)
        parts = [part for part in collapsed.split("/") if part]
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

            matches = [child for child in current.iterdir() if child.name.casefold() == part.casefold()]
            if len(matches) == 1:
                current = matches[0]
                continue
            if len(matches) > 1:
                raise ValueError(f"Ambiguous OKF path segment: {part}")

            if require_exists:
                raise FileNotFoundError(f"OKF path not found: {relative_path}")

            current = exact
            for remaining in parts[index + 1:]:
                current = current / remaining
            break

        resolved = current.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("Invalid OKF path")
        return resolved

    def canonical_directory(self, directory: str = "", require_exists: bool = True) -> str:
        cleaned = self._collapse_duplicate_root(directory.strip("/"))
        if not cleaned:
            return ""
        resolved = self._resolve_case_insensitive(cleaned, require_exists=require_exists)
        if require_exists and (not resolved.exists() or not resolved.is_dir()):
            raise FileNotFoundError(f"OKF directory not found: {directory}")
        return str(resolved.relative_to(self.root)).replace("\\", "/")

    def canonical_path(self, relative_path: str, require_exists: bool = True) -> str:
        resolved = self._resolve_case_insensitive(relative_path, require_exists=require_exists)
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
                result.add(self.canonical_path(path, require_exists=False))
            except ValueError:
                continue
        return result

    def _ensure_active(self, relative_path: str, active_files: set[str] | None) -> str:
        relative = self.canonical_path(relative_path)
        active = self._active(active_files)
        if active is not None and relative not in active:
            raise FileNotFoundError(f"OKF file not active in current bundle: {relative_path}")
        return relative

    def _override(self, relative_path: str, overrides: dict[str, str] | None) -> str | None:
        if not overrides:
            return None
        value = overrides.get(self._relative(relative_path))
        return value[: self.max_chars_per_file] if isinstance(value, str) else None

    def _extract_index_links(self, content: str, base_dir: str = "") -> list[str]:
        """Extract link destinations from index.md markdown links.
        
        Matches [text](path) patterns. Returns canonical relative paths.
        Filters out external links and anchors.
        """
        links = []
        pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        for match in re.finditer(pattern, content):
            url = match.group(2).strip()
            # Skip external links, anchors, and mailto
            if url.startswith(('http://', 'https://', '#', 'mailto:')):
                continue
            # Normalize slashes and strip trailing slashes
            url = url.replace('\\', '/').rstrip('/')
            if url and not url.startswith('/'):
                links.append(url)
        return links

    def _get_child_directories_and_concepts(self, directory: str) -> tuple[list[str], list[str]]:
        """Return actual child directories and concept paths (markdown files) from a directory.
        
        Returns (child_dirs, concept_paths) where paths are relative to root.
        """
        try:
            dir_path = self.root / directory if directory else self.root
            if not dir_path.exists() or not dir_path.is_dir():
                return ([], [])
        except (ValueError, FileNotFoundError):
            return ([], [])

        child_dirs = []
        concept_paths = []
        
        try:
            for entry in sorted(dir_path.iterdir()):
                rel = str(entry.relative_to(self.root)).replace("\\", "/")
                if entry.is_dir() and entry.name not in {".git", "__pycache__", ".pytest_cache"}:
                    child_dirs.append(rel)
                elif entry.is_file() and entry.suffix.lower() == ".md" and entry.name.lower() not in self.RESERVED_MARKDOWN:
                    concept_paths.append(rel)
        except (OSError, ValueError):
            pass
        
        return (child_dirs, concept_paths)

    def read_index(self, directory: str = "", overrides: dict[str, str] | None = None, active_files: set[str] | None = None) -> str:
        """Read index.md and append navigation manifest with actual child directories and concept paths.
        
        Requires: directory to exist and have index.md.
        On success: returns content with OKF_CANONICAL_DIRECTORY, OKF_CHILD_DIRECTORIES, OKF_CONCEPT_PATHS markers.
        On missing directory: returns OKF_REQUESTED_DIRECTORY, OKF_CANONICAL_PARENT, available children from parent.
        """
        # Try to resolve the requested directory
        try:
            cleaned = self.canonical_directory(directory) if directory.strip("/") else ""
        except FileNotFoundError:
            # Directory does not exist; respond with parent and available alternatives
            requested = self._collapse_duplicate_root(directory.strip("/"))
            parent = str(Path(requested).parent).replace("\\", "/") if requested else ""
            if parent == ".":
                parent = ""
            
            # Get actual children from canonical parent
            parent_children, parent_concepts = self._get_child_directories_and_concepts(parent)
            
            child_list = ""
            if parent_children:
                child_list += "- Child directories: " + ", ".join(f"`{d}`" for d in parent_children) + "\n"
            if parent_concepts:
                child_list += "- Concept files: " + ", ".join(f"`{c}`" for c in parent_concepts) + "\n"
            
            if not child_list:
                child_list = "- No child directories or concepts found in parent.\n"
            
            return (
                f"OKF_REQUESTED_DIRECTORY: {requested}\n"
                f"OKF_CANONICAL_PARENT: {parent or '<root>'}\n"
                f"\n"
                f"Index not found for requested directory: {requested}.\n"
                f"Parent index: {parent or '<root>'}.\n\n"
                f"Available destinations from parent:\n"
                f"{child_list}\n"
                f"Choose only from these destinations, then use scoped okf_search in the parent, "
                f"and use okf_list only as a last fallback."
            )

        # Directory exists; read its index.md
        relative = f"{cleaned}/index.md" if cleaned else "index.md"
        try:
            content = self.read_file(relative, overrides, active_files)
        except FileNotFoundError:
            # Index missing; fall back to parent
            parent = str(Path(cleaned).parent).replace("\\", "/") if cleaned else ""
            if parent == ".":
                parent = ""
            parent_children, parent_concepts = self._get_child_directories_and_concepts(parent)
            
            child_list = ""
            if parent_children:
                child_list += "- Child directories: " + ", ".join(f"`{d}`" for d in parent_children) + "\n"
            if parent_concepts:
                child_list += "- Concept files: " + ", ".join(f"`{c}`" for c in parent_concepts) + "\n"
            if not child_list:
                child_list = "- No child directories or concepts found in parent.\n"
            
            return (
                f"OKF_REQUESTED_DIRECTORY: {cleaned}\n"
                f"OKF_CANONICAL_PARENT: {parent or '<root>'}\n"
                f"\n"
                f"Index not found for OKF directory: {cleaned}.\n"
                f"Parent index: {parent or '<root>'}.\n\n"
                f"Available destinations from parent:\n"
                f"{child_list}\n"
                f"Choose only from these destinations, then use scoped okf_search in the parent, "
                f"and use okf_list only as a last fallback."
            )

        # Extract links from the index content and get on-disk children
        index_links = self._extract_index_links(content)
        child_dirs, concept_paths = self._get_child_directories_and_concepts(cleaned)
        
        # Merge: prefer index-linked destinations, supplement with on-disk children
        all_destinations = set()
        all_destinations.update(index_links)
        all_destinations.update(child_dirs)
        all_destinations.update(concept_paths)
        
        # Format manifest
        manifest_lines = [
            f"OKF_CANONICAL_DIRECTORY: {cleaned or '<root>'}",
            f"OKF_CHILD_DIRECTORIES: " + (", ".join(f"`{d}`" for d in sorted(child_dirs)) if child_dirs else "(none)"),
            f"OKF_CONCEPT_PATHS: " + (", ".join(f"`{c}`" for c in sorted(concept_paths)) if concept_paths else "(none)"),
            "",
        ]
        
        # Strip OKF_CANONICAL_PATH marker from content before appending manifest
        lines = content.split("\n")
        content_without_marker = "\n".join(line for line in lines if not line.startswith("OKF_CANONICAL_PATH:"))
        
        return "\n".join(manifest_lines) + content_without_marker

    def list_files(self, overrides: dict[str, str] | None = None, active_files: set[str] | None = None) -> str:
        active = self._active(active_files)
        if active is not None:
            files = active
        else:
            files = {str(path.relative_to(self.root)).replace("\\", "/") for path in self._markdown_files()}
            if overrides:
                for path in overrides:
                    try:
                        files.add(self._relative(path))
                    except ValueError:
                        pass
        return "\\n".join(sorted(files)) if files else "No OKF files available."

    def read_file(self, relative_path: str, overrides: dict[str, str] | None = None, active_files: set[str] | None = None) -> str:
        relative = self._ensure_active(relative_path, active_files)
        overridden = self._override(relative, overrides)
        if overridden is not None:
            return f"OKF_CANONICAL_PATH: {relative}\n\n{overridden}"
        content = self._safe_path(relative).read_text(encoding="utf-8")[: self.max_chars_per_file]
        return f"OKF_CANONICAL_PATH: {relative}\n\n{content}"

    def validate_edit(self, relative_path: str, content: str) -> str:
        relative = self._relative(relative_path)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("OKF file cannot be empty")
        if len(content) > 200_000:
            raise ValueError("OKF file exceeds the 200000 character edit limit")
        if Path(relative).name.lower() not in self.RESERVED_MARKDOWN and not re.search(r"^type\s*:\s*.+$", content, flags=re.MULTILINE):
            raise ValueError("OKF concept must contain a 'type:' frontmatter field")
        return relative

    def search(self, query: str, scope: str = "", overrides: dict[str, str] | None = None, active_files: set[str] | None = None) -> str:
        query_tokens = set(self._normalize(query).split())
        if not query_tokens:
            raise ValueError("Search query cannot be empty")

        # Canonicalize scope: case-insensitive, collapse duplicates
        cleaned_scope = ""
        if scope.strip("/"):
            try:
                cleaned_scope = self.canonical_directory(scope)
            except FileNotFoundError:
                cleaned_scope = self._collapse_duplicate_root(scope.strip("/"))

        ranked: list[tuple[int, str]] = []
        for relative in self.list_files(overrides, active_files).splitlines():
            if not relative.endswith(".md") or Path(relative).name.lower() in self.RESERVED_MARKDOWN:
                continue
            if cleaned_scope and not relative.startswith(cleaned_scope + "/"):
                continue
            try:
                content = self.read_file(relative, overrides, active_files)
            except FileNotFoundError:
                continue
            for number, line in enumerate(content.splitlines(), start=1):
                if line.startswith("OKF_CANONICAL_PATH:"):
                    continue
                score = len(query_tokens & set(self._normalize(line).split()))
                if score:
                    ranked.append((score, f"{relative}:{number}: {line.strip()}"))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        matches = [text for _, text in ranked[: self.max_results]]
        
        # Always include OKF_CANONICAL_SCOPE even when no matches
        scope_marker = f"OKF_CANONICAL_SCOPE: {cleaned_scope or '<root>'}"
        if matches:
            return f"{scope_marker}\n\n" + "\n".join(matches)
        else:
            return f"{scope_marker}\n\nNo OKF matches found."

    def read_section(self, relative_path: str, heading: str, overrides: dict[str, str] | None = None, active_files: set[str] | None = None) -> str:
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
        for line in lines[start + 1:]:
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match and len(match.group(1)) <= start_level:
                break
            collected.append(line)
        result = "\n".join(collected)[: self.max_chars_per_file]
        prefix = f"OKF_CANONICAL_PATH: {canonical}\n\n"
        
        # Return with resolved heading note
        if resolved and self._normalize(resolved) != target:
            return f"{prefix}Resolved heading '{heading}' to '{resolved}'.\n\n{result}"
        return f"{prefix}{result}"

