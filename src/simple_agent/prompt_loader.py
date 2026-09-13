from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = PROJECT_ROOT / "config"

COMMERCIAL_GROUNDING = """# Mandatory Commercial Grounding

Commercial negotiation terms must be grounded in the active OKF knowledge before an offer is generated.

- Treat customer state and institutional policy as separate sources.
- Before calling `generate_offer`, retrieve the applicable OKF policy for the current institution, product, and negotiation context.
- This requirement applies to discounts, installment counts, payment type, down payment, fees, interest, penalties, settlement rules, exceptions, and deadlines.
- Use progressive OKF navigation and choose the relevant path autonomously; this is not a deterministic router.
- Customer eligibility alone is not institutional authorization for a commercial condition.
- A proposed condition must satisfy both retrieved OKF policy and customer-specific eligibility.
- **Incomplete or undefined policy means no concrete offer.** If applicable policy cannot be found, is incomplete, or is marked as pending definition (e.g., "A DEFINIR PELA OPERAÇÃO"), do not invent terms and do not call `generate_offer` with guessed conditions.
- Do not suggest any concrete commercial term (discount %, installment count, fee, interest rate, deadline) when the underlying policy is undefined or incomplete.
- If relevant OKF evidence is already present in the current conversation and still applies to the same context, do not repeat identical lookups unnecessarily.
- Keep implementation details invisible to the end user unless they explicitly ask about them.
"""


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
        COMMERCIAL_GROUNDING.strip(),
    ]
    if isinstance(workflow, str) and workflow.strip():
        sections.append(
            "# Active Workflow\n\n"
            "Follow this workflow as an agentic process guide. Preserve mandatory gates and ordering constraints, "
            "but allow natural conversational detours that do not violate them. Do not expose workflow internals to the user.\n\n"
            + workflow.strip()
        )
    return "\n\n".join(sections)

