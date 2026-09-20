# Future Demo form backend — 0.4.2

- [x] Five-field server contract: full name, CPF, phone, amount and days overdue.
- [x] Creditor resolved from Zerai Canais with a server-only token.
- [x] Create-only session pinned to the future form's LangGraph thread.
- [x] Existing collection tools read the pinned form data after CPF-first-3 verification.
- [x] Presentation maps Canais Cedente to creditor and managed Assistant profile to agent name.
- [x] Railway backend 0.4.1 published: `26c57dc6-af67-4454-b718-bf445ed9c998`;
  live prompt smoke rendered `Fastpay / Sophia`, profile version 15, and unchanged
  Playground/session hashes were verified. Backup:
  `/data/backups/pre-future-demo-041-20260918-161510`.
- [x] Playground fixture and current frontend remain unchanged.
- [x] `/reset-demo` resets only future Demo sessions before LLM/tools, keeps the
  pinned fixture/snapshot and cuts previous messages from active context.
- [x] Railway backend 0.4.2 published: `c50fbdf9-9ade-40f1-96a3-adcd14e8a670`.
  Synthetic thread `f1887e35-7650-471a-b738-d61465dda21b` returned the reset
  receipt with one active message and three retained checkpoints; the state had
  identity false, zero offers/agreements/receipts and `reset_count=1`. The 29
  prior session rows, Playground fixture and 4,170 stable data files retained
  their pre-rollout hashes. Backup:
  `/data/backups/pre-reset-demo-042-20260918-163254`.
- [x] Railway backend 0.4.0 published: `1c727670-b324-46ca-b719-17c6009eee1a`;
  creditor catalog and unchanged Playground/session hashes verified. Backup:
  `/data/backups/pre-future-demo-040-20260918-143027`.
- [ ] Wire the future authenticated form; do not call this contract directly from a browser.
- [ ] Run the synthetic end-to-end through that future authenticated form.
- [ ] Map future-session data to each channel catalog entry's required template values.
- [ ] Move creditor and agent-name ownership into the selected portfolio configuration.

# Configurable identity — 0.2.5

- Published 0.2.5; Qwen validation and preserved histories confirmed. See
  docs/IDENTITY_RELEASE_2026-09-15.md for exact versions, timings and initial failure.

- 0.2.4 exposed a BlockingError in hosted async execution: reading session policy
  inside synchronous dynamic_prompt performed IO on the event loop. 0.2.5 moves
  the contract into the existing off-thread _filtered_request middleware.
- Regression asserts policy reads occur off the event loop; 126 tests pass,
  one skipped, 86% coverage, Ruff passes. The initial failed live run is retained.

- Existing fixture and conversation store reused; no new dependency or auth bypass.
- 125 pytest pass, one legacy integration skipped, 85% coverage; Ruff and Docker pass.
- Twelve policy combinations, generic failures, attempts/replay, isolation,
  revocation, pinning, safe context injection and legacy callers validated locally.
- Updated an old schema test to use invalid cpf type now that get_customer accepts
  no arguments; no-identity denial remains covered separately.
- Backup: /data/backups/pre-identity-024-20260915T193619Z, 12 conversations + volume.
- Publication and real-model acceptance pending; tests above use synthetic inputs.

# Tool usage inspection — 0.2.3

- Expose actual runtime descriptions and public input schemas via list_tools.
- Read-only contract inspection; no changes to permissions or execution.
- Ruff passes; 102 tests pass, one legacy integration skipped, 84% coverage.
- Contract regression covers all eleven tools and excludes injected runtime data.
- Published source fa3c8cc / runtime 0.2.3, Railway deployment
  a946629d-aba7-4f5f-9234-5b551a837d54 (SUCCESS).
- Eleven live contracts verified; nine prior conversation histories, active OKF
  snapshot and tool settings preserved. Backup:
  /data/backups/pre-tool-usage-20260915T171435Z (private, on-volume).
- Docker build passed on retry after the first local process exited 143.
- Local browser against published backend passes all eleven schemas, zero page
  errors, only list_tools; no provider call or business operation.

# Runtime audit corrections — 0.2.0

Scope: simple-agent-template and agent-chat-ui only. The original console and
WhatsApp are unchanged. No production data or published bundles are migrated.

- [x] 1. Lexical search and parseable OKF YAML, regression tests.
- [x] 2. Persistent, transactional state scoped to server thread ID.
- [x] 3. Policy receipts, Decimal offers, expiry and confirmation/idempotency.
- [x] 4. Incremental RAW drafts, conflict detection, indexes and append-only log.
- [x] 5. One LLM configuration, pinned snapshots and persistent server checkpoints.
- [x] 6. Three LOCAL synthetic journeys, frontend, streaming and provider cancellation.
- [x] Authorized Railway rollout with backup, Qwen tools and restart checks;
  see docs/RELEASE_2026-09-14.md for deployment IDs and limits.
