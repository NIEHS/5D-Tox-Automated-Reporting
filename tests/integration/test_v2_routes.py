"""
Integration tests for the new interface's shared routes (web_routes/v2_routes.py)
and the /app mount (web_routes/app_mount.py), through the FastAPI test client
against a scratch SESSIONS_DIR.

  * GET /api/v2/studies/{id}/state: the read model, and that reading it leaves
    the sessions directory exactly as it was (the side-effect test);
  * the error envelope on every /api/v2/ failure, for each mapped exception,
    while the old routes keep their own shape;
  * GET /api/v2/vocabularies;
  * the bundle at /app with its single-page fallback.
"""

import json
from pathlib import Path

import pytest

from workflow.errors import GuardViolation, StepError


def _snapshot(root: Path) -> dict:
    """Every path under root (dotfiles included) with its size and mtime."""
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*"))}


@pytest.fixture
def api():
    from fastapi.testclient import TestClient
    from web_routes.background_server import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# The state read model
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestStudyState:
    def test_state_of_a_validated_study(self, given_pfhxsam, api):
        resp = api.get("/api/v2/studies/DTXSID50469320/state")
        assert resp.status_code == 200, resp.text
        state = resp.json()
        assert state["id"] == "DTXSID50469320" and state["exists"] is True
        assert state["phase"] == "VALIDATED"
        assert "INTEGRATE" in state["legal_actions"]
        assert state["processed"] is False
        assert {"method", "definition"} <= set(state["pins"])
        assert state["pins"]["definition"]["source"] == "study"   # NIEHS-10's own definition
        assert state["readiness"]["publish"]["ready"] is True
        assert "data_approval" not in state["readiness"] and "run" not in state
        keys = [s["key"] for s in state["sections"]]
        assert "summary" in keys and "background" in keys

    def test_reading_the_state_changes_nothing_on_disk(self, given_pfhxsam, api):
        """The C4 guarantee for this read: no folder created, no fingerprint
        re-scan, no upload registered, nothing pinned, no provenance line."""
        from pipeline.pool_globals import get_pool_fingerprints

        sessions = given_pfhxsam.parent
        # Give the study what a later step would leave, so every reader runs.
        (given_pfhxsam / "summary.json").write_text(json.dumps(
            {"approved": True, "facts": ["final", "protected"], "version": 1, "source": "generated"}))
        (given_pfhxsam / "identity.json").write_text(json.dumps(
            {"name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1", "abbreviation": "PFHxSAm"}))
        (given_pfhxsam / "integrated.json").write_text(json.dumps({"bMDResult": []}))
        (given_pfhxsam / "_cache_ntp_0.json").write_text("{}")
        get_pool_fingerprints().clear()           # a cold server

        before = _snapshot(sessions)
        for path in ("/api/v2/studies/DTXSID50469320/state",
                     "/api/v2/studies/DTXSID5046932O/state",     # letter O for a zero
                     "/api/v2/studies/DTXSID9999999/state"):
            assert api.get(path).status_code == 200
        assert _snapshot(sessions) == before
        assert sorted(p.name for p in sessions.iterdir()) == ["DTXSID50469320"]
        assert get_pool_fingerprints() == {}      # nothing scanned into the cache
        assert not (given_pfhxsam / "method_profile.json").exists()
        assert not (given_pfhxsam / "document_definition.json").exists()

    def test_a_study_that_does_not_exist(self, sessions_dir, api):
        resp = api.get("/api/v2/studies/DTXSID5046932O/state")
        assert resp.status_code == 200
        assert resp.json() == {"id": "DTXSID5046932O", "exists": False}
        assert not (sessions_dir / "DTXSID5046932O").exists()

    def test_a_report_over_several_studies_lists_its_members(self, sessions_dir, api):
        (sessions_dir / "DTXSID1").mkdir()
        (sessions_dir / "DTXSID1" / "studies.json").write_text(
            json.dumps({"rat": "DTXSID1_rat", "mouse": "DTXSID1_mouse"}))
        (sessions_dir / "DTXSID1_rat").mkdir()
        resp = api.get("/api/v2/studies/DTXSID1/state")
        assert resp.status_code == 200, resp.text
        members = resp.json()["members"]
        assert [(m["key"], m["exists"]) for m in members] == [("rat", True), ("mouse", False)]
        assert members[0]["readiness"]["publish"]["ready"] is True


# ---------------------------------------------------------------------------
# The error envelope
# ---------------------------------------------------------------------------

def _envelope(resp, code, status):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"}
    err = body["error"]
    assert set(err) == {"code", "status", "message", "say", "fix", "details"}
    assert err["code"] == code and err["status"] == status
    assert err["say"] and err["message"]
    return err


