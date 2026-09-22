# Termos naturais de parcelamento sem confirmação redundante — 0.12.11

- [x] O backend reconhece `3x`, `3 parcelas`, `3 vezes`, número por extenso e
  resposta curta contextual, sempre comparando a quantidade mais recente.
- [x] Uma escolha completa e compatível com uma única política lida avança para
  `generate_payment_offer` mesmo quando a LLM tenta pedir nova confirmação.
- [x] Perguntas informativas continuam sem criar proposta ou acordo.
- [x] Suíte local: 243 testes passaram e 1 foi ignorado.
- [x] Railway: deployment `36b090a2-dadc-4cfb-96db-68a3d548e5b0` publicado com
  sucesso.
- [x] Canário sintético: 7/7 variações passaram; nenhum WhatsApp ou e-mail foi
  enviado e os estados operacionais foram reiniciados após os testes.

# Política OKF escolhida pela LLM e validada pelo backend — 0.12.9

- [x] Exigir em `generate_payment_offer` o caminho canônico previamente lido no OKF.
- [x] Remover a varredura automática de políticas do backend.
- [x] Validar recibo, snapshot, publicação, vigência, instituição, produto, limites, desconto e meios.
- [x] Permitir que o cliente informe apenas “2x” quando boleto for o único método parcelado da política.
- [x] Atualizar a resposta determinística após `sent=true`.
- [x] Validar com 231 testes unitários; integração externa permanece isolada.
- [x] Publicar o runtime e versionar as instruções do Assistant.
- [x] Executar canário sem envio real e registrar deployment/Assistant.

Publicado no Railway pelo deployment
`a0bbd258-c931-4ffa-98c7-bcb1233bc111`, com a versão `0.12.9`; Assistant
versionado de `62` para `63`. O canário sintético passou em 12/12 verificações:
frase exata após “Podemos falar”, primeiro nome após identidade, navegação OKF,
leitura da política publicada do Will Bank, limite de 3 parcelas e proposta em
2x por boleto sem repetir o método. Nenhum e-mail ou canal real foi acionado; a
thread, sessão, cliente e dívida sintéticos foram removidos após a validação.

# Parcelamento somente por boleto — 0.12.8

- [x] Tornar os métodos permitidos específicos por modalidade na política.
- [x] Bloquear `installment + pix` antes de criar oferta, acordo ou pagamento.
- [x] Publicar backend, política e instruções do Assistant.

Publicado no Railway pelo deployment
`dc2de744-d8bb-43d3-afb4-990cf0bbaa48`, com a versão `0.12.8`; política ativa
`will-bank-boleto-installment-20260922-20260922T201310Z-b8f24807` e Assistant
na versão `62`. O teste sintético bloqueou PIX parcelado sem gravar estado e
aceitou 2 parcelas por boleto; a thread, a sessão, o cliente e a dívida
sintéticos foram removidos após a validação. Backup anterior à mudança:
`/data/backups/pre-installment-boleto-0128-20260922T171500`.

# Desconto definido pelo credor — 0.12.7

- [x] Remover o percentual de desconto do schema público da tool de pagamento.
- [x] Exigir `offer_discount_percentage` na política publicada e validar contra o teto.
- [x] Aceitar modalidade e método informados pelo cliente em mensagens separadas.
- [x] Publicado após integrar a entrega paralela do fluxo de e-mail.
- Railway: `cf2c238c-7f97-4cf1-ac1a-3ec643cfb824`; Assistant versão 61.
- Backup: `/data/backups/pre-creditor-owned-terms-0127-20260922T163800`.
- Bundle ativo: `will-bank-creditor-terms-20260922-20260922T195837Z-3ba385a1`.
- Canary do chat: proposta sintética em 2x por PIX, desconto 0%, sem envio externo;
  thread, sessão, cliente e dívida sintéticos removidos após a validação.
- Backup da política anterior: `/data/backups/pre-will-bank-policy-terms-20260922T170500`.

# Future Demo form backend — 0.12.3

## Workflow-scoped identity contract — 0.12.3

