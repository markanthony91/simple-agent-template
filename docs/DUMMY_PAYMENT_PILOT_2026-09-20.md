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

## Railway rollout

- Backend 0.5.0 deployment: `73ea459c-e7b0-4766-895b-eef18b95a338`, success.
- Source with runtime behavior: `b3d61c1`.
- Backup: `/data/backups/pre-dummy-payment-050-20260920T143736Z`.
- Archive SHA-256: `b66d6f5803aae94587a9fb7da42323b440afe17e47d5aa6a55c9cb32242b9435`.
- Read-back confirmed package 0.5.0, all three payment tools and
  `/app/.langgraph_api -> /data/langgraph`.
- All 46 prior thread states/histories, four Assistants and 52 session rows matched
  the backup after deployment and canaries.
- The active bundle ID remained unchanged; the candidate remains a draft.

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

The default Qwen request timed out after 120 seconds before producing a response,
so it is not an acceptance result. Gemini through the registered Lovable connection
completed all four isolated scenarios. In the happy path it generated the exact 3x
schedule, registered the agreement, created a dummy boleto, captured the explicit
e-mail without claiming external delivery, repeated the same code and kept “Já
paguei” as `pending` after calling `get_payment_status`. The cash replay answered
the 0% discount objectively and repeated the same persisted offer. Negative and
neutral scenarios neither verified identity nor created offers.

The operator settlement canary denied the request without approval, then changed
both payment and agreement to `settled` after explicit admin approval. All canaries
used `/tmp` storage, not the active dataset or session database.
