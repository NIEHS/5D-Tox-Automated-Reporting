"""
test_full_pipeline.py — End-to-end smoke test for the domain model refactor.

Walks through the complete pipeline using golden DTXSID50469320 session data:
  1. Session load — discovers pending files
  2. Validate — fingerprints all files, checks platform/data_type fields
  3. Integrate — merges into unified BMDProject (mocked)
  4. Process — generates section cards per platform (mocked NTP stats)
  5. Approve — persists a section to disk
  6. Session restore — reloads from disk, finds approved sections

This covers the 9-point checklist for validating the domain model refactor.
"""

import json

import pytest

from bmdx_pipe import TableRow


def _make_integrated():
    """Minimal integrated BMDProject for mock return."""
    return {
        "doseResponseExperiments": [
            {
                "name": "BodyWeight_Male",
                "experimentDescription": {"platform": "Body Weight", "data_type": "tox_study"},
                "probeResponses": [{"probe": {"id": "SD5"}, "responses": [100, 110]}],
            },
        ],
        "_meta": {
            "source_files": {
                "Body Weight": {"filename": "body_weight_truth_male.txt"},
            },
        },
    }


def _make_table_data():
    """Mock NTP stats output.  responsive=True so section cards include them."""
    return {
        "Male": [
            TableRow(
                label="SD5",
                values_by_dose={0.0: "100.0 ± 5.0", 1.0: "110.0 ± 6.0**"},
                n_by_dose={0.0: 10, 1.0: 10},
                trend_marker="**",
                responsive=True,
            ),
        ],
    }


@pytest.mark.e2e
class TestFullPipeline:
    """Walk through the complete pipeline with golden session data."""

    def test_upload_validate_integrate_process_approve_restore(
        self, golden_50469320, mock_bmdx_pipe,
    ):
        """
        End-to-end: session load → validate → integrate → process → approve
        → clear state → restore from disk.
        """
        from fastapi.testclient import TestClient
        from background_server import app
        import pool_orchestrator
        import server_state

        client = TestClient(app)
        dtxsid = "DTXSID50469320"

        # ── Step 1: Session load ──────────────────────────────────────
        resp = client.get(f"/api/session/{dtxsid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["exists"] is True
        # Golden session has data files that should show up as pending
        pending = data.get("pending_files", [])
        assert len(pending) > 0, "No pending files found in golden session"

        # ── Step 2: Validate ──────────────────────────────────────────
        resp = client.post(f"/api/pool/validate/{dtxsid}")
        assert resp.status_code == 200
        report = resp.json()
        assert report["file_count"] > 0

        # Domain model refactor check: all fingerprints have platform/data_type
        for fid, fp in report.get("fingerprints", {}).items():
            assert "platform" in fp, f"Missing platform on {fp.get('filename')}"
            assert "data_type" in fp, f"Missing data_type on {fp.get('filename')}"

        # ── Step 3: Integrate (mocked) ────────────────────────────────
        mock_bmdx_pipe.integrate_pool.return_value = _make_integrated()
        resp = client.post(
            f"/api/pool/integrate/{dtxsid}",
            json={"identity": {"name": "PFHxSAm", "casrn": "41997-13-1", "dtxsid": dtxsid}},
        )
        assert resp.status_code == 200

        # Verify integrated data cached in memory (integrated.json is written
        # by the real integrate_pool, which is mocked here)
        assert dtxsid in pool_orchestrator._integrated_pool

        # ── Step 4: Process (mocked NTP stats) ────────────────────────
        mock_bmdx_pipe.build_table_data.return_value = _make_table_data()
        resp = client.post(
            f"/api/process-integrated/{dtxsid}",
            json={"compound_name": "PFHxSAm", "dose_unit": "mg/kg"},
        )
        assert resp.status_code == 200
        process_data = resp.json()
        assert "sections" in process_data
        assert len(process_data["sections"]) > 0

        # Section cards should use new platform names
        for sec in process_data["sections"]:
            assert "platform" in sec

        # ── Step 5: Approve a section ─────────────────────────────────
        resp = client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "background",
            "data": {"paragraphs": ["Test background paragraph."]},
        })
        assert resp.status_code == 200
        assert (golden_50469320 / "background.json").exists()

        # ── Step 6: Clear in-memory state and restore from disk ───────
        pool_orchestrator._pool_fingerprints.clear()
        pool_orchestrator._integrated_pool.clear()
        pool_orchestrator._data_uploads.clear()
        server_state._bm2_uploads.clear()
        server_state._csv_uploads.clear()

        resp = client.get(f"/api/session/{dtxsid}")
        assert resp.status_code == 200
        restored = resp.json()
        assert restored["exists"] is True

        # The approved background should be present after restore
        assert restored["background"] is not None
        assert restored["background"]["paragraphs"] == ["Test background paragraph."]

        # Pending files should be re-discovered from disk
        assert len(restored.get("pending_files", [])) > 0
