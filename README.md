# Agent Runtime — OKF simulator (0.2.0)

LangChain/LangGraph runtime, controlled OKF tools and synthetic debt negotiation.
The separate `agent-chat-ui` repository provides the Next.js frontend.
This release does not modify WhatsApp or the original FastAPI console.

Published status and evidence: [Railway release 2026-09-14](docs/RELEASE_2026-09-14.md).

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
docker build -t agent-runtime:0.2.0 .
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
