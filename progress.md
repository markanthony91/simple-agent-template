# Runtime audit corrections — 0.2.0

Scope: simple-agent-template and agent-chat-ui only. The original console and
WhatsApp are unchanged. No production data or published bundles are migrated.

- [x] 1. Lexical search and parseable OKF YAML, regression tests.
- [x] 2. Persistent, transactional state scoped to server thread ID.
- [x] 3. Policy receipts, Decimal offers, expiry and confirmation/idempotency.
- [x] 4. Incremental RAW drafts, conflict detection, indexes and append-only log.
- [x] 5. One LLM configuration, pinned snapshots and persistent server checkpoints.
- [x] 6. Three LOCAL synthetic journeys, frontend, streaming and provider cancellation.
- [ ] Coordinated Railway rollout after backup and explicit approval.
- [ ] Real Qwen journeys, latency and review of saved assistant instructions/policies.

Delivery stages: local tests → branches/PRs → separately approved Railway rollout.
Passing local checks does not prove publication or real-Qwen E2E.
