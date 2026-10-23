"""Per-file pool removal (DELETE /api/pool/{dtxsid}/files/{filename}) and the
hardened pool reset (POST /api/pool/reset/{dtxsid})."""

import json

DTX = "DTXSID_TEST_POOL"


def _seed(sessions_dir):
    """A session with one pivoted data file (+ sidecar + parked original), one
    .bm2, a fingerprint cache naming them, and validation/derived artifacts."""
    d = sessions_dir / DTX
    files = d / "files"
    files.mkdir(parents=True)
    (files / "body_weight_truth_male.txt").write_text("pivot")
    (files / "body_weight_truth_male.sidecar.json").write_text("{}")
    (files / "Gene_Expression.bm2").write_bytes(b"bm2")
    (d / "_originals").mkdir()
    (d / "_originals" / "body_weight_truth_male.csv").write_text("long")
    (d / "_fingerprints.json").write_text(json.dumps({
        "body_weight_truth_male.txt": {"filename": "body_weight_truth_male.txt"},
        "Gene_Expression.bm2": {"filename": "Gene_Expression.bm2"},
    }))
    (d / "identity.json").write_text(json.dumps({"name": "Test", "dtxsid": DTX}))
    (d / "validation_report.json").write_text("{}")
    (d / "integrated.json").write_text("{}")
    (d / "_cache_ntp_abc.json").write_text("{}")
    (d / "_cache_bmds_def.json").write_text("{}")
    (d / "genomics.sidecar.json").write_text("{}")
    (d / "views").mkdir()
    (d / "views" / "default.yaml").write_text("charts: []\n")
    return d


def test_remove_file_takes_companions_and_scrubs_cache(client, sessions_dir):
    d = _seed(sessions_dir)
    r = client.delete(f"/api/pool/{DTX}/files/body_weight_truth_male.txt")
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["removed"]) == sorted([
        "body_weight_truth_male.txt",
        "body_weight_truth_male.sidecar.json",
        "body_weight_truth_male.csv",
    ])
    # gone from the pool …
    assert not (d / "files" / "body_weight_truth_male.txt").exists()
    assert not (d / "files" / "body_weight_truth_male.sidecar.json").exists()
    assert not (d / "_originals" / "body_weight_truth_male.csv").exists()
    # … but recoverable
    trash = d / body["moved_to"]
    assert (trash / "body_weight_truth_male.txt").read_text() == "pivot"
    # other files untouched; fingerprint cache scrubbed of the removed file only
    assert (d / "files" / "Gene_Expression.bm2").exists()
    cache = json.loads((d / "_fingerprints.json").read_text())
    assert list(cache) == ["Gene_Expression.bm2"]
    # pool had progressed → validation/integration invalidated
    assert body["pool_invalidated"] is True
    assert not (d / "validation_report.json").exists()
    assert not (d / "integrated.json").exists()


def test_remove_file_rejects_sidecar_traversal_and_missing(client, sessions_dir):
    _seed(sessions_dir)
    base = f"/api/pool/{DTX}/files/"
    assert client.delete(base + "body_weight_truth_male.sidecar.json").status_code == 400
    assert client.delete(base + "..%2Fidentity.json").status_code in (400, 404)
    assert client.delete(base + "nope.txt").status_code == 400
    assert client.delete("/api/pool/DTXSID_NO_SUCH/files/x.txt").status_code == 404
    assert (sessions_dir / DTX / "identity.json").exists()


def test_reset_clears_derived_state_keeps_identity_and_views(client, sessions_dir):
    d = _seed(sessions_dir)
    r = client.post(f"/api/pool/reset/{DTX}")
    assert r.status_code == 200, r.text
    for gone in ("files", "_originals", "_fingerprints.json", "validation_report.json",
                 "integrated.json", "_cache_ntp_abc.json", "_cache_bmds_def.json",
                 "genomics.sidecar.json"):
        assert not (d / gone).exists(), gone
    assert (d / "identity.json").exists()
    assert (d / "views" / "default.yaml").exists()


def test_remove_and_reset_are_refused_on_a_study_with_no_files(client, sessions_dir):
    (sessions_dir / "DTXSID_NOFILES").mkdir()
    r = client.delete("/api/pool/DTXSID_NOFILES/files/x.csv")
    assert r.status_code == 409 and "REMOVE_FILE refused" in r.json()["error"]
    r = client.post("/api/pool/reset/DTXSID_NOFILES")
    assert r.status_code == 409 and "RESET refused" in r.json()["error"]


def test_reset_deletes_the_integration_basis(client, sessions_dir):
    d = _seed(sessions_dir)
    (d / "integration_basis.json").write_text('{"basis": "x"}')
    assert client.post(f"/api/pool/reset/{DTX}").status_code == 200
    assert not (d / "integration_basis.json").exists()


def test_a_guard_refusal_reaches_a_client_explained(sessions_dir):
    """The refusal a guarded act raises reaches a web client in the app's
    {"error": message} body with its explanation beside it (code, say, fix:
    web_routes.refusal_response)."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    from safeguards.guarded import validate_step
    from web_routes.refusal_response import refusal_response
    from workflow.errors import StepError
    from workflow.store import DiskPoolStore

    router = APIRouter()

    @router.post("/t/{dtxsid}")
    def validate(dtxsid: str):
        try:
            return validate_step(dtxsid, DiskPoolStore())
        except StepError as e:
            return refusal_response(e)

    app = FastAPI()
    app.include_router(router)
    (sessions_dir / "DTXSID_NOFILES").mkdir()
    r = TestClient(app).post("/t/DTXSID_NOFILES")
    assert r.status_code == 409
    body = r.json()
    assert body["error"].startswith("VALIDATE refused for DTXSID_NOFILES")
    assert (body["code"], body["fix"]) == ("phase_not_allowed", "files")
    assert body["say"] == ("Checking the files isn't possible yet. This study has no data "
                           "files yet. Add the study's files first.")
