# bmdx-pipe seam re-cut — scope

Status: **DONE (2026-09-09).** The seam objective — data-model/compute vs.
presentation, cut cleanly — is achieved. Increments **A1a** (retire the duplicated
per-platform narrative; presentation off the library), **C1** (delete the docx
emitters + CLI → library is data-only), and **D** (content-anchored dataType
classifier, ADR-0017) all shipped and verified (see the per-increment "DONE"
sections below). **B** (rename `bmdx_pipe`) was deliberately NOT done — downgraded
to "keep the name": once A1a+C1 removed the presentation, what remains IS a data
pipeline, and if it ever drives BMD Express runs "pipe" becomes literally accurate
(maintainer decision). No open increments remain; the D-semantics "open question"
(relax the value guard?) was resolved during the build — D classifies on dose-group
DROP (a roster fact), so the value guard's block behavior stays as-is.

Original scoping below (2026-09-08). The broad refactor motivated by ADR-0017 and
the misnomer/mis-cut finding (`project_bmdx_pipe_seam`). Executed as ordered,
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

★★ A1 EXECUTION FINDING (2026-09-08, verified empirically) — BYTE-IDENTICAL IS
IMPOSSIBLE. Ran both on the same input: the bmdx-pipe twin and the app's builders
produce GENUINELY DIFFERENT prose, not the same text reshaped:
  * Table numbers: twin DYNAMIC (`start_table_num` → Table 1/2); app HARDCODED
    (Table 2/3).
  * Organ-weight sentence STRUCTURE differs: twin "In {sex} rats at study
    termination (Table N), Liver absolute weight was significantly decreased at
    ≥50... The BMD and BMDL were X and Y (absolute weight)"; app "In {sex} rats at
    study termination, a significant decrease in Liver absolute weight occurred in
    dose groups ≥50...; these endpoints had negative trends (Table 3). The BMD
    (BMDL) was X (Y) (absolute weight)."  Different clause order, different BMD
    format ("BMD and BMDL were X and Y" vs "BMD (BMDL) was X (Y)").
The app's unified_narrative was written to the NIEHS REFERENCE-REPORT structure;
the bmdx-pipe twin follows the older PFHxSAm-prototype structure. They are two
DIFFERENT generators, not a duplication to dedupe by swap. So retiring the twin
CHANGES the bm2-card prose — a real, visible content change, not a no-op.
→ REVISED A1 sub-fork (needs sign-off):
  (A1a) ACCEPT the prose change: repoint callers to the app builders; the bm2 cards
        now render the NIEHS-structured prose (the SAME structure the report already
        uses — arguably MORE consistent). Update golden/characterization expectations
        to the new text. This is the true dedup: one generator, NIEHS structure
        everywhere. Table-number handling must be reconciled (cards may need a
        per-platform table-num param, or accept the hardcoded refs).
  (A1b) PRESERVE current bm2-card prose: MOVE generate_results_narrative from
        bmdx-pipe INTO the app (narrative/) unchanged, delete it from bmdx-pipe.
        Still removes the CROSS-SEAM leak (presentation leaves the lib) WITHOUT
        changing any output — the safe move. Leaves TWO app-side generators
        (prototype + NIEHS) to reconcile later. Byte-identical by construction.
  → DIRECTOR LEAN: A1b — it achieves the seam goal (presentation off the lib) with
    ZERO behavior change, and defers the harder "which prose structure wins" product
    decision. A1a is the fuller cleanup but is a genuine content change the user
    should choose deliberately, not as a refactor side effect.
- Net: removes THE cross-seam duplication AND unblocks Phase-3b (editable card gets
  typed slots) in one move.
- ★ NEEDS MAINTAINER SIGN-OFF: A1 vs A2 before executing (A1 touches 6 call sites +
  editable-card behavior).

