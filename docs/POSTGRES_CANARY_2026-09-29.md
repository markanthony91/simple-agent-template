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

## Queue and storage follow-up

The next isolated canary keeps production defaults unchanged and adds:

- structured `MODEL_CALL` timings for preparation, provider time and response
  audit, with sizes and token counts but no prompt or message content;
- a source-hash-guarded queue polling setting, defaulting to the existing 500 ms;
- an opt-in job count, defaulting to the existing single job;
- explicit SQLite `DELETE/FULL`, `WAL/FULL` and `WAL/NORMAL` comparisons against
  PostgreSQL, plus concurrent writers;
- one synthetic end-to-end negotiation that stops after creating a dummy boleto
  agreement and never invokes channels or payment providers.

Before deployment, eight concurrent admin runs with four clients completed in
872.95 ms total. The first four requests took 842.68–856.45 ms and the second
four 15.01–17.55 ms. This is the baseline for the canary-only 50 ms polling and
four-job configuration.

### Queue result

Deployment `4e27f8af-6edf-4602-9483-1cc4d82cbeba` was verified with four
background workers, `LANGGRAPH_QUEUE_POLL_SECONDS=0.05`, runtime 0.34.0 and both
source-hash-guarded patches. The same eight requests and four clients produced:

| Metric | Before | Canary | Change |
| --- | ---: | ---: | ---: |
| Total | 872.95 ms | 283.33 ms | -67.5% |
| p50 | 430.11 ms | 139.70 ms | -67.5% |
| Maximum | 856.45 ms | 164.01 ms | -80.9% |
| Errors | 0 | 0 | unchanged |

### Persistent-volume storage result

Twenty synthetic executions per mode used the canary's own `/data` volume and
four concurrent writers. Selected measurements:

| Mode | Session p95 | OKF read p95 | Identity p95 | Offer p95 | Concurrent writes/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQLite DELETE/FULL | 9.19 ms | 7.61 ms | 6.84 ms | 14.79 ms | 104.88 |
| SQLite WAL/FULL | 11.28 ms | 9.87 ms | 9.20 ms | 17.72 ms | 174.04 |
| SQLite WAL/NORMAL | 10.47 ms | 10.70 ms | 9.08 ms | 16.33 ms | 503.88 |
| PostgreSQL | 10.29 ms | 19.15 ms | 10.29 ms | 21.91 ms | 288.84 |

`WAL/NORMAL` had the highest synthetic write throughput but deliberately relaxes
fsync guarantees. PostgreSQL beat both FULL SQLite modes under concurrent writes
and remains the durable multi-replica candidate. On this clean canary volume,
SQLite kept lower single-operation latency; the earlier 672 ms production-volume
commit was not reproduced here.

### End-to-end negotiation

After configuring the canary with the same LLM gateway and private proxy as
production, one isolated three-turn negotiation completed from initial request
through identity, canonical OKF policy read and a dummy three-installment boleto
agreement:

| Turn | Duration |
| --- | ---: |
| Start negotiation | 1,163.55 ms |
| Validate identity and read policy | 4,255.82 ms |
| Create agreement | 1,177.86 ms |

The identity tool took 18.49 ms, the OKF search 11.38 ms, the OKF read 24.18 ms
and the offer 36.42 ms. Model provider phases ranged from 737.41 to 1,673.98 ms
and dominated the turn duration. The gateway did not return token usage on these
streaming responses, so the new event correctly omitted that optional field.
No email, SMS, WhatsApp, phone or payment-provider tool ran. The runtime thread
and PostgreSQL session were deleted after validation; no synthetic session rows
remained.

### Cutover decision

No production cutover was made. PostgreSQL and the queue settings passed the
isolated functional and concurrency checks, but the canary uses the compact
repository prompt (17,359 system characters), not the current production
Assistant context of about 102,578 characters. The excluded prompt/Workflow work
therefore remains the dominant untested difference. Before a production change,
run a controlled shadow using the production Assistant context and define rollback
thresholds for queue errors, p95 response time and PostgreSQL pool saturation.
