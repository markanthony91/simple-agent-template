from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_TOOLS: dict[str, dict[str, Any]] = {
    "utc_now": {"name": "utc_now", "description": "Current UTC date and time.", "category": "utility", "enabled": True, "mode": "read_only", "risk": "low", "requires_auth": False},
    "calculator": {"name": "calculator", "description": "Safe arithmetic calculator.", "category": "utility", "enabled": True, "mode": "read_only", "risk": "low", "requires_auth": False},
    "okf_index": {"name": "okf_index", "description": "Navigate OKF indexes using progressive disclosure.", "category": "knowledge", "enabled": True, "mode": "read_only", "risk": "low", "requires_auth": False},
    "okf_list": {"name": "okf_list", "description": "List files in the active OKF bundle.", "category": "knowledge", "enabled": True, "mode": "read_only", "risk": "low", "requires_auth": False},
    "okf_search": {"name": "okf_search", "description": "Search the active OKF bundle as a fallback.", "category": "knowledge", "enabled": True, "mode": "read_only", "risk": "low", "requires_auth": False},
    "okf_read": {"name": "okf_read", "description": "Read a document from the active OKF bundle.", "category": "knowledge", "enabled": True, "mode": "read_only", "risk": "low", "requires_auth": False},
    "okf_read_section": {"name": "okf_read_section", "description": "Read one section from an OKF document.", "category": "knowledge", "enabled": True, "mode": "read_only", "risk": "low", "requires_auth": False},
    "verify_and_get_customer": {"name": "verify_and_get_customer", "description": "Atomically verify the simulator customer and return the pinned debt only on success.", "category": "collection", "enabled": True, "mode": "write", "risk": "medium", "requires_auth": False},
    "generate_payment_offer": {"name": "generate_payment_offer", "description": "Generate a policy-approved offer, agreement and invalid dummy PIX/boleto in one transaction.", "category": "collection", "enabled": True, "mode": "write", "risk": "medium", "requires_auth": False},
    "send_payment_instruction": {"name": "send_payment_instruction", "description": "Capture a dummy email delivery in the local outbox without sending it.", "category": "collection", "enabled": True, "mode": "write", "risk": "medium", "requires_auth": False},
    "get_payment_status": {"name": "get_payment_status", "description": "Read a dummy payment status from the current session.", "category": "collection", "enabled": True, "mode": "read_only", "risk": "low", "requires_auth": False},
}


class ToolRegistry:
    """Persistent metadata and enable/disable state for registered agent tools."""

    def __init__(self, root: Path | None = None):
        configured = os.getenv("TOOL_REGISTRY_ROOT", "/data/tools")
        self.root = (root or Path(configured)).resolve()
        self.registry_file = self.root / "registry.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_registry()

    def _write_atomic(self, payload: dict[str, Any]) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix="registry", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.registry_file)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def _ensure_registry(self) -> None:
        if self.registry_file.exists():
            return
        self._write_atomic({"version": 1, "updated_at": datetime.now(timezone.utc).isoformat(), "tools": DEFAULT_TOOLS})

    def _load(self) -> dict[str, Any]:
        self._ensure_registry()
        try:
            data = json.loads(self.registry_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        tools = data.get("tools") if isinstance(data, dict) else None
        merged = {name: dict(meta) for name, meta in DEFAULT_TOOLS.items()}
        if isinstance(tools, dict):
            for name, metadata in tools.items():
                if name in merged and isinstance(metadata, dict):
                    merged[name].update(metadata)
        return {"version": int(data.get("version", 1)) if isinstance(data, dict) else 1, "updated_at": data.get("updated_at") if isinstance(data, dict) else None, "tools": merged}

    def list_tools(self) -> list[dict[str, Any]]:
        payload = self._load()
        return [dict(payload["tools"][name]) for name in sorted(payload["tools"])]

    def enabled_names(self) -> set[str]:
        return {item["name"] for item in self.list_tools() if item.get("enabled") is True and isinstance(item.get("name"), str)}

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        payload = self._load()
        tools = payload["tools"]
        if name not in tools:
            raise KeyError(f"Unknown tool: {name}")
        tools[name]["enabled"] = bool(enabled)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_atomic(payload)
        return dict(tools[name])

    def reset(self) -> list[dict[str, Any]]:
        self._write_atomic({"version": 1, "updated_at": datetime.now(timezone.utc).isoformat(), "tools": DEFAULT_TOOLS})
        return self.list_tools()
