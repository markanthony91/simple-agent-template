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


class PersistentOKFStore:
    """Persistent, fail-closed OKF bundle storage."""

    def __init__(self, root: Path | None = None):
        configured = os.getenv("OKF_DATA_ROOT", "/data/okf")
        self.root = (root or Path(configured)).resolve()
        self.bundles_root = self.root / "bundles"
        self.active_file = self.root / "active.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.bundles_root.mkdir(parents=True, exist_ok=True)

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

    def active_root(self) -> Path | None:
        bundle_id = self.active_bundle_id()
        if not bundle_id:
            return None
        root = (self.bundles_root / bundle_id).resolve()
        if not root.is_relative_to(self.bundles_root.resolve()) or not root.is_dir():
            return None
        return root

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
            "file_count": len(files),
            "files": files,
            "storage_root": str(self.root),
        }

    def import_bundle(self, name: str, version: str, files: dict[str, str]) -> dict:
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

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bundle_id = f"{self._slug(name)}-{stamp}-{uuid.uuid4().hex[:8]}"
        temp_root = self.bundles_root / f".{bundle_id}.tmp"
        final_root = self.bundles_root / bundle_id
        temp_root.mkdir(parents=True, exist_ok=False)
        try:
            for relative, content in normalized.items():
                target = temp_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            os.replace(temp_root, final_root)
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise

        metadata = {
            "bundle_id": bundle_id,
            "bundle_name": name,
            "bundle_version": version,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_json_atomic(self.active_file, metadata)
        return {**metadata, "file_count": len(normalized), "files": sorted(normalized)}

    def list_files(self) -> list[str]:
        status = self.status()
        return status["files"] if status["active"] else []

    def read_file(self, path: str) -> str:
        service = self.service()
        if service is None:
            raise FileNotFoundError("No active OKF bundle")
        return service.read_file(self._safe_relative(path))

    def write_file(self, path: str, content: str) -> dict:
        root = self.active_root()
        if root is None:
            raise FileNotFoundError("No active OKF bundle")
        relative = self._safe_relative(path)
        service = OKFService(root)
        service.validate_edit(relative, content)
        target = (root / relative).resolve()
        if not target.is_relative_to(root.resolve()):
            raise ValueError("Invalid OKF path")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=target.name, suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return {"path": relative, "saved": True}
