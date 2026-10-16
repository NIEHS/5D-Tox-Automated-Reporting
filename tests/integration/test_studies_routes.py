"""
Integration tests for module M1's routes (web_routes/studies_routes.py),
through the FastAPI test client against a scratch SESSIONS_DIR:

  * every endpoint of the M1 contract §2, and each of its refusals as the
    §4.2 envelope;
  * every GET leaves the store exactly as it was (the side-effect tests: the
    store is listed before and after each read);
  * R6: the upload routes refuse files into a companion or a report.

The chemical lookup is replaced; nothing reaches the network.
"""

import io
import json
from pathlib import Path

import pytest

NEW = "DTXSID7020182"
BPA = {"name": "Bisphenol A", "casrn": "80-05-7", "pubchem_cid": 6623,
       "molecular_formula": "C15H16O2", "molecular_weight": 228.29}


def _snapshot(root: Path) -> dict:
    """Every path under root (dotfiles included) with its size and mtime."""
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*"))}


def _session(root: Path, sid: str, **files) -> Path:
    d = root / sid
    d.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        name = name.replace("__", ".")
        if isinstance(data, (dict, list)):
            (d / name).write_text(json.dumps(data))
        else:
            (d / name).mkdir(exist_ok=True)
            (d / name / data).write_text("x")
    return d


def _envelope(resp, code, status):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"}
    err = body["error"]
    assert set(err) == {"code", "status", "message", "say", "fix", "details"}
    assert err["code"] == code and err["status"] == status
    assert err["say"] and err["message"]
    return err


def _app():
    """The app, with M1's router. Registering it in background_server is the
    orchestrator's change; until it lands, it is included here (once)."""
    from web_routes import studies_routes
    from web_routes.background_server import app
    if not any(getattr(r, "path", None) == "/api/v2/studies" for r in app.routes):
        app.include_router(studies_routes.router)
    return app


@pytest.fixture
def api():
    from fastapi.testclient import TestClient
    return TestClient(_app())


@pytest.fixture
def store(sessions_dir, tmp_path, monkeypatch):
    """A report over two studies with its companion, a study with a companion
    and a tool's copy, a study, a test folder, an empty folder, _prompts.
    OUTPUT_DIR is a scratch folder."""
    import common.paths
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(common.paths, "OUTPUT_DIR", out)
    _session(sessions_dir, "DTXSID1", identity__json={"name": "Dichloro", "casrn": "106-46-7"},
             studies__json={"rat": "DTXSID1_rat", "mouse": "DTXSID1_mouse"})
    _session(sessions_dir, "DTXSID1_rat", identity__json={"name": "Dichloro"}, files="a.txt")
    _session(sessions_dir, "DTXSID1_mouse", identity__json={"name": "Dichloro"}, files="a.txt")
    _session(sessions_dir, "DTXSID1_published", identity__json={"name": "Dichloro"},
             published_clone__json={"report": "NIEHS-13", "twin": "DTXSID1"})
    _session(sessions_dir, "DTXSID2", identity__json={"name": "Perfluoro", "casrn": "41997-13-1"},
             files="a.txt")
    _session(sessions_dir, "DTXSID2_published", identity__json={"name": "Perfluoro"},
             published_clone__json={"report": "NIEHS-10", "twin": "DTXSID2"})
    _session(sessions_dir, "DTXSID2_nb", identity__json={"name": "Perfluoro"}, files="a.txt")
    _session(sessions_dir, "DTXSID_TEST", method_profile__json={})
    (sessions_dir / "DTXSID9").mkdir()
    _session(sessions_dir, "_prompts", x__json={})
    return sessions_dir


@pytest.fixture
def resolver(monkeypatch):
    """The resolver replaced: DTXSID7020182 is Bisphenol A, listed under its
    DTXSID; anything else is not found. `calls` counts the lookups."""
    from narrative import chem_resolver as cr
    from workflow import studies

    studies._LOOKUPS.clear()
    calls = []

    def resolve(query, query_type="auto", ctx_api_key=""):
        calls.append(query)
        found = cr.ChemicalIdentity(dtxsid=query)
        if query == NEW:
            for k, v in BPA.items():
                setattr(found, k, v)
        else:
            found.resolution_notes.append(f"PubChem lookup failed for name '{query}'")
        return found

    monkeypatch.setattr(cr, "resolve_chemical", resolve)
    monkeypatch.setattr(cr, "pubchem_synonyms", lambda cid: ["Bisphenol A", NEW])
    monkeypatch.setattr(cr, "structure_png", lambda cid, size="300x300": b"\x89PNG\r\n\x1a\nfake")
    monkeypatch.delenv("CTX_API_KEY", raising=False)
    yield calls
    studies._LOOKUPS.clear()


