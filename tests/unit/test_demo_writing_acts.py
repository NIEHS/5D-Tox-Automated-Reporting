"""ui_api.writing_acts: write the Background, run the Summary, take a run into
the report (the demo path, spec §4 S3), on a finished report and its live copy.

The model and the network are replaced: the sources' gatherer, the Background
generator and the Summary generator are stand-ins that record how they were
called.
"""

import json
import types

import pytest

from tooling import demo_copy

REPORT = "DTXSID0000666"
LIVE, LIVE_RAT = f"{REPORT}_live", f"{REPORT}_live_rat"


def _write(folder, name, content="{}"):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))


@pytest.fixture
def pair(sessions_dir):
    report = sessions_dir / REPORT
    _write(report, "studies.json", {"rat": f"{REPORT}_rat"})
    _write(report, "identity.json", {"name": "Testane", "casrn": "50-00-0"})
    study = sessions_dir / f"{REPORT}_rat"
    _write(study, "files/data.txt", "doses")
    _write(study, "_fingerprints.json")
    _write(study, "validation_report.json")
    _write(study, "identity.json", {"name": "Testane", "casrn": "50-00-0"})
    demo_copy.make(REPORT)
    return sessions_dir


@pytest.fixture
def client(pair):
    from fastapi.testclient import TestClient
    from web_routes.background_server import app
    return TestClient(app)


@pytest.fixture
def sources(monkeypatch):
    """The gatherer, the resolver and the Background generator, replaced."""
    import narrative.background_writer as writer
    import narrative.chem_resolver as resolver
    import narrative.data_gatherer as gatherer

    seen = {"unreachable": [], "references": ["[1] PubChem Compound 1 (database). https://x/1"]}

    def gather_all(identity, progress=None):
        seen["identity"] = identity
        for message in ("Querying PubChem for chemical data...", "Querying ATSDR ToxProfiles...",
                        "Data gathering complete."):
            progress(message)
        return types.SimpleNamespace(identity=identity, unreachable_sources=seen["unreachable"])

    def generate_background(data, model=""):
        seen["generated"] = seen.get("generated", 0) + 1
        return {"paragraphs": ["Testane is a solvent [1]."], "references": seen["references"],
                "citation_report": {"inventory_size": 1, "cited": [1], "issues": [],
                                    "unresolved_count": 0},
                "abstract_background": "A solvent.", "model_used": model,
                "prompt": {"system": "Be exact.", "user": "SOURCES: PubChem …"}}

    monkeypatch.setattr(gatherer, "gather_all", gather_all)
    monkeypatch.setattr(writer, "generate_background", generate_background)
    monkeypatch.setattr(resolver, "resolve_chemical", lambda *a, **k: types.SimpleNamespace(
        to_dict=lambda: {"pubchem_cid": 1, "name": "resolved name"}))
    return seen


