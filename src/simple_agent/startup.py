"""Prepare persistent development-server checkpoints without overwriting data."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def prepare(cwd: Path, data_root: Path) -> None:
    target = (data_root / "langgraph").resolve()
    target.mkdir(parents=True, exist_ok=True)
    link = cwd / ".langgraph_api"
    if link.is_symlink():
        if link.resolve() != target:
            raise RuntimeError("checkpoint_location_mismatch")
    elif link.exists():
        raise RuntimeError(
            "Existing local checkpoints require explicit backup/migration before startup"
        )
    else:
        link.symlink_to(target, target_is_directory=True)


def main() -> None:
    prepare(Path.cwd(), Path(os.getenv("DATA_ROOT", "/data")))
    command = sys.argv[1:] or [
        "langgraph",
        "dev",
        "--host",
        "0.0.0.0",
        "--port",
        os.getenv("PORT", "2024"),
        "--no-browser",
    ]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