def _create_body(api, dtxsid=NEW, **over):
    check = api.get(f"/api/v2/studies/{dtxsid}/creation-check").json()
    found = api.get(f"/api/v2/chemicals/{dtxsid}").json()
    body = {"dtxsid": dtxsid,
            "identity": {**{k: found["identity"][k] for k in ("name", "casrn", "pubchem_cid")},
                         "source": {"kind": "lookup", "service": found["service"],
                                    "looked_up_at": found["looked_up_at"]}},
            "confirmed": True, "dtxsid_checked_by_person": False,
            "format_seen": {"definition": check["format"]["definition"],
                            "hash": check["format"]["hash"]}}
    body.update(over)
    return body


# ---------------------------------------------------------------------------
# Reads, and that they change nothing
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestReads:
    def test_the_list(self, store, api):
        resp = api.get("/api/v2/studies")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == {"chemicals", "unassigned", "generated_at"}
        chems = {c["dtxsid"]: c for c in body["chemicals"]}
        assert set(chems) == {"DTXSID1", "DTXSID2"}
        assert [r["kind"] for r in chems["DTXSID1"]["sessions"]] == [
            "report", "member", "member", "companion"]
        assert [r["id"] for r in body["unassigned"]] == ["DTXSID_TEST"]
        row = chems["DTXSID2"]["sessions"][0]
        assert set(row) == {"id", "kind", "chemical_dtxsid", "chemical_dtxsid_from", "identity",
                            "stands", "processed", "last_changed", "format", "published",
                            "bookshelf", "relations", "actions", "notes"}
        assert row["stands"] == {"phase": "UPLOADED", "say": "Files brought in, not yet validated",
                                 "next": {"say": "Validate the files", "fix": "M2"}}

    def test_one_study(self, store, api):
        body = api.get("/api/v2/studies/DTXSID1").json()
        assert body["kind"] == "report"
        assert body["detail"]["banner"]["say"].startswith("A report over two studies")
        assert [m["id"] for m in body["detail"]["members"]] == ["DTXSID1_rat", "DTXSID1_mouse"]
        assert body["detail"]["format"]["chosen_by"] == "id"
        assert body["detail"]["format"]["pin"] == {"mode": None, "pinned_at": None, "pinned_by": None}

    def test_the_state_carries_kind_relations_and_stands(self, store, api):
        state = api.get("/api/v2/studies/DTXSID1_rat/state").json()
        row = api.get("/api/v2/studies/DTXSID1_rat").json()
        assert state["kind"] == row["kind"] == "member"
        assert state["chemical_dtxsid"] == "DTXSID1"
        assert state["relations"] == row["relations"]
        assert state["stands"] == row["stands"]

    def test_creation_check(self, store, api):
        body = api.get(f"/api/v2/studies/{NEW}/creation-check").json()
        assert body["exists"] is False and body["related_sessions"] == []
        assert body["format"]["source"] == "default" and body["format"]["hash"]
        exists = api.get("/api/v2/studies/DTXSID2/creation-check").json()
        assert exists["existing"] == {"id": "DTXSID2", "kind": "study"}
        assert api.get("/api/v2/studies/DTXSID9/creation-check").json()["exists"] is False

    def test_every_get_leaves_the_store_as_it_was(self, store, api, resolver):
        """C4 for M1's reads: no folder created, nothing written, nothing
        scanned into memory, whatever the id."""
        from pipeline.pool_globals import get_integrated_pool, get_pool_fingerprints

        before = _snapshot(store)
        paths = ["/api/v2/studies"]
        for sid in ("DTXSID1", "DTXSID1_rat", "DTXSID1_published", "DTXSID2", "DTXSID2_nb",
                    "DTXSID_TEST", "DTXSID9", "DTXSID404", "DTXSID5046932O", "foo"):
            paths += [f"/api/v2/studies/{sid}", f"/api/v2/studies/{sid}/state",
                      f"/api/v2/studies/{sid}/creation-check",
                      f"/api/v2/studies/{sid}/delete-preview"]
        paths += [f"/api/v2/chemicals/{NEW}", f"/api/v2/chemicals/{NEW}/structure.png",
                  "/api/v2/chemicals/DTXSID0000000001"]
        for path in paths:
            resp = api.get(path)
            assert resp.status_code < 500, (path, resp.text)
            assert _snapshot(store) == before, path
        assert get_pool_fingerprints() == {} and get_integrated_pool() == {}


