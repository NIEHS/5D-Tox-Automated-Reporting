"""
Integration tests for the wizard convenience routes (web_routes/wizard_routes.py).

These are the two read-only helpers the from-scratch wizard UI needs that no
existing route provides: listing the uploaded files in a session, and returning
the detected per-file fingerprint classification for the confirm-metadata screen.

Everything else the wizard drives (validate/integrate/confirm/process/state) is
an existing route covered by other tests; this only pins the new surface.
"""

import pytest


@pytest.mark.integration
class TestWizardRoutes:
    def test_files_lists_uploaded_study_files(self, golden_50469320):
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        resp = client.get("/api/wizard/DTXSID50469320/files")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # The golden fixture ships a populated files/ dir.
        assert body["count"] > 0
        assert body["count"] == len(body["files"])
        # Every entry has a name + size, and the known bm2 is present.
        names = {f["name"] for f in body["files"]}
        assert "Body weight.bm2" in names
        for f in body["files"]:
            assert isinstance(f["name"], str) and f["name"]
            assert isinstance(f["size"], int) and f["size"] >= 0

    def test_files_empty_for_unknown_session(self, sessions_dir):
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        resp = client.get("/api/wizard/DTXSID_DOES_NOT_EXIST/files")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {"files": [], "count": 0}

    def test_integrated_tree_slim_structure(self, golden_50469320):
        import json

        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        # The tree endpoint needs integrated.json; the base golden fixture ships
        # files+validation but not integration, so synthesize a minimal one.
        (golden_50469320 / "integrated.json").write_text(
            json.dumps(
                {
                    "name": "integrated",
                    "doseResponseExperiments": [
                        {
                            "name": "liver_male",
                            "experimentDescription": {
                                "platform": "S1500+_rat",
                                "sex": "male",
                                "organ": "liver",
                                "provider": "BioSpyder",
                            },
                            "treatments": [
                                {"name": "a", "dose": 0.0},
                                {"name": "b", "dose": 0.0},
                                {"name": "c", "dose": 5.0},
                            ],
                            "probeResponses": [
                                {"probe": {"id": "GeneA"}, "responses": [1.0, 2.0, 3.0]},
                                {"probe": {"id": "GeneB"}, "responses": [4.0, 5.0, 6.0]},
                            ],
                        }
                    ],
                    "_meta": {
                        "dtxsid": "DTXSID50469320",
                        "integrated_at": "2026-01-01T00:00:00",
                        "source_files": {},
                    },
                }
            ),
            encoding="utf-8",
        )

        client = TestClient(app)
        resp = client.get("/api/integrated-tree/DTXSID50469320")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["experiment_count"] == 1
        node = body["experiments"][0]
        assert node["platform"] == "S1500+_rat"
        assert node["sex"] == "male"
        assert node["organ"] == "liver"
        assert node["probe_count"] == 2
        assert node["endpoints"] == ["GeneA", "GeneB"]
        # Dose levels de-duplicated from per-animal treatments.
        assert node["doses"] == [0.0, 5.0]
        # The heavy numeric `responses` arrays must NOT be shipped.
        assert "responses" not in json.dumps(body)

    def test_fingerprints_returns_classification_rows(self, golden_50469320):
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        resp = client.get("/api/wizard/DTXSID50469320/fingerprints")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["count"] == len(body["fingerprints"])
        assert body["count"] > 0
        # Each row carries the exact keys the confirm-metadata screen reads.
        for row in body["fingerprints"]:
            assert set(row.keys()) == {
                "file_id",
                "filename",
                "file_type",
                "platform",
                "data_type",
                "sexes",
            }
            assert isinstance(row["sexes"], list)
        # Rows are sorted by filename for a stable table.
        names = [r["filename"] for r in body["fingerprints"]]
        assert names == sorted(names)
