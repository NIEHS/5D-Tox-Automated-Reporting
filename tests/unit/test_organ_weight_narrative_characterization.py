"""
Characterization gate for _build_organ_weight_paragraphs (Phase 2 decomposition).

Pins the EXACT current prose output across every branch BEFORE the builder is
rewritten to a template+render form. The decomposition is behavior-preserving iff
these byte-for-byte expectations keep passing. Captured from the live builder on
2026-09-02.

Branches covered: no platform (empty), a multi-weight pair (absolute+relative,
"BMDs (BMDLs) ... respectively"), a single weight ("BMD (BMDL) was"), an
"endpoint"-type row that omits the weight word, the no-LOEL path (no "in dose
groups" clause), the no-significant-findings path, the non-significant tail list,
both sexes, and the sex/organ allowlists (including one that removes everything).
"""

from bmdx_pipe import TableRow

from narrative.unified_narrative import _build_organ_weight_paragraphs


def _row(label, bmd="ND", bmdl="ND", vals=None, resp=True):
    return TableRow(
        label=label, values_by_dose=vals or {}, n_by_dose={}, bmd_str=bmd,
        bmdl_str=bmdl, trend_marker="", bmd_status="", loel=None, noel=None,
        direction=None, responsive=resp, missing_animals_by_dose={},
    )


UNIT = "mg/kg"
CN = "PFHxSAm"

_liver_abs = _row("Liver Absolute", "12.5", "6.3", {0.0: "5.0", 50.0: "7.0*", 100.0: "9.0**"})
_liver_rel = _row("Liver Weight Relative", "10.1", "5.0", {0.0: "2.0", 50.0: "2.5", 100.0: "3.0*"})
_kidney_abs = _row("Kidney Absolute", "20.0", "15.0", {0.0: "10.0", 50.0: "8.0*", 100.0: "6.0**"})
_spleen = _row("Spleen", "8.0", "4.0", {0.0: "1.0", 50.0: "1.5*", 100.0: "2.0**"})
_thymus_abs = _row("Thymus Absolute", "30.0", "25.0", {0.0: "5.0", 50.0: "6.0", 100.0: "7.0"})
_heart_abs = _row("Heart Absolute", "ND", "ND", {0.0: "3.0"}, resp=False)
_adrenal = _row("Adrenal Gland", "ND", "ND", {0.0: "1.0"}, resp=False)


def test_no_organ_weight_platform_returns_empty():
    assert _build_organ_weight_paragraphs({}, CN, UNIT) == []


def test_multi_weight_pair_increase_bmds_plural():
    out = _build_organ_weight_paragraphs(
        {"Organ Weight": {"Male": [_liver_abs, _liver_rel]}}, CN, UNIT)
    assert out == [
        "In male rats at study termination, a significant increase in Liver "
        "absolute and relative weight occurred in dose groups ≥50 mg/kg; these "
        "endpoints had positive trends (Table 3). The BMDs (BMDLs) were 12.5 "
        "(6.3) mg/kg (absolute weight) and 10.1 (5.0) mg/kg (relative weight), "
        "respectively."
    ]


def test_single_weight_decrease_bmd_singular():
    out = _build_organ_weight_paragraphs(
        {"Organ Weight": {"Male": [_kidney_abs]}}, CN, UNIT)
    assert out == [
        "In male rats at study termination, a significant decrease in Kidney "
        "absolute weight occurred in dose groups ≥50 mg/kg; these endpoints had "
        "negative trends (Table 3). The BMD (BMDL) was 20.0 (15.0) mg/kg "
        "(absolute weight)."
    ]


def test_endpoint_type_omits_weight_word():
    out = _build_organ_weight_paragraphs(
        {"Organ Weight": {"Male": [_spleen]}}, CN, UNIT)
    assert out == [
        "In male rats at study termination, Spleen was significantly increased "
        "in dose groups ≥50 mg/kg; these endpoints had positive trends (Table "
        "3). The BMD (BMDL) was 8.0 (4.0) mg/kg."
    ]


