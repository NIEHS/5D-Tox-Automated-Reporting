"""Approved experiment metadata survives re-integration and reaches genomics.

Approval used to live only inside integrated.json, which every integration
rebuilds — a `--reintegrate` re-inferred NIEHS-13's heart experiment
("rat_4D_HE_No0") as blood.  Now the approval record stores the descriptions,
integration re-applies them (bmdx_pipe integrate_pool(approved_metadata=…)),
and approving reconciles the genomics sidecar's organ at once.
"""

import json
from unittest.mock import patch

import pytest

HE = "rat_4D_HE_No0"


def _integrated(organ):
    return {
        "name": "integrated",
        "doseResponseExperiments": [{
            "name": HE,
            "treatments": [{"name": "A1", "dose": 0.0}, {"name": "A2", "dose": 10.0}],
            "experimentDescription": {"organ": organ, "sex": "female", "species": "rat"},
            "probeResponses": [{"probe": {"id": "DERA_8462"}, "responses": [1.0, 2.0]}],
        }],
        "_meta": {"dtxsid": "DTXSID1020431", "integrated_at": "2026-10-07T00:00:00+00:00", "source_files": {}},
    }


@pytest.mark.integration
def test_approval_stores_descriptions_and_reconciles_the_genomics_sidecar(sessions_dir):
    from fastapi.testclient import TestClient
    from web_routes.background_server import app

    d = "DTXSID1020431"
    s = sessions_dir / d
    s.mkdir(parents=True)
    (s / "integrated.json").write_text(json.dumps(_integrated("blood")))
    (s / "genomics.sidecar.json").write_text(json.dumps(
        {"experiments": [{"name": HE, "organ": "Blood", "sex": "Female", "genes": []}]}))

    approved = {HE: {"organ": "heart", "sex": "female", "species": "rat"}}
    with patch("bmdx_pipe.export_integrated_bm2"):
        r = TestClient(app).post(f"/api/experiment-metadata/{d}", json={"metadata": approved})
    assert r.status_code == 200, r.text

    record = json.loads((s / "metadata_approved.json").read_text())
    assert record["metadata"][HE]["organ"] == "heart"
    sidecar = json.loads((s / "genomics.sidecar.json").read_text())
    assert sidecar["experiments"][0]["organ"] == "Heart"


@pytest.mark.integration
def test_integration_reapplies_the_approved_descriptions(given_pfhxsam, mock_bmdx_pipe):
    from fastapi.testclient import TestClient
    from web_routes.background_server import app

    d = "DTXSID50469320"
    approved = {HE: {"organ": "heart", "sex": "female"}}
    mock_bmdx_pipe.integrate_pool.return_value = _integrated("heart")
    client = TestClient(app)
    assert client.post(f"/api/pool/validate/{d}").status_code == 200
    (given_pfhxsam / "metadata_approved.json").write_text(json.dumps(
        {"approved_at": "2026-10-07T00:00:00+00:00", "experiments_updated": 1, "metadata": approved}))
    r = client.post(f"/api/pool/integrate/{d}",
                    json={"identity": {"name": "Test", "casrn": "123-45-6", "dtxsid": d}})
    assert r.status_code == 200, r.text
    assert mock_bmdx_pipe.integrate_pool.call_args.kwargs["approved_metadata"] == approved
