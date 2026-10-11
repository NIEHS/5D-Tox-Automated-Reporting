"""The prompt-workshop HTTP routes, with the model stubbed."""

import json

import pytest

from narrative import prompt_workshop, summary_llm

_DTXSID = "DTXSID5032498"
_VARS = {"draft_paragraphs": ["Liver weight rose at 36.7 (14.2) mg/kg."], "chemical_name": "X",
         "species": "rats", "strain": "", "route": "", "duration_days": 5, "sexes": ["Male"],
         "dose_unit": "mg/kg", "dose_groups": [0, 10], "abstract_background": "",
         "apical_evaluated": True, "has_genomics": False}
_T = "---\nsystem: S\n---\nRewrite: {{ draft_paragraphs|join(' ') }}"


@pytest.fixture
def api(client, monkeypatch):
    monkeypatch.setattr(summary_llm, "session_variables", lambda d: dict(_VARS))

    async def model(name, prompt, system, **kw):
        return ["Liver weight increased (BMD 36.7, BMDL 14.2 mg/kg); 3 more."]
    monkeypatch.setattr(summary_llm, "llm_generate_json_async", model)

    async def workshop(name, prompt, system, **kw):
        return {"reply": "Shorter.", "proposed_template": _T, "rationale": "Tighter."}
    monkeypatch.setattr(prompt_workshop, "llm_generate_json_async", workshop)
    return client


def test_template_versions_and_rollback(api):
    r = api.get("/api/prompts/summary").json()
    assert r["current_version"] == 1 and r["versions"][0]["version"] == 1
    assert "draft_paragraphs" in r["variables"]

    assert api.post("/api/prompts/summary", json={"template": "no front matter"}).status_code == 422
    assert api.post("/api/prompts/summary",
                    json={"template": "---\nsystem: S\n---\n{{ nope }}",
                          "dtxsid": _DTXSID}).status_code == 422
    saved = api.post("/api/prompts/summary", json={"template": _T, "rationale": "r"}).json()
    assert saved["version"] == 2
    assert api.get("/api/prompts/summary").json()["template"] == _T
    assert api.get("/api/prompts/summary/versions/1").json()["template"].startswith("---")
    assert api.post("/api/prompts/summary/current", json={"version": 1}).json() == {
        "current_version": 1}
    assert api.get("/api/prompts/summary/versions/7").status_code == 404
    assert api.get("/api/prompts/nope").status_code == 404


def test_render_reports_errors_in_the_body(api):
    ok = api.post("/api/prompts/summary/render", json={"dtxsid": _DTXSID, "template": _T}).json()
    assert ok["ok"] and ok["prompt"]["user"].startswith("Rewrite: Liver weight")
    bad = api.post("/api/prompts/summary/render",
                   json={"dtxsid": _DTXSID, "template": "---\nsystem: S\n---\n{{ x }}"}).json()
    assert bad["ok"] is False and "x" in bad["error"]
    assert api.post("/api/prompts/summary/render", json={"dtxsid": "../x"}).status_code == 400


def test_run_use_and_generate_summary(api, sessions_dir):
    run = api.post("/api/prompts/summary/run", json={"dtxsid": _DTXSID}).json()
    assert run["template_version"] == 1 and run["unmatched_numbers"] == ["3"]
    runs = api.get(f"/api/prompts/summary/runs/{_DTXSID}").json()["runs"]
    assert [r["run_id"] for r in runs] == [run["run_id"]]

    assert api.post(f"/api/prompts/summary/runs/{_DTXSID}/{run['run_id']}/use").json() == {"ok": True}
    saved = json.loads((sessions_dir / _DTXSID / "summary.json").read_text())
    assert saved["source"] == "model" and saved["run_id"] == run["run_id"]
    assert saved["approved"] is False and saved["paragraphs"] == run["paragraphs"]
    assert api.post(f"/api/prompts/summary/runs/{_DTXSID}/r20260101T000000-abcdef/use"
                    ).status_code == 404

    gen = api.post("/api/generate-summary", json={"dtxsid": _DTXSID}).json()
    assert gen["section_key"] == "summary" and gen["run_id"] != run["run_id"]
    assert gen["unmatched_numbers"] == ["3"]


def test_workshop_thread(api):
    api.post("/api/prompts/summary/run", json={"dtxsid": _DTXSID})
    thread = api.post("/api/prompts/summary/threads").json()
    turn = api.post(f"/api/prompts/summary/threads/{thread['id']}/messages",
                    json={"dtxsid": _DTXSID, "message": "Too wordy", "template": _T}).json()
    assert turn["proposed_template"] == _T and turn["render_error"] is None
    assert turn["thread"]["title"] == "Too wordy"
    assert turn["thread"]["messages"][0]["run_id"]
    assert api.get("/api/prompts/summary/threads").json()["threads"][0]["id"] == thread["id"]
    assert api.get(f"/api/prompts/summary/threads/{thread['id']}").json()["messages"]
    assert api.post("/api/prompts/summary/threads/bad.id/messages",
                    json={"dtxsid": _DTXSID, "message": "x"}).status_code == 400
    assert api.post(f"/api/prompts/summary/threads/{thread['id']}/messages",
                    json={"dtxsid": _DTXSID, "message": ""}).status_code == 400


def test_published_404_for_an_unpublished_study(api):
    assert api.get(f"/api/prompts/summary/published/{_DTXSID}").status_code == 404
