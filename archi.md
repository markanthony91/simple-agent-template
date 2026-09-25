# Architecture — 0.12.0

Next.js UI → LangGraph API → managed_graph → one configured ChatOpenAI adapter.
Model tool calls → LangChain schema validation → enabled-tool middleware →
session-authorized tool → deterministic direct reply for identity/payment actions.

ElevenLabs server tool → authenticated custom LangGraph route → existing
session/payment validation → `send_payment_instruction` service → Zerai Canais.
The voice adapter cannot provide or override financial terms.

System prompt, AGENTS.md and WORKFLOW.md remain external operational instructions.
OKF provides policy, not account balances. No RAG, embeddings or vector database.

- /data/okf: immutable bundles, active pointer, drafts and preserved RAW.
- /data/sessions/sessions.sqlite3: Playground fixture/session state and normalized
  Demo tenant, portfolio, customer, debt and session context. Identity, receipts,
  offers, idempotent agreements, dummy payments and e-mail dispatch records remain keyed by
  server `thread_id`.
- /data/simulator: editable synthetic fixture for NEW conversations.
- /data/tools: tool enablement checked on execution as well as model request.
- /data/langgraph: LangGraph dev-server checkpoints, linked by startup.

Snapshot and fixture are pinned at the first inference; publication does not
silently change an ongoing conversation. SQLite transactions serialize short
state operations only; no transaction holds a network LLM call.

Identity verification and customer lookup share one SQLite transaction. Only a
successful verification marks the debt as read and returns the pinned customer.
The model no longer receives the legacy two-tool path.

For a personal negotiation, the payment tool scans only policy-shaped documents
in the pinned snapshot and accepts exactly one published, current policy matching
the fixture's institution and product. The session fixture limits eligibility;
the OKF policy limits commercial terms, payment methods and delivery channels.
Either source may restrict a request and neither may broaden the other.

The future Demo form uses the existing admin graph only as a server-side contract:
it resolves `creditor_name` from Zerai Canais, then atomically creates the normalized
tenant/portfolio/customer/debt records and their session binding keyed by the target
`thread_id`. Tools reconstruct the same fixture contract from those rows, so their
schemas do not change. It never updates the global Playground fixture. An exact
repeat is idempotent; different data cannot overwrite an existing session.

Before inbound WhatsApp inference, `okf_admin.ensure_whatsapp_session` creates an
unbound session only when that thread has no stored context. Unbound sessions have
no fixture or normalized debt relationship; middleware removes financial tools and
the execution guard rejects them even if a model attempts a stale tool call. An
existing form-backed session is never replaced.
An older plain session cannot be classified safely, so preparation returns
`whatsapp_session_requires_reset` before inference. The Console pauses it; the
existing `/reset-demo` path rotates to a fresh thread while retaining audit history.

RAW → immutable source/hash → lexical manifest + selected concepts → create,
append or noop → incomplete draft → index/log → validation → human review →
atomic immutable publication. Conflicts do not auto-resolve. Failed partial
drafts cannot publish; restarting ingestion reuses a complete plan/result.

No new Redis, worker fleet or PostgreSQL dependency: this service is the existing
single-replica LangGraph laboratory, not the earlier FastAPI application.
The dev server periodically flushes checkpoints: hard crashes can lose recent
conversation messages. Durable transactional session state does not make the
dev server a production-grade execution queue.

Text still streams before semantic validation; this release does not implement
an output Evidence Gate. Backend action validation is not proof of text fidelity.

Customer-requested terms including PIX/boleto → one policy-gated transaction that
creates offer, agreement and invalid dummy payment → explicit e-mail address →
idempotent dispatch through Zerai Canais. The e-mail address is sent to the channel
provider but is not persisted in the session. Provider acceptance is rendered by
the backend and never described as delivery. The agent can only read payment status.
Settlement is an authenticated `okf_admin` operation standing in for the future
payment-provider webhook and is not registered as an agent tool.

For identity and payment transactions, return-direct routing skips the post-tool
model call and middleware appends a deterministic AI message from the tool result.
The same numeric audit annotates that message. Other answers keep the existing
post-stream audit; absence of a mismatch does not prove semantic fidelity.
System/AGENTS/workflow defaults are composed once, without a duplicate hidden
commercial prompt in Python. Saved context overrides remain supported.
The RAW compiler canonicalizes new roots and rejects case collisions; exact
existing append/noop targets remain unchanged. Published bundles are not migrated.
# Agent profile and sampling configuration

Assistant context stores `agent_profile`, `llm_settings` and `llm_integration` with native versioning.
The managed graph appends profile instructions after the operator prompt,
AGENTS and workflow; the existing middleware then appends the identity contract
and supplies validated sampling parameters per model request. No global model
mutation or new persistence service is introduced. `okf_admin` reports only safe
server defaults and validates operator edits. RAW compilation is unchanged.

The chat-only fallback middleware selects one of three server-defined connections.
It retries the same model request once on the backup for transient provider/network
errors before any streamed chunk, preserving the tool history and identity contract.
Per-call callbacks track stream start without mutating the shared model. Tool
execution and graph state are never replayed. The optional dedicated Lovable
Edge bridge only authenticates and forwards payloads to its fixed gateway; the
existing playground is not used because it changes prompts and omits tools.
