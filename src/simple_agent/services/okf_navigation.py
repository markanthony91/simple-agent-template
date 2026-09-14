"""Progressive index navigation, shared by the file service."""

from pathlib import Path
import re


class IndexNavigation:
    def _extract_index_links(self, content: str, base_dir: str = "") -> list[str]:
        """Extract link destinations from index.md markdown links.

        Matches [text](path) patterns. Returns canonical relative paths.
        Filters out external links and anchors.
        """
        links = []
        pattern = r"\[([^\]]+)\]\(([^)]+)\)"
        for match in re.finditer(pattern, content):
            url = match.group(2).strip()
            # Skip external links, anchors, and mailto
            if url.startswith(("http://", "https://", "#", "mailto:")):
                continue
            # Normalize slashes and strip trailing slashes
            url = url.replace("\\", "/").rstrip("/")
            if url and not url.startswith("/"):
                links.append(url)
        return links

    def _get_child_directories_and_concepts(
        self, directory: str
    ) -> tuple[list[str], list[str]]:
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
                if entry.is_dir() and entry.name not in {
                    ".git",
                    "__pycache__",
                    ".pytest_cache",
                }:
                    child_dirs.append(rel)
                elif (
                    entry.is_file()
                    and entry.suffix.lower() == ".md"
                    and entry.name.lower() not in self.RESERVED_MARKDOWN
                ):
                    concept_paths.append(rel)
        except (OSError, ValueError):
            pass

        return (child_dirs, concept_paths)

    def read_index(
        self,
        directory: str = "",
        overrides: dict[str, str] | None = None,
        active_files: set[str] | None = None,
    ) -> str:
        """Read index.md and append navigation manifest with actual child directories and concept paths.

        Requires: directory to exist and have index.md.
        On success: returns content with OKF_CANONICAL_DIRECTORY, OKF_CHILD_DIRECTORIES, OKF_CONCEPT_PATHS markers.
        On missing directory: returns OKF_REQUESTED_DIRECTORY, OKF_CANONICAL_PARENT, available children from parent.
        """
        # Try to resolve the requested directory
        try:
            cleaned = self.canonical_directory(directory)
        except FileNotFoundError:
            # Directory does not exist; respond with parent and available alternatives
            requested = self._collapse_duplicate_root(directory.strip("/"))
            parent = str(Path(requested).parent).replace("\\", "/") if requested else ""
            if parent == ".":
                parent = ""

            # Get actual children from canonical parent
            parent_children, parent_concepts = self._get_child_directories_and_concepts(
                parent
            )

            child_list = ""
            if parent_children:
                child_list += (
                    "- Child directories: "
                    + ", ".join(f"`{d}`" for d in parent_children)
                    + "\n"
                )
            if parent_concepts:
                child_list += (
                    "- Concept files: "
                    + ", ".join(f"`{c}`" for c in parent_concepts)
                    + "\n"
                )

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
            parent_children, parent_concepts = self._get_child_directories_and_concepts(
                parent
            )

            child_list = ""
            if parent_children:
                child_list += (
                    "- Child directories: "
                    + ", ".join(f"`{d}`" for d in parent_children)
                    + "\n"
                )
            if parent_concepts:
                child_list += (
                    "- Concept files: "
                    + ", ".join(f"`{c}`" for c in parent_concepts)
                    + "\n"
                )
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
            "OKF_CHILD_DIRECTORIES: "
            + (
                ", ".join(f"`{d}`" for d in sorted(child_dirs))
                if child_dirs
                else "(none)"
            ),
            "OKF_CONCEPT_PATHS: "
            + (
                ", ".join(f"`{c}`" for c in sorted(concept_paths))
                if concept_paths
                else "(none)"
            ),
            "",
        ]

        # Strip OKF_CANONICAL_PATH marker from content before appending manifest
        lines = content.split("\n")
        content_without_marker = "\n".join(
            line for line in lines if not line.startswith("OKF_CANONICAL_PATH:")
        )
        return "\n".join(manifest_lines) + content_without_marker
