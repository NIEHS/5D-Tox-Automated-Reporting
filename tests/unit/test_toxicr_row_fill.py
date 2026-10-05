"""ToxicR fills land on the NTP rows, so every surface shows the same BMD.

fill_rows_from_toxicr writes a viable ToxicR fit onto a BMD-candidate row that
has no usable bm2 BMD (before the section tables, narratives and BMD summary
are built); the summary keeps the fill's provenance, the bm2 cross-check skips
it, and the rendered summary footnotes a fill made at an inferred BMR.
"""

from bmdx_pipe import TableRow

from document_model.document_node import DocNode
from pipeline.processing_helpers import _build_apical_bmd_summary, fill_rows_from_toxicr
from rendering.render_common import BMD_SUMMARY_LEGEND, bmd_summary_plan

_TOX = {"Male::Liver": {"bmd": 62.976, "bmdl": 15.978, "status": "viable",
                        "model_name": "Exp 3", "bmr_config": "inferred",
                        "bmr": {"type": "SD", "factor": 1.0}},
        "Male::Kidney-Left": {"bmd": 300.0, "bmdl": 100.0, "status": "viable",
                              "bmr_config": "inferred"}}


def _row(label, bmd="—", status=None, responsive=True):
    return TableRow(label=label, bmd_str=bmd, bmdl_str=bmd, bmd_status=status,
                    loel=250.0, noel=125.0, direction="UP", responsive=responsive)


def test_fills_a_responsive_bm2_blank_row():
    liver = _row("Liver")
    assert fill_rows_from_toxicr({"Organ Weight": {"Male": [liver]}}, _TOX) == 1
    assert (liver.bmd_str, liver.bmdl_str, liver.bmd_status) == ("63", "16", "viable")
    assert liver._bmd_fill["bmr_config"] == "inferred"


def test_leaves_bm2_values_and_non_candidates_alone():
    kept = _row("Liver", bmd="55.1", status="viable")
    quiet = _row("Kidney-Left", responsive=False)
    assert fill_rows_from_toxicr({"Organ Weight": {"Male": [kept, quiet]}}, _TOX) == 0
    assert kept.bmd_str == "55.1" and quiet.bmd_str == "—"


def test_inferred_bmr_falls_back_to_the_assay_family_default():
    # A cached fit from before the BMR was stamped on results.
    kidney = _row("Kidney-Left")
    fill_rows_from_toxicr({"Organ Weight": {"Male": [kidney]}}, _TOX)
    assert kidney._bmd_fill["bmr"] == {"type": "SD", "factor": 1.0}


def test_summary_carries_provenance_and_skips_the_bm2_cross_check():
    tables = {"Organ Weight": {"Male": [_row("Liver")]}}
    fill_rows_from_toxicr(tables, _TOX)
    divergences: list = []
    entry = _build_apical_bmd_summary(tables, bmds_results=_TOX, divergences=divergences)[0]
    assert entry["bmd"] == "63" and entry["source"] == "toxicr" and entry["filled"]
    assert entry["validated"] is None and divergences == []
    # The filter-agnostic cache (no bmds_results) has the same value.
    assert _build_apical_bmd_summary(tables)[0]["bmd"] == "63"


def test_rendered_summary_footnotes_inferred_bmr():
    tables = {"Organ Weight": {"Male": [_row("Liver")]}}
    fill_rows_from_toxicr(tables, _TOX)
    endpoints = _build_apical_bmd_summary(tables)
    node = DocNode(id="bmd-summary", title="BMD Summary", node_type="bmd-summary")
    plan = bmd_summary_plan(node, {"bmd_summary": {"endpoints": endpoints}})
    texts = [f["text"] for f in plan.footnotes]
    assert texts[0] == BMD_SUMMARY_LEGEND
    assert "Absolute Liver Weight (male): benchmark response of 1 standard deviation" in texts[1]


def test_no_inferred_note_for_bm2_values():
    endpoints = _build_apical_bmd_summary(
        {"Organ Weight": {"Male": [_row("Liver", bmd="55.1", status="viable")]}})
    node = DocNode(id="bmd-summary", title="BMD Summary", node_type="bmd-summary")
    plan = bmd_summary_plan(node, {"bmd_summary": {"endpoints": endpoints}})
    assert [f["text"] for f in plan.footnotes] == [BMD_SUMMARY_LEGEND]


def test_responsive_row_bmdexpress_never_modeled_takes_toxicr_nvm():
    sdh = _row("Sorbitol dehydrogenase")
    tox = {"Male::Sorbitol dehydrogenase": {"bmd": None, "bmdl": None, "status": "NVM",
                                            "bmr_config": "inferred"}}
    assert fill_rows_from_toxicr({"Clinical Chemistry": {"Male": [sdh]}}, tox) == 1
    assert (sdh.bmd_str, sdh.bmdl_str, sdh.bmd_status) == ("NVM", "NVM", "NVM")
    # NVM is not a fitted value, so the inferred-BMR note does not name it.
    endpoints = _build_apical_bmd_summary({"Clinical Chemistry": {"Male": [sdh]}})
    node = DocNode(id="bmd-summary", title="BMD Summary", node_type="bmd-summary")
    plan = bmd_summary_plan(node, {"bmd_summary": {"endpoints": endpoints}})
    assert endpoints[0]["bmd"] == "NVM" and len(plan.footnotes) == 1
