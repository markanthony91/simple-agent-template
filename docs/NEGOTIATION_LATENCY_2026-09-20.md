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

## Atomic identity and direct replies — 0.9.1

Identity verification and customer lookup now share one transaction through
`verify_and_get_customer`. The model no longer sees the legacy two-tool route.
Identity and proposal tools end the agent loop after execution, and middleware
creates the final AI message from the authorized backend payload. This removes
the post-tool Gemini call and prevents the model from changing values, IDs,
installment rounding or failure reasons.

The source of each condition remains explicit:

- the pinned session supplies customer, current balance and individual eligibility;
- the published OKF policy matching institution and product supplies validity,
  commercial ceilings, payment methods and delivery channels;
- both validators may restrict a request, and neither can expand the other;
- the model supplies only the terms explicitly requested by the customer.

Railway 0.9.1 deployment: `739548fc-17c7-44c0-87a4-62b3dfb6c655`.
The managed Assistant was versioned from 24 to 25 with exact System Prompt,
AGENTS.md and Workflow read-back. Agent profile, Gemini/Lovable connection,
fallback, sampling settings and selected workflow were preserved.

| Measurement | 0.8.1 | 0.9.1 | Reduction |
|---|---:|---:|---:|
| Identity turn | 6.48 s | 2.40 s | 63.0% |
| Gemini calls in identity | 3 | 1 | 66.7% |
| Negotiation turn | 7.14 s | 3.15 s | 55.9% |
| Gemini calls in negotiation | 2 | 1 | 50.0% |
| Complete happy conversation | 32.53 s | 27.02 s | 16.9% |
| Complete unhappy conversation | 16.74 s | 15.15 s | 9.5% |

The final happy path created one offer, agreement, pending boleto and outbox
record with the exact schedule `1957.81`, `1957.81`, `1957.80`; the status check
remained pending. The unhappy path kept identity false and created no financial
state. Direct messages carried `deterministic_backend` metadata with pre-display
protection and no numeric mismatch. Three synthetic live conversations were
removed and the persistent session count returned to the 52-row baseline.

Local validation: 214 tests passed, one legacy test skipped, 87% coverage, Ruff,
diff checks and Docker build passed. Backup:
`/data/backups/pre-direct-reply-090-20260920T165926Z.tar.gz`, SHA-256
`f9cf525d3dfe0b63407ae762faf0e0f18ee99c354c22ac7c8964540718cc4ec9`.