### Increment B — name the seam for what it is (the misnomer). ★ RECONSIDERED — likely KEEP `bmdx_pipe` (2026-09-08).
Original premise: "pipe" is a misnomer because the library exports domain TYPES,
not a dataflow. But after A1a + C1 removed ALL presentation, what remains IS a
data-processing pipeline: uploaded files → fingerprint/classify → pivot → BMD
Express input → Java curve-fit (.bm2) → data-model out. Maintainer point
(2026-09-08): "bmdx-pipe might yet be a good name. if we decide to run bmd express
calculations at some point, it could actually be a pipe." AGREED — the misnomer
finding was really "it leaks presentation" (now FIXED by A1a+C1). If the library
later drives BMD Express runs, "pipe" becomes literally accurate. So B is
DOWNGRADED from "do it" to "keep the name; revisit only if it stops being a
pipe." A rename is trivially safe later (import-graph guard + suite) if ever
wanted — no reason to force it now.

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

★ SCOPING FINDING (2026-09-08) — the numerical anchor-match machinery ALREADY
LARGELY EXISTS. `pipeline/value_validation.py` (rlm-bmdx side) +
`bmdx_pipe.extract_xlsx_value_map` already do the hard part ADR-0017 D needs:
per-animal value extraction from the xlsx anchor keyed (sex, animal_id, endpoint,
day), reduced to the SAME shape as the derived CSV sidecar, with float-aware
equality, run from `validate_step`. So the "numerical join to the anchor with
tolerance" is BUILT — but wired as a pure GUARD (any divergence → blocking
`value_*` error), NOT as a CLASSIFIER. The gap between what exists and ADR-0017 D:
  1. It's a GUARD, not a LABELER. It flags divergences; it does NOT set
     `fp.data_type` from the match result. ADR-0017's core claim — "classification
     and cross-validation become ONE operation" — means the match OUTCOME should
     DERIVE the dataType (exact→tox_study / characteristic gap-fill→inferred /
     unexpected→error), not just error on any difference.
  2. It has NO "characteristic gap-fill" tolerance. Right now ANY value difference
     (including the legitimate dose-group-average gap-fill of an `inferred` file)
     is a blocking error. ADR-0017 D needs the classifier to RECOGNIZE the gap-fill
     pattern (missing cell → dose-group mean; dead-out high dose dropped) and label
     it `inferred` rather than error. This tolerance IS the unbuilt piece.
  3. It only compares xlsx↔CSV-sidecar. bm2 (the 3rd tier) is not value-matched to
     the anchor (bm2 is BMD output, a different numerical relationship).
  4. Increment 1 (committed `7b4e749`) already anchors the XLSX ITSELF
     (is_study_file → tox_study). D is about the DERIVED files' labels.
REVISED D SCOPE (much smaller than first thought): D is NOT "build value-matching
from scratch." It is "promote the existing value-match from guard to classifier +
add the gap-fill tolerance." Concretely: (a) a `classify_derived_by_anchor()` that
runs the existing value-map compare and returns tox_study | inferred | conflict
per (platform, file) from the match SHAPE; (b) define the gap-fill tolerance
precisely (dose-group-mean substitution; dead-out dose drop) so `inferred` is
provable; (c) have the classifier SET data_type so `_check_dose_consistency`'s
cross-datatype exemption engages correctly (closing the loop with increment 1);
(d) keep the current guard behavior for the "unexpected difference" case (it's
already the right error). The filename regex stays only as the no-anchor FALLBACK.
- OPEN QUESTION for D: does the value guard's current "any difference blocks"
  behavior get RELAXED (a gap-fill difference becomes a LABEL, not an error)? That
  is a real semantics change to a shipping check — needs the maintainer's explicit
  OK, because it changes when a session is publish-blocked. This is the crux
  decision of D, not a mechanical port.

