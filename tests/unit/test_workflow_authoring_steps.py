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

from tests.unit.section_store_fake import FakeSectionStore as _SharedFake
from workflow.errors import StepError
from workflow.steps import (
    accept_section_step,
    discard_section_step,
    release_section_step,
    restore_section_step,
)


class FakeSectionStore(_SharedFake):
    """The shared in-memory section store (tests/unit/section_store_fake.py),
    with the attribute names these tests were written against."""

    @property
    def saved(self):
        return self.sections

    @property
    def save_calls(self):
        return self.writes


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
    # Approve asserts the FINAL content fact (ADR-0015 facts-on-disk), which
    # auto-sets PROTECTED — serialized to data["facts"].
    assert saved["facts"] == ["final", "protected"]
    # lock flip does not create a history version (matches unapprove/approve
    # flag-flip convention)
    assert store.save_calls == [("background", False)]


def test_accept_restores_final_on_a_demoted_section():
    # A section demoted by a reprocess (final dropped, protected stands) that the
    # human re-approves must climb back to final — the up-ratchet.
    store = FakeSectionStore({"genomics_liver_male": {
        "gene_set_narrative": ["g"], "approved": True,
        "stale": True, "facts": ["protected"],
    }})
    accept_section_step("DTX", "genomics_liver_male", store)
    saved = store.saved["genomics_liver_male"]
    assert saved["facts"] == ["final", "protected"]
    assert "stale" not in saved


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
    result = release_section_step("DTX", "background", store, reason="recheck")

    assert result == {"ok": True, "section_key": "background", "approved": False,
                      "version": 1, "version_status": "working"}
    saved = store.saved["background"]
    assert saved["approved"] is False
    # content preserved — unapprove is a lock flip, not a discard
    assert saved["paragraphs"] == ["keep me"]
    assert store.save_calls == [("background", False)]


def test_release_of_an_absent_section_is_not_found():
    # C2 (T5): releasing a key that does not exist used to answer ok.
    store = FakeSectionStore()  # nothing on disk
    with pytest.raises(StepError) as ei:
        release_section_step("DTX", "summary", store, reason="r")
    assert ei.value.status_code == 404 and ei.value.code == "section_not_found"
    assert ei.value.message == "No 'summary' section to reopen"
    assert store.save_calls == []


def test_accept_then_release_roundtrip():
    store = FakeSectionStore({"summary": {"paragraphs": ["s"], "approved": False}})
    accept_section_step("DTX", "summary", store)
    assert store.saved["summary"]["approved"] is True
    release_section_step("DTX", "summary", store, reason="numbers changed")
    assert store.saved["summary"]["approved"] is False


def test_revise_with_reason_demotes_final_records_reason():
    # A blessed section reopened via Revise: FINAL withdrawn (HUMAN_RELEASE),
    # PROTECTED stands, the human's reason recorded on the section.
    store = FakeSectionStore({"background": {
        "paragraphs": ["p"], "approved": True, "facts": ["final", "protected"],
    }})
    release_section_step("DTX", "background", store, reason="tone needs work")
    saved = store.saved["background"]
    assert saved["approved"] is False
    assert saved["facts"] == ["protected"]          # FINAL withdrawn, PROTECTED stands
    assert saved["revised"] == {"reason": "tone needs work"}


def test_revise_then_reaccept_restores_final():
    store = FakeSectionStore({"background": {
        "paragraphs": ["p"], "approved": True, "facts": ["final", "protected"],
    }})
    release_section_step("DTX", "background", store, reason="fix numbers wording")
    assert store.saved["background"]["facts"] == ["protected"]
    accept_section_step("DTX", "background", store)
    assert store.saved["background"]["facts"] == ["final", "protected"]
    assert store.saved["background"]["approved"] is True


# --- C2: the section steps' new rules ------------------------------------------

def test_accept_validates_the_key():
    with pytest.raises(StepError) as ei:
        accept_section_step("DTX", "../DTX_OTHER/summary", FakeSectionStore())
    assert ei.value.status_code == 400 and ei.value.code == "section_key_invalid"


