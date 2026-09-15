# Identity policy release — 2026-09-15

Published only to the existing Railway runtime/chat laboratory. No WhatsApp,
Lovable, inference service, financial terms or OKF document changes.

| Component | Version/source | Successful deployment |
| --- | --- | --- |
| Backend | 0.2.5 / 4cc6424 | e999c575-d2f4-4648-a26a-16565613d077 |
| Frontend | 0.1.6 / 914aeb1 | ebf30064-72a2-419f-8742-7ba605da20f1 |

Simulator is set to first four CPF digits + full name, three failed attempts.
Existing conversations retain their original fixture/policy. The operator can
select full/first4/last4 CPF and name/birth/both (or legacy either) in Simulator.
The backend requires every selected factor and never discloses which one failed.
Identity verification and agreement confirmation remain separate checks.

## Evidence

- 126 pytest pass, one legacy integration skipped, 86% coverage; Ruff passes.
- Docker 0.2.5 builds successfully. Frontend typecheck/build pass; targeted lint
  zero errors, two existing effect warnings (simulator/editor).
- Twelve local and twelve published Playwright cases pass with mocked API.
  Separate real-browser inspection verifies persisted first4/name/3 controls,
  Dataset label, no horizontal overflow at 1440/1024/390 widths and no JS errors.
- Published Qwen/Qwen3-30B-A3B-Instruct-2507-FP8, three conversations/five turns:
  - Happy: `01a0a69b-2547-7130-96e3-abf7a8824d26`; initial identification request
    2560 ms, correct data → verify_customer_identity → get_customer 4212 ms.
  - Wrong: `01a0a69b-3fbf-7352-828d-bbcba0200f1c`; clarification 2479 ms (no tools),
    then supplied incorrect data → identity_validation_failed, two attempts left,
    2609 ms. No financial data read.
  - Missing name: `01a0a69b-4970-7ec0-9fd7-4942be8efbc0`; 1822 ms, no debt read.
- Timings above are backend run completion, NOT first visible text or a benchmark.
  No agreement was created; semantic fidelity beyond these checks is not certified.
- Maximum-attempt lock, all factor combinations, duplicate failure calls,
  cross-session isolation and revocation covered in deterministic local tests.

## Failure found and fixed

Initial 0.2.4 deployment succeeded but its first real run raised BlockingError:
session SQLite access inside synchronous dynamic_prompt ran on the async event
loop. 0.2.5 moves the policy contract into the existing off-thread request filter.
A regression explicitly checks the policy executes outside the main thread.
The initial failed test conversation was retained; it is not counted as a pass.

## Preservation and rollback

Backup `/data/backups/pre-identity-024-20260915T193619Z` contains 12 conversation
API exports and a private volume archive. SHA256:
`3d65a9df6090342e2acabe18988cf01dbe48f463b3c9c87ba80d338c2b95dda6`.
All 12 prior conversation message histories were verified unchanged after rollout.
Backup is on-volume, not an external disaster recovery copy.

Rollback targets: backend 0.2.3 deployment a946629d-aba7-4f5f-9234-5b551a837d54;
frontend 0.1.4 deployment 1d976f00-d066-4abb-9bfb-e5c2a142df65. Preserve /data.
Older backend ignores the new policy and requires full CPF + secondary factor;
review operator instructions before rollback. Do not restore the old archive over
new conversations. Do not rollback to the intermediate broken 0.2.4 image.

This remains an anonymous synthetic operator lab. Partial CPF and personal facts
are not strong identity authentication. New conversations reset attempts by design;
production requires authenticated sessions and an appropriate verification channel.
