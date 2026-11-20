"""ui_api.dataset, the reads: a study's files and the dataset combined from
them, and a results table followed back to its files (the demo path's
"Combined data" page).  Every link shown is a record; a missing record is
where the chain stops."""

import json

import pytest

ID = "DTXSID0000555"
WORKBOOK = "0555_Individual_Animal_Clinical_Chemistry_Data.xlsx"
TABLE = "clin_chem_truth_male.txt"
BM2 = "0555_Genomic.bm2"


def _write(folder, name, content="{}"):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))


def _fp(name, file_id, file_type, platform, data_type, **more):
    return {"file_id": file_id, "filename": name, "file_type": file_type,
            "platform": platform, "data_type": data_type, "sexes": ["Male"],
            "animal_ids": ["1", "2", "3"], "dose_groups": [0.0, 10.0], "dose_unit": "ppm",
            "derived_from": None, **more}


@pytest.fixture
def study(sessions_dir):
    """A study whose files passed the check: a workbook, the table converted
    from it (with its sidecar), an observations table with no sidecar, and a
    BMDExpress project."""
    session = sessions_dir / ID
    for name in (WORKBOOK, TABLE, "obs.csv", BM2):
        _write(session, f"files/{name}", "data")
    _write(session, f"files/{TABLE.removesuffix('.txt')}.sidecar.json", {"source": WORKBOOK})
    _write(session, "_fingerprints.json", {
        WORKBOOK: _fp(WORKBOOK, "id-xlsx", "xlsx", "Clinical Chemistry", "tox_study"),
        TABLE: _fp(TABLE, "id-txt", "txt", "Clinical Chemistry", "tox_study"),
        "obs.csv": _fp("obs.csv", "id-obs", "csv", "Clinical", "tox_study"),
        BM2: _fp(BM2, "id-bm2", "bm2", None, "gene_expression", sexes=[]),
    })
    _write(session, "validation_report.json", {"issues": [], "coverage_matrix": {
        "Clinical Chemistry|tox_study": {"xlsx": "id-xlsx", "txt_csv": ["id-txt"], "bm2": None},
        "Clinical|tox_study": {"xlsx": None, "txt_csv": ["id-obs"], "bm2": None},
        "gene_expression": {"xlsx": None, "txt_csv": [], "bm2": "id-bm2"},
    }})
    _write(session, "identity.json", {"name": "Test Compound", "dtxsid": ID})
    return session


def _description(platform, sex, data_type="tox_study"):
    return {"platform": platform, "provider": "Apical", "sex": sex, "dataType": data_type,
            "testArticle": {"name": "Test Compound", "casrn": "123-45-6", "dsstox": ID}}


INTEGRATED = {
    "name": "integrated",
    "doseResponseExperiments": [
        {"name": "clin_chem_truth_male", "@ref": 7,
         "treatments": [{"name": "1", "dose": 0.0}, {"name": "2", "dose": 10.0}],
         "probeResponses": [{"probe": {"id": "Albumin"}, "responses": [1.0, 2.0]},
                            {"probe": {"id": "Globulin"}, "responses": [1.0, 2.0]}],
         "experimentDescription": _description("Clinical Chemistry", "male")},
        {"name": "liver_male", "@ref": 9,
         "treatments": [{"name": "s1", "dose": 0.0}],
         "probeResponses": [{"probe": {"id": "GENE1_1"}, "responses": [1.0]}],
         "experimentDescription": _description("S1500+", "male", "gene_expression")},
    ],
    "bMDResult": [{"name": "liver_male_BMD", "doseResponseExperiment": 9}],
    "_meta": {"dtxsid": ID, "integrated_at": "2026-11-18T00:00:00+00:00", "source_files": {
        "Clinical Chemistry|tox_study": {"file_id": "id-txt", "filename": TABLE,
                                         "tier": "txt_csv", "file_count": 1},
        "gene_expression": {"file_id": "id-bm2", "filename": BM2, "tier": "bm2",
                            "file_count": 1},
    }},
}

