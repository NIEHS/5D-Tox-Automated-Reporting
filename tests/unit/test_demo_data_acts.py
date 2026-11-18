"""The two long acts of the demo path, as the new interface runs them:
combining the files (then the animal accounting) and Process (then the
results sections and the Summary).  Each is refused before it starts when it
may not run, holds the study while it runs, and tells its steps and its
result as lines of JSON.  The heavy core steps are stood in for here; the
real ones are run end to end on a scratch store."""

import json
import threading

import pytest

ID = "DTXSID0000666"


def _write(folder, name, content="{}"):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))


@pytest.fixture
def study(sessions_dir):
    """A study whose files passed the check: Integrate is its legal next act."""
    session = sessions_dir / ID
    _write(session, "files/data.txt", "doses")
    _write(session, "_fingerprints.json", {"data.txt": {"file_id": "id-1", "filename": "data.txt"}})
    _write(session, "validation_report.json", {"issues": [], "coverage_matrix": {
        "Body Weight|tox_study": {"xlsx": None, "txt_csv": ["id-1"], "bm2": None}}})
    _write(session, "identity.json", {"name": "Test Compound", "abbreviation": "TC",
                                      "dtxsid": ID})
    return session


def _events(lines) -> list[dict]:
    return [json.loads(line) for line in lines]


def _steps(events) -> list[tuple[str, str]]:
    return [(e["unit"], e["status"]) for e in events if e["event"] == "step"]


@pytest.fixture
def core(study, monkeypatch):
    """The core steps, stood in for: each records its call and leaves the
    files the real one leaves."""
    import workflow.steps as steps

    calls: list = []

    def integrate_step(dtxsid, identity, store):
        calls.append(("integrate", identity))
        _write(study, "integrated.json", {"name": "integrated", "doseResponseExperiments": []})
        return {"ok": True, "experiment_count": 9, "bmd_result_count": 5,
                "approval_withdrawn": False}

    def generate_animal_report_step(dtxsid, store):
        calls.append(("accounting",))
        _write(study, "animal_report.json", {"consistency_issues": []})
        return {"total_animals": 61, "consistency_issues": []}

    monkeypatch.setattr(steps, "integrate_step", integrate_step)
    monkeypatch.setattr(steps, "generate_animal_report_step", generate_animal_report_step)
    return calls


# ---------------------------------------------------------------------------
# Combine the files
# ---------------------------------------------------------------------------

def test_integrate_combines_then_accounts_and_tells_each_step(study, core):
    from ui_api import runs
    from ui_api.dataset import start_integrate
    from ui_api.read_model import study_state

    events = _events(start_integrate(ID))
    assert _steps(events) == [("integrate", "computing"), ("integrate", "done"),
                              ("accounting", "computing"), ("accounting", "done")]
    assert all(isinstance(e["ms"], int) for e in events
               if e["event"] == "step" and e["status"] == "done")
    assert events[-1] == {"event": "result", "ok": True, "summary": {
        "experiments": 9, "own_bmd_analyses": 5, "data_approval_withdrawn": False,
        "accounting_problems": 0}}
    assert [c[0] for c in core] == ["integrate", "accounting"]
    assert runs.current(ID) is None                      # released
    assert study_state(ID)["phase"] == "APPROVED"


def test_integrate_passes_the_identity_on_disk_and_no_other(study, core):
    from ui_api.dataset import start_integrate

    list(start_integrate(ID))
    assert core[0] == ("integrate", {"name": "Test Compound", "abbreviation": "TC",
                                     "dtxsid": ID})


def test_integrate_is_refused_before_it_starts_when_it_is_not_legal(study, core):
    from safeguards.refusals import PhaseRefusal
    from ui_api import runs
    from ui_api.dataset import start_integrate

    (study / "validation_report.json").unlink()           # files not checked
    with pytest.raises(PhaseRefusal):
        start_integrate(ID)
    assert core == [] and runs.current(ID) is None


def test_a_second_act_is_refused_while_the_first_runs(study, core, monkeypatch):
    import workflow.steps as steps
    from ui_api import runs
    from ui_api.dataset import start_integrate
    from ui_api.read_model import study_state
    from ui_api.studies import StudyRefusal

    entered, release = threading.Event(), threading.Event()
    real = steps.integrate_step

    def slow(dtxsid, identity, store):
        entered.set()
        assert release.wait(10)
        return real(dtxsid, identity, store)

    monkeypatch.setattr(steps, "integrate_step", slow)
    lines = start_integrate(ID)
    assert entered.wait(10)
    run = study_state(ID)["run"]
    assert run["in_flight"] and run["what"] == "combining the files into one dataset"
    with pytest.raises(StudyRefusal) as e:
        start_integrate(ID)
    assert e.value.code == "run_in_flight"
    release.set()
    assert _events(lines)[-1]["event"] == "result"
    assert runs.current(ID) is None


