"""reconcile_genomics_sidecar: organ/sex from ExperimentDescription, and flagged
single-sex inheritance for genomics experiments that state no sex."""

import json

from bmdx_pipe.genomics_metadata import reconcile_genomics_sidecar, study_single_sex


def _exp(name, organ=None, sex=None):
    return {"name": name, "experimentDescription": {"organ": organ, "sex": sex}}


def _write_sidecar(tmp_path, *pairs):
    p = tmp_path / "genomics.sidecar.json"
    p.write_text(json.dumps({"experiments": [
        {"name": n, "organ": o, "sex": s} for n, o, s in pairs]}))
    return p


def _read(p):
    return [(e["organ"], e["sex"]) for e in json.loads(p.read_text())["experiments"]]


def test_name_parse_corrected_and_single_sex_inherited(tmp_path):
    integ = {"_meta": {}, "doseResponseExperiments": [
        _exp("Chem_S1_AA_Kidney_No0", "kidney", None),
        _exp("Chem_S1_AA_liver_No0", "liver", "both"),
        _exp("body_weight_truth_male", "Whole Body", "male"),
        _exp("organ_weights_truth_male", "kidney, liver", "male"),
    ]}
    sc = _write_sidecar(tmp_path, ("Chem_S1_AA_Kidney_No0", "Chem", "Unknown"),
                        ("Chem_S1_AA_liver_No0", "Chem", "Unknown"))
    inferred = reconcile_genomics_sidecar(integ, str(sc))
    assert _read(sc) == [("Kidney", "Male"), ("Liver", "Male")]
    assert inferred == {"Chem_S1_AA_Kidney_No0": "male", "Chem_S1_AA_liver_No0": "male"}
    assert set(integ["_meta"]["inferred"]["genomics_sex"]) == set(inferred)
    assert integ["doseResponseExperiments"][0]["experimentDescription"]["sex"] == "male"


def test_mixed_sex_study_does_not_inherit(tmp_path):
    integ = {"doseResponseExperiments": [
        _exp("Chem_S1_AA_Kidney_No0", "kidney", None),
        _exp("x_male", "Whole Body", "male"),
        _exp("x_female", "Whole Body", "female"),
    ]}
    sc = _write_sidecar(tmp_path, ("Chem_S1_AA_Kidney_No0", "Chem", "Unknown"))
    assert reconcile_genomics_sidecar(integ, str(sc)) == {}
    assert _read(sc) == [("Kidney", "Unknown")]
    assert "inferred" not in integ.get("_meta", {})


def test_explicit_sex_kept_and_nothing_inferred(tmp_path):
    integ = {"doseResponseExperiments": [
        _exp("Kidney_Chem_Male_No0", "kidney", "male"),
        _exp("Kidney_Chem_Female_No0", "kidney", "female"),
    ]}
    sc = _write_sidecar(tmp_path, ("Kidney_Chem_Male_No0", "Kidney", "Male"),
                        ("Kidney_Chem_Female_No0", "Kidney", "Female"))
    before = sc.read_text()
    assert reconcile_genomics_sidecar(integ, str(sc)) == {}
    assert sc.read_text() == before  # unchanged → not rewritten


def test_study_single_sex():
    assert study_single_sex([_exp("a", sex="male"), _exp("b", sex=None)]) == "male"
    assert study_single_sex([_exp("a", sex="male"), _exp("b", sex="female")]) is None
    assert study_single_sex([_exp("a", sex="both")]) is None


def test_missing_sidecar_is_noop(tmp_path):
    assert reconcile_genomics_sidecar({"doseResponseExperiments": []},
                                      str(tmp_path / "absent.json")) == {}
