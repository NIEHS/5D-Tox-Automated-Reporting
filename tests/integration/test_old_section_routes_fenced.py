"""
The old interface's section write routes, fenced (C2 D5): they still answer,
but none of them replaces owned text, approves through a save, or loses
history. Through the FastAPI test client against a scratch SESSIONS_DIR.
"""

import json

import pytest

ID = "DTXSID_FENCE"


@pytest.fixture
def study(sessions_dir):
    d = sessions_dir / ID
    d.mkdir(parents=True)
    return d


def _seed(d, key, **fields):
    (d / f"{key}.json").write_text(json.dumps({"version": 1, "source": "generated", **fields}))


def _load(d, key):
    return json.loads((d / f"{key}.json").read_text())


# --- approve (§4.5) ------------------------------------------------------------

def test_approve_with_the_same_content_accepts_it(client, study):
    _seed(study, "background", paragraphs=["p"])
    r = client.post("/api/session/approve", json={
        "dtxsid": ID, "section_type": "background",
        "data": {"paragraphs": ["p"], "original_paragraphs": ["p"], "approved": False,
                 "version": 1, "source": "generated"}})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["version"] == 1
    assert _load(study, "background")["approved"] is True
    assert not (study / "identity.json").exists()


def test_approve_with_changed_content_is_refused(client, study):
    _seed(study, "background", paragraphs=["p"])
    r = client.post("/api/session/approve", json={
        "dtxsid": ID, "section_type": "background", "data": {"paragraphs": ["edited"]},
        "identity": {"name": "x"}})
    assert r.status_code == 409 and r.json()["code"] == "approve_content_retired"
    assert _load(study, "background") == {"version": 1, "source": "generated", "paragraphs": ["p"]}
    assert not (study / "identity.json").exists()


def test_approve_with_empty_data_no_longer_replaces_an_approved_summary(client, study):
    # document analysis §2: empty data replaced an approved Summary.
    _seed(study, "summary", paragraphs=["kept"], approved=True, facts=["final", "protected"])
    r = client.post("/api/session/approve", json={"dtxsid": ID, "section_type": "summary",
                                                   "data": {}})
    assert r.status_code == 200 and r.json().get("noop", {}).get("code") in (None, "already_accepted")
    assert _load(study, "summary")["paragraphs"] == ["kept"]


def test_approve_without_a_file_is_not_found(client, study):
    r = client.post("/api/session/approve", json={"dtxsid": ID, "section_type": "summary",
                                                   "data": {"paragraphs": ["x"]}})
    assert r.status_code == 404 and r.json()["code"] == "section_not_found"
    assert not (study / "summary.json").exists()


# --- save-section (§4.6) -------------------------------------------------------

def test_save_section_writes_a_draft_through_the_gate(client, study):
    r = client.post("/api/session/save-section", json={
        "dtxsid": ID, "section_type": "background", "data": {"paragraphs": ["a"], "source": "model"}})
    assert r.status_code == 200 and r.json() == {"ok": True, "version": 1}
    r = client.post("/api/session/save-section", json={
        "dtxsid": ID, "section_type": "background", "data": {"paragraphs": ["b"], "source": "model"}})
    assert r.json()["version"] == 2
    archived = [json.loads(p.read_text()) for p in (study / "history" / "background").glob("*.json")]
    assert [a["paragraphs"] for a in archived] == [["a"]]


def test_save_section_never_replaces_owned_text(client, study):
    # document analysis §2: save-section destroyed an approved Background.
    _seed(study, "background", paragraphs=["mine"], approved=True)
    r = client.post("/api/session/save-section", json={
        "dtxsid": ID, "section_type": "background", "data": {"paragraphs": ["machine"]}})
    assert r.status_code == 409 and r.json()["code"] == "section_owned"
    assert _load(study, "background")["paragraphs"] == ["mine"]


