# PostgreSQL session and OKF canary — 2026-09-29

## Scope

- Dedicated Railway database: `Postgres-N6HF` (`4fe1fa72-c700-44fe-9132-6c8240d9e556`).
- Isolated application canary: `agent-runtime-postgres-canary`.
- Production service remains on `SESSION_BACKEND=sqlite`; no traffic was moved.
- Synthetic data only. No channel, payment or customer action was triggered.

## Schema

Migration `001_postgres_session_okf.sql` creates:

- `runtime.sessions` for durable session state;
- `okf.snapshots` and `okf.documents` for the future metadata migration;
- `okf.receipts` for policy-read evidence used by the current tools;
- `langgraph` reserved for the later checkpoint migration.

Migration `002_postgres_payments.sql` creates:

- `runtime.payment_agreements` scoped to the originating session;
- `runtime.payment_instructions` with agreement, method and installment
  uniqueness;
- indexes for session context, agreement origin and payment lookup.

Indexes cover the session primary key, tenant/portfolio, customer, debt, recent
updates, snapshot/path and recent OKF reads. The migration is versioned and
idempotent through `runtime.schema_migrations`. Query plans with 5,000 synthetic
rows used the intended session-context, agreement-origin and payment indexes.

## Validation

Twenty synthetic executions per backend, from the same canary container:

| Operation | SQLite local p50/p95 | PostgreSQL p50/p95 |
| --- | ---: | ---: |
| UTC now | 0.42 / 0.61 ms | 0.40 / 0.44 ms |
| Calculator | 0.27 / 0.42 ms | 0.24 / 0.29 ms |
| Session transaction | 1.72 / 2.28 ms | 2.39 / 3.84 ms |
| OKF index | 0.94 / 1.31 ms | 1.31 / 1.68 ms |
| OKF list | 0.65 / 1.32 ms | 1.14 / 2.00 ms |
| OKF search | 0.57 / 1.26 ms | 0.98 / 1.80 ms |
| OKF read | 2.07 / 2.94 ms | 4.41 / 5.37 ms |
| OKF read section | 1.51 / 2.38 ms | 3.77 / 5.55 ms |
| Identity verification | 1.83 / 2.61 ms | 2.82 / 4.99 ms |
| Generate payment offer | 5.48 / 7.12 ms | 7.57 / 10.66 ms |
| Boleto second copy | 0.52 / 0.74 ms | 3.00 / 5.58 ms |
| Payment status | 0.40 / 0.66 ms | 0.94 / 1.61 ms |

The local SQLite comparison uses ephemeral container storage and is therefore
faster than PostgreSQL. It does not reproduce the persistent production volume,
where the observed SQLite commit was about 672 ms. PostgreSQL removed that
filesystem commit path and kept every measured canary tool below 11 ms at p95.
The direct UTC tool is below 1 ms, so a multi-second user-visible delay is in
model/runtime orchestration or queueing, not in the UTC calculation. A
shadow/canary traffic stage is still required before cutover.

The canary also validated transaction rollback, idempotent session creation,
identity gates, agreement ownership between sessions, Demo reset cleanup,
payment offer persistence, boleto second-copy retrieval and payment status.
After the benchmark the dedicated database contained zero sessions, agreements
or instructions. No provider API was called.

## Current production latency decomposition

A read-only inspection of one production negotiation run found 10,923 ms total:

- 878 ms waiting in the runtime queue;
- 10,039 ms executing the graph;
- four sequential requests to the configured LLM bridge;
- 2,531 ms across two OKF indexes, one OKF read and payment-offer handling;
- about 7,508 ms left in model, network and graph orchestration after subtracting
  the measured tool intervals from graph execution.

The deployed Assistant sends 102,578 instruction characters before the dynamic
session contract and conversation history. The active Workflow alone contributes
83,862 characters. This is roughly 25,600 tokens before tool schemas and messages,
and it is processed again at each model round trip. The sample therefore points
to prompt size plus four sequential model decisions as the main latency source.

There are two additional, bounded sources outside tool business logic:

- the current SQLite OKF receipt commit took 672 ms in the inspected read; the
  PostgreSQL canary reduced the full equivalent read to 5.37 ms at p95;
- `CashMessageDelay` intentionally pauses delivery for five seconds only when a
  streamed answer begins with the configured cash-review announcement.

The deployed checkpoint read-reuse patch was verified by package version and
source hash. It prevents repeated checkpoint reloads, so that previously fixed
path is not the explanation for this sample. Production queueing and the LLM
bridge still need their own model-call timing before any production tuning.

## Deliberate limits

- Immutable OKF Markdown stays on the filesystem; its measured read is already
  inexpensive. Only the durable receipt is stored in PostgreSQL in this phase.
- Redis was not added. Add it only for measured queue, lock or ephemeral-cache
  pressure; it is not a replacement for the durable session source of truth.
- Production remains on SQLite. This canary result does not prove end-to-end
  response-time improvement until shadow traffic includes model orchestration.
