# Agent Runtime — OKF simulator (0.2.6)

The operator Dataset catalog exposes titles, declared types/status, and bounded
matching excerpts from the complete Markdown text. Search is literal,
case/accent-insensitive and includes paths, YAML metadata and bodies; no LLM,
embeddings or document rewrite. Requests pin an immutable bundle ID, including
full-document preview. Existing collection tools and their limits are unchanged.
Catalog inputs are bounded (200 search characters, 2,000 documents, 40 MB encoded
bundle, 200,000 characters/document); symlinks and traversal are rejected.
Missing/invalid metadata is labeled, never interpreted as approval.

Publication, browser checks and rollback:
[Dataset search release](docs/DATASET_SEARCH_2026-09-15.md).

Identity policy is configured in Simulator (`identity_policy`): CPF `full`,
`first4`, or `last4`; secondary `full_name`, `birth_date`, `both`, or legacy `either`;
1–10 attempts. Backend pins the policy/fixture on the first turn and appends its
contract to the existing prompts without exposing expected values. Failed checks
revoke debt/offer access and expose only a generic error; the limit requires human
review. Existing fixtures default to full CPF + either secondary, three attempts.
After verification, `get_customer()` reads only the pinned customer, without asking
the model to reconstruct a partial CPF. Full-CPF legacy callers remain supported.
Names normalize case, spaces and accents, never fuzzy matching. Birth dates use ISO.
This is a synthetic lab, not strong authentication for real customer data.

The read-only `list_tools` result now includes `usage_description` and `parameters`
from the runtime's actual tools, excluding injected ToolRuntime arguments.
Registry summaries remain separate; enabling and execution semantics are unchanged.

Published runtime/chat and direct sharing validation: [2026-09-15 release](docs/RELEASE_2026-09-15.md).

LangChain/LangGraph runtime, controlled OKF tools and synthetic debt negotiation.
The separate `agent-chat-ui` repository provides the Next.js frontend.
This release does not modify WhatsApp or the original FastAPI console.

Published status and evidence: [Railway release 2026-09-14](docs/RELEASE_2026-09-14.md).
Real-model results and remaining blockers: [Qwen E2E 2026-09-14](docs/QWEN_E2E_2026-09-14.md).

Candidate changes, isolated tests and publication boundaries:
[OKF ingestion and grounding](docs/OKF_INGESTION_GROUNDING.md).
RAW instructions now distinguish uppercase domain roots from lowercase new slugs.
Published legacy paths remain readable without silently redirecting repeated roots.
The Playground receives a post-stream numeric diagnostic, NOT a text safety gate.
The [synthetic pilot bundle](examples/pilot-okf/index.md) remains a draft proposal;
tests approve a copy only in temporary storage, never in the live bundle.

## Run

```bash
uv sync --dev --frozen
# Configure the names in .env.example in your server environment.
uv run python -m simple_agent.startup
```

Canonical LLM configuration: `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`.
Chat and RAW ingestion use the same OpenAI-compatible adapter. Legacy
`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `SIMPLE_AGENT_MODEL` are fallback only.
Streaming uses the SDK; no automatic retry after partial text. No new inference server or tunnel.

## Tests

```bash
uv run pytest -q
uv run ruff check src tests
docker build -t agent-runtime:0.2.2 .
```

Tests force synthetic credentials and temporary storage. They do not call Qwen.
The optional legacy integration test remains skipped; see
[validation](docs/VALIDATION.md) for full local protocol/browser evidence.

## Architecture and deployment

[Architecture](archi.md) · [Deployment and rollback](docs/DEPLOYMENT.md) ·
[Approved policy contract](docs/POLICY_CONTRACT.md) · [Progress](progress.md).

Only a synthetic single-operator laboratory is supported by the current anonymous API.
An approval checkbox is not administrative authentication. Do not expose customer
data or real financial actions through this deployment.
# Shared pilot chat

The LLM is pinned by server `LLM_MODEL` (legacy fallback `SIMPLE_AGENT_MODEL`).
Neither message text nor Runnable `configurable.model` selects another model.
Endpoint/key stay on the backend; changing models is a server configuration and
rollout operation, not a visitor preference. Use synthetic data in this lab:
the shared link is not an authenticated, read-only guest role.
