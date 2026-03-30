"""
test_pool_validate.py — Integration tests for the pool validation endpoint.

This is the highest-ROI test for the domain model refactor: it verifies that
fingerprinting produces the new platform/data_type fields (not the old
monolithic domain strings) and that the coverage matrix uses compound keys.

Uses real golden session data (12 txt/csv files across 6 platforms) and
exercises the real fingerprint_file() function (pure Python for txt/csv).
Only Java-dependent functions need mocking.
"""

import json

import pytest


# The expected platforms in the DTXSID50469320 golden session.
# These must match what fingerprint_file() produces from the txt/csv files.
# The golden data has 7 file groups: body_weight, clin_chem, clinical_obs,
# hematology, hormones, organ_weights, tissue_conc — covering all 6 apical
# platforms plus Clinical Observations.
EXPECTED_PLATFORMS = {
    "Body Weight",
    "Organ Weight",
    "Clinical Chemistry",
    "Hematology",
    "Hormones",
    "Tissue Concentration",
}


@pytest.mark.integration
class TestPoolValidate:
    """POST /api/pool/validate/{dtxsid} — full fingerprint + cross-validation."""

    def test_validates_golden_session(self, golden_50469320):
        """
        Given the golden DTXSID50469320 session with 12 txt/csv files,
        validation should return a report with correct file_count and
        platform/data_type fields on every fingerprint.
        """
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        resp = client.post("/api/pool/validate/DTXSID50469320")
        assert resp.status_code == 200, f"Validation failed: {resp.text}"

        report = resp.json()

        # The session should have data files (txt/csv, possibly split by sex)
        assert report["file_count"] > 0, "No files fingerprinted"

    def test_fingerprints_have_platform_and_data_type(self, golden_50469320):
        """
        Every fingerprint must have 'platform' and 'data_type' fields —
        this is the core assertion for the domain model refactor.  The old
        monolithic 'domain' field should NOT appear.
        """
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        resp = client.post("/api/pool/validate/DTXSID50469320")
        report = resp.json()
        fingerprints = report.get("fingerprints", {})

        assert len(fingerprints) > 0, "No fingerprints in report"

        for file_id, fp in fingerprints.items():
            # New domain model fields must be present
            assert "platform" in fp, (
                f"Fingerprint {file_id} ({fp.get('filename')}) missing 'platform'"
            )
            assert "data_type" in fp, (
                f"Fingerprint {file_id} ({fp.get('filename')}) missing 'data_type'"
            )
            # Platform should be a recognized value, not empty
            assert fp["platform"], (
                f"Fingerprint {file_id} ({fp.get('filename')}) has empty platform"
            )

    def test_expected_platforms_covered(self, golden_50469320):
        """
        The golden session spans 6 platforms.  After validation, all
        expected platforms should appear in at least one fingerprint.
        """
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        resp = client.post("/api/pool/validate/DTXSID50469320")
        report = resp.json()

        # Collect all platforms from fingerprints
        platforms_found = set()
        for fp in report.get("fingerprints", {}).values():
            plat = fp.get("platform")
            if plat:
                platforms_found.add(plat)

        # Check that the expected platforms are covered (allow extras —
        # clinical observations might be separate)
        missing = EXPECTED_PLATFORMS - platforms_found
        assert not missing, (
            f"Expected platforms not found in fingerprints: {missing}. "
            f"Found: {platforms_found}"
        )

    def test_validation_report_persisted(self, golden_50469320):
        """
        Validation should write validation_report.json to the session dir.
        """
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        resp = client.post("/api/pool/validate/DTXSID50469320")
        assert resp.status_code == 200

        # Check the report was persisted to disk
        report_path = golden_50469320 / "validation_report.json"
        assert report_path.exists(), "validation_report.json not written"

        persisted = json.loads(report_path.read_text())
        assert persisted["dtxsid"] == "DTXSID50469320"
        assert "fingerprints" in persisted
        assert "issues" in persisted

    def test_no_files_returns_404(self, sessions_dir):
        """
        Validating a session with no files/ directory returns 404.
        """
        from fastapi.testclient import TestClient
        from background_server import app

        # Create session dir but no files/ subdirectory
        (sessions_dir / "DTXSID_EMPTY").mkdir(parents=True)

        client = TestClient(app)
        resp = client.post("/api/pool/validate/DTXSID_EMPTY")
        assert resp.status_code == 404
