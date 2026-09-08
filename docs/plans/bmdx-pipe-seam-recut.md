# bmdx-pipe seam re-cut — scope

Status: SCOPING (2026-09-08). The broad refactor motivated by ADR-0017 and the
misnomer/mis-cut finding (`project_bmdx_pipe_seam`). Executed as ordered,
independently-committable increments behind the characterization net
(`bmdx-pipe/tests/test_classification_characterization.py`, and the rlm-bmdx
integration/golden suites).

## The problem being fixed (recap)

`bmdx-pipe` is misnamed ("pipe" implies dataflow) and mis-cut: it EXPORTS shared
domain types + a vocabulary, not flow stages, AND it carries PRESENTATION logic
that is duplicated app-side. The seam should be **DATA-MODEL + COMPUTATION vs.
PRESENTATION**, cut cleanly.

## What rlm-bmdx actually imports (the real contract — measured, not guessed)

| symbol | uses | concern |
|---|---|---|
| `TableRow` | 13 | **domain type** (the big coupling) |
| `bm2_cache` | 4 | compute/cache |
| `IncidenceRow` | 2 | domain type |
| `extract_xlsx_value_map` | 2 | data extract |
| `export_integrated_bm2` | 2 | Java-interop export |
| `generate_results_narrative` (`_gen_narr`) | 1 | ★ **PRESENTATION — duplicated app-side** |
| `tox_study_csv_to_pivot_txt` | 1 | data transform (the pivot) |
| `FileFingerprint`, `ValidationIssue`, `TIER_XLSX` | 1 ea | classification/validation |
| `VOCABULARIES` | 1 | domain vocabulary |
| `build_clinical_obs_tables` | 1 | table build |
| `file_integrator`, `clinical_observations` (modules) | 1 ea | direct module access |

Everything is data-model/compute EXCEPT `generate_results_narrative` — the one
clear presentation leak, and it's already DUPLICATED (the app's Phase-2 templated
`narrative/unified_narrative.py` is the newer twin).

## Module inventory (bmdx-pipe, by concern)

| module | lines | concern | verdict |
|---|---|---|---|
| `file_integrator.py` | 2338 | fingerprint, classify, cross-validate | **stays below** (data-model). ADR-0017 lives here. |
| `pool_integrator.py` | 1303 | tier select, merge → BMDProject, pivot | **stays below** (compute) |
| `apical_report.py` | 2396 | table build + `generate_results_narrative` + docx emit | **SPLIT** — tables/stats stay; narrative + docx-emit are presentation → app |
| `apical_stats.py` | 682 | NTP stats (Java prefilter) | **stays below** (compute) |
| `animal_report.py` | 1302 | per-animal roster + docx emit | mostly compute; docx-emit is presentation |
| `clinical_observations.py` | 455 | incidence tables + docx emit | mostly compute; docx-emit is presentation |
| `experiment_metadata.py` | 646 | vocab + LLM metadata inference | vocab stays; LLM-infer is arguable |
| `file`… `bm2_cache.py` `java_bridge.py` | small | cache + Java bridge | **stays below** (compute/interop) |

Pattern: the library is ~85% legitimately-below-the-seam (data model + Java
compute), with **presentation leaks concentrated in `apical_report.py`**
(`generate_results_narrative`, the `add_*_to_doc` docx emitters).

## Increments (ordered: lowest-risk / highest-clarity first)

### Increment A — retire the duplicated narrative (the smoking gun). ★ FIRST.
`generate_results_narrative` in `apical_report.py` is dead-twin presentation: the
app already has the templated `narrative/unified_narrative.py`.

★ SCOPING CORRECTION (2026-09-08, verified against code — the Phase-3b note
UNDERCOUNTED): there are **6+ callers**, not one — `process_integrated.py:772`,
`processing_helpers.py` (×4: 595/649/693/724), `upload_routes.py` (×2: 249/753) —
AND the two functions have DIFFERENT SHAPES:
  * `generate_results_narrative(table_data: {sex: [TableRow]}, ...)` — PER-PLATFORM,
    called in loops; one platform's data per call. Feeds the editable per-platform
    bm2 cards.
  * `generate_apical_narrative(platform_tables: {platform: {sex:[TableRow]}}, ...)` —
    CROSS-PLATFORM UNIFIED; the whole apical section in one call. Feeds the single
    report section.
So this is NOT a mechanical delete-and-repoint — the two serve different call
patterns (per-platform card vs unified section). Options:
  (A1) Extract the per-platform builders the app ALREADY has
       (`_build_body_weight_paragraphs` etc. in unified_narrative) into a
       per-platform entry the 6 callers can use, then delete the bmdx-pipe twin.
       The app's builders ARE per-platform internally — `generate_apical_narrative`
       just composes them — so a thin per-platform wrapper is low-risk and reuses
       the Phase-2 templated code.
  (A2) Leave the per-platform callers on the bmdx-pipe twin for now; only retire it
       once the editable-card path is templated (Phase-3b proper). Smaller now,
       defers the duplication removal.
- RECOMMEND A1: add a per-platform templated entry to `unified_narrative`, repoint
  the 6 callers, delete the bmdx-pipe twin. Gate: byte-diff each caller's narrative
  old-vs-new (the templated builders were proven byte-identical in Phase 2, so a
  per-platform wrapper should match), + app narrative characterization tests.
- Net: removes THE cross-seam duplication AND unblocks Phase-3b (editable card gets
  typed slots) in one move.
- ★ NEEDS MAINTAINER SIGN-OFF: A1 vs A2 before executing (A1 touches 6 call sites +
  editable-card behavior).

### Increment B — name the seam for what it is (the misnomer).
Rename the package to a data-model name (candidates: `bmdx_core` — but that name is
TAKEN by the Java BMDExpress-3 branch, so AVOID; use `bmdx_data` / `bmdx_domain` /
`toxdata`). Mechanical: `pyproject` name, import name, all `from bmdx_pipe import`
sites (13 modules). Do AFTER A so the thing being renamed no longer lies about its
contents. Pure rename = trivially safe behind the import-graph guard + full suite.
- OPEN: confirm the new name with the maintainer before executing.

### Increment C — move the docx emitters app-side.
The `add_*_to_doc` functions (`apical_report`, `animal_report`,
`clinical_observations`) are presentation (they build python-docx output). They
belong with the app's `rendering/` surfaces. Move them out; the library keeps
pure table/roster/incidence DATA builders. Larger, touches the docx render path —
gate with the docx render tests + byte-compare (never byte-compare zip; compare
document.xml, per the known lesson).

### Increment D — ADR-0017 later increments (content-anchored classification).
With the seam clean, build the derived-file-dataType-from-anchor model in
`file_integrator` (now clearly below the seam). Unify classification with
cross-validation. This is where the "data model" improvement fully lands.

## Cross-cutting rules
- Every increment: independently committable, characterization net green before
  AND after, rlm-bmdx goldens green. The import-graph guard
  (`test_workflow_import_isolation`) stays green (workflow never imports the lib
  presentation).
- bmdx-pipe pre-existing uncommitted drift (`java_bridge.py`, .class files) is
  UNRELATED — leave untouched, never stage.
- The Java `bmdx-core` engine evaluation is a SEPARATE track (different layer) —
  don't entangle it with this Python-seam re-cut.

## Recommended execution order: A → (confirm name) → B → C → D.
Start with A (retire the duplicated narrative) — highest clarity, removes the
literal proof of the mis-cut, and unblocks Phase-3b in the same move.
