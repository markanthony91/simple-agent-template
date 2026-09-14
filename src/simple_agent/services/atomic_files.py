"""Atomic filesystem writes for drafts and immutable bundle staging."""

import json
import os
import shutil
import tempfile
from pathlib import Path


class AtomicFiles:
    def _write_json_atomic(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.name, suffix=".tmp", dir=path.parent
        )
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
