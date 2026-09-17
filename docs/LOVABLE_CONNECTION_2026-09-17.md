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
The Railway connection will register Gemini; allowing a model at the bridge does
not select it in the runtime or enable fallback.

## Preservation and rollback

Pre-change backup: `/data/backups/pre-lovable-connection-20260917T203229Z`.
35 conversations, four Assistants and 4171 data-file hashes; volume archive SHA-256:
`463bf866bd4af32deb8834572f064269eca413904fbf05d187f43189778820f5`.
Previous backend deployment: `bcdffb85-71cf-4906-b058-0408ba2b806f` (0.3.0).
Keep `/data`, Assistant context/version and the active Qwen connection.
Rollback removes only the optional Lovable connection variables and dedicated
function/verifier after stopping its traffic, retaining the volume and backups.

## Validation/status

- Backend 0.3.1 changes only the bridge package and version; no chat routing change.
- 169 Python tests and Ruff pass; bridge contract check passes including rejection
  of the public verifier as a bearer, missing configuration, invalid model/fields,
  oversized payload, upstream errors and preservation of prompt/tools/zero/SSE.
- Edge deployment, live Gemini tool check, Railway registration and UI availability
  are in progress. Fallback stays off and the managed Assistant is untouched.

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
An isolated process on Railway with this exact correction completed the live
Gemini loop: two model calls, one utc_now, all system/AGENTS/workflow/profile
markers observed by the callback, temperature zero on both calls. Persistent
Assistant and fallback settings were never edited. Deployment of 0.3.2 follows.

The SDK also concatenated the repeated provider `model_name` metadata. The
`llm_route.model` field retains the registered model identifier; no assertion of
a different model is made from the duplicated SDK string.
