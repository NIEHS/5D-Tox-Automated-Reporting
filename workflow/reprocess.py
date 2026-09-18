"""
workflow.reprocess — the pure decision layer for how a data reprocess treats each
report section (Phase 3a; design in project_integrated_wizard_versioned_preview.md
Decision 2 + docs/plans/phase3-reprocess-currency.md).

Today `pipeline.pool_state.invalidate_pool_artifacts` marks EVERY section
`stale=True` uniformly when the file pool changes. That is too blunt: the response
to new data must depend on how the section's content was authored (workflow.
content_origin):

  * PROGRAMMATIC (bm2_*) — a deterministic projection of data. Its numbers just
    refresh on the next render (Phase 2 templates); there is no LLM/human judgement
    to protect, so it must NOT be staled/blocked. -> REFRESH_NUMBERS.
  * LLM (genomics_*, background, methods, summary, bmd_summary) — model-authored
    narrative the human blessed. On new data it must be REWRITTEN, but visibly and
    attributed, and knocked below approved so a human re-accepts before publish
    (currency BLOCK). -> REWRITE_LLM.

This module is PURE — no disk, no HTTP. It decides; pool_state acts on the
decision. Kept separate so the decision is unit-testable in isolation and the two
consumers (the reprocess rewire in pool_state, Phase 3a task 2; the publish gate,
task 3) share one source of truth.

Phase 3b (deferred) adds REFRESH_WITH_WORDING_REVIEW: when a programmatic section
carries author wording edits AND a reprocess flips a CATEGORICAL slot
(section_template.categorical_flips), the numeric refresh is safe but the flipped
word may contradict the author's wording. That needs the section to persist its
template + last binding, which it does not today — so this layer emits only the
four actions below now; the fifth arrives with the persistence in 3b.
"""

from __future__ import annotations

import enum

from workflow.content_origin import ContentOrigin, origin_for_section_key


class ReprocessAction(str, enum.Enum):
    """What a data reprocess should do to one section's content."""

    REFRESH_NUMBERS = "refresh_numbers"  # programmatic: re-render, do NOT stale
    REWRITE_LLM = "rewrite_llm"          # LLM: rewrite-with-reason + demote (BLOCK)
    LEAVE = "leave"                      # no content to act on (missing/empty)


def classify_section_reprocess(
    section_key: str, section: "dict | None"
) -> ReprocessAction:
    """Decide how a reprocess treats `section_key`. Pure.

    LEAVE when there is no content dict to act on (a missing/empty section — the
    reprocess has nothing to refresh or rewrite). Otherwise route by content
    origin: PROGRAMMATIC -> REFRESH_NUMBERS, everything else -> REWRITE_LLM.

    Fail-safe: an UNKNOWN section_key routes to REWRITE_LLM, because
    origin_for_section_key returns None for it and is_llm-style handling treats the
    unclassifiable case as LLM — the conservative choice (never silently
    auto-refresh content we cannot establish is a pure data projection). Mirrors
    content_origin's own fail-safe.
    """
    if not isinstance(section, dict) or not section:
        return ReprocessAction.LEAVE
    origin = origin_for_section_key(section_key)
    if origin is ContentOrigin.PROGRAMMATIC:
        return ReprocessAction.REFRESH_NUMBERS
    # LLM origin AND the unknown/None fail-safe both land here.
    return ReprocessAction.REWRITE_LLM


def should_stale_on_reprocess(section_key: str, section: "dict | None") -> bool:
    """Whether `invalidate_pool_artifacts` should mark this section stale.

    The blunt current behavior stales everything; Phase 3a narrows it: only
    sections whose reprocess action is REWRITE_LLM are staled (they carry a claim
    that new data may invalidate and must be re-blessed). Programmatic sections
    (REFRESH_NUMBERS) are NOT staled — their numbers just refresh. LEAVE (no
    content) is not staled — there is nothing to flag.

    This is the single predicate the pool_state rewire consults, so the
    behavior-change is defined in ONE place and pinned by one characterization
    test.
    """
    return classify_section_reprocess(section_key, section) is ReprocessAction.REWRITE_LLM


# ---------------------------------------------------------------------------
# Report-grain publish gate (the currency BLOCK at report scope).
# ---------------------------------------------------------------------------

def blocking_llm_sections(sections: "dict[str, dict | None]") -> list[str]:
    """The LLM section keys that BLOCK publishing — stale + not yet re-accepted.

    A section blocks when it is an LLM section (REWRITE_LLM origin) AND still
    carries the `stale` flag a reprocess set. Re-acceptance is the human re-approve
    (Phase 1 accept_section_step), which clears `stale` — so a re-blessed section
    no longer blocks even though it was rewritten. Programmatic sections never
    block (their numbers just refresh; no claim to re-bless).

    `sections` maps section_key -> the section dict (as read from disk). Returns
    the sorted list of blocking keys (empty = publishable).
    """
    blocking: list[str] = []
    for key, section in sections.items():
        if classify_section_reprocess(key, section) is not ReprocessAction.REWRITE_LLM:
            continue
        if isinstance(section, dict) and section.get("stale"):
            blocking.append(key)
    return sorted(blocking)


def can_publish_report(sections: "dict[str, dict | None]") -> bool:
    """May the report be published right now? (report-grain currency BLOCK.)

    False iff any LLM section is stale-and-unaccepted (see blocking_llm_sections).
    This is the report-scope lift of workflow.currency.can_advance: publishing a
    report whose LLM conclusions are stale asserts a falsehood, so it is BLOCKED
    (a correctness invariant, not a courtesy) until a human re-blesses each stale
    LLM section. Empty/all-fresh -> True.
    """
    return not blocking_llm_sections(sections)
