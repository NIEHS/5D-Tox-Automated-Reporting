# rlm-bmdx

## Work Type Constraints

Before making changes, identify which type of work this session involves and load the corresponding constraint profile from memory. Each profile defines what's in-scope and what's off-limits.

| Work type | Constraint profile | Core scope |
|-----------|-------------------|------------|
| **Table builders** | `constraints_table_builders.md` | `*_table.py`, `table_builder_common.py`, `apical_bmds.py` — consume integrated.json only |
| **UI / sessions** | `constraints_ui_work.md` | `web/js/*`, `session_routes.py`, `session_store.py` — state derivation never imperative |
| **LLM narratives** | `constraints_llm_narratives.md` | `background_writer.py`, `interpret.py`, `llm_routes.py`, `unified_narrative.py` — know which sections are LLM vs programmatic |
| **Knowledge base** | `constraints_knowledge_base.md` | `build_db.py`, `interpret.py` ToxKBQuerier, crawl pipeline — schema is a cross-project contract |
| **Cross-cutting refactor** | `constraints_cross_cutting_refactor.md` | May touch anything, but must map blast radius first and test full flow |

If work spans multiple types, say so explicitly and follow the stricter constraints of each. When uncertain whether something is in-scope, err toward not touching it.

## Architectural Invariants

Three rules that apply to all work types, no exceptions:

### 1. Integrated dataset is the single source of truth

All report content reads from `integrated.json` (BMDProject format) + sidecar JSON files. Never bypass to read raw .bm2, .txt, .csv, or .xlsx files. If data is missing, fix the integration step — don't add a bypass.

Sidecars preserve per-animal metadata the pivot discards: Selection (core vs biosampling), Observation Day, Terminal Flag, raw per-animal values. See `expertise_data_pipeline.md` for the full source-of-truth hierarchy and the known pivot data loss problem.

### 2. Document tree drives all structure

The `DocNode` tree in `document_tree.py` is the single source of truth for report organization — heading hierarchy, section ordering, table numbering, platform-to-section mappings. Nothing structural is hardcoded. Table numbers are positional (auto-assigned by tree walk), never user-provided. See `expertise_document_tree.md` for node types, the Typst rendering pattern, and how to add new sections.

### 3. UI phase is derived, never imperatively set

`derivePoolPhase(artifacts)` examines what artifacts exist and returns the correct phase. All code dispatches the result of this function — never guess the phase. Transient async phases (VALIDATING, INTEGRATING, APPROVING) are the only exception. This rule extends to all future AppStore slices. See `expertise_ui_state.md` for the full phase sequence and POOL_PHASES registry.

## Domain Expertise and TODOs

Consult these memory files when working in unfamiliar areas:

- `expertise_java_interop.md` — .bm2 serialization traps, subprocess patterns, transient vs persisted fields
- `expertise_ntp_statistics.md` — Python/Java test split, responsive flag logic, BMD classification, table business rules, footnote scheme
- `expertise_data_pipeline.md` — source-of-truth hierarchy, pivot data loss, integration lifecycle, bmdx-pipe dependency
- `expertise_knowledge_base.md` — bmdx.duckdb schema, ToxKBQuerier, static artifact status
- `expertise_document_tree.md` — DocNode structure, Typst rendering, NIEHS fidelity gap
- `expertise_ui_state.md` — AppStore architecture, phase derivation, migration status
- `todo.md` — prioritized work items (CRITICAL/HIGH/MEDIUM/LONG-TERM)