SECTION = {"platform": "Clinical Chemistry", "title": "Clinical Chemistry",
           "caption": "Summary of Clinical Chemistry Data", "approved": False,
           "tables_json": {"Male": [
               {"label": "n", "is_n_row": True, "bmd": "NA", "bmdl": "NA"},
               {"label": "Albumin", "bmd": "12.5", "bmdl": "6.1"},
               {"label": "A/G Ratio", "bmd": "—", "bmdl": "—"}]}}

RECORD = {"engine": "toxicr_model_average", "settings": [{
    "source": "inferred", "bmr": {"type": "SD", "factor": 1.0}, "constant_variance": True,
    "models": ["Hill", "Power"], "platforms": {"Clinical Chemistry": ["Male"]}}]}


@pytest.fixture
def combined(study):
    _write(study, "integrated.json", INTEGRATED)
    _write(study, "animal_report.json", {
        "study_number": "0555", "total_animals": 3, "core_count": 3, "biosampling_count": 0,
        "dose_groups": [0.0, 10.0], "dose_design": {"0.0": {"Male": 2}, "10.0": {"Male": 1}},
        "domain_coverage": {"Clinical Chemistry": {"xlsx": 3, "txt_csv": 3, "bm2": 0}},
        "consistency_issues": [], "animals": {}})
    return study


@pytest.fixture
def processed(combined, monkeypatch):
    _write(combined, "bm2_clinical-chemistry.json", SECTION)
    _write(combined, "bm2_clinical-observations.json", {
        "platform": "Clinical Observations", "title": "Clinical Observations",
        "tables_json": {"Male": [{"label": "Lethargic", "n": {"0": 2}}]}})
    _write(combined, "_cache_methods_abc.json", {"context": {"apical_bmd_method": RECORD}})
    # The report's order is the read model's (the document tree's); the tree
    # is not what these tests are about.
    import ui_api.read_model as read_model
    monkeypatch.setattr(read_model, "study_state", lambda dtxsid: {"sections": [
        {"key": "methods", "has_file": False},
        {"key": "bm2_clinical-chemistry", "has_file": True},
        {"key": "bm2_clinical-observations", "has_file": True},
        {"key": "bm2_hematology", "has_file": False}]})
    return combined


# ---------------------------------------------------------------------------
# Before the files are combined
# ---------------------------------------------------------------------------

def test_before_combining_the_files_and_each_assays_chain_are_shown(study):
    from ui_api.dataset import study_dataset

    out = study_dataset(ID)
    assert (out["files_checked"], out["integrated"]) == (True, False)
    assert out["experiments"] is None and out["accounting"] is None
    files = {f["filename"]: f for f in out["files"]}
    assert files[WORKBOOK] | {"converted_from": None} == {
        "filename": WORKBOOK, "file_type": "xlsx", "assay": "Clinical Chemistry",
        "data_type": "tox_study", "sexes": ["Male"], "animals": 3,
        "dose_groups": [0.0, 10.0], "dose_unit": "ppm", "converted_from": None}
    # The table's sidecar names the workbook it was converted from.
    assert files[TABLE]["converted_from"] == {"filename": WORKBOOK, "recorded_in": "sidecar"}
    assays = {a["key"]: a for a in out["assays"]}
    assert assays["Clinical Chemistry|tox_study"] == {
        "key": "Clinical Chemistry|tox_study", "assay": "Clinical Chemistry",
        "data_type": "tox_study", "workbook": WORKBOOK, "bm2": None,
        "tables": [{"filename": TABLE,
                    "converted_from": {"filename": WORKBOOK, "recorded_in": "sidecar"}}]}
    assert assays["gene_expression"]["bm2"] == BM2
    assert "taken_from" not in assays["gene_expression"]      # nothing combined yet


def test_a_conversion_nothing_recorded_is_not_guessed(study):
    from ui_api.dataset import study_dataset

    obs = next(a for a in study_dataset(ID)["assays"] if a["key"] == "Clinical|tox_study")
    assert obs["workbook"] is None
    assert obs["tables"] == [{"filename": "obs.csv", "converted_from": None}]


def test_the_file_checks_own_note_names_the_workbook_when_there_is_no_sidecar(study):
    from ui_api.dataset import study_dataset

    fps = json.loads((study / "_fingerprints.json").read_text())
    fps["obs.csv"]["derived_from"] = "Observations.xlsx"
    _write(study, "_fingerprints.json", fps)
    obs = next(f for f in study_dataset(ID)["files"] if f["filename"] == "obs.csv")
    assert obs["converted_from"] == {"filename": "Observations.xlsx", "recorded_in": "file_check"}


