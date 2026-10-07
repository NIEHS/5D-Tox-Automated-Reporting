"""A stated study design (generate_report --design) survives re-integration.

The design facts BPAF and Triclosan's data do not record (strain, route,
vehicle, duration) were written onto integrated.json only, which every
integration rebuilds: a --reintegrate put the reports back on the logged
standard-design fallback.  Now they are kept in study_design.json and
integration re-applies them.
"""

import json
from unittest.mock import patch

import pytest

from tests.integration.test_approved_metadata_roundtrip import _integrated

DESIGN = {"species": "rat", "strain": "Sprague-Dawley", "articleRoute": "oral",
          "administrationMeans": "gavage", "articleVehicle": "corn oil", "studyDuration": "5d"}


@pytest.mark.integration
def test_integration_reapplies_the_stated_design(given_pfhxsam, mock_bmdx_pipe):
    from fastapi.testclient import TestClient
    from web_routes.background_server import app

    d = "DTXSID50469320"
    mock_bmdx_pipe.integrate_pool.return_value = _integrated("heart")
    client = TestClient(app)
    assert client.post(f"/api/pool/validate/{d}").status_code == 200
    (given_pfhxsam / "study_design.json").write_text(json.dumps(
        {"fields": DESIGN, "recorded_at": "2026-10-07T00:00:00+00:00"}))
    with patch("bmdx_pipe.export_integrated_bm2"):
        r = client.post(f"/api/pool/integrate/{d}",
                        json={"identity": {"name": "Test", "casrn": "123-45-6", "dtxsid": d}})
    assert r.status_code == 200, r.text

    on_disk = json.loads((given_pfhxsam / "integrated.json").read_text())
    ed = on_disk["doseResponseExperiments"][0]["experimentDescription"]
    assert {k: ed[k] for k in DESIGN} == DESIGN
    assert ed["organ"] == "heart"  # inferred metadata the design does not name is kept


@pytest.mark.integration
def test_no_stated_design_leaves_integration_alone(given_pfhxsam, mock_bmdx_pipe):
    from workflow.steps import reapply_study_design
    from workflow.store import DiskPoolStore

    assert reapply_study_design("DTXSID50469320", DiskPoolStore()) == 0
