# Dataset catalog and full-content search

Backend 0.2.6 / frontend 0.1.9. No document content, path, policy, financial
tool or conversation authorization was changed.

## Contract

The operator graph accepts `catalog` with optional `query` and `bundle_id`.
It returns path, title, declared type/status, metadata-warning flag and a bounded
matching excerpt/line. The browser pins bundle_id for subsequent searches and
full-document reads. Collection tools retain their existing limits.

Search is a literal, case/accent-insensitive substring across the full Markdown
text (including YAML), title and path. It is not semantic search or embeddings.
Limits: 200 query characters, 2,000 Markdown files, 40 MB encoded bundle and
200,000 characters/document. Symlinks and traversal fail closed.
No cache, Redis, index database or new dependency was introduced.

The UI shows declared types, not inferred classifications. A frontmatter
`status: draft` is shown as declared even inside a published snapshot; publication
does not establish semantic approval or fiscal/legal validity.

## Validation

- 133 backend tests, 86% total coverage, 96% catalog coverage.
- Frontend: typecheck, webpack production build, lint (existing warnings).
- 21 unit/browser cases: content-only and accent search, type filter combination,
  path identity, full preview, no results, delayed-response races, read/search
  errors, desktop/tablet/mobile layout, prompt persistence and existing controls.
- Backend deployment `d3a3f10a-84b8-465a-a006-2bf3299927c7` SUCCESS,
  source `1168772`, installed version 0.2.6 confirmed by SSH.
- 469 real documents; catalog 1,706 ms and CPF search 1,274 ms (one sample each,
  service computation only, not browser-visible latency).
- CPF: 8 matches, all absent from the matched filenames/titles.
- Local production UI with real Railway backend: 3,827 ms desktop and 3,330 ms
  mobile from typing to visible results, including 300 ms debounce and network.
  No JavaScript errors, horizontal overflow or document writes.
- Original prompt hash and all 25 conversation states survived this deployment.
- All 469 published Markdown files matched the pre-deploy archive byte-for-byte.
- Published frontend 0.1.9, source `f54cbbc`, deployment
  `7ffa2304-1181-4669-83b2-ff6101b0a968` SUCCESS; package version confirmed by SSH.
- Real published UI opened without connection parameters or user configuration.
  CPF search: 3,849 ms desktop and 3,840 ms mobile to visible results; preview
  opened successfully. No JavaScript errors or horizontal overflow. Requests
  were only catalog/read/list_versions/list_drafts (plus temporary admin threads).

## Backup and rollback

Private backup: `/data/backups/pre-dataset-catalog-20260915T203710Z`.
Includes assistant records, 25 API conversation exports and volume archive.
SHA-256: `293fd8ce82396d93fe1d8c5bd2186d484cd100ae74565ce858396d67cfef448d`.

Retain /data and the regular managed assistant. Roll back frontend to 0.1.8
before backend to 0.2.5; the old backend lacks catalog. The new backend remains
compatible with the old filename-list UI. Never roll back prompt persistence to
frontend 0.1.7, which used the recreated system assistant.
