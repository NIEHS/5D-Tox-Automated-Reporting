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
