# 0001 — `BMDProject` schema as a load-time validation barrier

- **Status:** Accepted (2026-05-11)
- **Deciders:** Dan Svoboda
- **Related:** [Architecture review of 2026-05-10](../architecture-review-2026-05-10.html), candidate #4

## Context

The seam between rlm-bmdx and bmdx-pipe is the most consequential interface
in the project: bmdx-pipe writes `integrated.json` ("BMDProject" format),
and every downstream concern in rlm-bmdx (table builders, narratives, BMDS
modeling, PDF rendering, session API endpoints) reads from it.

That interface is currently implicit. `integrated.json` is loaded as
`dict[str, Any]`. The shape of the contract lives in a Java class in
`bmdx-pipe`; rlm-bmdx has no runtime way to assert that what it just
loaded conforms to what it expects.

This caused a customer-facing bug on 2026-05-10: each apical platform
ended up with two experiments per sex (a legacy `{sex}_{platform}` and a
`{platform}_truth_{sex}` sibling), producing duplicate rows in three
clinical-pathology tables. The duplicates carried different mean/SE
values and a BMD column present on only one of the two copies. The bug
was fixed reactively in `pool_orchestrator.py` via
`_dedup_legacy_apical_experiments()`.

The dedup helper papered over a symptom. Nothing in rlm-bmdx caught the
two-experiments-per-(platform, sex) condition at load time, so the
customer-facing report shipped wrong for several days. The same class of
bug — schema drift, unexpected duplicates, missing fields, type changes
from upstream — will recur whenever bmdx-pipe evolves.

The Architecture Review of 2026-05-10 identified this as candidate #4
("BMDProject schema — no schema at the rlm-bmdx ↔ bmdx-pipe seam"). It is
one of three cross-cutting candidates flagged in that review.

## Decision

Introduce a Pydantic `BMDProject` model that validates `integrated.json`
at load time. The model is a **load barrier**, not a typed-interface
migration: it gates loading and catches drift, but downstream consumers
continue reading dicts. A future migration may convert consumers to use
the typed model.

### Scope of validation

- **Strict validation on the consumed surface.** rlm-bmdx reads
  `DoseResponseExperiment.{name, treatments, probeResponses}`,
  `ExperimentDescription.{platform, provider, sex, organ, studyDuration,
  testArticle, dataType, ...}`, and the rlm-bmdx-owned `_meta.{source_files,
  xlsx_rosters, clinical_obs_files, dtxsid, integrated_at}`. These are
  modeled with explicit field declarations and types.

- **Lossless preservation of unread fields.** Every Pydantic class sets
  `model_config = ConfigDict(extra="allow")`. The Java-side result lists
  (`williamsTrendResults`, `curveFitPrefilterResults`, `bMDResult`,
  `categoryAnalysisResults`, `oriogenResults`) and any other unread struct
  pass through as `model_extra`, available for future consumers and
  preserved on round-trip serialization.

  This honors the project stance: *the consumed surface is "point of
  sale"; any data in the file pool is fair game for the future.* We
  validate what we use without committing to track every field bmdx-pipe
  emits.

### Per-field strictness

- `sex` → `Literal["male", "female"]` (closed set, two values).
- `_meta.source_files[*].tier` → `Literal["bm2", "txt_csv"]` (closed set).
- `platform`, `provider`, `dataType` → plain `str` (or `Optional[str]`
  for `dataType` until the domain-model refactor is fully wired). These
  value sets are intentionally open and grow over time; locking them with
  `Literal` would force the model to be updated each time bmdx-pipe
  introduces a new value.

### No domain invariants in this commit

The model validates shape and types only. Invariants like
"`(experimentDescription.platform, sex)` is unique across
`doseResponseExperiments`" are deferred to a follow-up commit. They are
additive — a `model_validator` decorator can be added without affecting
existing validation — and they require a separate conversation about
whether the orchestrator's dedup helper should be removed in favor of the
invariant or whether dedup should run before validation. That
conversation is not in scope here.

### Failure mode

- Hard-fail on validation error: raise `BMDProjectValidationError`
  (a subclass of `ValueError` that wraps `pydantic.ValidationError`).
- FastAPI endpoints that load `integrated.json` catch the exception and
  translate it to a structured HTTP error for the UI.
- Background processing propagates the exception (loud failures during
  development).

A feature-flagged "log violations for N days, then flip to hard-fail"
period was considered and rejected. The two-state code adds complexity,
and the deprecation cleanup is easy to forget. Instead, we mitigate
production risk by **pre-validating every existing `integrated.json`** on
disk against the new model before the commit lands. Sessions that fail
get triaged: either the model is adjusted, or the data is fixed. No
session is allowed to be broken on day one.