def test_save_section_cannot_approve(client, study):
    r = client.post("/api/session/save-section", json={
        "dtxsid": ID, "section_type": "background", "approved": True,
        "data": {"paragraphs": ["x"]}})
    assert r.status_code == 400 and r.json()["code"] == "approve_via_accept"
    assert not (study / "background.json").exists()


# --- unapprove (§4.4), discard (§4.7), restore (§4.8) ---------------------------

def test_unapprove_needs_a_reason_and_an_existing_section(client, study):
    _seed(study, "background", paragraphs=["p"], approved=True)
    r = client.post("/api/session/unapprove", json={"dtxsid": ID, "section_type": "background"})
    assert r.status_code == 400 and r.json()["code"] == "reason_required"
    r = client.post("/api/session/unapprove", json={"dtxsid": ID, "section_type": "background",
                                                     "reason": "fix tone"})
    assert r.status_code == 200 and _load(study, "background")["approved"] is False
    r = client.post("/api/session/unapprove", json={"dtxsid": ID, "section_type": "summary",
                                                     "reason": "x"})
    assert r.status_code == 404 and r.json()["code"] == "section_not_found"


def test_discard_refuses_an_approved_section_and_archives_otherwise(client, study):
    _seed(study, "background", paragraphs=["p"], approved=True)
    body = {"dtxsid": ID, "section_type": "background", "reason": "wrong"}
    assert client.post("/api/session/discard-section", json=body).json()["code"] == "section_owned"
    client.post("/api/session/unapprove", json={**body, "reason": "r"})
    r = client.post("/api/session/discard-section", json=body)
    assert r.status_code == 200 and r.json()["archived"]
    assert not (study / "background.json").exists()
    assert list((study / "history" / "background").glob("*.json"))


def test_restore_route_validates_the_key(client, study):
    # T10: "../DTXSID_VICTIM/summary" read another session's file.
    r = client.post(f"/api/session/{ID}/restore", json={"section_key": "../DTXSID_OTHER/summary",
                                                         "version": 1, "reason": "x"})
    assert r.status_code == 400 and r.json()["code"] == "section_key_invalid"


def test_old_history_route_works_after_a_discard(client, study):
    _seed(study, "background", paragraphs=["p"])
    client.post("/api/session/discard-section", json={"dtxsid": ID, "section_type": "background",
                                                       "reason": "x"})
    r = client.get(f"/api/session/{ID}/history/background")
    assert r.status_code == 200
    assert r.json() == {"section_key": "background", "current_version": None,
                        "versions": [{"version": 1, "approved_at": "", "is_current": False}]}
    assert client.get(f"/api/session/{ID}/history/background?version=1").json()["paragraphs"] == ["p"]


# --- use run (§4.9, D6) ------------------------------------------------------------

def test_use_run_over_an_approved_summary_is_refused(client, study, monkeypatch):
    from pipeline import prompt_store
    _seed(study, "summary", paragraphs=["approved text"], approved=True)
    monkeypatch.setattr(prompt_store, "load_run", lambda d, s, r: {
        "run_id": r, "paragraphs": ["model text"], "prompt": {"model": "m"}})
    r = client.post(f"/api/prompts/summary/runs/{ID}/r1/use")
    assert r.status_code == 409 and r.json()["code"] == "section_owned"
    assert _load(study, "summary")["paragraphs"] == ["approved text"]


# --- pool reset (§4.15) -------------------------------------------------------------

def test_pool_reset_archives_each_section_before_deleting_it(client, study):
    _seed(study, "bm2_body-weight", tables_json={"rows": [1]}, approved=True)
    _seed(study, "summary", paragraphs=["s"])
    r = client.post(f"/api/pool/reset/{ID}")
    assert r.status_code == 200
    assert not (study / "bm2_body-weight.json").exists() and not (study / "summary.json").exists()
    from pipeline.session_store import read_version_history
    for key in ("bm2_body-weight", "summary"):
        (event,) = read_version_history(ID, key)
        assert (event["cause"], event["act"], event["actor"]) == ("discard", "pool_reset", "person")
        assert (study / "history" / key / event["archived"]).exists()
