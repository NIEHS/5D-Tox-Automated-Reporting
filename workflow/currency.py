"""
workflow.currency — the CURRENCY / staleness layer (ADR-0014 step 6, concept
model kind #6).

Currency is a CORRECTNESS concern, not a courtesy one. When the inputs that
produced a piece of content change (e.g. the cache hash that keyed it moves —
see pipeline.cache_plumbing), the content is STALE: it no longer reflects the
data or method it claims to. The concept model's ruling on stale content is a
hard BLOCK, not a warning — stale content is BLOCKED from ADVANCING (cannot go
final / published / render-as-final) until a human re-blesses it, and stale
content that already holds such a claim is knocked DOWN involuntarily.

This module is PURE — no disk I/O, no HTTP. It compares hashes and composes with
the fact ratchet in workflow.labels:

  * is_stale(recorded, current) — the staleness comparison itself.
  * can_advance / assert_can_advance / advance — the BLOCK: promotion toward
    final/published is refused while stale (composes with labels.promote).
  * demote_for_currency — the involuntary knock-down: the ratchet pawl
    force-released by the SYSTEM via DemoteReason.CURRENCY_FORCED (composes with
    labels.demote, which would otherwise refuse an unreasoned reversal).

The "who decides" split mirrors labels/guard: currency ENFORCES against actors
that can't reason (the pipeline, an LLM regen); a human-with-rights re-blesses by
recomputing/re-approving so the hashes match again (is_stale → False), or takes
the recorded HUMAN_RELEASE path in workflow.labels.
"""

from __future__ import annotations

from workflow.errors import GuardViolation
from workflow.labels import (
    DemoteReason,
    Fact,
    demote,
    maturity_rung,
    promote,
)

__all__ = [
    "is_stale",
    "can_advance",
    "assert_can_advance",
    "advance",
    "demote_for_currency",
    # re-exported for callers that reason about currency in one import
    "Fact",
    "DemoteReason",
]


def is_stale(recorded_hash: "str | None", current_hash: "str | None") -> bool:
    """Is content keyed by `recorded_hash` stale against `current_hash`?

    STALE only when BOTH hashes are present and they DIFFER — the content was
    produced under a keying that no longer holds.

    A None on either side is "unknown", NOT stale: either the content was never
    hash-keyed (nothing to compare) or the current inputs can't be hashed yet.
    Treating unknown as fresh is the deliberate choice to avoid FALSE-BLOCKING —
    currency is a hard BLOCK, so it must fire only on a POSITIVE staleness signal,
    never on absence of information. (The inverse — blocking on unknown — would
    wall off content the moment a hash went missing, which is a bug not a guard.)
    """
    if recorded_hash is None or current_hash is None:
        return False
    return recorded_hash != current_hash


def can_advance(facts: "frozenset[Fact]", *, is_stale: bool) -> bool:
    """BLOCK predicate (concept model kind #6): may this content be ADVANCED
    toward final/published right now?

    Currency BLOCKS, it does not warn: stale content CANNOT advance until a human
    re-blesses it (recompute so the hashes match, or take a recorded release).
    Returns False iff `is_stale`.

    `facts` is accepted for a signature uniform with promote/demote and to leave
    room for future advance conditions; staleness is the only advance-blocker this
    correctness layer owns (edit-hardness lives in workflow.guard, phase readiness
    in workflow.phases).
    """
    return not is_stale


def assert_can_advance(facts: "frozenset[Fact]", *, is_stale: bool) -> None:
    """Raise GuardViolation if content may not advance (i.e. it is stale).

    The enforcement half of the BLOCK: the mechanism refuses to let stale content
    move toward final/published. A human-with-rights clears it by re-blessing
    (making the hashes match again), not by suppressing this check.
    """
    if not can_advance(facts, is_stale=is_stale):
        raise GuardViolation(
            "Advancing stale content toward final/published is refused "
            "(currency BLOCK): re-bless it (recompute so its inputs match) "
            "before promoting."
        )


def advance(
    facts: "frozenset[Fact]", fact: Fact, *, is_stale: bool
) -> frozenset[Fact]:
    """Promote `fact` (advance toward final/published) UNLESS content is stale.

    Composes the currency BLOCK with labels.promote: raises GuardViolation when
    the content is stale, otherwise returns the promoted fact set. Use this
    instead of calling promote() directly whenever the promotion is a currency-
    sensitive advance (going final / published / render-as-final).
    """
    assert_can_advance(facts, is_stale=is_stale)
    return promote(facts, fact)


def demote_for_currency(facts: "frozenset[Fact]") -> frozenset[Fact]:
    """The involuntary knock-down: currency force-releases the ratchet pawl.

    Stale content that already holds a maturity claim can no longer stand behind
    it, so the SYSTEM knocks it down — drops the top maturity rung it holds
    (e.g. FINAL → withdrawn) WITHOUT a human acting. This composes with
    labels.demote using DemoteReason.CURRENCY_FORCED, the recorded reason the
    ratchet requires for an involuntary reversal; an UNREASONED demote of the same
    rung would raise GuardViolation.

    Only the maturity rung is withdrawn — an implied PROTECTED (or a manual lock)
    is left in place, so the content stops CLAIMING finality but stays guarded
    against silent machine regen until a human decides. Idempotent when there is
    no maturity rung to drop (returns the input fact set unchanged).
    """
    rung = maturity_rung(facts)
    if rung is None:
        return facts
    return demote(facts, rung, DemoteReason.CURRENCY_FORCED)
