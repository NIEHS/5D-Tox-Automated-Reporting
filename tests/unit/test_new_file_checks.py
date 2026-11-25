"""The three checks that keep the file step's promise.

The step promises "nothing missing, nothing twice, nothing from another
study". Each of these is an error, so it stops the files from being combined
until a person settles it — which is why each one leans away from raising
when it is not sure.
"""

import pytest

from bmdx_pipe.file_integrator import (
    FileFingerprint,
    _check_duplicate_contents,
    _check_name_against_contents,
    _check_test_articles,
    _same_article,
    content_hash_of,
    read_test_articles,
)


def fp(name, **kw):
    kw.setdefault("file_type", "txt")
    kw.setdefault("tier", 2)
    return FileFingerprint(file_id=name, filename=name, ts_added="2026-11-25T00:00:00Z", **kw)


def pool(*fps):
    return {f.file_id: f for f in fps}


# ---------------------------------------------------------------------------
# The same data twice
# ---------------------------------------------------------------------------

def test_the_same_file_under_two_names_stops_the_combine():
    issues = _check_duplicate_contents(pool(
        fp("body_weight.txt", content_hash="sha256:aaaa"),
        fp("body_weight_2.txt", content_hash="sha256:aaaa"),
        fp("organ_weights.txt", content_hash="sha256:bbbb"),
    ))
    assert len(issues) == 1
    one = issues[0]
    assert one.severity == "error"          # it blocks: the data would count twice
    assert one.issue_type == "duplicate_files"
    assert "body_weight.txt and body_weight_2.txt" in one.message
    assert sorted(one.files_involved) == ["body_weight.txt", "body_weight_2.txt"]


def test_files_that_merely_look_alike_are_not_called_the_same():
    """Structural likeness is _check_redundancy's business, and is not proof."""
    assert _check_duplicate_contents(pool(
        fp("male.txt", content_hash="sha256:aaaa", platform="Body Weight"),
        fp("female.txt", content_hash="sha256:bbbb", platform="Body Weight"),
    )) == []


def test_a_file_that_could_not_be_read_is_not_called_a_duplicate():
    assert _check_duplicate_contents(pool(
        fp("a.txt", content_hash=None), fp("b.txt", content_hash=None),
    )) == []


def test_the_hash_is_of_the_contents_not_the_name(tmp_path):
    one, two, other = tmp_path / "a.txt", tmp_path / "b.txt", tmp_path / "c.txt"
    one.write_text("Dose\tBody Weight\n0\t188.1\n")
    two.write_text("Dose\tBody Weight\n0\t188.1\n")
    other.write_text("Dose\tBody Weight\n0\t999.9\n")
    assert content_hash_of(str(one)) == content_hash_of(str(two))
    assert content_hash_of(str(one)) != content_hash_of(str(other))
    assert content_hash_of(str(tmp_path / "gone.txt")) is None


# ---------------------------------------------------------------------------
# Another study's data
# ---------------------------------------------------------------------------

def test_a_project_of_two_test_articles_stops_the_combine():
    issues = _check_test_articles(pool(fp(
        "genomic.bm2", file_type="bm2", tier=3,
        test_articles=["BPAF", "Triclosan"],
        test_article_basis="experiment_names_llm",
        experiment_names=["Liver_BPAF_Male_No0", "Liver_Triclosan_Male_No0"])))
    assert len(issues) == 1 and issues[0].severity == "error"
    assert issues[0].issue_type == "several_test_articles"
    assert "BPAF, Triclosan" in issues[0].message
    # Where the reading came from travels with it.
    assert issues[0].details["basis"] == "experiment_names_llm"


def test_one_test_article_is_this_study_and_raises_nothing():
    assert _check_test_articles(pool(fp(
        "genomic.bm2", file_type="bm2", tier=3, test_articles=["PFHxSAm"],
        test_article_basis="experiment_names_llm"))) == []


def test_names_that_carry_no_test_article_raise_nothing():
    """NIEHS-13's experiments are `rat_4D_HE_No0`: silence is not two chemicals."""
    assert _check_test_articles(pool(fp(
        "genomic.bm2", file_type="bm2", tier=3, test_articles=[],
        test_article_basis="none",
        experiment_names=["rat_4D_HE_No0", "rat_4D_KI_No0"]))) == []


def test_two_spellings_of_one_chemical_are_one_chemical():
    """Reading two names as two compounds would block a sound study."""
    assert _same_article("PFHxSAm", "Perfluorohexane sulfonamide")
    assert _same_article("1,2-dichlorobenzene", "1,2-DCB")
    assert _same_article("BPAF", "Bisphenol AF")
    assert not _same_article("Triclosan", "Bisphenol AF")
    assert not _same_article("1,2-dichlorobenzene", "Triclosan")


def test_what_was_read_says_where_it_came_from(monkeypatch):
    import bmdx_pipe.file_integrator as fi

    said = {"Liver_BPAF_Male_No0": {"test_article": "BPAF"},
            "Liver_Triclosan_Male_No0": {"test_article": "Triclosan"},
            "rat_4D_HE_No0": {"species": "Rattus norvegicus"}}
    monkeypatch.setattr(fi, "_deduce_metadata_from_experiments",
                        lambda names, *a, **k: said.get(names[0], {}))

    assert read_test_articles(["Liver_BPAF_Male_No0", "Liver_Triclosan_Male_No0"]) == (
        ["BPAF", "Triclosan"], "experiment_names_llm")
    # Read, and carrying none: a finding about the names.
    assert read_test_articles(["rat_4D_HE_No0"]) == ([], "none")


