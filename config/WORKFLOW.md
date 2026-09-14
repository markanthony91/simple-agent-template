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
- **Tools available**: `okf_search`, `okf_index` for verification policies; `verify_customer_identity` with CPF plus a secondary factor, then `get_customer`.
- **Exit condition**: Only a successful `verify_customer_identity` tool result establishes identity in this conversation. User claims and fixture flags cannot do so.
- **Constraint**: Do NOT disclose sensitive financial, policy, or operational information before this gate is satisfied.
- **Next stage**: Advance to Customer Lookup / Debt Context.

### Stage 3: Customer Lookup & Debt Context
- **Gate**: Retrieve and establish the customer's account context, outstanding debt, collection status, or negotiation history.
- **Autonomy**: Agent calls `get_customer` or performs contextual lookups to populate customer state.
- **Tools available**: `get_customer`, `okf_search`, `okf_index`.
- **Exit condition**: Sufficient customer context is available (account number, debt amount, product, due date, status, etc.).
- **Constraint**: If customer lookup fails or data is incomplete, explain the limitation transparently and ask for missing information.
- **Next stage**: Advance to Policy Retrieval.

### Stage 4: Retrieve Applicable OKF Policy (Mandatory Gate)
- **Gate**: Before generating any offer or discussing concrete terms, retrieve the applicable institutional policy for the customer's institution, product, and negotiation type.
- **Autonomy**: Agent performs progressive OKF index navigation. Tool selection and path discovery are autonomous.
- **Tools available**: `okf_index`, `okf_search`, `okf_read`, `okf_read_section`.
- **Navigation constraints**: 
  - Follow OKF_CHILD_DIRECTORIES and OKF_CONCEPT_PATHS returned by `okf_index`.
  - Do NOT invent child directories.
  - Use scoped `okf_search` if index navigation is exhausted.
  - Use `okf_list` only as a last resort.
- **Exit condition**: Policy search is complete. Classify evidence into one of four states:
  - **POLICY_FOUND_DEFINED**: Policy exists and contains concrete terms.
  - **POLICY_FOUND_UNDEFINED**: Policy exists but contains placeholders (A DEFINIR PELA OPERAÇÃO, etc.).
  - **POLICY_NOT_FOUND**: No policy found despite genuine lookup.
  - **NAVIGATION_FAILED**: OKF lookup failed (structure issues, all paths exhausted).
- **Constraint**: Record and communicate the evidence state to guide subsequent actions.
- **Next stage**: Conditional branching based on evidence state.

### Stage 5: Classify Evidence & Conditional Offer Generation

#### Branch 5a: POLICY_FOUND_DEFINED
- **Autonomy**: Agent has concrete policy. Evaluate user's requested terms against policy using autonomous reasoning.
- **Next action**: If user terms align with policy and customer eligibility is confirmed, proceed to `generate_offer`.
- **If terms misaligned**: Explain policy constraints and ask for revised user terms, or advance to user confirmation with policy-compliant terms.
- **Next stage**: Advance to Stage 6 (Explicit Confirmation).

#### Branch 5b: POLICY_FOUND_UNDEFINED
- **Constraint**: Do NOT generate `generate_offer` or suggest concrete commercial terms.
- **Action**: Acknowledge the policy placeholder and explain that operational definition is required.
- **Next action**: Offer to escalate, continue conversation, or ask if customer wishes to wait for policy clarification.
- **Next stage**: Return to Stage 1 (continue conversation) or exit to escalation.

#### Branch 5c: POLICY_NOT_FOUND or NAVIGATION_FAILED
- **Constraint**: Do NOT invent commercial terms or suggest concrete offers without policy grounding.
- **Action**: Report the evidence state transparently. Explain that policy could not be retrieved for the requested context.
- **Next action**: Offer alternative paths (different product, alternative institution, escalation) or request additional context.
- **Next stage**: Return to Stage 1 (continue conversation with user) or exit to escalation/support.

### Stage 6: Explicit User Confirmation (Mandatory Gate)
- **Gate**: Before calling `create_agreement`, the user must explicitly confirm they accept the proposed terms.
- **Autonomy**: Agent presents the offer clearly and requests confirmation using natural conversational language.
- **Constraint**: Do NOT call `create_agreement` without explicit user agreement.
- **Exit condition**: The user confirms the exact persisted offer using the simulator confirmation button or sends `CONFIRMAR ACORDO <offer_id>` as a new user message. The LLM must never synthesize this message.
- **Next stage**: Advance to Stage 7 (Agreement Creation & Summary).

