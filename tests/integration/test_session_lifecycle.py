"""
test_session_lifecycle.py — Integration tests for session load/approve/unapprove/history.

Uses the golden DTXSID70191136 session (with approved background + 2 bm2 sections)
to verify:
  - Session load returns existing approved sections
  - Approve accepts a section file as it is (fenced, C2 D5)
  - Unapprove reopens it, keeping its content
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
        from web_routes.background_server import app

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
        from web_routes.background_server import app

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
        from web_routes.background_server import app

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
        from web_routes.background_server import app

        client = TestClient(app)
        resp = client.get(f"/api/session/{DTXSID_70}")
        data = resp.json()

        # .bm2 files with approved sections get re-registered; those without
        # appear as pending_files.  Either way, the files should be found.
        bm2_sections = data.get("bm2_sections", {})
        pending = data.get("pending_files", [])
        total_files = len(bm2_sections) + len(pending)
        assert total_files > 0, "No files found in session"


def _seed(sessions_dir, dtxsid, key, content):
    """A section file as Process or generation leaves it (C2 D5: the approve
    route accepts a file; it no longer creates one from the posted content)."""
    d = sessions_dir / dtxsid
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.json").write_text(json.dumps({"version": 1, **content}))
    return d / f"{key}.json"


@pytest.mark.integration
class TestSessionApproveUnapprove:
    """POST /api/session/approve and /api/session/unapprove cycle."""

    def test_approve_accepts_the_file(self, sessions_dir):
        """Approving a background section accepts its file as it is."""
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        dtxsid = "DTXSID_TEST"
        path = _seed(sessions_dir, dtxsid, "background",
                     {"paragraphs": ["Test paragraph."], "references": []})
        resp = client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "background",
            "data": {
                "paragraphs": ["Test paragraph."],
                "references": [],
            },
        })
        assert resp.status_code == 200

        data = json.loads(path.read_text())
        assert data["paragraphs"] == ["Test paragraph."]
        assert data["approved"] is True
        assert "approved_at" in data
        assert data["version"] == 1

    def test_unapprove_preserves_content_and_clears_flag(self, sessions_dir):
        """Unapproving preserves the section file but flips approved=False.

        Per commit 8a20a9f ("Decouple disk persistence from approval"),
        unapprove is a UI lock-state flip — it keeps the on-disk content so
        the user can re-approve without regenerating.  Deletion is the
        separate /api/session/discard-section endpoint. Since C2 (D3) the
        reason is required.
        """
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        dtxsid = "DTXSID_TEST"
        path = _seed(sessions_dir, dtxsid, "background", {"paragraphs": ["Test."]})

        # First approve
        client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "background",
            "data": {"paragraphs": ["Test."]},
        })
        assert json.loads(path.read_text())["approved"] is True

        # Then unapprove — content stays, flag flips to False
        resp = client.post("/api/session/unapprove", json={
            "dtxsid": dtxsid,
            "section_type": "background",
            "reason": "check the references",
        })
        assert resp.status_code == 200
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["approved"] is False
        assert data["paragraphs"] == ["Test."]

    def test_approve_methods_section(self, sessions_dir):
        """Approve a methods section — verifies non-background section types work."""
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        dtxsid = "DTXSID_TEST"
        content = {"sections": [{"heading": "Study Design", "paragraphs": ["..."]}]}
        path = _seed(sessions_dir, dtxsid, "methods", content)
        resp = client.post("/api/session/approve", json={
            "dtxsid": dtxsid,
            "section_type": "methods",
            "data": content,
        })
        assert resp.status_code == 200
        assert json.loads(path.read_text())["approved"] is True

    def test_approve_materialized_bm2_section_by_slug(self, sessions_dir):
        """A materialized apical section (bm2_<slug>.json, no .bm2 filename) is
        approvable via bm2_slug — the body the Sections screen sends."""
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        path = _seed(sessions_dir, "DTXSID_TEST", "bm2_body-weight",
                     {"title": "Body Weight", "narrative": ["Text."], "approved": False})
        resp = client.post("/api/session/approve", json={
            "dtxsid": "DTXSID_TEST",
            "section_type": "bm2",
            "bm2_slug": "body-weight",
            "data": {"title": "Body Weight", "narrative": ["Text."], "approved": False},
        })
        assert resp.status_code == 200, resp.text
        data = json.loads(path.read_text())
        assert data["approved"] is True
        assert data["narrative"] == ["Text."]

    def test_approve_bm2_rejects_unsafe_slug(self, sessions_dir):
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        resp = client.post("/api/session/approve", json={
            "dtxsid": "DTXSID_TEST",
            "section_type": "bm2",
            "bm2_slug": "../escape",
            "data": {"narrative": ["x"]},
        })
        assert resp.status_code == 400

    def test_approve_requires_dtxsid(self, sessions_dir):
        """Missing dtxsid returns 400."""
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        resp = client.post("/api/session/approve", json={
            "section_type": "background",
            "data": {},
        })
        assert resp.status_code == 400

    def test_approve_invalid_section_type(self, sessions_dir):
        """Invalid section_type returns 400."""
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

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

    @staticmethod
    def _two_versions(dtxsid, first, second):
        """Two versions of a background, as generation writes them (through the
        section write gate), the second one accepted."""
        from workflow.section_writes import write_section
        from workflow.steps import accept_section_step
        from workflow.store import DiskPoolStore
        for text in (first, second):
            write_section(dtxsid, "background", {"paragraphs": [text], "source": "model"},
                          DiskPoolStore(), act="save", actor="person", author="model")
        accept_section_step(dtxsid, "background", DiskPoolStore())

    def test_two_versions_produce_history(self, sessions_dir):
        """
        Two versions of a section: v1 in history/, v2 as current.
        """
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        dtxsid = "DTXSID_TEST"
        self._two_versions(dtxsid, "Version 1", "Version 2")

        # Check history
        resp = client.get(f"/api/session/{dtxsid}/history/background")
        assert resp.status_code == 200

        history = resp.json()
        assert history["current_version"] == 2
        assert len(history["versions"]) == 2

        # The last version should be current
        assert history["versions"][-1]["is_current"] is True
        assert history["versions"][0]["is_current"] is False
        assert history["versions"][-1]["approved_at"]

    def test_history_returns_specific_version(self, sessions_dir):
        """Requesting a specific version returns its full content."""
        from fastapi.testclient import TestClient
        from web_routes.background_server import app

        client = TestClient(app)
        dtxsid = "DTXSID_TEST"
        self._two_versions(dtxsid, "V1 text", "V2 text")

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
        from web_routes.background_server import app

        client = TestClient(app)
        # Create the session dir so it exists
        (sessions_dir / "DTXSID_TEST").mkdir(parents=True)

        resp = client.get("/api/session/DTXSID_TEST/history/background")
        assert resp.status_code == 404
