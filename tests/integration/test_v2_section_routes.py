"""
The new interface's section routes (C2 contract, "Routes added"), through the
FastAPI test client against a scratch SESSIONS_DIR: each route, each refusal's
code and envelope (MODULES.md §4.2), and the no-ops.
"""

import json

import pytest

ID = "DTXSID_V2SEC"
BASE = f"/api/v2/studies/{ID}/sections"


@pytest.fixture
def study(sessions_dir):
    d = sessions_dir / ID
    d.mkdir(parents=True)
    return d


def _seed(d, key, **fields):
    (d / f"{key}.json").write_text(json.dumps({"version": 1, "source": "generated", **fields}))


def _envelope(resp, code, status):
    assert resp.status_code == status, resp.text
    err = resp.json()["error"]
    assert err["code"] == code and err["status"] == status
    assert err["message"] and err["say"]
    return err


# --- accept --------------------------------------------------------------------

def test_accept_approves_without_touching_the_text(client, study):
    _seed(study, "summary", paragraphs=["p"])
    r = client.post(f"{BASE}/summary/accept", json={})
    assert r.status_code == 200
    assert r.json() == {"section_key": "summary", "approved": True, "version": 1,
                        "version_status": "blessed"}
    s = json.loads((study / "summary.json").read_text())
    assert s["approved"] is True and s["paragraphs"] == ["p"]
    again = client.post(f"{BASE}/summary/accept").json()
    assert again["noop"]["code"] == "already_accepted" and again["noop"]["say"]


def test_accept_refusals(client, study):
    _envelope(client.post(f"{BASE}/summary/accept"), "section_not_found", 404)
    _envelope(client.post(f"{BASE}/meta/accept"), "section_key_invalid", 400)
    _envelope(client.post(f"{BASE}/bm2_a.b/accept"), "section_key_invalid", 400)
    err = _envelope(client.post("/api/v2/studies/not-a-study/sections/summary/accept"),
                    "invalid_study_id", 400)
    assert err["fix"] == "M1"


def test_a_study_that_does_not_exist_is_not_created(client, sessions_dir):
    _envelope(client.post("/api/v2/studies/DTXSID_NOPE/sections/summary/accept"),
              "section_not_found", 404)
    _envelope(client.get("/api/v2/studies/DTXSID_NOPE/sections/summary/history"),
              "section_not_found", 404)
    assert not (sessions_dir / "DTXSID_NOPE").exists()


# --- release -------------------------------------------------------------------

def test_release_needs_a_reason_and_keeps_the_section_protected(client, study):
    _seed(study, "summary", paragraphs=["p"])
    client.post(f"{BASE}/summary/accept")
    _envelope(client.post(f"{BASE}/summary/release", json={}), "reason_required", 400)
    _envelope(client.post(f"{BASE}/summary/release", json={"reason": "  "}), "reason_required", 400)
    r = client.post(f"{BASE}/summary/release", json={"reason": "recheck the doses"})
    assert r.json() == {"section_key": "summary", "approved": False, "version": 1,
                        "version_status": "working"}
    s = json.loads((study / "summary.json").read_text())
    assert s["facts"] == ["protected"] and s["revised"] == {"reason": "recheck the doses"}
    again = client.post(f"{BASE}/summary/release", json={"reason": "x"}).json()
    assert again["noop"]["code"] == "not_approved"
    _envelope(client.post(f"{BASE}/background/release", json={"reason": "x"}),
              "section_not_found", 404)


# --- restore -------------------------------------------------------------------

def _versions(client, study):
    from workflow.section_writes import write_section
    from workflow.store import DiskPoolStore
    for text in ("one", "two"):
        write_section(ID, "summary", {"paragraphs": [text], "source": "generated"},
                      DiskPoolStore(), act="summary", actor="system", author="generated")


def test_restore_brings_a_version_back_as_a_draft(client, study):
    _versions(client, study)
    client.post(f"{BASE}/summary/accept")
    r = client.post(f"{BASE}/summary/restore", json={"version": 1, "reason": "v2 dropped a finding"})
    assert r.status_code == 200, r.text
    assert r.json() == {"section_key": "summary", "version": 3, "from_version": 1,
                        "approved": False, "version_status": "working"}
    s = json.loads((study / "summary.json").read_text())
    assert s["paragraphs"] == ["one"] and s["facts"] == ["protected"]
    noop = client.post(f"{BASE}/summary/restore", json={"version": 3, "reason": "x"}).json()
    assert noop["noop"]["code"] == "already_current"


