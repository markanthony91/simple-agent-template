# Validation — 2026-09-14

This is the pre-publication local baseline. For the later authorized deployment,
real Qwen smoke and recovery checks, see [release evidence](RELEASE_2026-09-14.md).

Scope: the new simple-agent-template / agent-chat-ui pair. No changes to the
existing FastAPI console, WhatsApp, Railway configuration or the live gateway.

## Verified locally

- 79 pytest tests pass; 1 legacy live integration test skipped.
- Ruff passes. Coverage: 82% overall; collection tools 96%, session state 93%,
  RAW compiler 84%, OKF store 88%, validator 80%, active admin graph 100%.
  Some legacy graph entrypoints remain uncovered; the global 80% target is met.
- Frontend TypeScript and optimized Next build pass. ESLint has no errors;
  existing React hook/fast-refresh warnings remain. Existing build warnings:
  Tailwind config module format and legacy LangGraph auth proxy.
- Docker build passes. Container /info returns 200 with langgraph-api 0.14.0 /
  langgraph 1.2.6; /app/.langgraph_api resolves to /data/langgraph.
- Real local API tool loop: complete OpenAI-compatible streamed tool calls →
  injected ToolRuntime → authorized tool → role=tool → final response.
- 9 browser tests pass, including simulator save and published document preview
  through the same local backend. Browser journeys: verified customer → debt → policy → balanced proposal →
  explicit confirmation; other conversation denied financial data; index/concept
  lookup followed by out-of-scope response.
- Local checkpoint files were written under the persistent target, and agreement
  conversation history was recoverable after a graceful API restart.
- Text arrives before generation finishes. An interrupted provider response now
  fails with provider_response_incomplete rather than being labeled complete.
- Cancel now has backend cancellation plus observed provider disconnection.
  Previous SDK configuration only detached the UI: enabling native session run
  tracking (reconnectOnMount) fixed this without a custom streaming parser.
- Layouts: Chromium, 1440x900, 1024x768 and 390x844. No horizontal overflow in
  tested layouts. Screenshots retained locally by Playwright, not committed.

## Timings (one synthetic long-response scenario, not Qwen performance)

Optimized frontend, loopback HTTP provider intentionally emits a chunk every
50 ms. Latest measured first visible text: 1045 ms; end marker: 3975 ms.
Earlier samples: 1560 / 4031 ms and 1002 / 3855 ms. These are independent samples, NOT an A/B
improvement claim. They include browser scheduling and API overhead.
Model/context/tool time breakdown is not fully instrumented here. Tool execution
durations remain in backend operational logs; this suite does not establish
gateway RPM, production concurrency, real-model fidelity or SGLang TTFT.

## Reproduce

1. Backend: uv sync --dev --frozen; run tests/support/provider.py in one terminal.
   It listens ONLY on 127.0.0.1:3042. It is a protocol fixture, not agent logic.
2. Create a temporary directory with mktemp -d /tmp/runtime-e2e-XXXXXX.
3. Set DATA_ROOT to that directory; set OKF_DATA_ROOT, SESSION_ROOT, SIMULATOR_ROOT
   and TOOL_REGISTRY_ROOT to separate subdirectories. Export synthetic
   LLM_BASE_URL=http://127.0.0.1:3042/v1, LLM_MODEL=synthetic-protocol,
   LLM_API_KEY=synthetic-test-only, LLM_PROXY_URL empty, LANGSMITH_TRACING=false.
4. Run tests/support/seed.py, which refuses non-temporary targets.
5. From the temporary directory, use the backend virtualenv Python to run
   -m simple_agent.startup langgraph dev --config <repo>/langgraph.json
   --host 127.0.0.1 --port 3041 --no-browser --no-reload.
6. Frontend: pnpm install --frozen-lockfile; pnpm build;
   pnpm start --hostname 127.0.0.1 --port 3040; pnpm test:e2e.
   Install Playwright Chromium or set PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH.
   On this host Nix Chromium supplies missing system libraries without host changes.
7. Stop only these local processes. Temporary data contains synthetic fixtures.

## Not validated / release blockers

- No Preview/Railway publication of these branches. No live LLM tests.
- No semantic guarantee from a simulated provider: it intentionally supplies
  predictable text/tool decisions. Run the same journeys against Qwen after approval.
- No production authentication, external financial execution or output Evidence Gate.
- Complete text is visible before semantic validation; backend action checks do
  not imply that already-streamed text is safe or faithful.
- Existing assistant context overrides require explicit review; new checked-in
  instructions do not automatically replace saved System Prompt/AGENTS/workflow.
- Real commercial negotiation metadata must be reviewed before enabling offers.
- Ingestion supports conservative append/create/noop. Semantic conflict discovery
  still depends on the LLM and human review; it is not a deterministic truth checker.
- File locks / local SQLite / dev-server checkpoints target ONE replica only.
