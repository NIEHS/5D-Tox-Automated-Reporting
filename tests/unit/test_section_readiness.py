"""
Characterization test for workflow.section_readiness (Phase 1).

This is the GATE proving the DERIVED `derive_section_readiness` reproduces the
existing imperative JS dependency behavior before the browser cutover. The JS
rules were extracted from every call site that sets `ready.methods` /
`ready.summary`:

  * showMethodsSection() — background approve (background.js:302), restore when
    background approved OR ≥1 apical result exists (chemical.js:471), after
    process-integrated (pipeline.js:597).
  * showSummarySection() — background approve (background.js:305), genomics
    generation (genomics.js:209), restore when background approved
    (chemical.js:598), after process-integrated (pipeline.js:598).

Collapsed to their derived (approval-driven) form both unlock on the SAME
condition: `background approved OR ≥1 result section (bm2_*/genomics_*) approved`.
The table below encodes that as (approved-set → sections that must be enabled).

NOTE (flagged for review): the JS also unlocks Methods/Summary on the
pipeline-processed path regardless of approvals. That path is a data event, not
an approval, and Phase 1 derives readiness from the APPROVED-set only; the
approval-driven union is faithfully reproduced here. See the module docstring's
ambiguity note.
"""

import pytest

from workflow.section_readiness import derive_section_readiness


# --- Characterization table: (approved section_keys) → expected enabled set ---
#
# Only Methods and Summary have dependencies; everything else is always enabled.
# Each row lists the sections that are APPROVED and asserts whether methods /
# summary are enabled. "results" = any bm2_* or genomics_* approved.
# ★ SUMMARY is approval-gated (it synthesizes APPROVED sections): unlocks on
# `background approved OR ≥1 result approved`. METHODS is NO LONGER approval-gated —
# it unlocks on the `processed` resource (see the separate methods tests below), so
# these cases pass resources={} (unprocessed) to isolate the SUMMARY approval rule.
_SUMMARY_CASES = [
    # (label, approved_keys, summary_enabled)
    ("nothing approved",                     set(),                                 False),
    ("only background approved",             {"background"},                        True),
    ("one apical result approved",           {"bm2_organ-and-body-weights"},        True),
    ("one genomics result approved",         {"genomics_liver_male"},               True),
    ("bmd_summary approved (not a result)",  {"bmd_summary"},                       False),
    ("summary approved but nothing else",    {"summary"},                           False),
    ("background + result approved",         {"background", "bm2_clinical-path"},   True),
    ("result present but NOT approved",      set(),                                 False),
]


@pytest.mark.parametrize(
    "label,approved,summary_enabled",
    [(c[0], c[1], c[2]) for c in _SUMMARY_CASES],
)
def test_summary_readiness_approval_gated(label, approved, summary_enabled):
    # section_states maps key → approved bool. Summary synthesizes approved content,
    # so it stays approval-gated.
    section_states = {k: True for k in approved}
    readiness = derive_section_readiness(section_states)
    assert readiness["summary"]["enabled"] is summary_enabled, f"summary, case: {label}"


def test_methods_gated_on_processed_not_approval():
    # ★ M&M unlocks on the `processed` resource (study metadata exists post-Process),
    # NOT on any approval. Corrected from the ambiguous JS port (ADR-0018).
    # Unprocessed → blocked regardless of approvals:
    r = derive_section_readiness({"background": True}, resources={"processed": False})
    assert r["methods"]["enabled"] is False
    assert r["methods"]["blocked_by"] == ["processed"]
    # Processed → enabled even with nothing approved:
    r2 = derive_section_readiness({}, resources={"processed": True})
    assert r2["methods"]["enabled"] is True
    assert r2["methods"]["blocked_by"] == []


def test_unconditional_sections_always_enabled():
    # background / bmd_summary / result instances have no approval dependency.
    r = derive_section_readiness({})
    assert r["background"]["enabled"] is True
    assert r["bmd_summary"]["enabled"] is True
    # A present-but-unapproved result instance is still "enabled" (it is gated by
    # its data existing, not by another approval) — mirrors the JS, which shows
    # result cards as soon as the pipeline produces them.
    r2 = derive_section_readiness({"bm2_liver": False})
    assert r2["bm2_liver"]["enabled"] is True
    assert r2["bm2_liver"]["approved"] is False


def test_blocked_by_lists_unlock_groups():
    # When Summary is blocked, either approval group would unblock it (OR).
    r = derive_section_readiness({})
    assert r["summary"]["blocked_by"] == ["background", "results"]
    # Methods is blocked by the processed resource when unprocessed.
    assert r["methods"]["blocked_by"] == ["processed"]
    # Enabled → empty blocked_by.
    r2 = derive_section_readiness({"background": True}, resources={"processed": True})
    assert r2["summary"]["blocked_by"] == []
    assert r2["methods"]["blocked_by"] == []


