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
