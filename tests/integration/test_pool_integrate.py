"""
test_pool_integrate.py — Integration tests for the pool integration endpoint.

POST /api/pool/integrate/{dtxsid} merges pool files into a unified BMDProject.
The actual integration (Java-backed) is mocked; we test the endpoint wiring:
  - Reads fingerprints and coverage matrix from disk
  - Calls integrate_pool (mocked)
  - Caches result in _integrated_pool and writes integrated.json
"""


import pytest


@pytest.mark.integration
class TestPoolIntegrate:
    """POST /api/pool/integrate/{dtxsid} — merge pool files."""

    def _make_integrated(self):
        """Minimal integrated BMDProject for mock return."""
        # schema-valid: integration checks the merged dataset before recording it
        return {
            "name": "integrated",
            "doseResponseExperiments": [
                {
                    "name": "BodyWeight_Male",
                    "treatments": [{"name": "0", "dose": 0.0}, {"name": "1", "dose": 4.0},
                                   {"name": "2", "dose": 12.0}],
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
                "dtxsid": "DTXSID50469320",
                "integrated_at": "2026-10-17T00:00:00+00:00",
                "source_files": {
                    "Body Weight": {"file_id": "body_weight_truth_male.txt",
                                    "filename": "body_weight_truth_male.txt",
                                    "tier": "txt_csv", "file_count": 1},
                },
            },
        }

    def test_integrate_returns_200(self, niehs10, mock_bmdx_pipe):
        """
        Given a validated session with fingerprints and coverage matrix,
        integration should succeed and return 200.
        """
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

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

    def test_integrate_caches_in_memory(self, niehs10, mock_bmdx_pipe):
        """Integration should cache the result in _integrated_pool dict.

        Note: integrated.json is written by bmdx_pipe.integrate_pool() itself
        (which is mocked here), so we verify the in-memory cache instead.
        """
        from fastapi.testclient import TestClient
        from web_routes.background_server import app
        import pipeline.pool_orchestrator as pool_orchestrator

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

    def test_integrate_populates_memory(self, niehs10, mock_bmdx_pipe):
        """Integration should cache the result in _integrated_pool."""
        from fastapi.testclient import TestClient
        from web_routes.background_server import app
        import pipeline.pool_orchestrator as pool_orchestrator

        mock_bmdx_pipe.integrate_pool.return_value = self._make_integrated()

        client = TestClient(app)
        client.post("/api/pool/validate/DTXSID50469320")
        client.post(
            "/api/pool/integrate/DTXSID50469320",
            json={"identity": {"name": "Test", "casrn": "123-45-6", "dtxsid": "DTXSID50469320"}},
        )

        assert "DTXSID50469320" in pool_orchestrator._integrated_pool

    def test_integrate_without_validation_returns_409(self, sessions_dir):
        """Integration without prior validation is refused by the phase guard
        (UPLOADED: validate first), before anything is read."""
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)

        # Create session dir with files/ but no validation_report.json
        dtxsid = "DTXSID_NOVAL"
        files_dir = sessions_dir / dtxsid / "files"
        files_dir.mkdir(parents=True)
        (files_dir / "dummy.txt").write_text("data")

        resp = client.post(f"/api/pool/integrate/{dtxsid}", json={})
        assert resp.status_code == 409
        assert "phase UPLOADED" in resp.json()["error"]

    def test_integrate_without_files_returns_409(self, sessions_dir):
        """Integration with no files is refused by the phase guard (EMPTY)."""
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        (sessions_dir / "DTXSID_EMPTY").mkdir(parents=True)

        resp = client.post("/api/pool/integrate/DTXSID_EMPTY", json={})
        assert resp.status_code == 409
        assert "phase EMPTY" in resp.json()["error"]

    def test_reintegration_withdraws_the_data_approval(self, niehs10, mock_bmdx_pipe):
        """Re-integrating an approved study archives its data approval and says so."""
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        mock_bmdx_pipe.integrate_pool.return_value = self._make_integrated()
        client = TestClient(app)
        assert client.post("/api/pool/validate/DTXSID50469320").status_code == 200
        ident = {"identity": {"name": "Test", "casrn": "123-45-6", "dtxsid": "DTXSID50469320"}}
        first = client.post("/api/pool/integrate/DTXSID50469320", json=ident).json()
        assert first["approval_withdrawn"] is False
        (niehs10 / "integrated.json").write_text("{}")   # the mock writes none
        (niehs10 / "animal_report.json").write_text("{}")
        state = client.get("/api/workflow/DTXSID50469320/state").json()
        assert (state["phase"], state["artifacts"]["integration"]) == ("APPROVED", "current")

        again = client.post("/api/pool/integrate/DTXSID50469320", json=ident).json()
        assert again["approval_withdrawn"] is True
        assert not (niehs10 / "animal_report.json").exists()
        assert list((niehs10 / "history" / "_data_approval").iterdir())
        assert client.get("/api/workflow/DTXSID50469320/state").json()["phase"] == "INTEGRATED"
