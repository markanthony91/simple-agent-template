# LLM integration, fallback and agent profile - 2026-09-17

Published version 0.3.0 extends the existing instruction-versioning deployment
branches; do not replace them with the older main branches. Companion frontend:
agent-chat-ui `feat/llm-agent-settings`, also 0.3.0. No new dependencies/migrations.

## Behavior and configuration

The LLM tab edits validated sampling and selects primary/optional fallback from
server-registered connections. Integration metadata exposes sanitized endpoint,
model, read timeout, proxy status and credential presence; never credential values.
The profile tab sets presentation name, role and tone. Both use versioned
Assistant context, preserve existing prompts and confirm read-back before success.

Connection registration remains server-managed: default `LLM_*`, optional
`LLM_LOVABLE_*` and `LLM_EXTERNAL_*` as listed in `.env.example`. Each connection
uses its own endpoint/key/model/proxy/timeout. No primary proxy or credential is
implicitly reused for another connection. Restart the runtime after changing
server variables. The UI can only select available connections, not inject URLs
or keys. Configuration presence is not a successful connection test.

Fallback is off by default. For connection failures/timeouts/HTTP 408, 429 and
5xx, retry the same inference once with the selected backup before any response
chunk (including empty/tool chunks) is emitted. Preserve prompt, history, tool
schemas/results and sampling parameters. Never replay the graph or a completed
tool. Start with the primary again on the next model inference. Do not retry
partial streams, cancellations, invalid inputs, authorization/billing failures,
refusals or domain errors. If the backup fails, surface its error without cycling.
Final AI messages include `additional_kwargs.llm_route` (connection/model/
fallback_used); fallback logs contain hostname and non-sensitive error metadata.
RAW compilation keeps its original default-only connection.

Lovable integration uses the prepared [dedicated bridge](../integrations/lovable/README.md).
Read-only inspection of the existing `playground-chat` on 2026-09-17 confirmed
that it adds its own system directives/RAG/portfolio context, uses
`temperature || 0.7` (losing zero), and does not forward tool schemas. Reusing it
would change the behavior being tested. The dedicated bridge forwards payloads
and SSE to the fixed Lovable gateway with a separate server token; the Lovable
key stays in the Lovable environment. Gemini or GPT is selected by the registered
model ID and bridge allowlist. Model availability, parameter support, quota and
live tool compatibility remain to be verified after deployment. Some models
reject temperature/top-p; clear these overrides when required, never silently
remove an explicitly saved parameter.

## Validation

- 169 Python unit/protocol tests, 87% overall coverage. The settings module has
  100% coverage; fallback middleware 96%. Ruff passes.
- Real LangGraph tool loops against intercepted HTTP prove temperature=0,
  top_p=0.8 and the token cap reach both connections; System/AGENTS/workflow,
  profile, identity contract, tool definitions/results survive fallback before
  or after a tool call. The tool executes once. Subsequent runs do not leak
  settings/profile. Invalid settings fail before provider inference.
- Simulated 408/429/500/timeouts retry; 400/401/402/403, cancellation and streams
  interrupted after text or tool chunks do not retry. Sync routing is covered.
- Bridge contract check passes with Node 24, intercepted fetch: authentication,
  model/parameter allowlists, body cap, zero temperature, tool call IDs, unchanged
  prompt/results/SSE, and status-preserving generic upstream errors.
- Frontend: 18 browser/helper checks pass, including desktop/mobile save/reload,
  fallback persistence, unavailable connections, prompt preservation, version
  confirmation and failed saves. TypeScript, production webpack build and ESLint
  pass (25 existing warnings, zero errors). UI coverage percentage not measured.

These are local protocol tests, not live inference or prompt-adherence benchmarks.
The bridge has not been deployed/validated in Supabase Deno or against live
Gemini/GPT: activation is reserved exclusively to Marcelo. Published Qwen/UI
checks and the spontaneous-presentation limitation are recorded in
[rollout evidence](RELEASE_LLM_SETTINGS_2026-09-17.md). Fallback improves
availability, not instruction obedience.

## Publication and rollback

Release status: backend and frontend 0.3.0 published on 2026-09-17 after explicit
deployment-only approval. [Evidence and rollback](RELEASE_LLM_SETTINGS_2026-09-17.md).
Current Assistant settings and conversations were preserved. No optional provider
was activated/configured; no Lovable bridge was deployed. Activation remains
Marcelo's action. For later deployments, follow DEPLOYMENT.md and progress.md.
Deploy backend before frontend. Use a disposable Assistant for published checks:
save/reload both tabs, synthetic greeting, read-only tool round and a controlled
primary failure. Keep the operator's current Assistant/prompts unchanged.

Rollback: disable fallback, restore previous frontend/backend deployments,
retain /data and Assistant version history. Previous backends ignore the three
new context fields. Remove only the dedicated bridge after traffic has stopped.
No existing prompt, workflow, policy or business function is rewritten.
