"""tooling/demo_copy: a live copy of a finished report, for a demonstration.

The copy holds what a study holds once its files are checked and its facts are
stated (workflow steps 1-4, 6, 7) and nothing made from them; it is fixed to
its source's report definition; only a folder carrying the tool's marker is
ever deleted.
"""

import json

import pytest

from common import paths
from tooling import demo_copy as dc

REPORT = "DTXSID0000777"


def _write(folder, name, content="{}"):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))


@pytest.fixture
def store(sessions_dir):
    """A finished report over two studies, in a store of its own."""
    root = sessions_dir
    assert paths.SESSIONS_DIR == root
    report = root / REPORT
    _write(report, "studies.json", {"rat": f"{REPORT}_rat", "mouse": f"{REPORT}_mouse"})
    _write(report, "identity.json", {"name": "X"})
    _write(report, "background.json", {"paragraphs": ["written"]})
    for key in ("rat", "mouse"):
        study = root / f"{REPORT}_{key}"
        _write(study, "files/data.txt", "doses")
        _write(study, "_fingerprints.json")
        _write(study, "validation_report.json")
        _write(study, "study_design.json", {"dosingDays": 5})
        _write(study, "method_profile.json", {"name": "ntp-5day-2025"})
        _write(study, "integrated.json")
        _write(study, "animal_report.json")
        _write(study, "bm2_body-weight.json")
        _write(study, "_cache_ntp_abc.json")
        _write(study, "references.json")
        _write(study, "history/summary/v1.json")
    return root


def test_the_copy_holds_the_checked_files_and_the_declarations_and_nothing_made_from_them(store):
    out = dc.make(REPORT)
    assert out["copy"] == f"{REPORT}_live"
    rat = store / f"{REPORT}_live_rat"
    assert sorted(p.name for p in rat.iterdir()) == [
        "_fingerprints.json", "demo_copy.json", "document_definition.json",
        "document_definition.yaml", "files", "method_profile.json", "study_design.json",
        "validation_report.json"]
    assert (rat / "files" / "data.txt").read_text() == "doses"
    report = store / f"{REPORT}_live"
    assert not (report / "background.json").exists()
    assert json.loads((report / "studies.json").read_text()) == {
        "rat": f"{REPORT}_live_rat", "mouse": f"{REPORT}_live_mouse"}
    marker = json.loads((rat / "demo_copy.json").read_text())
    assert (marker["of"], marker["source"]) == (REPORT, f"{REPORT}_rat")
    assert not list(rat.glob("_cache_*.json"))  # integration would clear it anyway
    # The finished report is only read.
    assert (store / f"{REPORT}_rat" / "integrated.json").exists()
    assert not (store / f"{REPORT}_rat" / "demo_copy.json").exists()


def test_the_copy_is_fixed_to_its_sources_report_definition(store):
    from document_model.definition_pin import read_pin
    from document_model.document_definition import current_definition_name, definition_name

    dc.make(REPORT)
    for source, copy in ((REPORT, f"{REPORT}_live"), (f"{REPORT}_rat", f"{REPORT}_live_rat")):
        pin = read_pin(copy)
        assert (pin["mode"], pin["name"]) == ("fixed", current_definition_name(source))
        assert definition_name(copy) == f"@pinned/{copy}"


def test_the_copy_reads_as_checked_with_integrate_next(store):
    from workflow.engine import WorkflowEngine

    dc.make(REPORT)
    state = WorkflowEngine(f"{REPORT}_live_rat").state()
    assert state.phase.name == "VALIDATED"
    assert "INTEGRATE" in {a.name for a in state.legal_actions}


def test_the_pair_is_named_in_a_partition(store):
    dc.make(REPORT)
    assert json.loads((store / "_partitions.json").read_text()) == {
        "Demo": [REPORT, f"{REPORT}_live"]}
    dc.remove(REPORT)
    assert not (store / "_partitions.json").exists()
    assert not (store / f"{REPORT}_live").exists()
    assert (store / REPORT).exists()


def test_a_second_copy_and_a_copy_of_a_copy_are_refused(store):
    dc.make(REPORT)
    with pytest.raises(dc.DemoCopyError, match="a copy already exists"):
        dc.make(REPORT)
    with pytest.raises(dc.DemoCopyError, match="is itself a live copy"):
        dc.make(f"{REPORT}_live")


def test_reset_puts_the_copy_back_to_its_start_state(store):
    dc.make(REPORT)
    rat = store / f"{REPORT}_live_rat"
    _write(rat, "integrated.json")
    _write(rat, "bm2_body-weight.json")
    _write(rat, "_cache_sections_own.json")
    assert dc.status(REPORT)["sessions"][1]["beyond_start"] == [
        "_cache_sections_own.json", "bm2_body-weight.json", "integrated.json"]
    dc.reset(REPORT)
    assert dc.status(REPORT)["sessions"][1]["beyond_start"] == []
    assert (rat / "files" / "data.txt").exists()


def test_only_a_folder_with_the_marker_is_ever_deleted(store):
    someone_elses = store / f"{REPORT}_live_rat"
    _write(someone_elses, "integrated.json")
    with pytest.raises(dc.DemoCopyError, match="is not a live copy"):
        dc.remove(REPORT)
    with pytest.raises(dc.DemoCopyError, match="is not a live copy"):
        dc.reset(REPORT)
    assert (someone_elses / "integrated.json").exists()
    with pytest.raises(dc.DemoCopyError, match="no live copy to reset"):
        dc.reset("DTXSID0000777_mouse")


def test_a_background_run_is_recorded_with_the_exact_prompt():
    """What a demonstration shows of the Background: the prompt that was sent."""
    from narrative.background_writer import background_run_record

    result = {"prompt": {"system": "s", "user": "u"}, "model_used": "m", "paragraphs": ["p"],
              "references": ["r"], "citation_report": {"issues": []}, "text": "raw"}
    record = background_run_record("DTXSID0000777", result, version=3)
    assert record == {"section": "background", "dtxsid": "DTXSID0000777",
                      "prompt": {"system": "s", "user": "u"}, "model_used": "m",
                      "paragraphs": ["p"], "references": ["r"],
                      "citation_report": {"issues": []}, "section_version": 3}
