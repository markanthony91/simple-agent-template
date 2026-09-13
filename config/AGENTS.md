# Agent Operational Rules

## Knowledge lookup

When a request depends on institutional knowledge:

1. Use `okf_search` to locate the most relevant content.
2. Use `okf_read_section` when a specific section is enough.
3. Use `okf_read` only when the broader document is necessary.
4. Use `okf_list` to inspect the knowledge tree when the correct file is unknown.
5. Answer only from the retrieved OKF content for institutional rules and policies.

## Tool discipline

- Do not repeat identical tool calls unless new context justifies it.
- Prefer the smallest useful read.
- Do not read unrelated files speculatively.
- If a tool reports that content does not exist, do not fabricate it.

## Current test knowledge

The repository includes a small OKF test policy. Use it when questions concern payment installments.
