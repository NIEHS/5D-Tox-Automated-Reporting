"""The study the workbooks describe, and every file checked against it (ADR-0032)."""

import openpyxl

from bmdx_pipe.file_integrator import FileFingerprint, validate_pool
from bmdx_pipe.study_structure import (
    StudyStructure, build_study_structure, check_against_structure,
)

TITLE = "Study of X in Sprague Dawley Rats Treated via Oral Gavage"
BW_HDR = ["NTP Study Number", "Concentration", "Animal ID", "Sex", "Selection",
          "Body Weight", "Observation Day"]


def _workbook(path, rows, header=BW_HDR, study="S1", title=TITLE, unit="mg/kg"):
    wb = openpyxl.Workbook()
    ks = wb.active
    ks.title = "Key to Column Labels"
    ks.append(["Column Label", "Explanation of Column Label", None, title])
    ks.append(["Concentration", f"Dose in {unit}", None, "TOX"])
    ks.append(["Body Weight", "Body weight in grams", None, study])
    ks.append([None, None, None, "12/08/2020"])
    ds = wb.create_sheet("Data")
    ds.append(header)
    for r in rows:
        ds.append(r)
    wb.save(path)
    return str(path)


ROWS = [["S1", "0", "1", "Male", "Core Animals", "300", "SD0"],
        ["S1", "4", "2", "Male", "Core Animals", "310", "SD0"],
        ["S1", "0", "11", "Female", "Core Animals", "200", "SD0"]]


def test_structure_from_workbooks(tmp_path):
    p = _workbook(tmp_path / "a.xlsx", ROWS)
    st = build_study_structure({p: "Body Weight"})
    assert st.study_number == "S1" and st.dose_unit == "mg/kg"
    assert st.design == {"species": "rat", "strain": "Sprague-Dawley",
                         "articleRoute": "oral", "administrationMeans": "gavage"}
    assert st.sexes == ["Female", "Male"] and st.dose_groups == [0.0, 4.0]
    assert st.animals["2"] == {"sex": "Male", "dose": 4.0, "selection": "Core Animals"}
    assert st.platforms["Body Weight"]["days"] == ["SD0"] and not st.conflicts
    assert StudyStructure.from_dict(st.to_dict()) == st


def test_workbooks_that_disagree_are_conflicts(tmp_path):
    a = _workbook(tmp_path / "a.xlsx", ROWS)
    b = _workbook(tmp_path / "b.xlsx", [["S2", "4", "1", "Female", "Core Animals", "1", "SD5"]],
                  study="S2", unit="ppm")
    st = build_study_structure({a: "Body Weight", b: "Organ Weight"})
    kinds = {c["kind"] for c in st.conflicts}
    assert kinds == {"study_number", "dose_unit", "animal_sex", "animal_dose"}
    assert st.study_number is None


def _fp(name, **kw):
    return FileFingerprint(file_id=name, filename=name, file_type="txt", tier=2,
                           ts_added="t", platform="Body Weight", data_type="tox_study", **kw)


def test_every_file_is_checked_against_the_study(tmp_path):
    st = build_study_structure({_workbook(tmp_path / "a.xlsx", ROWS): "Body Weight"})
    fps = {
        "ok": _fp("ok", sexes=["Male"], dose_groups=[0.0, 4.0], animal_ids=["1", "2"],
                  animal_doses={"1": 0.0, "2": 4.0}, endpoint_names=["SD0"]),
        "bad": _fp("bad", sexes=["Male"], dose_groups=[0.0, 12.0], animal_ids=["1", "2", "9", "11"],
                   animal_doses={"1": 0.0, "2": 12.0, "9": 0.0, "11": 0.0},
                   endpoint_names=["SD0", "Body Wieght"]),
    }
    issues = {(i.issue_type, i.files_involved[0]) for i in check_against_structure(fps, st)}
    assert issues == {("animal_not_in_study", "bad"), ("animal_dose_mismatch", "bad"),
                      ("animal_sex_mismatch", "bad"), ("dose_not_in_study", "bad"),
                      ("endpoint_not_in_study", "bad")}
    msg = next(i.message for i in check_against_structure(fps, st)
               if i.issue_type == "endpoint_not_in_study")
    assert "'Body Wieght' (the workbook has 'Body Weight')" in msg


def test_missing_animals_are_not_a_contradiction(tmp_path):
    st = build_study_structure({_workbook(tmp_path / "a.xlsx", ROWS): "Body Weight"})
    fps = {"few": _fp("few", sexes=["Male"], dose_groups=[0.0], animal_ids=["1"],
                      animal_doses={"1": 0.0}, endpoint_names=["SD0", "Body Weight Gain"])}
    assert check_against_structure(fps, st) == []


def test_validate_pool_uses_the_structure(tmp_path):
    st = build_study_structure({_workbook(tmp_path / "a.xlsx", ROWS): "Body Weight"})
    fps = {"x": _fp("x", sexes=["Male"], dose_groups=[0.0], animal_ids=["1", "7"],
                    animal_doses={"1": 0.0, "7": 0.0})}
    report = validate_pool("D", fps, st)
    assert {i["issue_type"] for i in report.issues if i["severity"] == "error"} == {
        "animal_not_in_study"}
    assert {i["issue_type"] for i in validate_pool("D", fps).issues
            if i["severity"] == "error"} == set()


def test_workbooks_own_pivot_stays_tox_study(tmp_path):
    # A group that died before its samples were taken (NIEHS-05's high dose:
    # every value NA) is absent from the pivot, which holds measured animals.
    # That is the workbook's own projection, not lost data.
    from bmdx_pipe.file_integrator import fingerprint_file
    from bmdx_pipe.pool_integrator import study_workbook_to_pool_files

    hdr = ["NTP Study Number", "Concentration", "Animal ID", "Sex", "Selection",
           "Albumin", "Observation Day"]
    rows = [["S1", d, aid, "Male", "Core Animals", v, day]
            for d, aid, v, day in [("0", "1", "3.3", "SD4"), ("0", "2", "3.4", "SD4"),
                                   ("4", "3", "3.1", "SD4"), ("4", "4", "3.2", "SD4"),
                                   ("8", "5", "NA", "SD2"), ("8", "6", "NA", "SD2")]]
    wb = _workbook(tmp_path / "S1_Individual_Animal_Clinical_Chemistry_Data.xlsx", rows, hdr)
    out = tmp_path / "files"
    out.mkdir()
    fps = {"wb": fingerprint_file("wb", "S1_Individual_Animal_Clinical_Chemistry_Data.xlsx", wb, "xlsx", "t")}
    for path in study_workbook_to_pool_files(wb, str(out), "Clinical Chemistry"):
        name = path.rsplit("/", 1)[-1]
        fps[name] = fingerprint_file(name, name, path, "txt", "t")
    pivot = fps["clin_chem_truth_male.txt"]
    assert pivot.derived_from == "S1_Individual_Animal_Clinical_Chemistry_Data.xlsx"
    assert pivot.dose_groups == [0.0, 4.0]

    report = validate_pool("DTXSID", fps, build_study_structure({wb: "Clinical Chemistry"}))
    assert pivot.data_type == "tox_study"
    assert not [i for i in report.issues if i["severity"] == "error"], report.issues