def test_accept_of_an_accepted_section_is_a_noop_with_no_event():
    store = FakeSectionStore({"summary": {"paragraphs": ["s"], "approved": False}})
    accept_section_step("DTX", "summary", store)
    events = list(store.events["summary"])
    again = accept_section_step("DTX", "summary", store)
    assert again["noop"]["code"] == "already_accepted" and again["noop"]["say"]
    assert store.events["summary"] == events and len(store.writes) == 1


def test_accept_records_a_format_2_event_and_clears_review():
    store = FakeSectionStore({"bm2_bw": {"tables_json": {}, "approved": False, "version": 4,
                                         "review": {"why": "numbers_changed", "since_version": 3},
                                         "wording_review": ["x"], "source": "generated"}})
    out = accept_section_step("DTX", "bm2_bw", store)
    assert out["version"] == 4 and out["version_status"] == "blessed" and "noop" not in out
    now = store.sections["bm2_bw"]
    assert "review" not in now and "wording_review" not in now
    e = store.last_event("bm2_bw")
    assert (e["cause"], e["status"], e["act"], e["actor"], e["author"], e["version"],
            e["changed"]) == ("edit", "blessed", "accept", "person", "generated", 4, False)


def test_a_reaccept_after_a_hold_on_the_accepted_version_is_still_a_noop():
    store = FakeSectionStore({"summary": {"paragraphs": ["s"]}})
    accept_section_step("DTX", "summary", store)
    store.record_version_event("DTX", "summary", 1, {"cause": "hold", "status": "blessed"})
    assert accept_section_step("DTX", "summary", store)["noop"]["code"] == "already_accepted"


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_release_requires_a_reason(reason):
    store = FakeSectionStore({"summary": {"paragraphs": ["s"], "approved": True}})
    with pytest.raises(StepError) as ei:
        release_section_step("DTX", "summary", store, reason=reason)
    assert ei.value.status_code == 400 and ei.value.code == "reason_required"
    assert ei.value.message == "A reason is required to reopen 'summary'"
    assert store.writes == []


def test_release_of_an_unapproved_section_is_a_noop():
    store = FakeSectionStore({"summary": {"paragraphs": ["s"], "approved": False}})
    out = release_section_step("DTX", "summary", store)
    assert out["noop"]["code"] == "not_approved" and store.writes == [] and store.events == {}


def test_release_records_the_reason_on_the_trail():
    store = FakeSectionStore({"summary": {"paragraphs": ["s"], "approved": True,
                                          "facts": ["final", "protected"], "version": 2}})
    release_section_step("DTX", "summary", store, reason="  tone  ")
    e = store.last_event("summary")
    assert (e["cause"], e["status"], e["act"], e["reason"], e["version"]) == (
        "revise", "working", "release", "tone", 2)
    assert store.sections["summary"]["revised"] == {"reason": "tone"}


# restore (D3: back as a draft a person owns; reason required)

def _three_versions():
    store = FakeSectionStore()
    from workflow.section_writes import write_section
    for text in ("one", "two", "three"):
        write_section("DTX", "summary", {"paragraphs": [text], "source": "generated"}, store,
                      act="summary", actor="system", author="generated")
    return store


def test_restore_brings_a_version_back_as_an_owned_draft():
    store = _three_versions()
    accept_section_step("DTX", "summary", store)
    out = restore_section_step("DTX", "summary", 1, store, reason="v3 lost a finding")
    assert out == {"ok": True, "section_key": "summary", "version": 4, "from_version": 1,
                   "approved": False, "version_status": "working"}
    now = store.sections["summary"]
    assert now["paragraphs"] == ["one"] and now["version"] == 4
    assert now["approved"] is False and now["facts"] == ["protected"]
    assert "approved_at" not in now
    e = store.last_event("summary")
    assert (e["cause"], e["status"], e["from_version"], e["reason"], e["prior_version"]) == (
        "restore", "working", 1, "v3 lost a finding", 3)
    # The approved v3 was archived first (I2).
    assert store.read_archived("DTX", "summary", 3)["approved"] is True


