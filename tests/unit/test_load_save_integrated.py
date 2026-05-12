"""
test_load_save_integrated.py — Tests for the symmetric load/save barrier.

Covers `pool_orchestrator.save_integrated()`, the writer added in
ADR-0001 commit-sequence step 3.  The companion `load_integrated()`
read path is exercised throughout the unit suite already; here we
focus on the validate-then-write semantics that step 3 introduced.
"""

from __future__ import annotations

import copy
import json

import pytest

from bmd_project_schema import BMDProjectValidationError


# ---------------------------------------------------------------------------
# Minimal valid fixture — mirrors test_bmd_project_schema.py so the two
# files are independently readable.
# ---------------------------------------------------------------------------

MINIMAL_VALID: dict = {
    "name": "integrated",
    "doseResponseExperiments": [
        {
            "name": "male_clin_chem",
            "treatments": [{"name": "0", "dose": 0.0}, {"name": "1", "dose": 1.0}],
            "probeResponses": [
                {"probe": {"id": "ALT"}, "responses": [60.0, 75.0]},
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
        "integrated_at": "2026-05-12T00:00:00+00:00",
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
# save_integrated — happy path
# ---------------------------------------------------------------------------

class TestSaveIntegratedHappyPath:
    """A valid dict is persisted and the in-memory cache is updated."""

    def test_writes_file_to_disk(self, sessions_dir):
        from pool_orchestrator import save_integrated

        result = save_integrated("DTXSID12345", copy.deepcopy(MINIMAL_VALID))

        # File appears on disk under the patched sessions dir.
        json_path = sessions_dir / "DTXSID12345" / "integrated.json"
        assert json_path.exists()

        # And contains the same data we passed in (after model round-trip).
        on_disk = json.loads(json_path.read_text())
        assert on_disk["_meta"]["dtxsid"] == "DTXSID12345"
        assert len(on_disk["doseResponseExperiments"]) == 1
        # Return value is the validated form — useful for callers that
        # want the canonical dict back without re-loading.
        assert result["_meta"]["dtxsid"] == "DTXSID12345"

    def test_updates_in_memory_cache(self, sessions_dir):
        from pool_orchestrator import save_integrated, _integrated_pool

        save_integrated("DTXSID12345", copy.deepcopy(MINIMAL_VALID))

        # The cache now holds the validated form so the next
        # `load_integrated` call returns it without re-reading disk.
        assert "DTXSID12345" in _integrated_pool
        cached = _integrated_pool["DTXSID12345"]
        assert cached["_meta"]["dtxsid"] == "DTXSID12345"

    def test_round_trip_via_load_integrated(self, sessions_dir):
        # Symmetry: save then load returns equivalent content.
        from pool_orchestrator import save_integrated, load_integrated

        saved = save_integrated("DTXSID12345", copy.deepcopy(MINIMAL_VALID))
        loaded = load_integrated("DTXSID12345")

        # Both go through model_dump() — identical canonical form.
        assert loaded == saved


# ---------------------------------------------------------------------------
# save_integrated — invalid data is rejected, disk untouched
# ---------------------------------------------------------------------------

class TestSaveIntegratedRejectsInvalid:
    """Invalid data raises before any disk write happens."""

    def test_invalid_sex_raises_validation_error(self, sessions_dir):
        from pool_orchestrator import save_integrated

        bad = copy.deepcopy(MINIMAL_VALID)
        bad["doseResponseExperiments"][0]["experimentDescription"]["sex"] = "other"

        with pytest.raises(BMDProjectValidationError):
            save_integrated("DTXSID12345", bad)

    def test_invalid_data_does_not_create_file(self, sessions_dir):
        from pool_orchestrator import save_integrated

        bad = copy.deepcopy(MINIMAL_VALID)
        del bad["_meta"]["dtxsid"]  # required field

        with pytest.raises(BMDProjectValidationError):
            save_integrated("DTXSID12345", bad)

        # File was never created because validation ran before write.
        assert not (sessions_dir / "DTXSID12345" / "integrated.json").exists()

    def test_invalid_data_does_not_clobber_existing_file(self, sessions_dir):
        # Setup: persist a valid file first.
        from pool_orchestrator import save_integrated

        save_integrated("DTXSID12345", copy.deepcopy(MINIMAL_VALID))
        json_path = sessions_dir / "DTXSID12345" / "integrated.json"
        original_bytes = json_path.read_bytes()

        # Attempt to overwrite with garbage.
        bad = copy.deepcopy(MINIMAL_VALID)
        bad["doseResponseExperiments"][0]["experimentDescription"]["sex"] = "alien"

        with pytest.raises(BMDProjectValidationError):
            save_integrated("DTXSID12345", bad)

        # Existing file is byte-identical — validation prevented the
        # write entirely, so the on-disk content is the original.
        assert json_path.read_bytes() == original_bytes
