"""
Unit tests for the label + guard model (ADR-0015).

Pins the concept-model decisions as executable truth tables:
  * guard = max over live facts, derived-never-stored;
  * final = protected + editorial (strict superset, NOT a synonym);
  * the RATCHET: promote cheap; demote guarded (needs a recorded reason) or
    currency-forced; two kinds of descent;
  * two guard AXES (against-machines fires at first edit; against-humans rises at
    final/published);
  * published is a REPORT-grain floor, not a node label.

If any of these change, it must change AT THE MODEL (labels.py/guard.py) as a
deliberate act — these tests are the record of what was decided.
"""

import pytest

from workflow.errors import GuardViolation
from workflow.guard import (
    GuardLevel,
    blocks_machine_regen,
    guard_level,
    human_guard,
    with_published_floor,
)
from workflow.labels import (
    ContentKind,
    DemoteReason,
    Fact,
    MATURITY_LADDER,
    VOCABULARIES,
    demote,
    maturity_rung,
    promote,
)

F = frozenset


# --- guard = max over facts ------------------------------------------------

@pytest.mark.parametrize("facts,expected", [
    (F(),                              GuardLevel.OPEN),
    (F({Fact.APPROVED}),              GuardLevel.OPEN),      # data-approved ≠ content guard
    (F({Fact.FIRST_DRAFT}),          GuardLevel.OPEN),
    (F({Fact.WORKING_DRAFT}),        GuardLevel.OPEN),
    (F({Fact.PROTECTED}),            GuardLevel.GUARDED),
    (F({Fact.FINAL, Fact.PROTECTED}), GuardLevel.GUARDED),
    (F({Fact.PUBLISHED}),            GuardLevel.PUBLISHED),
    (F({Fact.PROTECTED, Fact.PUBLISHED}), GuardLevel.PUBLISHED),  # max wins
])
def test_guard_level_is_max_over_facts(facts, expected):
    assert guard_level(facts) is expected


def test_protected_and_final_reach_the_same_rung():
    # No privileged "human-locked" tier above the automatic ones — guard is a
    # plain max, so manual protect and final sit at the SAME GUARDED rung.
    assert guard_level(F({Fact.PROTECTED})) is guard_level(F({Fact.FINAL, Fact.PROTECTED}))


# --- final = protected + editorial (superset, not synonym) -----------------

def test_final_auto_sets_protected():
    facts = promote(F(), Fact.FINAL)
    assert Fact.FINAL in facts and Fact.PROTECTED in facts


def test_protected_does_not_imply_final():
    facts = promote(F(), Fact.PROTECTED)
    assert Fact.PROTECTED in facts and Fact.FINAL not in facts


def test_final_is_strict_superset_the_maturity_rung_survives():
    # Collapsing final≡protected would destroy the top ladder rung; prove final
    # still carries the maturity meaning protected does not.
    assert maturity_rung(promote(F(), Fact.FINAL)) is Fact.FINAL
    assert maturity_rung(promote(F(), Fact.PROTECTED)) is None


# --- the ratchet: promote cheap, demote guarded ----------------------------

def test_promote_is_idempotent():
    once = promote(F(), Fact.WORKING_DRAFT)
    twice = promote(once, Fact.WORKING_DRAFT)
    assert once == twice


def test_demote_without_reason_refused_when_it_lowers_guard():
    facts = promote(F(), Fact.PROTECTED)  # GUARDED
    with pytest.raises(GuardViolation):
        demote(facts, Fact.PROTECTED)


def test_demote_without_reason_refused_when_it_drops_maturity():
    # Clearing final keeps guard GUARDED (protected remains) but drops the rung —
    # still a reversal, still needs a reason.
    facts = promote(F(), Fact.FINAL)  # {final, protected}
    with pytest.raises(GuardViolation):
        demote(facts, Fact.FINAL)


def test_demote_with_human_release_allowed():
    facts = promote(F(), Fact.FINAL)
    out = demote(facts, Fact.FINAL, DemoteReason.HUMAN_RELEASE)
    assert Fact.FINAL not in out
    assert Fact.PROTECTED in out  # one-directional: implied fact not auto-cleared