def test_the_values_the_package_left_out_are_shown_as_the_tables_mark_them(study):
    # ADR-0037: the converted table's sidecar keeps the value under a mark.
    from ui_api.dataset import study_dataset

    assert study_dataset(ID)["left_out"] == []
    _write(study, f"files/{TABLE.removesuffix('.txt')}.sidecar.json", {
        "source": WORKBOOK, "platform": "Clinical Chemistry", "sex": "Male",
        "animals": {"202": {"dose": 10.0, "selection": "Core Animals", "observations": [
            {"day": "SD5", "endpoint": "Albumin", "value": "4.1", "terminal": True},
            {"day": "SD5", "endpoint": "Bile salts/acids", "value": None, "terminal": True,
             "excluded": {"value": "0", "reason": "measurement problem", "note": "",
                          "source": "Excluded_Values.csv"}}]}}})
    assert study_dataset(ID)["left_out"] == [{
        "animal_id": "202", "assay": "Clinical Chemistry", "sex": "Male", "dose": 10.0,
        "endpoint": "Bile salts/acids", "day": "SD5", "value": "0",
        "reason": "measurement problem",
        "reason_say": "the laboratory indicated the measurement as inadequate",
        "note": None, "stated_in": "Excluded_Values.csv"}]


def test_reading_changes_nothing(study):
    from ui_api.dataset import result_tables, study_dataset

    before = sorted(p.relative_to(study).as_posix() for p in study.rglob("*"))
    study_dataset(ID)
    result_tables(ID)
    assert sorted(p.relative_to(study).as_posix() for p in study.rglob("*")) == before


# ---------------------------------------------------------------------------
# After
# ---------------------------------------------------------------------------

def test_after_combining_the_experiments_say_which_file_each_came_from(combined):
    from ui_api.dataset import study_dataset

    out = study_dataset(ID)
    assert out["integrated"] and out["integrated_at"] == "2026-11-18T00:00:00+00:00"
    chem, liver = out["experiments"]
    assert chem == {"name": "clin_chem_truth_male", "assay": "Clinical Chemistry",
                    "data_type": "tox_study", "sex": "male", "organ": None, "endpoints": 2,
                    "animals": 2, "taken_from": {"filename": TABLE, "kind": "txt_csv"},
                    "own_benchmark_doses": False}
    assert liver["taken_from"] == {"filename": BM2, "kind": "bm2"}
    # The study's own benchmark dose analysis is in the dataset for the liver only.
    assert liver["own_benchmark_doses"] is True
    assert out["own_bmd_analysis"] == {"analyses": 1, "experiments": ["liver_male"]}
    assays = {a["key"]: a for a in out["assays"]}
    assert assays["Clinical Chemistry|tox_study"]["taken_from"] == {
        "filename": TABLE, "kind": "txt_csv"}
    assert assays["Clinical|tox_study"]["taken_from"] is None     # the dataset names no file
    assert out["accounting"] == {
        "study_number": "0555", "total_animals": 3, "core_count": 3, "biosampling_count": 0,
        "dose_groups": [0.0, 10.0], "dose_design": {"0.0": {"Male": 2}, "10.0": {"Male": 1}},
        "assay_coverage": {"Clinical Chemistry": {"xlsx": 3, "txt_csv": 3, "bm2": 0}},
        "problems": []}


def test_a_new_integration_is_read_afresh(combined):
    import os

    from ui_api.dataset import study_dataset

    assert len(study_dataset(ID)["experiments"]) == 2
    again = {**INTEGRATED, "doseResponseExperiments": INTEGRATED["doseResponseExperiments"][:1],
             "bMDResult": []}
    _write(combined, "integrated.json", again)
    os.utime(combined / "integrated.json", ns=(1, 1))
    from pipeline.pool_globals import forget_session
    forget_session(ID, combined / "files")      # what a server's integration replaces
    out = study_dataset(ID)
    assert [e["name"] for e in out["experiments"]] == ["clin_chem_truth_male"]
    assert out["own_bmd_analysis"] == {"analyses": 0, "experiments": []}


