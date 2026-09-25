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
