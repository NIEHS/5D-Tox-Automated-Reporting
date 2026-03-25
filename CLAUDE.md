# rlm-bmdx

## Data Source Architecture

The **integrated dataset** is the single source of truth for all report content. Nothing in the report should read from individual file pool files directly.

Two artifacts comprise the integrated dataset:

1. **`integrated.json`** (BMDProject format) — the merged .bm2 produced by `integrate_pool()`. Contains all dose-response experiments, BMDExpress 3 bMDResults, and probe responses. This is the source for:
   - Mean ± SE per dose group (from probeResponses)
   - BMD/BMDL values and NIEHS classification (from bMDResult: viable, NVM, UREP, NR)
   - NTP statistics: Jonckheere trend, Williams/Dunnett pairwise (computed by `build_table_data()` from integrated experiments)
   - Significance markers on dose group cells

2. **Sidecar JSON files** (`*.sidecar.json`) — per-animal metadata written alongside pivots during integration by `tox_study_csv_to_pivot_txt()`. These preserve information the pivot discards:
   - Animal Selection (Core Animals vs Biosampling Animals) — for correct N counts
   - Observation Day / Removal Day / Phase+Day — for study day labels and attrition detection
   - Terminal Flag — for identifying dead/moribund animals
   - Raw per-animal values — for computing stats from scratch (body weight, organ weight relative weights)

**Rule: No table builder or report generator should read from individual file pool .bm2 files, .txt pivots, or .csv source files.** Everything flows through `integrated.json` + sidecars. If data is missing from the integrated dataset, fix the integration step — don't add a bypass that reads raw files.

BMDExpress 3 modeling (bMDResult) and NTP statistical significance (Jonckheere + Dunnett) are **independent concerns**. An endpoint can have a viable BMD without being NTP-significant, and vice versa. Both are shown in the tables — the BMD column reflects .bm2 modeling status, not the NTP gate.

## Document Structure Architecture

The **document structure tree** (`document_tree.py`) is the single source of truth for the report's organization. The NIEHS report is defined as a tree of `DocNode` objects specifying heading hierarchy, section ordering, table numbering, node types, and platform-to-section mappings.

**Rule: No part of the system should hardcode document structure.** The tree drives everything:

- **Typst template** (`report.typ`): reads the tree from JSON (`data.document_tree`), walks it to emit headings at the correct level, render narratives, and number tables. Group headings, narrative keys, and platform membership are all derived from the tree at render time — not from hardcoded maps in the template.
- **PDF preview filter** (`report_pdf._apply_section_filter`): given a TOC node ID, uses `find_node()` + `collect_data_keys()` + `collect_platforms()` to determine which data to keep. No hardcoded filter maps.
- **Table numbering**: auto-assigned by `compute_table_numbers()` walking the tree in document order. Table numbers are never user-provided or hardcoded — position in the tree determines the number.
- **TOC sidebar**: should be generated from the serialized tree, not hardcoded HTML.
- **Figure/chart numbering**: same principle — position in tree determines number.

**The user's only editorial input is narrative content.** Everything structural (headings, table numbers, section ordering, footnote lettering) is determined by the tree and the data.

When adding a new section or table type:
1. Add a `DocNode` to the tree in `document_tree.py`
2. The Typst template, preview filter, table numbering, and TOC all pick it up automatically
3. Do NOT add hardcoded `if platform == "..."` checks in the template or filter

## UI State Management Architecture

The **AppStore** (`web/js/app_store.js`) is the single source of truth for all UI state. State is organized into slices (pool, sections, genomics, export), each with a phase registry, a reducer, and a renderer.

**Rule: No code should directly manipulate pool workflow buttons, badges, or status indicators.** All UI state changes go through `AppStore.dispatch('slice.verb', payload)`. The renderer subscribes to state changes and applies DOM updates atomically.

### Pool workflow state machine (`web/js/pool_state.js`)

The pool workflow progresses linearly. Each phase defines the exact enabled/disabled/visible state of every control:

```
EMPTY → UPLOADED → VALIDATING → VALIDATED → INTEGRATING → INTEGRATED → APPROVING → APPROVED
```

Each step unlocks exactly the next step — no skipping ahead:
- **EMPTY**: all buttons visible but disabled (visual workflow cue)
- **UPLOADED**: only Validate is enabled
- **VALIDATED**: only Integrate is enabled (Re-validate is NOT active — user just validated)
- **INTEGRATED**: Re-validate and Approve are enabled (user previews data, decides)
- **APPROVED**: all locked except Reset Pool

