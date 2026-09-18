# Future Demo form backend

Version 0.4.2 prepares the current Railway agent runtime for a separate future
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

## Temporary presentation mapping

- `creditor`: the `creditor_name` returned by Canais, which is the **Cedente**
  field in the current screen (`Fastpay` in the validated configuration).
- Agent name: `agent_profile.name` from the selected managed Assistant (`Sophia`
  in the current profile). It is already injected into the model context and is
  not copied into the form payload or SQLite session.

For future-form sessions, the backend replaces only the literal placeholders
`{{credor}}` and `{{nome_agente}}` before the prompt reaches the model. Other
System Prompt placeholders are not inferred or rendered by this contract.

Both are temporary sources. When portfolio configuration owns these fields, the
authenticated future route must resolve them from the selected portfolio instead.

Channel template rendering is already enforced by Zerai Canais: SMS is rendered
before transport, Meta receives approved template parameters, and ElevenLabs
receives `dynamic_variables`. The future route still must map session fields into
each catalog entry's exact `required` keys before requesting a dispatch.

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
- The exact command `/reset-demo` is handled before any model/tool call and only
  for a session created by this contract. It preserves the fixture, creditor and
  pinned OKF snapshot; clears identity, attempts, offers, agreements, receipts and
  transient state; and replaces the active message context with a reset receipt.
  Historical LangGraph checkpoints remain available for audit. Playground or
  unknown sessions receive `Comando indisponível nesta sessão.` and are unchanged.
- No WhatsApp, SMS, call, offer or agreement is triggered by creating the session.

## Validation

Tests use only temporary SQLite databases, a fake Canais response and synthetic
identities. They verify validation, non-overwrite, Playground preservation,
CPF-first-3 identity and tool reads without external calls.
They also verify exact-command matching, Demo-only isolation, operational reset
and removal of prior messages from the active model context.