def test_a_failure_is_the_streams_error_and_the_study_is_released(study, core, monkeypatch):
    import workflow.steps as steps
    from ui_api import runs
    from ui_api.dataset import start_integrate
    from workflow.errors import StepError

    def fails(dtxsid, identity, store):
        raise StepError("Integration failed: body_weight.txt has no dose row", status_code=500)

    monkeypatch.setattr(steps, "integrate_step", fails)
    events = _events(start_integrate(ID))
    assert _steps(events) == [("integrate", "computing"), ("integrate", "failed")]
    error = events[-1]["error"]
    assert events[-1]["event"] == "error" and error["code"] == "integration_failed"
    assert error["fix"] == "M3" and "body_weight.txt" in error["message"]
    assert runs.current(ID) is None


def test_the_act_goes_on_when_nobody_reads_it(study, core):
    """A page closed during the wait stops reading; the act still ends and
    releases the study."""
    import time

    from ui_api import runs
    from ui_api.dataset import start_integrate

    start_integrate(ID)                                    # the lines are never read
    deadline = time.monotonic() + 10
    while runs.current(ID) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert runs.current(ID) is None
    assert [c[0] for c in core] == ["integrate", "accounting"]


def test_the_finished_side_of_a_pair_is_not_combined(sessions_dir, core):
    from tooling import demo_copy
    from ui_api.dataset import start_integrate
    from ui_api.studies import StudyRefusal

    report = "DTXSID0000777"
    _write(sessions_dir / report, "studies.json", {"rat": f"{report}_rat"})
    _write(sessions_dir / report, "identity.json", {"name": "X", "dtxsid": report})
    member = sessions_dir / f"{report}_rat"
    _write(member, "files/data.txt", "doses")
    _write(member, "_fingerprints.json")
    _write(member, "validation_report.json")
    _write(member, "identity.json", {"name": "X", "dtxsid": report})
    demo_copy.make(report)
    with pytest.raises(StudyRefusal) as e:
        start_integrate(f"{report}_rat")
    assert e.value.code == "demo_reference" and core == []


# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------

@pytest.fixture
def process(study, monkeypatch):
    """Process and the two writes after it, stood in for.  The stand-in for
    Process records the cache events the core records: one unit computed, one
    reused."""
    import safeguards.acts
    import safeguards.guarded as guarded
    from common import provenance

    calls: list = []
    monkeypatch.setattr(safeguards.acts, "require", lambda *a, **k: calls.append(("require", a[1:], k)))

    async def process_step(dtxsid, params, store):
        calls.append(("process", params))
        provenance.record("cache_miss", dtxsid=dtxsid, unit="ntp", hash="a")
        provenance.record("cache_saved", dtxsid=dtxsid, unit="ntp", hash="a", bytes=1)
        provenance.record("cache_hit", dtxsid=dtxsid, unit="interpretation_liver_female",
                          hash="b", bytes=1)
        provenance.record("cache_miss", dtxsid="DTXSID0000999", unit="charts", hash="c")
        provenance.record("content_regenerated", dtxsid=dtxsid, ms=71364.6)
        return {"sections": [{}, {}], "genomics_sections": [{}], "methods": {"sections": []}}

    def materialize_result_sections(dtxsid, store):
        calls.append(("sections",))
        return {"ok": True, "materialized": ["bm2_body-weight", "bm2_organ-weight"],
                "unchanged": ["bm2_hematology"], "held": [],
                "needs_review": [{"key": "bm2_organ-weight", "why": "numbers_changed",
                                  "prior_version": 1, "version": 2, "flips": []}]}

    def materialize_summary(dtxsid, store):
        calls.append(("summary",))
        return {"ok": True, "written": True, "paragraphs": 3}

    monkeypatch.setattr(guarded, "process_step", process_step)
    monkeypatch.setattr(guarded, "materialize_result_sections", materialize_result_sections)
    monkeypatch.setattr(guarded, "materialize_summary", materialize_summary)
    return calls