def test_unapproved_background_does_not_unlock():
    # A background section that exists on disk but is NOT approved must not
    # unlock methods/summary — approval, not mere presence, is the trigger.
    r = derive_section_readiness({"background": False})
    assert r["methods"]["enabled"] is False
    assert r["summary"]["enabled"] is False
    assert r["background"]["approved"] is False


def test_singletons_always_present_in_map():
    r = derive_section_readiness({})
    for key in ("background", "methods", "bmd_summary", "summary"):
        assert key in r
        assert set(r[key].keys()) == {"enabled", "blocked_by", "approved"}


def test_instance_sections_surface_when_on_disk():
    r = derive_section_readiness(
        {"bm2_liver": True, "genomics_kidney_female": False}
    )
    assert r["bm2_liver"]["approved"] is True
    assert r["genomics_kidney_female"]["approved"] is False
    # Both count toward the readiness universe.
    assert "bm2_liver" in r and "genomics_kidney_female" in r


def test_summary_is_pure_function_of_approved_set():
    # Two different section_states with the same APPROVED subset yield the same
    # SUMMARY verdict — the approval-gated rule derives from approvals, nothing else.
    a = derive_section_readiness({"background": True, "methods": False})
    b = derive_section_readiness({"background": True, "summary": False})
    assert a["summary"]["enabled"] == b["summary"]["enabled"] is True


# --- KB resource gate: genomics interpretation is grounded in the knowledge graph
#     (bmdx.duckdb), so genomics sections are gated on the knowledge_base resource.


def test_genomics_gated_on_knowledge_base_present():
    # With the KB present, a genomics instance is enabled.
    r = derive_section_readiness(
        {"genomics_liver_male": False}, resources={"knowledge_base": True}
    )
    assert r["genomics_liver_male"]["enabled"] is True
    assert r["genomics_liver_male"]["blocked_by"] == []


def test_genomics_blocked_when_knowledge_base_absent():
    # With the KB absent, genomics sections are blocked — the per-section KB gate.
    r = derive_section_readiness(
        {"genomics_liver_male": False}, resources={"knowledge_base": False}
    )
    assert r["genomics_liver_male"]["enabled"] is False
    assert r["genomics_liver_male"]["blocked_by"] == ["knowledge_base"]


def test_apical_result_not_kb_gated():
    # Only genomics (interpretation-bearing) sections need the KB; apical bm2
    # results do not — they carry no graph-grounded references.
    r = derive_section_readiness(
        {"bm2_liver": False}, resources={"knowledge_base": False}
    )
    assert r["bm2_liver"]["enabled"] is True


def test_resources_default_absent_gates_genomics():
    # Omitting resources means no external groups are satisfied → genomics blocked.
    # (Callers that care about genomics MUST pass resources; the engine does.)
    r = derive_section_readiness({"genomics_liver_male": False})
    assert r["genomics_liver_male"]["enabled"] is False


# --- Catalog-seeded universe (section-catalog seam) --------------------------
#
# When the engine passes the tree-derived catalog, its NON-family keys (the
# singletons + the programmatic group narratives that had no row before) join the
# readiness universe even with nothing on disk. The default (no-catalog) path above
# is unchanged — these cases pin the seeded path.


def test_catalog_seeds_group_narratives_into_the_universe():
    from workflow.section_catalog import catalog_for_tree
    from document_model.document_tree import DOCUMENT_TREE

    catalog = catalog_for_tree(DOCUMENT_TREE)
    r = derive_section_readiness(
        {}, resources={"processed": False}, catalog=catalog
    )
    # internal_dose (and its siblings) now appear — the headline seam.
    for key in ("internal_dose", "animal_condition", "clinical_pathology"):
        assert key in r
        assert r[key]["enabled"] is True
        assert r[key]["blocked_by"] == []


def test_catalog_does_not_change_existing_singleton_rules():
    from workflow.section_catalog import catalog_for_tree
    from document_model.document_tree import DOCUMENT_TREE

    catalog = catalog_for_tree(DOCUMENT_TREE)
    r = derive_section_readiness(
        {}, resources={"processed": False}, catalog=catalog
    )
    # The 12-key contract's singletons keep their prior verdicts.
    assert r["background"]["enabled"] is True
    assert r["bmd_summary"]["enabled"] is True
    assert r["methods"]["enabled"] is False and r["methods"]["blocked_by"] == ["processed"]
    assert r["summary"]["enabled"] is False


def test_catalog_families_are_not_seeded_as_bare_keys():
    # Family specs (bm2, genomics) must NOT leak into readiness as bare keys —
    # only their concrete on-disk instances do (still via section_states).
    from workflow.section_catalog import catalog_for_tree
    from document_model.document_tree import DOCUMENT_TREE

    catalog = catalog_for_tree(DOCUMENT_TREE)
    r = derive_section_readiness({}, catalog=catalog)
    assert "bm2" not in r
    assert "genomics" not in r
