"""
workflow.labels — the FACT layer: what humans assert about content (ADR-0015).

The concept model's kind #4. Humans assert FACTS; the system derives consequences
(guard in workflow.guard, currency elsewhere, phase in workflow.phases). This
module owns the facts, the per-content-kind vocabularies, and the RATCHET that
governs how facts change.

Key model decisions encoded here (see project_workflow_concept_model.md):

  * Facts are an OPEN, per-content-kind set — data gets {approved}; a narrative
    gets a maturity ladder {first_draft → working_draft → final} plus the
    orthogonal flag {protected}; the report gets {published}. NO single universal
    label set. Adding an adjective = one row in the right vocabulary.
  * `approved` (data readiness) is DERIVED from artifacts (workflow.phases), not a
    human-asserted content fact — it appears in the data vocabulary for
    completeness but is not promoted/demoted through the ratchet here.
  * `final` = `protected` + "editorially done" (STRICT SUPERSET, not a synonym):
    promoting to `final` auto-sets `protected`; the reverse is false (manual-lock
    reaches the same guard WITHOUT the editorial claim).
  * Maturity is a RATCHET, not a ladder: promote = ADD a fact (cheap, moves with
    the guard); demote = REMOVE a fact (against the guard — requires a deliberate
    RECORDED reason, or is system-forced by currency). Up and down are DIFFERENT
    operations, not one reversed — hence no symmetric set_maturity(level).
"""

from __future__ import annotations

import enum

from workflow.errors import GuardViolation


class ContentKind(str, enum.Enum):
    """The grain a fact set belongs to. Vocabularies are per-kind."""

    DATA = "data"            # pool / integrated data readiness
    NARRATIVE = "narrative"  # authored section prose
    REPORT = "report"        # the whole living bundle


class Fact(str, enum.Enum):
    """Human-assertable (or, for APPROVED, system-derived) facts.

    Open set — a future adjective is a new member + a vocabulary entry + a
    guard-contribution row (workflow.guard._FACT_GUARD). Never a reshape.
    """

    # data grain (derived, not ratcheted here)
    APPROVED = "approved"
    # narrative grain — the maturity ladder + the orthogonal lock
    FIRST_DRAFT = "first_draft"
    WORKING_DRAFT = "working_draft"
    FINAL = "final"
    PROTECTED = "protected"
    # report grain
    PUBLISHED = "published"


# Per-content-kind vocabularies (the "open, per-kind set" made concrete).
VOCABULARIES: dict[ContentKind, frozenset[Fact]] = {
    ContentKind.DATA: frozenset({Fact.APPROVED}),
    ContentKind.NARRATIVE: frozenset({
        Fact.FIRST_DRAFT, Fact.WORKING_DRAFT, Fact.FINAL, Fact.PROTECTED,
    }),
    ContentKind.REPORT: frozenset({Fact.PUBLISHED}),
}

# The narrative maturity LADDER as an ordered scale (rungs, low → high). The flag
# PROTECTED is deliberately NOT here — it's orthogonal to maturity (you can
# protect a working draft). Monotonic by construction (constitutive of "ladder").
MATURITY_LADDER: tuple[Fact, ...] = (
    Fact.FIRST_DRAFT, Fact.WORKING_DRAFT, Fact.FINAL,
)

# Implication rules: asserting the key fact AUTO-sets the value facts.
# `final` ⇒ `protected` (superset, not synonym). One-directional.
_AUTO_SETS: dict[Fact, frozenset[Fact]] = {
    Fact.FINAL: frozenset({Fact.PROTECTED}),
}


class DemoteReason(str, enum.Enum):
    """Why a fact is being removed — the RECORDED release the ratchet requires.

    HUMAN_RELEASE   — a person deliberately reopens (voluntary, recorded).
    CURRENCY_FORCED — stale content knocked down by the system (involuntary).
    Both move against the guard; only CURRENCY_FORCED is involuntary.
    """

    HUMAN_RELEASE = "human_release"
    CURRENCY_FORCED = "currency_forced"


def promote(facts: "frozenset[Fact]", fact: Fact) -> frozenset[Fact]:
    """Add a fact (the up-ratchet). Cheap, default-OK — moves WITH the guard.

    Applies implication rules (`final` auto-sets `protected`). Idempotent.
    Returns the new fact set; inputs are never mutated (facts are immutable data).
    """
    new = set(facts)
    new.add(fact)
    new |= _AUTO_SETS.get(fact, frozenset())
    return frozenset(new)


def demote(
    facts: "frozenset[Fact]",
    fact: Fact,
    reason: "DemoteReason | None" = None,
) -> frozenset[Fact]:
    """Remove a fact (the down-ratchet). Moves AGAINST the guard.

    Refused with GuardViolation UNLESS a DemoteReason is supplied — the deliberate,
    recorded release (human) or the system-forced release (currency). This is the
    ratchet pawl: free to advance, locked against reversal unless deliberately
    released.

    A removal is a REVERSAL (needs a reason) when it either LOWERS the derived
    guard OR drops the top maturity rung. Both are observable regressions the
    ratchet exists to record. Removing a fact that does neither — e.g. clearing a
    stale FIRST_DRAFT while WORKING_DRAFT still holds the rung, or clearing
    PROTECTED while FINAL still holds the guard — is free (idempotent-ish cleanup,
    no consequence changes).

    Note the guard-vs-maturity split matters: clearing `final` while `protected`
    remains does NOT lower the guard (protected keeps it GUARDED) but DOES drop
    the maturity rung (the editorial claim is withdrawn) — so it needs a reason.
    Removing `final` does NOT auto-clear the `protected` it implied — the
    implication is one-directional and clearing is a separate deliberate act.
    """
    if fact not in facts:
        return facts  # nothing to remove; idempotent

    # An implied fact can't be cleared while its implier still holds — that would
    # violate the implication invariant (`final` present ⇒ `protected` present).
    # No-op; demote the implier first if you mean to release protection.
    for implier, implied in _AUTO_SETS.items():
        if fact in implied and implier in facts:
            return facts

    from workflow.guard import guard_level  # local import breaks labels↔guard cycle

    remaining = frozenset(facts - {fact})
    lowers_guard = guard_level(remaining) < guard_level(facts)
    lowers_maturity = maturity_rung(remaining) != maturity_rung(facts)
    if (lowers_guard or lowers_maturity) and reason is None:
        raise GuardViolation(
            f"Demoting {fact.value!r} is a reversal (lowers guard or maturity) "
            f"and requires a recorded reason (human release or currency-forced); "
            f"refused."
        )
    return remaining


def maturity_rung(facts: "frozenset[Fact] | set[Fact]") -> "Fact | None":
    """The highest maturity rung currently held, or None if untouched.

    Reads only the LADDER facts; ignores the orthogonal PROTECTED flag.
    """
    held = [rung for rung in MATURITY_LADDER if rung in facts]
    return held[-1] if held else None
