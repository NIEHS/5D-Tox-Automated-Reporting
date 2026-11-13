# Architecture Map

> Package-by-package map of rlm-bmdx on the **package-layout** branch
> (ADR-0013). Unlike `main`'s flat root, the modules here physically live in
> concern packages and imports are package-qualified
> (`from rendering.render_common import ...`). Generated 2026-08-26 from an
> `rlm-code` index of the branch (262 files, 2,841 symbols, 15,702 edges).
>
> Companion docs: [`CONTEXT.md`](../CONTEXT.md) (*why* the architecture is shaped
> this way) and [`code-walkthrough.md`](code-walkthrough.md) (*how* control flows
> across these packages at runtime).

**14 Python packages** + a TypeScript/React `wizard-ui/` frontend. LOC is line
count; the one-liner is the module's own docstring.

## web_routes

FastAPI app + HTTP route modules — the server surface the web UI calls. Entry point: `python -m web_routes.background_server`.

| module | loc | purpose |
|--------|----:|---------|
| `background_server.py` | 544 | FastAPI application shell for 5dToxReport. |
| `export_routes.py` | 1114 | Export and style-profile routes. |
| `llm_routes.py` | 1500 | LLM-powered generation API endpoints. |
| `pool_admin.py` | 388 | Superuser tool for managing the file pool. |
| `pool_routes.py` | 164 | File-pool lifecycle route handlers (thin transport layer). |
| `query_routes.py` | 132 | Read-only SQL API over a session's DuckDB (ADR-0016 Phase B). |
| `section_serializers.py` | 186 | JSON-row serialization for the section-card pipeline. |
| `server_state.py` | 60 | Central in-memory stores shared across route modules. |
| `session_routes.py` | 1617 | Session persistence and history API endpoints. |
| `upload_routes.py` | 900 | File upload and processing API endpoints. |
| `wizard_routes.py` | 96 | Wizard UI convenience routes (thin transport layer). |

## pipeline

The pool lifecycle: fingerprint → validate → integrate → process. Turns uploads into integrated.json + section caches + the per-session query substrate.

| module | loc | purpose |
|--------|----:|---------|
| `bmd_project_schema.py` | 996 | Pydantic models that validate `integrated.json` (ADR-0001 load barrier). |
| `cache_plumbing.py` | 566 | Per-section disk cache + hash inputs + platform-table (de)serializers. |
| `integrated_io.py` | 490 | Read/write barrier for integrated.json — the BMDProject seam. |
| `pool_fingerprints.py` | 368 | File-pool fingerprinting and lightweight validation. |
| `pool_globals.py` | 142 | Shared mutable state, router, and path helpers for the pool. |
| `pool_orchestrator.py` | 186 | Pool orchestrator — facade over the split modules. |
| `pool_state.py` | 212 | Pool-state mutation: progression, file replacement, artifacts. |
| `process_integrated.py` | 1384 | `run_process` orchestrator + the process/traceability endpoints. |
| `processing_helpers.py` | 1413 | Process-integrated pipeline phase functions. |
| `session_db.py` | 474 | Writer that materializes a session's DuckDB (ADR-0016 Phase A). |
| `session_schema.py` | 323 | Canonical per-session DuckDB schema (ADR-0016 Phase A). |
| `session_store.py` | 195 | Session persistence and version history per chemical. |
| `value_validation.py` | 212 | Value-level provenance cross-check (xlsx ↔ derived CSV). |

## document_model

The DocNode tree, template instantiation, the component catalog, the semantic type/style vocabulary, plus report-level filters and versions — the single source of report structure.

