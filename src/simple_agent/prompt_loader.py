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
    """Load versioned instructions once. None selects defaults; empty workflow disables it.

    Context overrides remain supported. Authorization does NOT depend on these
    prompts: identity, policy, scope and consent checks are enforced by tools.
    """
    base = (system_prompt or "").strip() or _read_text(CONFIG_ROOT / "system_prompt.md")
    rules = (agent_instructions or "").strip() or _read_text(CONFIG_ROOT / "AGENTS.md")
    sections = [base, "# Operational Instructions\n\n" + rules]
    active = (
        _read_text(CONFIG_ROOT / "WORKFLOW.md")
        if workflow is None
        else workflow.strip()
    )
    if active:
        sections.append("# Active Workflow\n\n" + active)
    return "\n\n".join(sections)
