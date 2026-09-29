# Code Walkthrough

> A **flow-oriented** tour of rlm-bmdx on the **package-layout** branch: how a
> request actually moves through the code, traced symbol-by-symbol against the
> call graph. Generated 2026-08-26 from an `rlm-code` index of the branch
> (262 files, 2,841 symbols, 15,702 edges — Python + the TypeScript/React
> `wizard-ui`). Every `file:line` was read out of the graph; line numbers drift,
> so re-index (`rlm-code index --force`) if they feel stale.
>
> **Read the other two docs first for orientation, then this one for motion:**
> - [`CONTEXT.md`](../CONTEXT.md) — *why* the architecture is shaped this way (domain-driven).
> - [`architecture-map.md`](architecture-map.md) — *what* lives where (14 packages, static).
> - **This doc** — *how* control flows across those packages at runtime (dynamic).
>
> **Layout note:** this branch is the **package-layout** world (ADR-0013). Modules
> live in concern packages and imports are package-qualified
> (`from pipeline.process_integrated import run_process`). This differs from `main`,
> where everything is still flat at the repo root.

---

## 1. The shape of the system, from the graph

**Hot paths** (PageRank over the reversed call graph — ranks orchestrators):

| Symbol | Location | Role |
|--------|----------|------|
| `PendingContentError` / `BMDProjectValidationError` / `StepError` | `rendering/render_common.py:99`, `pipeline/bmd_project_schema.py:157`, `workflow/errors.py:22` | the three **load/guard barriers** (render, data, workflow) |
| `run_process` | `pipeline/process_integrated.py:1074` | **the pipeline orchestrator** (out=31) |
| `marshal_export_data` | `rendering/report_data.py:228` | the web/preview **assembly** path |
| `load_session_data` | `rendering/latex_export.py:567` | the export-side assembly path |
| `_get_sections` | `pipeline/process_integrated.py:653` | apical section-card builder + cache |
| `api_process_integrated` | `pipeline/process_integrated.py:1043` | thin HTTP wrapper → delegates to `run_process` (out=2) |
| `process_step` | `workflow/steps.py:369` | the workflow-engine entry that also calls `run_process` |
| `generate_docx` | `rendering/docx_generator.py:2408` | Word emitter (in=72 — most-referenced render entry) |

**God objects** (highest total degree):

| Symbol | in / out | Why it's central |
|--------|---------:|------------------|
| `Vocabulary.get` (`document_model/vocabulary.py`) | 631 / 1 | the semantic-type lookup; every render decision consults it |
| `generate_docx` / `generate_html` / `generate_latex` | 72 / 42 / 40 | the three live render surfaces |
| `instantiate` (`document_model/document_template.py`) | 48 / 3 | builds the `DocNode` tree from a YAML template |
| `run_process` (`pipeline/process_integrated.py`) | 2 / 31 | the orchestrator (high fan-out, low fan-in — pure top of the pipeline) |
| `find_node` (`document_model/document_tree.py`) | 37 / 2 | the tree's addressing primitive |

The center of gravity is unchanged from `main` — a **tree** + a **vocabulary** feeding **assembly** and **emitters** — but the branch adds two structural layers: a **`workflow/` engine** and a **`query/` substrate** (both appear in the hot paths above).

---

## 2. The defining branch change: `api_process_integrated` is now thin

On `main`, `api_process_integrated` *was* the god function (out=26). On this branch it's a **2-callee HTTP shim**; the real orchestration moved into **`run_process`** so it can be driven without HTTP. Both the route and the workflow engine call the same core:

```
api_process_integrated (web handler)   pipeline/process_integrated.py:1043
   └─ run_process ····················· pipeline/process_integrated.py:1074   (out=31)

process_step (workflow engine)         workflow/steps.py:369
   └─ run_process ····················· pipeline/process_integrated.py         (same core)
```