def test_demote_with_currency_forced_allowed():
    facts = promote(F(), Fact.PROTECTED)
    out = demote(facts, Fact.PROTECTED, DemoteReason.CURRENCY_FORCED)
    assert out == F()


def test_demote_free_when_no_consequence_changes():
    # first_draft alongside working_draft: rung is working_draft, guard OPEN.
    facts = promote(promote(F(), Fact.WORKING_DRAFT), Fact.FIRST_DRAFT)
    out = demote(facts, Fact.FIRST_DRAFT)  # no reason needed
    assert out == F({Fact.WORKING_DRAFT})


def test_cannot_clear_an_implied_fact_while_implier_holds():
    # protected is implied by final; clearing it while final holds is a no-op
    # (keeps the fact set consistent with the implication invariant).
    facts = promote(F(), Fact.FINAL)
    assert demote(facts, Fact.PROTECTED) == facts


def test_demote_absent_fact_is_noop():
    facts = promote(F(), Fact.WORKING_DRAFT)
    assert demote(facts, Fact.PUBLISHED) == facts


# --- two axes --------------------------------------------------------------

def test_axis1_blocks_machines_at_first_edit_below_final():
    # A user-edited working draft blocks LLM regen (axis 1 ON) while its human
    # guard is still nil (axis 2 OPEN). The two axes are independent.
    facts = promote(F(), Fact.WORKING_DRAFT)
    assert blocks_machine_regen(facts, user_edited=True) is True
    assert human_guard(facts) is GuardLevel.OPEN


def test_axis1_open_when_untouched_and_no_guarding_fact():
    assert blocks_machine_regen(F(), user_edited=False) is False


def test_axis1_blocks_once_guarded_even_without_edit_flag():
    assert blocks_machine_regen(F({Fact.PROTECTED}), user_edited=False) is True


def test_axis2_rises_at_final_and_published():
    assert human_guard(F({Fact.WORKING_DRAFT})) is GuardLevel.OPEN
    assert human_guard(F({Fact.FINAL, Fact.PROTECTED})) is GuardLevel.GUARDED
    assert human_guard(F({Fact.PUBLISHED})) is GuardLevel.PUBLISHED


# --- published report-grain floor ------------------------------------------

def test_published_floor_propagates_onto_nodes():
    # A node with no facts, in a published report, inherits the floor — but only
    # raises, never lowers.
    assert with_published_floor(GuardLevel.OPEN, report_published=True) is GuardLevel.PUBLISHED
    assert with_published_floor(GuardLevel.OPEN, report_published=False) is GuardLevel.OPEN


def test_published_floor_never_lowers_a_higher_node_level():
    assert with_published_floor(GuardLevel.PUBLISHED, report_published=False) is GuardLevel.PUBLISHED


def test_human_guard_applies_published_floor():
    facts = F({Fact.WORKING_DRAFT})
    assert human_guard(facts, report_published=True) is GuardLevel.PUBLISHED


# --- vocabularies + ladder integrity ---------------------------------------

def test_vocabularies_are_per_kind():
    assert VOCABULARIES[ContentKind.DATA] == F({Fact.APPROVED})
    assert Fact.PUBLISHED in VOCABULARIES[ContentKind.REPORT]
    assert Fact.FINAL in VOCABULARIES[ContentKind.NARRATIVE]
    # protected is a narrative flag, not a data or report fact
    assert Fact.PROTECTED not in VOCABULARIES[ContentKind.DATA]


def test_maturity_ladder_is_ordered_and_excludes_protected():
    assert MATURITY_LADDER == (Fact.FIRST_DRAFT, Fact.WORKING_DRAFT, Fact.FINAL)
    assert Fact.PROTECTED not in MATURITY_LADDER


def test_maturity_ladder_guard_is_monotonic_nondecreasing():
    # Constitutive: climbing the ladder must never DROP the guard.
    levels = [guard_level(F({rung})) for rung in MATURITY_LADDER]
    assert levels == sorted(levels)
