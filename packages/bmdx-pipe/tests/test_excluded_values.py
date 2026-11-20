"""The values a study's package says were left out of the analysis (ADR-0037).

NIEHS-12 Table 3, footnote e: "n = 9. One value was excluded as an outlier."
Which value is a fact the package states in a file; the conversion leaves the
named value out of the pivot (statistics, derived endpoints, benchmark dose
inputs) and marks it in the sidecar, where the value itself is kept.
"""

import json

from bmdx_pipe import tox_study_csv_to_pivot_txt
from bmdx_pipe.excluded_values import (
    ExcludedValue,
    excluded_marks,
    is_applied,
    is_excluded_values_file,
    read_excluded_values,
)
from bmdx_pipe.file_integrator import fingerprint_file

HEADER = "Animal ID,Endpoint,Observation Day,Reason,Note\n"
OW = "NTP Study Number,Concentration,Animal ID,Sex,Selection,Kidney-Right,Terminal Body Weight,Removal Day\n"
BW = "NTP Study Number,Concentration,Animal ID,Sex,Selection,Body Weight,Observation Day,Terminal Flag\n"


def _file(tmp_path, rows, name="Excluded_Values.csv"):
    path = tmp_path / name
    path.write_text(HEADER + rows)
    return path


def _pivot(path):
    lines = [ln.split("\t") for ln in open(path).read().splitlines() if not ln.startswith("#")]
    return lines[0][1:], {r[0]: r[1:] for r in lines[2:]}


def _ev(animal, endpoint, day="", reason="measurement problem"):
    return ExcludedValue(animal, endpoint, day, reason, "", "Excluded_Values.csv", 2)


# ── the file ────────────────────────────────────────────────────────────────

def test_the_file_is_read_row_by_row(tmp_path):
    path = _file(tmp_path, "4,Kidney-Right,SD5,As Published,\"Table 3, footnote e\"\n"
                           "202,Bile salts/acids,,measurement problem,\n")
    assert is_excluded_values_file(path)
    values, problems = read_excluded_values(path)
    assert problems == []
    assert [(v.animal_id, v.endpoint, v.day, v.reason, v.row) for v in values] == [
        ("4", "Kidney-Right", "SD5", "as published", 2),
        ("202", "Bile salts/acids", "", "measurement problem", 3)]
    assert values[0].source == "Excluded_Values.csv"


def test_a_row_that_cannot_be_followed_is_a_problem_not_a_value(tmp_path):
    path = _file(tmp_path, "4,Kidney-Right,SD5,looked odd,\n"          # not a known reason
                           ",Liver,SD5,measurement problem,\n"          # no animal
                           "7,,SD5,unrelated illness,\n"                # no endpoint
                           "8,Liver,SD5,as published,\n"                # needs a note
                           "9,Liver,SD5,unrelated illness,\n"
                           "9,liver,5,measurement problem,\n")          # the same value again
    values, problems = read_excluded_values(path)
    assert [v.animal_id for v in values] == ["9"]
    assert [p.split(":")[0] for p in problems] == ["row 2", "row 3", "row 4", "row 5", "row 7"]
    assert "not one of" in problems[0] and "needs a note" in problems[3]
    assert "same value as row 6" in problems[4]


def test_a_data_file_is_not_an_excluded_values_file(tmp_path):
    data = tmp_path / "organ_weights.csv"
    data.write_text(OW + "S,0,1,Female,Core Animals,0.13,20.1,SD5\n")
    assert not is_excluded_values_file(data)
    assert read_excluded_values(data) == ([], [])


def test_its_fingerprint_names_no_platform_and_carries_what_it_says(tmp_path):
    path = _file(tmp_path, "4,Kidney-Right,SD5,measurement problem,\n")
    fp = fingerprint_file("f1", path.name, str(path), "csv", "2026-11-20T00:00:00+00:00")
    assert (fp.platform, fp.data_type) == (None, "excluded_values")
    assert fp.animal_ids == ["4"]
    # Each row is part of the fingerprint: a changed row is a changed basis.
    assert fp.endpoint_names == ["4 | Kidney-Right | SD5 | measurement problem"]
    assert not fp.is_long_format


# ── the conversion ──────────────────────────────────────────────────────────

