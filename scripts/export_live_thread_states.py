"""Snapshot agent thread states from the live local API for an isolated canary.

Writes only to /tmp with restrictive permissions. Never prints conversation data.
The result is a point-in-time rehearsal input, not a transactional cutover export.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

MAIN_SERVICE_ID = "861cf8e9-935f-4673-baf0-6bb438eac5fb"
FIELDS = ["thread_id", "created_at", "updated_at", "state_updated_at", "status", "metadata", "values"]


def export(path: Path) -> dict:
    if os.getenv("RAILWAY_SERVICE_ID") != MAIN_SERVICE_ID or path.parent != Path("/tmp"):
        raise ValueError("wrong_service_or_output_path")
    base = f"http://127.0.0.1:{os.getenv('PORT', '2024')}"
    started = datetime.now(UTC).isoformat()
    seen: set[str] = set()
    statuses: Counter[str] = Counter()
    value_keys: Counter[str] = Counter()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb") as out:
            for offset in range(0, 2_000, 100):
                query = {
                    "limit": 100,
                    "offset": offset,
                    "metadata": {"graph_id": "agent"},
                    "sort_by": "created_at",
                    "sort_order": "asc",
                    "select": FIELDS,
                }
                request = urllib.request.Request(
                    base + "/threads/search",
                    data=json.dumps(query).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    page = json.load(response)
                if not isinstance(page, list):
                    raise TypeError("invalid_search_response")
                for thread in page:
                    thread_id = thread["thread_id"]
                    if thread_id in seen or thread.get("metadata", {}).get("graph_id") != "agent":
                        raise ValueError("duplicate_or_mismatched_thread")
                    seen.add(thread_id)
                    statuses[thread.get("status") or "missing"] += 1
                    value_keys.update((thread.get("values") or {}).keys())
                    out.write((json.dumps(thread, separators=(",", ":")) + "\n").encode())
                if len(page) < 100:
                    break
            else:
                raise ValueError("thread_limit_exceeded")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "threads": len(seen),
        "statuses": dict(statuses),
        "value_keys": dict(value_keys),
        "gzip_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    try:
        print(json.dumps(export(Path(sys.argv[1]))))
    except Exception as exc:  # noqa: BLE001 - do not expose conversation data in errors
        print(f"thread_export_failed:{type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