| module | loc | purpose |
|--------|----:|---------|
| `content_item.py` | 70 | An addressable content item within a document component. |
| `cover_layouts.py` | 318 | The cover / title-page layout catalog. |
| `document_config.py` | 511 | Per-session document STRUCTURE overrides (ADR-0007 follow-on). |
| `document_node.py` | 134 | The `DocNode` dataclass — one node in the report tree. |
| `document_template.py` | 1163 | Load a data-driven template and instantiate the tree. |
| `document_tree.py` | 534 | Declarative NIEHS report document structure. |
| `filters.py` | 256 | Report-level data-selection predicates. |
| `layout_style.py` | 320 | Per-content-type font & flow specification. |
| `render_capabilities.py` | 567 | The component-type catalog. |
| `version_config.py` | 212 | Per-DTXSID report VERSIONS (structure + filters). |
| `vocabulary.py` | 332 | The semantic-type vocabulary (design) system. |

## rendering

The shared `render_common` IR + the four emitters (HTML, LaTeX, docx, JATS/BITS) that project the DocNode tree to output surfaces.

| module | loc | purpose |
|--------|----:|---------|
| `render_common.py` | 1520 | Format-agnostic EXTRACT step shared by all surfaces (ADR-0006). |
| `html_generator.py` | 1712 | HTML rendering of the report. |
| `latex_generator.py` | 1914 | LaTeX rendering of the report. |
| `docx_generator.py` | 2544 | Microsoft Word (.docx) rendering (ADR-0008). |
| `jats_generator.py` | 868 | JATS/BITS XML projection (ADR-0004). |
| `jats_stylecheck.py` | 173 | Offline PMC/NLM StyleChecker gate for the JATS surface. |
| `latex_export.py` | 1305 | Overleaf bundle exporter (`load_session_data` assembly path). |
| `report_data.py` | 1013 | Data-assembly (`marshal_export_data` — the web/preview path). |
| `report_data_overlays.py` | 630 | Overlay layer for report data assembly. |
| `report_data_toc.py` | 458 | Table-of-Contents and section-filter layer. |
| `cross_references.py` | 173 | In-text cross-reference resolver (ADR-0004 amendment c). |

## tables

Per-platform NTP table builders + shared table formatting. Consume integrated.json, emit structured table rows.

| module | loc | purpose |
|--------|----:|---------|
| `table_builder_common.py` | 883 | Shared utilities for NIEHS table builders. |
| `apical_bmds.py` | 328 | BMDS-based benchmark dose modeling for apical endpoints. |
| `body_weight_table.py` | 697 | Build NIEHS Table 2 (Body Weights). |
| `organ_weight_table.py` | 635 | Build NIEHS Table 3 (Organ Weights) from sidecar data. |
| `clinical_pathology_table.py` | 398 | Build NIEHS Tables 4/5/6 from sidecar data. |
| `tissue_concentration_table.py` | 321 | Build NIEHS Table 7 (Tissue Concentration). |
| `sample_counts_table.py` | 152 | Sample-counts table builder for the Methods section. |

## narrative

Section prose — LLM (background, methods, genomics interpretation, summary) and programmatic (apical). Plus the interpretation engine.

| module | loc | purpose |
|--------|----:|---------|
| `unified_narrative.py` | 963 | Unified apical narrative — cross-platform NTP-style results prose. |
| `interpret_analysis.py` | 958 | Dose-response analysis layer for the interpretation engine. |
| `data_gatherer.py` | 1117 | Regulatory/toxicological data gatherer for background generation. |
| `background_writer.py` | 729 | LLM-based background section writer. |
| `methods_extract.py` | 648 | Methods context extractor from the file pool. |
| `chem_resolver.py` | 496 | Chemical identity resolver for the background generator. |
| `interpret_narrative.py` | 483 | LLM narrative generation and concordance analysis. |
| `abstract_apical.py` | 474 | Apical BMD summary + Abstract→Results apical paragraph. |
| `narrative_helpers.py` | 382 | Cross-cutting formatters + BMD-quality predicates. |
| `methods_prompt.py` | 331 | LLM prompt assembly for Materials & Methods. |
| `abstract_summary.py` | 314 | Abstract → Summary + Results aggregator. |
| `interpret.py` | 312 | Dose-response interpretation engine for bmdx. |
| `abstract_genomics.py` | 274 | Abstract → Results genomics paragraph. |
| `methods_models.py` | 269 | Dataclasses + heading skeleton for Methods. |
| `style_learning.py` | 247 | Writing-style profile persistence + LLM extraction. |
| `abstract_methods.py` | 155 | Abstract → Methods paragraph builder. |
| `abstract_pk.py` | 154 | Abstract → Results pharmacokinetics paragraph. |
| `methods_report.py` | 139 | Backward-compatible facade over the methods_* modules. |