### Integration point and signature

- This commit modifies `_load_integrated()` only. It constructs the
  Pydantic model internally, validates, calls `.model_dump()`, and
  returns the dict. **The function signature does not change.** Every
  current caller keeps working unchanged.

- Three direct readers (`export_routes.py:298`, `llm_routes.py:258`,
  `session_routes.py:1272`) and one writer (`session_routes.py:1352`)
  bypass `_load_integrated()` today. These remain unchanged in this
  commit and are migrated in follow-ups.

### File location

The model lives in a new file `bmd_project_schema.py` at the repo root,
mirroring the project's flat module layout. It can be imported by any
caller without circular-dependency risk (no rlm-bmdx-specific imports
inside the schema file).

### Tests

- One golden fixture: a real `integrated.json` from a known-good session.
- Negative cases: missing required field, wrong type on a required field,
  invalid value on a `Literal` field, lossless round-trip of an unread
  field via `extra="allow"`.
- A standalone `validate_all_sessions.py` script (not committed) that
  walks `sessions/*/integrated.json` and reports failures. Its results
  are included in the PR description and discarded after migration.

## Commit sequence

This ADR governs only the first commit. The full migration sequence:

1. **(this commit)** Model + `_load_integrated()` validation + pre-validation.
2. Refactor the three bypass readers to use `_load_integrated()`.
3. Add a typed `save_integrated(model: BMDProject)` helper used by the
   metadata-edit write path in `session_routes.py:1352`. Closes the
   read+write seam end-to-end.
4. Add the `(platform, sex)` uniqueness invariant as a `model_validator`.
   At this point, evaluate whether `_dedup_legacy_apical_experiments()`
   can be removed (with the invariant moved upstream into the integration
   step) or whether the orchestrator continues to run dedup before
   validation.

Each step is independently landable and validatable.

## Consequences

### Positive

- **Schema drift is caught at the seam.** Upstream changes from bmdx-pipe
  that affect the consumed surface fail loudly at load instead of
  surfacing as confusing downstream errors.
- **A typed model exists** for future migration of consumers to typed
  access without re-deriving the contract.
- **Lossless preservation** of unread fields means rlm-bmdx can adopt new
  bmdx-pipe fields by reading them later, without re-ingesting files.
- **Pre-validation** removes the "one bad session locks the user out"
  risk on day one.
- **Pydantic is already a transitive dependency** via FastAPI; no new
  dependency cost.

### Negative

- **A new chokepoint** must be maintained as bmdx-pipe evolves. New
  fields we want to consume require updating the model; until then, they
  pass through unmodeled (acceptable, per the preservation stance).
- **Per-field choices embed durable assumptions.** Declaring
  `sex: Literal["male", "female"]` means a future "Unknown" / "Other"
  value would require both a code change and a discussion. This is
  appropriate for closed-set fields but is worth flagging.
- **The barrier is partial in this commit.** Three bypass readers and
  one writer continue to use dicts. Follow-up commits close those gaps;
  in the meantime, the validation gates `_load_integrated()` only.
- **The orchestrator dedup helper (`_dedup_legacy_apical_experiments`)
  remains.** Removing it depends on the (platform, sex) invariant being
  added in commit 4 of the sequence, plus a decision about whether to
  push dedup upstream into bmdx-pipe or keep it in rlm-bmdx.

## Alternatives considered

- **(B) Typed interface for downstream consumers.** Change
  `_load_integrated()` to return `BMDProject` and migrate every consumer.
  Rejected for this commit on size grounds: the architecture review
  flagged the cautionary precedent that an earlier domain-model refactor
  was committed but not validated end-to-end. The load barrier is the
  smaller, validatable unit; conversion of consumers is an independent
  workstream.

- **(C) Documentation-only types.** Define the model as type hints
  without runtime validation. Rejected: doesn't catch production drift,
  defeats the purpose of identifying the seam.

- **(i) Strict on consumed surface, drop unread fields.** Rejected:
  conflicts with the "file pool is fair game" stance. Dropping fields
  loses information that future features may consume.

- **(ii) Full Java domain mirror.** Model every field of every Java
  struct including the result lists. Rejected: over-couples rlm-bmdx's
  refactor velocity to bmdx-pipe's evolution rate for fields we don't
  read.

- **Feature-flag transitional period for failure mode.** Rejected: the
  two-state code is harder to reason about than a pre-validation pass
  against existing sessions.
