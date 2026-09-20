# Will Bank dummy payment pilot — 2026-09-20

## Scope

This laboratory flow uses the exact identifiers `Will Bank` and
`cartao_de_credito`. It supports a synthetic offer with at most three installments,
zero discount, invalid dummy PIX/boleto codes and local e-mail outbox capture.
No payment or e-mail leaves the service.

The LLM cannot settle a payment. Only the approved `simulate_payment_settled`
admin operation can change a dummy payment from `pending` to `settled`.

## Dataset candidate

- Active bundle retained: `okf_wiki_2026-09-18_paths-corrigidos-yaml-corrigido-20260918T222113Z-807463fd`.
- Isolated draft: `will-bank-negotiation-pilot-20260920-185ae54d`.
- 22 existing Will Bank concept files had their declared identifiers normalized.
- 26 scoped concepts read back with only `Will Bank` and `cartao_de_credito` identifiers.
- Added `COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO/policies/negociacao-piloto-sintetico.md` and linked it from the existing policy index.
- Draft validation: valid, zero errors, 128 inherited broken-relative-link warnings.

The draft was not published or activated. Review it in Dataset before changing the
active snapshot.

## Validation

```text
207 unit tests passed
87.55% total coverage
Ruff check passed
Pilot OKF: 8 files, valid, zero errors, zero warnings
Integration suite: one legacy test skipped; no runnable integration test collected
```

The deterministic happy journey covers identity, debt, policy read, three-part
offer, explicit agreement confirmation, dummy PIX, dummy boleto, explicit e-mail
capture, pending status and admin settlement. Negative and neutral journeys cover
missing agreement, draft/excess terms and general knowledge lookup without opening
a negotiation.

The isolated real-model probe reuses only anonymized dialogue patterns from the
Smart Debt Marcelo Barbosa replay: isolated “A vista”, discount inquiry, repeated
cash-condition inquiry, preference for installments, request for 3x, boleto,
explicit e-mail, code redelivery and “Já paguei”. Customer identity, amounts,
dates and commercial terms remain the local synthetic fixture and OKF policy.
