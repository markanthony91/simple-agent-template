from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from simple_agent.services.okf_service import OKFService
from simple_agent.services.okf_validator import validate_okf_files


class PersistentOKFStore:
    """Persistent, fail-closed OKF bundle storage with drafts and immutable versions."""

    def __init__(self, root: Path | None = None):
        configured = os.getenv("OKF_DATA_ROOT", "/data/okf")
        self.root = (root or Path(configured)).resolve()
        self.bundles_root = self.root / "bundles"
        self.drafts_root = self.root / "drafts"
        self.active_file = self.root / "active.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.bundles_root.mkdir(parents=True, exist_ok=True)
        self.drafts_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _slug(value: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.").lower()
        return clean[:80] or "okf-bundle"

    @staticmethod
    def _safe_relative(path: str) -> str:
        normalized = path.replace("\\", "/").strip("/")
        candidate = Path(normalized)
        if not normalized or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Invalid OKF path: {path}")
        if candidate.suffix.lower() != ".md":
            raise ValueError("Only Markdown files are supported")
        return candidate.as_posix()

    def _write_json_atomic(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def _write_files_atomic(self, root: Path, files: dict[str, str]) -> None:
        root.mkdir(parents=True, exist_ok=False)
        try:
            for relative, content in files.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise

    def _normalize_files(self, files: dict[str, str]) -> dict[str, str]:
        if not isinstance(files, dict) or not files:
            raise ValueError("Bundle has no files")
        normalized: dict[str, str] = {}
        for raw_path, content in files.items():
            if not isinstance(raw_path, str) or not isinstance(content, str):
                raise ValueError("Bundle files must map string paths to string contents")
            relative = self._safe_relative(raw_path)
            if not content.strip():
                raise ValueError(f"OKF file cannot be empty: {relative}")
            normalized[relative] = content
        if "index.md" not in normalized:
            raise ValueError("Root index.md is required")
        return normalized

    def _root_files(self, root: Path) -> dict[str, str]:
        return {
            str(path.relative_to(root)): path.read_text(encoding="utf-8")
            for path in sorted(root.rglob("*.md"))
            if path.is_file()
        }

    def active_metadata(self) -> dict:
        if not self.active_file.exists():
            return {}
        try:
            data = json.loads(self.active_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def active_bundle_id(self) -> str | None:
        value = self.active_metadata().get("bundle_id")
        return value if isinstance(value, str) and value else None

    def bundle_root(self, bundle_id: str) -> Path:
        root = (self.bundles_root / self._slug(bundle_id)).resolve()
        if not root.is_relative_to(self.bundles_root.resolve()) or not root.is_dir():
            raise FileNotFoundError(f"Bundle not found: {bundle_id}")
        return root

    def active_root(self) -> Path | None:
        bundle_id = self.active_bundle_id()
        if not bundle_id:
            return None
        try:
            return self.bundle_root(bundle_id)
        except FileNotFoundError:
            return None

    def _bundle_metadata(self, bundle_id: str) -> dict:
        root = self.bundle_root(bundle_id)
        meta_file = root / ".bundle.json"
        meta: dict = {}
        if meta_file.exists():
            try:
                loaded = json.loads(meta_file.read_text(encoding="utf-8"))
                meta = loaded if isinstance(loaded, dict) else {}
            except (json.JSONDecodeError, OSError):
                meta = {}
        active = self.active_metadata()
        if bundle_id == active.get("bundle_id"):
            for key in ("bundle_name", "bundle_version", "published_at"):
                if key not in meta and active.get(key) is not None:
                    meta[key] = active.get(key)
        stat = root.stat()
        return {
            "bundle_id": bundle_id,
            "bundle_name": meta.get("bundle_name") or bundle_id,
            "bundle_version": meta.get("bundle_version") or "0.2",
            "published_at": meta.get("published_at") or datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "source_draft_id": meta.get("source_draft_id"),
            "file_count": len(list(root.rglob("*.md"))),
            "active": bundle_id == self.active_bundle_id(),
        }

    def list_versions(self) -> list[dict]:
        versions = [self._bundle_metadata(path.name) for path in self.bundles_root.iterdir() if path.is_dir() and not path.name.startswith(".")]
        versions.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
        return versions

    def activate_bundle(self, bundle_id: str) -> dict:
        meta = self._bundle_metadata(bundle_id)
        active = {
            "bundle_id": meta["bundle_id"],
            "bundle_name": meta["bundle_name"],
            "bundle_version": meta["bundle_version"],
            "published_at": meta["published_at"],
            "activated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_json_atomic(self.active_file, active)
        return {**meta, "active": True, "activated_at": active["activated_at"]}

    def service(self) -> OKFService | None:
        root = self.active_root()
        return OKFService(root) if root else None

    def status(self) -> dict:
        meta = self.active_metadata()
        root = self.active_root()
        files = []
        if root:
            files = sorted(str(path.relative_to(root)) for path in root.rglob("*.md") if path.is_file())
        return {
            "active": bool(root),
            "bundle_id": meta.get("bundle_id"),
            "bundle_name": meta.get("bundle_name"),
            "bundle_version": meta.get("bundle_version"),
            "published_at": meta.get("published_at"),
            "activated_at": meta.get("activated_at"),
            "file_count": len(files),
            "files": files,
            "storage_root": str(self.root),
        }

    def create_draft(self, name: str, version: str = "0.2", from_active: bool = True) -> dict:
        draft_id = f"{self._slug(name)}-{uuid.uuid4().hex[:8]}"
        draft_root = self.drafts_root / draft_id
        files: dict[str, str] = {}
        if from_active and self.active_root():
            files = self._root_files(self.active_root())
        draft_root.mkdir(parents=True, exist_ok=False)
        for relative, content in files.items():
            target = draft_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        metadata = {
            "draft_id": draft_id,
            "draft_name": name,
            "bundle_version": version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source_bundle_id": self.active_bundle_id() if from_active else None,
        }
        self._write_json_atomic(draft_root / ".draft.json", metadata)
        return {**metadata, "file_count": len(files)}

    def list_drafts(self) -> list[dict]:
        drafts: list[dict] = []
        for root in sorted(path for path in self.drafts_root.iterdir() if path.is_dir()):
            meta_file = root / ".draft.json"
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
            except json.JSONDecodeError:
                meta = {}
            drafts.append({**meta, "draft_id": root.name, "file_count": len(list(root.rglob("*.md")))})
        return drafts

    def draft_root(self, draft_id: str) -> Path:
        root = (self.drafts_root / self._slug(draft_id)).resolve()
        if not root.is_relative_to(self.drafts_root.resolve()) or not root.is_dir():
            raise FileNotFoundError(f"Draft not found: {draft_id}")
        return root

    def draft_files(self, draft_id: str) -> dict[str, str]:
        return self._root_files(self.draft_root(draft_id))

    def write_draft_file(self, draft_id: str, path: str, content: str) -> dict:
        root = self.draft_root(draft_id)
        relative = self._safe_relative(path)
        OKFService(root).validate_edit(relative, content)
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Invalid OKF path")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        meta_path = root / ".draft.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_json_atomic(meta_path, meta)
        return {"draft_id": draft_id, "path": relative, "saved": True}

    def validate_draft(self, draft_id: str) -> dict:
        root = self.draft_root(draft_id)
        meta_path = root / ".draft.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        return validate_okf_files(self._root_files(root), str(meta.get("bundle_version") or "0.2"))

    def publish_draft(self, draft_id: str) -> dict:
        root = self.draft_root(draft_id)
        validation = self.validate_draft(draft_id)
        if not validation["valid"]:
            raise ValueError("Draft validation failed")
        meta = json.loads((root / ".draft.json").read_text(encoding="utf-8"))
        result = self.import_bundle(
            str(meta.get("draft_name") or draft_id),
            str(meta.get("bundle_version") or "0.2"),
            self._root_files(root),
            source_draft_id=draft_id,
        )
        return {**result, "draft_id": draft_id, "validation": validation}

    def import_bundle(self, name: str, version: str, files: dict[str, str], source_draft_id: str | None = None) -> dict:
        normalized = self._normalize_files(files)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bundle_id = f"{self._slug(name)}-{stamp}-{uuid.uuid4().hex[:8]}"
        temp_root = self.bundles_root / f".{bundle_id}.tmp"
        final_root = self.bundles_root / bundle_id
        self._write_files_atomic(temp_root, normalized)
        published_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "bundle_id": bundle_id,
            "bundle_name": name,
            "bundle_version": version,
            "published_at": published_at,
            "source_draft_id": source_draft_id,
        }
        self._write_json_atomic(temp_root / ".bundle.json", metadata)
        os.replace(temp_root, final_root)
        self._write_json_atomic(self.active_file, {**metadata, "activated_at": published_at})
        return {**metadata, "file_count": len(normalized), "files": sorted(normalized), "active": True}

    def list_files(self) -> list[str]:
        status = self.status()
        return status["files"] if status["active"] else []

    def read_file(self, path: str) -> str:
        service = self.service()
        if service is None:
            raise FileNotFoundError("No active OKF bundle")
        return service.read_file(self._safe_relative(path))

    def write_file(self, path: str, content: str) -> dict:
        raise PermissionError("Published OKF bundles are immutable. Create a draft, edit it, validate it, and publish a new version.")
