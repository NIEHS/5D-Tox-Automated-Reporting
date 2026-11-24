"""Checking files before they join a study (pipeline.intake).

A file that should not be in a study is cheapest to refuse before it is
written, and a file that would replace one already there must not be written
until a person says so. Nothing here writes into the study.
"""

import json
import zipfile

import pytest

from pipeline import intake

BM2 = b"\xac\xed\x00\x05" + b"a BMDExpress project"
XLSX = b"PK\x03\x04" + b"a workbook"
TABLE = "Animal ID\tDose\tSD0\n1\t0\t188.1\n"
WIDE = "Dose\tBody Weight\n0\t188.1\n"


@pytest.fixture
def study(tmp_path):
    (tmp_path / "session" / "files").mkdir(parents=True)
    (tmp_path / "batch").mkdir()
    return tmp_path


def plan(study, answers=None):
    return intake.plan(study / "session", study / "batch", answers)


def put(study, name, content=TABLE):
    f = study / "batch" / name
    f.write_bytes(content if isinstance(content, bytes) else content.encode())
    return f


def already(study, name, content=TABLE):
    f = study / "session" / "files" / name
    f.write_bytes(content if isinstance(content, bytes) else content.encode())
    return f


def only(rows, name):
    return next(r for r in rows if r.name == name)


# ---------------------------------------------------------------------------
# A file that cannot be brought in
# ---------------------------------------------------------------------------

def test_a_file_that_is_not_data_is_refused_by_its_ending(study):
    put(study, "notes.pdf", b"%PDF-1.4")
    row = only(plan(study), "notes.pdf")
    assert row.verdict == "refused" and row.code == "file_type_refused"
    assert "not a data file" in row.say


def test_an_empty_file_is_refused(study):
    put(study, "nothing.csv", "")
    assert only(plan(study), "nothing.csv").code == "empty_file"


def test_a_file_the_application_writes_itself_is_refused(study):
    put(study, "body_weight.sidecar.json", "{}")
    row = only(plan(study), "body_weight.sidecar.json")
    assert row.code == "sidecar_refused"
    assert "the table it belongs to" in row.say


def test_a_name_that_cannot_be_used_is_refused(study):
    put(study, ".hidden.csv")
    assert only(plan(study), ".hidden.csv").code == "name_invalid"


def test_contents_are_checked_against_the_ending(study):
    """A text table named .bm2 would be read as a BMDExpress project."""
    put(study, "hormones.bm2", TABLE)
    row = only(plan(study), "hormones.bm2")
    assert row.code == "content_mismatch"
    assert "is named .bm2 but its contents are not" in row.say


def test_a_real_bmdexpress_project_is_taken(study):
    put(study, "genomic.bm2", BM2)
    assert only(plan(study), "genomic.bm2").verdict == "add"


# ---------------------------------------------------------------------------
# A file already in the study
# ---------------------------------------------------------------------------

def test_the_same_file_again_is_not_brought_in_twice(study):
    already(study, "body_weight.csv")
    put(study, "body_weight.csv")
    row = only(plan(study), "body_weight.csv")
    assert row.verdict == "unchanged"
    assert row.needs_answer is None
    assert intake.counts(plan(study))["add"] == 0


def test_replacing_a_file_needs_an_answer(study):
    already(study, "body_weight.csv", "Animal ID\tDose\n1\t0\n")
    put(study, "body_weight.csv", "Animal ID\tDose\n1\t999\n")

    row = only(plan(study), "body_weight.csv")
    assert row.verdict == "replace" and row.needs_answer == "replace"
    assert row.replaces["name"] == "body_weight.csv"
    assert "kept among the removed files" in row.say

    answered = only(plan(study, {"replace": ["body_weight.csv"]}), "body_weight.csv")
    assert answered.needs_answer is None


def test_the_same_contents_under_another_name_needs_an_answer(study):
    already(study, "body_weight.csv")
    put(study, "body_weight_2.csv")

    row = only(plan(study), "body_weight_2.csv")
    assert row.verdict == "copy" and row.needs_answer == "copy"
    assert row.copy_of == {"name": "body_weight.csv", "where": "study"}
    assert "count twice" in row.say

    assert only(plan(study, {"copy_anyway": ["body_weight_2.csv"]}),
                "body_weight_2.csv").needs_answer is None


def test_two_files_of_one_batch_with_the_same_contents(study):
    put(study, "a.csv", WIDE)
    put(study, "b.csv", WIDE)
    rows = plan(study)
    assert only(rows, "a.csv").verdict == "add"
    assert only(rows, "b.csv").verdict == "copy"
    assert only(rows, "b.csv").copy_of["where"] == "batch"


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def test_a_table_of_one_row_per_animal_without_units_needs_an_answer(study):
    put(study, "body_weight.csv", TABLE)
    row = only(plan(study), "body_weight.csv")
    assert row.verdict == "units_missing" and row.needs_answer == "without_units"
    assert "[units pending]" in row.say