def _events(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Write the Background
# ---------------------------------------------------------------------------

def test_the_background_is_written_saved_as_a_draft_and_its_prompt_kept(client, pair, sources):
    from ui_api.writing import writing_part

    response = client.post(f"/api/v2/studies/{LIVE}/writing/background")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = _events(response)
    steps = [(e["unit"], e["status"]) for e in events if e["event"] == "step"]
    assert steps[:2] == [("chemical", "computing"), ("chemical", "done")]
    assert ("source_1", "done") in steps and ("source_2", "done") in steps
    assert [u for u, s in steps if s == "computing"] == [
        "chemical", "source_1", "source_2", "sources", "model", "references", "save", "record"]
    assert [u for u, s in steps if s == "done"] == [u for u, s in steps if s == "computing"]
    assert all(e["say"] and not e["say"].endswith(".") for e in events if e["event"] == "step")
    result = events[-1]
    assert result["event"] == "result" and result["ok"] is True
    assert result["summary"]["paragraphs"] == 1 and result["summary"]["outcome"] == "written"

    # The chemical is named by its own DTXSID, not by the copy's id.
    assert sources["identity"].dtxsid == REPORT and sources["identity"].name == "Testane"

    saved = json.loads((pair / LIVE / "background.json").read_text())
    assert saved["approved"] is False and saved["paragraphs"] == ["Testane is a solvent [1]."]
    part = writing_part(LIVE, "background")
    [prompt] = part["given"]
    assert prompt["record"] == "as_sent" and "SOURCES: PubChem" in prompt["text"]
    assert part["run"]["run_id"] == result["summary"]["run_id"]
    # The study is free again once the run has ended.
    from ui_api import runs
    assert runs.current(LIVE) is None


def test_unreachable_hazard_sources_end_the_run_with_the_refusal_and_save_nothing(client, pair, sources):
    sources["unreachable"] = ["ATSDR", "IRIS"]
    events = _events(client.post(f"/api/v2/studies/{LIVE}/writing/background"))
    error = events[-1]
    assert error["event"] == "error"
    assert error["error"]["code"] == "background_sources_unreachable"
    assert "ATSDR, IRIS" in error["error"]["say"]
    assert [e for e in events if e["event"] == "step"][-1]["status"] == "failed"
    assert "generated" not in sources                        # the model was not asked
    assert not (pair / LIVE / "background.json").exists()
    assert not (pair / LIVE / "narrative_runs").exists()


def test_a_text_with_no_references_is_not_saved(client, pair, sources):
    sources["references"] = []
    events = _events(client.post(f"/api/v2/studies/{LIVE}/writing/background"))
    assert events[-1]["error"]["code"] == "background_no_references"
    assert not (pair / LIVE / "background.json").exists()


def test_the_finished_side_a_study_and_an_approved_text_are_refused_before_any_work(client, pair, sources):
    finished = client.post(f"/api/v2/studies/{REPORT}/writing/background")
    assert finished.status_code == 409 and finished.json()["error"]["code"] == "demo_reference"
    member = client.post(f"/api/v2/studies/{LIVE_RAT}/writing/background")
    assert member.status_code == 409
    assert member.json()["error"]["code"] == "background_is_the_reports"
    assert LIVE in member.json()["error"]["say"]

    _write(pair / LIVE, "background.json", {"paragraphs": ["Approved text."], "approved": True,
                                            "version": 1})
    owned = client.post(f"/api/v2/studies/{LIVE}/writing/background")
    assert owned.status_code == 409 and owned.json()["error"]["code"] == "section_owned"
    assert json.loads((pair / LIVE / "background.json").read_text())["paragraphs"] == ["Approved text."]
    assert "identity" not in sources and "generated" not in sources

    gone = client.post("/api/v2/studies/DTXSID0000999/writing/background")
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "study_not_found"


def test_a_second_act_on_the_same_study_is_refused_while_one_runs(client, pair, sources):
    from ui_api import runs

    with runs.running(LIVE, "the writing of the Background"):
        busy = client.post(f"/api/v2/studies/{LIVE}/writing/background")
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "run_in_flight"


def test_the_overview_offers_each_act_where_it_can_be_done(pair):
    from ui_api.writing import writing_overview

    live = writing_overview(LIVE)["acts"]
    assert live["background"] == {"allowed": True, "say": None}
    assert live["summary"]["allowed"] is False               # a study's, not the report's
    study = writing_overview(LIVE_RAT)["acts"]
    assert study["summary"] == {"allowed": True, "say": None}
    assert study["background"]["allowed"] is False
    finished = writing_overview(REPORT)["acts"]["background"]
    assert finished["allowed"] is False and finished["counterpart"] == LIVE
    assert LIVE in finished["say"]


# ---------------------------------------------------------------------------
# The Summary
# ---------------------------------------------------------------------------

@pytest.fixture
def summary_model(monkeypatch):
    import narrative.summary_llm as summary_llm
    from pipeline import prompt_store

    calls = {"paragraphs": ["Worded by the model at 12.5 ppm."]}

    async def generate_summary(dtxsid, **kwargs):
        calls["dtxsid"] = dtxsid
        return prompt_store.save_run(dtxsid, "summary", {
            "section": "summary", "dtxsid": dtxsid, "template_version": 1,
            "prompt": {"system": "S", "user": "U", "model": "model-s"},
            "paragraphs": calls["paragraphs"], "unmatched_numbers": ["12.5"]})

    monkeypatch.setattr(summary_llm, "generate_summary", generate_summary)
    monkeypatch.setattr(summary_llm, "render_for_session", lambda dtxsid, text=None: (None, {}))
    return calls


def test_a_summary_run_is_kept_and_leaves_the_report_alone(client, pair, summary_model):
    from ui_api.writing import writing_part

    _write(pair / LIVE_RAT, "summary.json", {"paragraphs": ["Facts by rule."],
                                             "source": "generated", "approved": False, "version": 1})
    events = _events(client.post(f"/api/v2/studies/{LIVE_RAT}/writing/summary"))
    result = events[-1]
    assert result["event"] == "result"
    assert result["summary"]["unmatched_numbers"] == ["12.5"] and result["summary"]["model"] == "model-s"
    assert [e["unit"] for e in events if e["event"] == "step" and e["status"] == "done"] == ["facts", "model"]
    part = writing_part(LIVE_RAT, "summary")
    assert part["text"][0]["paragraphs"] == ["Facts by rule."]        # the report is unchanged
    [run] = part["runs"]
    assert run["in_use"] is False and run["paragraphs"] == summary_model["paragraphs"]
    assert "U" in run["prompt"]

    # Taking the run into the report: a new, unapproved version worded by the model.
    used = client.post(f"/api/v2/studies/{LIVE_RAT}/writing/summary/runs/{run['run_id']}/use")
    assert used.status_code == 200 and used.json()["outcome"] == "written"
    part = writing_part(LIVE_RAT, "summary")
    assert part["written_by"] == "model" and part["approved"] is False
    assert part["runs"][0]["in_use"] is True and part["unmatched_numbers"] == ["12.5"]
    again = client.post(f"/api/v2/studies/{LIVE_RAT}/writing/summary/runs/{run['run_id']}/use")
    assert again.json()["noop"]["code"] == "unchanged"


def test_a_study_with_nothing_to_summarize_is_refused_in_plain_words(client, pair, monkeypatch):
    import narrative.summary_llm as summary_llm
    from narrative.prompt_templates import TemplateError

    def nothing(dtxsid, text=None):
        raise TemplateError("This session has no results to summarize yet (run Process first).")
    monkeypatch.setattr(summary_llm, "render_for_session", nothing)
    events = _events(client.post(f"/api/v2/studies/{LIVE_RAT}/writing/summary"))
    assert events[-1]["error"]["code"] == "summary_not_ready"
    assert "no results to summarize" in events[-1]["error"]["say"]


def test_summary_acts_are_refused_on_the_finished_side_on_a_report_and_for_an_unknown_run(
        client, pair, summary_model):
    finished = client.post(f"/api/v2/studies/{REPORT}_rat/writing/summary")
    assert finished.status_code == 409 and finished.json()["error"]["code"] == "demo_reference"
    report = client.post(f"/api/v2/studies/{LIVE}/writing/summary")
    assert report.status_code == 409 and report.json()["error"]["code"] == "summary_is_a_studys"
    use = client.post(f"/api/v2/studies/{REPORT}_rat/writing/summary/runs/r20260101T000000-aaaaaa/use")
    assert use.status_code == 409 and use.json()["error"]["code"] == "demo_reference"
    unknown = client.post(f"/api/v2/studies/{LIVE_RAT}/writing/summary/runs/r20260101T000000-aaaaaa/use")
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "summary_run_not_found"
    assert "dtxsid" not in summary_model                     # the model was never asked


def test_an_approved_summary_is_not_replaced_by_a_run(client, pair, summary_model):
    _write(pair / LIVE_RAT, "narrative_runs/summary/r20261118T130000-def456.json", {
        "run_id": "r20261118T130000-def456", "paragraphs": ["Run text."],
        "prompt": {"system": "S", "user": "U", "model": "model-s"}, "template_version": 1})
    _write(pair / LIVE_RAT, "summary.json", {"paragraphs": ["Approved."], "source": "generated",
                                             "approved": True, "version": 1})
    refused = client.post(
        f"/api/v2/studies/{LIVE_RAT}/writing/summary/runs/r20261118T130000-def456/use")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "section_owned"
    assert json.loads((pair / LIVE_RAT / "summary.json").read_text())["paragraphs"] == ["Approved."]
