"""
workflow.content_origin — is a report section's content LLM-authored or
programmatically generated? (Phase 0 of the integrated-wizard work; design in
memory project_integrated_wizard_versioned_preview.md.)

This is the single read point the currency logic needs. On a data reprocess the
two origins get DIFFERENT treatment (design Decision 2):

  * PROGRAMMATIC — deterministic projection of data (apical result prose built
    from TableRow by narrative.unified_narrative). Numbers auto-refresh; the
    author's wording survives (Phase 2 templates). No re-blessing needed for a
    numeric-only change.
  * LLM — narrative synthesized by a model (Background, Materials & Methods,
    Summary, genomics interpretation, apical-BMD narrative). A reprocess REWRITES
    it, but visibly + attributed, and it must be re-accepted before the report
    can publish (currency BLOCK).

Deliberately keyed by the canonical section vocabulary (the SAME set
web_routes.session_routes._resolve_section_key maps), NOT hardcoded in
pool_state. Phase 3 (reprocess router) and Phase 4 (publish gate) both consult
this; keeping it here in the UI-agnostic core means one source of truth.

Origin is a property of the section KIND, not of any particular session's data —
so it is a static table, verified by test, not something derived per-session.
"""

from __future__ import annotations

import enum


class ContentOrigin(str, enum.Enum):
    """How a section's content came to exist."""

    LLM = "llm"                    # model-authored narrative
    PROGRAMMATIC = "programmatic"  # rule-based prose from structured data


# The canonical section-type vocabulary → origin. Mirrors the section_type
# strings in session_routes._resolve_section_key:
#   background / methods / bmd_summary / summary / bm2 / genomics
_ORIGIN_BY_SECTION_TYPE: dict[str, ContentOrigin] = {
    "background": ContentOrigin.LLM,      # background_writer LLM
    "methods": ContentOrigin.LLM,         # methods_report LLM
    "summary": ContentOrigin.LLM,         # LLM synthesis of approved sections
    "bmd_summary": ContentOrigin.LLM,     # apical-BMD narrative (LLM, content-addressed)
    "genomics": ContentOrigin.LLM,        # interpret.py genomics interpretation
    "bm2": ContentOrigin.PROGRAMMATIC,    # unified_narrative apical result prose
}


def origin_for_section_type(section_type: str) -> ContentOrigin | None:
    """Origin for a canonical section_type, or None if unknown.

    None (not a guess) for an unrecognized type so callers can decide how to
    treat the unknown — the currency path should fail safe (treat unknown as LLM
    = the more conservative "needs re-bless") rather than silently auto-updating
    content it can't classify.
    """
    return _ORIGIN_BY_SECTION_TYPE.get(section_type)


def origin_for_section_key(section_key: str) -> ContentOrigin | None:
    """Origin for an ON-DISK section_key (what save_section writes).

    Keys are either a bare type (`background`, `methods`, `bmd_summary`,
    `summary`) or a prefixed instance (`bm2_<slug>`, `genomics_<organ>_<sex>`).
    Resolves the instance forms to their type, then defers to
    origin_for_section_type. None for an unrecognized key.
    """
    if section_key in _ORIGIN_BY_SECTION_TYPE:
        return _ORIGIN_BY_SECTION_TYPE[section_key]
    if section_key.startswith("bm2_"):
        return ContentOrigin.PROGRAMMATIC
    if section_key.startswith("genomics_"):
        return ContentOrigin.LLM
    return None


def is_llm_section(section_key: str) -> bool:
    """Whether a section_key names LLM-authored content.

    Fail-safe: an UNKNOWN key is treated as LLM (True) — the conservative choice
    for the currency path, which must not silently auto-update content whose
    origin it cannot establish.
    """
    return origin_for_section_key(section_key) is not ContentOrigin.PROGRAMMATIC
