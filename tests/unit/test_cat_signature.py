"""
Unit tests for the Phase 3b categorical signature + flip detection.

A programmatic finding's data-derived WORDS (direction/trend) are projected into a
compact `cat_signature` carried on the section card, so a later reprocess can flag a
FLIP against an approved section (wording-review inform-signal). These tests pin:
  - the signature captures ONLY categorical values, keyed by finding identity;
  - it mirrors the narrative builders' filtering (significant findings only);
  - the narrative prose is UNCHANGED by the additive projection;
  - cat_signature_flips diffs two signatures correctly.
"""

from bmdx_pipe import TableRow

from narrative.unified_narrative import (
    apical_cat_signature,
    clinical_pathology_cat_signature,
    generate_platform_narrative,
    platform_cat_signature,
)
from workflow.reprocess import cat_signature_flips

UNIT = "mg/kg"


def _row(label, bmd="ND", bmdl="ND", vals=None, resp=True):
    return TableRow(
        label=label, values_by_dose=vals or {}, n_by_dose={}, bmd_str=bmd,
        bmdl_str=bmdl, trend_marker="", bmd_status="", loel=None, noel=None,
        direction=None, responsive=resp, missing_animals_by_dose={},
    )


# Decreasing body weight (control 100 → high 70): direction "decrease".
def _bw_decreasing():
    return _row("Terminal Body Wt.", "41.2", "22.8",
                {0.0: "100.0", 50.0: "85.0*", 100.0: "70.0**"})


# Increasing body weight (control 70 → high 100): direction "increase".
def _bw_increasing():
    return _row("Terminal Body Wt.", "41.2", "22.8",
                {0.0: "70.0", 50.0: "85.0*", 100.0: "100.0**"})


# --- apical_cat_signature ---------------------------------------------------

def test_body_weight_signature_captures_direction_and_trend():
    sig = apical_cat_signature({"Body Weight": {"Male": [_bw_decreasing()]}}, UNIT)
    assert sig == {"Male|Terminal Body Wt.": {"direction": "decreased", "trend": "negative"}}


def test_signature_excludes_numeric_slots():
    sig = apical_cat_signature({"Body Weight": {"Male": [_bw_decreasing()]}}, UNIT)
    vals = sig["Male|Terminal Body Wt."]
    # No bmd/bmdl/loel/unit — those are silent-refresh-safe magnitudes.
    assert set(vals) == {"direction", "trend"}


def test_signature_skips_non_significant_findings():
    # ND / non-responsive rows are not templated in the prose → not in the signature.
    nd = _row("Terminal Body Wt.", "ND", "ND",
              {0.0: "100.0", 100.0: "70.0"}, resp=False)
    sig = apical_cat_signature({"Body Weight": {"Male": [nd]}}, UNIT)
    assert sig == {}


def test_organ_signature_keyed_by_organ_name():
    liver = _row("Liver Absolute", "12.5", "6.3",
                 {0.0: "5.0", 50.0: "7.0*", 100.0: "9.0**"})
    sig = apical_cat_signature({"Organ Weight": {"Male": [liver]}}, UNIT)
    assert "Male|Liver" in sig
    assert sig["Male|Liver"]["direction_adj"] == "increased"
    assert sig["Male|Liver"]["trend"] == "positive"


def test_clinical_pathology_signature_keyed_by_subplatform():
    alt = _row("ALT", "45.0", "30.0",
               {0.0: "20.0", 50.0: "25.0*", 100.0: "30.0**"})
    sig = clinical_pathology_cat_signature(
        {"Clinical Chemistry": {"Male": [alt]}}, UNIT)
    assert sig == {
        "Clinical Chemistry|Male|ALT": {"direction": "increased", "trend": "positive"}
    }


# --- platform_cat_signature dispatch (per-card) -----------------------------

def test_platform_signature_dispatches_like_narrative():
    bw = {"Male": [_bw_decreasing()]}
    assert platform_cat_signature("Body Weight", bw, UNIT) == {
        "Male|Terminal Body Wt.": {"direction": "decreased", "trend": "negative"}
    }
    assert platform_cat_signature("Body Weight", {}, UNIT) == {}


# --- the additive projection does not perturb the prose ---------------------

def test_narrative_prose_unchanged_by_signature():
    # The same rows through the prose builder produce the same prose regardless of
    # the signature pass (they are independent projections over the same data).
    bw = {"Male": [_bw_decreasing()]}
    before = generate_platform_narrative("Body Weight", bw, "PFHxSAm", UNIT)
    _ = platform_cat_signature("Body Weight", bw, UNIT)
    after = generate_platform_narrative("Body Weight", bw, "PFHxSAm", UNIT)
    assert before == after
    assert "decreased" in before[0]


# --- cat_signature_flips ----------------------------------------------------

def test_flips_detects_direction_change():
    old = apical_cat_signature({"Body Weight": {"Male": [_bw_decreasing()]}}, UNIT)
    new = apical_cat_signature({"Body Weight": {"Male": [_bw_increasing()]}}, UNIT)
    flips = cat_signature_flips(old, new)
    assert flips == [
        "Male|Terminal Body Wt..direction", "Male|Terminal Body Wt..trend"
    ]


def test_flips_empty_when_identical():
    sig = apical_cat_signature({"Body Weight": {"Male": [_bw_decreasing()]}}, UNIT)
    assert cat_signature_flips(sig, sig) == []


def test_flips_fail_safe_on_missing_side():
    sig = apical_cat_signature({"Body Weight": {"Male": [_bw_decreasing()]}}, UNIT)
    assert cat_signature_flips(None, sig) == []
    assert cat_signature_flips(sig, None) == []
    assert cat_signature_flips({}, sig) == []


def test_flips_ignores_appeared_finding():
    # A finding present only in `new` is a structural change (prose rebuilt), not a
    # wording contradiction under stable structure → no flip.
    old = {"Male|A": {"direction": "increased"}}
    new = {"Male|A": {"direction": "increased"}, "Male|B": {"direction": "decreased"}}
    assert cat_signature_flips(old, new) == []
