"""What the file check found, in words a toxicologist reads
(workflow.file_issues).

The check writes its findings for a log. This turns one into the group it
belongs in, what it says, and what to do — with the files named as a person
brought them in.
"""

import json
from pathlib import Path

from workflow import file_issues as fi

NAMES = {"scan-body_weight_truth_female.txt": "body_weight_truth_female.txt",
         "scan-bw.xlsx": "108020006_Body_Weight.xlsx"}


def issue(**over):
    base = {"severity": "warning", "platform": "Body Weight|tox_study",
            "issue_type": "animal_count_mismatch", "message": "Body Weight|tox_study: a message",
            "files_involved": ["scan-body_weight_truth_female.txt"],
            "details": {"xlsx_count": 61, "txt_csv_count": 40}}
    return {**base, **over}


# ---------------------------------------------------------------------------
# The groups
# ---------------------------------------------------------------------------

def test_the_severity_decides_the_group_where_the_type_does_not():
    assert fi.say(issue(severity="error"), NAMES)["group"] == "fix"
    assert fi.say(issue(severity="warning"), NAMES)["group"] == "look"
    assert fi.say(issue(severity="info"), NAMES)["group"] == "expected"


def test_a_type_that_is_always_one_group_keeps_it():
    """A table whose values differ from the workbook always has to be fixed,
    whatever severity the check happened to give it."""
    said = fi.say(issue(issue_type="value_mismatch", severity="info",
                        details={"count": 1, "total": 243, "examples": []}), NAMES)
    assert said["group"] == "fix"


def test_a_missing_bmdexpress_project_is_expected_not_a_gap():
    """A BMDExpress project is not required for an apical assay: Process
    computes its benchmark doses itself (the maintainer, 2026-10-16)."""
    said = fi.say(issue(issue_type="missing_tier", severity="warning",
                        message="Body Weight|tox_study: no .bm2 (BMDExpress analysis) found"),
                  NAMES)
    assert said["group"] == "expected"
    assert said["say"] == ("Body Weight: no BMDExpress project. Process computes "
                           "this assay's benchmark doses itself.")


def test_a_workbook_with_no_table_written_from_it_is_worth_a_look():
    said = fi.say(issue(issue_type="missing_tier",
                        message="Body Weight|tox_study: no txt/csv (BMDExpress input) found"),
                  NAMES)
    assert said["group"] == "look"
    assert "no table was written from it" in said["say"]
    assert said["what_to_do"]


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------

def test_the_assay_is_named_as_a_person_names_it():
    """The check files a finding under the coverage key, which is how the
    dataset is indexed, not how an assay is spoken of."""
    said = fi.say(issue(), NAMES)
    assert said["say"].startswith("Body Weight: ")
    assert "|tox_study" not in said["say"]


def test_the_files_are_named_as_they_were_brought_in():
    said = fi.say(issue(issue_type="redundant_files", severity="info",
                        files_involved=["scan-body_weight_truth_female.txt", "scan-bw.xlsx"]),
                  NAMES)
    assert "body_weight_truth_female.txt and 108020006_Body_Weight.xlsx" in said["say"]
    assert said["files"] == ["body_weight_truth_female.txt", "108020006_Body_Weight.xlsx"]
    assert "scan-" not in said["say"]


def test_the_check_does_not_say_the_same_thing_twice():
    """The check's message already begins with the assay or the file name."""
    said = fi.say(issue(issue_type="samples_unresolved", severity="warning",
                        platform="gene_expression",
                        message="body_weight_truth_female.txt: 198 samples not traced"),
                  NAMES)
    assert said["say"] == "body_weight_truth_female.txt: 198 samples not traced"


def test_a_value_difference_shows_one_example():
    said = fi.say(issue(issue_type="value_mismatch", severity="error",
                        details={"count": 1, "total": 243, "examples": [
                            {"animal_id": "111", "day": "SD0", "endpoint": "Body Weight",
                             "xlsx": "215.9", "csv": "251.9"}]}), NAMES)
    assert "animal 111 on SD0, Body Weight" in said["say"]
    assert "'215.9'" in said["say"] and "'251.9'" in said["say"]


def test_a_finding_the_data_review_accounts_for_says_so():
    assert fi.say(issue(issue_type="roster_subset", severity="info",
                        details={"sex": "Female", "file_count": 42,
                                 "roster_count": 61, "missing_count": 19}),
                  NAMES)["feeds"] == "M6"


def test_a_finding_the_application_will_not_settle_says_who_does():
    assert fi.say(issue(issue_type="redundant_files", severity="info"),
                  NAMES)["settle"] == "outside"


# ---------------------------------------------------------------------------
# What it does not know
# ---------------------------------------------------------------------------

def test_an_unknown_finding_keeps_the_checks_own_message():
    said = fi.say(issue(issue_type="something_new", message="A new kind of finding."), NAMES)
    assert said["known"] is False
    assert said["say"] == "A new kind of finding."
    assert said["group"] == "look"


def test_a_field_the_finding_does_not_carry_is_visible_not_invented():
    said = fi.say(issue(details={}), NAMES)
    assert "[xlsx_count not recorded]" in said["say"]


# ---------------------------------------------------------------------------
# Naming a finding
# ---------------------------------------------------------------------------

def test_a_finding_has_the_same_name_every_time_it_is_found():
    assert fi.issue_id(issue(), NAMES) == fi.issue_id(issue(), NAMES)


def test_a_finding_that_says_something_else_has_another_name():
    assert fi.issue_id(issue(), NAMES) != fi.issue_id(issue(message="other"), NAMES)


# ---------------------------------------------------------------------------
# On a real study
# ---------------------------------------------------------------------------

def test_every_finding_of_a_real_study_is_recognized():
    """NIEHS-12's rat study, as the check last recorded it."""
    report = Path("sessions/DTXSID6020430_rat/validation_report.json")
    if not report.is_file():
        import pytest
        pytest.skip("the real session is not in this checkout")
    data = json.loads(report.read_text())
    names = {fid: fp.get("filename", fid)
             for fid, fp in (data.get("fingerprints") or {}).items()}
    said = [fi.say(one, names) for one in data["issues"]]

    assert said, "the report records findings"
    assert [one for one in said if not one["known"]] == []
    assert all(one["say"] and not one["say"].startswith("scan-") for one in said)
    assert set(fi.counts(said)) == set(fi.GROUPS)