@pytest.mark.integration
class TestReadRefusals:
    def test_not_a_study_id(self, store, api):
        for path in ("/api/v2/studies/foo", "/api/v2/studies/foo/creation-check",
                     "/api/v2/chemicals/foo", "/api/v2/studies/foo/delete-preview"):
            _envelope(api.get(path), "invalid_study_id", 400)
        assert not (store / "foo").exists()

    def test_not_found_creates_nothing(self, store, api):
        err = _envelope(api.get(f"/api/v2/studies/{NEW}"), "study_not_found", 404)
        assert err["say"] == f"There is no study {NEW}. It may have been deleted."
        assert err["fix"] == "M1"
        _envelope(api.get("/api/v2/studies/DTXSID9"), "study_not_found", 404)   # empty folder
        assert not (store / NEW).exists()

    def test_a_suffixed_id_cannot_be_created(self, store, api):
        err = _envelope(api.get("/api/v2/studies/DTXSID2_v2/creation-check"),
                        "study_id_has_suffix", 400)
        assert "suffix" in err["say"]
        _envelope(api.get("/api/v2/chemicals/DTXSID2_v2"), "study_id_has_suffix", 400)

    def test_the_list_refuses_when_the_store_is_missing(self, tmp_path, api, monkeypatch):
        import common.paths
        monkeypatch.setattr(common.paths, "SESSIONS_DIR", tmp_path / "nowhere")
        _envelope(api.get("/api/v2/studies"), "list_failed", 500)


