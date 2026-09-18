# Lovable connection preparation - 2026-09-17

Marcelo authorized preparing/deploying the connection after the 0.3.0 rollout.
Selecting the fallback in the managed Assistant remains exclusively his action.
Registration, isolated connection checks and deployment do not change that selection.

Target: dedicated `llm-bridge` function in existing Lovable project
`ac0154a8-fb7e-4316-bebe-0b89235cabc8` / Supabase `pslmuzlndwtwcxezxefj`.
The existing Smart Debt frontend, business functions, portfolio routing, prompts
and database are outside this change. The function has a fixed Lovable gateway
upstream; `LOVABLE_API_KEY` remains in the existing Lovable environment.

## Authentication

A random 48-byte bridge bearer token was generated in memory and stored directly
in Railway `LLM_LOVABLE_API_KEY` using stdin and `--skip-deploys`. Its value was
not included in shell arguments, source, chat or a local file. The function needs
only its public SHA-256 verifier, kept in its deployment-specific `config.ts`.
The repo template fails closed until configured. Sending the verifier itself
as a bearer is rejected; the local contract test covers this. Timing-safe
comparison uses Node crypto primitives supported by the Edge runtime.

Allowed bridge model IDs: `google/gemini-3-flash-preview`, `openai/gpt-5-mini`.
The Railway connection registers Gemini; allowing a model at the bridge does
not select it in the runtime or enable fallback.

## Preservation and rollback

Pre-change backup: `/data/backups/pre-lovable-connection-20260917T203229Z`.
35 conversations, four Assistants and 4171 data-file hashes; volume archive SHA-256:
`463bf866bd4af32deb8834572f064269eca413904fbf05d187f43189778820f5`.
Previous backend deployment: `bcdffb85-71cf-4906-b058-0408ba2b806f` (0.3.0).
Keep `/data`, Assistant context/version and the active Qwen connection.
Rollback removes only the optional Lovable connection variables and dedicated
function/verifier after stopping its traffic, retaining the volume and backups.

## Published validation

Connection preparation is complete; fallback remains disabled. Backend 0.3.2,
source `c317c51`, deployment `4a5d7c7e-3d30-4cec-8ad2-4005856de77f` is SUCCESS.
Frontend remains 0.3.0, source `d0ef04f`, deployment
`5962ca83-8fd3-47a7-9caa-8201b7197d22`. The Lovable Edge deployment is commit
`7b293f8fc763e8a128a59cee03af0c2416bf3a1a`; its diff contains only the new
bridge implementation/config and the dedicated function entry in config.toml.
No frontend publication, business function or database change in Lovable.

- Edge Deno check and local Node bridge contract check passed. Real HTTP probes
  returned 401 for invalid bearer and verifier-as-bearer, 400 for disallowed
  model and 200 for Gemini inference. No bearer or Lovable key was exported.
- The final deployed graph completed isolated live Gemini and Qwen tool loops:
  each made two model calls and one utc_now call. The callback confirmed all
  System/AGENTS/workflow/profile markers and temperature zero on both calls.
  These probes select a connection only in their isolated graph context; they
  never save a fallback or alter the managed Assistant.
- Published Playwright check passed (7.5 seconds): Lovable option available,
  default primary, fallback off, Save disabled, desktop/mobile layout and zero
  page errors; managed Assistant context/version unchanged. The test initially
  hit a Chromium response-body retrieval race after the SSE request was removed;
  it now checks rendered availability. Actual model identity is checked by the
  separate live provider probe, not inferred from the browser test environment.
- Final volume verification: all 35 prior conversation states, managed Assistant
  fields and 27 prior SQLite session rows unchanged. All 4171 tracked data files
  preserved, allowing the verified SQLite database's one additional synthetic
  session row. Verification is stored in the backup as
  `post-connection-verification.json`.
- Primary remains `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8`. Lovable is configured
  with `google/gemini-3-flash-preview`; external is unconfigured. GPT is allowed
  by the bridge but was neither registered nor tested.

To activate, Marcelo opens Settings > LLM > Conexão de fallback, chooses
Lovable (Gemini ou GPT), and clicks Salvar LLM. The prepared model is Gemini.
No real primary outage was induced: automatic retry boundaries are verified
by intercepted-HTTP graph tests; both provider connections were tested live
independently. These checks are not an instruction-adherence benchmark.

## Streaming compatibility correction (0.3.2)

The initial real tool check on 0.3.1 failed with `provider_response_incomplete`.
Inspection of the original SSE showed two identical `tool_calls` finish markers
across three chunks. LangChain concatenated them into `tool_callstool_calls`.
The shared completion check now canonicalizes only repetitions of the same
accepted marker (`stop` or `tool_calls`); missing, mixed, truncated and filtered
reasons still fail. No response text, tool payload or prompt is rewritten.

181 Python tests pass with 87% overall coverage, including actual graph/HTTP
streams with duplicated finishes before and after tool execution, and rejection
of `stoplength`, `tool_callsstop`, `length`, missing/unknown reasons. Ruff passes.
The final deployed 0.3.2 process completed the live
Gemini loop: two model calls, one utc_now, all system/AGENTS/workflow/profile
markers observed by the callback, temperature zero on both calls. Persistent
Assistant and fallback settings were never edited.

The SDK also concatenated the repeated provider `model_name` metadata. The
`llm_route.model` field retains the registered model identifier; no assertion of
a different model is made from the duplicated SDK string.