- [x] Published Qwen battery: 14 browser turns + 1 API probe, 41 tool calls;
  see docs/QWEN_E2E_2026-09-14.md. Identity/action guards passed; financial text
  and autonomous GLOBAL discovery failed. No valid financial closing approved.
- [x] Prepare an isolated synthetic policy with complete scope/terms; separate entry remains unsupported.
- [x] Candidate: consolidate prompts and add bounded post-stream numeric review (not semantic approval).
- [x] Candidate: preserve existing nested paths and YAML metadata in section reads; test root conflicts.
- [x] Candidate: distinguish tool execution from domain outcomes.
- [x] Repeat isolated Qwen journeys; final iteration creates one simulated agreement with exact schedule.
- [x] Activate the approved RAW AGENTS root-casing instructions, with verified backup.
- [ ] Human review/publication of the proposed pilot bundle in the hosted application.
- [x] Frontend 0.1.1 / backend 0.2.2 rollout and published read-only Qwen browser E2E;
  see docs/RELEASE_2026-09-15.md. Financial live acceptance remains separate.
- [ ] Broader semantic regression validation; no full-fidelity guarantee from one successful run.

Delivery stages: local tests → branches/PRs → separately approved Railway rollout.
Passing local checks does not prove publication or real-Qwen E2E.
The E2E report records the tested financial journeys and current failures;
published end-to-end financial acceptance remains pending. Candidate/isolation
evidence and remaining failures: docs/OKF_INGESTION_GROUNDING.md.
Coordinate PR integration before another main autodeploy.

## Dummy payment pilot — 0.5.0

- [x] Normalize the synthetic test scope to `Will Bank` / `cartao_de_credito`.
- [x] Revalidate the agreement policy before creating invalid dummy PIX/boleto.
- [x] Capture explicit e-mail in a local outbox without external delivery.
- [x] Keep simulated settlement behind an approved admin operation.
- [x] Validate happy, negative and neutral journeys locally.
- [x] Create and validate isolated Railway draft `will-bank-negotiation-pilot-20260920-185ae54d`.
- [ ] Publish/activate the draft only after operator review.
- [x] Deploy backend 0.5.0 and run isolated Gemini conversations based on the
  anonymized Marcelo Barbosa replay; Qwen timed out before response.
- [ ] Activate the reviewed draft and repeat the same conversation through the UI.
## Authorized rollout — 2026-09-15

- Initial 0.2.1 build failed before startup: pip bootstrap inherited a proxy
  unavailable to the Railway builder. Candidate 0.2.2 excludes proxy variables
  during bootstrap as well as uv sync, preserving all runtime LLM proxy settings.

- Server-pinned model verified with a request-override regression test: 101 tests
  pass, one skipped, 83% coverage; Ruff passes. No new model selector/dependency.
- Backup: `/data/backups/pre-runtime-021-20260915T154311Z` (six conversations,
  API exports and volume archive). Both deployments and published smoke passed;
  all previous conversation hashes and 3,228 data-file hashes preserved.
- Preserve the existing OKF bundle; the separate invented pilot policy is not
  implicitly approved by a code deployment.

## RAW instruction versions (0.2.7)

- [x] Preserve legacy instructions; atomic version history with serialized saves.
- [x] Newest-first paginated history and active version exposed by compiler graph.
- [x] 135 unit tests passed, 86% coverage overall and 90% compiler coverage.
- [x] Railway 0.2.7 published: `7eb7e7ab-4907-4e58-8d5e-ee601e33fd20`.
- [x] 31 conversation states, managed Assistant context/version and 4148 Markdown hashes preserved.
- [x] Published UI saved unchanged RAW content into v2, retained v1 and reloaded it.
# LLM and agent profile settings (0.3.0)

- [x] Per-request temperature, top-p and output limit; optional agent identity/style.
- [x] Admin metadata and validation; server-defined connections and existing safety gates retained.
- [x] Sampling/profile and provider-fallback protocol tests; see docs/LLM_AGENT_SETTINGS.md for current results.
- [x] Versioned principal/fallback selection, sanitized integration metadata and dedicated Lovable bridge source.
- [x] Authorized connection preparation: bridge deployed, Gemini registered, live Gemini/Qwen tools and published availability verified on backend 0.3.2; see docs/LOVABLE_CONNECTION_2026-09-17.md. Fallback remains off; activation is exclusively Marcelo's action.
- [x] Authorized deployment-only Railway rollout, both services 0.3.0; published settings and Qwen tool/profile check passed.
- [x] Original conversations, managed Assistant settings and all 25 previous session rows preserved; 4170 file hashes unchanged after canaries, with two new synthetic SQLite sessions.
- [ ] Known model limitation: spontaneous self-introduction was omitted in the time-query probe; explicit name query passed. See docs/RELEASE_LLM_SETTINGS_2026-09-17.md.
