# 0017 — Content/provenance-based data classification (the xlsx is the anchor)

- **Status:** Proposed (2026-09-08). Motivates and is scoped alongside the
  bmdx-pipe seam re-cut (see `project_bmdx_pipe_seam`).
- **Deciders:** Dan Svoboda
- **Related:** [ADR-0013](0013-package-layout.md) (the concern-package layout this
  extends into bmdx-pipe); `project_bmdx_pipe_seam` (the "pipe" misnomer + poor
  seam this refactor addresses); `expertise_data_pipeline.md` (tier model, pivot
  loss, dataType vocabulary); the truth-vs-inferred model in
  `pipeline/bmd_project_schema.py:190` (Auerbach, Weekly Meeting 8).

## Context

A file's **dataType** (`tox_study` = raw source-of-truth data with gaps, vs
`inferred` = gap-filled for BMD Express modeling) is today decided by a
**filename regex** (`bmdx_pipe/file_integrator.py:76-127`): a file is `tox_study`
only if its name contains `_truth` / `_tox_study`, else `inferred`.

This is fragile and produced a real, observed bug. A NIEHS-native xlsx
(`C20022-01_Individual_Animal_Organ_Weight_Data.xlsx`) carries no `_truth` token,
so it is misclassified `inferred` — even though the xlsx is, by definition, the
raw study-team source of truth (`file_integrator.py:19` "xlsx — ground truth").
It is then compared, as an `inferred` file, against a genuinely-inferred pivoted
txt whose top dose groups (333/1000 mg/kg) are absent because all animals died —
and the dose-group cross-check (`_check_dose_groups`) raises a spurious **error**.
The check even has the RIGHT exemption (line 1799 skips comparison across
different dataTypes: "tox_study files are expected to have more dose groups than
inferred files") — but it never fires, because the misclassification makes both
files `inferred`.

Key facts that make a better model possible:
- The xlsx **self-identifies**. Its "Key to Column Labels" sheet is a data
  dictionary + study identity (study number `C20022-01`, study title, `TOX`,
  date) and defines every column's meaning (Concentration = "Dose in mg/kg",
  Selection = "Cohort assigned", per-endpoint descriptions). `fingerprint_xlsx`
  ALREADY reads this sheet — but does NOT use it for dataType (line 867 still
  calls the filename regex).
- Derived files (txt / csv / bm2) are **projections** of the xlsx. Their dataType
  is not intrinsic to their name — it is their **numerical relationship to the
  source-of-truth xlsx**.

## Decision (the application-model change)

**Classify by content + provenance, not by filename or extension.** The xlsx is
the ANCHOR; every other file's dataType is DERIVED from its relationship to it.

1. **The xlsx anchors itself.** An xlsx bearing the "Key to Column Labels"
   study-metadata is `tox_study` (raw study-team source of truth) — established
   from its own content, never its name. (Genomics xlsx / non-study spreadsheets
   are out of this anchor set.)
2. **A derived file's dataType is its relationship to the anchor**, verified by a
   precise numerical match on the applicable fields (animal ID × dose × endpoint
   value):
   - **`tox_study`** — values MATCH the anchor exactly (raw values preserved,
     gaps and all). It IS the truth, re-shaped.
   - **`inferred`** — values differ from the anchor in the CHARACTERISTIC
     gap-filling way (missing cells replaced by dose-group averages; dead-out
     high-dose groups dropped). It is provably a modeling projection.
   - **neither** — values differ in an UNEXPECTED way → a genuine data conflict
     (the real error the current check is trying to catch).
3. **Classification and cross-validation become ONE operation.** Today the
   classifier LABELS files (by name) and `_check_dose_groups` COMPARES them
   (by value), and they can disagree — that disagreement IS the bug. Under this
   model the comparison-to-anchor is BOTH the label and the check: a match →
   `tox_study`; an expected gap-fill difference → `inferred`; an unexpected
   difference → error. One source of truth, no contradiction.

## Consequences

- **The observed bug's ROOT is removed**, not patched: an xlsx cannot be
  mislabeled `inferred`, so the spurious dose-mismatch error cannot arise.
- **Satisfies the "neither prefix nor extension" goal** the maintainer set: the
  classifier already ignores extension; this removes the last filename dependency
  (the `_truth`/`_tox_study` token) for anchored pools.
- **Filename heuristic becomes a FALLBACK, not the rule.** When no xlsx anchor is
  present (txt/bm2-only pool), fall back to the current name heuristic and/or the
  user's Confirm-Metadata choice. This AUGMENTS, does not fully replace.
- **The truth-vs-inferred difference is finally represented as PURPOSEFUL** — an
  expected gap-fill relationship, not a warning and not an error. (This answers
  the maintainer's semantic point: the mismatch between a truth file and its
  inferred projection should read as intentional, because the model now KNOWS it
  is.)
- **This lands in `bmdx_pipe/file_integrator.py`** — the misnamed, mis-cut seam
  (`project_bmdx_pipe_seam`). Doing it here is the MOTIVATION to perform the broad
  seam re-cut: classification is domain/computation logic that belongs BELOW the
  seam (a real data-model library), cleanly separated from presentation.

## Caveats / open questions

- **Anchor required.** No xlsx ⇒ no numerical anchor; fall back gracefully.
- **Shape reconciliation.** The anchor "Data" sheet is long-format
  (row per animal×observation); txt is pivoted (endpoint×animal); bm2 is BMD
  output. The match is a numerical join on (animal ID, dose, endpoint) with
  tolerance for the EXPECTED differences (that tolerance IS the classifier).
  The sidecar already reconciles long↔pivot, so the machinery is precedented.
- **Tolerance definition.** "Characteristic gap-fill" must be defined precisely
  (dose-group-average substitution; dead-out dose drop) so `inferred` is
  provable, not merely "differs somehow".
- **Interim resolution stands.** Until built, the intended fix is Confirm
  Metadata: the user sets the xlsx dataType to `tox_study` (the wizard exposes
  the per-file dataType dropdown; `confirm_metadata_step` applies it). NOTE a
  known gap: xlsx corrections persist only in the fingerprint (no header line to
  stamp, unlike txt/csv) — verify the correction survives to Integrate and that
  validation re-runs so the error clears.

## Scope note

This is an **application-model** change (how the system KNOWS what a file is),
not merely a coding fix. It should be built as part of the bmdx-pipe seam re-cut,
not smuggled in as a point patch.
