"""tables.row_sources: the dataset endpoints a row of a results table is built
from, read back from the builders' own naming."""

from tables.row_sources import row_sources

ORGANS = ["Heart", "Kidney-Left", "Kidney-Right", "Liver", "Lungs", "Terminal Body Weight"]


def test_a_row_named_as_its_endpoint_is_that_endpoint():
    assert row_sources("Clinical Chemistry", "Albumin", ["Albumin", "Glucose"]) == {
        "endpoints": ["Albumin"], "how": None}
    # Whatever the table: an exact name needs no rule.
    assert row_sources(None, "Albumin", ["Albumin"]) == {"endpoints": ["Albumin"], "how": None}


def test_organ_weight_rows_as_the_builder_labels_them():
    from tables.organ_weight_table import ABSOLUTE, RELATIVE, TERMINAL_BODY_WEIGHT, row_label

    assert row_sources("Organ Weight", row_label(TERMINAL_BODY_WEIGHT, "g"), ORGANS) == {
        "endpoints": ["Terminal Body Weight"], "how": None}
    for organ in ORGANS[:-1]:
        assert row_sources("Organ Weight", row_label(f"{organ} {ABSOLUTE}", "g"), ORGANS) == {
            "endpoints": [organ], "how": None}
        relative = row_sources("Organ Weight", row_label(f"{organ} {RELATIVE}", "mg/g"), ORGANS)
        assert relative["endpoints"] == [organ, "Terminal Body Weight"]
        assert "divided by the terminal body weight" in relative["how"]


def test_an_organ_the_dataset_does_not_hold_is_not_guessed():
    assert row_sources("Organ Weight", "Spleen Absolute (g)", ORGANS) is None
    # A relative weight needs the body weight it is divided by.
    assert row_sources("Organ Weight", "Heart Relative (mg/g)", ["Heart"]) is None


def test_body_weight_day_rows_are_the_study_day_endpoints():
    from tables.body_weight_table import BODY_WEIGHT_GAIN, _study_day_label

    endpoints = [BODY_WEIGHT_GAIN, "SD0", "SD4", "SD5"]
    for endpoint in endpoints[1:]:
        assert row_sources("Body Weight", _study_day_label(endpoint), endpoints)["endpoints"] == [endpoint]
    assert row_sources("Body Weight", BODY_WEIGHT_GAIN, endpoints) == {
        "endpoints": [BODY_WEIGHT_GAIN], "how": None}
    assert row_sources("Body Weight", "9", endpoints) is None


def test_derived_clinical_chemistry_rows_name_what_they_are_computed_from():
    from bmdx_pipe.apical_report import AG_RATIO, GLOBULIN

    measured = ["Albumin", "Globulin", "Total protein"]
    assert row_sources("Clinical Chemistry", AG_RATIO, measured) == {
        "endpoints": ["Albumin", "Globulin"], "how": "albumin divided by globulin, per animal"}
    # Globulin not measured: derived first, from total protein and albumin.
    derived = row_sources("Clinical Chemistry", AG_RATIO, ["Albumin", "Total protein"])
    assert derived["endpoints"] == ["Albumin", "Total protein"]
    assert "globulin is total protein minus albumin" in derived["how"]
    assert row_sources("Clinical Chemistry", GLOBULIN, ["Albumin", "Total protein"])["endpoints"] == [
        "Total protein", "Albumin"]
    assert row_sources("Clinical Chemistry", AG_RATIO, ["Albumin"]) is None


def test_the_derivation_computes_from_the_inputs_it_declares():
    """DERIVED_INPUTS says what _derived_protein_endpoints reads."""
    from bmdx_pipe.apical_report import AG_RATIO, DERIVED_INPUTS, GLOBULIN, _derived_protein_endpoints

    assert DERIVED_INPUTS[GLOBULIN][0] == ("Total protein", "Albumin")
    assert DERIVED_INPUTS[AG_RATIO][0] == ("Albumin", GLOBULIN)
    both = [("Albumin", [3.0]), ("Total protein", [5.0])]
    assert dict(_derived_protein_endpoints(both)) == {GLOBULIN: [2.0], AG_RATIO: [1.5]}
    # Without total protein there is no globulin, and so no ratio; a measured
    # globulin gives the ratio without it.
    assert _derived_protein_endpoints([("Albumin", [3.0])]) == []
    assert dict(_derived_protein_endpoints([("Albumin", [3.0]), (GLOBULIN, [2.0])])) == {AG_RATIO: [1.5]}


def test_tissue_concentration_rows_as_the_builder_labels_them():
    from tables.blood_tissue_concentration_table import concentration_label, normalized_label

    endpoints = ["Blood 1,2-DCB Concentration", "Blood 1,2-DCB LOD",
                 "Liver 1,2-DCB Concentration", "Liver 1,2-DCB LOD"]
    plain = row_sources("Tissue Concentration", concentration_label("Blood", "ng/mL"), endpoints)
    assert plain["endpoints"] == ["Blood 1,2-DCB Concentration", "Blood 1,2-DCB LOD"]
    normalized = row_sources("Tissue Concentration", normalized_label("Liver", "ng/g", "ppm"), endpoints)
    assert normalized["endpoints"] == ["Liver 1,2-DCB Concentration", "Liver 1,2-DCB LOD"]
    assert "divided by the exposure concentration" in normalized["how"]
    assert row_sources("Tissue Concentration", concentration_label("Lung", "ng/g"), endpoints) is None


def test_a_table_without_a_rule_links_only_exact_names():
    assert row_sources("Hormones", "Thyroxine (total)", ["Total T4"]) is None
