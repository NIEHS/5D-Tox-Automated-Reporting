"""
Unit tests for workflow.ownership — the ONE guard predicate over content
ownership (ADR-0015 §Consolidation, the narrow step-4b half).

Pins:
  * the adapter (on-disk approved/stale/user_edited booleans → the step-4a Fact
    set, at read time, no migration);
  * may_machine_write — the single machine-guard predicate that replaces the
    scattered checks (force escape hatch; refuse on user-owned);
  * protection_map — the render wiring (MACHINE-PROTECTED semantics, decided
    2026-08-16: approved/user-edited lights up now; published floor louder), keyed
    by DocNode.id, empty when nothing owned (byte-identical safety).
"""

import pytest

from workflow.guard import GuardLevel
from workflow.labels import Fact
from workflow.ownership import (
    is_section_stale,
    is_user_owned,
    may_machine_write,
    protection_level,
    protection_map,
    section_facts,
)

F = frozenset


# --- adapter: booleans -> facts --------------------------------------------

def test_section_facts_approved_maps_to_APPROVED():
    assert section_facts({"approved": True}) == F({Fact.APPROVED})


@pytest.mark.parametrize("section", [None, {}, {"approved": False}, "nonsense"])
def test_section_facts_empty_when_not_approved(section):
    assert section_facts(section) == F()


def test_is_section_stale():
    assert is_section_stale({"stale": True}) is True
    assert is_section_stale({"stale": False}) is False
    assert is_section_stale({}) is False
    assert is_section_stale(None) is False


def test_is_user_owned():
    assert is_user_owned({"approved": True}) is True
    assert is_user_owned({"user_edited": True}) is True
    assert is_user_owned({"approved": False}) is False
    assert is_user_owned({}) is False
    assert is_user_owned(None) is False


# --- may_machine_write: the unified predicate ------------------------------

def test_may_write_fresh_content():
    # Nothing owned → safe to (re)generate.
    assert may_machine_write({}) is True
    assert may_machine_write(None) is True


def test_may_not_write_over_approved():
    assert may_machine_write({"approved": True}) is False


def test_may_not_write_over_user_edited():
    assert may_machine_write({"user_edited": True}) is False


def test_force_is_the_escape_hatch():
    # The user explicitly asked to regenerate — always permitted.
    assert may_machine_write({"approved": True}, force=True) is True
    assert may_machine_write({"user_edited": True}, force=True) is True


def test_stale_but_owned_still_refused():
    # A stale approved section must NOT be clobbered — the user re-blesses it.
    assert may_machine_write({"approved": True, "stale": True}) is False


# --- protection_level: MACHINE-PROTECTED semantics -------------------------

def test_protection_level_owned_is_guarded():
    assert protection_level({"approved": True}) is GuardLevel.GUARDED
    assert protection_level({"user_edited": True}) is GuardLevel.GUARDED


def test_protection_level_unowned_is_open():
    assert protection_level({}) is GuardLevel.OPEN
    assert protection_level(None) is GuardLevel.OPEN


def test_protection_level_published_floor():
    # Published report floors even unowned nodes to PUBLISHED.
    assert protection_level({}, report_published=True) is GuardLevel.PUBLISHED
    # And owned content is at least PUBLISHED under the floor.
    assert protection_level({"approved": True}, report_published=True) is GuardLevel.PUBLISHED


# --- protection_map: the render wiring --------------------------------------

class _N:
    def __init__(self, id, data_key=None, narrative_key=None, children=None):
        self.id = id
        self.data_key = data_key
        self.narrative_key = narrative_key
        self.children = children or []


def _tree():
    return [
        _N("background", data_key="background"),
        _N("methods", data_key="methods"),
        _N("grp", narrative_key="interp", children=[_N("leaf", data_key="bw")]),
    ]


def test_protection_map_marks_only_owned_nodes():
    data = {
        "background": {"approved": True},
        "methods": {"approved": False},
        "unified_narratives": {"interp": {"user_edited": True}},
        "bw": {},
    }
    result = protection_map(_tree(), data)
    assert result == {"background": GuardLevel.GUARDED, "grp": GuardLevel.GUARDED}
    # methods (not approved) and leaf (empty) are omitted → no mark.
    assert "methods" not in result
    assert "leaf" not in result


def test_protection_map_empty_when_nothing_owned():
    # The byte-identical safety property: no owned content → empty map → the
    # renderer adds no data["protection"] → output unchanged.
    data = {"background": {"approved": False}, "methods": {}}
    assert protection_map(_tree(), data) == {}


def test_protection_map_empty_data_is_empty():
    assert protection_map(_tree(), {}) == {}


def test_protection_map_published_floors_visited_nodes():
    data = {"background": {"approved": True}, "methods": {}, "bw": {}}
    result = protection_map(_tree(), data, report_published=True)
    # Every node with a resolvable section slot is floored to PUBLISHED.
    assert result["background"] is GuardLevel.PUBLISHED
    assert result["methods"] is GuardLevel.PUBLISHED
    assert result["leaf"] is GuardLevel.PUBLISHED


def test_protection_map_accepts_single_root():
    root = _N("background", data_key="background")
    data = {"background": {"approved": True}}
    assert protection_map(root, data) == {"background": GuardLevel.GUARDED}
