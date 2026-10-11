"""
Coherence gate for generate_platform_narrative — the per-platform templated
entry that replaced bmdx_pipe.generate_results_narrative (Increment A1a).

Prose structure follows the NIEHS reference (via the shared _build_* builders);
these assertions check that each platform routes to the right builder and that
the prose CITES the correct data (BMD/BMDL strings, dose, direction), NOT that
the wording byte-matches the retired twin.
"""

from bmdx_pipe import TableRow

from narrative.unified_narrative import generate_platform_narrative


def _row(label, bmd="ND", bmdl="ND", vals=None, resp=True):
    return TableRow(
        label=label, values_by_dose=vals or {}, n_by_dose={}, bmd_str=bmd,
        bmdl_str=bmdl, trend_marker="", bmd_status="", loel=None, noel=None,
        direction=None, responsive=resp, missing_animals_by_dose={},
    )


UNIT = "mg/kg"
CN = "PFHxSAm"


def test_empty_returns_empty():
    assert generate_platform_narrative("Body Weight", {}, CN, UNIT) == []
    assert generate_platform_narrative(None, {}, CN, UNIT) == []


def test_body_weight_platform_produces_body_weight_prose():
    bw = _row("Terminal Body Wt.", "41.2", "22.8",
              {0.0: "100.0", 50.0: "85.0*", 100.0: "70.0**"})
    out = generate_platform_narrative("Body Weight", {"Male": [bw]}, CN, UNIT)
    assert len(out) == 1
    para = out[0]
    assert "Terminal body weight" in para
    # Cites the right numbers, direction, and LOEL dose.
    assert "41.2" in para and "22.8" in para
    assert "decreased" in para
    assert "50" in para


def test_organ_weight_platform_produces_organ_prose():
    liver_abs = _row("Liver Absolute", "12.5", "6.3",
                     {0.0: "5.0", 50.0: "7.0*", 100.0: "9.0**"})
    out = generate_platform_narrative("Organ Weight", {"Male": [liver_abs]}, CN, UNIT)
    assert len(out) == 1
    para = out[0]
    assert "Liver" in para
    assert "12.5" in para and "6.3" in para
    assert "increase" in para  # "a significant increase in Liver ..."


def test_clinical_sub_platform_produces_sub_platform_prose():
    alt = _row("Alanine aminotransferase", "45.0", "30.0",
               {0.0: "20.0", 50.0: "25.0*", 100.0: "30.0**"})
    out = generate_platform_narrative(
        "Clinical Chemistry", {"Male": [alt]}, CN, UNIT)
    assert len(out) == 1
    para = out[0]
    assert "Alanine aminotransferase was significantly increased" in para
    assert "45.0" in para and "30.0" in para


def test_unknown_platform_auto_detects_body_then_organ():
    # A mixed bm2 card: body-weight + organ rows, no clean platform string.
    bw = _row("Terminal Body Wt.", "41.2", "22.8",
              {0.0: "100.0", 50.0: "85.0*", 100.0: "70.0**"})
    liver_abs = _row("Liver Absolute", "12.5", "6.3",
                     {0.0: "5.0", 50.0: "7.0*", 100.0: "9.0**"})
    out = generate_platform_narrative(None, {"Male": [bw, liver_abs]}, CN, UNIT)
    joined = "\n".join(out)
    # Both the body-weight and organ findings surface, in that order.
    assert "Terminal body weight" in joined
    assert "Liver" in joined
    assert out[0].startswith("Terminal body weight")
    # Data from both endpoints is cited.
    assert "41.2" in joined and "12.5" in joined


def test_unknown_platform_falls_back_to_generic_for_endpoint_rows():
    # Endpoint-type rows with no clean platform still yield prose via the
    # organ-weight builder's endpoint branch (mirrors the old twin auto-detect).
    glucose = _row("Glucose", "60.0", "40.0",
                   {0.0: "100.0", 50.0: "90.0*", 100.0: "80.0**"})
    out = generate_platform_narrative(None, {"Male": [glucose]}, CN, UNIT)
    joined = "\n".join(out)
    assert "Glucose" in joined
    assert "60.0" in joined and "40.0" in joined
