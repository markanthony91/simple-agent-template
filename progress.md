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
- [ ] Candidate frontend/backend rollout and published browser E2E.
- [ ] Broader semantic regression validation; no full-fidelity guarantee from one successful run.

Delivery stages: local tests → branches/PRs → separately approved Railway rollout.
Passing local checks does not prove publication or real-Qwen E2E.
The E2E report records the tested financial journeys and current failures;
published end-to-end financial acceptance remains pending. Candidate/isolation
evidence and remaining failures: docs/OKF_INGESTION_GROUNDING.md.
Coordinate PR integration before another main autodeploy.
