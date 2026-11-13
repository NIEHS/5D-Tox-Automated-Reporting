"""
Integration tests for value-level xlsx↔derived-CSV provenance cross-validation
(pipeline/value_validation.py, wired into workflow.steps.validate_step).

The NIEHS-10 session holds BOTH the study workbooks and the truth CSVs converted
from them; the workbooks drive, and the CSVs are set aside in _originals/, so it
is a real lossless oracle. These pin:
  A. lossless — the session produces NO value-provenance error;
  B. corruption — a changed / deleted CSV value produces a blocking error;
  C. warning — a derived platform with no workbook warns but doesn't block.

Full-session validation is pure Python (no Java), so these run over the real
validate endpoint without mocking bmdx_pipe.
"""

import json
from pathlib import Path

import pytest

# The value-provenance issue types are prefixed "value_" so they never blur with
# validate_pool's STRUCTURAL dose_mismatch/animal_count_mismatch (which the given-PFHxSAm
# session already emits — the xlsx and txt legitimately differ on dose groups
# because the txt excludes dead animals). We assert only on OUR channel.
_VALUE_ERROR_TYPES = {
    "value_mismatch", "value_missing_in_csv", "value_missing_in_xlsx",
    "value_dose_mismatch", "value_selection_mismatch", "value_terminal_mismatch",
}


def _validate(dtxsid="DTXSID50469320"):
    from fastapi.testclient import TestClient
    from web_routes.background_server import app
    client = TestClient(app)
    resp = client.post(f"/api/pool/validate/{dtxsid}")
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.integration
class TestValueProvenance:
    def test_reference_session_is_lossless(self, niehs10):
        """The derived CSV faithfully reproduces the source xlsx — no value error."""
        report = _validate()
        value_errors = [
            i for i in report["issues"]
            if i["issue_type"] in _VALUE_ERROR_TYPES
        ]
        assert value_errors == [], (
            "reference session should be lossless, got: "
            + "; ".join(i["message"] for i in value_errors)
        )
        # and it should NOT warn — every tox_study platform has its xlsx here
        assert not [i for i in report["issues"]
                    if i["issue_type"] == "unverified_derived_data"]

    def test_corrupted_value_blocks_integration(self, niehs10):
        """A set-aside CSV value that diverges from the workbook → blocking error."""
        csv = niehs10 / "_originals" / "body_weight_truth_male.csv"
        text = csv.read_text()
        # animal 101 SD5 body weight: 300.3 → 999.9
        assert ",101,Male,Core Animals,300.3,SD5," in text
        csv.write_text(text.replace(",101,Male,Core Animals,300.3,SD5,",
                                    ",101,Male,Core Animals,999.9,SD5,"))

        report = _validate()
        vm = [i for i in report["issues"] if i["issue_type"] == "value_mismatch"]
        assert vm, "expected a value_mismatch error"
        issue = vm[0]
        assert issue["severity"] == "error"
        assert issue["platform"] == "Body Weight"
        assert "body_weight_truth_male.csv" in issue["message"]
        # the example payload should name animal 101 / SD5
        exs = issue["details"]["examples"]
        assert any(e["animal_id"] == "101" and e["day"] == "SD5" for e in exs)

        # and it must gate Integrate (hasValidationErrors)
        from workflow.engine import WorkflowEngine
        from workflow.store import DiskPoolStore
        artifacts = WorkflowEngine("DTXSID50469320", DiskPoolStore()).gather_artifacts()
        assert artifacts["hasValidationErrors"] is True

    def test_deleted_observation_flags_missing(self, niehs10):
        """A measurement the set-aside CSV lacks → missing_in_csv error."""
        csv = niehs10 / "_originals" / "body_weight_truth_male.csv"
        lines = csv.read_text().splitlines(keepends=True)
        csv.write_text("".join(l for l in lines if ",101,Male,Core Animals,300.3,SD5," not in l))

        report = _validate()
        missing = [i for i in report["issues"] if i["issue_type"] == "value_missing_in_csv"]
        assert missing and missing[0]["severity"] == "error"

    def test_no_xlsx_warns_but_does_not_block(self, niehs10):
        """A derived platform with no original study xlsx → warning, not error."""
        # Remove the Body Weight study xlsx so its tox_study CSV is unverified.
        bw_xlsx = niehs10 / "files" / "C20022-01_Individual_Animal_Body_Weight_Data.xlsx"
        assert bw_xlsx.exists()
        bw_xlsx.unlink()

        report = _validate()
        warns = [i for i in report["issues"]
                 if i["issue_type"] == "unverified_derived_data"
                 and i["platform"] == "Body Weight"]
        assert warns, "expected an unverified_derived_data warning for Body Weight"
        assert warns[0]["severity"] == "warning"
        # the warning must NOT introduce a value error for Body Weight
        assert not [i for i in report["issues"]
                    if i["platform"] == "Body Weight"
                    and i["issue_type"] in _VALUE_ERROR_TYPES]


class TestExtractXlsxValueMap:
    def test_extracts_keyed_values(self):
        from bmdx_pipe import extract_xlsx_value_map
        # Fixture path is repo-relative; resolve from this test file.
        xlsx = (Path(__file__).parents[1] / "fixtures" / "regression"
                / "given-pfhxsam-2026" / "files"
                / "C20022-01_Individual_Animal_Body_Weight_Data.xlsx")
        xm = extract_xlsx_value_map(str(xlsx))
        rec = xm[("Male", "101", "Body Weight", "SD5")]
        assert rec["value"] == "300.3"
        assert rec["terminal"] is True
        assert rec["selection"] == "Core Animals"
        assert rec["dose"] == 0.0
        # a dead high-dose animal captured with its SD1 terminal reading
        assert any(k[3] == "SD1" for k in xm)
