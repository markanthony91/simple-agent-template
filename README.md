# Agent Runtime — OKF simulator (0.6.0)

The synthetic negotiation flow now generates the offer, agreement and invalid
dummy PIX/boleto in one transaction after the customer requests complete terms.
There is no internal human approval or separate confirmation. Local email outbox
capture and operator-only settlement simulation remain session-bound and idempotent.
No payment or email is sent externally.
The pilot uses the canonical test scope `Will Bank` / `cartao_de_credito`.

The backend now has a create-only contract for a future Demo form. It accepts
full name, CPF, E.164 phone, debt amount and days overdue, resolves the creditor
server-side from Zerai Canais and pins the resulting fixture to one new LangGraph
thread. Existing Playground fixture editing and existing conversations are unchanged.
For future-form sessions, the presentation uses the Canais **Cedente** as creditor
and the selected Assistant's `agent_profile.name` as the agent name. The backend
renders only `{{credor}}` and `{{nome_agente}}`; this is not delegated to the LLM.
See [future Demo form](docs/FUTURE_DEMO_FORM.md). This remains a synthetic lab;
the operation is not a public customer-data endpoint.

In a future-form Demo conversation, the exact command `/reset-demo` resets the
same session: it retains the pinned form/creditor and OKF snapshot, clears
identity, offers, agreements, dummy payments, outbox records and transient state,
and excludes prior messages from subsequent model context. Earlier checkpoints
remain available for audit.
The command does not call the LLM or any channel; Playground sessions return
`Comando indisponível nesta sessão.`

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

## Agent profile and LLM settings (0.3.0)

The managed `agent` graph reads optional Assistant context fields:

- `llm_settings`: `temperature` (0-2), `top_p` (>0-1), `max_tokens` (integer,
  1-32768). Missing/null values leave the existing server/provider defaults in
  effect; they do not silently select a temperature. Parameters apply to each
  model call, including tool rounds, without changing the shared model instance.
- `llm_integration`: `primary` (default `default`) and optional `fallback`.
  Values select server-registered `default`, `lovable` or `external` connections.
  The UI cannot inject an endpoint, model name or API key.
- `agent_profile`: `name` (80 characters), `role` (500), `tone` (200).
  Nonempty fields append the current identity/style to the composed prompt.
  Empty fields preserve existing behavior. The profile instructs the model to
  prefer the configured identity/style over conflicting prose, but does not
  replace backend identity, policy or consent guards. This is model guidance,
  not a guarantee of literal output. RAW compilation retains its own defaults.

`okf_admin` operations `get_llm_config` and `validate_runtime_settings` expose
safe model metadata/defaults and validate changes before the UI saves native
Assistant versions. Sanitized endpoints, models, timeouts, proxy/credential status
are returned; credential values are never returned. Runtime validation
also rejects unknown settings, non-finite/out-of-range numbers and model/URL
overrides. The UI shows provider-default sampling values as unspecified, since
the server cannot report the provider's effective default. Output limits remain
subject to the provider's context window; small limits can truncate responses.

Settings affect subsequent runs; use a new conversation for comparisons so
existing messages do not carry the previous persona. Saving preserves unrelated
Assistant context and confirms persistence/version before showing success.
Fallback retries one failed inference on the selected backup only for connection
errors, timeouts, HTTP 408/429/5xx, before any streamed chunk. It preserves the
same history, tools and parameters and never reruns the graph or an executed tool.
Partial streams, cancellations, invalid parameters, authorization/billing errors
and refusals are not retried. It starts with the primary again on the next model
call. The final message records `additional_kwargs.llm_route`; logs include
connection IDs/error type/status, not provider error bodies or credentials.
RAW compilation still uses only the default connection.

Delivery evidence: [LLM/profile settings](docs/LLM_AGENT_SETTINGS.md).
Lovable setup: [dedicated authenticated bridge](integrations/lovable/README.md).

The default LLM is pinned by server `LLM_MODEL` (legacy fallback `SIMPLE_AGENT_MODEL`).
Optional connections use `LLM_LOVABLE_*` and `LLM_EXTERNAL_*` variables shown in
`.env.example`. Each connection pins its own model and key. Neither message text
nor Runnable `configurable.model` can inject a model. Operators select configured
connections through versioned Assistant context. Credential values stay on the backend. Use synthetic data in this lab:
the shared link is not an authenticated, read-only guest role.

## RAW instruction history (0.2.7)

`save_agents` creates a sequential version with UTC timestamp and content, and
`get_agents_versions` returns newest first (`limit` 1-100, default 20; `offset`
>= 0). `get_agents` returns the active version. Existing legacy/default content
is retained as v1 when the first versioned save creates v2. History and active
content are committed together using the existing atomic writer and volume lock.
The canonical file is `raw/agents_versions.json` under `OKF_DATA_ROOT`; the old
`raw/AGENTS.md` is kept intact for recovery. No model call is required for saves.

Rollback to an older backend requires exporting the chosen history content to
legacy `raw/AGENTS.md` before switching images; retain history and backups.
The frontend 0.2.0 displays revisions and restores by creating a new save.

Published on 2026-09-16: backend deployment
`7eb7e7ab-4907-4e58-8d5e-ee601e33fd20` (source `c5e99c9`) verified at 0.2.7.
Private pre-rollout backup: `/data/backups/pre-instruction-versions-20260916T194309Z`.
31 conversation states, the managed Assistant configuration and 4148 Markdown
hashes matched after deployment. The published frontend save/history/reload check
passed with identical RAW content. Full evidence and rollback details:
[frontend release notes](https://github.com/markanthony91/agent-chat-ui/blob/feat/instruction-versions/docs/INSTRUCTION_VERSIONS.md).

## Lovable connection preparation (0.3.2)

The dedicated bridge supports a public SHA-256 verifier of a separate Railway
bearer token, so no provider credential needs to be copied into a chat or source.
Connection registration and enabling fallback are separate operations. Marcelo
retains control of activation in the LLM tab; preparing the connection does not
change the current Qwen selection. See [connection evidence](docs/LOVABLE_CONNECTION_2026-09-17.md).

The completion check accepts repeated identical stop/tool-call markers emitted
by the gateway while still rejecting missing, mixed or truncated finishes.
