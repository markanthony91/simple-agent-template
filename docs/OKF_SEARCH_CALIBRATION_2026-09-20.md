# OKF search calibration — 2026-09-20

## Observed cause

The active Will Bank policy is seven index levels below the root. Gemini also sees
a generic `PRODUCTS/cartao_de_credito` branch and may explore it in parallel. Each
tool result requires another model inference, so a negotiation used 7–10 navigation
calls before the payment tool and increased exposure to incomplete bridge streams.

The previous lexical search ranked matching lines. Repeated generic lines occupied
the ten-result limit and hid the specific pilot policy. A prompt-only calibration
reduced one boleto trial from 7 calls and 14.72 seconds to 3 calls and 7.76 seconds,
but selected `limites-de-autonomia.md` and created no payment.

## Candidate

- Rank query coverage across the complete document and canonical path.
- Return at most one result per document.
- Ignore common Portuguese stop words.
- Normalize `3x` to `3` plus `parcela`, and normalize parcel/installment variants.
- After `get_customer`, use one root index and one search scoped to `COMPANIES`;
  read the first institution/product policy and stop when it is sufficient.

Against an isolated copy of the active 469-file bundle, the candidate ranked
`COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO/policies/negociacao-piloto-sintetico.md`
first for both `boleto parcelado 3x` and `à vista PIX` queries.

## Acceptance

Railway 0.7.0 deployment `3f5a0fc0-b8f1-4ad4-a53b-d4f98458a73d`
completed successfully from source `66611aa`.

| Variant | Navigation | Time | Result |
|---|---:|---:|---|
| Main Assistant v22, uncalibrated | 12 calls | 20.71 s | Visited `PRODUCTS` and `COMPANIES`; provider error; no payment |
| Prompt shortcut with old line ranking | 3 calls | 7.76 s | Read generic autonomy document; no payment |
| Temporary calibrated Assistant on 0.7.0 | 3 calls per run | 11.21 s median over three reliable measurements | 4/4 payments created: 2 boleto and 2 PIX |
| Main Assistant v23 on 0.7.0 | 3 calls per run | 12.28 s boleto; 11.32 s PIX | 2/2 payments created |

Every calibrated financial run used exactly `okf_index(<root>)`, one
`okf_search(scope="COMPANIES")`, then `okf_read` on the synthetic Will Bank
policy. No calibrated run visited `PRODUCTS` or returned
`provider_response_incomplete`.

A neutral debt-contestation query still followed `GLOBAL`, used four navigation
calls, completed in 13.54 seconds and did not request identity. Twenty direct
search measurements on the hosted 469-file bundle returned the correct first path
with 124.92 ms median, 149.25 ms p95 and 156.37 ms maximum. Model round trips,
not server-side lexical search, remain the dominant latency.

The main Assistant was versioned from 22 to 23 with exact AGENTS.md and WORKFLOW
read-back. System Prompt, profile, Gemini/Lovable integration, model settings and
workflow catalog were preserved. The temporary Assistant, eight synthetic threads
and their session rows were removed; the persistent session count returned from 60
to the 52-row baseline.

Backup: `/data/backups/pre-okf-search-070-20260920T152920Z.tar.gz`, SHA-256
`e1b3534f05ef9d8aa62a384674da2e5b94e54fc66cef33b9432489c6e568b277`.
