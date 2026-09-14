# Architecture — 0.2.0

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
