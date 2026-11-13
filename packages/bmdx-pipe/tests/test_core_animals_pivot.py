"""Pivot values (statistics + BMD modeling input) are Core animals only.

Every published NIEHS body weight table counts the Core cohort: its n equals
the Core count per dose in NIEHS-07 … 13 (NIEHS-12 mice at 250 ppm: 8 Core,
n = 8), the internal-dose animals ("Biosampling"/"Biosample Animals", 3 per
group) excluded.  The sidecar keeps every animal.
"""

import json

import openpyxl

from bmdx_pipe import tox_study_csv_to_pivot_txt
from bmdx_pipe.pool_integrator import study_workbook_to_pool_files

BW = "NTP Study Number,Concentration,Animal ID,Sex,Selection,Body Weight,Observation Day,Terminal Flag\n"


def _pivot(path) -> tuple[list[str], dict[str, list[str]]]:
    lines = [ln.split("\t") for ln in open(path).read().splitlines() if not ln.startswith("#")]
    return lines[0][1:], {r[0]: r[1:] for r in lines[2:]}


def _csv(tmp_path, header, rows, platform="Body Weight"):
    csv = tmp_path / "body_weight_truth_male.csv"
    csv.write_text(header + rows)
    return tox_study_csv_to_pivot_txt(str(csv), str(tmp_path), platform, "tox_study")


def test_internal_dose_animals_stay_out_of_the_day_rows(tmp_path):
    [out] = _csv(tmp_path, BW,
                 "S,0,1,Male,Core Animals,296.5,SD0,\n"
                 "S,0,1,Male,Core Animals,311.0,SD5,Yes\n"
                 "S,4,2,Male,Biosample Animals,290.0,SD0,\n"
                 "S,4,2,Male,Biosample Animals,300.0,SD5,Yes\n"
                 "S,4,3,Male,Biosampling Animals,288.0,SD0,\n"
                 "S,4,4,Male,Core Animals,292.6,SD0,\n"
                 "S,4,4,Male,Core Animals,308.2,SD5,Yes\n")
    animals, rows = _pivot(out)
    assert animals == ["1", "4"]
    assert rows["SD0"] == ["296.5", "292.6"] and rows["SD5"] == ["311.0", "308.2"]
    # The sidecar still has every animal (attrition and mortality footnotes read it).
    side = json.load(open(out.replace(".txt", ".sidecar.json")))
    assert set(side["animals"]) == {"1", "2", "3", "4"}


def test_a_file_with_no_core_cohort_is_kept_whole(tmp_path):
    # Tissue Concentration: internal-dose animals only.
    hdr = "NTP Study Number,Concentration,Animal ID,Sex,Selection,Plasma 2 Hour X Concentration,Phase,Day\n"
    [out] = _csv(tmp_path, hdr, "S,4,2,Male,Biosample Animals,33.8,SD,4\n"
                                "S,12,3,Male,Biosample Animals,137.0,SD,4\n", platform="Tissue Concentration")
    assert _pivot(out)[0] == ["2", "3"]


def test_a_file_without_selection_counts_every_animal(tmp_path):
    hdr = "NTP Study Number,Concentration,Animal ID,Sex,Body Weight,Observation Day\n"
    [out] = _csv(tmp_path, hdr, "S,0,1,Male,250.0,SD0\nS,4,2,Male,251.0,SD0\n")
    assert _pivot(out)[0] == ["1", "2"]


def test_xlsx_pivot_is_core_only_too(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["NTP Study Number", "Concentration", "Animal ID", "Sex", "Selection", "Liver"])
    ws.append(["S", 0, "1", "Male", "Core Animals", 10.1])
    ws.append(["S", 4, "2", "Male", "Biosampling Animals", 10.5])
    ws.append(["S", 4, "3", "Male", "Core Animals", 11.2])
    path = tmp_path / "organ.xlsx"
    wb.save(path)
    [out] = study_workbook_to_pool_files(str(path), str(tmp_path), "Organ Weight")
    animals, rows = _pivot(out)
    assert animals == ["1", "3"] and rows["Liver"] == ["10.1", "11.2"]


OW = "NTP Study Number,Concentration,Animal ID,Sex,Selection,Removal Day,Liver,Terminal Body Weight\n"


def test_an_animal_removed_before_the_necropsy_is_kept_out_of_the_organ_weights(tmp_path):
    # NIEHS-12 mouse 502: weighed at its SD4 removal, organs not weighed; the
    # book's terminal body weight counts the SD5 necropsy only.
    [out] = _csv(tmp_path, OW,
                 "S,0,1,Male,Core Animals,SD5,1.1,20.3\n"
                 "S,250,2,Male,Core Animals,SD5,1.2,18.9\n"
                 "S,250,3,Male,Core Animals,SD4,NA,14.9\n"
                 "S,250,4,Male,Core Animals,,1.0,18.2\n", platform="Organ Weight")
    animals, rows = _pivot(out)
    assert animals == ["1", "2", "4"]           # no recorded day: kept
    assert rows["Terminal Body Weight"] == ["20.3", "18.9", "18.2"]
    side = json.load(open(out.replace(".txt", ".sidecar.json")))
    assert "3" in side["animals"]


def test_body_weights_keep_every_day(tmp_path):
    # Only organ weights are limited to the scheduled necropsy.
    [out] = _csv(tmp_path, BW, "S,0,1,Male,Core Animals,296.5,SD0,\n"
                               "S,0,2,Male,Core Animals,290.0,SD0,\n"
                               "S,0,2,Male,Core Animals,280.0,SD3,Yes\n")
    assert _pivot(out)[0] == ["1", "2"]
