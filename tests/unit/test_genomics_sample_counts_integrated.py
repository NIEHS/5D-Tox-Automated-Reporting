"""Table 1 sample counts come from the integrated project's gene-expression
experiments (organ/sex from experimentDescription, one count per treatment).

A .bm2 holding two organs has ONE file fingerprint with no organ or sex, so the
fingerprint-based counts printed an "Unknown"/"null" row with the first
experiment's counts only."""

from narrative.methods_extract import _genomics_sample_counts_from_integrated


def _exp(name, organ, sex, doses):
    return {"name": name, "experimentDescription": {"dataType": "gene_expression",
            "organ": organ, "sex": sex},
            "treatments": [{"name": f"s{i}", "dose": d} for i, d in enumerate(doses)]}


def test_counts_per_organ_and_sex_from_treatments():
    integrated = {"doseResponseExperiments": [
        _exp("k", "kidney", "male", [0, 0, 0, 8, 8]),
        _exp("l", "liver", "male", [0, 0, 8]),
        {"name": "bw", "experimentDescription": {"dataType": "tox_study"}, "treatments": []},
    ]}
    assert _genomics_sample_counts_from_integrated(integrated) == {
        "Kidney": {"Male": {0.0: 3, 8.0: 2}},
        "Liver": {"Male": {0.0: 2, 8.0: 1}},
    }


def test_missing_organ_falls_back():
    integrated = {"doseResponseExperiments": [_exp("x", None, "male", [0])]}
    assert _genomics_sample_counts_from_integrated(integrated) is None
