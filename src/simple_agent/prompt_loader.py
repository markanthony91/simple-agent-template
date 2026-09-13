from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = PROJECT_ROOT / "config"


def _read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_agent_prompt() -> str:
    system_prompt = _read_text(CONFIG_ROOT / "system_prompt.md")
    agent_rules = _read_text(CONFIG_ROOT / "AGENTS.md")
    return f"{system_prompt}\n\n# Operational Instructions\n\n{agent_rules}"