def test_process_runs_the_analysis_then_writes_sections_and_summary(study, process):
    from ui_api import runs
    from ui_api.process_run import start_process
    from workflow.phases import Action

    _write(study, "references.json", {"references": [], "warnings": [{"token": "[P9]"}]})
    events = _events(start_process(ID))
    # Checked before anything runs: the act, with the method choice and the parameters.
    assert process[0][0] == "require" and process[0][1][0] == Action.PROCESS
    assert process[0][2] == {"method": True}
    # No run parameter but the test article's short name, as the command line passes it.
    assert process[1:] == [("process", {"compound_name": "TC"}), ("sections",), ("summary",)]
    assert _steps(events) == [
        ("process", "computing"),
        ("unit:ntp", "computing"), ("unit:ntp", "done"),
        ("unit:interpretation_liver_female", "reused"),
        ("unit:content", "done"),
        ("process", "done"),
        ("result_sections", "computing"), ("result_sections", "done"),
        ("summary", "computing"), ("summary", "done")]
    says = {e["unit"]: e["say"] for e in events if e["event"] == "step"}
    assert says["unit:ntp"] == "Statistics of the apical endpoints"
    assert says["unit:interpretation_liver_female"] == "Gene-level interpretation: liver, female"
    assert events[-1] == {"event": "result", "ok": True, "summary": {
        "test_article": "TC",
        "units": {"recorded": True,
                  "computed": [{"unit": "ntp", "say": "Statistics of the apical endpoints"},
                               {"unit": "content", "say": "Drafted text: the results sentences "
                                                          "and the gene-level interpretation"}],
                  "reused": [{"unit": "interpretation_liver_female",
                              "say": "Gene-level interpretation: liver, female"}]},
        "analysis": {"apical_sections": 2, "genomics_sections": 1, "methods": True},
        "result_sections": {"written": ["bm2_body-weight", "bm2_organ-weight"],
                            "unchanged": ["bm2_hematology"]},
        "approvals_affected": {"needs_review": [{"key": "bm2_organ-weight",
                                                 "why": "numbers_changed"}], "held": []},
        "summary": {"written": True, "paragraphs": 3, "held": None},
        "citations_removed": 1}}
    assert runs.current(ID) is None


def test_what_was_not_recorded_is_not_said(study, process):
    import logging

    from common import provenance
    from ui_api.process_run import start_process

    provenance.logger.setLevel(logging.WARNING)            # events switched off
    try:
        summary = _events(start_process(ID))[-1]["summary"]
    finally:
        provenance.logger.setLevel(logging.INFO)
    assert summary["units"] == {"recorded": False}
    assert summary["citations_removed"] is None           # the run wrote no reference list


def test_process_is_refused_before_it_starts(study):
    """The real checks: the files are not combined, so Process is not legal."""
    from safeguards.refusals import PhaseRefusal
    from ui_api import runs
    from ui_api.process_run import start_process

    with pytest.raises(PhaseRefusal):
        start_process(ID)
    assert runs.current(ID) is None


def test_a_failed_process_writes_no_sections(study, process, monkeypatch):
    import safeguards.guarded as guarded
    from ui_api.process_run import start_process
    from workflow.errors import StepError

    async def fails(dtxsid, params, store):
        raise StepError("Processing failed: boom", status_code=500)

    monkeypatch.setattr(guarded, "process_step", fails)
    events = _events(start_process(ID))
    assert events[-1]["event"] == "error" and events[-1]["error"]["code"] == "processing_failed"
    assert ("sections",) not in process and ("summary",) not in process


def test_a_unit_the_table_does_not_know_keeps_the_cores_name():
    from ui_api.process_run import unit_say

    assert unit_say("bmds") == "Benchmark dose modeling of the apical endpoints"
    assert unit_say("something_new") == "something_new"


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

def test_the_integrate_route_streams_ndjson(study, core, client):
    with client.stream("POST", f"/api/v2/studies/{ID}/integrate") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        events = _events(line for line in r.iter_lines() if line)
    assert events[0] == {"event": "step", "unit": "integrate", "status": "computing",
                         "say": "Combining the files into one dataset"}
    assert events[-1]["event"] == "result" and events[-1]["ok"] is True


def test_a_refusal_before_the_start_is_an_envelope_with_its_status(study, core, client):
    r = client.post(f"/api/v2/studies/{ID}/process")
    body = r.json()["error"]
    assert (r.status_code, body["code"], body["fix"]) == (409, "phase_not_allowed", "M3")
    assert body["details"]["action"] == "PROCESS"
    r = client.post("/api/v2/studies/DTXSID0000999/integrate")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "study_not_found")
    assert core == []


def test_the_process_route_streams_the_result(study, process, client):
    with client.stream("POST", f"/api/v2/studies/{ID}/process") as r:
        assert r.status_code == 200
        events = _events(line for line in r.iter_lines() if line)
    assert events[-1]["summary"]["result_sections"]["written"] == ["bm2_body-weight",
                                                                   "bm2_organ-weight"]


def test_the_steps_address_nobody(study, core, process):
    import re

    from ui_api.dataset import start_integrate
    from ui_api.process_run import _UNIT_SAY

    says = [e["say"] for e in _events(start_integrate(ID)) if e["event"] == "step"]
    for text in (*says, *_UNIT_SAY.values()):
        assert not re.search(r"\b(you|your|yours)\b", text, re.I), text
