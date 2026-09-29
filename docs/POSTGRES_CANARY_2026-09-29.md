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

Indexes cover the session primary key, tenant/portfolio, customer, debt, recent
updates, snapshot/path and recent OKF reads. The migration is versioned and
idempotent through `runtime.schema_migrations`.

## Validation

Twenty synthetic executions per backend, from the same canary container:

| Operation | SQLite local p50/p95 | PostgreSQL p50/p95 |
| --- | ---: | ---: |
| Session transaction | 4.62 / 5.59 ms | 7.46 / 11.29 ms |
| OKF read plus receipt | 5.98 / 6.99 ms | 16.35 / 19.50 ms |
| Identity verification | 6.41 / 9.60 ms | 8.58 / 9.67 ms |

The local SQLite comparison uses ephemeral container storage and is therefore
faster than PostgreSQL. It does not reproduce the persistent production volume,
where the observed SQLite commit was about 672 ms. PostgreSQL removed that
filesystem commit path and kept complete canary tool calls below 20 ms at p95.
A shadow/canary traffic stage is still required before cutover.

## Deliberate limits

- Payment persistence and boleto second-copy lookup fail closed on PostgreSQL.
- Immutable OKF Markdown stays on the filesystem; its measured read is already
  inexpensive. Only the durable receipt is stored in PostgreSQL in this phase.
- Redis was not added. Add it only for measured queue, lock or ephemeral-cache
  pressure; it is not a replacement for the durable session source of truth.
