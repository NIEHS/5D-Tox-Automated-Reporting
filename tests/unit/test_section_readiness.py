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
_CASES = [
    # (label, approved_keys, methods_enabled, summary_enabled)
    ("nothing approved",                     set(),                                 False, False),
    ("only background approved",             {"background"},                        True,  True),
    ("one apical result approved",           {"bm2_organ-and-body-weights"},        True,  True),
    ("one genomics result approved",         {"genomics_liver_male"},               True,  True),
    ("bmd_summary approved (not a result)",  {"bmd_summary"},                       False, False),
    ("methods approved but nothing else",    {"methods"},                           False, False),
    ("background + result approved",         {"background", "bm2_clinical-path"},   True,  True),
    ("result present but NOT approved",      set(),                                 False, False),
]


@pytest.mark.parametrize(
    "label,approved,methods_enabled,summary_enabled",
    [(c[0], c[1], c[2], c[3]) for c in _CASES],
)
def test_methods_summary_readiness_matches_js(label, approved, methods_enabled, summary_enabled):
    # section_states maps key → approved bool. Include the approved keys as
    # True; that is all derive_section_readiness needs.
    section_states = {k: True for k in approved}
    readiness = derive_section_readiness(section_states)

    assert readiness["methods"]["enabled"] is methods_enabled, f"methods, case: {label}"
    assert readiness["summary"]["enabled"] is summary_enabled, f"summary, case: {label}"


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


def test_blocked_by_lists_both_unlock_groups():
    # When Methods/Summary are blocked, either group would unblock them (OR).
    r = derive_section_readiness({})
    assert r["methods"]["blocked_by"] == ["background", "results"]
    assert r["summary"]["blocked_by"] == ["background", "results"]
    # Enabled → empty blocked_by.
    r2 = derive_section_readiness({"background": True})
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


def test_readiness_is_pure_function_of_approved_set():
    # Two different section_states with the same APPROVED subset yield the same
    # methods/summary verdict — readiness derives from approvals, nothing else.
    a = derive_section_readiness({"background": True, "methods": False})
    b = derive_section_readiness({"background": True, "summary": False})
    assert a["methods"]["enabled"] == b["methods"]["enabled"] is True
