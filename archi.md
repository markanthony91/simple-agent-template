# Architecture — 0.2.2

Next.js UI → LangGraph API → managed_graph → one configured ChatOpenAI adapter.
Model tool calls → LangChain schema validation → enabled-tool middleware →
session-authorized tool → result → next inference.

System prompt, AGENTS.md and WORKFLOW.md remain external operational instructions.
OKF provides policy, not account balances. No RAG, embeddings or vector database.

- /data/okf: immutable bundles, active pointer, drafts and preserved RAW.
- /data/sessions/sessions.sqlite3: fixture copy, identity, read receipts, expiring
  offers and idempotent agreements per server thread_id.
- /data/simulator: editable synthetic fixture for NEW conversations.
- /data/tools: tool enablement checked on execution as well as model request.
- /data/langgraph: LangGraph dev-server checkpoints, linked by startup.

Snapshot and fixture are pinned at the first inference; publication does not
silently change an ongoing conversation. SQLite transactions serialize short
state operations only; no transaction holds a network LLM call.

The future Demo form uses the existing admin graph only as a server-side contract:
it resolves `creditor_name` from Zerai Canais, then creates one new row keyed by
the target `thread_id` in the same sessions SQLite database. It never updates the
global Playground fixture and never overwrites an existing session.

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

The existing middleware annotates the final AI message with response_audit:
explicit BRL/percentage checks against authorized customer/offer results.
No response rewrite, extra LLM call, or retry. Absence of a numeric mismatch does
not prove semantic fidelity. Frontend 0.1.1 explains this limitation beside the text.
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