def test_the_tables_are_listed_in_the_reports_order(processed):
    from ui_api.dataset import result_tables

    assert result_tables(ID) == {"id": ID, "tables": [
        {"key": "bm2_clinical-chemistry", "title": "Clinical Chemistry",
         "assay": "Clinical Chemistry", "caption": "Summary of Clinical Chemistry Data",
         "sexes": ["Male"], "rows": 3, "has_benchmark_doses": True},
        {"key": "bm2_clinical-observations", "title": "Clinical Observations",
         "assay": "Clinical Observations", "caption": None, "sexes": ["Male"], "rows": 1,
         "has_benchmark_doses": False}]}


def test_a_table_is_followed_back_to_its_workbook(processed):
    from ui_api.dataset import table_sources

    out = table_sources(ID, "bm2_clinical-chemistry")
    assert (out["assay"], out["has_benchmark_doses"], out["benchmark_dose_recorded"]) == (
        "Clinical Chemistry", True, True)
    [male] = out["sexes"]
    assert male["experiments"] == [{"name": "clin_chem_truth_male", "organ": None,
                                    "endpoints": 2, "animals": 2,
                                    "endpoint_names": ["Albumin", "Globulin"]}]
    assert male["files"] == [{"filename": TABLE, "kind": "txt_csv", "file_type": "txt",
                              "converted_from": {"filename": WORKBOOK,
                                                 "recorded_in": "sidecar"}}]
    assert male["stops"] is None
    # Fit here (no analysis of this assay among the study's files), per the record.
    assert male["benchmark_dose"] == {"source": "inferred", "bmr": {"type": "SD", "factor": 1.0},
                                      "constant_variance": True, "models": ["Hill", "Power"]}
    assert male["counted_from_files"] is False
    count, albumin, ratio = male["rows"]
    assert (count["count_row"], count["endpoint_in_dataset"], count["built_from"]) == (
        True, None, None)
    assert albumin == {"label": "Albumin", "heading": False, "count_row": False,
                       "built_from": {"endpoints": ["Albumin"], "how": None},
                       "endpoint_in_dataset": True, "bmd": "12.5", "bmdl": "6.1"}
    # A row the builder derives has no endpoint of its own name: it is
    # followed to the endpoints it is computed from (tables.row_sources).
    assert ratio["built_from"] == {"endpoints": ["Albumin", "Globulin"],
                                   "how": "albumin divided by globulin, per animal"}
    assert ratio["endpoint_in_dataset"] is True


def test_a_row_no_rule_names_an_endpoint_for_is_not_guessed(processed):
    from ui_api.dataset import table_sources

    section = json.loads(json.dumps(SECTION))
    section["tables_json"]["Male"].append({"label": "Anion gap", "bmd": "—", "bmdl": "—"})
    _write(processed, "bm2_clinical-chemistry.json", section)
    row = table_sources(ID, "bm2_clinical-chemistry")["sexes"][0]["rows"][-1]
    assert (row["built_from"], row["endpoint_in_dataset"]) == (None, False)


def test_a_table_counted_from_files_is_followed_to_those_files(processed):
    """Clinical Observations: the dataset holds no experiment for it and
    records the files it is counted from (_meta.clinical_obs_files)."""
    from pipeline.pool_globals import forget_session
    from ui_api.dataset import table_sources

    data = json.loads(json.dumps(INTEGRATED))
    data["_meta"]["clinical_obs_files"] = [str(processed / "files" / "obs.csv")]
    _write(processed, "integrated.json", data)
    forget_session(ID, processed / "files")

    [obs] = table_sources(ID, "bm2_clinical-observations")["sexes"]
    assert (obs["experiments"], obs["counted_from_files"]) == ([], True)
    # The file is named; nothing records the workbook it was converted from.
    assert obs["files"] == [{"filename": "obs.csv", "kind": "txt_csv", "file_type": "csv",
                             "converted_from": None}]
    assert obs["stops"] == "workbook"
    [row] = obs["rows"]
    assert (row["built_from"], row["endpoint_in_dataset"]) == (None, None)

    # With the record of the conversion, the chain is whole.
    _write(processed, "files/obs.sidecar.json", {"source": WORKBOOK})
    [obs] = table_sources(ID, "bm2_clinical-observations")["sexes"]
    assert obs["files"][0]["converted_from"] == {"filename": WORKBOOK, "recorded_in": "sidecar"}
    assert obs["stops"] is None


