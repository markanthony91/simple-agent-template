# Future Demo form backend

Version 0.4.0 prepares the current Railway agent runtime for a separate future
interface. It does not change the existing Playground or its Simulator panel.

## Contract

The future server creates a LangGraph thread, then invokes the `okf_admin` graph
with operator approval and this input:

```json
{
  "operation": "create_future_demo_session",
  "approved": true,
  "thread_id": "the-new-langgraph-thread-id",
  "demo_form": {
    "full_name": "Synthetic Test",
    "cpf": "a valid synthetic CPF",
    "phone": "+55 plus DDD and nine-digit mobile",
    "amount": "850.00",
    "days_overdue": 42
  }
}
```

The backend validates every field, reads `creditor_name` from
`GET /api/engine/v1/channels`, builds internal customer/debt/contract identifiers
and inserts a new isolated session. An existing `thread_id` is never overwritten.
The response masks CPF and phone and does not return the stored fixture.

The pinned identity rule matches the Smart Debt Demo: three first CPF digits,
three attempts, no secondary factor. Before verification, collection tools do
not expose financial fields. After `verified=true`, `get_customer()` returns the
pinned name, masked CPF/phone, creditor, amount and the submitted days overdue.

## Railway configuration

Set only on `langgraph-simple-agent-clean`:

- `CHANNEL_CONSOLE_URL`: Zerai Canais URL. Railway's generated service URL is valid.
- `CHANNEL_CONSOLE_ENGINE_TOKEN`: same M2M token accepted by the Canais Engine API.

Both values stay server-side. A missing/unavailable catalog fails before writing.
Do not place the token in Next.js public variables, graph input, logs or tickets.

## Boundaries

- The current Playground global fixture remains unchanged.
- This is a synthetic single-operator lab, not an authenticated public intake API.
- The future UI must call from an authenticated server route, never directly from
  browser JavaScript. `approved=true` records intent; it is not authentication.
- The creditor is snapshotted at creation. Later Canais edits do not rewrite an
  existing conversation.
- Reset is intentionally not added here: safely cutting LangGraph message history
  belongs to the future interface/session lifecycle, not the data-ingestion contract.
- No WhatsApp, SMS, call, offer or agreement is triggered by creating the session.

## Validation

Tests use only temporary SQLite databases, a fake Canais response and synthetic
identities. They verify validation, non-overwrite, Playground preservation,
CPF-first-3 identity and tool reads without external calls.