@pytest.mark.integration
class TestErrorEnvelope:
    def test_a_malformed_id(self, sessions_dir, api):
        err = _envelope(api.get("/api/v2/studies/NOT-A-STUDY/state"), "invalid_study_id", 400)
        assert err["fix"] == "M1"
        assert "invalid session id" in err["message"]      # the backend's text, verbatim
        assert list(sessions_dir.iterdir()) == []

    def test_a_damaged_session_file(self, sessions_dir, api):
        (sessions_dir / "DTXSID1").mkdir()
        (sessions_dir / "DTXSID1" / "identity.json").write_text("{trunc")
        err = _envelope(api.get("/api/v2/studies/DTXSID1/state"), "damaged_session_file", 422)
        assert err["details"] == {"file": "DTXSID1/identity.json"}

    @pytest.mark.parametrize("exc,code,status", [
        (StepError("No integrated data found -- run integration first", 400), "not_integrated", 400),
        (StepError("No files directory found for this session", 404), "no_files", 404),
        (StepError("No 'methods' section to approve", 404), "section_not_found", 404),
        (StepError("Processing failed: RunApicalBmds failed", 500), "calculation_program_failed", 500),
        (GuardViolation("Advancing stale content toward final/published is refused "
                        "(currency BLOCK): re-bless it"), "stale_content", 409),
        (RuntimeError("boom"), "unexpected", 500),
    ])
    def test_each_mapped_exception(self, sessions_dir, api, monkeypatch, exc, code, status):
        import ui_api.read_model as read_model

        def raise_it(dtxsid, store=None):
            raise exc
        monkeypatch.setattr(read_model, "study_state", raise_it)
        err = _envelope(api.get("/api/v2/studies/DTXSID1/state"), code, status)
        assert err["message"] == (str(exc) if code != "unexpected" else "RuntimeError: boom")

    def test_pin_errors(self, sessions_dir, api, monkeypatch):
        from document_model.definition_pin import DefinitionPinError
        from pipeline.method_profile import MethodProfileError
        import ui_api.read_model as read_model

        for exc, code in ((MethodProfileError("DTXSID1: method profile 'x' changed since it "
                                              "was pinned (hash a → b)"), "method_profile_changed"),
                          (DefinitionPinError("DTXSID1: document_definition.yaml no longer "
                                              "matches its pin"), "definition_pin_changed")):
            monkeypatch.setattr(read_model, "study_state", lambda d, store=None, e=exc: (_ for _ in ()).throw(e))
            _envelope(api.get("/api/v2/studies/DTXSID1/state"), code, 409)

    def test_the_old_routes_keep_their_shape(self, sessions_dir, api):
        resp = api.get("/api/workflow/NOT-A-STUDY/state")
        assert resp.status_code == 400
        assert isinstance(resp.json()["error"], str)


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_vocabularies_route(api):
    resp = api.get("/api/v2/vocabularies")
    assert resp.status_code == 200
    body = resp.json()
    assert body["vocabularies"]["strain"]["depends_on"] == "species"
    assert "rat" in body["vocabularies"]["strain"]["by"]
    assert body["vocabularies"]["species"]["label"] == "Species"
    assert body["patterns"]["study_id"]["pattern"] == r"^DTXSID\d+$"


# ---------------------------------------------------------------------------
# The bundle at /app
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web_routes.app_mount import make_router

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app-1a2b.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside the bundle")
    app = FastAPI()
    app.include_router(make_router(dist))
    return TestClient(app), dist


@pytest.mark.integration
class TestAppMount:
    def test_a_file_of_the_bundle(self, app_client):
        client, _ = app_client
        resp = client.get("/app/assets/app-1a2b.js")
        assert resp.status_code == 200 and resp.text == "console.log(1)"
        assert "javascript" in resp.headers["content-type"]

    def test_any_other_path_is_the_app(self, app_client):
        client, _ = app_client
        for path in ("/app/", "/app/studies/DTXSID50469320/files", "/app/no-such.js"):
            resp = client.get(path)
            assert resp.status_code == 200 and "id=root" in resp.text, path
        assert client.get("/app", follow_redirects=False).headers["location"] == "/app/"

    def test_no_path_leaves_the_bundle(self, app_client):
        client, _ = app_client
        resp = client.get("/app/..%2Fsecret.txt")
        assert "outside the bundle" not in resp.text

    def test_not_built(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from web_routes.app_mount import make_router

        app = FastAPI()
        app.include_router(make_router(tmp_path / "missing"))
        resp = TestClient(app).get("/app/")
        assert resp.status_code == 404 and "not been built" in resp.json()["error"]

    def test_the_main_app_serves_app_and_leaves_api_alone(self, api):
        # /app is registered on the real app; /api/v2 is not swallowed by it.
        assert api.get("/app/studies").status_code in (200, 404)
        assert api.get("/api/v2/vocabularies").status_code == 200
