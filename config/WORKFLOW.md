# Default Negotiation Workflow

This is an agentic workflow guide for the standard collection/negotiation process. It describes stages, gates, and ordering constraints, but preserves agent autonomy for conversational detours that do not violate mandatory gates.

## Stages

### Stage 1: Natural Conversation & Intent Discovery
- **Gate**: User engagement and conversational context established.
- **Autonomy**: Full agent discretion. Respond naturally to greetings, small talk, and initial context.
- **Exit condition**: User indicates a negotiation, collection, or policy inquiry intent, or sufficient context is available to proceed.
- **Next stage**: Advance to Identity Verification.

### Stage 2: Identity Verification (Mandatory Gate)
- **Gate**: Customer identity must be verified before proceeding to financial terms or policy disclosure.
- **Autonomy**: Agent may ask security questions, request validation, or perform lookups using available tools.
- **Tools available**: `okf_search`, `okf_index` for verification policies; `get_customer` if integration is available.
- **Exit condition**: Identity is confirmed (either through provided data or tool verification).
- **Constraint**: Do NOT disclose sensitive financial, policy, or operational information before this gate is satisfied.
- **Next stage**: Advance to Customer Lookup / Debt Context.

### Stage 3: Customer Lookup & Debt Context
- **Gate**: Retrieve and establish the customer's account context, outstanding debt, collection status, or negotiation history.
- **Autonomy**: Agent calls `get_customer` or performs contextual lookups to populate customer state.
- **Tools available**: `get_customer`, `okf_search`, `okf_index`.
- **Exit condition**: Sufficient customer context is available.
- **Constraint**: If customer lookup fails or data is incomplete, explain the limitation transparently and ask for missing information.
- **Next stage**: Advance to Policy Retrieval.

### Stage 4: Retrieve Applicable OKF Policy (Mandatory Gate)
- **Gate**: Before generating any offer or discussing concrete terms, retrieve the applicable institutional policy for the customer's institution, product, and negotiation type.
- **Autonomy**: Agent performs progressive OKF index navigation. Tool selection and path discovery are autonomous.
- **Navigation constraints**:
  - Follow `OKF_CHILD_DIRECTORIES` and `OKF_CONCEPT_PATHS` returned by `okf_index`.
  - Do not invent child directories.
  - Use scoped `okf_search` if index navigation is exhausted.
  - Use `okf_list` only as a last resort.
- **Evidence states**:
  - `POLICY_FOUND_DEFINED`: policy exists and contains concrete terms.
  - `POLICY_FOUND_UNDEFINED`: policy exists but contains unresolved placeholders.
  - `POLICY_NOT_FOUND`: no policy found despite a genuine lookup.
  - `NAVIGATION_FAILED`: lookup failed because navigation could not reach valid evidence.

### Stage 5: Classify Evidence & Conditional Offer Generation
- If `POLICY_FOUND_DEFINED`, evaluate the requested terms and call `generate_offer` only when policy and customer state allow it.
- If `POLICY_FOUND_UNDEFINED`, do not generate or suggest concrete commercial terms.
- If `POLICY_NOT_FOUND` or `NAVIGATION_FAILED`, do not invent a commercial condition; explain the limitation and offer a safe next step.

### Stage 6: Explicit User Confirmation (Mandatory Gate)
- Before calling `create_agreement`, require explicit user acceptance of the proposed terms.
- Do not call `create_agreement` without explicit confirmation.

### Stage 7: Agreement Creation & Summary
- After confirmation, call `create_agreement` with the confirmed terms.
- Summarize the agreement naturally and clearly without exposing internal tool output.

## Conversational Detours

The user may ask clarifying or unrelated questions at any stage. Answer naturally and then resume the current stage without bypassing mandatory gates.

## Implementation Notes

This workflow is guidance, not a hard router. The agent retains autonomy over wording, tool choice, and conversational detours while respecting mandatory gates and evidence constraints.
