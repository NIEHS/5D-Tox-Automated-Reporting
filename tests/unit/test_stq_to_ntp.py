"""
tooling.stq_to_ntp keeps the unit a raw STQ extract records: the body-weight
extract's UNIT column ("g") becomes the truth CSV's .units.json companion,
which the pool reads into the sidecar (pipeline.pool_fingerprints). The
organ-weight extract records none for its weights — a unit is never assumed.
The dose unit (DOSE_UNIT) goes to the companion under the dose column,
"Concentration", and from there to the sidecar and the file's fingerprint.
"""

import json

import openpyxl
import pytest

from tooling.stq_to_ntp import convert_body_weight, convert_organ_weight

BW_HEADER = ["DEPOSITOR_STUDY_NUMBER", "DOSE", "ANMLNUM", "SEX", "SELECTION",
             "WGTVALUE", "UNIT", "OBSDAY", "TERMINAL_FLAG"]
OW_HEADER = ["DEPOSITOR_STUDY_NUMBER", "DOSE", "ANMLID", "SEX", "SELECTION",
             "RMVLDAY", "ORGAN_NAME", "ORGANVALUE"]


def _xlsx(path, header, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return str(path)


def test_the_body_weight_unit_goes_to_the_companion(tmp_path):
    src = _xlsx(tmp_path / "bw.xlsx", BW_HEADER, [
        ["C08002-01", "0", "901", "Male", None, "297.7", "g", "SD0", None],
        ["C08002-01", "0", "901", "Male", None, "310.2", "g", "SD5", "Yes"],
    ])
    (out, chem, n), = convert_body_weight(src, tmp_path / "out")
    assert chem == "BPAF" and n == 2
    assert json.loads(out.with_suffix(".units.json").read_text()) == {"Body Weight": "g"}


def test_two_units_for_one_measurement_are_refused(tmp_path):
    src = _xlsx(tmp_path / "bw.xlsx", BW_HEADER, [
        ["C08002-01", "0", "901", "Male", None, "297.7", "g", "SD0", None],
        ["C08002-01", "0", "902", "Male", None, "0.31", "kg", "SD0", None],
    ])
    with pytest.raises(ValueError, match="more than one unit"):
        convert_body_weight(src, tmp_path / "out")


def test_no_unit_recorded_no_companion(tmp_path):
    src = _xlsx(tmp_path / "ow.xlsx", OW_HEADER, [
        ["C08002-01", "0", "901", "Male", "Core Males", "SD5", "Liver Weight", "11.2"],
    ])
    (out, _, _), = convert_organ_weight(src, tmp_path / "out")
    assert out.exists() and not out.with_suffix(".units.json").exists()


# --- the dose unit (2026-11-17): the extracts record it in DOSE_UNIT; the
# converter dropped it, so BPAF and Triclosan read "no dose unit recorded" ---

BW_DOSED = BW_HEADER[:2] + ["DOSE_UNIT"] + BW_HEADER[2:]
OW_DOSED = OW_HEADER[:2] + ["DOSE_UNIT"] + OW_HEADER[2:]


def test_the_dose_unit_goes_to_the_companion_under_the_dose_column(tmp_path):
    bw = _xlsx(tmp_path / "bw.xlsx", BW_DOSED, [
        ["C08002-01", "0", "mg/kg", "901", "Male", None, "297.7", "g", "SD0", None],
        ["C08002-01", "8", "mg/kg", "905", "Male", None, "310.2", "g", "SD0", None],
    ])
    (out, _, _), = convert_body_weight(bw, tmp_path / "out")
    assert json.loads(out.with_suffix(".units.json").read_text()) == {
        "Concentration": "mg/kg", "Body Weight": "g"}
    # The organ-weight extract has no unit for its weights: the dose unit only.
    ow = _xlsx(tmp_path / "ow.xlsx", OW_DOSED, [
        ["C08002-01", "0", "mg/kg", "901", "Male", "Core Males", "SD5", "Liver Weight", "11.2"],
    ])
    (out, _, _), = convert_organ_weight(ow, tmp_path / "out")
    assert json.loads(out.with_suffix(".units.json").read_text()) == {"Concentration": "mg/kg"}


def test_two_dose_units_in_one_study_are_refused(tmp_path):
    bw = _xlsx(tmp_path / "bw.xlsx", BW_DOSED, [
        ["C08002-01", "0", "mg/kg", "901", "Male", None, "297.7", "g", "SD0", None],
        ["C08002-01", "8", "ppm", "905", "Male", None, "310.2", "g", "SD0", None],
    ])
    with pytest.raises(ValueError, match="dose recorded in more than one unit"):
        convert_body_weight(bw, tmp_path / "out")


def test_the_dose_unit_reaches_the_sidecar_and_the_fingerprint(tmp_path):
    """Converter → companion → pivot sidecar → the pivot's fingerprint, which
    is where the study's parameters read the recorded unit."""
    from bmdx_pipe import tox_study_csv_to_pivot_txt
    from bmdx_pipe.file_integrator import fingerprint_file

    from pipeline.study_parameters import resolve

    bw = _xlsx(tmp_path / "bw.xlsx", BW_DOSED, [
        ["C08002-01", str(dose), "mg/kg", str(900 + i), "Male", None, str(300 + i), "g",
         day, "Yes" if day == "SD5" else None]
        for i, dose in enumerate([0, 0, 8, 8], start=1) for day in ("SD0", "SD5")])
    (csv_path, _, _), = convert_body_weight(bw, tmp_path / "conv")
    units = json.loads(csv_path.with_suffix(".units.json").read_text())
    pool = tmp_path / "files"
    pool.mkdir()
    (pivot,) = tox_study_csv_to_pivot_txt(str(csv_path), str(pool), "Body Weight", "tox_study",
                                          units=units)
    sidecar = json.loads((pool / "body_weight_truth_male.sidecar.json").read_text())
    assert sidecar["dose_unit"] == "mg/kg" and sidecar["units"] == {"Body Weight": "g"}
    fp = fingerprint_file("f1", "body_weight_truth_male.txt", pivot, "txt", "2026-11-17", None)
    assert fp.dose_unit == "mg/kg"
    params = resolve(None, [fp.dose_unit], {})
    assert (params.values["dose_unit"], params.sources["dose_unit"]) == ("mg/kg", "recorded")

    # A source that records none writes none: never assumed.
    bare = tmp_path / "bare"
    bare.mkdir()
    (pivot,) = tox_study_csv_to_pivot_txt(str(csv_path), str(bare), "Body Weight", "tox_study")
    assert "dose_unit" not in json.loads(
        (bare / "body_weight_truth_male.sidecar.json").read_text())
    assert fingerprint_file("f2", "body_weight_truth_male.txt", pivot, "txt", "2026-11-17",
                            None).dose_unit is None
