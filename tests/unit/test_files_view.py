"""The Study files page's read (ui_api.files.files_view, module M2).

Everything the page shows is derived here, on each read: the browser works out
no phase, no readiness and no act. The read has no side effects.
"""

import json

import pytest

from ui_api.files import files_view
from ui_api.studies import StudyRefusal

DTX = "DTXSID_M2"

_FP = {
    "108020006_Body_Weight.xlsx": {
        "file_id": "scan-108020006_Body_Weight.xlsx",
        "filename": "108020006_Body_Weight.xlsx", "file_type": "xlsx", "tier": 1,
        "platform": "Body Weight", "data_type": "tox_study", "is_study_file": True,
        "sexes": ["Female"], "dose_groups": [0.0, 100.0], "dose_unit": "ppm",
        "animal_ids": ["1", "2", "3"], "n_animals_by_dose": {"0.0": 2, "100.0": 1},
        "endpoint_names": ["Body Weight", "SD0"], "ts_added": "2026-11-24T10:00:00+00:00",
        "derived_from": None,
    },
    "body_weight_truth_female.txt": {
        "file_id": "scan-body_weight_truth_female.txt",
        "filename": "body_weight_truth_female.txt", "file_type": "txt", "tier": 2,
        "platform": "Body Weight", "data_type": "tox_study", "is_study_file": False,
        "sexes": ["Female"], "dose_groups": [0.0, 100.0],
        "animal_ids": ["1", "2"], "endpoint_names": ["Body Weight"],
        "derived_from": "108020006_Body_Weight.xlsx",
    },
}

_REPORT = {
    "dtxsid": DTX, "run_at": "2026-11-24T10:05:00+00:00", "file_count": 2,
    "fingerprints": {fp["file_id"]: fp for fp in _FP.values()},
    "issues": [{
        "severity": "warning", "platform": "Body Weight|tox_study",
        "issue_type": "animal_count_mismatch",
        "message": "Body Weight|tox_study: txt/csv files have 2 unique animals vs 3 in xlsx",
        "files_involved": ["scan-body_weight_truth_female.txt"],
        "details": {"xlsx_count": 3, "txt_csv_count": 2},
    }],
    "coverage_matrix": {"Body Weight|tox_study": {
        "xlsx": "scan-108020006_Body_Weight.xlsx",
        "txt_csv": ["scan-body_weight_truth_female.txt"], "bm2": None}},
    "is_complete": False,
}


def _seed(sessions_dir, *, checked=True, stated=None):
    d = sessions_dir / DTX
    files = d / "files"
    files.mkdir(parents=True)
    (files / "108020006_Body_Weight.xlsx").write_bytes(b"PK\x03\x04 a workbook")
    (files / "body_weight_truth_female.txt").write_text("a pivot")
    (files / "body_weight_truth_female.sidecar.json").write_text(json.dumps(
        {"source": "108020006_Body_Weight.xlsx", "units": {"Body Weight": "grams"}}))
    (d / "identity.json").write_text(json.dumps({"name": "Test", "dtxsid": DTX}))
    (d / "_fingerprints.json").write_text(json.dumps(_FP))
    if checked:
        (d / "validation_report.json").write_text(json.dumps(_REPORT))
    if stated:
        (d / "classifications.json").write_text(json.dumps(stated))
    return d


# ---------------------------------------------------------------------------
# Which files are rows
# ---------------------------------------------------------------------------

def test_a_row_is_a_file_a_person_brought_in(sessions_dir):
    """The check writes a table from a study workbook (ADR-0032). The workbook
    is what was brought in; the table and the check's note ride on it."""
    _seed(sessions_dir)
    view = files_view(DTX)

    assert [row["name"] for row in view["files"]] == ["108020006_Body_Weight.xlsx"]
    rides = view["files"][0]["companions"]
    assert sorted(c["name"] for c in rides) == [
        "body_weight_truth_female.sidecar.json", "body_weight_truth_female.txt"]
    assert {c["role"] for c in rides} == {"sidecar", "table"}


def test_a_row_carries_what_the_check_recorded_of_it(sessions_dir):
    _seed(sessions_dir)
    row = files_view(DTX)["files"][0]

    assert row["kind"] == "workbook" and row["kind_say"] == "Study workbook"
    assert row["checked"] is True
    assert row["tables"][0]["animals"] == 3
    assert row["tables"][0]["doses"] == [0.0, 100.0]
    assert row["tables"][0]["dose_unit"] == "ppm"
    assert row["size"] > 0