## genomics

Genomics interpretation, charts/visualization, gene bodies, and enrichment.

| module | loc | purpose |
|--------|----:|---------|
| `genomics_viz.py` | 1430 | Genomics visualization endpoints. |
| `gene_bodies.py` | 474 | Body Results: Gene Set BMD + Gene BMD analysis prose. |
| `genomics_narratives.py` | 306 | Shared assembler for Gene Set / Gene BMD body narratives. |
| `chart_registry.py` | 263 | The chart-type catalog (configurable charts WP-2). |
| `chart_style.py` | 193 | The three-layer chart-style merge (configurable charts WP-1). |
| `genomics_charts.py` | 175 | Shared assembly of genomics chart images. |
| `genomics_content.py` | 100 | The ordered, sub-addressable content items in a genomics component. |

## knowledge_base

bmdx.duckdb build + query (ToxKBQuerier) and the crawl pipeline that populates it.

| module | loc | purpose |
|--------|----:|---------|
| `extract.py` | 1184 | LLM-based extraction from paper abstracts (local Ollama). |
| `citegraph.py` | 916 | Citation graph crawler with governor system. |
| `genefunc_crawl.py` | 611 | Gene-function second-pass crawl. |
| `fulltext.py` | 608 | Full-text retrieval for the extraction pipeline. |
| `crawl_phase2.py` | 478 | Phase 2 crawl: interpretation-driven literature expansion. |
| `build_db.py` | 407 | Build bmdx.duckdb (papers, genes, GO, pathways, claims). |
| `pathway_enrich.py` | 355 | Pathway enrichment over consensus/moderate genes. |
| `go_gene_map.py` | 313 | GO term → gene member mapping. |
| `enrichr_client.py` | 247 | Minimal client for the Enrichr REST API. |
| `enrichr_analysis.py` | 216 | CLI for running Enrichr enrichment analysis. |
| `enrichment_stats.py` | 195 | Pure statistical core for over-representation analysis. |
| `toxkb.py` | 163 | ToxKBQuerier — read-only typed queries over bmdx.duckdb. |
| `extract_phase2_runner.py` | 27 | Run Phase 2 extraction across the crawl dirs. |

## workflow

**(ADR-0014 / ADR-0015)** A UI-agnostic pool workflow engine lifted out of the browser: HTTP-free steps, a phase machine, and the label/guard ownership model.

| module | loc | purpose |
|--------|----:|---------|
| `phases.py` | 322 | UI-agnostic port of the pool phase machine (ADR-0014 step 1). |
| `steps.py` | 385 | HTTP-free pool workflow steps (ADR-0014 step 2). |
| `ownership.py` | 186 | The one guard predicate over content ownership (ADR-0015). |
| `labels.py` | 162 | The FACT layer: what humans assert about content (ADR-0015). |
| `store.py` | 157 | The injectable state seam for the engine (ADR-0014 Q2). |
| `currency.py` | 133 | The currency / staleness layer (ADR-0014 step 6). |
| `engine.py` | 120 | The UI-agnostic pool workflow engine (ADR-0014 step 3). |
| `guard.py` | 119 | The DERIVED edit-hardness layer (ADR-0015). |
| `errors.py` | 39 | HTTP-free failure signalling for workflow steps. |

## query

**(ADR-0016 Phase B)** Read-only SQL access to the per-session materialized DuckDB.

| module | loc | purpose |
|--------|----:|---------|
| `session_query.py` | 175 | `SessionQuerier` — read-only, validated SQL over a session's DuckDB. |