This is **ADR-0014** — "extract a UI-agnostic workflow engine from the browser."
The pipeline core is now callable from an HTTP route, the workflow engine, or a
notebook, all through `run_process`.

---

## 3. The main flow: `run_process`

The orchestrator's 31 callees fall into the same four ordered stages as `main`'s
old `api_process_integrated`, plus one new stage — the query substrate:

```
run_process                                    pipeline/process_integrated.py:1074
│
├─ (1) LOAD via the injectable store seam (ADR-0014 Q2)
│     PoolStore.get_integrated / DiskPoolStore.get_integrated ··· workflow/store.py
│     _session_dir ····················· pipeline/pool_globals.py
│
├─ (2) CACHE FENCE — hash each section's inputs
│     _hash_sidecars / _hash_sections / _hash_bmds
│     _hash_genomics / _hash_methods ··· pipeline/cache_plumbing.py
│
├─ (3) RESOLVE report-scoped context from the tree/template
│     load_report_organs / _sex / _assays / _genes / _gene_sets ··· document_model/document_template.py
│
├─ (4) BUILD content — the ADR-0002 labeled layers
│     _build_ntp_stats                  # Java-backed Williams/Dunnett stats
│     _get_sections / _get_bmds / _get_genomics / _get_methods
│     _build_charts / _build_bmd_summary
│     _build_genomics_llm_narratives / _build_genomics_body_narratives
│     _build_apical_bmd_narrative
│
└─ (5) MATERIALIZE the query substrate  (NEW — ADR-0016)
      _build_query_substrate ··········· pipeline/process_integrated.py
              └─ writes session.duckdb via pipeline/session_db.py + session_schema.py
```

Everything downstream of `run_process` (the `_get_*`/`_build_*` layers) is the same
NTP report machinery documented in `main`'s walkthrough — see `_get_sections`
(`pipeline/process_integrated.py:653`) for the apical-tables layer, which reads
**integrated.json + sidecars** (never raw `.bm2`) via `table_builder_common`.

---

## 4. The workflow engine (ADR-0014 / ADR-0015)

`workflow/` is the branch's biggest new subsystem — the pool lifecycle lifted out
of the browser into HTTP-free, testable pieces:

| Layer | Module | Role |
|-------|--------|------|
| Phase machine | `workflow/phases.py` | UI-agnostic port of the pool phase sequence (step 1) |
| Steps | `workflow/steps.py` | HTTP-free step functions; `process_step` calls `run_process` (step 2) |
| Engine | `workflow/engine.py` | drives steps against a store (step 3) |
| Store seam | `workflow/store.py` | injectable state (`PoolStore` / `DiskPoolStore`) — the seam that makes the pipeline HTTP-free |
| Currency | `workflow/currency.py` | staleness / recompute detection (step 6) |
| **Labels** | `workflow/labels.py` | the FACT layer — what humans assert about content (ADR-0015) |
| **Guard** | `workflow/guard.py` + `ownership.py` | the DERIVED edit-hardness — consequences the system computes from labels |

ADR-0015's thesis shows up directly in the split: **`labels.py` (facts humans
assert)** vs **`guard.py`/`ownership.py` (consequences the system derives)** — the
same "derived, never imperatively set" principle the UI phase already followed,
now applied to content ownership.

---

## 5. The query substrate (ADR-0016)

A new capability: each processed session materializes its own **DuckDB**, exposed
read-only over HTTP and to an in-browser query UI.

```
WRITE (during processing)
  run_process → _build_query_substrate
      └─ pipeline/session_db.py       # materialize session.duckdb
         pipeline/session_schema.py   # the canonical per-session schema

READ (on demand)
  web_routes/query_routes.py  (HTTP, ADR-0016 Phase B)
      └─ query/session_query.py :: SessionQuerier
             ├─ validate_sql()   # read-only guard — rejects writes/DDL
             ├─ run_sql()        # execute against session.duckdb
             └─ schema()         # table/column introspection
```

