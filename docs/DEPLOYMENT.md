# Controlled rollout / rollback

1. Review backend/frontend branches and test evidence. Do not treat a commit as deployed.
2. Back up the existing /data volume and export current LangGraph conversations
   before changing the deployment. The old .langgraph_api directory may be ephemeral.
3. Preserve the Railway Volume at /data and exactly one replica. Configure canonical
   LLM variables securely; do not copy keys into the frontend.
4. Build the Dockerfile. ENTRYPOINT prepares the persistent checkpoint directory
   even when Railway overrides CMD. An existing different checkpoint directory
   causes startup to stop rather than overwrite it; migrate a verified backup explicitly.
5. Publish backend and companion frontend together in a controlled maintenance window.
   Old clients cannot publish without the new approved flag. New clients send it
   only after operator confirmation. This is intent capture, not admin authentication.
6. Start a NEW synthetic conversation. Verify identity → debt → policy → offer →
   confirmation. Verify another thread cannot reuse identity or offer.
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