- [x] Inject CPF factors only after the active Workflow selects individual service.
- [x] Keep greetings, isolated names and general queries outside identity collection.

## Workflow-owned intent — 0.12.2

- [x] Remove the backend regex router between general and personal requests.
- [x] Keep financial authorization and identity-factor enforcement in the backend.
- [x] Rewrite any identity request to the active CPF-first-3 contract.

## Identidade vinculada à sessão

- [x] Consultar cliente e dívida pela `thread_id` fixada pelo backend.
- [x] Usar os três dígitos exatos da mensagem humana, sem depender da
  retranscrição da LLM.
- [x] Manter bloqueados valores com quatro ou onze dígitos e preservar o
  Playground.
- [x] Railway 0.12.1 publicado no deployment
  `b133597d-44bd-4dd0-8e9b-2e4f87d1d12a` após o backup
  `/data/backups/pre-thread-identity-0121-20260921-222846.tar.gz`.
- [x] Canary `3ab28f70-5532-4b0f-a273-1bbb4de88398` consultou a dívida
  vinculada à thread e retornou o valor e os dias esperados. A thread original
  permaneceu inalterada e nenhum canal foi acionado.

## E-mail pelo Zerai Channel Console

- [x] Substituir o outbox local pela chamada M2M idempotente ao perfil `email`.
- [x] Exigir endereço na última mensagem humana e não persistir o destinatário.
- [x] Montar valores somente do estado validado de cliente/acordo/pagamento.
- [x] Resposta determinística distingue aceitação pelo provedor de entrega.
- [x] Runtime 0.12.0 publicado com o canal inativo; sessões preservadas.
- [ ] Ativar o perfil e homologar um envio após o operador cadastrar o Resend.

- [x] CPF-only pilot contract: exact first three digits, no name or birth date;
  backend response guard removes extra identity factors added by the model and
  rejects model-side truncation of a longer value supplied by the user.

- [x] Direct inbound WhatsApp threads are created without customer/debt context;
  institutional OKF remains available and financial tools fail closed. Existing
  form-backed threads are preserved.
- [x] Legacy unclassified WhatsApp threads fail closed before inference and must
  use the existing `/reset-demo` rotation instead of reusing old fixture/history.
- [x] Railway 0.11.1 publicado no deployment
  `5750c955-e072-42ee-a7a6-699e293f8c41` a partir do merge `8774b54`.
  Uma sessão legada real retornou `whatsapp_session_requires_reset` sem alterar a
  contagem de 101 sessões; integridade permaneceu OK e nenhum canal foi acionado.
