"""A gene-expression experiment is not "blood" unless its name says so.

NIEHS-13's heart experiment "rat_4D_HE_No0" was inferred as blood (HE read as
hematology).  The prompt names the tissue codes; validation clears an
unsupported "blood" so the metadata review sees a gap, not a wrong organ.
"""

from bmdx_pipe.experiment_metadata import _SYSTEM_PROMPT, infer_experiment_metadata


def _infer(name, organ, data_type="gene_expression"):
    exp = {"name": name, "probeResponses": [{"probe": {"id": "DERA_8462"}, "responses": [1.0]}]}
    llm = lambda *a, **k: {name: {"organ": organ, "dataType": data_type, "subjectType": "in vivo"}}
    return infer_experiment_metadata([exp], {}, {"name": "X"}, llm_generate_json=llm)[name]


def test_tissue_code_misread_as_blood_is_left_for_review():
    assert _infer("rat_4D_HE_No0", "blood")["organ"] is None


def test_blood_stays_where_the_name_or_domain_supports_it():
    assert _infer("Whole_Blood_No0", "blood")["organ"] == "blood"
    assert _infer("clin_chem_truth_female", "blood", data_type="tox_study")["organ"] == "blood"
    assert _infer("rat_4D_KI_No0", "kidney")["organ"] == "kidney"


def test_prompt_names_the_niehs_tissue_codes():
    assert "HE = heart" in _SYSTEM_PROMPT and "OV = ovary" in _SYSTEM_PROMPT
