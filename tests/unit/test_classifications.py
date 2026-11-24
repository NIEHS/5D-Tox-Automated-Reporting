"""What a person says a study file is, kept (pipeline.classifications).

The file check reads a file's assay and kind of data from its name. When it
reads one wrongly a person corrects it, and that correction has to survive the
next check — before `classifications.json` it did not.
"""

import json

import pytest

from pipeline import classifications as cl


@pytest.fixture
def study(tmp_path):
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "hormones_truth_male.txt").write_text("a pivot")
    return tmp_path


# ---------------------------------------------------------------------------
# Which statements can be made
# ---------------------------------------------------------------------------

def test_a_table_of_the_studys_own_measurements_names_its_assay(study):
    assert cl.problem("Hormones", "tox_study", "table") is None
    assert cl.problem(None, "tox_study", "table") == (
        "A file of the study's own measurements needs the assay it measures.")


def test_gene_expression_has_no_assay(study):
    assert cl.problem(None, "gene_expression", "bm2") is None
    assert "leave the assay empty" in cl.problem("Hormones", "gene_expression", "bm2")


def test_a_kind_of_file_only_holds_what_it_can_hold(study):
    # A BMDExpress project is never the study's own measurements.
    why = cl.problem("Hormones", "tox_study", "bm2")
    assert why.startswith("A BMDExpress project holds")
    assert "not the study's own measurements" in why
    # A workbook is only ever the study's own measurements.
    assert cl.problem(None, "gene_expression", "workbook")
    assert cl.problem("Hormones", "tox_study", "workbook") is None


def test_a_value_outside_the_vocabulary_is_refused(study):
    assert cl.problem("Phrenology", "tox_study", "table") == (
        "'Phrenology' is not an assay this application knows.")
    assert cl.problem("Hormones", "vibes", "table") == (
        "'vibes' is not a kind of data this application knows.")


def test_the_kind_of_a_file_comes_from_its_type():
    assert cl.kind_of("xlsx") == "workbook"
    assert cl.kind_of("bm2") == "bm2"
    assert cl.kind_of("txt") == cl.kind_of("csv") == "table"


# ---------------------------------------------------------------------------
# Keeping them
# ---------------------------------------------------------------------------

def test_a_statement_is_kept_with_who_and_when(study):
    said = cl.state(study, "hormones_truth_male.txt", "Hormones", "tox_study", "table")
    assert said["platform"] == "Hormones" and said["data_type"] == "tox_study"
    assert said["by"] == "person" and said["at"]
    assert said["seen"]["size"] == len("a pivot")

    on_disk = json.loads((study / "classifications.json").read_text())
    assert on_disk["hormones_truth_male.txt"]["platform"] == "Hormones"


def test_a_statement_that_cannot_be_made_is_not_written(study):
    with pytest.raises(ValueError):
        cl.state(study, "hormones_truth_male.txt", None, "tox_study", "table")
    assert not (study / "classifications.json").exists()


def test_a_statement_can_be_dropped(study):
    cl.state(study, "hormones_truth_male.txt", "Hormones", "tox_study", "table")
    assert cl.clear(study, "hormones_truth_male.txt") is True
    assert cl.read(study) == {}
    assert cl.clear(study, "hormones_truth_male.txt") is False


def test_a_study_with_no_statements_reads_as_none(tmp_path):
    assert cl.read(tmp_path) == {}


def test_an_unreadable_file_is_no_statement(study):
    (study / "classifications.json").write_text("{ not json")
    assert cl.read(study) == {}


# ---------------------------------------------------------------------------
# Applying them
# ---------------------------------------------------------------------------

def test_a_statement_stands_over_what_was_detected(study):
    cl.state(study, "hormones_truth_male.txt", "Hormones", "tox_study", "table")
    fps = {"scan-hormones_truth_male.txt": {
        "filename": "hormones_truth_male.txt",
        "platform": "Body Weight", "data_type": "inferred"}}

    assert cl.apply(study, fps) == 1
    said = fps["scan-hormones_truth_male.txt"]
    assert said["platform"] == "Hormones" and said["data_type"] == "tox_study"


def test_a_file_with_no_statement_keeps_what_was_detected(study):
    fps = {"scan-x.txt": {"filename": "x.txt", "platform": "Body Weight",
                          "data_type": "tox_study"}}
    assert cl.apply(study, fps) == 0
    assert fps["scan-x.txt"]["platform"] == "Body Weight"


def test_a_statement_about_a_file_no_longer_there_speaks_for_nothing(study):
    cl.state(study, "hormones_truth_male.txt", "Hormones", "tox_study", "table")
    assert cl.apply(study, {"scan-other.txt": {"filename": "other.txt"}}) == 0
    # It is kept: the file may come back.
    assert "hormones_truth_male.txt" in cl.read(study)


def test_a_correction_survives_the_next_file_check(sessions_dir):
    """The reason this module exists. The check reads a file's assay from its
    name; a person corrects it; the next check used to put the name's answer
    back."""
    from pipeline.pool_fingerprints import ensure_fingerprints

    dtxsid = "DTXSID_M2_STATEMENT"
    d = sessions_dir / dtxsid
    (d / "files").mkdir(parents=True)
    (d / "files" / "body_weight_truth_female.txt").write_text(
        "Animal ID\tDose\tSD0\n1\t0\t188.1\n2\t0\t190.2\n")

    detected = ensure_fingerprints(dtxsid, force=True)
    assert [fp.platform for fp in detected.values()] == ["Body Weight"]

    # A person says the file is something else.
    cl.state(d, "body_weight_truth_female.txt", "Hormones", "tox_study", "table")

    again = ensure_fingerprints(dtxsid, force=True)
    assert [fp.platform for fp in again.values()] == ["Hormones"]

    # And the cache the next cold start reads says so too.
    on_disk = json.loads((d / "_fingerprints.json").read_text())
    assert on_disk["body_weight_truth_female.txt"]["platform"] == "Hormones"


def test_a_file_changed_since_the_statement_is_noticed(study):
    cl.state(study, "hormones_truth_male.txt", "Hormones", "tox_study", "table")
    said = cl.read(study)["hormones_truth_male.txt"]
    assert cl.changed_since(study, "hormones_truth_male.txt", said) is False

    (study / "files" / "hormones_truth_male.txt").write_text("a different pivot")
    assert cl.changed_since(study, "hormones_truth_male.txt", said) is True
