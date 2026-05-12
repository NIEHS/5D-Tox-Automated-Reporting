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
        # Smoke checks: 26 experiments in the known-good session,
        # _meta envelope round-trips, and the Java result lists are
        # preserved.
        assert len(out["doseResponseExperiments"]) == 26
        assert out["_meta"]["dtxsid"] == "DTXSID50469320"
        # Java result lists pass through as extras at the top level.
        assert "williamsTrendResults" in out
        assert "bMDResult" in out
