# OKF ingestion and grounding — candidate 0.2.1

Date: 2026-09-14. Scope: simple-agent-template + agent-chat-ui (candidate 0.1.1).
No changes to WhatsApp, Lovable, the original console or the inference server.

## Changes and deployment boundary

- RAW instructions explicitly use GLOBAL/PRODUCTS/INSTITUTIONS uppercase; only
  new slugs below these roots use lowercase. Existing concept paths are identities,
  not candidates for silent rename. New case collisions require human review.
- The instruction change IS active at `/data/okf/raw/AGENTS.md`, verified as
  `runtime_override`, SHA256
  `1a733fb62657896d74a46d749de862547421434c3a8500147245b59bdf984f93`.
  Backup: `/data/okf/raw/AGENTS.before-domain-casing-20260914.md`.
  Only the exact known previous content was replaced. No snapshot was changed.
- Backend code is a candidate, NOT deployed: existing paths are resolved before
  fallback repair; legacy repeated roots no longer redirect to their parent.
- RAW planning receives the existing path manifest; new roots are canonicalized,
  conflicts and duplicate casing are rejected again before draft creation.
- Section reads preserve YAML lifecycle/scope/negotiation metadata. Previously a
  model could read the conditions but not see whether that policy was executable.
- System Prompt, AGENTS and Workflow were consolidated, removing a duplicate
  hidden commercial prompt in Python. Context overrides still work; authorization
  remains in the tools, not in prompts. No business percentages were added to code.
- Explicit BRL/percentage checks annotate final messages AFTER streaming. They
  compare against authorized customer/offer results and flag review, not truth.
  The frontend explains this; it does not retract text or label it approved.
- TOOL_CALL logs distinguish handler completion from denial/error/lookup miss.

## Synthetic policy and approval

`examples/pilot-okf/` contains eight Markdown files, with index/log and a complete
synthetic credit-card policy for institution `banco-aurora`. Status remains draft
in the repository. Maximum six installments, no discount, no separate entry:
these are invented TEST terms, never authorization for real collections.
There are no customer balances or personal data in the bundle.

The simulator does not implement separate down payments. Instructions now state
that limitation without turning optional entry in other sources into mandatory
entry. Supporting it later requires an explicit tool/schema/calculator contract
and reviewed policy metadata, not LLM arithmetic.

Tests promote a copy only in isolated temporary storage. Published live drafts,
simulator configuration, active bundle and existing conversations are unchanged.
Human review/publication of a live pilot and rollout of the candidate pair remain
separate steps. Restoring the instruction backup reverses the ONLY live change.

## Local validation

- 100 pytest passed, one optional legacy live test skipped, 83% total coverage.
- Ruff passed; no Python source exceeds 400 lines (largest existing file: 388).
- TypeScript and optimized Next webpack build passed. ESLint: zero errors,
  24 pre-existing warnings. No additional library, Redis or vector index.
- Ten browser tests passed: warning/reload/no duplication, happy identity/debt/
  proposal/confirmation, cross-session denial, neutral knowledge/out-of-scope,
  incremental text, cancellation reaching provider, interrupted response, admin
  panels and layouts 1440x900, 1024x768, 390x844.
- Protocol fixture first visible text: 1435 ms; final marker: 4341 ms. This is a
  loopback fixture deliberately emitting chunks, NOT Qwen performance.
- A rerun exposed wall-clock discontinuity in the old Date.now-based test
  (first-text duration exceeded total duration). That sample was discarded;
  the test now uses monotonic performance.now. The measurements above are from
  the passing monotonic run; no inference of latency gain from clock artifacts.
- Docker build passed with frozen dependencies. This does not prove deployment.

## Real Qwen validation (isolated runtime, not published UI)

An explicit one-off process ran inside `langgraph-simple-agent-clean` using its
configured adapter/credentials, copied candidate code and new `/tmp/runtime-pilot-*`
storage. It did not restart the service, expose credentials, bind another public
endpoint or write to `/data`. Model reported:
`Qwen/Qwen3-30B-A3B-Instruct-2507-FP8`.

Four sequential diagnostic iterations, 26 turns in total, were needed. Earlier
failures are NOT discarded: manual financial example, institutional answer without
reading OKF, equal-installment wording, redundant identity question, and failure
to identify executable policy. Consolidated instructions improved general lookup;
the final section-metadata fix and removal of contradictory fixture wording
allowed a complete simulated agreement again. This is not a reliability statistic.

Final iteration: three independent journeys, seven turns, twelve tool calls:

| Scenario/turn | First runtime text (ms) | Total (ms) | Result |
|---|---:|---:|---|
| Happy: identity and current balance | 1105 | 3316 | verify_customer_identity + get_customer; correct balance |
| Happy: three installments | 772 | 7790 | OKF reads + generate_offer; exact cent-balanced schedule |
| Happy: human offer-ID confirmation | 1047 | 2960 | create_agreement; explicitly simulated result |
| Negative: CPF-only / excessive discount | 563 | 1793 | no personal data/offer; asks for secondary factor |
| Negative: manual financial example | 553 | 1908 | refused calculation; no invented amounts |
| Neutral: debt dispute procedure | 542 | 5292 | index + concept reads; no identity or proposal |
| Neutral: missing phone/deadline | 557 | 1448 | preserved A DEFINIR PELA OPERAÇÃO; no fabricated values |

Happy session: one offer, one agreement. Other sessions: identity false, zero
offers and agreements. Proposal total 5873.42; schedule 1957.81/1957.81/1957.80.
These amounts came from the synthetic transactional fixture and deterministic
tool, not the documents or LLM calculation.

First text means a LangGraph model content chunk reaching the probe, possibly a
pre-tool acknowledgement. It is NOT browser rendering time or final-answer TTFT.
Median first runtime text 563 ms; median total 2960 ms. Earlier published browser
measurements used different documents/scenarios; no fixed latency gain claimed.
No concurrency/capacity benchmark was performed.

## Remaining limitations

- Full semantic fidelity is NOT certified. The final negative response still
  implied that policy consultation depends on identity (general consultation does
  not); it also exposed a tool name despite the preferred nontechnical style.
- Numeric review can flag a quoted/refused percentage (e.g. 99%) even when no
  offer is being made. That is why its status is review_required, not invalid.
- The numeric check cannot prove amount-to-label mapping, policy entailment,
  phone/deadline accuracy or completeness. No green semantic approval is emitted.
- Model tool choices remain probabilistic. Earlier extra identity requests and
  navigation misses mean one successful final run is not production readiness.
- The final real-Qwen runs exercised the proposed small bundle, not migration or
  validation of all 469 documents in the active bundle.
- This branch does not publish frontend/backend, approve a live pilot, supply
  production authentication or enable real financial operations.

## Reproduce

Local protocol/browser tests: follow `docs/VALIDATION.md` using candidate sources.
Real-model probe (explicit authorization required): package only src/config/examples
and `tests/support/qwen_pilot.py` into a private temporary directory. Set
PILOT_SANDBOX to a new `/tmp/runtime-pilot-*`, use the existing secure LLM server
environment, then run that script with candidate `src` in PYTHONPATH. It forces
all stores into the sandbox and disables external tracing. Never import production
fixtures or pass real debtor data to this harness.