# ---------------------------------------------------------------------------
# What a file is
# ---------------------------------------------------------------------------

def test_nothing_is_confirmed_by_default(sessions_dir):
    _seed(sessions_dir)
    said = files_view(DTX)["files"][0]["classification"]

    assert said["status"] == "unconfirmed"
    assert said["say"] == "Body Weight · the study's own measurements"
    assert said["detected"]["basis"] == "file_name"
    assert said["stated"] is None
    assert any(p["what"] == "classification" for p in files_view(DTX)["files"][0]["pending"])


def test_a_person_s_statement_stands_and_says_so(sessions_dir):
    _seed(sessions_dir, stated={"108020006_Body_Weight.xlsx": {
        "platform": "Hormones", "data_type": "tox_study",
        "by": "person", "at": "2026-11-24T11:00:00+00:00", "seen": None}})
    said = files_view(DTX)["files"][0]["classification"]

    assert said["platform"] == "Hormones"
    assert said["status"] == "changed"
    assert said["detected"]["platform"] == "Body Weight"
    assert said["stated"]["by"] == "person"


def test_a_statement_that_agrees_with_the_check_reads_as_confirmed(sessions_dir):
    _seed(sessions_dir, stated={"108020006_Body_Weight.xlsx": {
        "platform": "Body Weight", "data_type": "tox_study",
        "by": "person", "at": "2026-11-24T11:00:00+00:00", "seen": None}})
    assert files_view(DTX)["files"][0]["classification"]["status"] == "confirmed"


def test_a_file_changed_since_it_was_confirmed_asks_again(sessions_dir):
    d = _seed(sessions_dir, stated={"108020006_Body_Weight.xlsx": {
        "platform": "Body Weight", "data_type": "tox_study", "by": "person",
        "at": "2026-11-24T11:00:00+00:00",
        "seen": {"size": 1, "modified_at": "2026-01-01T00:00:00+00:00"}}})
    assert (d / "files" / "108020006_Body_Weight.xlsx").stat().st_size != 1
    assert files_view(DTX)["files"][0]["classification"]["status"] == "needs_reconfirm"


def test_before_the_check_nothing_is_recognized_yet(sessions_dir):
    d = _seed(sessions_dir, checked=False)
    (d / "_fingerprints.json").unlink()
    view = files_view(DTX)

    assert view["check"] is None
    assert view["files"][0]["classification"]["status"] == "not_checked"
    assert view["files"][0]["checked"] is False


# ---------------------------------------------------------------------------
# The check and what it found
# ---------------------------------------------------------------------------

def test_the_findings_are_in_plain_words_and_name_no_file_id(sessions_dir):
    _seed(sessions_dir)
    view = files_view(DTX)

    assert len(view["issues"]) == 1
    found = view["issues"][0]
    assert found["group"] == "look"
    assert found["say"].startswith("Body Weight: ")
    assert found["files"] == ["body_weight_truth_female.txt"]
    assert "scan-" not in json.dumps(view)


def test_the_check_is_out_of_date_once_a_file_appears(sessions_dir):
    d = _seed(sessions_dir)
    assert files_view(DTX)["check"]["current"] is True

    (d / "files" / "organ_weights.xlsx").write_bytes(b"PK\x03\x04 another")
    check = files_view(DTX)["check"]
    assert check["current"] is False
    assert "organ_weights.xlsx" in check["why_not_current"]


def test_what_the_report_would_be_built_from(sessions_dir):
    _seed(sessions_dir)
    coverage = files_view(DTX)["coverage"]

    assert len(coverage) == 1
    assert coverage[0]["assay"] == "Body Weight"
    assert coverage[0]["workbook"] == "108020006_Body_Weight.xlsx"
    assert coverage[0]["tables"] == ["body_weight_truth_female.txt"]
    assert coverage[0]["level"] == "ok"


def test_an_assay_with_only_its_workbook_would_bring_nothing_in(sessions_dir):
    d = _seed(sessions_dir)
    report = json.loads((d / "validation_report.json").read_text())
    report["coverage_matrix"]["Body Weight|tox_study"]["txt_csv"] = []
    (d / "validation_report.json").write_text(json.dumps(report))

    row = files_view(DTX)["coverage"][0]
    assert row["level"] == "block"
    assert "no table was written from it" in row["say"] or "Only the study workbook" in row["say"]


# ---------------------------------------------------------------------------
# What can be done
# ---------------------------------------------------------------------------

