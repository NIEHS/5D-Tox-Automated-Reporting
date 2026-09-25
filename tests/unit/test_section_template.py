"""Unit tests for narrative.section_template (Phase 2 template representation)."""

import pytest

from narrative.section_template import (
    Literal,
    Slot,
    SlotKind,
    categorical_flips,
    edit_literal,
    render,
)


def _tpl():
    return [
        Literal("Weight was "),
        Slot("direction", SlotKind.CATEGORICAL),
        Literal(" (BMD "),
        Slot("bmd", SlotKind.NUMERIC),
        Literal(")."),
    ]


def test_render_interleaves_wording_and_slots():
    out = render(_tpl(), {"direction": "decreased", "bmd": "41.2"})
    assert out == "Weight was decreased (BMD 41.2)."


def test_render_missing_key_is_visible_not_crash():
    out = render(_tpl(), {"direction": "decreased"})
    assert out == "Weight was decreased (BMD <bmd?>)."


def test_edit_literal_keeps_slots_live():
    edited = edit_literal(_tpl(), 0, "Body weight ")
    # New wording applied, slots re-render against fresh data.
    assert render(edited, {"direction": "increased", "bmd": "9.4"}) == \
        "Body weight increased (BMD 9.4)."


def test_edit_literal_does_not_mutate_input():
    tpl = _tpl()
    edit_literal(tpl, 0, "Changed ")
    assert tpl[0].text == "Weight was "


def test_edit_literal_refuses_slot_target():
    with pytest.raises(TypeError):
        edit_literal(_tpl(), 1, "nope")  # index 1 is a Slot


def test_numeric_only_change_has_no_flips():
    tpl = _tpl()
    old = {"direction": "decreased", "bmd": "41.2"}
    new = {"direction": "decreased", "bmd": "18.7"}  # only BMD moved
    assert categorical_flips(tpl, old, new) == []


def test_categorical_flip_is_detected():
    tpl = _tpl()
    old = {"direction": "decreased", "bmd": "41.2"}
    new = {"direction": "increased", "bmd": "41.2"}
    assert categorical_flips(tpl, old, new) == [("direction", "decreased", "increased")]


def test_each_categorical_key_reported_once():
    tpl = [
        Slot("direction", SlotKind.CATEGORICAL),
        Literal(" ... "),
        Slot("direction", SlotKind.CATEGORICAL),  # same key twice
    ]
    old = {"direction": "decreased"}
    new = {"direction": "increased"}
    assert categorical_flips(tpl, old, new) == [("direction", "decreased", "increased")]
