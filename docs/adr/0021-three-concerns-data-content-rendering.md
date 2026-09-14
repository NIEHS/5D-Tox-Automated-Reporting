# 0021 — Three concerns: processing, content preparation, rendering

- **Status:** Accepted (2026-09-14) — names the application's production
  architecture and supersedes the informal "data vs. document" two-axis framing that
  had no home for the content-preparation layer.
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0002](0002-decompose-api-process-integrated.md) (the
  `run_process` decomposition this ADR extends — extract under a golden oracle, then
  change behavior), [ADR-0006](0006-unify-html-latex-renderers.md) (the render_common
  IR — clarified here as internal to concern [3], not the content intermediate),
  [ADR-0016](0016-canonical-query-substrate.md) (the query substrate is a concern-[1]
  output; "rendering domain as binding seam" is a concern-[3] input),
  [ADR-0018](0018-app-is-not-an-editor.md) (the document reader already reads prepared
  content read-only — the half-built seam this ADR completes),
  [ADR-0020](0020-one-evolving-report-not-a-version-tree.md) (all three concerns act
  on the one evolving report), [ADR-0019](0019-metadata-vocabulary-policy.md) (the
  data-side twin: metadata authority is a concern-[1] policy).

## Context — the seam that has no name

`run_process` (`pipeline/process_integrated.py`) does two different jobs fused into
one function. It **processes** imported data into numeric, hash-keyed, reproducible
results (NTP stats, BMDS, genomics extraction, BMD summary, the query substrate) —
and it **also** eagerly produces every piece of prose the report will render
(methods, genomics narratives, apical BMD narrative, unified narratives, the
per-card narratives inside `sections`). Both land in one 12-key `result_payload`, and
`load_session_data` (`rendering/latex_export.py`) reassembles them into one `data`
dict that carries `bmd_summary["endpoints"]` numbers *and* `unified_narratives`
sentences side by side.

We repeatedly tried to model this as a single axis — "data vs. document" — and it
kept failing, because that framing is a **render-time composition formula**
("description + data → document", [ADR-0003](0003-document-component-model.md)), not
an account of how the inputs are *produced*. Its three nouns are render-time roles.
Reasoning from it as if it were the architecture created a false trichotomy with no
slot for the layer that turns processed numbers into renderable content, and no slot
for the LLM (which is neither data nor document — it is a helper on both).

The consequence is concrete misfiling: a document concern (prose) lives inside the
data pipeline; the `data` dict is an undifferentiated blend; and a structure-only
fact (a figure number) is stamped data-side (`genomics/genomics_charts.py`), forcing
two figure counters that "must be reconciled" (`document_model/document_tree.py`).

## Decision

**The application has three production concerns, with two intermediates between input
and output.** This is the architecture; the composition formula sits at the boundary
of the third concern and is unchanged.

```
input ─[1]─▶ processed data ──┐
                              ├─[2] prepare content ─▶ document content ─[3] render ─▶ output
              declarations ───┘   (data-derived +                  ▲
              (policy + content)   declaration-derived +        declarations
                                   structure-derived)           (styling)
```

### [1] Processing — input → processed data

Numeric results, classified by metadata; reproducible and hash-keyed (the golden-
oracle domain). Takes **no** declarations — it is a pure function of its inputs. Today:
`_build_ntp_stats`, `_get_bmds`, `_get_genomics` (extraction), `_build_bmd_summary`,
`_build_charts` (data viz), `_build_query_substrate` (the `session.duckdb` substrate,
already skip-guarded — commit `11682fb`). LLM role here: a **helper** that guesses
missing descriptive metadata (e.g. sex not explicitly supplied), never authoring
substance.

### [2] Content preparation — processed data + declarations → document content

**Document content is EVERYTHING that gets rendered**, not just prose. Its kinds:

- **prose** (narrative reductions — deterministic *and* LLM-phrased alike),
- **table content** (the rows a table is rendered *from* — not the table *of*
  contents),
- **chart/figure content** (kinds extensible, not a closed set),
- **references**,
- **front matter** (title, authors, contract numbers, "About This Report" — these are
  the human-set declaration *values*, not a data reduction),
- **ToC / List-of-Tables / List-of-Figures** (structure-derived at render).

