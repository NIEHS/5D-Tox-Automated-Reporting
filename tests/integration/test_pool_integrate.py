"""
test_pool_integrate.py — Integration tests for the pool integration endpoint.

POST /api/pool/integrate/{dtxsid} merges pool files into a unified BMDProject.
The actual integration (Java-backed) is mocked; we test the endpoint wiring:
  - Reads fingerprints and coverage matrix from disk
  - Calls integrate_pool (mocked)
  - Caches result in _integrated_pool and writes integrated.json
"""

import json

import pytest


@pytest.mark.integration
class TestPoolIntegrate:
    """POST /api/pool/integrate/{dtxsid} — merge pool files."""

    def _make_integrated(self):
        """Minimal integrated BMDProject for mock return."""
        return {
            "doseResponseExperiments": [
                {
                    "name": "BodyWeight_Male",
                    "experimentDescription": {
                        "platform": "Body Weight",
                        "data_type": "tox_study",
                    },
                    "probeResponses": [
                        {"probe": {"id": "SD5"}, "responses": [100, 110, 120]},
                    ],
                },
            ],
            "_meta": {
                "source_files": {
                    "Body Weight": {"filename": "body_weight_truth_male.txt"},
                },
            },
        }

    def test_integrate_returns_200(self, golden_50469320, mock_bmdx_pipe):
        """
        Given a validated session with fingerprints and coverage matrix,
        integration should succeed and return 200.
        """
        from fastapi.testclient import TestClient
        from background_server import app

        mock_bmdx_pipe.integrate_pool.return_value = self._make_integrated()

        client = TestClient(app)

        # First validate to populate fingerprints + coverage matrix
        resp = client.post("/api/pool/validate/DTXSID50469320")
        assert resp.status_code == 200, f"Validate failed: {resp.text}"

        # Then integrate
        resp = client.post(
            "/api/pool/integrate/DTXSID50469320",
            json={"identity": {"name": "Test", "casrn": "123-45-6", "dtxsid": "DTXSID50469320"}},
        )
        assert resp.status_code == 200, f"Integrate failed: {resp.text}"

    def test_integrate_caches_in_memory(self, golden_50469320, mock_bmdx_pipe):
        """Integration should cache the result in _integrated_pool dict.

        Note: integrated.json is written by bmdx_pipe.integrate_pool() itself
        (which is mocked here), so we verify the in-memory cache instead.
        """
        from fastapi.testclient import TestClient
        from background_server import app
        import pool_orchestrator

        mock_bmdx_pipe.integrate_pool.return_value = self._make_integrated()

        client = TestClient(app)
        client.post("/api/pool/validate/DTXSID50469320")
        client.post(
            "/api/pool/integrate/DTXSID50469320",
            json={"identity": {"name": "Test", "casrn": "123-45-6", "dtxsid": "DTXSID50469320"}},
        )

        assert "DTXSID50469320" in pool_orchestrator._integrated_pool
        cached = pool_orchestrator._integrated_pool["DTXSID50469320"]
        assert "doseResponseExperiments" in cached

    def test_integrate_populates_memory(self, golden_50469320, mock_bmdx_pipe):
        """Integration should cache the result in _integrated_pool."""
        from fastapi.testclient import TestClient
        from background_server import app
        import pool_orchestrator

        mock_bmdx_pipe.integrate_pool.return_value = self._make_integrated()

        client = TestClient(app)
        client.post("/api/pool/validate/DTXSID50469320")
        client.post(
            "/api/pool/integrate/DTXSID50469320",
            json={"identity": {"name": "Test", "casrn": "123-45-6", "dtxsid": "DTXSID50469320"}},
        )

        assert "DTXSID50469320" in pool_orchestrator._integrated_pool

    def test_integrate_without_validation_returns_400(self, sessions_dir):
        """Integration without prior validation should fail (no fingerprints)."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)

        # Create session dir with files/ but no validation_report.json
        dtxsid = "DTXSID_NOVAL"
        files_dir = sessions_dir / dtxsid / "files"
        files_dir.mkdir(parents=True)
        (files_dir / "dummy.txt").write_text("data")

        resp = client.post(f"/api/pool/integrate/{dtxsid}", json={})
        assert resp.status_code == 400

    def test_integrate_without_files_returns_404(self, sessions_dir):
        """Integration with no files/ directory returns 404."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        (sessions_dir / "DTXSID_EMPTY").mkdir(parents=True)

        resp = client.post("/api/pool/integrate/DTXSID_EMPTY", json={})
        assert resp.status_code == 404
