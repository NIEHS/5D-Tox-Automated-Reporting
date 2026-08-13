# rlm-bmdx

## Package layout (read first)

The codebase is organized into **concern packages** (restructured 2026-08-12, ADR-0013).
First-party modules are NOT at the repo root — they live in these packages, and
imports are package-qualified (`from rendering.render_common import ...`,
`from pipeline.process_integrated import ...`, `from document_model.document_tree import ...`):

| package | concern |
|---------|---------|
| `web_routes/` | FastAPI app + HTTP routes (entrypoint: `python -m web_routes.background_server`) |
| `pipeline/` | pool lifecycle + processing; `process_integrated`, `session_store`, `bmd_project_schema`, `integrated_io`, `cache_plumbing`, `pool_*` |
| `document_model/` | `document_tree`/`document_node`/`document_template`/`document_config`, `render_capabilities`, `vocabulary`, `cover_layouts`, `layout_style` |
| `rendering/` | shared IR `render_common` + the 4 emitters (`html_generator`, `latex_generator`, `docx_generator`, `jats_generator`) + `report_data*`, `latex_export`, `cross_references`, `jats_stylecheck` |
| `tables/` | `table_builder_common`, `*_table`, `apical_bmds`, `methods_table1` |
| `narrative/` | `interpret*`, `methods_*`, `abstract_*`, `background_writer`, `data_gatherer`, `unified_narrative`, `style_learning` |
| `genomics/` | `genomics_*`, `gene_bodies`, `chart_registry`, `chart_style` |
| `knowledge_base/` | `build_db`, `toxkb`, `citegraph`, `crawl_*`, `fulltext`, `extract`, `enrichr_*`, `enrichment_stats`, `pathway_enrich`, `go_gene_map` |
| `styling_export/` | `docx_style_extract`, `freeform_content`, `export_sessions`, `*_provision`, `llm_endpoints`, `llm_helpers` |
| `tooling/` | dev/scratch/build scripts |

`roundtrip/` and `pdf_text/` are pre-existing packages. Resolution is the
repo-root-on-`sys.path` (cwd) model — no `pip install` needed. Known accepted
debt: cross-package import cycles the flat layout had masked (see ADR-0013).

## Work Type Constraints

Before making changes, identify which type of work this session involves and load the corresponding constraint profile from memory. Each profile defines what's in-scope and what's off-limits.

| Work type | Constraint profile | Core scope |
|-----------|-------------------|------------|
| **Table builders** | `constraints_table_builders.md` | `tables/` — `*_table.py`, `table_builder_common.py`, `apical_bmds.py`; consume integrated.json only |
| **UI / sessions** | `constraints_ui_work.md` | `web/js/*`, `web_routes/session_routes.py`, `pipeline/session_store.py` — state derivation never imperative |
| **LLM narratives** | `constraints_llm_narratives.md` | `narrative/` (`background_writer.py`, `interpret.py`, `unified_narrative.py`) + `web_routes/llm_routes.py` — know which sections are LLM vs programmatic |
| **Knowledge base** | `constraints_knowledge_base.md` | `knowledge_base/` — `build_db.py`, `toxkb.py` ToxKBQuerier, crawl pipeline; schema is a cross-project contract |
| **Cross-cutting refactor** | `constraints_cross_cutting_refactor.md` | May touch anything, but must map blast radius first and test full flow |

If work spans multiple types, say so explicitly and follow the stricter constraints of each. When uncertain whether something is in-scope, err toward not touching it.

## Architectural Invariants

Three rules that apply to all work types, no exceptions:

### 1. Integrated dataset is the single source of truth

All report content reads from `integrated.json` (BMDProject format) + sidecar JSON files. Never bypass to read raw .bm2, .txt, .csv, or .xlsx files. If data is missing, fix the integration step — don't add a bypass.

Sidecars preserve per-animal metadata the pivot discards: Selection (core vs biosampling), Observation Day, Terminal Flag, raw per-animal values. See `expertise_data_pipeline.md` for the full source-of-truth hierarchy and the known pivot data loss problem.

### 2. Document tree drives all structure

The `DocNode` tree in `document_model/document_tree.py` is the single source of truth for report organization — heading hierarchy, section ordering, table numbering, platform-to-section mappings. Nothing structural is hardcoded. Table numbers are positional (auto-assigned by tree walk), never user-provided. See `expertise_document_tree.md` for node types, the four-surface render IR (Typst is dead — see `project_render_surfaces`), and how to add new sections.

### 3. UI phase is derived, never imperatively set

`derivePoolPhase(artifacts)` examines what artifacts exist and returns the correct phase. All code dispatches the result of this function — never guess the phase. Transient async phases (VALIDATING, INTEGRATING, APPROVING) are the only exception. This rule extends to all future AppStore slices. See `expertise_ui_state.md` for the full phase sequence and POOL_PHASES registry.

## Domain Expertise and TODOs

Consult these memory files when working in unfamiliar areas:

- `expertise_java_interop.md` — .bm2 serialization traps, subprocess patterns, transient vs persisted fields
- `expertise_ntp_statistics.md` — Python/Java test split, responsive flag logic, BMD classification, table business rules, footnote scheme
- `expertise_data_pipeline.md` — source-of-truth hierarchy, pivot data loss, integration lifecycle, bmdx-pipe dependency
- `expertise_knowledge_base.md` — bmdx.duckdb schema, ToxKBQuerier, static artifact status
- `expertise_document_tree.md` — DocNode structure, four-surface render IR (Typst dead), NIEHS fidelity gap
- `expertise_ui_state.md` — AppStore architecture, phase derivation, migration status
- `todo.md` — prioritized work items (CRITICAL/HIGH/MEDIUM/LONG-TERM)

## Agent skills

### Issue tracker

GitHub Issues at NIEHS/5D-Tox-Automated-Reporting via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles using their default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
