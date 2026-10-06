"""Endpoint units come from the workbook's Key sheet and travel in the sidecar.

The Data-sheet headers (and so the truth CSVs) carry no units; the Key sheet
states them as "Albumin in g/dL" or "... post-dosing (ug/ml)" — and they vary
by study (NIEHS-07 – -09 plasma ng/ml, NIEHS-10 ug/ml).
"""

import json

import openpyxl

from bmdx_pipe import key_sheet_units, tox_study_csv_to_pivot_txt

PLASMA = "Plasma 2 Hour X Concentration"


def _workbook(path):
    wb = openpyxl.Workbook()
    key = wb.active
    key.title = "Key to Column Labels"
    for row in [
        ("Column Label", "Explanation of Column Label"),
        ("Concentration", "Dose in mg/kg"),
        ("Phase", "Phase of Study (SD = Study day; )"),
        ("Albumin", "Albumin in g/dL"),
        (PLASMA, "Concentration of X in plasma 2 hours post-dosing (ug/ml)"),
        ("Hematocrit", "Hematocrit in %"),
        ("Remark", "Free-text remark (see protocol section 4)"),
    ]:
        key.append(row)
    wb.create_sheet("Data").append(["NTP Study Number", "Concentration", "Animal ID", "Sex"])
    wb.save(path)


def test_units_parsed_from_both_explanation_forms(tmp_path):
    p = tmp_path / "w.xlsx"
    _workbook(p)
    assert key_sheet_units(str(p)) == {
        "Albumin": "g/dL", PLASMA: "ug/ml", "Hematocrit": "%"}


def test_sidecar_records_units_for_its_endpoints(tmp_path):
    csv = tmp_path / "tissue_conc_truth_male.csv"
    csv.write_text(
        f"NTP Study Number,Concentration,Animal ID,Sex,Selection,Phase,Day,{PLASMA}\n"
        "S1,4,541,Male,Biosampling Animals,SD,4,31.5\n")
    out = tox_study_csv_to_pivot_txt(str(csv), str(tmp_path), "Tissue Concentration",
                                     "tox_study", units={PLASMA: "ug/ml", "Albumin": "g/dL"})
    sidecar = json.loads((tmp_path / "tissue_conc_truth_male.sidecar.json").read_text())
    assert out and sidecar["units"] == {PLASMA: "ug/ml"}

    # No units given: the sidecar says nothing about them (not a default).
    tox_study_csv_to_pivot_txt(str(csv), str(tmp_path), "Tissue Concentration", "tox_study")
    sidecar = json.loads((tmp_path / "tissue_conc_truth_male.sidecar.json").read_text())
    assert "units" not in sidecar