def test_an_act_that_is_not_allowed_says_why(sessions_dir):
    d = _seed(sessions_dir, checked=False)
    (d / "validation_report.json").unlink(missing_ok=True)
    acts = files_view(DTX)["acts"]

    assert acts["add"]["allowed"] is True
    assert acts["classify"]["allowed"] is False
    assert acts["classify"]["code"] == "not_validated"
    assert acts["classify"]["say"]


def test_an_empty_study_is_told_to_bring_files_in(sessions_dir):
    (sessions_dir / DTX).mkdir(parents=True)
    (sessions_dir / DTX / "files").mkdir()
    view = files_view(DTX)

    assert view["files"] == []
    assert view["next"]["act"] == "ADD_FILES"
    assert view["acts"]["check"]["code"] == "no_files"
    assert view["progress"][0]["say"] == "No files yet"


def test_the_next_step_is_the_one_the_study_is_waiting_for(sessions_dir):
    _seed(sessions_dir)
    assert files_view(DTX)["next"]["act"] == "CONFIRM_CLASSIFICATION"

    _seed_confirmed(sessions_dir)
    assert files_view(DTX)["next"] == {
        "act": "INTEGRATE", "say": "Combine the files into one dataset", "fix": "M3"}


def test_a_correction_sends_a_person_back_to_the_check(sessions_dir):
    """A statement that disagrees with what the check concluded leaves the
    check describing something else."""
    _seed(sessions_dir, stated={"108020006_Body_Weight.xlsx": {
        "platform": "Hormones", "data_type": "tox_study",
        "by": "person", "at": "2026-11-24T11:00:00+00:00", "seen": None}})
    view = files_view(DTX)

    assert view["check"]["current"] is False
    assert "108020006_Body_Weight.xlsx" in view["check"]["why_not_current"]
    assert view["next"]["act"] == "VALIDATE"


def _seed_confirmed(sessions_dir):
    d = sessions_dir / DTX
    (d / "classifications.json").write_text(json.dumps({
        name: {"platform": fp["platform"], "data_type": fp["data_type"],
               "by": "person", "at": "2026-11-24T11:00:00+00:00", "seen": None}
        for name, fp in _FP.items()}))


# ---------------------------------------------------------------------------
# A study whose data is not its own
# ---------------------------------------------------------------------------

def test_a_report_over_several_studies_says_where_the_files_belong(sessions_dir):
    d = sessions_dir / "DTXSID_REPORT"
    d.mkdir(parents=True)
    (d / "identity.json").write_text(json.dumps({"name": "Test", "dtxsid": "DTXSID_REPORT"}))
    (d / "studies.json").write_text(json.dumps({"rat": DTX}))
    _seed(sessions_dir)

    view = files_view("DTXSID_REPORT")
    assert view["takes_files"]["allowed"] is False
    assert view["takes_files"]["code"] == "takes_no_files"
    assert DTX in view["takes_files"]["say"]
    assert view["files"] == []
    assert all(act["allowed"] is False for act in view["acts"].values())


def test_a_study_that_is_not_there_is_refused(sessions_dir):
    with pytest.raises(StudyRefusal) as refusal:
        files_view("DTXSID_NOT_HERE")
    assert refusal.value.code == "study_not_found"


# ---------------------------------------------------------------------------
# The read leaves no trace
# ---------------------------------------------------------------------------

def test_reading_the_page_changes_nothing(sessions_dir):
    """No re-scan, no file id minted, nothing written — not even a folder."""
    d = _seed(sessions_dir)

    def snapshot():
        return {str(p.relative_to(d)): (p.stat().st_size, p.stat().st_mtime_ns)
                for p in sorted(d.rglob("*")) if p.is_file()}

    before = snapshot()
    files_view(DTX)
    files_view(DTX)
    assert snapshot() == before


def test_the_read_never_opens_a_study_file(sessions_dir, monkeypatch):
    """CONTEXT.md invariant 1: the page reads what the check recorded, never
    the study's raw files."""
    _seed(sessions_dir)
    import bmdx_pipe

    def refuse(*_a, **_k):
        raise AssertionError("the view read a study file")

    monkeypatch.setattr(bmdx_pipe, "fingerprint_file", refuse, raising=False)
    view = files_view(DTX)
    assert view["files"]


def test_the_read_does_not_create_a_session_folder(sessions_dir):
    with pytest.raises(StudyRefusal):
        files_view("DTXSID_ABSENT")
    assert not (sessions_dir / "DTXSID_ABSENT").exists()