def test_a_reading_that_could_not_be_made_says_so(monkeypatch):
    """Not the same as "no test article found": one is a finding, the other is
    a check that did not happen."""
    import bmdx_pipe.file_integrator as fi
    monkeypatch.setattr(fi, "_deduce_metadata_from_experiments", lambda *a, **k: {})
    assert read_test_articles(["Liver_BPAF_Male_No0"]) == ([], "unavailable")
    assert read_test_articles([]) == ([], "unavailable")


# ---------------------------------------------------------------------------
# A name against its contents
# ---------------------------------------------------------------------------

def workbook(platform, endpoints):
    return fp(f"{platform}.xlsx", file_type="xlsx", tier=1,
              platform=platform, endpoint_names=endpoints)


def test_a_table_whose_contents_belong_to_another_assay_stops_the_combine():
    issues = _check_name_against_contents(pool(
        workbook("Hematology", ["Hematocrit", "Hemoglobin", "Platelets"]),
        workbook("Clinical Chemistry", ["Albumin", "ALT", "AST"]),
        fp("hematology_truth_male.txt", platform="Hematology",
           endpoint_names=["Albumin", "ALT", "AST"]),
    ))
    assert len(issues) == 1 and issues[0].severity == "error"
    assert issues[0].issue_type == "name_disagrees_with_contents"
    assert "named for Hematology" in issues[0].message
    assert "matches Clinical Chemistry better" in issues[0].message


def test_a_table_that_agrees_with_its_name_raises_nothing():
    assert _check_name_against_contents(pool(
        workbook("Hematology", ["Hematocrit", "Hemoglobin"]),
        workbook("Clinical Chemistry", ["Albumin", "ALT"]),
        fp("hematology_truth_male.txt", platform="Hematology",
           endpoint_names=["Hematocrit", "Hemoglobin"]),
    )) == []


def test_no_overlap_with_its_own_assay_is_not_evidence():
    """A body-weight workbook's endpoints are study-day columns while its
    table's are not. Requiring overlap would misfire on 24 real files, so
    only a strictly better match elsewhere counts."""
    assert _check_name_against_contents(pool(
        workbook("Body Weight", ["SD0", "SD5"]),
        workbook("Hematology", ["Hematocrit"]),
        fp("body_weight_truth_male.txt", platform="Body Weight",
           endpoint_names=["Body Weight", "Terminal Body Weight"]),
    )) == []


def test_one_assay_alone_can_be_mistaken_for_nothing():
    assert _check_name_against_contents(pool(
        workbook("Hematology", ["Hematocrit"]),
        fp("hematology_truth_male.txt", platform="Hematology",
           endpoint_names=["Albumin"]),
    )) == []


def test_a_workbook_is_not_checked_against_itself():
    """The workbooks are the authority; only derived tables are read back."""
    assert _check_name_against_contents(pool(
        workbook("Hematology", ["Albumin", "ALT"]),
        workbook("Clinical Chemistry", ["Albumin", "ALT", "AST"]),
    )) == []


# ---------------------------------------------------------------------------
# The way out: what removing a file would take with it
# ---------------------------------------------------------------------------

def test_the_dry_run_names_everything_that_rides_on_a_file(sessions_dir):
    from pipeline.pool_state import would_remove

    d = sessions_dir / "DTXSID9000055" / "files"
    d.mkdir(parents=True)
    (d / "body_weight.txt").write_text("Dose\tBody Weight\n0\t188.1\n")
    (d / "body_weight.sidecar.json").write_text("{}")
    (d / "body_weight.units.json").write_text('{"Body Weight": "grams"}')
    (d / "organ_weights.txt").write_text("other")

    said = would_remove("DTXSID9000055", "body_weight.txt")
    assert said["file"] == "body_weight.txt"
    assert {c["name"] for c in said["companions"]} == {
        "body_weight.sidecar.json", "body_weight.units.json"}
    assert any("units of its measurements" in c["say"] for c in said["companions"])
    assert said["kept"] is True
    # A dry run changes nothing.
    assert (d / "body_weight.txt").exists() and (d / "body_weight.units.json").exists()


def test_the_dry_run_refuses_what_the_act_would_refuse(sessions_dir):
    from pipeline.pool_state import PoolFileError, would_remove

    d = sessions_dir / "DTXSID9000055" / "files"
    d.mkdir(parents=True)
    (d / "body_weight.sidecar.json").write_text("{}")

    with pytest.raises(PoolFileError):           # a sidecar belongs to its file
        would_remove("DTXSID9000055", "body_weight.sidecar.json")
    with pytest.raises(PoolFileError):           # no such file
        would_remove("DTXSID9000055", "gone.txt")
    with pytest.raises(PoolFileError):           # not a bare name
        would_remove("DTXSID9000055", "../escape.txt")


def test_the_dry_run_and_the_act_agree(sessions_dir):
    """They read the same listing, so they cannot promise different things."""
    from pipeline.pool_state import remove_pool_file, would_remove

    d = sessions_dir / "DTXSID9000055" / "files"
    d.mkdir(parents=True)
    (d / "body_weight.txt").write_text("Dose\tBody Weight\n0\t188.1\n")
    (d / "body_weight.units.json").write_text('{"Body Weight": "grams"}')

    promised = {c["name"] for c in would_remove("DTXSID9000055", "body_weight.txt")["companions"]}
    promised.add("body_weight.txt")
    happened = set(remove_pool_file("DTXSID9000055", "body_weight.txt")["removed"])
    assert happened == promised