`SessionQuerier` (`query/session_query.py:95`) is the seam: a context-managed,
timeout-bounded, **read-only-validated** SQL surface. The `wizard-ui` frontend
consumes it (below); `value_validation.py` (`pipeline/`) uses the same substrate
idea for an xlsx↔CSV provenance cross-check that blocks on divergence.

---

## 6. The wizard UI (TypeScript / React, ADR-0016)

A from-scratch step-by-step report builder under `wizard-ui/` (built to
`web_wizard/`, served at `/wizard`). Unlike the main app's server-rendered flow,
this is a client app that talks to the query substrate:

```
wizard-ui/src/App.tsx                     # step orchestrator
  ├─ api.ts                               # client for query_routes + wizard_routes
  ├─ duckdb.ts                            # in-browser DuckDB-WASM
  └─ steps/
       ├─ SessionPicker.tsx               # pick a processed session
       ├─ DataTree.tsx / ConfirmMetadata.tsx   # inspect the data
       ├─ QueryBuilder.tsx + buildSql.ts + Query.tsx   # visual query builder (tables=nodes, joins=edges)
       ├─ SummaryTables.tsx               # tabular results
       └─ ReportGallery.tsx              # data-lineage gallery — a card per report table/chart
```

The query builder composes SQL client-side (`buildSql.ts`) and runs it either in
the browser (`duckdb.ts`, DuckDB-WASM over per-table Parquet) or against the
server's `SessionQuerier`.

---

## 7. The render flow: one tree, four surfaces

Unchanged in structure from `main` (ADR-0006), just package-qualified. Assembly
happens once, then each emitter projects the same `DocNode` tree:

- **Assembly** — `marshal_export_data` (`rendering/report_data.py:228`, web path)
  and `load_session_data` (`rendering/latex_export.py:567`, export path) both walk
  `document_model/document_tree.py`, compute **positional** table numbers
  (`compute_table_numbers`), overlay content domains, and apply user overrides
  from `roundtrip/overrides.py`.
- **Emit** — `generate_html` / `generate_latex` / `generate_docx` /
  `jats_generator` (all under `rendering/`) funnel through `find_node` on the
  shared tree. `render_common.py` holds the format-agnostic EXTRACT plan; each
  emitter owns only its markup. Parity is enforced at import (a node-type registry
  fails to load if any type lacks an emitter on HTML/LaTeX/Word).

`Vocabulary.get` (`document_model/vocabulary.py`, in-degree 631) is consulted
throughout — it resolves each node's semantic type to its style.

---

## 8. The KB-grounding flow: genomics interpretation

Unchanged from `main`, package-qualified: `narrative/interpret.py` and
`interpret_analysis.py` pull literature-grounded facts from the knowledge base via
`ToxKBQuerier` (`knowledge_base/toxkb.py`) — `gene_go_terms`, `gene_organs`,
`gene_papers`, `gene_claims` — run enrichment (`knowledge_base/enrichment_stats.py`),
and feed that context to the LLM. Apical narratives (`narrative/unified_narrative.py`)
stay largely deterministic.

> **Note the two DuckDBs, don't confuse them:** `knowledge_base/bmdx.duckdb` is the
> cross-session literature KB (grounds genomics prose); the ADR-0016
> `session.duckdb` (§5) is per-session materialized report data (powers the query
> UI). Different databases, different purposes.

---

## 9. How to navigate further

- **Browse interactively:** `rlm-code viz` for this worktree at
  `http://localhost:9000` — tree, call graph, per-symbol callers/callees, and the
  Opus summaries inline.
- **Query the graph:** `rlm-code query <symbol> --path /workspace/package-layout-workflow-engine`,
  plus `trace` / `related` / `hotspots` / `patterns`.
- **Re-index after changes:** `rlm-code index --force /workspace/package-layout-workflow-engine`.