def test_a_units_file_brought_in_with_its_table(study):
    put(study, "body_weight.csv", TABLE)
    put(study, "body_weight.units.json", json.dumps({"Body Weight": "grams"}))
    rows = plan(study)
    assert only(rows, "body_weight.csv").verdict == "add"
    units = only(rows, "body_weight.units.json")
    assert units.verdict == "units" and units.pairs_with == "body_weight.csv"


def test_a_units_file_with_no_table_is_refused(study):
    put(study, "hormones.units.json", json.dumps({"T4": "ng/dL"}))
    row = only(plan(study), "hormones.units.json")
    assert row.code == "units_without_table"
    assert "Bring them in together" in row.say


def test_a_units_file_that_is_not_a_list_of_units_is_refused(study):
    put(study, "body_weight.csv", TABLE)
    put(study, "body_weight.units.json", json.dumps(["grams"]))
    assert only(plan(study), "body_weight.units.json").code == "units_invalid"


def test_a_table_that_is_not_one_row_per_animal_needs_no_units(study):
    put(study, "body_weight_truth_female.txt", WIDE)
    assert only(plan(study), "body_weight_truth_female.txt").verdict == "add"


# ---------------------------------------------------------------------------
# A zip
# ---------------------------------------------------------------------------

def _zip(study, name, entries):
    path = study / "batch" / name
    with zipfile.ZipFile(path, "w") as z:
        for entry, content in entries.items():
            z.writestr(entry, content)
    return path


def test_a_zip_stands_for_the_files_inside_it(study):
    _zip(study, "package.zip", {"NIEHS-99/body_weight.xlsx": XLSX,
                                "NIEHS-99/genomic.bm2": BM2})
    rows = plan(study)
    assert {r.name for r in rows} == {"body_weight.xlsx", "genomic.bm2"}
    assert all(r.verdict == "add" for r in rows)
    assert only(rows, "body_weight.xlsx").from_zip == "NIEHS-99"


def test_what_a_package_carries_that_is_not_data_is_left_out(study):
    """A real package carries PDFs and supplementary archives."""
    _zip(study, "package.zip", {"p/body_weight.xlsx": XLSX,
                                "p/metadata.pdf": b"%PDF-1.4",
                                "p/read_counts.zip": b"PK\x03\x04 inner"})
    rows = plan(study)
    assert only(rows, "body_weight.xlsx").verdict == "add"
    assert only(rows, "metadata.pdf").verdict == "left_out"
    inner = only(rows, "read_counts.zip")
    assert inner.verdict == "left_out"
    assert "supplementary" in inner.say


def test_a_zip_holding_only_another_zip_is_refused(study):
    _zip(study, "wrapper.zip", {"inner.zip": b"PK\x03\x04 inner"})
    row = only(plan(study), "wrapper.zip")
    assert row.code == "zip_nested"


def test_a_zip_with_two_files_of_one_name_is_refused(study):
    _zip(study, "package.zip", {"a/body_weight.xlsx": XLSX, "b/body_weight.xlsx": XLSX})
    row = only(plan(study), "package.zip")
    assert row.code == "zip_name_clash"
    assert "cannot know which" in row.say


def test_a_damaged_zip_is_refused(study):
    put(study, "broken.zip", b"PK\x03\x04 not really a zip")
    assert only(plan(study), "broken.zip").code == "zip_invalid"


# ---------------------------------------------------------------------------
# Nothing is written
# ---------------------------------------------------------------------------

def test_planning_writes_nothing_into_the_study(study):
    already(study, "body_weight.csv")
    put(study, "body_weight.csv", "different")
    put(study, "notes.pdf", b"%PDF")
    before = {p.name: p.read_bytes() for p in (study / "session" / "files").iterdir()}

    plan(study)
    after = {p.name: p.read_bytes() for p in (study / "session" / "files").iterdir()}
    assert after == before


def test_the_counts_say_what_would_happen(study):
    already(study, "there.csv", WIDE)
    put(study, "there.csv", WIDE)
    put(study, "new.txt", "Dose\tLiver Weight\n0\t9.9\n")
    put(study, "notes.pdf", b"%PDF")
    put(study, "replacing.csv", "Dose\tKidney Weight\n0\t1.4\n")
    already(study, "replacing.csv", "Dose\tKidney Weight\n0\t1.1\n")

    counts = intake.counts(plan(study))
    assert counts["add"] == 1          # new.txt; the replacement waits on an answer
    assert counts["unchanged"] == 1
    assert counts["refused"] == 1
    assert counts["needs_answer"] == 1
