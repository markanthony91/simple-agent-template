from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = PROJECT_ROOT / "config"


def _read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_agent_prompt(
    system_prompt: str | None = None,
    agent_instructions: str | None = None,
    workflow: str | None = None,
) -> str:
    base_prompt = (system_prompt or "").strip() or _read_text(CONFIG_ROOT / "system_prompt.md")
    agent_rules = (agent_instructions or "").strip() or _read_text(CONFIG_ROOT / "AGENTS.md")

    sections = [
        base_prompt,
        "# Operational Instructions\n\n" + agent_rules,
    ]
    if isinstance(workflow, str) and workflow.strip():
        sections.append(
            "# Active Workflow\n\n"
            "Follow this workflow as an agentic process guide. Preserve mandatory gates and ordering constraints, "
            "but allow natural conversational detours that do not violate them. Do not expose workflow internals to the user.\n\n"
            + workflow.strip()
        )
    return "\n\n".join(sections)
