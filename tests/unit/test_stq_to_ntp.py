"""
tooling.stq_to_ntp keeps the unit a raw STQ extract records: the body-weight
extract's UNIT column ("g") becomes the truth CSV's .units.json companion,
which the pool reads into the sidecar (pipeline.pool_fingerprints). The
organ-weight extract records none, so its CSV gets no companion — a unit is
never assumed.
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
