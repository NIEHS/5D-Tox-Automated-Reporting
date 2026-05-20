"""
test_bmd_project_schema.py — Tests for the BMDProject load-time validator.

Covers the contract laid out in `docs/adr/0001-bmdproject-schema-as-
load-barrier.md`:

  - A minimal-valid integrated.json passes validation.
  - Missing required fields fail with BMDProjectValidationError.
  - Type mismatches fail.
  - Invalid Literal values (e.g. `sex="other"`) fail.
  - Undeclared fields at every nesting level are preserved losslessly
    via `extra="allow"`.
  - The real on-disk session's integrated.json validates (regression
    guard against future schema-vs-reality drift).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from bmd_project_schema import BMDProjectValidationError, load_and_validate


# ---------------------------------------------------------------------------
# Minimal valid fixture — hand-built so the test stays readable.
# This is the smallest dict that passes the schema; tests mutate copies
# of it to provoke specific failure modes.
# ---------------------------------------------------------------------------

MINIMAL_VALID: dict = {
    "name": "integrated",
    "doseResponseExperiments": [
        {
            "name": "male_clin_chem",
            "treatments": [
                {"name": "0", "dose": 0.0},
                {"name": "111", "dose": 111.0},
            ],
            "probeResponses": [
                {
                    "probe": {"id": "Alanine aminotransferase"},
                    "responses": [60.0, 75.0],
                },
            ],
            "experimentDescription": {
                "platform": "Clinical Chemistry",
                "provider": "Apical",
                "sex": "male",
                "testArticle": {
                    "name": "Test Compound",
                    "casrn": "123-45-6",
                    "dsstox": "DTXSID12345",
                },
            },
        },
    ],
    "_meta": {
        "dtxsid": "DTXSID12345",
        "integrated_at": "2026-05-11T00:00:00+00:00",
        "source_files": {
            "Clinical Chemistry|tox_study": {
                "file_id": "abc-123",
                "filename": "clin_chem_truth_male.txt",
                "tier": "txt_csv",
                "file_count": 1,
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestMinimalValidInput:
    """The smallest valid BMDProject is accepted."""

    def test_minimal_validates(self):
        out = load_and_validate(MINIMAL_VALID, source="test")
        # The dict-form is shape-equivalent to the input for declared
        # fields.  We confirm the experiment survived end-to-end.
        assert len(out["doseResponseExperiments"]) == 1
        assert out["doseResponseExperiments"][0]["name"] == "male_clin_chem"

    def test_meta_alias_round_trips(self):
        # The JSON's `_meta` key is internally mapped to the Python
        # attribute `meta`, then serialized back via the alias.  Verify
        # the underscore-prefixed key comes out the other side.
        out = load_and_validate(MINIMAL_VALID, source="test")
        assert "_meta" in out
        assert out["_meta"]["dtxsid"] == "DTXSID12345"


# ---------------------------------------------------------------------------
# Required-field violations
# ---------------------------------------------------------------------------

class TestMissingRequiredFields:
    """
    Required fields on the consumed surface must be present.  Pydantic
    raises ValidationError → wrapped into BMDProjectValidationError.
    """

    def test_missing_dtxsid_in_meta_fails(self):
        bad = copy.deepcopy(MINIMAL_VALID)
        del bad["_meta"]["dtxsid"]
        with pytest.raises(BMDProjectValidationError) as exc:
            load_and_validate(bad, source="test")
        # The pydantic error path should point at the dtxsid field for
        # easy diagnosis.
        assert any("dtxsid" in str(e.get("loc", "")) for e in exc.value.pydantic_error.errors())

    def test_missing_experiment_name_fails(self):
        bad = copy.deepcopy(MINIMAL_VALID)
        del bad["doseResponseExperiments"][0]["name"]
        with pytest.raises(BMDProjectValidationError):
            load_and_validate(bad, source="test")


# ---------------------------------------------------------------------------
# Type and value violations
# ---------------------------------------------------------------------------

class TestTypeAndLiteralViolations:
    """Type mismatches and Literal-violation values both fail loudly."""

    def test_responses_must_be_floats(self):
        bad = copy.deepcopy(MINIMAL_VALID)
        # Pass a string where a float is expected.  Pydantic will
        # attempt coercion for some types but a non-numeric string
        # fails.
        bad["doseResponseExperiments"][0]["probeResponses"][0]["responses"] = ["not-a-number"]
        with pytest.raises(BMDProjectValidationError):
            load_and_validate(bad, source="test")

    def test_invalid_sex_literal_fails(self):
        bad = copy.deepcopy(MINIMAL_VALID)
        bad["doseResponseExperiments"][0]["experimentDescription"]["sex"] = "other"
        with pytest.raises(BMDProjectValidationError) as exc:
            load_and_validate(bad, source="test")
        # Confirm the failure points at the sex field.
        assert any("sex" in ".".join(str(x) for x in e.get("loc", ())) for e in exc.value.pydantic_error.errors())

    def test_invalid_tier_literal_fails(self):
        bad = copy.deepcopy(MINIMAL_VALID)
        # The compound-key value's tier must be "bm2" or "txt_csv";
        # anything else fails.
        bad["_meta"]["source_files"]["Clinical Chemistry|tox_study"]["tier"] = "xlsx"
        with pytest.raises(BMDProjectValidationError):
            load_and_validate(bad, source="test")


# ---------------------------------------------------------------------------
# Extra-fields preservation (the "file pool is fair game" stance)
# ---------------------------------------------------------------------------

class TestExtraFieldsPreserved:
    """
    Fields not declared on the model must round-trip losslessly so that
    rlm-bmdx never drops data from the file pool.
    """

    def test_top_level_extra_preserved(self):
        # Java-side result lists are unread today; they must pass through.
        with_extras = copy.deepcopy(MINIMAL_VALID)
        with_extras["williamsTrendResults"] = [{"@type": "WilliamsTrendResults", "name": "demo"}]
        with_extras["bMDResult"] = [{"@type": "BMDResult", "ref": 42}]
        out = load_and_validate(with_extras, source="test")
        assert out["williamsTrendResults"] == [{"@type": "WilliamsTrendResults", "name": "demo"}]
        assert out["bMDResult"] == [{"@type": "BMDResult", "ref": 42}]

    def test_nested_extra_preserved(self):
        # Add an undeclared field deep in an experiment — it must
        # survive the model round-trip.
        with_nested = copy.deepcopy(MINIMAL_VALID)
        with_nested["doseResponseExperiments"][0]["futureFieldFromBmdxPipe"] = {"key": "value"}
        with_nested["doseResponseExperiments"][0]["experimentDescription"]["futureSubfield"] = "lorem"
        out = load_and_validate(with_nested, source="test")
        exp = out["doseResponseExperiments"][0]
        assert exp["futureFieldFromBmdxPipe"] == {"key": "value"}
        assert exp["experimentDescription"]["futureSubfield"] == "lorem"


# ---------------------------------------------------------------------------
# Regression — the real on-disk session must validate
# ---------------------------------------------------------------------------
# This is the closest thing we have to a "golden fixture" without
# committing a 25MB integrated.json into the test tree.  Falling back
# to the live session means the test is only meaningful in local dev,
# but it catches schema-vs-reality drift earlier than any synthetic
# fixture could.

class TestRealSessionIntegratedJson:
    """The on-disk DTXSID50469320 session passes validation."""

    def test_real_session_validates(self):
        path = Path(__file__).resolve().parents[2] / "sessions" / "DTXSID50469320" / "integrated.json"
        if not path.exists():
            pytest.skip(f"session fixture not present at {path}")
        raw = json.loads(path.read_text())
        out = load_and_validate(raw, source="DTXSID50469320")
        # As of ADR-0001 step 4, the schema's pre-validator dedupes
        # legacy apical experiments superseded by truth siblings.
        # The on-disk session has 26 raw experiments; after dedup,
        # 10 legacy siblings (Body Weight, Organ Weight, Clinical
        # Chemistry, Hematology, Hormones — male+female each) are
        # dropped, leaving 16.
        assert len(out["doseResponseExperiments"]) == 16
        assert out["_meta"]["dtxsid"] == "DTXSID50469320"
        # Java result lists pass through as extras at the top level.
        assert "williamsTrendResults" in out
        assert "bMDResult" in out


# ---------------------------------------------------------------------------
# Domain invariants (ADR-0001 step 4): legacy/truth dedup + uniqueness
# ---------------------------------------------------------------------------

def _exp(
    name: str, platform: str, sex: str, provider: str = "Apical",
) -> dict:
    """Helper to build a minimal valid DoseResponseExperiment dict."""
    return {
        "name": name,
        "treatments": [{"name": "0", "dose": 0.0}],
        "probeResponses": [{"probe": {"id": "X"}, "responses": [1.0]}],
        "experimentDescription": {
            "platform": platform,
            "provider": provider,
            "sex": sex,
            "testArticle": {"name": "X", "dsstox": "DTXSID00000000"},
        },
    }


def _project(*experiments: dict) -> dict:
    """Helper to build a minimal valid BMDProject dict around experiments."""
    return {
        "name": "integrated",
        "doseResponseExperiments": list(experiments),
        "_meta": {
            "dtxsid": "DTXSID00000000",
            "integrated_at": "2026-05-12T00:00:00+00:00",
            "source_files": {},
        },
    }


class TestLegacyTruthDedup:
    """The pre-validator drops legacy siblings when a truth sibling exists."""

    def test_truth_wins_over_legacy(self):
        # Both legacy and truth experiments for the same (platform, sex).
        # After dedup, only the truth one survives.
        raw = _project(
            _exp("male_clin_chem", "Clinical Chemistry", "male"),
            _exp("clin_chem_truth_male", "Clinical Chemistry", "male"),
        )
        out = load_and_validate(raw, source="test")
        names = [e["name"] for e in out["doseResponseExperiments"]]
        assert names == ["clin_chem_truth_male"]

    def test_no_truth_means_no_dedup(self):
        # Two non-truth experiments for the same (platform, sex) — the
        # pre-validator can't choose, so it leaves both.  The post-
        # validator then catches the duplicate as an invariant failure.
        raw = _project(
            _exp("male_clin_chem_v1", "Clinical Chemistry", "male"),
            _exp("male_clin_chem_v2", "Clinical Chemistry", "male"),
        )
        with pytest.raises(BMDProjectValidationError) as exc:
            load_and_validate(raw, source="test")
        # The error message names both experiments so the caller can
        # diagnose which (platform, sex) bucket exploded.
        msg = str(exc.value)
        assert "Clinical Chemistry" in msg
        assert "male" in msg

    def test_lone_experiment_untouched(self):
        # Single experiment per (platform, sex) — no dedup, no error.
        raw = _project(
            _exp("male_clin_chem", "Clinical Chemistry", "male"),
        )
        out = load_and_validate(raw, source="test")
        assert len(out["doseResponseExperiments"]) == 1


class TestApicalUniquenessInvariant:
    """The post-validator enforces (platform, sex) uniqueness on apical data."""

    def test_two_truth_experiments_fail(self):
        # Two truth-named experiments — pre-validator can't dedup
        # (both have _truth_ in name), so the post-validator fires.
        raw = _project(
            _exp("clin_chem_truth_male_a", "Clinical Chemistry", "male"),
            _exp("clin_chem_truth_male_b", "Clinical Chemistry", "male"),
        )
        with pytest.raises(BMDProjectValidationError):
            load_and_validate(raw, source="test")

    def test_genomics_multi_organ_allowed(self):
        # BioSpyder genomics legitimately has Kidney + Liver under the
        # same (platform, sex) — the invariant must exempt them.
        raw = _project(
            _exp("Kidney_X_Female_No0", "S1500+_rat", "female", "BioSpyder"),
            _exp("Liver_X_Female_No0",  "S1500+_rat", "female", "BioSpyder"),
        )
        out = load_and_validate(raw, source="test")
        # Both survive: BioSpyder is exempt from the invariant.
        assert len(out["doseResponseExperiments"]) == 2

    def test_different_sexes_allowed(self):
        # Same platform, different sexes — not a duplicate.
        raw = _project(
            _exp("male_clin_chem",   "Clinical Chemistry", "male"),
            _exp("female_clin_chem", "Clinical Chemistry", "female"),
        )
        out = load_and_validate(raw, source="test")
        assert len(out["doseResponseExperiments"]) == 2

    def test_different_platforms_allowed(self):
        # Same sex, different platforms — not a duplicate.
        raw = _project(
            _exp("male_clin_chem", "Clinical Chemistry", "male"),
            _exp("male_organ_weights", "Organ Weight", "male"),
        )
        out = load_and_validate(raw, source="test")
        assert len(out["doseResponseExperiments"]) == 2


# ---------------------------------------------------------------------------
# BMD-result repointing: when the pre-validator drops a legacy apical
# experiment, the bMDResult entries BMDExpress produced against it must be
# repointed onto the surviving truth sibling — otherwise the BMD/BMDL
# columns collapse to "—".  See `_repoint_bmd_results_to_truth`.
# ---------------------------------------------------------------------------

def _exp_with_refs(
    name: str, platform: str, sex: str,
    exp_ref: int, probes: list[tuple[int, str]],
) -> dict:
    """
    Build an experiment dict with explicit Jackson @ref identity, the way
    bmdx-pipe serializes it.  `probes` is a list of (probe_ref, label).
    """
    return {
        "@ref": exp_ref,
        "name": name,
        "treatments": [{"name": "0", "dose": 0.0}],
        "probeResponses": [
            {"@ref": pref, "probe": {"id": label}, "responses": [1.0]}
            for pref, label in probes
        ],
        "experimentDescription": {
            "platform": platform,
            "provider": "Apical",
            "sex": sex,
            "testArticle": {"name": "X", "dsstox": "DTXSID00000000"},
        },
    }


def _bmd_result(name: str, exp_ref: int, probe_refs: list[int]) -> dict:
    """Build a bMDResult entry referencing an experiment + probe @refs."""
    return {
        "@type": "BMDResult",
        "name": name,
        "doseResponseExperiment": exp_ref,
        "probeStatResults": [
            {"probeResponse": pref, "bestBMD": 10.0 + i, "bestBMDL": 5.0 + i}
            for i, pref in enumerate(probe_refs)
        ],
    }


class TestBmdResultRepointing:
    """Legacy bMDResult entries get repointed onto the truth sibling."""

    def test_bmd_result_experiment_ref_repointed(self):
        # Legacy experiment @ref=1 carries the bMDResult; truth is @ref=2.
        # After dedup the legacy experiment is gone, and the bMDResult's
        # doseResponseExperiment must now point at the truth @ref.
        legacy = _exp_with_refs(
            "male_clin_chem", "Clinical Chemistry", "male",
            exp_ref=1, probes=[(11, "ALT"), (12, "AST")],
        )
        truth = _exp_with_refs(
            "clin_chem_truth_male", "Clinical Chemistry", "male",
            exp_ref=2, probes=[(21, "ALT"), (22, "AST")],
        )
        raw = _project(legacy, truth)
        raw["bMDResult"] = [_bmd_result("legacy_bmd", 1, [11, 12])]

        out = load_and_validate(raw, source="test")

        # Only the truth experiment survives.
        names = [e["name"] for e in out["doseResponseExperiments"]]
        assert names == ["clin_chem_truth_male"]
        # The bMDResult survived (model_extra) AND was repointed.
        assert len(out["bMDResult"]) == 1
        assert out["bMDResult"][0]["doseResponseExperiment"] == 2

    def test_probe_response_refs_repointed_by_label(self):
        # Each probeStatResult's probeResponse @ref must move from the
        # legacy probe @ref to the truth probe @ref carrying the same
        # endpoint label.
        legacy = _exp_with_refs(
            "male_clin_chem", "Clinical Chemistry", "male",
            exp_ref=1, probes=[(11, "ALT"), (12, "AST")],
        )
        truth = _exp_with_refs(
            "clin_chem_truth_male", "Clinical Chemistry", "male",
            exp_ref=2, probes=[(21, "ALT"), (22, "AST")],
        )
        raw = _project(legacy, truth)
        raw["bMDResult"] = [_bmd_result("legacy_bmd", 1, [11, 12])]

        out = load_and_validate(raw, source="test")

        psrs = out["bMDResult"][0]["probeStatResults"]
        # 11 (legacy ALT) -> 21 (truth ALT); 12 (legacy AST) -> 22 (truth AST)
        assert [p["probeResponse"] for p in psrs] == [21, 22]
        # The BMD values themselves are untouched — only the refs move.
        assert psrs[0]["bestBMD"] == 10.0
        assert psrs[1]["bestBMD"] == 11.0

    def test_unmatched_probe_label_left_alone(self):
        # When a legacy probe label has no counterpart in the truth
        # experiment (e.g. a customer-side typo), that probeResponse @ref
        # is left untouched rather than guessed at — the downstream lookup
        # skips it.  The other probes still repoint correctly.
        legacy = _exp_with_refs(
            "male_hormone_data", "Hormones", "male",
            exp_ref=1, probes=[(11, "Total Thyroxine"), (12, "Triiodiodothyronine")],
        )
        truth = _exp_with_refs(
            "hormones_truth_male", "Hormones", "male",
            exp_ref=2, probes=[(21, "Total Thyroxine"), (22, "Triiodothyronine")],
        )
        raw = _project(legacy, truth)
        raw["bMDResult"] = [_bmd_result("legacy_bmd", 1, [11, 12])]

        out = load_and_validate(raw, source="test")

        psrs = out["bMDResult"][0]["probeStatResults"]
        # "Total Thyroxine" matches -> repointed to 21.
        assert psrs[0]["probeResponse"] == 21
        # The misspelled "Triiodiodothyronine" has no truth match -> the
        # original legacy @ref is left in place (12), not invented.
        assert psrs[1]["probeResponse"] == 12

    def test_no_truth_sibling_leaves_bmd_result_untouched(self):
        # A lone legacy experiment (no truth sibling) is not dropped, so
        # its bMDResult is not repointed either.
        legacy = _exp_with_refs(
            "male_clin_chem", "Clinical Chemistry", "male",
            exp_ref=1, probes=[(11, "ALT")],
        )
        raw = _project(legacy)
        raw["bMDResult"] = [_bmd_result("legacy_bmd", 1, [11])]

        out = load_and_validate(raw, source="test")

        assert len(out["doseResponseExperiments"]) == 1
        assert out["bMDResult"][0]["doseResponseExperiment"] == 1
        assert out["bMDResult"][0]["probeStatResults"][0]["probeResponse"] == 11


# ---------------------------------------------------------------------------
# Imputed-cell detection: when the legacy file fills a value the truth file
# leaves missing, the pre-validator records the affected dose groups in
# `_meta.imputed_cells` so the report can footnote imputation-backed BMDs.
# ---------------------------------------------------------------------------

def _exp_for_imputation(
    name: str, platform: str, sex: str,
    doses: list[float], probe_responses: dict[str, list],
) -> dict:
    """
    Build an experiment dict with a multi-dose treatment vector and
    per-probe response vectors (which may contain None for missing cells).
    `probe_responses` is {endpoint_label: [value_per_treatment_slot]}.
    """
    return {
        "name": name,
        "treatments": [
            {"name": str(d), "dose": d} for d in doses
        ],
        "probeResponses": [
            {"probe": {"id": label}, "responses": responses}
            for label, responses in probe_responses.items()
        ],
        "experimentDescription": {
            "platform": platform,
            "provider": "Apical",
            "sex": sex,
            "testArticle": {"name": "X", "dsstox": "DTXSID00000000"},
        },
    }


class TestImputedCellDetection:
    """Legacy-vs-truth value gaps are recorded in _meta.imputed_cells."""

    def test_imputed_cell_recorded(self):
        # Truth leaves slot 1 (dose 1.4) missing; legacy fills it.  That
        # one cell must show up under (platform, sex, dose) in _meta.
        legacy = _exp_for_imputation(
            "male_clin_chem", "Clinical Chemistry", "male",
            doses=[0.0, 1.4, 12.0],
            probe_responses={"ALT": [50.0, 55.0, 60.0]},
        )
        truth = _exp_for_imputation(
            "clin_chem_truth_male", "Clinical Chemistry", "male",
            doses=[0.0, 1.4, 12.0],
            probe_responses={"ALT": [50.0, None, 60.0]},
        )
        out = load_and_validate(_project(legacy, truth), source="test")

        imputed = out["_meta"]["imputed_cells"]
        assert imputed == {"Clinical Chemistry": {"Male": {"1.4": 1}}}

    def test_counts_aggregate_per_dose(self):
        # Two endpoints, both missing the same dose in truth — the count
        # for that dose group is the sum across endpoints.
        legacy = _exp_for_imputation(
            "male_clin_chem", "Clinical Chemistry", "male",
            doses=[0.0, 12.0],
            probe_responses={"ALT": [50.0, 60.0], "AST": [70.0, 80.0]},
        )
        truth = _exp_for_imputation(
            "clin_chem_truth_male", "Clinical Chemistry", "male",
            doses=[0.0, 12.0],
            probe_responses={"ALT": [50.0, None], "AST": [70.0, None]},
        )
        out = load_and_validate(_project(legacy, truth), source="test")

        assert out["_meta"]["imputed_cells"] == {
            "Clinical Chemistry": {"Male": {"12.0": 2}}
        }

    def test_no_gap_means_no_imputation_entry(self):
        # Identical truth and legacy data — nothing imputed, and the key
        # is not added to _meta at all (rather than added empty).
        legacy = _exp_for_imputation(
            "male_clin_chem", "Clinical Chemistry", "male",
            doses=[0.0, 12.0],
            probe_responses={"ALT": [50.0, 60.0]},
        )
        truth = _exp_for_imputation(
            "clin_chem_truth_male", "Clinical Chemistry", "male",
            doses=[0.0, 12.0],
            probe_responses={"ALT": [50.0, 60.0]},
        )
        out = load_and_validate(_project(legacy, truth), source="test")

        assert "imputed_cells" not in out["_meta"]

    def test_mismatched_treatment_vectors_skipped(self):
        # If legacy and truth don't share an identical dose vector we
        # can't align response slots, so detection is skipped (no entry)
        # — but the dedup itself still happens.
        legacy = _exp_for_imputation(
            "male_clin_chem", "Clinical Chemistry", "male",
            doses=[0.0, 1.4, 12.0],
            probe_responses={"ALT": [50.0, 55.0, 60.0]},
        )
        truth = _exp_for_imputation(
            "clin_chem_truth_male", "Clinical Chemistry", "male",
            doses=[0.0, 12.0],
            probe_responses={"ALT": [50.0, None]},
        )
        out = load_and_validate(_project(legacy, truth), source="test")

        # Dedup still ran — only the truth experiment survives.
        names = [e["name"] for e in out["doseResponseExperiments"]]
        assert names == ["clin_chem_truth_male"]
        # But no imputation was recorded (vectors couldn't be aligned).
        assert "imputed_cells" not in out["_meta"]

    def test_truth_value_present_is_not_imputation(self):
        # A slot where BOTH files have a value is not imputation, even if
        # the values differ — only truth-missing / legacy-present counts.
        legacy = _exp_for_imputation(
            "male_clin_chem", "Clinical Chemistry", "male",
            doses=[0.0, 12.0],
            probe_responses={"ALT": [50.0, 99.0]},
        )
        truth = _exp_for_imputation(
            "clin_chem_truth_male", "Clinical Chemistry", "male",
            doses=[0.0, 12.0],
            probe_responses={"ALT": [50.0, 60.0]},
        )
        out = load_and_validate(_project(legacy, truth), source="test")

        assert "imputed_cells" not in out["_meta"]