def test_the_chain_stops_where_the_record_stops(processed):
    from ui_api.dataset import table_sources

    # No experiment of this assay in the dataset, and no file recorded for it.
    [obs] = table_sources(ID, "bm2_clinical-observations")["sexes"]
    assert (obs["experiments"], obs["files"], obs["stops"]) == ([], [], "experiment")
    assert obs["counted_from_files"] is False
    assert obs["benchmark_dose"] is None            # the table prints no benchmark dose

    # The dataset names no file for the assay.
    data = json.loads(json.dumps(INTEGRATED))
    data["_meta"]["source_files"].pop("Clinical Chemistry|tox_study")
    _write(processed, "integrated.json", data)
    from pipeline.pool_globals import forget_session
    forget_session(ID, processed / "files")
    [male] = table_sources(ID, "bm2_clinical-chemistry")["sexes"]
    assert (male["files"], male["stops"]) == ([], "file")

    # The file is named, and nothing records what it was converted from.
    _write(processed, "integrated.json", INTEGRATED)
    forget_session(ID, processed / "files")
    (processed / "files" / "clin_chem_truth_male.sidecar.json").unlink()
    [male] = table_sources(ID, "bm2_clinical-chemistry")["sexes"]
    assert male["files"][0]["converted_from"] is None and male["stops"] == "workbook"


def test_a_benchmark_dose_method_nothing_recorded_is_not_stated(processed):
    from ui_api.dataset import table_sources

    (processed / "_cache_methods_abc.json").unlink()
    out = table_sources(ID, "bm2_clinical-chemistry")
    assert out["benchmark_dose_recorded"] is False
    assert out["sexes"][0]["benchmark_dose"] is None


def test_an_unknown_table_and_a_report_are_refused(processed, sessions_dir):
    from ui_api.dataset import study_dataset, table_sources
    from ui_api.refusals import explain
    from ui_api.studies import StudyRefusal

    with pytest.raises(StudyRefusal) as e:
        table_sources(ID, "bm2_hematology")
    body = explain(e.value)["error"]
    assert (body["code"], body["status"], body["fix"]) == ("table_not_found", 404, "P1")
    with pytest.raises(StudyRefusal) as e:
        table_sources(ID, "identity")            # a file of the study, not a results table
    assert e.value.code == "table_not_found"

    _write(sessions_dir / "DTXSID0000556", "studies.json", {"rat": ID})
    with pytest.raises(StudyRefusal) as e:
        study_dataset("DTXSID0000556")
    assert e.value.code == "report_has_no_data" and e.value.details["members"] == [ID]
    with pytest.raises(StudyRefusal) as e:
        study_dataset("DTXSID0000999")
    assert e.value.code == "study_not_found"


def test_the_routes_answer_and_refuse_in_the_envelope(processed, client):
    r = client.get(f"/api/v2/studies/{ID}/dataset")
    assert r.status_code == 200 and r.json()["integrated"] is True
    r = client.get(f"/api/v2/studies/{ID}/tables")
    assert [t["key"] for t in r.json()["tables"]] == ["bm2_clinical-chemistry",
                                                      "bm2_clinical-observations"]
    r = client.get(f"/api/v2/studies/{ID}/tables/bm2_clinical-chemistry/sources")
    assert r.status_code == 200 and r.json()["sexes"][0]["stops"] is None
    r = client.get(f"/api/v2/studies/{ID}/tables/bm2_nope/sources")
    assert r.status_code == 404 and r.json()["error"]["code"] == "table_not_found"
    r = client.get("/api/v2/studies/not-a-study/dataset")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_study_id"


def test_the_new_refusals_address_nobody():
    import re

    from ui_api.refusals import STUDY_REFUSALS
    assert not re.search(r"\b(you|your|yours)\b", STUDY_REFUSALS["table_not_found"].say, re.I)
