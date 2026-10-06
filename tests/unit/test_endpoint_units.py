"""Measurement units come from the data — the study workbook's Key sheet —
never from a literal.

NIEHS-10's plasma concentrations are recorded in ug/ml (CEBS C20022-01 Key
sheet); NIEHS-07 – -09 record ng/ml.  The tissue table used to print "ng/mL"
for every study.
"""

import json
import shutil
from pathlib import Path

import openpyxl
import pytest
from bmdx_pipe.file_integrator import TIER_XLSX

from pipeline.sidecar_units import stamp_sidecar_units
from rendering.render_common import scan_pending_markers
from tables.tissue_concentration_table import (
    _parse_timepoint, build_tissue_concentration_table_from_sidecar,
)
from tables.toxicokinetics import build_internal_dose_narrative, compute_toxicokinetics
from tables.units import display_unit
from tooling.cebs_to_pool import convert_workbook

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "DTXSID50469320" / "files"
TISSUE_XLSX = "C20022-01_Individual_Animal_Tissue_Concentration_Data.xlsx"
CHEM = "Perfluorohexanesulfonamide"


def test_lab_spelling_prints_as_si():
    assert [display_unit(u) for u in ("ug/ml", "ng/ml", "K/uL", "IU/L", "g/dL")] == [
        "µg/mL", "ng/mL", "K/µL", "IU/L", "g/dL"]


def test_detection_limit_columns_are_not_timepoints():
    assert _parse_timepoint(f"Plasma 2 Hour {CHEM} LOQ") is None
    assert _parse_timepoint(f"Plasma 2 Hour {CHEM} LOD") is None


@pytest.mark.skipif(not (GOLDEN / TISSUE_XLSX).exists(), reason="golden fixture not present")
def test_niehs10_unit_comes_from_the_study_workbook(tmp_path):
    session = tmp_path / "s"
    (session / "files").mkdir(parents=True)
    for name in (TISSUE_XLSX, "tissue_conc_truth_male.sidecar.json",
                 "tissue_conc_truth_female.sidecar.json"):
        shutil.copy2(GOLDEN / name, session / "files" / name)
    paths = {s: str(session / "files" / f"tissue_conc_truth_{s.lower()}.sidecar.json")
             for s in ("Male", "Female")}

    # Before integration stamps the units: the table says the unit is unrecorded.
    tc = build_tissue_concentration_table_from_sidecar(paths, compound_name=CHEM)
    assert scan_pending_markers(tc["footnotes"][0]) == [
        "[Placeholder: concentration unit not recorded in the data]"]
    assert compute_toxicokinetics(paths)["unit"] is None

    fps = {"x": {"tier": TIER_XLSX, "is_study_file": True,
                 "platform": "Tissue Concentration", "filename": TISSUE_XLSX}}
    assert len(stamp_sidecar_units(fps, session)) == 2
    tc = build_tissue_concentration_table_from_sidecar(paths, compound_name=CHEM)
    assert tc["footnotes"][0].endswith("plasma concentration data are presented in µg/mL.")
    tk = compute_toxicokinetics(paths)
    assert tk["unit"] == "µg/mL"
    assert "(in µg/mL)" in build_internal_dose_narrative(tk, CHEM)[0]
    # Idempotent: a second integration changes nothing.
    assert stamp_sidecar_units(fps, session) == {}


def test_cebs_converter_writes_the_units_companion(tmp_path):
    wb = openpyxl.Workbook()
    key = wb.active
    key.title = "Key to Column Labels"
    for row in [("Column Label", "Explanation of Column Label"),
                ("Albumin", "Albumin in g/dL"), ("Unused", "Not in the Data sheet (mg)")]:
        key.append(row)
    data = wb.create_sheet("Data")
    data.append(["NTP Study Number", "Concentration", "Animal ID", "Sex", "Albumin"])
    data.append(["C1", "0", "1", "Male", "3.1"])
    src = tmp_path / "C1_Individual_Animal_Clinical_Chemistry_Data.xlsx"
    wb.save(src)
    out = tmp_path / "out"
    out.mkdir()
    assert convert_workbook(str(src), str(out))["units"] == 1
    assert json.loads((out / "clin_chem_truth_male.units.json").read_text()) == {"Albumin": "g/dL"}


def test_tk_narrative_names_the_final_exposure_for_inhalation():
    tk = {"by_sex": {"Female": {"timepoints": [2, 24], "doses": [4.0], "means": {},
                                "half_life": {}}}, "unit": "ng/mL"}
    text = build_internal_dose_narrative(tk, "X", "ppm", design={"route": "inhaled"})[0]
    assert "following the final exposure in the 4 ppm exposure groups" in text
