"""
test_session_lifecycle.py — Integration tests for session load/approve/unapprove/history.

Uses the golden DTXSID70191136 session (with approved background + 2 bm2 sections)
to verify:
  - Session load returns existing approved sections
  - Approve creates section files on disk
  - Unapprove removes them
  - Version history is maintained
  - Non-existent session returns exists=False
"""

import json

import pytest


DTXSID_70 = "DTXSID70191136"
DTXSID_50 = "DTXSID50469320"


@pytest.mark.integration
class TestSessionLoad:
    """GET /api/session/{dtxsid} — load a previously saved session."""

    def test_nonexistent_session(self, sessions_dir):
        """A DTXSID with no session directory returns exists=False."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        resp = client.get("/api/session/DTXSID_NONEXISTENT")
        assert resp.status_code == 200

        data = resp.json()
        assert data["exists"] is False

    def test_golden_session_loads(self, golden_70191136, mock_bmdx_pipe):
        """
        The golden DTXSID70191136 session has a background section and
        two approved bm2 sections.  Session load should return them.
        """
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        resp = client.get(f"/api/session/{DTXSID_70}")
        assert resp.status_code == 200

        data = resp.json()
        assert data["exists"] is True

        # Background section should be loaded
        assert data["background"] is not None
        assert "paragraphs" in data["background"]

        # Two bm2 sections should be present
        bm2 = data["bm2_sections"]
        assert "clinical-pathology" in bm2, f"Missing clinical-pathology. Keys: {list(bm2.keys())}"
        assert "organ-and-body-weights" in bm2, f"Missing organ-and-body-weights. Keys: {list(bm2.keys())}"

    def test_identity_loaded(self, golden_70191136, mock_bmdx_pipe):
        """Session load should include the chemical identity."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        resp = client.get(f"/api/session/{DTXSID_70}")
        data = resp.json()

        identity = data.get("identity")
        assert identity is not None
        assert identity.get("dtxsid") == DTXSID_70

    def test_pending_files_discovered(self, golden_70191136, mock_bmdx_pipe):
        """
        The golden session has .bm2 files in files/ — they should appear
        either as approved sections or pending files.
        """
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        resp = client.get(f"/api/session/{DTXSID_70}")
        data = resp.json()

        # .bm2 files with approved sections get re-registered; those without
        # appear as pending_files.  Either way, the files should be found.
        bm2_sections = data.get("bm2_sections", {})
        pending = data.get("pending_files", [])
        total_files = len(bm2_sections) + len(pending)
        assert total_files > 0, "No files found in session"


@pytest.mark.integration
class TestSessionApproveUnapprove:
    """POST /api/session/approve and /api/session/unapprove cycle."""

    def test_approve_creates_file(self, sessions_dir):
        """Approving a background section writes it to disk."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        dtxsid = "DTXSID_TEST"
        resp = client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "background",
            "data": {
                "paragraphs": ["Test paragraph."],
                "references": [],
            },
        })
        assert resp.status_code == 200

        # File should exist on disk
        path = sessions_dir / dtxsid / "background.json"
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["paragraphs"] == ["Test paragraph."]
        assert "approved_at" in data
        assert data["version"] == 1

    def test_unapprove_removes_file(self, sessions_dir):
        """Unapproving removes the section file."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        dtxsid = "DTXSID_TEST"

        # First approve
        client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "background",
            "data": {"paragraphs": ["Test."]},
        })
        assert (sessions_dir / dtxsid / "background.json").exists()

        # Then unapprove
        resp = client.post("/api/session/unapprove", json={
            "dtxsid": dtxsid,
            "section_type": "background",
        })
        assert resp.status_code == 200
        assert not (sessions_dir / dtxsid / "background.json").exists()

    def test_approve_methods_section(self, sessions_dir):
        """Approve a methods section — verifies non-background section types work."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        dtxsid = "DTXSID_TEST"
        resp = client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "methods",
            "data": {
                "sections": [{"heading": "Study Design", "paragraphs": ["..."]}],
            },
        })
        assert resp.status_code == 200
        assert (sessions_dir / dtxsid / "methods.json").exists()

    def test_approve_requires_dtxsid(self, sessions_dir):
        """Missing dtxsid returns 400."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        resp = client.post("/api/session/approve", json={
            "section_type": "background",
            "data": {},
        })
        assert resp.status_code == 400

    def test_approve_invalid_section_type(self, sessions_dir):
        """Invalid section_type returns 400."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        resp = client.post("/api/session/approve", json={
            "dtxsid": "DTXSID_TEST",
            "section_type": "invalid_type",
            "data": {},
        })
        assert resp.status_code == 400


@pytest.mark.integration
class TestSessionHistory:
    """GET /api/session/{dtxsid}/history/{section_key} — version history."""

    def test_two_approvals_produce_history(self, sessions_dir):
        """
        Approving a section twice should create version history:
        v1 in history/, v2 as current.
        """
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        dtxsid = "DTXSID_TEST"

        # Approve v1
        client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "background",
            "data": {"paragraphs": ["Version 1"]},
        })

        # Approve v2
        client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "background",
            "data": {"paragraphs": ["Version 2"]},
        })

        # Check history
        resp = client.get(f"/api/session/{dtxsid}/history/background")
        assert resp.status_code == 200

        history = resp.json()
        assert history["current_version"] == 2
        assert len(history["versions"]) == 2

        # The last version should be current
        assert history["versions"][-1]["is_current"] is True
        assert history["versions"][0]["is_current"] is False

    def test_history_returns_specific_version(self, sessions_dir):
        """Requesting a specific version returns its full content."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        dtxsid = "DTXSID_TEST"

        # Approve twice
        client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "background",
            "data": {"paragraphs": ["V1 text"]},
        })
        client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "background",
            "data": {"paragraphs": ["V2 text"]},
        })

        # Fetch v1 content
        resp = client.get(f"/api/session/{dtxsid}/history/background?version=1")
        assert resp.status_code == 200
        v1 = resp.json()
        assert v1["paragraphs"] == ["V1 text"]

        # Fetch v2 content (current)
        resp = client.get(f"/api/session/{dtxsid}/history/background?version=2")
        assert resp.status_code == 200
        v2 = resp.json()
        assert v2["paragraphs"] == ["V2 text"]

    def test_history_nonexistent_section_returns_404(self, sessions_dir):
        """Requesting history for a section that doesn't exist returns 404."""
        from fastapi.testclient import TestClient
        from background_server import app

        client = TestClient(app)
        # Create the session dir so it exists
        (sessions_dir / "DTXSID_TEST").mkdir(parents=True)

        resp = client.get("/api/session/DTXSID_TEST/history/background")
        assert resp.status_code == 404
