"""
Unit tests for the authoring steps in workflow.steps (Phase 1), driven by a FAKE
PoolStore — no disk, no FastAPI, no globals. These lift the approve/lock and
unapprove/unlock state transitions out of web_routes/session_routes.py; the
tests pin that the lifted logic matches the route behavior:

  * accept_section_step  ↔ POST /api/session/approve (persistence half)
  * release_section_step ↔ POST /api/session/unapprove

Mirrors tests/unit/test_workflow_steps.py's FakeStore discipline.
"""

import pytest

from workflow.errors import StepError
from workflow.steps import accept_section_step, release_section_step


class FakeSectionStore:
    """In-memory PoolStore double for the authoring steps.

    `read_json` serves `<key>.json` documents; `save_section` records the
    written data + whether it was archived (approve/unapprove both use
    archive=False for the lock flip)."""

    def __init__(self, sections=None):
        # sections maps section_key -> the section dict (as read_json would see
        # it under "<key>.json").
        self._sections = dict(sections or {})
        self.saved = {}          # section_key -> last saved data dict
        self.save_calls = []     # (section_key, archive) tuples

    def read_json(self, dtxsid, name):
        # name is "<section_key>.json"
        key = name[:-5] if name.endswith(".json") else name
        return self._sections.get(key)

    def save_section(self, dtxsid, key, data, archive=True):
        # Stamp a version the way session_store.save_section would, so callers
        # can read it back.
        data.setdefault("version", 1)
        self._sections[key] = data
        self.saved[key] = data
        self.save_calls.append((key, archive))


# --- accept_section_step ----------------------------------------------------

def test_accept_requires_dtxsid_and_key():
    store = FakeSectionStore()
    with pytest.raises(StepError) as ei:
        accept_section_step("", "background", store)
    assert ei.value.status_code == 400
    with pytest.raises(StepError) as ei2:
        accept_section_step("DTX", "", store)
    assert ei2.value.status_code == 400


def test_accept_missing_section_raises_404():
    store = FakeSectionStore()  # nothing on disk
    with pytest.raises(StepError) as ei:
        accept_section_step("DTX", "background", store)
    assert ei.value.status_code == 404


def test_accept_sets_approved_and_stamps_time():
    store = FakeSectionStore({"background": {"paragraphs": ["p"], "approved": False}})
    result = accept_section_step("DTX", "background", store)

    assert result["ok"] is True
    assert result["approved"] is True
    assert result["section_key"] == "background"
    saved = store.saved["background"]
    assert saved["approved"] is True
    assert "approved_at" in saved and saved["approved_at"]
    # lock flip does not create a history version (matches unapprove/approve
    # flag-flip convention)
    assert store.save_calls == [("background", False)]


def test_accept_clears_stale_flag():
    # invalidate_pool_artifacts sets stale=True; re-approval clears it (mirrors
    # /api/session/approve `data.pop("stale", None)`).
    store = FakeSectionStore(
        {"bm2_liver": {"tables_json": {}, "approved": False, "stale": True}}
    )
    accept_section_step("DTX", "bm2_liver", store)
    assert "stale" not in store.saved["bm2_liver"]
    assert store.saved["bm2_liver"]["approved"] is True


def test_accept_returns_version():
    store = FakeSectionStore({"methods": {"sections": [], "approved": False}})
    result = accept_section_step("DTX", "methods", store)
    assert result["version"] == 1


# --- release_section_step ---------------------------------------------------

def test_release_requires_dtxsid_and_key():
    store = FakeSectionStore()
    with pytest.raises(StepError) as ei:
        release_section_step("", "background", store)
    assert ei.value.status_code == 400


def test_release_flips_approved_false_preserving_content():
    store = FakeSectionStore(
        {"background": {"paragraphs": ["keep me"], "approved": True}}
    )
    result = release_section_step("DTX", "background", store)

    assert result == {"ok": True, "section_key": "background", "approved": False}
    saved = store.saved["background"]
    assert saved["approved"] is False
    # content preserved — unapprove is a lock flip, not a discard
    assert saved["paragraphs"] == ["keep me"]
    assert store.save_calls == [("background", False)]


def test_release_is_noop_safe_when_section_absent():
    store = FakeSectionStore()  # nothing on disk
    result = release_section_step("DTX", "summary", store)
    # always-ok so the caller need not pre-check (matches the route)
    assert result == {"ok": True, "section_key": "summary", "approved": False}
    assert store.save_calls == []


def test_accept_then_release_roundtrip():
    store = FakeSectionStore({"summary": {"paragraphs": ["s"], "approved": False}})
    accept_section_step("DTX", "summary", store)
    assert store.saved["summary"]["approved"] is True
    release_section_step("DTX", "summary", store)
    assert store.saved["summary"]["approved"] is False
