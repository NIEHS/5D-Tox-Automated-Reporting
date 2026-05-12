"""
bmd_project_schema.py — Pydantic models that validate `integrated.json`.

PURPOSE OF THIS MODULE
======================

`integrated.json` is the canonical merged dataset produced by bmdx-pipe
(BMDExpress 3's "BMDProject" format augmented with rlm-bmdx's `_meta`
envelope).  Every downstream concern in rlm-bmdx — table builders,
narratives, BMDS modeling, PDF rendering, session-restore endpoints —
reads from this file.

The seam between rlm-bmdx and bmdx-pipe is the single most consequential
interface in the project, and until now it was implicit: `integrated.json`
was loaded as `dict[str, Any]`, and consumers had to know the field names,
nesting, types, and optionality by reading other consumers.  Schema drift
from bmdx-pipe — renamed fields, changed types, missing keys — surfaced
as confusing `KeyError`s deep inside table builders, often on customer
data, often days after the change shipped.

This module turns that implicit contract into a runtime-validated one.
It is a **load-time barrier**: when `_load_integrated()` reads
`integrated.json`, the contents are checked against the models defined
here before the data is handed to any consumer.  If validation fails,
load fails — loudly, with a typed exception — so the problem is caught
at the seam instead of leaking into a half-built report.

This was decided in `docs/adr/0001-bmdproject-schema-as-load-barrier.md`.
Read that ADR before changing the contract here.

WHAT IS VALIDATED VS WHAT IS PRESERVED
======================================

Two principles govern the model scope:

  1. **Strict validation on the consumed surface.**  The fields rlm-bmdx
     reads from `integrated.json` today are declared with explicit
     Python types.  Missing required fields, wrong types, or invalid
     `Literal` values cause validation to fail.

  2. **Lossless preservation of everything else.**  Every Pydantic class
     in this module sets `extra="allow"`, which tells Pydantic to keep
     unknown fields rather than discard them.  This honors the project
     stance that *any data already in the file pool is fair game for the
     future*: bmdx-pipe may emit fields rlm-bmdx doesn't read yet, and
     we never want to lose those.  They are accessible as
     `model.model_extra` and round-trip on serialization.

The Java-side result lists — `williamsTrendResults`,
`curveFitPrefilterResults`, `bMDResult`, `categoryAnalysisResults`,
`oriogenResults`, `oneWayANOVAResults` — are recomputed in rlm-bmdx via
`build_table_data()`, so we don't declare them.  They pass through as
`model_extra` on `BMDProject`.

PER-FIELD STRICTNESS
====================

Closed-set fields use `typing.Literal` to catch value drift:

  - `sex`: `Literal["male", "female"]` — only ever two values.
  - `source_files[*].tier`: `Literal["bm2", "txt_csv"]` — only two values.

Open-set fields use plain `str`:

  - `platform`, `provider`: legitimately grow over time as bmdx-pipe
    adds support for new file types.
  - `dataType`: the per-experiment field is currently always None in
    practice (the domain-model refactor is not fully wired through);
    using `Optional[str]` lets us land this commit without first
    finishing that refactor.

WHAT THIS MODULE INTENTIONALLY DOES NOT DO
==========================================

  - **No domain invariants.**  The model validates structural shape and
    types only.  Rules like "(experimentDescription.platform, sex) is
    unique across doseResponseExperiments" are deferred to a follow-up
    commit (see ADR commit-sequence step 4).

  - **No typed return from _load_integrated().**  After validation the
    model is dumped back to a plain dict; downstream consumers see no
    signature change.  Converting consumers to typed access is a
    separate workstream.

  - **No write-side helper.**  The metadata-edit code path in
    `session_routes.py` writes `integrated.json` directly today.
    Adding `save_integrated(model)` is commit-sequence step 3 in the
    ADR.

HOW DOWNSTREAM CODE USES THIS
=============================

Only `_load_integrated()` in `pool_orchestrator.py` calls into this
module today, via `load_and_validate()`.  Callers of `_load_integrated()`
need no changes: they keep receiving a `dict`.

When the schema is wrong about the data (a real session fails to load),
the error message from Pydantic is preserved inside
`BMDProjectValidationError`, which subclasses `ValueError` so existing
exception-handling in FastAPI endpoints catches it naturally.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
# Standard library only; Pydantic is already a transitive dependency via
# FastAPI (see uv.lock).  No new external dependency is introduced.

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Closed value sets used by `Literal` fields.  Centralized here so a
# follow-up that needs to expand a set (e.g. adding a new tier) has one
# obvious place to edit.

# The two valid `sex` values that bmdx-pipe emits in
# `experimentDescription.sex`.  Lowercase is the canonical form;
# downstream code (e.g. `_partition_by_platform`) capitalizes for display.
ALLOWED_SEX_VALUES = ("male", "female")

# The two valid `tier` values that rlm-bmdx writes into
# `_meta.source_files[*].tier`.  "bm2" means the BMDExpress 3 binary
# format; "txt_csv" covers the legacy text/CSV ingestion path.
ALLOWED_TIER_VALUES = ("bm2", "txt_csv")


# ---------------------------------------------------------------------------
# Exception type
# ---------------------------------------------------------------------------
# A dedicated exception lets callers distinguish "this integrated.json is
# malformed" from generic JSON / I/O errors.  It subclasses ValueError so
# that existing FastAPI exception handlers — which already translate
# ValueError to a 4xx response — work without modification.

class BMDProjectValidationError(ValueError):
    """
    Raised by `load_and_validate()` when `integrated.json` does not
    conform to the BMDProject schema defined in this module.

    The underlying `pydantic.ValidationError` is preserved on the
    `.pydantic_error` attribute so callers can inspect the per-field
    failure details if needed.
    """

    # Constructor: builds the human-readable message from the Pydantic
    # error, and stashes the original error for programmatic access.
    def __init__(self, source: str, pydantic_error: ValidationError) -> None:
        # `source` is a short description of where the data came from
        # (file path or session id) so the error message is actionable.
        self.source = source
        self.pydantic_error = pydantic_error
        # The Pydantic error's str() is verbose and structured; we
        # include it directly because it's the most useful diagnostic.
        super().__init__(
            f"integrated.json failed schema validation ({source}):\n"
            f"{pydantic_error}"
        )


# ---------------------------------------------------------------------------
# Shared base class
# ---------------------------------------------------------------------------
# Every model in this module inherits from `_BaseModel` instead of
# `pydantic.BaseModel` directly so the "preserve unknown fields"
# configuration is set in one place rather than repeated on every class.

class _BaseModel(BaseModel):
    """
    Project-wide Pydantic base.  Sets `extra="allow"` so any field that
    appears in the JSON but isn't declared on the subclass is preserved
    in `model_extra` rather than discarded.

    This is the mechanism that implements the "file pool is fair game"
    stance documented in ADR-0001: rlm-bmdx validates what it consumes
    today and keeps everything else available for tomorrow.
    """

    # Pydantic v2 configuration.  `extra="allow"` is the load-bearing
    # setting; everything else is conventional.
    model_config = ConfigDict(
        extra="allow",
        # `populate_by_name=True` lets us declare a model field under a
        # Python-friendly name while still accepting the JSON's original
        # key via the `alias=` parameter on each Field, if we ever need
        # it.  We don't use aliases today but the option is cheap to
        # have on.
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# Consumed-surface model classes
# ---------------------------------------------------------------------------
# These are the structures rlm-bmdx actually reads.  Anything not declared
# here passes through as `model_extra` on the nearest declared ancestor.
#
# Field order within each class mirrors the order keys appear in the JSON
# for readability when comparing the model against a real
# `integrated.json` file.

class Probe(_BaseModel):
    """
    A measurable entity within an experiment.  For apical experiments,
    `id` is the endpoint label (e.g. "Alanine aminotransferase").  For
    genomics, `id` is the probe identifier as it appears in the chip
    annotations.  Other Probe fields exist in the Java domain but are
    not read by rlm-bmdx.
    """

    # The probe identifier.  rlm-bmdx uses this to look up endpoint
    # labels and to match TableRows back to the experiment they came
    # from inside `_partition_by_platform`.
    id: str


class ProbeResponse(_BaseModel):
    """
    The numeric responses for one probe across all animals in one
    experiment.  `responses` is a flat list whose ordering matches the
    `treatments` list on the parent `DoseResponseExperiment`.  Missing
    values appear as `None` (typically because an animal was excluded
    by the Selection column in the truth file's sidecar).
    """

    # The Probe metadata; only `.id` is consumed downstream.
    probe: Probe

    # Numeric response values per animal.  Order parallels the parent
    # experiment's `treatments` list.  `None` entries are legitimate
    # — they represent animals excluded from analysis (Biosampling) or
    # data that was never collected for this probe.
    responses: list[Optional[float]]


class Treatment(_BaseModel):
    """
    One animal's exposure record within an experiment.  Each entry in
    `DoseResponseExperiment.treatments` is a single animal; the parallel
    `responses` list on each `ProbeResponse` carries the measured value
    for that animal at that probe.
    """

    # Human-readable label for this treatment — typically just the dose
    # group identifier rendered as a string (e.g. "111" for 111 mg/kg).
    name: str

    # The administered dose in mg/kg (or whatever unit is implicit in
    # the parent study).  May be 0.0 for the vehicle-control group.
    dose: float


class TestArticle(_BaseModel):
    """
    Identification of the chemical under study.  Carried inside every
    experiment's `experimentDescription`.  rlm-bmdx uses `dsstox` (the
    DTXSID) to look up the session, `name` for human-readable headings,
    and `casrn` for cross-references to external databases.
    """

    # Common name of the chemical.
    name: str

    # CAS Registry Number; not strictly required by every consumer but
    # historically always present.  Optional to be safe — a missing
    # CASRN should not block the load.
    casrn: Optional[str] = None

    # The EPA DSSTox substance ID (a.k.a. DTXSID); this is the primary
    # session key throughout rlm-bmdx.  Treated as required because
    # without it the session has no identity.
    dsstox: str


class ExperimentDescription(_BaseModel):
    """
    Metadata about one `DoseResponseExperiment` that rlm-bmdx uses to
    classify and group results.  This is the structure that the
    schema's `_dedupe_legacy_apical_pre` validator,
    `_partition_by_platform()`, and the table builders read most
    heavily.

    Most fields are Optional because the Java-side `experimentDescription`
    objects attached to result lists (WilliamsTrendResults, BMDResult,
    etc.) carry a stub `ExperimentDescription` where every field is None.
    Those stubs aren't read, but they pass through this class because
    our top-level model declares the result lists as `extra` rather than
    explicitly modeling them.

    Only `platform`, `provider`, and the `testArticle` are actually used
    by rlm-bmdx downstream, but we keep the rest as Optional[str] so the
    model accepts what bmdx-pipe writes.
    """

    # The data platform — e.g. "Body Weight", "Hematology", "Organ
    # Weight", "S1500+_rat".  rlm-bmdx uses this to group experiments
    # into report sections.  An open set; new platforms are added as
    # bmdx-pipe supports new file types.
    platform: Optional[str] = None

    # The data provider — currently "Apical" or "BioSpyder".  Used to
    # decide which downstream pipeline (NTP stats vs gene-expression
    # processing) handles the experiment.
    provider: Optional[str] = None

    # The animal sex, lowercase.  rlm-bmdx splits tables by sex
    # downstream.  None on stub descriptions attached to result lists.
    sex: Optional[Literal["male", "female"]] = None

    # The dataType field exists in the source-files compound key
    # ("Platform|dataType") but is not currently populated on the
    # per-experiment description — see the cross-project domain-model
    # refactor noted in project_domain_model_refactor.md.  Kept as
    # Optional[str] so we accept whatever bmdx-pipe sends when the
    # refactor lands.
    dataType: Optional[str] = None

    # Biological context fields.  None of these are strictly required
    # by rlm-bmdx today; they appear in narratives where present.
    species: Optional[str] = None
    strain: Optional[str] = None
    subjectType: Optional[str] = None
    studyDuration: Optional[str] = None
    articleRoute: Optional[str] = None
    articleVehicle: Optional[str] = None
    administrationMeans: Optional[str] = None
    articleType: Optional[str] = None
    cellLine: Optional[str] = None
    organ: Optional[str] = None

    # The TestArticle identifies the chemical.  Optional because the
    # stub descriptions on result lists set it to None; on real
    # DoseResponseExperiments it is always populated.
    testArticle: Optional[TestArticle] = None


class DoseResponseExperiment(_BaseModel):
    """
    A single experiment, in the BMDExpress 3 sense: one dose-response
    measurement series for one (platform, sex) combination.  rlm-bmdx
    reads `name` (to disambiguate sources, e.g. legacy vs `_truth_`),
    `experimentDescription` (to classify), `treatments` (for dose
    columns in tables), and `probeResponses` (for the actual numeric
    values that drive every downstream computation).
    """

    # Internal identifier — used by the schema's
    # `_dedupe_legacy_apical_pre` validator to detect legacy-vs-truth
    # siblings, and by `_partition_by_platform` to infer sex when the
    # description is missing it.
    name: str

    # Per-animal exposure records; parallels the `responses` lists on
    # every `ProbeResponse` in this experiment.
    treatments: list[Treatment]

    # The measured probes (endpoints).  Each carries one numeric value
    # per animal in `treatments`.
    probeResponses: list[ProbeResponse]

    # Description carrying the platform/provider/sex classification.
    # Optional because not every BMDExpress export includes one; in
    # practice every experiment rlm-bmdx cares about has one.
    experimentDescription: Optional[ExperimentDescription] = None


# ---------------------------------------------------------------------------
# `_meta` envelope — rlm-bmdx-owned, not part of the BMDExpress format
# ---------------------------------------------------------------------------
# `_meta` is added by rlm-bmdx's integration step.  We own this part of
# the file end-to-end, so we can be stricter here than we are with the
# Java-emitted fields above.

class SourceFile(_BaseModel):
    """
    One entry in `_meta.source_files`, describing which file was the
    source for one (platform, dataType) compound key.  The key in the
    parent dict — e.g. "Body Weight|tox_study" — is the compound
    "Platform|dataType" identifier; `file_id` and `filename` identify
    the file that became the source for that bucket.
    """

    # Upload file identifier, used to look up the file in the pool.
    file_id: str

    # Original filename as uploaded by the user.
    filename: str

    # Which ingestion path was used: "bm2" for BMDExpress binary,
    # "txt_csv" for the legacy text/CSV path that produces sidecars.
    tier: Literal["bm2", "txt_csv"]

    # How many uploaded files were merged into this bucket.  At least
    # 1; usually exactly 1 for bm2 files and 2 (male+female) for
    # txt_csv files.
    file_count: int

    # How many experiments this bucket contributed to the integrated
    # project.  Optional because it's not always tracked.
    experiment_count: Optional[int] = None


class Meta(_BaseModel):
    """
    The rlm-bmdx-side envelope attached to every `integrated.json`.
    Carries provenance and cross-cutting metadata that doesn't fit
    inside the per-experiment structure.
    """

    # The DSSTox session identifier.  Required — without it the
    # integrated file has no session it belongs to.
    dtxsid: str

    # ISO timestamp of when integration was run.  Useful for debugging
    # stale caches and reproducibility audits.
    integrated_at: str

    # Map of "Platform|dataType" compound keys (or the special key
    # "gene_expression") to the source file that became authoritative
    # for that bucket.  See `SourceFile` for the per-entry shape.
    source_files: dict[str, SourceFile]

    # Per-platform animal rosters loaded from the customer's xlsx study
    # files.  Used by `annotate_missing_animals` to detect animals that
    # died before terminal sacrifice.  Empty dict is legitimate when
    # the customer did not provide an xlsx file.
    xlsx_rosters: dict[str, Any] = {}

    # Absolute paths to clinical-observation CSVs (separate ingestion
    # path because they are categorical, not dose-response numeric).
    # Optional because not every session has clinical observations.
    clinical_obs_files: list[str] = []


# ---------------------------------------------------------------------------
# Top-level BMDProject model
# ---------------------------------------------------------------------------
# Everything that's not explicitly declared on this class falls into
# `model_extra` and round-trips losslessly.  In practice the Java result
# lists (williamsTrendResults, bMDResult, etc.) live there.

class BMDProject(_BaseModel):
    """
    Top-level model for `integrated.json`.  rlm-bmdx reads `name`
    (rarely; mostly for diagnostics), `doseResponseExperiments` (the
    primary data), and `_meta` (the rlm-bmdx-owned envelope).
    Everything else — the precomputed Java result lists — is preserved
    via `model_extra` because we don't currently read it but may in
    the future.
    """

    # The project-level name, set by bmdx-pipe.  Always "integrated"
    # in practice but kept as a regular str field for flexibility.
    name: str

    # The actual data the project carries: one experiment per
    # (platform, sex) source.  May be empty if a session was created
    # but never had files uploaded.
    doseResponseExperiments: list[DoseResponseExperiment]

    # The rlm-bmdx envelope.  The Python attribute is `meta` because
    # Pydantic disallows attribute names starting with an underscore,
    # but the JSON key is `_meta` — bridged by `Field(alias="_meta")`.
    # The `_BaseModel.model_config` has `populate_by_name=True` so the
    # model can also be constructed with the keyword `meta=...` in
    # Python code (useful for tests and for hand-built BMDProjects).
    meta: Meta = Field(alias="_meta")

    # ---------------------------------------------------------------
    # Domain invariants (ADR-0001 commit-sequence step 4)
    # ---------------------------------------------------------------
    # Two validators consolidate the legacy-vs-truth handling that
    # previously lived in `_dedup_legacy_apical_experiments` inside
    # pool_orchestrator.py.  This pulls the domain rule into the
    # schema, so any code path that constructs a BMDProject — load
    # AND save — sees the same normalized, validated data without
    # the orchestrator having to remember to call a helper.
    #
    # The split is:
    #
    #   1. `mode="before"` pre-validator (`_dedupe_legacy_apical_pre`):
    #      runs on the raw input dict, drops legacy `{sex}_{platform}`
    #      experiments when a `{platform}_truth_{sex}` sibling exists
    #      for the same (platform, sex).  This is the normalization
    #      step — it makes data that USED to fail the invariant pass
    #      it cleanly, so existing sessions on disk continue to load.
    #
    #   2. `mode="after"` post-validator (`_assert_apical_uniqueness`):
    #      enforces that no (platform, sex) pair carries more than one
    #      apical experiment.  Anything the pre-validator didn't clean
    #      up — e.g. two truth-named experiments for the same bucket,
    #      or a future bmdx-pipe bug producing fresh duplicates —
    #      fails loudly with a ValidationError.  The pre-validator is
    #      forgiving; the post-validator is the safety net.
    #
    # Genomics (provider="BioSpyder") is exempt from the uniqueness
    # check because S1500+_rat legitimately carries multiple organs
    # per (platform, sex) — Kidney + Liver are separate experiments
    # with the same platform string.  The exemption is by provider,
    # not platform, so any future genomics platforms inherit it.

    @model_validator(mode="before")
    @classmethod
    def _dedupe_legacy_apical_pre(cls, data: Any) -> Any:
        """
        Drop legacy apical experiments superseded by `_truth_` siblings.

        For each (platform, sex) group of non-genomics experiments, if
        any experiment in the group has `_truth_` in its name, drop
        every non-`_truth_` sibling.  Groups without a truth marker
        are left untouched so the post-validator can flag them.

        Operates on the raw input dict — runs BEFORE field validation,
        so it sees plain Python types (dicts, strings, numbers).
        """
        # Only act on dict input; passing through other shapes lets
        # Pydantic produce its standard "expected dict" error.
        if not isinstance(data, dict):
            return data
        exps = data.get("doseResponseExperiments")
        if not isinstance(exps, list) or not exps:
            return data

        # Group experiments by (platform, sex).  Genomics is skipped
        # via the BioSpyder provider check.
        groups: dict[tuple[str, str], list[dict]] = {}
        for exp in exps:
            if not isinstance(exp, dict):
                continue
            desc = exp.get("experimentDescription") or {}
            if not isinstance(desc, dict):
                continue
            if desc.get("provider") == "BioSpyder":
                continue
            platform = desc.get("platform") or desc.get("domain")
            if not platform:
                continue
            name = exp.get("name", "")
            if not isinstance(name, str):
                continue
            nlow = name.lower()
            if "female" in nlow:
                sex = "Female"
            elif "male" in nlow:
                sex = "Male"
            else:
                continue
            groups.setdefault((platform, sex), []).append(exp)

        # Identify legacy duplicates to drop: any group with both a
        # truth-named member and at least one non-truth-named member.
        # The non-truth members all go.  Use id() to track because
        # two unrelated experiments could theoretically be `==`.
        to_drop_ids: set[int] = set()
        dropped_names: list[str] = []
        for group in groups.values():
            if len(group) < 2:
                continue
            has_truth = any(
                "_truth_" in e.get("name", "").lower() for e in group
            )
            if not has_truth:
                continue
            for e in group:
                if "_truth_" not in e.get("name", "").lower():
                    to_drop_ids.add(id(e))
                    dropped_names.append(e.get("name", ""))

        if to_drop_ids:
            logger.info(
                "Dropped %d legacy apical experiment(s) superseded by "
                "truth siblings: %s",
                len(dropped_names),
                ", ".join(dropped_names),
            )
            data["doseResponseExperiments"] = [
                e for e in exps if id(e) not in to_drop_ids
            ]
        return data

    @model_validator(mode="after")
    def _assert_apical_uniqueness(self) -> "BMDProject":
        """
        Enforce that every (platform, sex) carries at most one apical
        experiment.

        Runs after field validation, so `experimentDescription` is a
        typed `ExperimentDescription` (or None) and `sex` has already
        been narrowed to the `Literal["male", "female"]` set.

        Genomics (`provider == "BioSpyder"`) is exempt: those platforms
        carry one experiment per organ within the same (platform, sex),
        which is intentional and not a duplicate.
        """
        groups: dict[tuple[str, str], list[str]] = {}
        for exp in self.doseResponseExperiments:
            desc = exp.experimentDescription
            if desc is None:
                continue
            if desc.provider == "BioSpyder":
                continue
            platform = desc.platform
            if not platform:
                continue
            # Sex may be explicitly set; if missing on the description
            # itself, fall back to inferring from the experiment name
            # using the same female-before-male rule as elsewhere.
            sex = desc.sex
            if sex is None:
                nlow = exp.name.lower()
                if "female" in nlow:
                    sex = "female"
                elif "male" in nlow:
                    sex = "male"
                else:
                    # Can't classify; skip rather than false-positive.
                    continue
            groups.setdefault((platform, sex), []).append(exp.name)

        duplicates = {k: v for k, v in groups.items() if len(v) > 1}
        if duplicates:
            # Raise ValueError; Pydantic wraps it into a
            # ValidationError automatically, and `load_and_validate`
            # converts that into BMDProjectValidationError → 422.
            detail = "; ".join(
                f"({platform}, {sex}): {names}"
                for (platform, sex), names in duplicates.items()
            )
            raise ValueError(
                "Apical experiments must be unique per (platform, sex). "
                f"Duplicates found: {detail}"
            )
        return self


# ---------------------------------------------------------------------------
# Public load helper
# ---------------------------------------------------------------------------
# This is the only function callers should reach for.  It takes a raw
# parsed JSON (a dict produced by `json.load(...)`) and either returns
# the validated dict-form (after a round-trip through the model) or
# raises `BMDProjectValidationError`.

def load_and_validate(raw: dict[str, Any], source: str = "<unknown>") -> dict[str, Any]:
    """
    Validate a parsed `integrated.json` against the BMDProject model.

    Construct the Pydantic `BMDProject` model from the raw dict — which
    triggers validation of every declared field — and then dump the
    model back to a plain dict before returning.  The model itself
    never escapes this function; callers see exactly the same shape
    they would have seen before this barrier existed, except that the
    data is now guaranteed to conform to the contract this module
    declares.

    The returned dict is byte-equivalent to the input for any field
    declared in the model, and preserves all undeclared fields
    losslessly via `extra="allow"`.

    Args:
        raw:    The result of `json.load()` on an `integrated.json`
                file (or an equivalent in-memory dict from a cache).
        source: Short label identifying where `raw` came from — used
                in the error message when validation fails.  Pass the
                session id or file path.

    Returns:
        A dict identical in shape to `raw` but with every consumed
        field type-checked.  Safe to hand to any existing consumer
        that expects the old untyped dict.

    Raises:
        BMDProjectValidationError: when `raw` does not match the model.
        The original `pydantic.ValidationError` is available on the
        exception's `pydantic_error` attribute for callers that need
        structured access to the per-field failure details.
    """
    # Pydantic raises `ValidationError` on any model construction
    # failure; we wrap it in our typed exception so callers can catch
    # one class instead of importing pydantic just for the type.
    try:
        # `model_validate` is the canonical "build me a model from a
        # dict" entry point in Pydantic v2.  It runs all field
        # validators and the `extra="allow"` capture logic.
        model = BMDProject.model_validate(raw)
    except ValidationError as exc:
        # Re-raise with project-specific typing.  The wrapping is the
        # ONLY transformation we do; the original error is preserved
        # in case a caller wants to format it specially.
        raise BMDProjectValidationError(source, exc) from exc

    # Round-trip back to a plain dict for the caller.  `mode="python"`
    # (the default) keeps native types (datetime, etc.); `by_alias=True`
    # restores the underscore-prefixed `_meta` key in the output.
    return model.model_dump(mode="python", by_alias=True)