## styling_export

docx style extraction, freeform authored content, Overleaf/GitHub provisioning, session export, LLM adapters.

| module | loc | purpose |
|--------|----:|---------|
| `docx_style_extract.py` | 834 | Bootstrap the styling vocabulary FROM a Word template. |
| `freeform_content.py` | 426 | Authored ("freeform") document content. |
| `export_sessions.py` | 235 | Export Claude Code session transcripts to Markdown. |
| `llm_endpoints.py` | 161 | LLM endpoint adapters + credential/model-name resolution. |
| `llm_helpers.py` | 120 | Shared LLM generation utilities. |
| `overleaf_provision.py` | 98 | Overleaf addressing helpers (ADR-0005 Am.1a). |
| `github_provision.py` | 81 | Originate/adopt a report's GitHub repo (ADR-0005 Am.1a). |

## roundtrip

**(ADR-0005)** Domain-agnostic round-trip sync between machine-generated LaTeX and human edits in a git-backed editor (Overleaf).

| module | loc | purpose |
|--------|----:|---------|
| `transport.py` | 584 | Transport between the app and an Overleaf project. |
| `reconcile.py` | 246 | Attribute edited report.tex regions back to nodes. |
| `overrides.py` | 231 | Per-node user-owned content overrides (edits win at render). |
| `latex_to_html.py` | 150 | Conservative LaTeX → HTML for round-trip preview. |
| `lock.py` | 129 | Single-writer checkout lock per report. |
| `anchors.py` | 55 | The sentinel convention for anchored regions. |
| `_io.py` | 43 | Atomic file writes for round-trip state files. |

## pdf_text

Dependency-free (zlib-only) PDF library: semantic text extraction + a lossless codec.

| module | loc | purpose |
|--------|----:|---------|
| `parse_pdf.py` | 2186 | From-scratch PDF parser with classified text extraction. |
| `pdf_codec.py` | 429 | Lossless PDF decomposer and assembler (SHA-256 verified). |

## tooling

Build/scaffold/one-off scripts and dev utilities — not part of the request-serving app.

| module | loc | purpose |
|--------|----:|---------|
| `_build_divergence_doc.py` | 459 | Build the customer-facing style-divergence Word document. |
| `datasets_pipeline.py` | 407 | Bulk-corpus pipeline via the Semantic Scholar Datasets API. |
| `browser_fetch.py` | 202 | Headed-browser recovery fetcher for walled papers. |
| `build_catalog.py` | 199 | Build a consolidated corpus catalog. |
| `build_manifest.py` | 141 | Build a navigable manifest of the retrieved corpus. |
| `_rebuild_sections.py` | 105 | Dev helper: rebuild the cheap deterministic caches. |
| `_content_only_docx.py` / `_content_only_ntp_docx.py` | 77 / 66 | Content/style separation tests. |
| `_build_docx_base.py` / `_derive_dotx.py` | 65 / 60 | docx template-base dev helpers. |
| `_rebuild_genomics.py` / `_regen_docx.py` | 55 / 20 | Cache/report regeneration helpers. |

## wizard-ui (TypeScript / React)

**(ADR-0016)** The from-scratch step-by-step report wizard: a visual query builder, an in-browser DuckDB console, and a report data-lineage gallery. Built to `web_wizard/` and served at `/wizard`.

| module | purpose |
|--------|---------|
| `src/api.ts` | Client for the session-query + wizard routes. |
| `src/duckdb.ts` | In-browser DuckDB-WASM bindings. |
| `src/steps/Query.tsx` / `QueryBuilder.tsx` / `buildSql.ts` | Visual query builder — tables as nodes, joins as edges. |
| `src/steps/ReportGallery.tsx` | Report data-lineage gallery — a card per table/chart. |
| `src/steps/SummaryTables.tsx` / `DataTree.tsx` / `SessionPicker.tsx` | Data-prep step surfaces. |
