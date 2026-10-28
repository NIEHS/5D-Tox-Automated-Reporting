"""The workbooks state an experiment's metadata first; the model infers the rest (ADR-0032)."""

from bmdx_pipe.experiment_metadata import (
    apply_described, attach_metadata, describe_from_structure, record_provenance,
    workbook_disagreements,
)
from bmdx_pipe.pool_integrator import _apply_approved_metadata

STRUCTURE = {
    "design": {"species": "rat", "strain": "Sprague-Dawley", "articleRoute": "oral",
               "administrationMeans": "gavage"},
    "animals": {"101": {"sex": "Male", "dose": 0.0}, "111": {"sex": "Female", "dose": 0.0}},
}


def _exps():
    return [
        {"name": "body_weight_truth_male", "treatments": [{"name": "101", "dose": 0.0}],
         "experimentDescription": {"sex": "female", "platform": "Body Weight"}},
        {"name": "Liver_X_Female", "treatments": [{"name": "Plate1-111", "dose": 0.0}],
         "experimentDescription": None},
    ]


def test_the_workbooks_state_first_and_win():
    exps = _exps()
    described = describe_from_structure(exps, STRUCTURE)
    assert described["body_weight_truth_male"]["sex"] == "male"
    # A sample traced to its animal ("Plate1-111" → 111) gives the sex.
    assert described["Liver_X_Female"]["sex"] == "female"
    assert described["Liver_X_Female"]["species"] == "rat"   # the design is study-wide
    prov: dict = {}
    apply_described(exps, described, prov)
    assert exps[0]["experimentDescription"]["sex"] == "male"
    assert prov["body_weight_truth_male"]["sex"] == "workbook"

    # The model fills only what is left, and is recorded as such.
    inferred = {"body_weight_truth_male": {"sex": "female", "organ": "Whole Body"},
                "Liver_X_Female": {"sex": "female", "organ": "liver"}}
    assert workbook_disagreements(described, inferred) == [
        "body_weight_truth_male: sex inferred 'female', the workbook states 'male'"]
    before = {e["name"]: dict(e["experimentDescription"]) for e in exps}
    attach_metadata(exps, inferred)
    record_provenance(exps, before, prov, "llm")
    assert exps[0]["experimentDescription"]["sex"] == "male"
    assert prov["Liver_X_Female"]["organ"] == "llm" and prov["Liver_X_Female"]["sex"] == "workbook"


def test_an_approval_cannot_override_the_workbook():
    exps = _exps()
    prov: dict = {}
    apply_described(exps, describe_from_structure(exps, STRUCTURE), prov)
    _apply_approved_metadata(exps, {"body_weight_truth_male": {
        "sex": "female", "species": "rat", "organ": "Whole Body"}}, prov)
    ed = exps[0]["experimentDescription"]
    assert ed["sex"] == "male" and ed["organ"] == "Whole Body"
    assert prov["body_weight_truth_male"] == {
        "species": "workbook", "strain": "workbook", "articleRoute": "workbook",
        "administrationMeans": "workbook", "sex": "workbook", "organ": "approved"}
    # Without a structure nothing is stated: today's behaviour.
    assert describe_from_structure(_exps(), None) == {}


def test_a_platform_with_only_its_workbook_stops_integration(tmp_path):
    import pytest
    from bmdx_pipe.pool_integrator import integrate_pool

    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "S1_Individual_Animal_Body_Weight_Data.xlsx").write_bytes(b"")
    fps = {"w": {"filename": "S1_Individual_Animal_Body_Weight_Data.xlsx", "file_type": "xlsx",
                 "data_type": "tox_study", "platform": "Body Weight"}}
    matrix = {"Body Weight|tox_study": {"xlsx": ["w"], "txt_csv": [], "bm2": []}}
    with pytest.raises(ValueError, match="only its workbook"):
        integrate_pool("DTXSID", str(tmp_path), fps, matrix, [])
