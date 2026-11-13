"""
Characterization gate for _build_sub_platform_paragraphs (Phase 2 decomposition).

Pins the EXACT current prose output across every branch BEFORE the builder is
rewritten to a template+render form. Captured from the live builder on 2026-09-02.

Branches covered: empty input, the no-significant-endpoints path, a significant
increase and a significant decrease (with LOEL), a significant finding with no
LOEL (no "at ≥" clause), a multi-finding paragraph with a non-significant tail
list, and both sexes.
"""

from bmdx_pipe import TableRow

from narrative.unified_narrative import _build_sub_platform_paragraphs


def _row(label, bmd="ND", bmdl="ND", vals=None, resp=True):
    return TableRow(
        label=label, values_by_dose=vals or {}, n_by_dose={}, bmd_str=bmd,
        bmdl_str=bmdl, trend_marker="", bmd_status="", loel=None, noel=None,
        direction=None, responsive=resp, missing_animals_by_dose={},
    )


UNIT = "mg/kg"
CN = "PFHxSAm"

_alt = _row("Alanine aminotransferase", "45.0", "30.0", {0.0: "20.0", 50.0: "25.0*", 100.0: "30.0**"})
_glucose = _row("Glucose", "60.0", "40.0", {0.0: "100.0", 50.0: "90.0*", 100.0: "80.0**"})
_chol_nolow = _row("Cholesterol", "70.0", "50.0", {0.0: "50.0", 50.0: "55.0", 100.0: "60.0"})
_album = _row("Albumin", "ND", "ND", {0.0: "3.0"}, resp=False)
_protein = _row("Total protein", "ND", "ND", {0.0: "6.0"}, resp=False)


def test_empty_returns_empty():
    assert _build_sub_platform_paragraphs("Clinical Chemistry", {}, CN, UNIT) == []


def test_no_significant_endpoints():
    out = _build_sub_platform_paragraphs(
        "Clinical Chemistry", {"Male": [_album, _protein]}, CN, UNIT)
    assert out == [
        "In male rats, no clinical chemistry endpoints exhibited significant "
        "trend and pairwise comparisons."
    ]


def test_significant_increase_with_low_dose():
    out = _build_sub_platform_paragraphs(
        "Clinical Chemistry", {"Male": [_alt]}, CN, UNIT)
    assert out == [
        "In male rats, Alanine aminotransferase was significantly increased at "
        "≥50 mg/kg with a positive trend. The BMD and BMDL were 45.0 and 30.0 "
        "mg/kg, respectively."
    ]


def test_significant_decrease_with_low_dose():
    out = _build_sub_platform_paragraphs(
        "Clinical Chemistry", {"Male": [_glucose]}, CN, UNIT)
    assert out == [
        "In male rats, Glucose was significantly decreased at ≥50 mg/kg with a "
        "negative trend. The BMD and BMDL were 60.0 and 40.0 mg/kg, respectively."
    ]


def test_significant_no_low_dose_omits_clause():
    out = _build_sub_platform_paragraphs(
        "Clinical Chemistry", {"Male": [_chol_nolow]}, CN, UNIT)
    assert out == [
        "In male rats, Cholesterol was significantly increased with a positive "
        "trend. The BMD and BMDL were 70.0 and 50.0 mg/kg, respectively."
    ]


def test_multi_significant_and_non_significant_tail():
    out = _build_sub_platform_paragraphs(
        "Clinical Chemistry",
        {"Male": [_alt, _glucose, _album, _protein]}, CN, UNIT)
    assert out == [
        "In male rats, Alanine aminotransferase was significantly increased at "
        "≥50 mg/kg with a positive trend. The BMD and BMDL were 45.0 and 30.0 "
        "mg/kg, respectively. Glucose was significantly decreased at ≥50 mg/kg "
        "with a negative trend. The BMD and BMDL were 60.0 and 40.0 mg/kg, "
        "respectively. Significant trend and pairwise comparisons were not "
        "observed in albumin or total protein."
    ]


def test_both_sexes():
    out = _build_sub_platform_paragraphs(
        "Clinical Chemistry", {"Male": [_alt], "Female": [_album]}, CN, UNIT)
    assert out == [
        "In male rats, Alanine aminotransferase was significantly increased at "
        "≥50 mg/kg with a positive trend. The BMD and BMDL were 45.0 and 30.0 "
        "mg/kg, respectively.",
        "In female rats, no clinical chemistry endpoints exhibited significant "
        "trend and pairwise comparisons.",
    ]