def test_restore_refusals(client, study):
    _versions(client, study)
    _envelope(client.post(f"{BASE}/summary/restore", json={"version": 1}), "reason_required", 400)
    _envelope(client.post(f"{BASE}/summary/restore", json={"version": 9, "reason": "x"}),
              "version_not_found", 404)
    _envelope(client.post(f"{BASE}/summary/restore", json={"reason": "x"}),
              "version_not_found", 404)
    _envelope(client.post(f"{BASE}/..x/restore", json={"version": 1, "reason": "x"}),
              "section_key_invalid", 400)
    # A key with a separator never reaches the step: no route matches it.
    assert client.post(f"{BASE}/..%2Fx/restore", json={"version": 1, "reason": "x"}
                       ).status_code == 404
    hist = study / "history" / "summary"
    with (hist / "index.jsonl").open("a") as fh:   # an old session's lost version
        fh.write(json.dumps({"version": 0, "cause": "edit", "status": "blessed", "ts": "t"}) + "\n")
    (hist / "index.jsonl").write_text((hist / "index.jsonl").read_text().replace(
        '"version": 0', '"version": 7'))
    _envelope(client.post(f"{BASE}/summary/restore", json={"version": 7, "reason": "x"}),
              "version_content_missing", 409)


def test_restore_works_after_a_discard(client, study):
    # T9, through the old discard route (D4: not offered by the new interface).
    _versions(client, study)
    r = client.post("/api/session/discard-section", json={
        "dtxsid": ID, "section_type": "summary", "reason": "wrong study"})
    assert r.status_code == 200 and not (study / "summary.json").exists()
    hist = client.get(f"{BASE}/summary/history").json()
    assert hist["current_version"] is None
    assert [v["version"] for v in hist["versions"]] == [1, 2]
    r = client.post(f"{BASE}/summary/restore", json={"version": 2, "reason": "it was right"})
    assert r.status_code == 200 and r.json()["version"] == 3      # T8: never 1 again


# --- history ---------------------------------------------------------------------

def test_history_lists_versions_and_events(client, study):
    _versions(client, study)
    client.post(f"{BASE}/summary/accept")
    h = client.get(f"{BASE}/summary/history").json()
    assert h["section_key"] == "summary" and h["current_version"] == 2
    assert h["current_status"] == "blessed"
    assert [(v["version"], v["status"], v["current"]) for v in h["versions"]] == [
        (1, "draft", False), (2, "blessed", True)]
    assert h["versions"][0]["archived"].startswith("v0001-")
    assert [(e["cause"], e["act"]) for e in h["events"]] == [
        ("generate", "summary"), ("generate", "summary"), ("edit", "accept")]
    assert all(e["v"] == 2 for e in h["events"])
    v1 = client.get(f"{BASE}/summary/history/1").json()
    assert v1["paragraphs"] == ["one"]
    _envelope(client.get(f"{BASE}/summary/history/9"), "version_not_found", 404)
    _envelope(client.get(f"{BASE}/summary/history/x"), "version_not_found", 404)
    _envelope(client.get(f"{BASE}/background/history"), "section_not_found", 404)


def test_reading_history_writes_nothing(client, study):
    _versions(client, study)
    before = sorted((p.relative_to(study), p.stat().st_mtime_ns) for p in study.rglob("*"))
    client.get(f"{BASE}/summary/history")
    client.get(f"{BASE}/summary/history/1")
    assert sorted((p.relative_to(study), p.stat().st_mtime_ns) for p in study.rglob("*")) == before


def test_the_state_read_model_follows_the_acts(client, study):
    _seed(study, "summary", paragraphs=["p"])
    _seed(study, "background", paragraphs=["b"], approved=True, facts=["final", "protected"])
    state = client.get(f"/api/v2/studies/{ID}/state").json()
    row = next(s for s in state["sections"] if s["key"] == "summary")
    assert row["machine_may_write"] is True and row["maturity"] is None
    client.post(f"{BASE}/background/release", json={"reason": "r"})
    state = client.get(f"/api/v2/studies/{ID}/state").json()
    bg = next(s for s in state["sections"] if s["key"] == "background")
    assert bg["approved"] is False and bg["machine_may_write"] is False
    assert bg["maturity"] is None and bg["facts"] == ["protected"]
    assert bg["version_status"] == "working"
