"""
The section write gate, workflow.section_writes (C2 spec §3), rule by rule,
with an in-memory store (no disk). Acceptance criteria I1 (the gate itself),
I2, I4, I6 and the T10 key check.
"""

import pytest

from tests.unit.section_store_fake import FakeSectionStore
from workflow import section_writes as sw
from workflow.ownership import content_hash
from workflow.refusals import explain

ID = "DTXSID_GATE"


def _w(store, key="summary", content=None, **kw):
    kw.setdefault("act", "summary")
    kw.setdefault("actor", "system")
    kw.setdefault("author", "generated")
    return sw.write_section(ID, key, content or {"paragraphs": ["new"], "source": "generated"},
                            store, **kw)


# --- rule 1: the key ---------------------------------------------------------

@pytest.mark.parametrize("key", ["../DTXSID_VICTIM/summary", "meta", "identity", "bm2_",
                                 "bm2_a/b", "bm2_x.json", "", None, "genomics_../x"])
def test_a_key_that_is_not_a_section_of_the_report_is_refused(key):
    store = FakeSectionStore()
    with pytest.raises(sw.SectionRefusal) as ei:
        _w(store, key=key)
    assert ei.value.code == "section_key_invalid" and ei.value.status_code == 400
    assert store.writes == []


@pytest.mark.parametrize("key", ["summary", "background", "methods", "bmd_summary",
                                 "bm2_body-weight", "genomics_liver_male"])
def test_the_catalog_s_sections_are_accepted(key):
    assert sw.validate_section_key(ID, key) == key


def test_the_key_refusal_is_explained():
    with pytest.raises(sw.SectionRefusal) as ei:
        sw.validate_section_key(ID, "../x")
    body = explain(ei.value)["error"]
    assert body["code"] == "section_key_invalid" and body["status"] == 400
    assert body["message"] == "'../x' is not a section of this report"
    assert body["say"] == "There is no section by that name in this report."


# --- rule 2: absent → written as v1, with an event -------------------------

def test_a_new_section_is_written_with_an_event():
    store = FakeSectionStore()
    out = _w(store)
    assert out["outcome"] == "written" and out["version"] == 1 and out["archived"] is None
    e = store.last_event("summary")
    assert e["v"] == 2 and e["section"] == "summary" and e["version"] == 1
    assert (e["cause"], e["status"], e["act"], e["actor"], e["author"]) == (
        "generate", "draft", "summary", "system", "generated")
    assert e["changed"] is True and e["applied"] is True and e["user"] is None
    assert e["content_hash"] == content_hash(store.sections["summary"])


# --- rule 3: unchanged → nothing --------------------------------------------

def test_unchanged_content_writes_nothing_and_records_nothing():
    store = FakeSectionStore({"summary": {"paragraphs": ["new"], "source": "generated",
                                          "approved": True, "facts": ["final", "protected"],
                                          "version": 3}})
    out = _w(store)
    assert out["outcome"] == "unchanged" and out["version"] == 3
    assert store.writes == [] and store.events == {}
    assert store.sections["summary"]["approved"] is True


# --- rule 4: owned + system → held ------------------------------------------

@pytest.mark.parametrize("owned", [
    {"approved": True, "facts": ["final", "protected"]},
    {"approved": False, "facts": ["protected"]},          # released (C2 D1)
    {"user_edited": True},
    {"source": "ingested"},
])
def test_a_machine_never_overwrites_owned_content(owned):
    prior = {"paragraphs": ["mine"], "source": "generated", "version": 2, **owned}
    store = FakeSectionStore({"summary": prior})
    out = _w(store)
    assert out["outcome"] == "held" and out["version"] == 2
    assert store.sections["summary"]["paragraphs"] == ["mine"]
    assert store.writes == []
    e = store.last_event("summary")
    assert (e["cause"], e["applied"], e["changed"], e["version"]) == ("hold", False, False, 2)
    assert e["held_hash"] == content_hash({"paragraphs": ["new"], "source": "generated"})


# --- rule 5: owned + person, no force → section_owned -----------------------

def test_a_person_s_write_over_owned_content_is_refused():
    store = FakeSectionStore({"summary": {"paragraphs": ["mine"], "approved": True, "version": 1}})
    with pytest.raises(sw.SectionRefusal) as ei:
        _w(store, actor="person", act="use_run")
    assert ei.value.code == "section_owned" and ei.value.status_code == 409
    assert ei.value.message == ("'summary' is approved or protected; use_run would replace its "
                                "text. Release it first, with a reason.")
    assert store.writes == [] and store.events == {}
    body = explain(ei.value)["error"]
    assert body["code"] == "section_owned" and body["fix"] == "D1"


def test_a_person_s_explicit_act_replaces_a_released_section():
    # D1 + D6: released = PROTECTED stands (no machine replaces it), but the
    # person who released it may now replace it; the released text is archived.
    released = {"paragraphs": ["mine"], "approved": False, "facts": ["protected"], "version": 2}
    store = FakeSectionStore({"summary": released})
    out = _w(store, actor="person", act="use_run", author="model")
    assert out["outcome"] == "written" and out["version"] == 3
    assert store.archives["summary"][0][1] == released
    assert "forced" not in store.last_event("summary")


# --- rule 6: force needs a reason --------------------------------------------