### Stage 7: Agreement Creation & Post-Negotiation Summary
- **Gate**: User confirmed; proceed to `create_agreement`.
- **Autonomy**: Call `create_agreement` with confirmed terms. Handle success or failure gracefully.
- **Next action**: Summarize the agreement naturally, confirm next steps (payment, collection schedule, contact channels), and close the negotiation.
- **Constraint**: Keep summary brief and human-friendly; do not expose tool outputs.
- **End of workflow**: Negotiation complete.

## Conversational Detours

- **Allowed**: At any stage, the user may ask clarifying questions, request additional information, or discuss unrelated topics. The agent should answer naturally using available tools.
- **Constraint**: Detours must not skip mandatory gates (Identity Verification, Policy Retrieval, User Confirmation).
- **Re-entry**: After a detour, return to the current stage and resume from the last exit condition.

## Tool Availability & Constraints

### Stages 1–3: Pre-Policy Lookup
- `utc_now`, `calculator`, `okf_index`, `okf_search`, `okf_read`, `okf_read_section`, `okf_list`
- `get_customer` (if integrated)
- Not available: `generate_offer`, `create_agreement` (policy not yet retrieved)

### Stage 4: Policy Retrieval
- `utc_now`, `calculator`, `okf_index`, `okf_search`, `okf_read`, `okf_read_section`, `okf_list`
- Full autonomy for tool selection and navigation.

### Stage 5: Conditional Offer Generation (POLICY_FOUND_DEFINED only)
- `generate_offer` becomes available only if POLICY_FOUND_DEFINED.
- `okf_read`, `okf_read_section` remain available if customer has questions.
- Never use `calculator` for financial terms. Use only `generate_offer`.

### Stage 6–7: Confirmation & Agreement
- `create_agreement` available only after explicit user confirmation.
- `okf_search`, `okf_read` still available for answering customer questions.

## Evidence State Reference

| State | Meaning | Action | Offer Generation | Next Stage |
|-------|---------|--------|-------------------|-----------|
| POLICY_FOUND_DEFINED | Policy retrieved with concrete terms | Evaluate terms, present offer if compliant | ✅ Allowed | Stage 6 |
| POLICY_FOUND_UNDEFINED | Policy exists but incomplete (placeholders) | Explain limitation, do not suggest concrete terms | ❌ Forbidden | Escalate or Stage 1 |
| POLICY_NOT_FOUND | No policy found despite lookup | Report state, offer alternatives | ❌ Forbidden | Escalate or Stage 1 |
| NAVIGATION_FAILED | OKF lookup failed (structure, paths) | Report state, attempt escalation | ❌ Forbidden | Escalate or Stage 1 |

## Implementation Notes

- This workflow is embedded in the agent prompt as a guide, not a hard router.
- The agent should use autonomy to navigate stages and gates based on conversational context.
- Mandatory gates (2, 4, 6) are constraints that must be honored; others allow flexibility.
- Registered tools are schema-validated and authorized by the backend. Stage descriptions are procedural guidance, not a claim that tools disappear from the schema.
- Always prioritize natural conversation and user clarity over workflow formalism.

## Simulator contract (v0.2.0)

- `get_customer` returns current transactional data, not installment amounts.
- `generate_offer` requires `policy_path` from a prior successful OKF read in this conversation.
- The policy must belong to the pinned snapshot, be published and current, match institution/product, and declare approved `negotiation` metadata. Prose alone or undefined metadata is not executable authorization.
- Send percentages as decimal strings, for example `"10"`, never calculate totals yourself.
- Present `negotiated_amount` and the complete `installment_schedule` exactly. Rounding can make installments differ by a cent.
- Do not promise success before `create_agreement` returns `created: true`.
- Reuse the same offer ID on retries. Expired offers require a new simulation.
- Fixture edits and new publication affect NEW conversations only. Existing conversations keep their fixture and snapshot.
- Knowledge-only questions do not require identity unless they disclose customer-specific information.

