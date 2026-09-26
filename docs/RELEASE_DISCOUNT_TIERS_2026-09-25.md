# Runtime 0.13.4 — OKF discounts by overdue range

Published code: commit `00d58ac`, PR #55, branch `fix/okf-discount-tiers`.
Railway project `511a294c-8d6a-4906-bd26-e8e33011eac5`, service
`861cf8e9-935f-4673-baf0-6bb438eac5fb`, deployment
`93def5d4-1ccb-41fc-8a04-7c55854647da`: SUCCESS. Running package version and
SHA-256 hashes of all three modified Python modules matched the tested source.

User authorized preserving the existing OKF overdue discounts (5%, 8%, 10%, 10%)
rather than flattening the pilot to 10%. No model-supplied percentage/day count is
accepted. Existing fixed-discount documents remain supported.

Backup: `/data/backups/pre-discount-tiers-20260926T000511Z`, with complete values
for 363 threads, four assistants, volume archive and consistent SQLite backup.
All 363 histories and Assistant settings matched after deployment. Archive SHA-256:
`b50802692d51476b386c051b063106737f471a464e812318fb3b6e9a6cd5fdf8`.

After the Runtime was verified, three OKF documents were published:
`politica-negociacao.md`, `pagamento-parametros.md`, and the policies `index.md`
under `COMPANIES/fastpay/INSTITUTIONS/will-bank/CARTAO_DE_CREDITO/policies/`.
The executable cash policy contains the existing four overdue ranges and allows
cash PIX/boleto. Reference documents explicitly route installment proposals to
`parcelamento.md`. The cash policy replaces its stale installment/human-supervisor
instructions with that reference and the authorized automatic flow.

Previous bundle:
`okf-will-bank-installment-contract-20260925-20260925T234535Z-d1f0944d`.
New bundle:
`okf-will-bank-cash-tiers-20260925-20260926T001809Z-f35ea74f`.
All 571 files validated, zero errors/warnings, modified documents read back exactly.

Validation:
- 285 tests passed; total coverage 88%, offer policy 93%, payment policy 85%.
- Boundary days 30/31, 90/91, 180/181; PIX/boleto totals, idempotency, invalid
  tables, missing debt context and excessive discounts covered.
- Actual prepared cash document passed 16 range/method checks.
- Published frontend, new conversation: PIX created with 10% for 169 overdue
  days, reducing the synthetic 5873.42 to 5286.08. Generation turn 14.3 seconds.
- Separate frontend conversation: three boleto installments created at 0%,
  schedule 1957.81 / 1957.81 / 1957.80. Generation turn 38.1 seconds.
- Both browser sessions reported no page errors. Tests stopped at the email
  request; external delivery was not tested in this rollout.

Residual observations: installment navigation visited unrelated branches before
finding the correct document. Its initial greeting requested a name, although the
subsequent submitted CPF prefix was validated successfully. This release does not
claim to resolve overall workflow consistency or navigation latency. Existing
sessions keep their pinned OKF snapshot; start a new chat for the new cash policy.

Rollback: retain 0.13.4 while sessions pinned to tier policies exist. Re-activate
the previous bundle for new sessions if needed; it restores the former PIX policy
limitation. Do not restore data snapshots over intervening customer activity.
