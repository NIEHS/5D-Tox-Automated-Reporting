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