def test_no_low_dose_omits_dose_group_clause():
    out = _build_organ_weight_paragraphs(
        {"Organ Weight": {"Male": [_thymus_abs]}}, CN, UNIT)
    assert out == [
        "In male rats at study termination, a significant increase in Thymus "
        "absolute weight occurred; these endpoints had positive trends (Table "
        "3). The BMD (BMDL) was 30.0 (25.0) mg/kg (absolute weight)."
    ]


def test_no_significant_findings():
    out = _build_organ_weight_paragraphs(
        {"Organ Weight": {"Male": [_heart_abs, _adrenal]}}, CN, UNIT)
    assert out == [
        "In male rats at study termination, there were no organ weights that "
        "exhibited significant trend and pairwise comparisons."
    ]


def test_non_significant_tail_list():
    out = _build_organ_weight_paragraphs(
        {"Organ Weight": {"Male": [_kidney_abs, _heart_abs, _adrenal]}}, CN, UNIT)
    assert out == [
        "In male rats at study termination, a significant decrease in Kidney "
        "absolute weight occurred in dose groups ≥50 mg/kg; these endpoints had "
        "negative trends (Table 3). The BMD (BMDL) was 20.0 (15.0) mg/kg "
        "(absolute weight). Significant trend and pairwise comparisons were not "
        "observed in absolute heart or adrenal gland weights."
    ]


def test_both_sexes_two_paragraphs():
    out = _build_organ_weight_paragraphs(
        {"Organ Weight": {"Male": [_liver_abs, _liver_rel], "Female": [_kidney_abs]}},
        CN, UNIT)
    assert out == [
        "In male rats at study termination, a significant increase in Liver "
        "absolute and relative weight occurred in dose groups ≥50 mg/kg; these "
        "endpoints had positive trends (Table 3). The BMDs (BMDLs) were 12.5 "
        "(6.3) mg/kg (absolute weight) and 10.1 (5.0) mg/kg (relative weight), "
        "respectively.",
        "In female rats at study termination, a significant decrease in Kidney "
        "absolute weight occurred in dose groups ≥50 mg/kg; these endpoints had "
        "negative trends (Table 3). The BMD (BMDL) was 20.0 (15.0) mg/kg "
        "(absolute weight).",
    ]


def test_sex_allowlist_male_only():
    out = _build_organ_weight_paragraphs(
        {"Organ Weight": {"Male": [_liver_abs, _liver_rel], "Female": [_kidney_abs]}},
        CN, UNIT, sex_allowlist=["male"])
    assert out == [
        "In male rats at study termination, a significant increase in Liver "
        "absolute and relative weight occurred in dose groups ≥50 mg/kg; these "
        "endpoints had positive trends (Table 3). The BMDs (BMDLs) were 12.5 "
        "(6.3) mg/kg (absolute weight) and 10.1 (5.0) mg/kg (relative weight), "
        "respectively."
    ]


def test_organ_allowlist_liver_only():
    out = _build_organ_weight_paragraphs(
        {"Organ Weight": {"Male": [_liver_abs, _liver_rel, _kidney_abs]}},
        CN, UNIT, organ_allowlist=["liver"])
    assert out == [
        "In male rats at study termination, a significant increase in Liver "
        "absolute and relative weight occurred in dose groups ≥50 mg/kg; these "
        "endpoints had positive trends (Table 3). The BMDs (BMDLs) were 12.5 "
        "(6.3) mg/kg (absolute weight) and 10.1 (5.0) mg/kg (relative weight), "
        "respectively."
    ]


def test_organ_allowlist_removes_all_returns_empty():
    out = _build_organ_weight_paragraphs(
        {"Organ Weight": {"Male": [_kidney_abs]}}, CN, UNIT, organ_allowlist=["liver"])
    assert out == []