@pytest.mark.parametrize("reason", [None, "", "   "])
def test_a_forced_write_needs_a_reason(reason):
    store = FakeSectionStore({"summary": {"paragraphs": ["mine"], "approved": True, "version": 1}})
    with pytest.raises(sw.SectionRefusal) as ei:
        _w(store, actor="person", act="background", force=True, reason=reason)
    assert ei.value.code == "reason_required" and ei.value.status_code == 400
    assert ei.value.message == "A reason is required to background 'summary'"
    assert store.writes == []


def test_a_forced_write_with_a_reason_archives_then_writes():
    store = FakeSectionStore({"summary": {"paragraphs": ["mine"], "approved": True, "version": 1}})
    out = _w(store, actor="person", act="background", force=True, reason="  new sources  ")
    assert out["outcome"] == "written" and out["version"] == 2 and out["prior_version"] == 1
    assert store.archives["summary"][0][1]["paragraphs"] == ["mine"]
    e = store.last_event("summary")
    assert e["reason"] == "new sources" and e["forced"] is True
    assert e["archived"] == out["archived"] == store.archives["summary"][0][0]


# --- rule 7: unowned + changed → archive, write, event ----------------------

def test_changed_unowned_content_is_archived_before_it_is_replaced():
    store = FakeSectionStore({"summary": {"paragraphs": ["old"], "source": "generated", "version": 4}})
    out = _w(store)
    assert out["outcome"] == "written" and out["version"] == 5
    assert store.archives["summary"][0][1]["paragraphs"] == ["old"]
    assert store.last_event("summary")["prior_version"] == 4


def test_two_overwrites_keep_both_archives():
    # I2: every content-changing overwrite archives the prior first.
    store = FakeSectionStore()
    for text in ("a", "b", "c"):
        _w(store, content={"paragraphs": [text], "source": "generated"})
    assert [d["paragraphs"] for _n, d in store.list_archived(ID, "summary")] == [["a"], ["b"]]
    assert [e["version"] for e in store.events["summary"]] == [1, 2, 3]


# --- D2/A1: an owned apical section whose content changed -------------------

def test_an_approved_apical_section_whose_numbers_changed_is_knocked_down_with_a_record():
    prior = {"title": "Body Weight", "tables_json": {"rows": [1]}, "source": "generated",
             "approved": True, "approved_at": "t", "facts": ["final", "protected"], "version": 3}
    store = FakeSectionStore({"bm2_body-weight": prior})
    out = sw.write_section(ID, "bm2_body-weight",
                           {"title": "Body Weight", "tables_json": {"rows": [2]},
                            "source": "generated", "approved": False},
                           store, act="materialize", actor="system", author="generated",
                           on_owned=sw.REVIEW, review={"why": "numbers_changed", "flips": []})
    assert out["outcome"] == "needs_review" and out["version"] == 4
    now = store.sections["bm2_body-weight"]
    assert now["approved"] is False and "approved_at" not in now
    assert now["facts"] == ["protected"]                    # FINAL withdrawn, PROTECTED stands
    assert now["review"] == {"why": "numbers_changed", "since_version": 3, "flips": []}
    assert "wording_review" not in now and "stale" not in now
    assert store.archives["bm2_body-weight"][0][1]["approved"] is True
    e = store.last_event("bm2_body-weight")
    assert (e["cause"], e["status"], e["act"], e["actor"]) == (
        "reprocess", "needs-re-bless", "materialize", "system")
    assert e["review"] == {"why": "numbers_changed", "flips": []}


# --- discard and history ------------------------------------------------------

def test_discard_archives_deletes_and_records():
    store = FakeSectionStore({"summary": {"paragraphs": ["x"], "source": "generated", "version": 2}})
    out = sw.discard(ID, "summary", store, act="discard", actor="person", reason="wrong study")
    assert out["version"] == 2 and out["archived"]
    assert "summary" not in store.sections
    e = store.last_event("summary")
    assert (e["cause"], e["status"], e["reason"], e["archived"]) == (
        "discard", "discarded", "wrong study", out["archived"])
    hist = sw.section_history(ID, "summary", store)          # works after a discard
    assert hist["current_version"] is None
    assert hist["versions"][0]["archived"] == out["archived"] and hist["versions"][0]["retrievable"]
    assert sw.read_version(ID, "summary", 2, store)["paragraphs"] == ["x"]


def test_history_reports_a_version_whose_text_was_lost():
    store = FakeSectionStore({"summary": {"paragraphs": ["x"], "version": 3}})
    store.events["summary"] = [{"version": 1, "cause": "edit", "status": "blessed", "ts": "a"},
                               {"version": 3, "cause": "edit", "status": "blessed", "ts": "b"}]
    hist = sw.section_history(ID, "summary", store)
    v1 = next(v for v in hist["versions"] if v["version"] == 1)
    assert v1["archived"] is None and v1["retrievable"] is False
    assert hist["current_version"] == 3 and hist["current_status"] == "blessed"
    with pytest.raises(sw.SectionRefusal) as ei:
        sw.read_version(ID, "summary", 1, store)
    assert ei.value.code == "version_content_missing" and ei.value.status_code == 409
    with pytest.raises(sw.SectionRefusal) as ei:
        sw.read_version(ID, "summary", 9, store)
    assert ei.value.code == "version_not_found" and ei.value.status_code == 404


def test_history_of_a_section_that_never_existed_is_not_found():
    with pytest.raises(sw.SectionRefusal) as ei:
        sw.section_history(ID, "summary", FakeSectionStore())
    assert ei.value.code == "section_not_found"
