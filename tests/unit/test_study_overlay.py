"""Study selections live in the study's overlay, not the shared template.

The shared template carried NIEHS-10's choices (Table 3 liver-only and
male-only; hand-picked "Select" clinical-pathology endpoints), so a
female-only study (NIEHS-13) got an empty Table 3.  They now live in
templates/studies/DTXSID50469320/view.yaml; the template selects nothing.
"""

from document_model.document_template import load_report_filters, normalize_filters_block
from document_model.document_tree import ACTIVE_TEMPLATE
from document_model.view_config import load_study_view, resolve_view_filters

_NIEHS10 = {
    "organs": {"genomics": ["liver", "kidney"], "organ-weight": ["liver"]},
    "sex": {"organ-weight": ["male"]},
    "assays": {
        "clinical-chemistry": {"male": ["cholesterol"],
                               "female": ["aspartate aminotransferase", "sorbitol dehydrogenase"]},
        "hematology": {"male": ["neutrophil count"], "female": ["manual hematocrit"]},
        "hormones": {"male": ["triiodothyronine", "total thyroxine"],
                     "female": ["total thyroxine"]},
    },
}


def test_shared_template_selects_nothing():
    assert load_report_filters(ACTIVE_TEMPLATE)["filters"] == {}


def test_a_session_view_wins_over_the_overlay(sessions_dir):
    from document_model.view_config import save_view

    save_view("DTXSID50469320", "default", {"filters": {}})
    assert resolve_view_filters("DTXSID50469320", "default")["filters"] == {}


def test_niehs10_overlay_keeps_its_published_selections(sessions_dir):
    # sessions_dir isolates the run from any saved session view (which would
    # win over the overlay by design).
    assert load_study_view("DTXSID50469320")["filters"] == normalize_filters_block(_NIEHS10)
    resolved = resolve_view_filters("DTXSID50469320", "default")
    assert resolved["filters"] == normalize_filters_block(_NIEHS10)
    # The overlay sets no charts: the report type's setting applies.
    assert resolved["charts"] == load_report_filters(ACTIVE_TEMPLATE)["charts"]


def test_a_study_without_an_overlay_is_reported_in_full(sessions_dir):
    assert resolve_view_filters("DTXSID1020431", "default")["filters"] == {}
