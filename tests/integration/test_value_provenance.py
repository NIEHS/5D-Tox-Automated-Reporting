"""
Integration tests for value-level xlsx↔derived-CSV provenance cross-validation
(pipeline/value_validation.py, wired into workflow.steps.validate_step).

The golden DTXSID50469320 fixture ships BOTH the original NTP study xlsx and the
derived tox_study CSV + sidecars for all six apical platforms, so it's a real
lossless oracle. These pin:
  A. lossless — the reference session produces NO value-provenance error;
  B. corruption — a changed / deleted sidecar value produces a blocking error;
  C. warning — a derived platform with no original xlsx warns but doesn't block.

Full-session validation is pure Python (no Java), so these run over the real
validate endpoint without mocking bmdx_pipe.
"""

import json
from pathlib import Path

import pytest

# The value-provenance issue types are prefixed "value_" so they never blur with
# validate_pool's STRUCTURAL dose_mismatch/animal_count_mismatch (which the golden
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
    def test_reference_session_is_lossless(self, golden_50469320):
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

    def test_corrupted_value_blocks_integration(self, golden_50469320):
        """Changing a sidecar value that diverges from the xlsx → blocking error."""
        sc_path = golden_50469320 / "files" / "body_weight_truth_male.sidecar.json"
        sc = json.loads(sc_path.read_text())
        # animal 101 SD5 body weight: 300.3 → 999.9
        obs = sc["animals"]["101"]["observations"]
        target = next(o for o in obs if o["day"] == "SD5")
        assert target["value"] == "300.3"
        target["value"] = "999.9"
        sc_path.write_text(json.dumps(sc))

        report = _validate()
        vm = [i for i in report["issues"] if i["issue_type"] == "value_mismatch"]
        assert vm, "expected a value_mismatch error"
        issue = vm[0]
        assert issue["severity"] == "error"
        assert issue["platform"] == "Body Weight"
        # the example payload should name animal 101 / SD5
        exs = issue["details"]["examples"]
        assert any(e["animal_id"] == "101" and e["day"] == "SD5" for e in exs)

        # and it must gate Integrate (hasValidationErrors)
        from workflow.engine import WorkflowEngine
        from workflow.store import DiskPoolStore
        artifacts = WorkflowEngine("DTXSID50469320", DiskPoolStore()).gather_artifacts()
        assert artifacts["hasValidationErrors"] is True

    def test_deleted_observation_flags_missing(self, golden_50469320):
        """Dropping a measurement from the CSV sidecar → missing_in_csv error."""
        sc_path = golden_50469320 / "files" / "body_weight_truth_male.sidecar.json"
        sc = json.loads(sc_path.read_text())
        obs = sc["animals"]["101"]["observations"]
        sc["animals"]["101"]["observations"] = [o for o in obs if o["day"] != "SD5"]
        sc_path.write_text(json.dumps(sc))

        report = _validate()
        missing = [i for i in report["issues"] if i["issue_type"] == "value_missing_in_csv"]
        assert missing and missing[0]["severity"] == "error"

    def test_no_xlsx_warns_but_does_not_block(self, golden_50469320):
        """A derived platform with no original study xlsx → warning, not error."""
        # Remove the Body Weight study xlsx so its tox_study CSV is unverified.
        bw_xlsx = golden_50469320 / "files" / "C20022-01_Individual_Animal_Body_Weight_Data.xlsx"
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
        xlsx = (Path(__file__).parents[1] / "fixtures" / "golden"
                / "DTXSID50469320" / "files"
                / "C20022-01_Individual_Animal_Body_Weight_Data.xlsx")
        xm = extract_xlsx_value_map(str(xlsx))
        rec = xm[("Male", "101", "Body Weight", "SD5")]
        assert rec["value"] == "300.3"
        assert rec["terminal"] is True
        assert rec["selection"] == "Core Animals"
        assert rec["dose"] == 0.0
        # a dead high-dose animal captured with its SD1 terminal reading
        assert any(k[3] == "SD1" for k in xm)