The `POOL_PHASES` registry in `pool_state.js` is the authoritative definition. When adding a new button or badge to the pool workflow:
1. Add its element ID to every phase in `POOL_PHASES`
2. The renderer applies it automatically
3. Do NOT add `getElementById` + `show/hide/disabled` calls in validation.js, pipeline.js, or upload.js

### Migration status

- **Phase 1 (pool slice)**: implemented — pool workflow buttons driven by `AppStore.dispatch('pool.transition', phase)`
- **Phase 2 (section approval slice)**: not started — will replace `backgroundApproved`, `methodsApproved`, etc. booleans and `setButtons()` calls
- **Phase 3 (visibility slice)**: not started — will replace Alpine `$store.app.ready.*` flags with store-driven rendering
- **Phase 4 (lifecycle slice)**: not started — will replace scattered card creation/destruction with state-driven renderers

Until Phases 2–4 are complete, some Alpine `ready.*` flag manipulation remains as bridge code (marked with `// Phase N` comments). Do not add new `ready.*` toggles — file an issue for the relevant phase instead.

## Table Business Rules (Tables 2-7)

### Row inclusion
- **All endpoints appear** in every table, not just responsive ones. The NTP statistical gate does NOT control row inclusion — it controls significance markers and the `responsive` flag only.
- Body Weight: all study days (SD0, SD5) always appear.
- Organ Weight: all organs in the data appear, each with Absolute (g) and Relative (mg/g) rows. Terminal Body Weight is a context row.
- Clinical Chemistry, Hematology, Hormones: all measured endpoints appear for both sexes.
- Tissue Concentration: all timepoints for Biosampling Animals only (no NTP stats, no BMD columns).
- Clinical Observations: incidence table (separate builder, categorical data).

### NTP statistical gatekeeper (`responsive` flag)
Two tests must BOTH pass for an endpoint to be marked responsive:
1. **Jonckheere trend test** — significant monotonic dose-response trend (p ≤ 0.01)
2. **Dunnett pairwise test** — at least one dose group significantly different from control (p ≤ 0.05)

The `responsive` flag controls:
- Significance markers (`*` p ≤ 0.05, `**` p ≤ 0.01) on dose group cells
- Direction (UP/DOWN) reported in the BMD summary
- LOEL/NOEL determination

The `responsive` flag does NOT control:
- Whether the endpoint row appears in the table (always yes)
- BMD/BMDL column values (independent — comes from .bm2 modeling)

### BMD/BMDL column values (from integrated .bm2 bMDResult)
BMDExpress 3 runs its own prefilter and dose-response modeling independently of NTP stats. The `bmd_str`/`bmdl_str` on each TableRow is populated from the integrated .bm2's `bMDResult` array via `_classify_bmd_result()`:

| Classification | BMD column | BMDL column | Trigger |
|---------------|-----------|------------|---------|
| `viable` | Numeric value | Numeric value | Model succeeded, passed all quality checks |
| `NVM` | "NVM" | "NVM" | Nonviable model — fit failed or r² < 0.1 |
| `NR` | "<LNZD/3" | "—" | Not reportable — BMD below 1/3 lowest nonzero dose |
| `UREP` | "UREP" | "UREP" | Unreliable estimate — BMDU/BMDL ratio > 40 or step function |
| `failure` | "NVM" | "NVM" | Model did not complete |
| `None` | "—" | "—" | Endpoint not modeled by BMDExpress 3 |

### N-row
- Shows Core Animals count per dose group (from sidecar, excludes Biosampling Animals).
- BMD/BMDL = "NA" (not applicable — sample size is not a dose-response endpoint).
- Dose groups where all animals died show "–" with attrition footnote marker.

### Footnotes (standard set for Tables 2-7)
- **BMD definition** (unnumbered paragraph above lettered footnotes): BMD₁Std and BMDL₁Std definitions, NA/ND legend.
- **(a)** Data format: "Data are displayed as mean ± standard error of the mean" + unit-specific text.
- **(b)** Statistical method: "Statistical analysis performed by the Jonckheere (trend) and Williams or Dunnett (pairwise) tests."
- **(c, d, ...)** Animal attrition notes (dynamically generated from sidecar terminal flags).

## Master TODO

### CRITICAL

