"""
Integration test for GET /api/workflow/{dtxsid}/state (ADR-0014 step 3).

Drives the REAL route + WorkflowEngine + DiskPoolStore over real session disk
(the golden fixture), exercising the server-side phase derivation end to end.

The load-bearing assertion is the DE-CONFLATION (ADR-0014 follow-up): with
integrated.json present but animal_report.json absent, the server reports
INTEGRATED — a state the JS caller collapsed away by feeding both
hasIntegrated/hasAnimalReport from !!data.animal_report. This is the one intended
behavior change of the port; the unit contract (workflow_phase_cases.json) pins
the pure function, this pins the route/caller wiring.
"""

import json

import pytest


@pytest.mark.integration
class TestWorkflowStateRoute:
    def test_validated_before_integration(self, golden_50469320):
        # The golden fixture ships a clean validation_report.json (0 errors,
        # coverage matrix present). We derive phase over THAT persisted report
        # rather than re-running Java validation — this test pins server-side
        # phase derivation, not the validator (which is exercised elsewhere and
        # flags this fixture's clinical-obs CSVs).
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        resp = client.get("/api/workflow/DTXSID50469320/state")
        assert resp.status_code == 200, resp.text
        state = resp.json()

        # files + clean validation report, nothing integrated → VALIDATED
        assert state["phase"] == "VALIDATED"
        assert state["artifacts"]["hasIntegrated"] is False
        assert state["artifacts"]["hasAnimalReport"] is False
        assert "INTEGRATE" in state["legal_actions"]

    def test_integrated_not_approved_deconfliction(self, golden_50469320):
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        # Simulate a completed integration: integrated.json exists, but the pool
        # has NOT been approved (no animal_report.json). The JS caller could not
        # represent this; the server must.
        (golden_50469320 / "integrated.json").write_text(
            json.dumps({"doseResponseExperiments": [], "_meta": {}}), encoding="utf-8"
        )

        resp = client.get("/api/workflow/DTXSID50469320/state")
        assert resp.status_code == 200, resp.text
        state = resp.json()

        assert state["phase"] == "INTEGRATED"
        assert state["artifacts"]["hasIntegrated"] is True
        assert state["artifacts"]["hasAnimalReport"] is False
        assert "APPROVE" in state["legal_actions"]

    def test_approved_when_animal_report_present(self, golden_50469320):
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        (golden_50469320 / "integrated.json").write_text(
            json.dumps({"doseResponseExperiments": [], "_meta": {}}), encoding="utf-8"
        )
        (golden_50469320 / "animal_report.json").write_text(
            json.dumps({"animals": []}), encoding="utf-8"
        )

        resp = client.get("/api/workflow/DTXSID50469320/state")
        assert resp.status_code == 200, resp.text
        assert resp.json()["phase"] == "APPROVED"
