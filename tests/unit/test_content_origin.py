"""Phase 0 gate: section content-origin classification.

Pins that every canonical section resolves to the right origin (LLM vs
programmatic) in both the section_type and on-disk section_key forms, and that
unknown keys fail safe to LLM. No behavior change — this is the read point Phase 3
(reprocess) and Phase 4 (publish gate) will consume.
"""

import pytest

from workflow.content_origin import (
    ContentOrigin,
    is_llm_section,
    origin_for_section_key,
    origin_for_section_type,
)


@pytest.mark.parametrize("section_type,expected", [
    ("background", ContentOrigin.LLM),
    ("methods", ContentOrigin.LLM),
    ("summary", ContentOrigin.LLM),
    ("bmd_summary", ContentOrigin.LLM),
    ("genomics", ContentOrigin.LLM),
    ("bm2", ContentOrigin.PROGRAMMATIC),
])
def test_origin_for_section_type(section_type, expected):
    assert origin_for_section_type(section_type) is expected


def test_unknown_section_type_is_none():
    assert origin_for_section_type("nope") is None


@pytest.mark.parametrize("section_key,expected", [
    ("background", ContentOrigin.LLM),
    ("methods", ContentOrigin.LLM),
    ("summary", ContentOrigin.LLM),
    ("bmd_summary", ContentOrigin.LLM),
    # instance forms
    ("bm2_liver_male", ContentOrigin.PROGRAMMATIC),
    ("bm2_terminal-body-wt", ContentOrigin.PROGRAMMATIC),
    ("genomics_liver_male", ContentOrigin.LLM),
    ("genomics_kidney_female", ContentOrigin.LLM),
])
def test_origin_for_section_key(section_key, expected):
    assert origin_for_section_key(section_key) is expected


def test_unknown_section_key_is_none():
    assert origin_for_section_key("mystery_section") is None


def test_is_llm_section_true_for_llm_kinds():
    for key in ("background", "methods", "summary", "bmd_summary",
                "genomics_liver_male"):
        assert is_llm_section(key) is True


def test_is_llm_section_false_for_programmatic():
    assert is_llm_section("bm2_liver_male") is False


def test_is_llm_section_fails_safe_to_llm_on_unknown():
    # An unclassifiable key must NOT be treated as auto-updatable programmatic.
    assert is_llm_section("mystery_section") is True
