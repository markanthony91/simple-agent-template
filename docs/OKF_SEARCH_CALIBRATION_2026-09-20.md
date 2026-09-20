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

Pending controlled Railway trials with the managed Gemini connection. Measure
navigation calls, elapsed negotiation time, selected canonical path, payment
creation and provider completeness. Synthetic threads must be removed afterward.