- [x] Railway 0.11.0 publicado no deployment
  `56d90db5-b283-4eea-9242-49d0ab9a48e3` a partir do merge `8f856bd`.
  PR [#24](https://github.com/markanthony91/simple-agent-template/pull/24);
  225 testes passaram, um foi ignorado, com 87,54% de cobertura; Ruff e imagem
  Docker 0.11.0 passaram.
  Backup `/data/backups/pre-whatsapp-unbound-0110-20260921` validado por
  integridade e hash lógico; 101 sessões, seis tabelas e zero falhas de chave
  estrangeira após o deploy. Nenhum canal foi acionado.

- [x] Railway 0.10.0 publicado no deployment
  `59600615-4ced-4760-b26b-5824f9e1d9d4` a partir do merge `86e973d`.
  Backup `/data/backups/pre-demo-context-0100-20260921-111500` validado por
  SHA-256; 101 sessões anteriores preservadas, seis tabelas presentes e
  `foreign_key_check` sem erros. Nenhum canal foi acionado.
- [x] Normalize Demo tenant, portfolio, customer, debt and session context in the
  existing persistent store without changing tool schemas or Playground data.
- [x] Make exact form/thread replay idempotent and reject changed data for an
  existing thread.
- [x] Define `thread_id = WhatsApp decision_id` as the channel binding contract.

- [x] Five-field server contract: full name, CPF, phone, amount and days overdue.
- [x] Creditor resolved from Zerai Canais with a server-only token.
- [x] Create-only session pinned to the future form's LangGraph thread.
- [x] Existing collection tools read the pinned form data after CPF-first-3 verification.
- [x] Presentation maps Canais Cedente to creditor and managed Assistant profile to agent name.
- [x] Railway backend 0.4.1 published: `26c57dc6-af67-4454-b718-bf445ed9c998`;
  live prompt smoke rendered `Fastpay / Sophia`, profile version 15, and unchanged
  Playground/session hashes were verified. Backup:
  `/data/backups/pre-future-demo-041-20260918-161510`.
- [x] Playground fixture and current frontend remain unchanged.
- [x] `/reset-demo` resets only future Demo sessions before LLM/tools, keeps the
  pinned fixture/snapshot and cuts previous messages from active context.
- [x] Railway backend 0.4.2 published: `c50fbdf9-9ade-40f1-96a3-adcd14e8a670`.
  Synthetic thread `f1887e35-7650-471a-b738-d61465dda21b` returned the reset
  receipt with one active message and three retained checkpoints; the state had
  identity false, zero offers/agreements/receipts and `reset_count=1`. The 29
  prior session rows, Playground fixture and 4,170 stable data files retained
  their pre-rollout hashes. Backup:
  `/data/backups/pre-reset-demo-042-20260918-163254`.
- [x] Railway backend 0.4.0 published: `1c727670-b324-46ca-b719-17c6009eee1a`;
  creditor catalog and unchanged Playground/session hashes verified. Backup:
  `/data/backups/pre-future-demo-040-20260918-143027`.
- [ ] Wire the future authenticated form; do not call this contract directly from a browser.
- [ ] Run the synthetic end-to-end through that future authenticated form.
- [ ] Map future-session data to each channel catalog entry's required template values.
- [ ] Move creditor and agent-name ownership into the selected portfolio configuration.

# Configurable identity — 0.2.5

- Published 0.2.5; Qwen validation and preserved histories confirmed. See
  docs/IDENTITY_RELEASE_2026-09-15.md for exact versions, timings and initial failure.

- 0.2.4 exposed a BlockingError in hosted async execution: reading session policy
  inside synchronous dynamic_prompt performed IO on the event loop. 0.2.5 moves
  the contract into the existing off-thread _filtered_request middleware.
- Regression asserts policy reads occur off the event loop; 126 tests pass,
  one skipped, 86% coverage, Ruff passes. The initial failed live run is retained.

- Existing fixture and conversation store reused; no new dependency or auth bypass.
- 125 pytest pass, one legacy integration skipped, 85% coverage; Ruff and Docker pass.
- Twelve policy combinations, generic failures, attempts/replay, isolation,
  revocation, pinning, safe context injection and legacy callers validated locally.
- Updated an old schema test to use invalid cpf type now that get_customer accepts
  no arguments; no-identity denial remains covered separately.
- Backup: /data/backups/pre-identity-024-20260915T193619Z, 12 conversations + volume.
- Publication and real-model acceptance pending; tests above use synthetic inputs.

# Tool usage inspection — 0.2.3

- Expose actual runtime descriptions and public input schemas via list_tools.
- Read-only contract inspection; no changes to permissions or execution.
- Ruff passes; 102 tests pass, one legacy integration skipped, 84% coverage.
- Contract regression covers all eleven tools and excludes injected runtime data.
- Published source fa3c8cc / runtime 0.2.3, Railway deployment
  a946629d-aba7-4f5f-9234-5b551a837d54 (SUCCESS).
- Eleven live contracts verified; nine prior conversation histories, active OKF
  snapshot and tool settings preserved. Backup:
  /data/backups/pre-tool-usage-20260915T171435Z (private, on-volume).
- Docker build passed on retry after the first local process exited 143.
- Local browser against published backend passes all eleven schemas, zero page
  errors, only list_tools; no provider call or business operation.

# Runtime audit corrections — 0.2.0

Scope: simple-agent-template and agent-chat-ui only. The original console and
WhatsApp are unchanged. No production data or published bundles are migrated.

- [x] 1. Lexical search and parseable OKF YAML, regression tests.
- [x] 2. Persistent, transactional state scoped to server thread ID.
- [x] 3. Policy receipts, Decimal offers, expiry and confirmation/idempotency.
- [x] 4. Incremental RAW drafts, conflict detection, indexes and append-only log.
- [x] 5. One LLM configuration, pinned snapshots and persistent server checkpoints.
- [x] 6. Three LOCAL synthetic journeys, frontend, streaming and provider cancellation.
- [x] Authorized Railway rollout with backup, Qwen tools and restart checks;
  see docs/RELEASE_2026-09-14.md for deployment IDs and limits.
- [x] Published Qwen battery: 14 browser turns + 1 API probe, 41 tool calls;
  see docs/QWEN_E2E_2026-09-14.md. Identity/action guards passed; financial text
  and autonomous GLOBAL discovery failed. No valid financial closing approved.
- [x] Prepare an isolated synthetic policy with complete scope/terms; separate entry remains unsupported.
- [x] Candidate: consolidate prompts and add bounded post-stream numeric review (not semantic approval).
- [x] Candidate: preserve existing nested paths and YAML metadata in section reads; test root conflicts.
- [x] Candidate: distinguish tool execution from domain outcomes.
- [x] Repeat isolated Qwen journeys; final iteration creates one simulated agreement with exact schedule.
- [x] Activate the approved RAW AGENTS root-casing instructions, with verified backup.
- [ ] Human review/publication of the proposed pilot bundle in the hosted application.
- [x] Frontend 0.1.1 / backend 0.2.2 rollout and published read-only Qwen browser E2E;
  see docs/RELEASE_2026-09-15.md. Financial live acceptance remains separate.
- [ ] Broader semantic regression validation; no full-fidelity guarantee from one successful run.

Delivery stages: local tests → branches/PRs → separately approved Railway rollout.
Passing local checks does not prove publication or real-Qwen E2E.
The E2E report records the tested financial journeys and current failures;
published end-to-end financial acceptance remains pending. Candidate/isolation
evidence and remaining failures: docs/OKF_INGESTION_GROUNDING.md.
Coordinate PR integration before another main autodeploy.

## Dummy payment pilot — 0.6.1

- [x] Normalize the synthetic test scope to `Will Bank` / `cartao_de_credito`.
- [x] Revalidate the agreement policy before creating invalid dummy PIX/boleto.
- [x] Capture explicit e-mail in a local outbox without external delivery.
- [x] Keep simulated settlement behind an authenticated admin operation.
- [x] Replace separate offer confirmation with one transactional offer/agreement/payment tool after the customer requests complete terms.
- [x] Validate happy, negative and neutral journeys locally.
- [x] Create and validate isolated Railway draft `will-bank-negotiation-pilot-20260920-185ae54d`.
- [x] Publish/activate the reviewed draft as `will-bank-negotiation-pilot-20260920-20260920T144839Z-d1e9d7be`.
- [x] Deploy backend 0.5.0 and run isolated Gemini conversations based on the
  anonymized Marcelo Barbosa replay; Qwen timed out before response.
- [x] Activate the reviewed draft.
- [x] Deploy 0.6.0 and verify atomic proposal/agreement/boleto creation through the managed Assistant.
- [x] Deploy 0.6.1 with punctuation-safe e-mail capture and complete the live boleto journey through settlement.
- [ ] Repeat the live PIX journey after the Gemini/Lovable bridge stops returning `provider_response_incomplete`; no PIX state was persisted by the failed runs.

## Scoped OKF search calibration — 0.7.0

- [x] Reproduce long navigation and wrong-branch selection with the managed Gemini Assistant.
- [x] Prove that prompt-only routing reduces calls but still selects a generic document with line-level ranking.
- [x] Rank whole documents, deduplicate paths and normalize installment terms.
- [x] Confirm the active Will Bank policy ranks first for boleto 3x and PIX à vista using an isolated copy of the published bundle.
- [x] Deploy 0.7.0 and complete controlled Gemini A/B trials.
- [x] Version the primary Assistant from 22 to 23 after 4/4 temporary calibrated payment runs succeeded.
- [x] Confirm boleto and PIX on Assistant v23, preserve the neutral `GLOBAL` path and remove all synthetic artifacts.

## Backend negotiation policy resolution — 0.8.1

- [x] Resolve one applicable policy inside the pinned snapshot without model-managed OKF navigation.
- [x] Fail closed for missing, draft, incompatible or ambiguous policy candidates.
- [x] Reduce negotiation from five Gemini calls and four tools to two Gemini calls and one tool.
- [x] Deploy Railway 0.8.1 and version the managed Assistant from 23 to 24 with exact read-back.
- [x] Complete published happy and unhappy conversations; negotiation fell from 10.81 s to 7.14 s.
- [x] Remove four synthetic conversations and return persistent sessions to the 52-row baseline.

## Atomic identity and deterministic replies — 0.9.1

- [x] Verify identity and return the pinned customer in one backend transaction.
- [x] Remove the legacy two-tool identity route from the model's tool catalog.
- [x] Render identity and proposal results from backend output without a post-tool model call.
- [x] Keep customer eligibility in the pinned session and commercial conditions in the matching published OKF policy.
- [x] Add regression coverage for identity data isolation, exact installment rendering and one-call graph routing.
- [x] Deploy Railway 0.9.1 and version the managed Assistant from 24 to 25 with exact read-back.
- [x] Repeat live happy/unhappy paths; identity reached 2.40 s and negotiation 3.15 s with one Gemini call each.
- [x] Remove three synthetic conversations and return persistent sessions to the 52-row baseline.
## Authorized rollout — 2026-09-15

- Initial 0.2.1 build failed before startup: pip bootstrap inherited a proxy
  unavailable to the Railway builder. Candidate 0.2.2 excludes proxy variables
  during bootstrap as well as uv sync, preserving all runtime LLM proxy settings.

- Server-pinned model verified with a request-override regression test: 101 tests
  pass, one skipped, 83% coverage; Ruff passes. No new model selector/dependency.
- Backup: `/data/backups/pre-runtime-021-20260915T154311Z` (six conversations,
  API exports and volume archive). Both deployments and published smoke passed;
  all previous conversation hashes and 3,228 data-file hashes preserved.
- Preserve the existing OKF bundle; the separate invented pilot policy is not
  implicitly approved by a code deployment.

## RAW instruction versions (0.2.7)

- [x] Preserve legacy instructions; atomic version history with serialized saves.
- [x] Newest-first paginated history and active version exposed by compiler graph.
- [x] 135 unit tests passed, 86% coverage overall and 90% compiler coverage.
- [x] Railway 0.2.7 published: `7eb7e7ab-4907-4e58-8d5e-ee601e33fd20`.
- [x] 31 conversation states, managed Assistant context/version and 4148 Markdown hashes preserved.
- [x] Published UI saved unchanged RAW content into v2, retained v1 and reloaded it.
# LLM and agent profile settings (0.3.0)

- [x] Per-request temperature, top-p and output limit; optional agent identity/style.
- [x] Admin metadata and validation; server-defined connections and existing safety gates retained.
- [x] Sampling/profile and provider-fallback protocol tests; see docs/LLM_AGENT_SETTINGS.md for current results.
- [x] Versioned principal/fallback selection, sanitized integration metadata and dedicated Lovable bridge source.
- [x] Authorized connection preparation: bridge deployed, Gemini registered, live Gemini/Qwen tools and published availability verified on backend 0.3.2; see docs/LOVABLE_CONNECTION_2026-09-17.md. Fallback remains off; activation is exclusively Marcelo's action.
- [x] Authorized deployment-only Railway rollout, both services 0.3.0; published settings and Qwen tool/profile check passed.
- [x] Original conversations, managed Assistant settings and all 25 previous session rows preserved; 4170 file hashes unchanged after canaries, with two new synthetic SQLite sessions.
- [ ] Known model limitation: spontaneous self-introduction was omitted in the time-query probe; explicit name query passed. See docs/RELEASE_LLM_SETTINGS_2026-09-17.md.