Its sources are mixed on purpose: **data-derived** (reductions of concern [1]),
**declaration-derived** (front matter is the declared values themselves), and
**structure-derived** (positional lists from the tree). Prose, table-rows, and
chart-marks are the **same kind of thing** architecturally — each is content prepared
for rendering. Do not re-split them into "prose = document / tables = data"; that is
the original conflation relocated. The BMDS *numbers* are concern [1]; their
*arrangement* into Table 3's filtered, ordered, labeled rows is concern [2].

**This concern does not exist as a layer today** — it is scattered: prose in
`run_process`, front matter in the configurator, references in `_persist_references`,
`content_items`/freeform on the tree, ToC computed at render. `content_items` and
freeform are early partial instances of it. LLM role here: a **helper** that phrases
one reduction, inside the one prose method — nowhere else.

Method selection per content **kind** is an open registry (kinds and methods
extensible), symmetric with the node-type→render registry — not a closed switch.

### [3] Rendering — document content + structure + styling → output

Rendering takes **three** inputs, not one:

1. **document content** (from [2]),
2. **structure** — the `DocNode` tree: ordering, **numbering**, and cross-references,
3. **styling declarations** — how it looks.

**Structure is a distinct render input, neither content nor styling.** Numbering is
kept *off* content deliberately: "Table 3" does not exist until the tree is walked;
it is global and positional, so a baked-in number goes stale on re-parent or rename.
`compute_table_numbers` / `compute_figure_numbers` / appendix-letters run *inside* the
render call as a positional tree walk (`document_model/document_tree.py`), and
cross-references (`[[xref:id]]`, `rendering/cross_references.py`) resolve *after*
numbering by tree lookup. Verified: emitters are `generate_latex(data, tree)` /
`generate_docx(data, tree)` — they receive content and structure and walk the tree
themselves.

The **render_common IR is internal to this concern**, not the content intermediate.
There is no `render(ir)` interface; each emitter pulls small per-node, transient plan
structs at walk time (`resolve_narrative_content`, `apical_table_plan`, …) and turns
them into markup. The IR is an anti-drift refactor of shared decision logic
([ADR-0006](0006-unify-html-latex-renderers.md)), welded to `data`'s shape — not an
abstraction over an arbitrary content source. Whether it *should* become a true
`document-content → IR → surface` interface is a separate, live design question.

### Declarations split by role AND stage

- **policy** (how to reduce/select) → feeds [2],
- **content** (front-matter values) → feeds [2],
- **styling** (how it looks) → feeds [3].

The `description + data = document` formula bundled all three under "description."
Separating them by stage is what the concern model buys.

### The LLM is a helper, never a structural axis

It appears in exactly two places, symmetrically: guessing metadata in [1], phrasing a
reduction inside one method of [2]. It is never a data-pipeline stage, a document
sub-type, or its own axis. How much LLM is needed shrinks as the fundamental axis on
each side (metadata vocabulary; the reduction + structure) is specified as policy.

## What this rejects

- The two-axis "data vs. document" model **as the architecture** (it survives only as
  the render-time composition formula it always was).
- Treating the render_common IR as the document-content intermediate.
- Any model in which the LLM is a structural layer.
- Splitting content into "prose = document, tables = data."

## Consequences and known seam violations

- **The refactor is scoped and leaf-first.** Concern [2] gets materialized as a
  function (`prepare_content`) carved out of `run_process` under the existing
  12-key golden byte-oracle (`tests/integration/test_process_integrated_golden.py`),
  behavior-preserving; then given its own skip-guard keyed on [1]-outputs +
  declarations (mirroring `build_session_db_if_changed`). The payoff:
  **regenerate content without recomputing data.** See the concern manifest below.
- **Known seam violations to fix (deliberately, behind a gate):**
  1. genomics **chart figure numbers** are assigned data-side
     (`genomics/genomics_charts.py`), a structure fact smuggled into content — the
     two-counter reconciliation noted at `document_model/document_tree.py:174-180`.
  2. literal `"Table N"` strings are baked into genomics prose
     (`genomics/gene_bodies.py:118,328`, numbers sourced in
     `genomics/genomics_narratives.py`), bypassing the `[[xref:id]]` cross-reference
     system. Both are structure-derived facts that belong at render time.
