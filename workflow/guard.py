"""
workflow.guard — the DERIVED edit-hardness layer (ADR-0015).

The concept model splits label handling into two layers:

  * FACTS (workflow.labels) — what humans assert (`final`, `protected`,
    `published`, `approved`). Independently settable, human-meaningful.
  * GUARD (this module) — the single CONSEQUENCE those facts point at: "how hard
    is this to edit, and by whom." DERIVED, never stored.

Why derived-never-stored (same discipline as CONTEXT.md invariant 3): clearing
`protected` must drop the guard ONLY if `final` isn't also holding it up. That
falls out for free from recomputing `max` over the live facts; a stored `guarded`
boolean would get the clear-order case wrong.

Two AXES the concept model insists not be collapsed:
  1. against machines (LLM / regeneration) — a hard, deterministic refusal. Turns
     ON as early as the first user edit (a "user-owned" working draft), well below
     `final`.
  2. against humans — the SOFT / inform guard (the visual "protected" mark). ~nil
     on a working draft, RISES at `final`, higher at `published`. Never a wall.

`GuardLevel` is the ordered scale; `guard_level(facts)` is `max` over each live
fact's contributed level. The two axes are projections of the fact set, not of the
scalar level (a working-draft edit blocks machines without raising the human mark).
"""

from __future__ import annotations

import enum

from workflow.labels import Fact


class GuardLevel(enum.IntEnum):
    """Ordered edit-hardness. IntEnum so `max()` and `<`/`>=` work directly.

    OPEN       — freely editable, LLM may regenerate (untouched / first-draft).
    GUARDED    — locked against silent machine regen; the working-to-final band.
                 Reached by `final` OR manual `protected` (same rung, different
                 facts — there is NO privileged human-locked tier above the
                 automatic ones; guard is a plain max).
    PUBLISHED  — report-grain release floor; the loudest human-facing guard.
    """

    OPEN = 0
    GUARDED = 1
    PUBLISHED = 2


# What edit-hardness each FACT contributes. guard_level = max over live facts.
# A future adjective is ONE row here (what it asserts lives in labels; what it
# guards lives here) — never a new tier, never a reshape. `approved` (data
# readiness) contributes nothing to CONTENT edit-hardness; it gates the pipeline,
# a different concern.
_FACT_GUARD: dict[Fact, GuardLevel] = {
    Fact.PROTECTED: GuardLevel.GUARDED,
    Fact.FINAL: GuardLevel.GUARDED,       # final = protected + editorial (labels)
    Fact.PUBLISHED: GuardLevel.PUBLISHED,
    Fact.APPROVED: GuardLevel.OPEN,
}


def guard_level(facts: "frozenset[Fact] | set[Fact]") -> GuardLevel:
    """The single ordered guard for a node: max over its live facts.

    Empty / data-only fact sets → OPEN. Derived every call; never persist this.
    """
    level = GuardLevel.OPEN
    for fact in facts:
        contributed = _FACT_GUARD.get(fact, GuardLevel.OPEN)
        if contributed > level:
            level = contributed
    return level


def with_published_floor(
    node_level: GuardLevel, report_published: bool
) -> GuardLevel:
    """Apply the report-grain PUBLISHED floor to a node's own guard level.

    `published` is a REPORT-grain fact (a real-world release event), so it can't
    be a node label. It sets a FLOOR that propagates onto every node; node-grain
    facts can only RAISE from there. This is the report→node derivation the model
    calls for — not a label copied onto nodes.
    """
    if report_published and node_level < GuardLevel.PUBLISHED:
        return GuardLevel.PUBLISHED
    return node_level


# ---------------------------------------------------------------------------
# The two axes — projections of the FACT SET (not of the scalar level).
# ---------------------------------------------------------------------------

def blocks_machine_regen(facts: "frozenset[Fact] | set[Fact]", *, user_edited: bool) -> bool:
    """Axis 1 (against machines): may an LLM/regeneration silently overwrite?

    Hard/deterministic. True (refuse) as soon as the content is user-owned — the
    CONTEXT.md rule that a user-edited narrative is never silently recomputed —
    OR once any content-guarding fact is live. `user_edited` is passed in because
    it's a provenance fact about the node, not a label. Note this fires BELOW
    `final`: a merely user-edited working draft already blocks machines while its
    human-facing guard is still nil.
    """
    if user_edited:
        return True
    return guard_level(facts) >= GuardLevel.GUARDED


def human_guard(facts: "frozenset[Fact] | set[Fact]", *, report_published: bool = False) -> GuardLevel:
    """Axis 2 (against humans): the SOFT / inform guard the renderer surfaces.

    This is the visual "protected" mark's intensity. It is the guard scale with
    the published floor applied — it RISES at `final`/`protected`, highest at
    `published`. Never a wall: a human with edit rights can always override
    (that override is recorded, per the ratchet). Rendering step 5 reads this.
    """
    return with_published_floor(guard_level(facts), report_published)
