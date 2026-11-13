# The existing HTTP API (appendix to HANDOFF.md)

Generated from the route decorators in `web_routes/*.py` on 2026-10-14
(method, path, the handler's first docstring line). This is the **backend** a
front-end calls today. It was shaped by the old front-ends, so treat it as a
starting inventory, not a contract: keep what serves the new design, reshape or
replace the rest. Whatever you add, follow the house rule that a route is
**parse → call the UI-agnostic core (`workflow.steps` / `WorkflowEngine` /
`rendering.preview_surface`) → serialize**, with no workflow logic in the route.

Rows marked **(walled)** serve the old front-ends' pages; don't open their
implementations (see WALL.md). Everything under `/Bookshelf` is kept and in scope.

Every `/api/` path is gated by `ALLOWED_USERS` (`?user=`) only when that env var
is set; it is unset here (open mode). There is no real authentication.


## `web_routes/background_server.py`

| method | path | what it does |
|---|---|---|
| GET | `/api/document-tree` | Return the document structure tree as JSON. |
| POST | `/api/resolve` | Resolve a chemical identifier to all known identifiers. |
| GET | `/api/admin/sessions/export` | Stream the sessions/ directory as a .tar.gz download. |
| GET | `/api/admin/sessions/summary` | Return a quick summary of what's in the sessions/ directory. |
| GET | `/manual` | The command-line manual (docs/headless-report-generation.html). |
| GET | `/` **(walled)** |  |
| GET | `/workflow` **(walled)** |  |
| GET | `/workflow/report` **(walled)** |  |
| GET | `/workflow/configure` **(walled)** |  |
| GET | `/workflow/knowledge-graph` **(walled)** |  |
| GET | `/workflow/corpus` **(walled)** |  |
| GET | `/workflow/prompts` **(walled)** |  |

## `web_routes/bookshelf_routes.py`

| method | path | what it does |
|---|---|---|
| GET | `/Bookshelf/{dtxsid}` | Render one session's report as a Bookshelf reader-view facsimile page, with |
| GET | `/Bookshelf/{dtxsid}/report.docx` | Download the DOCX preview — the actual Word deliverable, rendered on demand |
| GET | `/Bookshelf/{dtxsid}/report.pdf` | Download the PDF preview — the DOCX deliverable converted to PDF on demand |
| GET | `/Bookshelf` | The shelf: the generated reports on disk, each linked to its facsimile. |

## `web_routes/chat_routes.py`

| method | path | what it does |
|---|---|---|
| GET | `/api/chat/{dtxsid}/threads` |  |
| POST | `/api/chat/{dtxsid}/threads` |  |
| GET | `/api/chat/{dtxsid}/threads/{thread_id}` |  |
| DELETE | `/api/chat/{dtxsid}/threads/{thread_id}` |  |
| POST | `/api/chat/{dtxsid}/threads/{thread_id}/messages` |  |

## `web_routes/compare_routes.py`  (walled: the Compare page)

| method | path | what it does |
|---|---|---|
| GET | `/Compare` |  |
| GET | `/Compare/{dtxsid}` |  |
| GET | `/Compare/{dtxsid}/diff` |  |
| GET | `/Compare/{dtxsid}/{side}.txt` |  |

## `web_routes/corpus_routes.py`

| method | path | what it does |
|---|---|---|
| GET | `/api/corpus/{dtxsid}/organs` | The organ inventory (term, frequencies, current mapping) + curated flag. |
| GET | `/api/corpus/{dtxsid}/history` | The live append-only tweak-log (oldest → newest). |
| POST | `/api/corpus/{dtxsid}/organs/map` | Append a map/drop tweak. 422 on invalid, nothing written. No materialize. |
| POST | `/api/corpus/{dtxsid}/materialize` | Build corpus.duckdb by projecting the tweak-log onto the frozen original. |
| POST | `/api/corpus/{dtxsid}/reset` | Revert to the frozen original (remove log, corpus, fingerprint). |

## `web_routes/export_routes.py`

| method | path | what it does |
|---|---|---|
| POST | `/api/export-overleaf-bundle` | Export the full report as an Overleaf-ready zip bundle. |
| POST | `/api/compile-pdf` | Compile the current report to a PDF locally, for the in-app live preview. |
| POST | `/api/sync-document/{dtxsid}` | Materialize/refresh the dev document directory documents/<dtxsid>/ from the |
| GET | `/api/repo-binding/{dtxsid}` | Return the report's repo binding {git_remote?, baseline_commit?} ({} if unset). |
| POST | `/api/repo-binding/{dtxsid}` | Set the report's repo binding.  Body: {git_remote} — the GitHub repo the app |
| GET | `/api/repo-status/{dtxsid}` | Report the clone's git state so the UI can *derive* which controls to offer |
| POST | `/api/commit-local/{dtxsid}` | "Commit Local" (ADR-0005 Am.3 §B/§C): render the report from the **posted |
| POST | `/api/push-to-github/{dtxsid}` | "Push to GitHub" (ADR-0005 Am.3 §C): push the working clone's local commits |
| POST | `/api/pull-from-github/{dtxsid}` | "Pull from GitHub" (ADR-0005 Am.3 §A): pull the bound remote into the working |
| POST | `/api/provision-report/{dtxsid}` | Provision the report's GitHub repo, app-driven — **init only** (ADR-0005 |
| GET | `/api/report-for-project/{project_id}` | Resolve an Overleaf project id back to the report (dtxsid) bound to it. |
| POST | `/api/preview-latex-html` | Render a slice of the report to HTML for the in-app preview iframes. |
| GET | `/api/export-bm2/{dtxsid}` | Download the metadata-enriched .bm2 file for a session. |
| GET | `/api/document-config/{dtxsid}` | Return the session's document-structure YAML for the config editor. |
| POST | `/api/document-config/{dtxsid}` | Validate + persist the session's document-structure YAML. |
| GET | `/api/views/{dtxsid}` | List a session's report views (always includes the implicit 'default'). |
| GET | `/api/views/{dtxsid}/{name}` | Return one view's stored mapping (document / filters / charts / methods). |
| POST | `/api/views/{dtxsid}/{name}` | Validate + persist a view.  A malformed structure returns 422 and |
| DELETE | `/api/views/{dtxsid}/{name}` | Delete a named view ('default' cannot be deleted). |
| GET | `/api/document-config-default` | Return the default (template) document-structure YAML for the editor. |
| POST | `/api/document-config-default` | Validate + persist + LIVE-APPLY an edit to the DEFAULT (template) structure. |
| GET | `/api/layout-style/{dtxsid}` | Return the session's layout-styles config for the styles editor, as BOTH the |
| POST | `/api/layout-style/{dtxsid}` | Validate + persist the session's layout-styles config. |
| GET | `/api/layout-style-default` | Return the default (template) layout-styles YAML for the editor. |
| POST | `/api/layout-style-default` | Validate + persist an edit to the DEFAULT (template) ``styles:`` block. |
| GET | `/api/report-filters-default` | Return the default (template) filter/chart blocks as YAML for the editor. |
| POST | `/api/report-filters-default` | Validate + persist an edit to the DEFAULT (template) filter/chart blocks. |

## `web_routes/genomics_routes.py`

| method | path | what it does |
|---|---|---|
| POST | `/api/genomics-clusters` | Cluster GO categories by gene-set overlap (Jaccard distance). |
| POST | `/api/genomics-cluster-enrichment` | Run Enrichr enrichment analysis for each gene-overlap cluster. |
| POST | `/api/genomics-chart-images` | Render the UMAP scatter and cluster scatter charts as PNG images. |

## `web_routes/integrated_routes.py`

| method | path | what it does |
|---|---|---|
| GET | `/api/integrated/{dtxsid}` | Stream the full integrated BMDProject JSON from disk. |
| GET | `/api/integrated-summary/{dtxsid}` | Return a lightweight summary of the integrated BMDProject. |
| GET | `/api/integrated-tree/{dtxsid}` | Return a slim, browser-safe structural tree of the integrated BMDProject. |
| POST | `/api/process-integrated/{dtxsid}` | HTTP transport for the processing pipeline. Parses the request body and |
| POST | `/api/generate-animal-report/{dtxsid}` | Generate a per-animal traceability report for a session's file pool. |

## `web_routes/knowledge_graph_routes.py`

| method | path | what it does |
|---|---|---|
| GET | `/api/crawl-config/{dtxsid}` | Load the session's crawl config (or the frozen original if unedited). |
| POST | `/api/crawl-config/{dtxsid}` | Validate and persist a tweaked crawl config. 422 on invalid, nothing written. |
| POST | `/api/crawl-config/{dtxsid}/reset` | Revert to the frozen original by removing the session config (archived first). |

## `web_routes/llm_routes.py`

| method | path | what it does |
|---|---|---|
| GET | `/api/models` | Return the proxy's chat-capable models grouped by provider category. |
| POST | `/api/generate` | Run the full background generation pipeline. |
| POST | `/api/generate-methods` | Generate a structured Materials and Methods section for the 5dToxReport. |
| GET | `/api/methods-context/{dtxsid}` | Return the extracted MethodsContext for a DTXSID without running the LLM. |
| POST | `/api/generate-summary` | Generate the Summary section: the facts narrative.report_summary picks from |
| GET | `/api/session/{dtxsid}/citation-warnings` | Every citation the verification layers could not resolve for a session, in |
| POST | `/api/generate-genomics-narrative` | HTTP wrapper over `generate_genomics_narrative_async`.  Preserves |
| POST | `/api/session/{dtxsid}/regenerate-genomics-narrative` | Force-regenerate the LLM genomics narrative for ONE organ. |

## `web_routes/pool_routes.py`

| method | path | what it does |
|---|---|---|
| GET | `/api/workflow/{dtxsid}/state` | Return the server-derived pool workflow state. |
| GET | `/api/workflow/{dtxsid}/section-readiness` | Return server-DERIVED per-section readiness (Phase 1). |
| GET | `/api/workflow/{dtxsid}/sections` | Return the tree-DERIVED section catalog merged with live readiness. |
| GET | `/api/workflow/{dtxsid}/publish-readiness` | Return server-DERIVED publish readiness (Phase 3a currency BLOCK). |
| POST | `/api/pool/validate/{dtxsid}` | Run full cross-validation on a session's file pool. |
| POST | `/api/pool/resolve` | Record a user's precedence decision for a specific validation conflict. |
| POST | `/api/pool/confirm-metadata/{dtxsid}` | Confirm file metadata and write headers into txt/csv file copies. |
| POST | `/api/pool/integrate/{dtxsid}` | Merge all pool files into a unified BMDProject JSON. |
| POST | `/api/pool/materialize-sections/{dtxsid}` | Materialize the apical result sections from the Process cache to disk as |

## `web_routes/preview_routes.py`

| method | path | what it does |
|---|---|---|
| POST | `/api/preview/{dtxsid}/materialize` | Render + persist the preview artifact set for a session. |
| GET | `/api/preview/{dtxsid}/view` | Serve a materialized preview file inline for the iframe. |
| GET | `/api/preview/{dtxsid}/download` | Download a materialized deliverable (default docx) as an attachment. |

## `web_routes/prompt_routes.py`

| method | path | what it does |
|---|---|---|
| GET | `/api/prompts/{section}` |  |
| GET | `/api/prompts/{section}/versions/{version}` |  |
| POST | `/api/prompts/{section}` |  |
| POST | `/api/prompts/{section}/current` |  |
| POST | `/api/prompts/{section}/render` |  |
| POST | `/api/prompts/{section}/run` |  |
| GET | `/api/prompts/{section}/runs/{dtxsid}` |  |
| POST | `/api/prompts/{section}/runs/{dtxsid}/{run_id}/use` | Save a run's text as the section — a new, unapproved version of it. |
| GET | `/api/prompts/{section}/studies` |  |
| GET | `/api/prompts/{section}/published/{dtxsid}` |  |
| GET | `/api/prompts/{section}/models/{dtxsid}` | The gateway's prose models grouped by provider, each marked whether the |
| POST | `/api/prompts/{section}/compare` | Run a model comparison, streaming progress. Everything is checked |
| GET | `/api/prompts/{section}/comparisons/{dtxsid}` |  |
| GET | `/api/prompts/{section}/comparisons/{dtxsid}/{comparison_id}` |  |
| GET | `/api/prompts/{section}/threads` |  |
| POST | `/api/prompts/{section}/threads` |  |
| GET | `/api/prompts/{section}/threads/{thread_id}` |  |
| POST | `/api/prompts/{section}/threads/{thread_id}/messages` |  |

## `web_routes/query_routes.py`

| method | path | what it does |
|---|---|---|
| POST | `/api/query/{dtxsid}` | Run one read-only SELECT/WITH against the session DB. |
| GET | `/api/query/{dtxsid}/schema` | The table/column catalog for the session DB (schema sidebar). |
| GET | `/api/query/{dtxsid}/parquet` | List the Parquet tables available for a session (those actually on disk). |
| GET | `/api/query/{dtxsid}/parquet/{table}` | Stream one table's Parquet file. ``table`` must be a known schema table. |

## `web_routes/session_routes.py`

| method | path | what it does |
|---|---|---|
| GET | `/api/session/{dtxsid}/bmd-summary` | Auto-derive an Apical Endpoint BMD Summary from all approved .bm2 sections. |
| GET | `/api/session/{dtxsid}` | Load a previously-saved session for a given DTXSID. |
| POST | `/api/session/{dtxsid}/genomics-narrative-override` | Save (or clear) a user's edit to a genomics LLM narrative block. |
| POST | `/api/session/approve` | Approve a report section and persist it to disk. |
| POST | `/api/session/{dtxsid}/models` | Persist the user's per-concern model selections into meta.json. |
| POST | `/api/session/save-section` | Persist a report section to disk WITHOUT changing its approval state. |
| POST | `/api/session/unapprove` | REVISE (reopen) a report section for editing, preserving its content. |
| POST | `/api/session/discard-section` | Permanently delete a section's JSON file (and abandon its history). |
| GET | `/api/session/{dtxsid}/history/{section_key}` | Return version history for an approved section. |
| POST | `/api/session/{dtxsid}/restore` | Restore a past version of a section by re-saving it as the new current. |
| GET | `/api/experiment-metadata/{dtxsid}` | Return experiment metadata for all experiments in the integrated data. |
| POST | `/api/experiment-metadata/{dtxsid}` | Save user-edited experiment metadata back to integrated.json. |
| DELETE | `/api/pool/{dtxsid}/files/{filename}` | Remove ONE file (plus its sidecar/original companions) from the pool. |
| POST | `/api/pool/reset/{dtxsid}` | Completely reset the data pool for a given DTXSID. |
| POST | `/api/session/reset/{dtxsid}` | Completely delete the entire session for a given DTXSID. |

## `web_routes/structure_routes.py`

| method | path | what it does |
|---|---|---|
| GET | `/api/document-structure/catalog` |  |
| POST | `/api/document-structure/parse` | YAML text → the node-entry list the editor edits (no validation beyond |
| POST | `/api/document-structure/dump` | Node-entry list → YAML text, using the same dumper as the default config |
| POST | `/api/document-structure/validate` | Dry-run the full save-time validation on a node-entry list. |

## `web_routes/upload_routes.py`

| method | path | what it does |
|---|---|---|
| POST | `/api/upload-bm2` | Accept one or more .bm2 file uploads. |
| POST | `/api/process-bm2` | Process an uploaded .bm2 file through the NTP statistical pipeline. |
| POST | `/api/upload-csv` | Accept one or more loose CSV (or TXT) file uploads. |
| POST | `/api/upload-zip` | Accept a single .zip archive upload, extract its contents, and register |
| POST | `/api/process-genomics` | Process an uploaded gene-level BMD CSV to produce the data for the |
| GET | `/api/preview/{file_id}` | Return preview-ready content for an uploaded file. |

## `web_routes/wizard_routes.py`

| method | path | what it does |
|---|---|---|
| GET | `/api/wizard/{dtxsid}/files` | List uploaded study files in the session's files/ directory. |
| GET | `/api/wizard/{dtxsid}/processed` | Whether this session has already been processed (its compute caches exist). |
| GET | `/api/wizard/{dtxsid}/identity` | The compound's cross-identifiers from identity.json (name, CASRN, DTXSID, |
| GET | `/api/document/{dtxsid}/front-matter` | Read the session's human-set front-matter (authors, contributors, publication |
| POST | `/api/document/{dtxsid}/front-matter` | Persist the session's front-matter. Validates the top-level shape (authors / |
| GET | `/api/wizard/{dtxsid}/fingerprints` | Detected per-file classification for the confirm-metadata screen. |
