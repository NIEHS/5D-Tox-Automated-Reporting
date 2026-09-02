"""Unit tests for workflow.reprocess (Phase 3a pure router)."""

import pytest

from workflow.reprocess import (
    ReprocessAction,
    blocking_llm_sections,
    can_publish_report,
    classify_section_reprocess,
    should_stale_on_reprocess,
)

_CONTENT = {"approved": True, "paragraphs": ["x"]}


@pytest.mark.parametrize("key,expected", [
    ("bm2_organ-and-body-weights", ReprocessAction.REFRESH_NUMBERS),
    ("bm2_clinical-pathology", ReprocessAction.REFRESH_NUMBERS),
    ("genomics_liver_male", ReprocessAction.REWRITE_LLM),
    ("genomics_kidney_female", ReprocessAction.REWRITE_LLM),
    ("background", ReprocessAction.REWRITE_LLM),
    ("methods", ReprocessAction.REWRITE_LLM),
    ("summary", ReprocessAction.REWRITE_LLM),
    ("bmd_summary", ReprocessAction.REWRITE_LLM),
])
def test_classify_by_origin(key, expected):
    assert classify_section_reprocess(key, _CONTENT) is expected


def test_unknown_key_fails_safe_to_rewrite_llm():
    # Unclassifiable content must never be treated as auto-refreshable programmatic.
    assert classify_section_reprocess("mystery_section", _CONTENT) is ReprocessAction.REWRITE_LLM


@pytest.mark.parametrize("section", [None, {}])
def test_missing_or_empty_section_is_leave(section):
    assert classify_section_reprocess("bm2_liver", section) is ReprocessAction.LEAVE
    assert classify_section_reprocess("genomics_liver_male", section) is ReprocessAction.LEAVE


def test_should_stale_only_llm_sections():
    # The behavior change vs the old "stale everything": programmatic is NOT staled.
    assert should_stale_on_reprocess("bm2_liver", _CONTENT) is False
    assert should_stale_on_reprocess("genomics_liver_male", _CONTENT) is True
    assert should_stale_on_reprocess("background", _CONTENT) is True
    # unknown fails safe to staled (conservative)
    assert should_stale_on_reprocess("mystery", _CONTENT) is True
    # nothing to act on -> not staled
    assert should_stale_on_reprocess("bm2_liver", None) is False


# --- publish gate ----------------------------------------------------------

_FRESH_LLM = {"approved": True, "gene_set_narrative": ["x"]}
_STALE_LLM = {"approved": True, "stale": True, "gene_set_narrative": ["x"]}
_STALE_PROG = {"approved": True, "stale": True, "paragraphs": ["x"]}


def test_publishable_when_all_fresh():
    sections = {"genomics_liver_male": _FRESH_LLM, "bm2_liver": _CONTENT}
    assert can_publish_report(sections) is True
    assert blocking_llm_sections(sections) == []


def test_stale_llm_section_blocks_publish():
    sections = {"genomics_liver_male": _STALE_LLM, "background": _FRESH_LLM}
    assert can_publish_report(sections) is False
    assert blocking_llm_sections(sections) == ["genomics_liver_male"]


def test_stale_programmatic_does_not_block():
    # A programmatic section carrying stale (shouldn't happen post-3a, but be safe)
    # must NOT block publish — it has no LLM claim to re-bless.
    sections = {"bm2_liver": _STALE_PROG, "genomics_liver_male": _FRESH_LLM}
    assert can_publish_report(sections) is True


def test_reaccept_clears_block():
    # Re-approve (Phase 1 accept_section_step) clears `stale` → unblocks.
    sections = {"genomics_liver_male": _STALE_LLM}
    assert can_publish_report(sections) is False
    reaccepted = {"genomics_liver_male": {**_STALE_LLM, "stale": False}}
    assert can_publish_report(reaccepted) is True


def test_multiple_blockers_sorted():
    sections = {
        "genomics_liver_male": _STALE_LLM,
        "background": _STALE_LLM,
        "bm2_liver": _CONTENT,
    }
    assert blocking_llm_sections(sections) == ["background", "genomics_liver_male"]
