# Negotiation latency — 2026-09-20

## Cause

The published 0.7.0 negotiation required five sequential Gemini calls around
`okf_index`, `okf_search`, `okf_read` and `generate_payment_offer`. The four tools
used about 228 ms together; model round trips dominated the 10.81-second client
measurement.

## Change

Version 0.8.1 lets `generate_payment_offer` resolve the policy inside the pinned
OKF snapshot. It filters candidates by declared negotiation/payment metadata,
then reuses the existing lifecycle, institution, product, commercial-term and
payment-method validators. Zero or multiple applicable policies fail closed.
Explicit customer terms and identity gates are unchanged. General institutional
questions still use progressive OKF navigation.

The managed Assistant was versioned from 23 to 24 with exact AGENTS.md and
Workflow read-back. System Prompt, agent profile and Gemini/Lovable settings were
preserved.

## Published validation

Final Railway deployment: `e1a73d36-5b9c-4758-8ba0-7097dabf74fb`.

| Measurement | 0.7.0 | 0.8.1 |
|---|---:|---:|
| Negotiation client time | 10.81 s | 7.14 s |
| Negotiation tools selected by the model | 4 | 1 |
| Gemini calls in negotiation | 5 | 2 |
| Policy/payment tool time | 228 ms total | 459 ms composite |
| Complete happy conversation | 35.29 s | 32.53 s |
| Complete unhappy conversation | 16.00 s | 16.74 s |

The 0.8.1 happy path validated identity, resolved the Will Bank credit-card
policy, created one offer/agreement/pending boleto, captured one local outbox
record and refused to claim settlement. The unhappy path kept identity false and
created no offer, agreement, payment or delivery after invalid credentials and a
bypass request.

Local validation: 211 tests passed, one legacy test skipped, 88% coverage, Ruff
and diff checks passed. Four synthetic live conversations used during the two
deploy iterations were removed; the persistent session count returned from 56 to
the 52-row baseline.

Backup before rollout:
`/data/backups/pre-negotiation-resolver-080-20260920T162409Z.tar.gz`, SHA-256
`65c9e9880ec0d2eafa1fb60863c74978fb5fa9b9d7d3d79a31c202afaf47775e`.