# ---------------------------------------------------------------------------
# The lookup
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLookup:
    def test_found(self, store, api, resolver):
        body = api.get(f"/api/v2/chemicals/{NEW}").json()
        assert body["identity"]["name"] == "Bisphenol A" and body["identity"]["pubchem_cid"] == 6623
        assert body["dtxsid_matched"] is True and body["service"] == "PubChem"
        assert body["structure_url"] == f"/api/v2/chemicals/{NEW}/structure.png"
        png = api.get(body["structure_url"])
        assert png.status_code == 200 and png.headers["content-type"] == "image/png"

    def test_not_found(self, store, api, resolver):
        err = _envelope(api.get("/api/v2/chemicals/DTXSID0000000001"), "identity_not_found", 404)
        assert err["details"]["service"] == "PubChem"
        assert "Test Article" not in json.dumps(err)

    def test_unreachable(self, store, api, monkeypatch):
        import requests

        from narrative import chem_resolver as cr
        from workflow import studies
        studies._LOOKUPS.clear()
        monkeypatch.setattr(cr, "RATE_LIMIT", 0)
        monkeypatch.delenv("CTX_API_KEY", raising=False)
        monkeypatch.setattr(cr.requests, "get",
                            lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")))
        err = _envelope(api.get(f"/api/v2/chemicals/{NEW}"), "identity_lookup_unreachable", 503)
        assert "could not be reached" in err["say"]

    def test_no_structure_picture(self, store, api, resolver, monkeypatch):
        from narrative import chem_resolver as cr
        monkeypatch.setattr(cr, "structure_png", lambda cid, size="300x300": None)
        _envelope(api.get(f"/api/v2/chemicals/{NEW}/structure.png"), "structure_unavailable", 404)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestCreate:
    def test_create(self, store, api, resolver):
        resp = api.post("/api/v2/studies", json=_create_body(api))
        assert resp.status_code == 201, resp.text
        row = resp.json()
        assert row["id"] == NEW and row["kind"] == "study"
        assert row["identity"]["name"] == "Bisphenol A" and row["identity"]["source"]["kind"] == "lookup"
        assert row["stands"]["next"] == {"say": "Bring in the study's files", "fix": "M2"}
        assert sorted(p.name for p in (store / NEW).iterdir() if not p.name.startswith(".")) == [
            "identity.json", "meta.json"]
        listed = [c["dtxsid"] for c in api.get("/api/v2/studies").json()["chemicals"]]
        assert NEW in listed

    def test_create_twice(self, store, api, resolver):
        body = _create_body(api)
        assert api.post("/api/v2/studies", json=body).status_code == 201
        err = _envelope(api.post("/api/v2/studies", json=body), "study_exists", 409)
        assert err["details"]["existing_id"] == NEW and err["fix"] == "M1"

    def test_create_an_existing_study(self, store, api, resolver, monkeypatch):
        from workflow import studies
        monkeypatch.setitem(studies._LOOKUPS, "DTXSID2", (1e18, {
            "dtxsid": "DTXSID2", "dtxsid_matched": True, "service": "PubChem",
            "looked_up_at": "2026-10-15T12:00:00Z",
            "identity": {"name": "Perfluoro", "casrn": "41997-13-1", "pubchem_cid": 1}}))
        monkeypatch.setattr(studies.time, "monotonic", lambda: 1e18)
        body = _create_body(api)
        body.update(dtxsid="DTXSID2",
                    identity={"name": "Perfluoro", "casrn": "41997-13-1", "source": {"kind": "lookup"}})
        body["format_seen"]["hash"] = api.get(
            "/api/v2/studies/DTXSID2/creation-check").json()["format"]["hash"]
        before = _snapshot(store)
        err = _envelope(api.post("/api/v2/studies", json=body), "study_exists", 409)
        assert err["details"]["existing_id"] == "DTXSID2"
        assert _snapshot(store) == before

    @pytest.mark.parametrize("over,code,status", [
        ({"dtxsid": "DTXSID7020182_v2"}, "study_id_has_suffix", 400),
        ({"dtxsid": "7020182"}, "invalid_study_id", 400),
        ({"confirmed": False}, "identity_unconfirmed", 400),
        ({"format_seen": {"definition": "eras/niehs-2026", "hash": "0000000000000000"}},
         "format_changed", 409),
        ({"format_seen": None}, "format_changed", 409),
    ])
    def test_refusals(self, store, api, resolver, over, code, status):
        body = {**_create_body(api), **over}
        _envelope(api.post("/api/v2/studies", json=body), code, status)
        assert not (store / NEW).exists() and not (store / "DTXSID7020182_v2").exists()

    @pytest.mark.parametrize("ident,code,status", [
        ({"casrn": ""}, "identity_incomplete", 400),
        ({"casrn": "80-05-8"}, "invalid_casrn", 400),
        ({"name": "Bisphenol B"}, "identity_changed", 409),
        ({"source": {"kind": "stated"}}, "identity_unconfirmed", 400),
    ])
    def test_identity_refusals(self, store, api, resolver, ident, code, status):
        body = _create_body(api)
        body["identity"].update(ident)
        _envelope(api.post("/api/v2/studies", json=body), code, status)
        assert not (store / NEW).exists()

    def test_not_found_creates_nothing(self, store, api, resolver):
        body = _create_body(api)
        body["dtxsid"] = "DTXSID0000000001"
        body["format_seen"]["hash"] = api.get(
            "/api/v2/studies/DTXSID0000000001/creation-check").json()["format"]["hash"]
        _envelope(api.post("/api/v2/studies", json=body), "identity_not_found", 404)
        assert not (store / "DTXSID0000000001").exists()

    def test_a_malformed_body(self, store, api):
        _envelope(api.post("/api/v2/studies", json={"identity": {}}), "bad_request", 422)


# ---------------------------------------------------------------------------
# Fill a missing identity
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestIdentity:
    def _body(self, api):
        found = api.get(f"/api/v2/chemicals/{NEW}").json()
        return {"identity": {"name": found["identity"]["name"], "casrn": found["identity"]["casrn"],
                             "source": {"kind": "lookup"}},
                "confirmed": True}

    def test_fill(self, store, api, resolver):
        _session(store, f"{NEW}_nb", meta__json={})
        resp = api.put(f"/api/v2/studies/{NEW}_nb/identity", json=self._body(api))
        assert resp.status_code == 200, resp.text
        assert resp.json()["identity"]["name"] == "Bisphenol A"

    def test_refusals(self, store, api, resolver):
        body = self._body(api)
        _envelope(api.put(f"/api/v2/studies/{NEW}/identity", json=body), "study_not_found", 404)
        _session(store, NEW, identity__json={"name": "Bisphenol A"})
        _envelope(api.put(f"/api/v2/studies/{NEW}/identity", json=body), "identity_exists", 409)
        _envelope(api.put("/api/v2/studies/DTXSID2_published/identity", json=body),
                  "read_only_session", 409)
        _envelope(api.put("/api/v2/studies/DTXSID1/identity", json=body), "read_only_session", 409)
        _session(store, f"{NEW}_x", meta__json={})
        _envelope(api.put(f"/api/v2/studies/{NEW}_x/identity", json={**body, "confirmed": False}),
                  "identity_unconfirmed", 400)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestDelete:
    def test_preview_then_delete(self, store, api):
        preview = api.get("/api/v2/studies/DTXSID2/delete-preview")
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["confirm"]["strength"] == "irreversible"
        assert body["type_to_confirm"] == "DTXSID2"
        assert {k["what"] for k in body["confirm"]["keeps"]} == {"companion", "others"}
        resp = api.post("/api/v2/studies/DTXSID2/delete",
                        json={"confirm_id": "DTXSID2", "preview_token": body["preview_token"]})
        assert resp.status_code == 200, resp.text
        assert resp.json()["say"] == "DTXSID2 was deleted."
        assert not (store / "DTXSID2").exists()
        assert (store / "DTXSID2_published").is_dir() and (store / "DTXSID2_nb").is_dir()
        _envelope(api.get("/api/v2/studies/DTXSID2"), "study_not_found", 404)
        assert api.get("/api/v2/studies/DTXSID2/state").json() == {"id": "DTXSID2", "exists": False}

    def test_preview_refusals(self, store, api):
        err = _envelope(api.get("/api/v2/studies/DTXSID1_rat/delete-preview"), "member_of_report", 409)
        assert err["details"]["parent"] == "DTXSID1"
        assert err["say"] == "This is the rat study of the report DTXSID1. Deleting it would break that report."
        _envelope(api.get("/api/v2/studies/DTXSID2_published/delete-preview"), "read_only_session", 409)
        _envelope(api.get("/api/v2/studies/DTXSID404/delete-preview"), "study_not_found", 404)
        assert not (store / "DTXSID404").exists()

    def test_delete_refusals(self, store, api):
        token = api.get("/api/v2/studies/DTXSID2/delete-preview").json()["preview_token"]
        for typed in ("dtxsid2", "DTXSID", ""):
            _envelope(api.post("/api/v2/studies/DTXSID2/delete",
                               json={"confirm_id": typed, "preview_token": token}),
                      "confirm_mismatch", 400)
        (store / "DTXSID2" / "files" / "b.txt").write_text("brought in after the review")
        _envelope(api.post("/api/v2/studies/DTXSID2/delete",
                           json={"confirm_id": "DTXSID2", "preview_token": token}),
                  "changed_since_preview", 409)
        _envelope(api.post("/api/v2/studies/DTXSID1_rat/delete",
                           json={"confirm_id": "DTXSID1_rat", "preview_token": token}),
                  "member_of_report", 409)
        _envelope(api.post("/api/v2/studies/DTXSID404/delete",
                           json={"confirm_id": "DTXSID404", "preview_token": token}),
                  "study_not_found", 404)
        assert (store / "DTXSID2").is_dir() and (store / "DTXSID1_rat").is_dir()

    def test_a_retry_after_a_mistyped_id_is_accepted(self, store, api):
        """A refused delete writes the request log; the retry must not be
        refused as "changed since the review"."""
        token = api.get("/api/v2/studies/DTXSID2/delete-preview").json()["preview_token"]
        for _ in range(2):
            _envelope(api.post("/api/v2/studies/DTXSID2/delete",
                               json={"confirm_id": "dtxsid2", "preview_token": token}),
                      "confirm_mismatch", 400)
        resp = api.post("/api/v2/studies/DTXSID2/delete",
                        json={"confirm_id": "DTXSID2", "preview_token": token})
        assert resp.status_code == 200, resp.text

    def test_deleting_a_report_keeps_its_studies(self, store, api):
        token = api.get("/api/v2/studies/DTXSID1/delete-preview").json()["preview_token"]
        assert api.post("/api/v2/studies/DTXSID1/delete",
                        json={"confirm_id": "DTXSID1", "preview_token": token}).status_code == 200
        rat = api.get("/api/v2/studies/DTXSID1_rat").json()
        assert rat["kind"] == "other" and rat["actions"]["delete"]["allowed"] is True

    def test_a_delete_that_loses_the_race_is_not_found(self, store, api, monkeypatch):
        """F3: the second of two delete POSTs reaches its dry run while the
        first is removing the folder. Forced: the dry run's section read
        removes the folder, then fails as the walk did (FileNotFoundError).
        The answer is study_not_found, never a 500."""
        import shutil

        import workflow.read_model as rm

        token = api.get("/api/v2/studies/DTXSID2/delete-preview").json()["preview_token"]

        def walk(dtxsid, store_=None):
            shutil.rmtree(store / dtxsid)
            raise FileNotFoundError(f"{dtxsid}/narrative_runs/summary/r1.json")

        monkeypatch.setattr(rm, "study_state", walk)
        _envelope(api.post("/api/v2/studies/DTXSID2/delete",
                           json={"confirm_id": "DTXSID2", "preview_token": token}),
                  "study_not_found", 404)

    def test_a_preview_of_a_vanishing_folder_is_not_found(self, store, api, monkeypatch):
        import workflow.read_model as rm

        def walk(dtxsid, store_=None):
            (store / dtxsid).rename(store / f".deleting-{dtxsid}")
            return {"sections": []}

        monkeypatch.setattr(rm, "study_state", walk)
        _envelope(api.get("/api/v2/studies/DTXSID2/delete-preview"), "study_not_found", 404)


# ---------------------------------------------------------------------------
# The old full reset (F2): refuses what the delete refuses
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestOldReset:
    def test_it_refuses_a_member_and_a_companion(self, store, api):
        err = _envelope(api.post("/api/session/reset/DTXSID1_rat"), "member_of_report", 409)
        assert err["details"]["parent"] == "DTXSID1"
        assert err["say"] == "This is the rat study of the report DTXSID1. Deleting it would break that report."
        _envelope(api.post("/api/session/reset/DTXSID2_published"), "read_only_session", 409)
        assert (store / "DTXSID1_rat").is_dir() and (store / "DTXSID2_published").is_dir()

    def test_it_refuses_a_run_in_flight(self, store, api, monkeypatch):
        from workflow import studies
        monkeypatch.setattr(studies, "running_since", lambda sid: "2026-10-15T12:00:00Z")
        err = _envelope(api.post("/api/session/reset/DTXSID2"), "run_in_flight", 409)
        assert err["details"] == {"started_at": "2026-10-15T12:00:00Z"}
        assert (store / "DTXSID2").is_dir()

    def test_it_still_resets_a_study_without_a_token(self, store, api):
        resp = api.post("/api/session/reset/DTXSID2_nb")
        assert resp.status_code == 200 and resp.json() == {"ok": True}
        assert not (store / "DTXSID2_nb").exists()

    def test_an_absent_or_empty_id(self, store, api):
        resp = api.post("/api/session/reset/DTXSID404")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "message": "No session to reset"}
        assert not (store / "DTXSID404").exists()
        assert api.post("/api/session/reset/DTXSID9").json() == {"ok": True}   # empty folder
        assert not (store / "DTXSID9").exists()


# ---------------------------------------------------------------------------
# R6: no files into a companion or a report
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestNoDataIntoCompanionsOrReports:
    @pytest.mark.parametrize("route,field,name", [
        ("/api/upload-csv", "files", "a.csv"),
        ("/api/upload-bm2", "files", "a.bm2"),
        ("/api/upload-zip", "file", "a.zip"),
    ])
    def test_uploads_are_refused(self, store, api, route, field, name):
        payload = io.BytesIO()
        if name.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(payload, "w") as z:
                z.writestr("a.csv", "x,y\n1,2\n")
        else:
            payload.write(b"x,y\n1,2\n")
        for sid, code in (("DTXSID2_published", "read_only_session"), ("DTXSID1", "report_has_no_data")):
            before = _snapshot(store)
            payload.seek(0)
            resp = api.post(f"{route}?dtxsid={sid}", files={field: (name, payload.getvalue())})
            _envelope(resp, code, 409)
            assert _snapshot(store) == before

    def test_the_validate_route_refuses_a_companion(self, store, api):
        resp = api.post("/api/pool/validate/DTXSID2_published")
        assert resp.status_code == 409, resp.text
