"""CEBS database-export workbooks (NIEHS-02 … 05) → NTP Key/Data rows.

Rules (tooling.cebs_db_export), each checked against the published summaries:
the marked cohort only when SELECTION marks one, "Exclude"/"Not Measured" →
"NA", NAME/VALUE rows pivoted per animal and day, Key/Data organ names, units
from the export's UNIT column.
"""

from tooling.cebs_db_export import to_key_data

BW = ["DEPOSITOR_STUDY_NUMBER", "DOSE", "DOSE_UNIT", "ANMLNUM", "SEX", "SELECTION",
      "WGTVALUE", "UNIT", "OBSDAY", "TERMINAL_FLAG"]


def test_body_weight_marked_cohort_and_excluded_values():
    rows = [["X-C10674", "0", "mMol/kg", "7", "Male", "Original Animals", "250.1", "g", "SD0", ""],
            ["X-C10674", "0", "mMol/kg", "7", "Male", "Original Animals", "Exclude", "g", "SD3", "Yes"],
            ["X-C10674", "0", "mMol/kg", "165", "Male", "", "236.3", "g", "SD0", ""]]   # second cohort
    header, out, units, notes = to_key_data("body_weight", BW, rows)
    assert header == ["NTP Study Number", "Concentration", "Animal ID", "Sex", "Body Weight",
                      "Observation Day", "Terminal Flag"]
    assert out == [["C10674", "0", "7", "Male", "250.1", "SD0", ""],
                   ["C10674", "0", "7", "Male", "NA", "SD3", "Yes"]]    # the death stays, unvalued
    assert units == {"Body Weight": "g"}
    assert "165" in notes[0]


def test_an_unmarked_export_keeps_every_animal():
    rows = [["X-C20299", "0", "mMol/kg", "173", "Male", "", "258.9", "g", "SD0", ""],
            ["X-C20299", "0", "mMol/kg", "174", "Male", "", "250.0", "g", "SD0", ""]]
    _, out, _, notes = to_key_data("body_weight", BW, rows)
    assert [r[2] for r in out] == ["173", "174"] and notes == []


def test_organ_weights_pivot_per_animal_with_key_data_names():
    hdr = ["DEPOSITOR_STUDY_NUMBER", "DOSE", "ANMLID", "SEX", "SELECTION", "RMVLDAY", "ORGAN_NAME", "ORGANVALUE"]
    rows = [["X-C1", "0", "26", "Male", "", "SD4", n, v] for n, v in
            (("Brain Weight", "1.84"), ("Liver Weight", "Not Measured"), ("Terminal Bodyweight", "272.3"))]
    header, out, units, _ = to_key_data("organ_weights", hdr, rows)
    assert header[-4:] == ["Removal Day", "Brain", "Liver", "Terminal Body Weight"]
    assert out == [["C1", "0", "26", "Male", "SD4", "1.84", "NA", "272.3"]]
    assert units == {}                                   # the organ weight export records none


def test_clinical_chemistry_units_come_from_the_export():
    hdr = ["DEPOSITOR_STUDY_NUMBER", "DOSE", "ANMLNUM", "SEX", "SELECTION", "OBSDAY",
           "CLINCHEM_MEASUREMENT_NAME", "CLINCHEM_MEASUREMENT_VALUE", "UNIT"]
    rows = [["X-C1", "0", "26", "Male", "", "SD4", "Albumin", "3.5", "g/dL"],
            ["X-C1", "0", "26", "Male", "", "SD4", "Creatinine", ".25", "mg/dL"]]
    header, out, units, _ = to_key_data("clin_chem", hdr, rows)
    assert header[-3:] == ["Observation Day", "Albumin", "Creatinine"]
    assert out == [["C1", "0", "26", "Male", "SD4", "3.5", ".25"]]
    assert units == {"Albumin": "g/dL", "Creatinine": "mg/dL"}
