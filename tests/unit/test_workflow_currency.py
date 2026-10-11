"""
Unit tests for the currency / staleness layer (ADR-0014 step 6, concept-model
kind #6).

Pins the model's ruling on stale content as executable truth:
  * is_stale fires ONLY on a positive signal (both hashes present and differing);
    a None on either side is "unknown" and treated as fresh (no false-blocking).
  * currency is a hard BLOCK, not a warning: stale content CANNOT advance toward
    final/published (can_advance False / assert_can_advance + advance raise
    GuardViolation), while fresh content advances via the labels ratchet.
  * currency force-releases the ratchet pawl involuntarily: a stale FINAL is
    knocked down via DemoteReason.CURRENCY_FORCED, which succeeds where an
    unreasoned demote of the same rung would raise.

If any of these change it must change at the model (workflow/currency.py) as a
deliberate act — these tests are the record of what was decided.
"""

import pytest

from workflow.currency import (
    advance,
    assert_can_advance,
    can_advance,
    demote_for_currency,
    is_stale,
)
from workflow.errors import GuardViolation
from workflow.labels import DemoteReason, Fact, demote, maturity_rung, promote

F = frozenset


# --- is_stale: positive-signal-only ---------------------------------------

def test_is_stale_both_present_and_differ_is_true():
    assert is_stale("aaa", "bbb") is True


def test_is_stale_equal_is_false():
    assert is_stale("aaa", "aaa") is False


@pytest.mark.parametrize("recorded,current", [
    (None, "bbb"),
    ("aaa", None),
    (None, None),
])
def test_is_stale_none_is_unknown_not_stale(recorded, current):
    """Unknown (missing hash on either side) must NOT block — currency fires only
    on a positive staleness signal, never on absence of information."""
    assert is_stale(recorded, current) is False


# --- the BLOCK: fresh advances, stale is refused ---------------------------

def test_fresh_content_can_advance():
    assert can_advance(F(), is_stale=False) is True


def test_stale_content_cannot_advance():
    assert can_advance(F(), is_stale=False) is not can_advance(F(), is_stale=True)
    assert can_advance(F(), is_stale=True) is False


def test_assert_can_advance_passes_when_fresh():
    # Should not raise.
    assert_can_advance(F({Fact.WORKING_DRAFT}), is_stale=False)


def test_assert_can_advance_blocks_when_stale():
    with pytest.raises(GuardViolation):
        assert_can_advance(F({Fact.WORKING_DRAFT}), is_stale=True)


def test_advance_fresh_promotes_to_final():
    """Fresh working draft advances to final (and picks up implied protected)."""
    result = advance(F({Fact.WORKING_DRAFT}), Fact.FINAL, is_stale=False)
    assert Fact.FINAL in result
    assert Fact.PROTECTED in result  # final ⇒ protected (labels implication)


def test_advance_stale_is_blocked():
    with pytest.raises(GuardViolation):
        advance(F({Fact.WORKING_DRAFT}), Fact.FINAL, is_stale=True)


# --- involuntary knock-down: currency force-releases the pawl --------------

def test_currency_forced_demotion_drops_the_maturity_rung():
    facts = promote(F(), Fact.FINAL)  # {final, protected}
    demoted = demote_for_currency(facts)
    # The editorial claim is withdrawn; protection is left standing.
    assert Fact.FINAL not in demoted
    assert Fact.PROTECTED in demoted
    assert maturity_rung(demoted) is None


def test_currency_forced_succeeds_where_unreasoned_demote_would_raise():
    """The point of CURRENCY_FORCED: an unreasoned demote of the top rung is a
    reversal the ratchet refuses; currency supplies the recorded reason."""
    facts = promote(F(), Fact.FINAL)
    # Baseline: an unreasoned demote of FINAL is refused.
    with pytest.raises(GuardViolation):
        demote(facts, Fact.FINAL)  # reason=None
    # But the currency-forced path (DemoteReason.CURRENCY_FORCED) succeeds.
    assert demote_for_currency(facts) == demote(
        facts, Fact.FINAL, DemoteReason.CURRENCY_FORCED
    )


def test_currency_forced_demotion_is_idempotent_when_no_rung():
    """No maturity rung to drop → returns the fact set unchanged."""
    facts = F({Fact.PROTECTED})  # protected but not final: no ladder rung
    assert demote_for_currency(facts) == facts
    assert demote_for_currency(F()) == F()
