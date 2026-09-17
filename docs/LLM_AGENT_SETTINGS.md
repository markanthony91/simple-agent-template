# LLM and agent profile settings - 2026-09-17

Version 0.3.0 is based on the instruction-versioning branch currently used by
the deployment, not the older main branch. Companion frontend: agent-chat-ui
`feat/llm-agent-settings`, also 0.3.0. No new dependencies or migrations.

Validation: 151 backend tests passed, 87% overall coverage; the new settings
module has 100% coverage. An intercepted OpenAI-compatible HTTP stream proves
temperature=0, top_p=0.8 and a 1024-token cap reach both calls of a real graph
tool loop. A subsequent run without settings has neither the overrides nor the
previous agent identity. Invalid settings fail before any provider request.
These are protocol tests, not new Qwen behavior benchmarks.

Release status: local implementation; not yet published. Follow DEPLOYMENT.md
for backup, rollout and preservation of current Assistant context/conversations.
Publish the backend before the frontend. Check the UI using a disposable
Assistant, save/reload both tabs and test one synthetic greeting with the named
profile. Keep the operator's current Assistant and conversations unchanged.

Rollback: restore previous frontend/backend deployments, retaining /data and
Assistant versions. Previous backend versions ignore the two new context fields;
removing them is unnecessary. No existing prompt, workflow or policy is rewritten.
