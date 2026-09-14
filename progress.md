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
- [ ] Review financial policy status/scope/parameters and supported entry terms.
- [ ] Correct financial response grounding and conditional-source interpretation.
- [ ] Correct nested-path/root discovery and redundant OKF navigation.
- [ ] Distinguish tool execution success from business/lookup/textual outcomes.
- [ ] Repeat Qwen journeys and validate a complete authorized agreement path.

Delivery stages: local tests → branches/PRs → separately approved Railway rollout.
Passing local checks does not prove publication or real-Qwen E2E.
The E2E report records the tested financial journeys and current failures;
successful end-to-end financial acceptance remains pending.
Coordinate PR integration before another main autodeploy.