def test_a_named_value_is_left_out_of_the_pivot_and_marked_in_the_sidecar(tmp_path):
    csv = tmp_path / "organ_weights_truth_female.csv"
    csv.write_text(OW + "S,0,3,Female,Core Animals,0.13,20.5,SD5\n"
                        "S,0,4,Female,Core Animals,0.06,22.2,SD5\n")
    [out] = tox_study_csv_to_pivot_txt(str(csv), str(tmp_path), "Organ Weight", "tox_study",
                                       excluded=[_ev("4", "kidney-right", "5")])
    animals, rows = _pivot(out)
    assert animals == ["3", "4"]
    assert rows["Kidney-Right"] == ["0.13", "NaN"]
    assert rows["Terminal Body Weight"] == ["20.5", "22.2"]      # the animal's other values stay

    side = json.load(open(out.replace(".txt", ".sidecar.json")))
    obs = {o["endpoint"]: o for o in side["animals"]["4"]["observations"]}
    assert obs["Kidney-Right"]["value"] is None
    assert obs["Kidney-Right"]["excluded"] == {
        "value": "0.06", "reason": "measurement problem", "note": "",
        "source": "Excluded_Values.csv"}
    assert obs["Terminal Body Weight"]["value"] == "22.2"
    [mark] = excluded_marks(side)
    assert (mark["animal_id"], mark["endpoint"], mark["dose"], mark["platform"]) == (
        "4", "Kidney-Right", 0.0, "Organ Weight")
    assert is_applied(_ev("4", "Kidney-Right", "SD5"), [mark])
    assert not is_applied(_ev("5", "Kidney-Right", "SD5"), [mark])


def test_a_weight_left_out_on_the_last_day_leaves_the_animal_out_of_the_gain(tmp_path):
    csv = tmp_path / "body_weight_truth_male.csv"
    csv.write_text(BW + "S,0,1,Male,Core Animals,296.5,SD0,\n"
                        "S,0,1,Male,Core Animals,311.0,SD5,Yes\n"
                        "S,0,2,Male,Core Animals,290.0,SD0,\n"
                        "S,0,2,Male,Core Animals,150.0,SD5,Yes\n")
    [out] = tox_study_csv_to_pivot_txt(str(csv), str(tmp_path), "Body Weight", "tox_study",
                                       excluded=[_ev("2", "Body Weight", "SD5")])
    _animals, rows = _pivot(out)
    assert rows["SD0"] == ["296.5", "290.0"]
    assert rows["SD5"] == ["311.0", "NaN"]
    assert rows["Body Weight Gain"] == ["14.5", "NaN"]


def test_a_row_without_a_day_names_the_value_on_every_day(tmp_path):
    csv = tmp_path / "body_weight_truth_male.csv"
    csv.write_text(BW + "S,0,1,Male,Core Animals,296.5,SD0,\n"
                        "S,0,1,Male,Core Animals,311.0,SD5,Yes\n"
                        "S,0,2,Male,Core Animals,290.0,SD0,\n"
                        "S,0,2,Male,Core Animals,150.0,SD5,Yes\n")
    [out] = tox_study_csv_to_pivot_txt(str(csv), str(tmp_path), "Body Weight", "tox_study",
                                       excluded=[_ev("2", "Body Weight")])
    animals, rows = _pivot(out)
    assert animals == ["1"] and rows["SD0"] == ["296.5"]


def test_internal_dose_values_cannot_be_named(tmp_path):
    # Tissue concentrations have the method's own outlier rule.
    hdr = "NTP Study Number,Concentration,Animal ID,Sex,Selection,Plasma 2 Hour X Concentration,Phase,Day\n"
    csv = tmp_path / "tissue_conc_truth_male.csv"
    csv.write_text(hdr + "S,4,2,Male,Biosample Animals,33.8,SD,4\n")
    [out] = tox_study_csv_to_pivot_txt(
        str(csv), str(tmp_path), "Tissue Concentration", "tox_study",
        excluded=[_ev("2", "Plasma 2 Hour X Concentration")])
    _animals, rows = _pivot(out)
    assert rows["Plasma 2 Hour X Concentration"] == ["33.8"]
    side = json.load(open(out.replace(".txt", ".sidecar.json")))
    assert excluded_marks(side) == []