- **Cache families already reveal the split** (verified): `_cache_bmds_*`,
  `_cache_bmd_summary_*`, `_cache_genomics_*`, the substrate = concern [1];
  `_cache_methods_*`, `_cache_interpretation_*`, `references.json`,
  `_cache_summary_generated.json`, `background.json`, and `_cache_sections_*` =
  concern [2]. `_cache_sections_*` carries **table content** (`tables_json`,
  `caption`, `first_col_header`, `footnotes`, `table_type`) alongside **prose**
  (each card's `narrative`, plus a top-level `unified_narratives`). Under this
  ADR that co-location is **content next to content, NOT a data/content blend**:
  `tables_json` is the presentation-ready display rows `_build_section_cards`
  serializes FROM the concern-[1] `platform_tables` (which stays on `ctx`, never
  in this cache), so it is concern [2], the same kind of thing as the prose.
  Splitting prose from table-content here would be the original "prose=document,
  tables=data" conflation relocated — explicitly rejected (see "What this
  rejects"). Verified against a real cache: keys are exactly
  `{sections, unified_narratives}`, and each card is
  `{caption, first_col_header, footnotes, narrative, platform, tables_json,
  title}` — no raw processed data present.
- **Consistent with the version model** ([ADR-0020](0020-one-evolving-report-not-a-version-tree.md)):
  all three concerns act on the one evolving report; concern boundaries are not
  version boundaries.

## Concern manifest — every persisted artifact classified

| Artifact / cache family | Producer | Concern | Notes |
|---|---|---|---|
| `_cache_bmds_*` | `_get_bmds` | [1] data | BMDS compute results |
| `_cache_bmd_summary_*` | `_build_bmd_summary` | [1] data | numeric endpoint summary |
| `_cache_genomics_*` | `_get_genomics` | [1] data | genomics extraction |
| `_cache_charts_*` / `chart_images` | `_build_charts` | [1] data | data viz (rendered marks) |
| `session.duckdb` + `session_parquet/` | `_build_query_substrate` | [1] data | query substrate; skip-guarded (`11682fb`) |
| `.session_db.fingerprint` | `build_session_db_if_changed` | [1] data | substrate skip-guard key |
| `_cache_methods_*` | `_get_methods` | [2] content | M&M prose (LLM-phrased) |
| `_cache_interpretation_<organ>_<sex>_*` | `_build_genomics_llm_narratives` → `generate_genomics_narrative_async` | [2] content | shared builder+cache with standalone endpoint (clean) |
| `_cache_apical_narrative_*` | `_build_apical_bmd_narrative` | [2] content | apical BMD prose; **no standalone endpoint (gap)** |
| `references.json` | `_persist_references` | [2] content | reference assembly (depends on genomics narrative pass) |
| `background.json` | (written elsewhere) | [2] content | read as content by the reader |
| `summary.json` / `_cache_summary_generated.json` | `/api/generate-summary` (standalone-only) | [2] content | **cache-write mismatch**: writer emits `summary.json`, reader looks for `_cache_summary_generated.json` |
| `_cache_sections_*` | `_get_sections` | [2] content | Table CONTENT (`tables_json`/caption/headers/footnotes, serialized from `platform_tables`) + prose (`narrative`, `unified_narratives`). Content-next-to-content, NOT a data blend — assessed and deliberately NOT split (D3) |
| serialized `DOCUMENT_TREE`, `toc_entries`, `table_entries` | `serialize_tree` at read | [3] structure | correctly derived at render time |
| render_common plan structs | emitters at walk time | [3] render | internal IR, transient, per-node |

## Open questions

- **Eager vs. lazy content preparation.** Does [2] run automatically right after
  processing (preserving today's "process fills everything," lowest-risk, oracle-
  preserving) or become on-demand like the existing regenerate endpoints? Deferred to
  the maintainer. Note: eager-but-separated is compatible with the intended blocking
  Process UI; the frontend already tolerates blank prose, so lazy is *possible* but
  needs the cache-write paths unified first (methods drifts on model; summary/apical
  have cache/endpoint gaps).
- **Should the IR become a true content→surface interface?** Left open (above).
- **Elevate [2] to a workflow step?** A `document_step` beside `process_step`
  ([ADR-0014](0014-ui-agnostic-workflow-engine.md)) — depends on the eager/lazy call.
