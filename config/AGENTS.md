# Agent Operational Rules

## Knowledge lookup

When a request depends on institutional knowledge, use OKF progressive disclosure:

1. Use `okf_index` first to inspect the relevant `index.md` and identify the best concept or subdirectory.
2. If the root index points to a subdirectory, use `okf_index` for that directory when an index exists there.
3. Use `okf_read_section` when a specific section is enough.
4. Use `okf_read` when the broader concept is necessary.
5. Use `okf_search` only as a fallback when the indexes and known concept structure do not locate the answer.
6. Use `okf_list` only when the index structure is missing, incomplete, or inconsistent.
7. Answer institutional rules and policies only from retrieved OKF content.

## OKF v0.2 behavior

- Treat `index.md` as the discovery layer for progressive disclosure.
- Treat non-reserved Markdown files as concepts.
- Do not assume optional trust or provenance metadata is present.
- Tolerate unknown concept `type` values and additional frontmatter keys.
- Do not reject knowledge merely because an optional index, link, or metadata family is absent.
- Never fabricate a rule that was not retrieved from the bundle.

## Tool discipline

- Do not repeat identical tool calls unless new context justifies it.
- Prefer the smallest useful read.
- Do not read unrelated concepts speculatively.
- If an index identifies a relevant concept, read that concept before performing corpus-wide search.
- If a tool reports that content does not exist, do not fabricate it.

## Current test knowledge

The OKF v0.2 test bundle contains a payment policy under `policies/payment.md`. Use the index-first flow for questions about payment installments.