def test_restore_keeps_the_current_file_s_currency_markers():
    store = _three_versions()
    store.sections["summary"].update({"stale": True, "regenerated": {"reason": "data_changed"}})
    restore_section_step("DTX", "summary", 1, store, reason="r")
    now = store.sections["summary"]
    assert now["stale"] is True and now["regenerated"] == {"reason": "data_changed"}


def test_restore_of_the_current_version_is_a_noop():
    store = _three_versions()
    out = restore_section_step("DTX", "summary", 3, store, reason="r")
    assert out["noop"]["code"] == "already_current" and len(store.events["summary"]) == 3


@pytest.mark.parametrize("version", [9, 0, -1, "1", None, True])
def test_restore_of_an_unknown_version_is_not_found(version):
    with pytest.raises(StepError) as ei:
        restore_section_step("DTX", "summary", version, _three_versions(), reason="r")
    assert ei.value.status_code == 404 and ei.value.code == "version_not_found"


def test_restore_requires_a_reason_and_a_valid_key():
    with pytest.raises(StepError) as ei:
        restore_section_step("DTX", "summary", 1, _three_versions(), reason="")
    assert ei.value.code == "reason_required"
    with pytest.raises(StepError) as ei:
        restore_section_step("DTX", "../x", 1, _three_versions(), reason="r")
    assert ei.value.code == "section_key_invalid"     # T10


# discard (D4: behind the old route and pool reset)

def test_discard_archives_and_restore_brings_it_back():
    # T9: after a discard, restore and history still reach the archives;
    # T8: version numbers never repeat.
    store = _three_versions()
    out = discard_section_step("DTX", "summary", store, reason="wrong chemical")
    assert out["version"] == 3 and out["archived"] and "summary" not in store.sections
    back = restore_section_step("DTX", "summary", 3, store, reason="it was right")
    assert back["version"] == 4 and store.sections["summary"]["paragraphs"] == ["three"]


def test_discard_refuses_an_approved_section_and_needs_a_reason():
    store = _three_versions()
    accept_section_step("DTX", "summary", store)
    with pytest.raises(StepError) as ei:
        discard_section_step("DTX", "summary", store, reason="r")
    assert ei.value.code == "section_owned" and ei.value.status_code == 409
    release_section_step("DTX", "summary", store, reason="r")
    with pytest.raises(StepError) as ei:
        discard_section_step("DTX", "summary", store, reason="")
    assert ei.value.code == "reason_required"
    assert discard_section_step("DTX", "summary", store, reason="r")["version"] == 3
    with pytest.raises(StepError) as ei:
        discard_section_step("DTX", "summary", store, reason="r")
    assert ei.value.code == "section_not_found"


def test_i3_every_version_the_trail_names_has_retrievable_text():
    # I3, over a sequence of every act: accept, release, machine write,
    # restore, discard, and the D2 knock-down.
    from workflow.section_writes import REVIEW, write_section
    store = _three_versions()
    accept_section_step("DTX", "summary", store)
    release_section_step("DTX", "summary", store, reason="r1")
    restore_section_step("DTX", "summary", 2, store, reason="r2")
    accept_section_step("DTX", "summary", store)
    write_section("DTX", "summary", {"paragraphs": ["machine"], "source": "generated"}, store,
                  act="summary", actor="system", author="generated", on_owned=REVIEW,
                  review={"why": "numbers_changed"})
    release_section_step("DTX", "summary", store)          # not approved: noop
    discard_section_step("DTX", "summary", store, reason="r3")
    restore_section_step("DTX", "summary", 4, store, reason="r4")
    versions = {e["version"] for e in store.events["summary"]}
    assert versions == {1, 2, 3, 4, 5, 6}
    for v in versions:
        assert store.retrievable("summary", v), v
    # I4: one event per change of approval (accept ×2, release ×1, knock-down ×1).
    flips = [e for e in store.events["summary"]
             if (e["cause"], e["status"]) in {("edit", "blessed"), ("revise", "working"),
                                              ("reprocess", "needs-re-bless")}]
    assert len(flips) == 4