- [ ] **Domain model refactor: end-to-end testing** — The provider/platform/dataType refactor (replacing monolithic domain strings) is committed but NOT validated. Test the full pipeline:
  1. Upload → validate → confirm metadata → integrate → process flow
  2. Integrated data tree: verify both tox_study AND inferred experiments appear as doseResponseExperiments
  3. NTP stats (build_table_data): verify stats computed correctly from tox_study experiments
  4. BMD values: verify BMD/BMDL from inferred .bm2 files attach correctly
  5. Section cards: verify one card per platform with merged tox_study + inferred data
  6. Clinical observations: verify categorical data handled correctly (not pivoted, own section)
  7. Gene expression: verify genomics pipeline still works
  8. DOCX/PDF export: verify reports render with new platform labels
  9. Session restore: verify saved sessions load correctly with new fingerprint format

### HIGH

- [ ] **xlsx as source of truth (unified feature)** — Three interconnected customer action items (#2, #5, #6) merged into one feature. xlsx = source of truth for animal roster, dose assignments, missing animals. bm2 = source of truth for BMD/BMDL modeling. txt/csv = derived intermediates. Includes study file detection by internal sheet structure and footnotes for animals that didn't survive to terminal sacrifice.
- [ ] **Split process-integrated cache into per-section units** — The monolithic `_processed_cache_{hash}.json` forces a full 10+ minute recompute (mostly BMDS modeling) when anything changes. Split into: NTP stats per platform (~5s), section cards per platform (<1s), BMDS modeling per endpoint (~8min total, the bottleneck), genomics extraction (~10s), BMD summary (<1s). Each unit has its own invalidation key so changing a narrative or footnote only rebuilds the affected section card, not the entire pipeline. BMDS only reruns when actual dose-response data changes.
- [ ] **Progress updates in processing spinner** — The "Processing integrated data..." spinner gives no indication of what's happening during the 10+ minute computation. Stream progress updates to the UI via SSE or polling: "Running NTP stats...", "Building section cards...", "BMDS modeling (endpoint 3/47)...", "Extracting genomics...", "Building BMD summary...". The per-section cache split (above) would make this natural since each cache unit is a discrete step.
- [ ] **Verify pairwise statistics vs reference report** — Spot-checking showed some values match (T3, T4 hormones) but need thorough comparison across all endpoints against reference report.

### MEDIUM

- [ ] **experimentDescription null for genomic data** — When the integrated data object is created, `experimentDescription` is null for genomic/gene expression experiments. The LLM metadata inference pipeline (`experiment_metadata.py`) should populate these but genomic experiments end up with all-null fields. May be a bug in `infer_experiment_metadata()` or in how genomic experiment signals are gathered/matched.
- [ ] **Decouple background generation from data analysis tabs** — Apical and genomics tabs should be independently accessible once pool is approved, without requiring background section generation/approval first. Pool approval + metadata approval should be sufficient to unlock data processing tabs.
- [ ] **Rework Data tab UX** — The current Data tab workflow (upload → validate → confirm metadata → integrate → process) is cryptic and hard to follow. Needs a clearer step-by-step flow with better status indicators, progress feedback, and guidance for new users.
- [ ] **Process-integrated performance and UX** — Processing takes 10+ minutes (pybmds fitting ~15 models per endpoint). Needs: (1) progress feedback in the spinner showing current step (NTP stats → section cards → BMDS modeling → genomics), (2) ability to cancel/abort processing, (3) don't auto-process on page reload if cache exists, (4) optional email notification on completion, (5) nuclear reset should be possible even while processing is in progress.
- [ ] **Typst template fidelity** — Typst-generated reports don't yet match NIEHS reference layout (Bookshelf_NBK589955.pdf, InDesign-produced). Use `diff_tables.py` for cell-level comparison and `pdf_text/` parser for detailed font/position metadata.
- [ ] **Move generate_results_narrative out of bmdx-pipe** — Narrative generation is presentation logic (report writing), not data processing. It belongs in rlm-bmdx (the web app), not bmdx-pipe (the pipeline library). The template-based approach also produces generic boilerplate — consider LLM-generated narratives that read more like scientist-written prose.

### LONG-TERM

- [ ] **BMDExpress 3 domain-agnostic refactor** — 8-phase plan to make bmdx-core a domain-agnostic dose-response framework. Phases: (1) terminology aliasing, (2) domain identity fields, (3) domain config schema, (4) import generalization, (5) prefilter/model gating, (6) annotation/grouping abstraction, (7) reference ranges, (8) new domain rollout. Repo: ~/Dev/Projects/BMDExpress-3, branch bmdx-core. Full plan in memory: `bmdx-domain-agnostic-plan.md`.