★★ CHARACTERIZATION DONE (2026-09-08) — MEASURED. Pinned in
`tests/integration/test_inferred_anchor_characterization.py` (5 green). Initial
draft OVERCLAIMED "gap-fill doesn't happen"; maintainer corrected ("there *is*
inferred data *somewhere*") and it was RIGHT. Corrected finding: there are TWO
DISTINCT inference mechanisms and PFHxSAm only visibly shows one.
  1. CURRENT STATE clean: 0 dose_mismatch, 0 value-provenance issues (increment 1
     holds). The 26 remaining structural issues are roster_subset/missing_tier/
     animal_count_mismatch — UNRELATED to dataType.
  2. ★ MECHANISM (1) — DOSE-GROUP DROP (what PFHxSAm shows at the pivot-TXT layer):
     a whole/partial dead-out dose group is REMOVED (333/1000 mg/kg, all died; also
     a partial drop at 0.15 in hematology). Surviving-animal cells BYTE-IDENTICAL to
     truth (Body/Organ/Hormone: 0 mismatch, 0 fill). For THIS mechanism the
     discriminator is the ROSTER — overlapping cells match EXACTLY, so "exact value
     match → tox_study" MISLABELS a dropped-dose inferred file.
  3. ★ MECHANISM (2) — CELL IMPUTATION (ADR-0017's "dose-group-average
     substitution", and it IS REAL): an INDIVIDUAL missing cell (dead animal / lost
     sample inside a SURVIVING dose group) is filled with the dose-group mean so
     BMDExpress can curve-fit. Lives in the legacy/inferred BMDExpress upload →
     .bm2 → footnoted in the report ("N missing individual values were imputed…",
     `tables/clinical_pathology_table.py`). DETECTED by `_detect_imputed_cells`
     (`pipeline/bmd_project_schema.py`), PINNED in
     `tests/unit/test_bmd_project_schema.py::test_imputed_cell_recorded` (truth
     [50, None, 60] → legacy [50, 55, 60]). PFHxSAm's reference PDF has NO
     imputation footnote → this fixture is DROP-DOMINANT and does not exercise (2)
     visibly; but (2) is live, shipped code. For THIS mechanism the VALUE is the
     signal (truth-missing/legacy-present), the exact opposite of mechanism (1).
  4. clin_chem & hematology truth txt use DAY-TAG rows ('SD5') vs inferred
     analyte-name rows → txt↔txt not cell-comparable; only the xlsx anchor is a
     common reference there. (Pinned.)
→ CORRECTED D DESIGN CONSEQUENCE: a value-only OR roster-only classifier is
  insufficient — D must handle BOTH mechanisms across TWO tiers:
    • TXT tier (xlsx anchor ↔ pivot txt): key on ROSTER relationship. full roster +
      matching cells → tox_study; dropped dose groups + matching surviving cells →
      inferred (dead-out drop); differing surviving cells → conflict/error.
    • BM2 tier (truth ↔ legacy experiment pair): key on CELL imputation — ALREADY
      BUILT as `_detect_imputed_cells` (truth-missing/legacy-present → imputed).
  So D is "unify the roster-classifier (new, txt tier) with the existing
  imputation-detector (bm2 tier) into one dataType-deriving operation", not "add a
  gap-fill tolerance from scratch." The gap-fill IS real (mechanism 2) — my earlier
  "non-issue" call was WRONG; it's just detected at a different tier than the txt
  layer I first measured. OPEN for maintainer: whether the value-guard's "any
  surviving-cell difference blocks" should stay as-is (mechanism-1 drops don't trip
  it — they're roster facts) — likely YES, no relax needed, but confirm.

## ★ VERIFICATION BAR — the load-bearing principle (maintainer, 2026-09-08)

Do NOT gate byte-identical on prose (esp. AI-regenerated/templated narrative — a
byte bar freezes old wording as if it were a contract, which is nonsense). DO gate
byte-identical on everything DATA-DERIVED. The dividing test:

  **"Could this differ between two correct runs on the SAME input data?"**
  No → data-derived → DETERMINISTIC, byte-identical required (a change = regression
       unless input changed).
  Yes → authored/descriptive → gate COHERENCE (cites right numbers/direction), not
       the string.

| DETERMINISTIC (byte-gate) | AUTHORED (coherence-gate, NO byte bar) |
|---|---|
| table cell values, BMD/BMDL, dose groups, N counts | narrative prose (body-weight/organ findings) |
| significance markers (*/**), NVM/NR/UREP codes | genomics interpretation |
| **footnotes** (attrition notes from sidecar terminal | any LLM-regenerated text |
|  flags; NA/ND legends; the `–` dead-out marker), | |
|  captions, table/figure NUMBERS, cross-references | |

★ FOOTNOTES ARE DETERMINISTIC — they look like text but are DATA-DERIVED (memory
`expertise_ntp_statistics.md`: footnote scheme (a)/(b) boilerplate, (c,d,…)
dynamically generated from sidecar terminal flags; `–`+attrition marker keyed to
which dose groups died). A footnote changes ONLY if the data changed → byte-gate.
Same for captions, table numbers, cross-refs.

Consequence for THIS re-cut: Increment A moves PROSE (coherence bar, prose may
change to NIEHS structure — accepted). Increment C moves the docx TABLE EMITTERS,
which carry footnotes/captions/numbering → byte-gate those (compare document.xml,
never zip). Two different bars travelling in the same refactor; keep them straight.

## Cross-cutting rules
- Every increment: independently committable, characterization net green before
  AND after, rlm-bmdx goldens green. The import-graph guard
  (`test_workflow_import_isolation`) stays green (workflow never imports the lib
  presentation).
- bmdx-pipe pre-existing uncommitted drift (`java_bridge.py`, .class files) is
  UNRELATED — leave untouched, never stage.
- The Java `bmdx-core` engine evaluation is a SEPARATE track (different layer) —
  don't entangle it with this Python-seam re-cut.

## ★ INCREMENT A1a DONE (2026-09-08) — director-run agent, verified
Committed: bmdx-pipe `47fc10c` (delete twin + 6 unused helpers, −428 lines),
rlm-bmdx `c13f6ab` (new `generate_platform_narrative` entry + 6 callers repointed +
conftest mock). Presentation (per-platform narrative) has LEFT the library — the
core seam objective for this increment. VERIFIED (not just agent report): goldens
byte-UNCHANGED (data determinism held — stash-tested); auto-detect fallback builders
self-filter with NO cross-leakage on mixed bm2 cards (the one real design risk,
checked directly); twin+helpers grep-confirmed unused before delete; the 2 full-suite
failures (latex_export real-session, docx caption interpolation) reproduce on the
PRISTINE tree → pre-existing, unrelated. 40 targeted + 10 bmdx-pipe tests green.
Pre-existing bmdx-pipe `java_bridge.py` drift left untouched/unstaged.
- ★ ACCEPTED behavior change: bm2-card prose now renders NIEHS structure (was the
  old PFHxSAm-prototype wording). Per the verification bar this is fine (prose,
  coherence-gated). A human should eyeball the bm2 cards in the browser once.
- CAVEAT (upload_routes L249/L753): the bm2 preview path has no clean platform
  string → passes None → row-type auto-detect. Tested, works; noted as the visible
  content-change surface.

## ★ INCREMENT C1 DONE (2026-09-08) — director-executed (deletes warrant direct care)
Committed: bmdx-pipe `94ce94c` (−1240 lines). Deleted ALL docx emitters (add_*_to_doc
×6), generate_report/generate_section_from_bm2, the __main__ CLI, module-level
docx/argparse imports, unused docx helpers, + __init__ exports from apical_report/
animal_report/clinical_observations. bmdx-pipe is now DATA-ONLY (no module imports
docx). User chose C1 (delete, not keep the standalone CLI) — bmdx-pipe is a pure
rlm-bmdx dependency, not standalone-usable. VERIFIED: rlm-bmdx never imported any
emitter (grep-confirmed); goldens + docx path byte-unchanged (18 + 51 tests); the 1
docx caption-interpolation failure is PRE-EXISTING (reproduces pristine; app-side
rendering/ bug). DATA builders kept. NOTE re earlier scoping: the "presentation leaks
in apical_report" were MOSTLY bmdx-pipe's own CLINE presentation, NOT cross-seam
leaks — the only cross-seam leak was generate_results_narrative (A1a). So A1a+C1
together = the seam is fully presentation-free.
- SEQUENCING NOTE (confirmed): C before B was correct — B (rename) now renames a
  clean, presentation-free library.
- The pre-existing docx caption bug lives in rlm-bmdx rendering/ — candidate for a
  separate app-side fix, unrelated to the seam.

## ★ INCREMENT D DONE (2026-09-09) — content-anchored dataType classifier, wired
Committed: bmdx-pipe (classify_derived_by_anchor + validate_pool wiring + 6 tests).
`classify_derived_by_anchor(fingerprints)` runs at the TOP of `validate_pool`
(before the coverage matrix + `_check_dose_consistency`), fingerprint-only. Per
platform it compares each derived txt/csv's DOSE-GROUP SET to the study-xlsx
anchor's per-sex dose set:
  * a dose group the anchor HAS but the derived file ENTIRELY LACKS → PROVABLE LOSS
    → set data_type="inferred" (the dead-out-dose drop). This is what lets the dose
    check's cross-datatype exemption fire from a CONTENT-derived label.
  * same dose-group set as the anchor → AMBIGUOUS → KEEP PRIOR LABEL (maintainer
    decision — content can't separate a faithful tox_study reshape from a no-gap
    inferred pivot, e.g. Hormones/Clin-Chem where nothing died; never override a
    human Confirm on ambiguous data).
  * a dose the anchor lacks / no anchor for the platform → leave label, structural
    checks handle conflicts / filename stays the fallback.
★ KEY DESIGN CORRECTION found during build: the signal is DOSE-GROUP DROP, NOT
per-dose animal-count shrink. A tox_study MEASUREMENT file legitimately has FEWER
animals than the anchor's assigned CORE roster (only measured animals appear;
biosampling/unmeasured absent), so "fewer animals" would WRONGLY relabel truth
files (it did, in the first draft: clin_chem/hematology truth → inferred). Fixed to
compare dose SETS only.
VERIFIED: NO-OP on the golden pool (0 label changes — already correctly labeled);
the 4 provable_loss detections are exactly Body/Organ Weight male+female (333/1000
died out); counterfactual — a dropped-dose file mislabeled tox_study by a bad
filename is RECOVERED to inferred from content (the ADR-0017 goal); ambiguous files
never overridden either direction. 16 bmdx-pipe tests green; 209 rlm-bmdx
wired-path tests green (1 pre-existing failure: TestRealSessionIntegratedJson reads
a STALE live sessions/ integrated.json, reproduces identically with D stashed —
unrelated). Filename regex now only a FALLBACK when no anchor.
- SCOPE HONESTY: D is an AUGMENT, not a full filename replacement — matches the
  ADR's own "AUGMENTS, does not fully replace" line. Content can PROVE inferred
  (dropped dose) and FLAG conflict, but CANNOT prove tox_study for a no-loss file
  (genuinely ambiguous). The bm2-tier cell-imputation detector (_detect_imputed_cells)
  is unified BY REFERENCE (it already labels imputation one tier down) — D does not
  reimplement it.

## Recommended execution order: A → (confirm name) → B → C → D.  [A1a ✅, C1 ✅, D ✅; B → keep name]
Start with A (retire the duplicated narrative) — highest clarity, removes the
literal proof of the mis-cut, and unblocks Phase-3b in the same move.
