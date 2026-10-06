# Controlled rollout / rollback

1. Review backend/frontend branches and test evidence. Do not treat a commit as deployed.
2. Back up the existing /data volume and export current LangGraph conversations
   before changing the deployment. The old .langgraph_api directory may be ephemeral.
3. Preserve the Railway Volume at /data and exactly one replica. Configure canonical
   LLM variables securely; do not copy keys into the frontend.
   For the ElevenLabs e-mail bridge, configure `ELEVENLABS_RUNTIME_API_TOKEN` in
   the Runtime and only in the new ElevenLabs server tool. Configure
   `CHANNEL_CONSOLE_AGENT_RUNTIME_TOKEN` with the same value as
   `AGENT_RUNTIME_API_TOKEN` in Canais. Keep both credentials distinct.
   For the future Demo form, copy the existing Canais M2M token server-to-server
   into `CHANNEL_CONSOLE_ENGINE_TOKEN` and set `CHANNEL_CONSOLE_URL` while the
   legacy fallback is still needed. Never print or expose tokens. Catalog failure
   must prevent session creation.
4. Build the Dockerfile. Railway's custom start command can bypass ENTRYPOINT.
   Explicitly configure `sh -c 'exec python -m simple_agent.startup langgraph dev --host
   0.0.0.0 --port ${PORT:-2024} --no-browser --no-reload'` and healthcheck `/info`.
   Set `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=30` so the in-memory runtime has time
   to flush its checkpoints during graceful shutdown. Do not rely on an outer shell
   forwarding signals. This does not guarantee crash-safe transactional persistence.
   Publish a new deployment to apply changed settings: redeploying an earlier
   deployment can reuse its old start command. Verify the running command and
   `/app/.langgraph_api` symlink target `/data/langgraph` via SSH.
   An existing different checkpoint directory causes startup to stop rather than
   overwrite it; migrate a verified backup explicitly. Export history via the API
   too: a running in-memory server may not have flushed checkpoint files to disk.
5. Publish backend and companion frontend together in a controlled maintenance window.
   Old clients cannot publish without the new approved flag. New clients send it
   only after operator confirmation. This is intent capture, not admin authentication.
6. Start a NEW synthetic conversation. Verify atomic identity/customer lookup →
   requested terms → deterministic proposal/payment response. Verify another thread
   cannot reuse identity or offer.
7. Check /info (application), then a protected synthetic tool loop (provider/runtime).
   /info alone does not establish Qwen availability.

Rollback: restore the previous images/config and active bundle pointer after review.
Retain /data, including sessions and immutable versions. Rolling back to the old
global simulator code reintroduces the identity-isolation defect; do not use real data.
Repeated publication returns the same version without reactivating an old version.
Do not run simultaneous replicas against this local persistence architecture.

No live deployment, variable change, migration or gateway load test is implied
by the local test suite. Existing assistant prompt/workflow overrides are preserved:
review and update them explicitly; changing config/*.md cannot replace overrides.

## Isolated OSS PostgreSQL canary

The Dockerfile starts `simple_agent.oss_runtime:app` only when
`OSS_RUNTIME_ENABLED=true`. Set that variable on the isolated canary alongside
`SESSION_BACKEND=postgres`, `LANGGRAPH_STRICT_MSGPACK=true`,
`SESSION_DATABASE_URL` for its own database, and a distinct
`OSS_RUNTIME_API_TOKEN` of at least 32 characters. Browser origins, if needed,
must be enumerated in `OSS_RUNTIME_CORS_ORIGINS`. Do not set these on the
current principal as an incidental effect of building the image. On an empty
PostgreSQL database, apply the repository migrations, import the Assistant
definitions from a verified snapshot with `scripts/import_legacy_assistants.py`,
and then start the canary. Startup creates empty conversation/archive tables and the OSS
checkpoint schema; importing old threads is optional. The `legacy_assistants`
table holds active Assistant configuration despite its historical name. Do not
point this fresh start at the populated migration database or the current
principal database. Keep the existing volume and database unchanged. The prior
import and its evidence are documented in
[OSS_CHECKPOINT_CANARY_2026-10-02.md](OSS_CHECKPOINT_CANARY_2026-10-02.md).

Before any future route change, export the **live API state**, reconcile
sessions, agreements, payment instructions, OKF data and Assistant versions.
If old conversations are intentionally discarded, start new thread IDs and
expect customers to repeat identity verification; do not discard operational
records with the chat history. Test HTTP/SSE and the real clients, and record
the current main deployment as the return target. Keep the old volume and its
Railway backup. There is no automatic dual-write or rejoin API in the canary,
so a failed post-cutover run cannot be assumed to exist on the old SQLite
service. A rollback decision must
account for work created after the switch.

For Redis-backed execution, set `OSS_RUNTIME_REDIS_ENABLED=true` and
`OSS_RUNTIME_REDIS_URL` only on the isolated Runtime. `OSS_RUNTIME_REDIS_DB=1`
keeps its transient keys separate from Playground and Canais, which currently
use database 0. Run input, status and final result stay in PostgreSQL. A
disconnected client can query `/runs/{run_id}`; live streaming does not replay
every intermediate event. Cancellation is checked between graph events, not
during a blocked model or tool call. Since 0.17.3, a run has a 30-second
PostgreSQL lease renewed every 5 seconds. A new worker marks an expired run
`failed` with `error_code=worker_lost`; it never replays the input because a
prior tool may already have sent an external instruction. Reconcile the
business outcome before manually retrying. Real client compatibility still
needs integrated testing before any traffic cutover.

On 2026-10-05, the isolated Railway services were renamed **Agente de Homologação**
(`accedeb1-4a8d-455e-a7ed-f4d2d7d92dec`, previously **Agente de Testes**)
and **Dados de Homologação** (`4fe1fa72-c700-44fe-9132-6c8240d9e556`,
previously **Dados de Testes**). Their IDs and the database's
private hostname did not change. The Redis-enabled test deployment is
`8362ba5d-9f25-4ff7-bf5e-1da8b6615c91`; no client route was changed. The
principal Railway service's GitHub auto-deploy is disabled so `main` can hold
the tested code without publishing it to customer traffic. Check this setting
explicitly before the later production cutover.

For the current operator-facing Railway labels and stable service IDs, see
[Railway service labels](RAILWAY_SERVICES.md).

O teste de 05/10 com PostgreSQL, Redis, o mesmo bundle OKF do principal e uma
conversa sintética está em
[Homologação PostgreSQL, Redis e OKF](POSTGRES_REDIS_HOMOLOGATION_2026-10-05.md).
Ainda há bloqueios de recuperação de runs e integração real dos clientes antes
de qualquer virada de tráfego.
