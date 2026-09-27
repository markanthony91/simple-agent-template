# Dedicated Lovable bridge

`llm-bridge/index.ts` is an independent Supabase Edge Function for the Agent Chat
runtime. It forwards the OpenAI Chat Completions payload and SSE unchanged to
Lovable's gateway. It does not use the existing playground, portfolio router,
RAG, boleto, prompt augmentation, or business tools. The runtime executes tools.

Connection preparation was authorized on 2026-09-17; selecting/enabling fallback
remains exclusively Marcelo's action. Registration is not activation.

Deployment procedure:

1. Copy `llm-bridge/index.ts` and `llm-bridge/config.ts` into
   `supabase/functions/llm-bridge/` in the existing Lovable project. Add only this function to its Supabase config:
   ```toml
   [functions.llm-bridge]
   verify_jwt = false
   ```
   The function authenticates every POST with its own bearer token. Disabling
   Supabase JWT validation here does not make it anonymous. Do not change other
   functions or their authentication.
2. Generate a random bridge bearer token (at least 32 random bytes) and store it
   directly in the Railway secret variable `LLM_LOVABLE_API_KEY`, using stdin
   and `--skip-deploys`. Never include its value in a chat, source or shell argument.
   Configure only its SHA-256 verifier and the allowed model IDs in the deployed
   `config.ts`. The committed template is empty and fails closed. The verifier
   cannot be used as a bearer token; the contract test checks this explicitly.
   Alternatively the bridge supports `LLM_BRIDGE_TOKEN_SHA256` and comma-separated
   `LLM_BRIDGE_MODELS` environment overrides. Keep the existing `LOVABLE_API_KEY`
   in the Lovable environment; never export it to Railway/browser. Deploy only
   this function. Token rotation replaces the Railway token and bridge verifier.
3. In Railway backend variables, set:
   - `LLM_LOVABLE_BASE_URL=https://<project>.supabase.co/functions/v1/llm-bridge/v1`
   - `LLM_LOVABLE_MODEL=<one allowed model ID>`
   - `LLM_LOVABLE_API_KEY=<the bridge token, not the Lovable key>`
   - Optional `LLM_LOVABLE_READ_TIMEOUT_SECONDS` (default 120).
   Keep `LLM_LOVABLE_PROXY_URL` empty for normal public HTTPS. The private Qwen
   proxy is not inherited by this connection.
4. After backend rollout and isolated connection checks, leave the current
   Assistant unchanged. Marcelo can select Lovable in the LLM tab and save when
   he decides to activate fallback.
   Validate a disposable Assistant with a synthetic greeting, a read-only tool
   round and a controlled primary outage before operational use. Confirm the
   effective model and `additional_kwargs.llm_route`. Keep current real prompts
   and conversation state unchanged.

The bridge accepts at most 1 MiB of JSON and rejects unlisted models/parameters.
Its fixed upstream prevents client-controlled URL forwarding. No prompts,
credentials, provider error bodies or customer data are logged. Upstream errors
keep their status with a generic body; successful response bodies are streamed.
There are no hidden retries. Gateway quota, availability and tool/parameter
support must still be validated for the selected model. Some GPT models do not
accept temperature/top-p: clear those overrides instead of silently discarding
operator choices. HTTP 400/401/402/403 do not trigger runtime fallback.

Local contract test (Node 24; native TypeScript stripping, no dependency install):

```sh
node --test integrations/lovable/llm-bridge/bridge.test.mjs
```

The local test intercepts fetch; live preparation/deployment evidence is recorded
in `docs/LOVABLE_CONNECTION_2026-09-17.md`. It does not imply activation of fallback
in the current Assistant.
Rollback: disable fallback in Assistant settings, restore runtime deployments
if needed and remove only the dedicated function/bridge secret after traffic stops.
