"""One reader for an NTP study workbook, whatever layout CEBS published it in.

Every column is found by name.  The male-only Tgx studies (RR-8, NIEHS-06) have
no Sex or Selection column; the 2025 workbooks (NIEHS-12, 13) say "Study Number"
and have no Sex column.  The sex then comes from the Key sheet's title.
"""

import openpyxl

from bmdx_pipe.file_integrator import fingerprint_xlsx
from bmdx_pipe.pool_integrator import extract_xlsx_value_map
from bmdx_pipe.study_workbook import read_study_workbook, title_facts

PFAS_TITLE = ("Evaluation of Transcriptomic Changes and Toxicological Potential of Selected "
              "Per/Polyfluorinated Alkyl Substances (PFAS) in Sprague Dawley Rats "
              "(Hsd:Sprague Dawley® SD®) Treated via Oral Gavage (T05730) PFHxSAm")
DTT_TITLE = ("5-Day Whole Body Inhalation Toxicity Study of 1,4-Dichlorobenzene (1,4-DCB; "
             "DTTID 108-020-005-000-6; CAS 106-46-7) in Female B6D2F1/Crl Mice (A-201-17) (Female)")
TGX_TITLE = "5-Day Tgx Study for Triphenyl Phosphate (Male)"


def _workbook(path, title, study, key, header, rows):
    wb = openpyxl.Workbook()
    ks = wb.active
    ks.title = "Key to Column Labels"
    meta = [title, "TOX", study, "12/08/2020"]
    lines = [("Column Label", "Explanation of Column Label")] + key
    lines += [()] * (4 - len(lines))
    for i, line in enumerate(lines):
        ks.append(list(line) + [None] * (3 - len(line)) + ([meta[i]] if i < 4 else []))
    ds = wb.create_sheet("Data")
    ds.append(header)
    for r in rows:
        ds.append(r)
    wb.save(path)
    return str(path)


def _pfas(tmp_path):
    return _workbook(
        tmp_path / "C20022-01_Individual_Animal_Body_Weight_Data.xlsx", PFAS_TITLE, "C20022-01",
        [("Concentration", "Dose in mg/kg"), ("Body Weight", "Body weight measured in grams")],
        ["NTP Study Number", "Concentration", "Animal ID", "Sex", "Selection", "Body Weight",
         "Observation Day", "Terminal Flag"],
        [["C20022-01", "0", "101", "Male", "Core Animals", "285.1", "SD0", ""],
         ["C20022-01", "0", "101", "Male", "Core Animals", "300.3", "SD5", "Yes"],
         ["C20022-01", "4", "111", "Female", "Biosampling Animals", "215.9", "SD0", ""]])


def _dtt(tmp_path):
    return _workbook(
        tmp_path / "108020005_Individual_Animal_Organ_Weight_Data_Mice.xlsx", DTT_TITLE,
        "108020005",
        [("Concentration", "Exposure in ppm"), ("Liver", "Liver weight in grams")],
        ["Study Number", "Concentration", "Animal ID", "Selection", "Removal Day", "Liver"],
        [["108020005", "0", "1", "Core Animals", "SD5", ".95"],
         ["108020005", "300", "2", "Core Animals", "SD5", "NA"]])


def _tgx(tmp_path):
    return _workbook(
        tmp_path / "C11042_Individual_Animal_Hormone_Data.xlsx", TGX_TITLE, "C11042",
        [("Concentration", "Dose in mMol/kg"), ("Total Thyroxine", "Total thyroxine in ng/dL")],
        ["NTP Study Number", "Concentration", "Animal ID", "Removal Day ", "Total Thyroxine", "", ""],
        [["C11042", "0", "77", "SD4", "5.16", None, None]])


