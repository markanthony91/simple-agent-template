# LLM settings rollout - 2026-09-17

Marcelo authorized Railway deployment and explicitly reserved provider/fallback
activation to himself. No Lovable bridge was deployed, no optional provider
variables were created, and no existing Assistant prompt/profile/sampling or
integration settings were changed. The default Qwen connection remains active.

## Backup and preservation

Before rollout, all 35 conversations were idle. Backup on the existing volume:
`/data/backups/pre-llm-settings-20260917T194700Z`.

- API exports: 35 thread records/states/histories and four Assistants/versions.
- Volume archive SHA-256:
  `9c493984c44ffadee7523e40af7013debbff0a439eba1e6efd4a06a820114996`.
- Hash manifest: 4171 existing data files (excludes backups/runtime checkpoints).
- Retained `/data`, one replica, `/app/.langgraph_api -> /data/langgraph`,
  existing start command and 30-second draining environment variable.
- Post-backend comparison: all 35 thread states, all 4171 original file hashes,
  and managed Assistant context/version/config/metadata/name unchanged.
  Evidence retained privately at `post-deploy-verification.json` in the backup.
- After the two browser canaries, all 35 original thread states and managed
  Assistant settings still match. 4170 file hashes remain unchanged; the session
  SQLite file changed only by adding two synthetic sessions. All 25 pre-existing
  session rows were compared to the archived database and remain byte-for-byte
  unchanged. Evidence: `post-smoke-verification.json`.

## Deployments

Backend 0.3.0, source `fe89fb90bf082fd71096eb34325d3cb89b0acde4`:
`bcdffb85-71cf-4906-b058-0408ba2b806f`, SUCCESS. `/info` returns 200;
installed package version and volume symlink verified through Railway SSH.

Frontend 0.3.0, source `d0ef04f`:
`5962ca83-8fd3-47a7-9caa-8201b7197d22`, SUCCESS. Installed package version
verified through Railway SSH; public site served the new settings tabs.
The four deployed backend source files for model construction, fallback,
settings validation and managed graph match the local source hashes.

Published browser acceptance passed in 24.6 seconds using a disposable Assistant:
zero temperature/profile save, three confirmed native versions, reload,
desktop/mobile layout, disabled unconfigured providers and fallback off. A real
Qwen inference called utc_now once, returned the timestamp, and recorded
`llm_route.connection=default`, `fallback_used=false`. On an explicit follow-up,
Qwen identified the configured name Sofia. No JavaScript errors. The managed
Assistant context/version was unchanged; the disposable Assistant and conversation
were deleted in the test cleanup.

The initial probe failed its spontaneous-introduction assertion: Qwen answered
the time without introducing Sofia. This is a recorded behavioral limitation,
not a persistence failure. The acceptance test separates that observation from
functional save/routing checks and explicitly verifies the model knows its name.
Synthetic context and sampling were the same in both probes.
Test: agent-chat-ui `tests/e2e/published-runtime-settings.spec.ts`.

Sources were deployed from their tested feature branches via Railway CLI; PRs
remain available for review. No merge into the older main branches was required.

Rollback backend deployment:
`7eb7e7ab-4907-4e58-8d5e-ee601e33fd20` (0.2.7).
Rollback frontend deployment:
`f1430cd8-8194-4e41-bed6-7b4821fdd111` (0.2.0).
Keep the volume and Assistant version history. Do not remove or overwrite
conversation data when reverting an application image.

## Activation boundary

The runtime reports `default.configured=true`, `lovable.configured=false` and
`external.configured=false`. A connection is registered only when server endpoint,
model and credential are present. Provider registration and the optional bridge
setup remain manual follow-up for Marcelo; see `integrations/lovable/README.md`.
Fallback controls remain off. Live Gemini/GPT/fallback activation testing is
outside this authorized rollout and was deliberately not performed.
