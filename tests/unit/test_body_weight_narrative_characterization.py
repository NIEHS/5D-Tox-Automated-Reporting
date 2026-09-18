"""
Characterization gate for _build_body_weight_paragraphs (Phase 2 decomposition).

Pins the EXACT current prose output across all three branches BEFORE the builder
is rewritten to a template+render form. The decomposition is behavior-preserving
iff these byte-for-byte expectations keep passing. Captured from the live builder
on 2026-09-01.
"""

from bmdx_pipe import TableRow

from narrative.unified_narrative import _build_body_weight_paragraphs


def _row(label, bmd, bmdl, vals, resp=True):
    return TableRow(
        label=label, values_by_dose=vals, n_by_dose={}, bmd_str=bmd, bmdl_str=bmdl,
        trend_marker="", bmd_status="", loel=None, noel=None, direction=None,
        responsive=resp, missing_animals_by_dose={},
    )


def test_both_sexes_significant_with_and_without_loel():
    # Male: decreasing, has a pairwise-significant dose (loel segment present).
    male = _row("Terminal Body Wt.", "41.2", "22.8",
                {0.0: "100.0", 50.0: "85.0*", 100.0: "70.0**"})
    # Female: increasing, NO pairwise marker → low_dose None → loel segment dropped.
    female = _row("Terminal Body Wt.", "30.0", "15.5",
                  {0.0: "50.0", 50.0: "60.0", 100.0: "70.0"})
    tables = {"Body Weight": {"Male": [male], "Female": [female]}}

    out = _build_body_weight_paragraphs(tables, "PFHxSAm", "mg/kg/day")
    assert out == [
        "Terminal body weight was significantly decreased in male rats at ≥50 "
        "mg/kg/day with a negative trend (Table 2). The BMD and BMDL were 41.2 "
        "and 22.8 mg/kg/day, respectively. Terminal body weight was significantly "
        "increased in female rats with a positive trend (Table 2). The BMD and "
        "BMDL were 30.0 and 15.5 mg/kg/day, respectively."
    ]


def test_all_non_significant_combined_sentence():
    male = _row("Terminal Body Wt.", "ND", "ND", {0.0: "100.0"}, resp=False)
    female = _row("Terminal Body Wt.", "ND", "ND", {0.0: "100.0"}, resp=False)
    tables = {"Body Weight": {"Male": [male], "Female": [female]}}

    out = _build_body_weight_paragraphs(tables, "PFHxSAm", "mg/kg/day")
    assert out == [
        "No significant changes in terminal body weight for male rats (Table 2) "
        "or female rats (Table 2) occurred with exposure to PFHxSAm."
    ]


def test_no_body_weight_platform_returns_empty():
    assert _build_body_weight_paragraphs({}, "PFHxSAm", "mg/kg/day") == []
