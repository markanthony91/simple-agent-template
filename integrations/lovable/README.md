# Dedicated Lovable bridge (prepared; not deployed)

`llm-bridge/index.ts` is an independent Supabase Edge Function for the Agent Chat
runtime. It forwards the OpenAI Chat Completions payload and SSE unchanged to
Lovable's gateway. It does not use the existing playground, portfolio router,
RAG, boleto, prompt augmentation, or business tools. The runtime executes tools.

After separate rollout approval:

1. Copy `llm-bridge/index.ts` to `supabase/functions/llm-bridge/index.ts` in the
   existing Lovable project. Add only this function to its Supabase config:
   ```toml
   [functions.llm-bridge]
   verify_jwt = false
   ```
   The function authenticates every POST with its own bearer token. Disabling
   Supabase JWT validation here does not make it anonymous. Do not change other
   functions or their authentication.
2. In the Edge Function secrets manager, set `LLM_BRIDGE_TOKEN` to a newly
   generated random server secret (at least 32 random bytes), and set
   `LLM_BRIDGE_MODELS` to a comma-separated allowlist of the desired currently
   available Gemini/GPT model IDs. Use the existing `LOVABLE_API_KEY` in that
   environment; do not export it to Railway or the browser. Deploy the function.
3. In Railway backend variables, set:
   - `LLM_LOVABLE_BASE_URL=https://<project>.supabase.co/functions/v1/llm-bridge/v1`
   - `LLM_LOVABLE_MODEL=<one allowed model ID>`
   - `LLM_LOVABLE_API_KEY=<the bridge token, not the Lovable key>`
   - Optional `LLM_LOVABLE_READ_TIMEOUT_SECONDS` (default 120).
   Keep `LLM_LOVABLE_PROXY_URL` empty for normal public HTTPS. The private Qwen
   proxy is not inherited by this connection.
4. After backend/frontend rollout, select Lovable in the LLM tab and save.
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

The test intercepts fetch; it does not validate Deno deployment, current Lovable
credits or live model output. No live bridge has been deployed by these changes.
Rollback: disable fallback in Assistant settings, restore runtime deployments
if needed and remove only the dedicated function/bridge secret after traffic stops.
