"""Measurement units come from the data — the study workbook's Key sheet —
never from a literal.

NIEHS-10's plasma concentrations are recorded in ug/ml (CEBS C20022-01 Key
sheet); NIEHS-07 – -09 record ng/ml.  The tissue table used to print "ng/mL"
for every study.
"""

import json

import openpyxl

from pipeline.sidecar_units import stamp_sidecar_units
from rendering.render_common import scan_pending_markers
from tables.table_builder_common import find_sidecar_paths, load_sidecar
from tables.tissue_concentration_table import (
    _parse_timepoint, build_tissue_concentration_table_from_sidecar,
)
from tables.toxicokinetics import build_internal_dose_narrative, compute_toxicokinetics
from tables.units import display_unit
from tooling.cebs_to_pool import convert_workbook

CHEM = "Perfluorohexanesulfonamide"


def test_lab_spelling_prints_as_si():
    assert [display_unit(u) for u in ("ug/ml", "ng/ml", "K/uL", "IU/L", "g/dL")] == [
        "µg/mL", "ng/mL", "K/µL", "IU/L", "g/dL"]


def test_detection_limit_columns_are_not_timepoints():
    assert _parse_timepoint(f"Plasma 2 Hour {CHEM} LOQ") is None
    assert _parse_timepoint(f"Plasma 2 Hour {CHEM} LOD") is None


def test_niehs10_unit_reaches_the_sidecar_at_ingest(reference_session):
    # cebs_to_pool's .units.json companion → the pool's ingest → the sidecar.
    session = reference_session("NIEHS-10", "DTXSID50469320")
    sc = load_sidecar(find_sidecar_paths(str(session), "Tissue Concentration")["Male"])
    assert sc["units"][f"Plasma 2 Hour {CHEM} Concentration"] == "ug/ml"
    ow = load_sidecar(find_sidecar_paths(str(session), "Organ Weight")["Male"])
    assert ow["units"]["Liver"] == "grams"


def test_niehs10_unit_comes_from_the_study_workbook_at_integration(reference_session):
    # A pool of unit-less truth CSVs plus the original study workbooks (what a
    # customer supplies): integration stamps the units from the workbook.
    from pipeline.pool_fingerprints import ensure_fingerprints

    session = reference_session("NIEHS-10", "DTXSID50469320", with_workbooks=True, units=False)
    paths = find_sidecar_paths(str(session), "Tissue Concentration")

    tc = build_tissue_concentration_table_from_sidecar(paths, compound_name=CHEM)
    assert scan_pending_markers(tc["footnotes"][0]) == [
        "[Placeholder: concentration unit not recorded in the data]"]
    assert compute_toxicokinetics(paths)["unit"] is None

    fps = ensure_fingerprints("DTXSID50469320")
    assert stamp_sidecar_units(fps, session)  # every platform with a workbook
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