def test_standard_layout(tmp_path):
    wb = read_study_workbook(_pfas(tmp_path))
    assert wb.is_study_file and wb.study_number == "C20022-01" and wb.study_type == "TOX"
    assert wb.date == "2020-12-08T00:00:00" and wb.dose_unit == "mg/kg"
    assert wb.endpoints == ["Body Weight"] and wb.units == {"Body Weight": "grams"}
    assert wb.sex_filled is None and wb.notes == []
    obs = list(wb.observations())
    assert [(o.animal_id, o.dose, o.sex, o.day, o.terminal) for o in obs] == [
        ("101", 0.0, "Male", "SD0", False), ("101", 0.0, "Male", "SD5", True),
        ("111", 4.0, "Female", "SD0", False)]


def test_2025_layout_sex_from_title(tmp_path):
    wb = read_study_workbook(_dtt(tmp_path))
    assert wb.header[:4] == ["NTP Study Number", "Concentration", "Animal ID", "Sex"]
    assert wb.sex_filled == "Female" and wb.study_number == "108020005"
    assert wb.dose_unit == "ppm"
    assert {o.sex for o in wb.observations()} == {"Female"}
    assert [o.values for o in wb.observations()] == [{"Liver": ".95"}, {"Liver": "NA"}]


def test_tgx_layout_trailing_columns_and_spaces(tmp_path):
    wb = read_study_workbook(_tgx(tmp_path))
    assert wb.header == ["NTP Study Number", "Concentration", "Animal ID", "Sex", "Removal Day",
                         "Total Thyroxine"]
    assert wb.sex_filled == "Male" and wb.dose_unit == "mMol/kg"
    (ob,) = wb.observations()
    assert (ob.sex, ob.day, ob.values) == ("Male", "SD4", {"Total Thyroxine": "5.16"})


def test_title_naming_both_sexes_fills_nothing(tmp_path):
    p = _workbook(tmp_path / "w.xlsx", "Study in Male and Female Rats", "S1",
                  [("Concentration", "Dose in mg/kg")],
                  ["NTP Study Number", "Concentration", "Animal ID", "Body Weight"],
                  [["S1", "0", "1", "200"]])
    wb = read_study_workbook(p)
    assert wb.sex_filled is None and wb.col("Sex") is None
    assert "does not name exactly one sex" in wb.notes[0]


def test_title_facts():
    assert title_facts(PFAS_TITLE) == {"species": "rat", "strain": "Sprague-Dawley",
                                       "articleRoute": "oral", "administrationMeans": "gavage"}
    assert title_facts(DTT_TITLE) == {"species": "mouse", "strain": "B6D2F1",
                                      "articleRoute": "inhaled", "administrationMeans": "whole-body",
                                      "studyDuration": "5d", "sex": "female"}
    assert title_facts(TGX_TITLE) == {"studyDuration": "5d", "sex": "male"}
    assert title_facts("") == {}


def test_fingerprint_reads_every_layout(tmp_path):
    fp = fingerprint_xlsx("x", "C20022-01_Individual_Animal_Body_Weight_Data.xlsx",
                          _pfas(tmp_path), "t")
    assert fp.sexes == ["Female", "Male"] and fp.endpoint_names == ["Body Weight"]
    assert fp.core_animals_by_dose_sex == {0.0: {"Male": ["101"]}}

    fp = fingerprint_xlsx("x", "108020005_Individual_Animal_Organ_Weight_Data_Mice.xlsx",
                          _dtt(tmp_path), "t")
    assert fp.sexes == ["Female"] and fp.study_number == "108020005" and fp.dose_unit == "ppm"
    assert fp.core_animals_by_dose_sex == {0.0: {"Female": ["1"]}, 300.0: {"Female": ["2"]}}

    # No Selection column: every animal is core.
    fp = fingerprint_xlsx("x", "C11042_Individual_Animal_Hormone_Data.xlsx", _tgx(tmp_path), "t")
    assert fp.sexes == ["Male"] and fp.core_animals_by_dose_sex == {0.0: {"Male": ["77"]}}
    assert fp.endpoint_names == ["Total Thyroxine"]


def test_value_map_uses_the_filled_sex(tmp_path):
    vm = extract_xlsx_value_map(_dtt(tmp_path))
    assert set(vm) == {("Female", "1", "Liver", "SD5"), ("Female", "2", "Liver", "SD5")}
