"""
The section-history primitive (C2 spec §3, "The primitive changes"):
pipeline.session_store archives a section under a name no other archive can
take, and numbers versions monotonically.

  * T7: archives were named after the section's `approved_at`, which a version
    keeps through an invalidation, so a later approve overwrote an earlier
    version's archive. Two overwrites in one second now keep both (I2).
  * T8: the version counter was "archives + 1", which restarted after a
    discard, so the version events then described the wrong text.
"""

import json

import pytest

from pipeline.session_store import (
    InvalidSectionKey,
    _VERSION_EVENT_KEY,
    archive_current,
    delete_section,
    list_archived,
    next_section_version,
    read_archived,
    read_version_history,
    save_section,
)

ID = "DTXSID_PRIM"


def _current(sessions_dir, key):
    return json.loads((sessions_dir / ID / f"{key}.json").read_text())


def test_two_overwrites_with_the_same_approved_at_keep_both_archives(sessions_dir):
    # T7: the same approved_at on every version (an invalidation keeps it).
    for text in ("v1", "v2", "v3"):
        save_section(ID, "summary", {"paragraphs": [text], "approved_at": "2026-01-01T00:00:00+00:00"})
    archived = list_archived(ID, "summary")
    assert [d["version"] for _n, d in archived] == [1, 2]
    assert [d["paragraphs"] for _n, d in archived] == [["v1"], ["v2"]]
    assert len({n for n, _d in archived}) == 2
    assert all(n.startswith(f"v{d['version']:04d}-") for n, d in archived)


def test_archives_within_one_microsecond_do_not_collide(sessions_dir, monkeypatch):
    import pipeline.session_store as ss
    monkeypatch.setattr(ss, "now_iso", lambda: "2026-01-01T00:00:00+00:00")
    save_section(ID, "summary", {"paragraphs": ["a"]})
    first = archive_current(ID, "summary")
    second = archive_current(ID, "summary")
    assert first != second
    assert len(list_archived(ID, "summary")) == 2


def test_version_numbers_never_repeat_after_a_discard(sessions_dir):
    # T8: a discard deletes the file and keeps history/.
    save_section(ID, "summary", {"paragraphs": ["one"],
                                 _VERSION_EVENT_KEY: {"cause": "edit", "status": "blessed"}})
    save_section(ID, "summary", {"paragraphs": ["two"],
                                 _VERSION_EVENT_KEY: {"cause": "edit", "status": "blessed"}})
    archive_current(ID, "summary")
    delete_section(ID, "summary")
    # The next save, archived or in place, is numbered above everything seen.
    save_section(ID, "summary", {"paragraphs": ["three"]}, archive=False)
    assert _current(sessions_dir, "summary")["version"] == 3
    save_section(ID, "summary", {"paragraphs": ["four"]})
    assert _current(sessions_dir, "summary")["version"] == 4


def test_the_counter_counts_events_without_archives(sessions_dir):
    # A version known only from the events (its text was lost to an old
    # collision) still blocks its number.
    hist = sessions_dir / ID / "history" / "summary"
    hist.mkdir(parents=True)
    (hist / "index.jsonl").write_text(json.dumps({"version": 7, "cause": "edit", "status": "blessed",
                                                  "ts": "t"}) + "\n")
    assert next_section_version(ID, "summary") == 8


def test_old_timestamp_named_archives_still_read(sessions_dir):
    hist = sessions_dir / ID / "history" / "background"
    hist.mkdir(parents=True)
    (hist / "2026-01-01T00-00-00+00-00.json").write_text(json.dumps({"version": 1, "paragraphs": ["old"]}))
    (sessions_dir / ID / "background.json").write_text(json.dumps({"version": 2, "paragraphs": ["new"]}))
    name, data = read_archived(ID, "background", 1)
    assert name == "2026-01-01T00-00-00+00-00.json" and data["paragraphs"] == ["old"]
    save_section(ID, "background", {"paragraphs": ["newer"]})
    assert _current(sessions_dir, "background")["version"] == 3
    assert [d["version"] for _n, d in list_archived(ID, "background")] == [1, 2]


def test_a_tagged_overwrite_records_what_it_archived(sessions_dir):
    save_section(ID, "summary", {"paragraphs": ["one"]})
    save_section(ID, "summary", {"paragraphs": ["two"], _VERSION_EVENT_KEY: {
        "cause": "generate", "status": "draft", "v": 2, "actor": "system"}})
    (event,) = read_version_history(ID, "summary")
    assert event["version"] == 2 and event["prior_version"] == 1
    assert event["archived"] == list_archived(ID, "summary")[0][0]
    assert event["v"] == 2 and event["actor"] == "system"   # format-2 fields ride along


def test_archive_current_of_an_absent_section_is_none(sessions_dir):
    (sessions_dir / ID).mkdir(parents=True)
    assert archive_current(ID, "summary") is None


@pytest.mark.parametrize("key", ["../DTXSID_OTHER/summary", "a/b", "", ".", "x.json"])
def test_a_key_that_is_not_a_file_name_is_refused(sessions_dir, key):
    with pytest.raises(InvalidSectionKey):
        save_section(ID, key, {"x": 1})
    with pytest.raises(InvalidSectionKey):
        read_version_history(ID, key)
    with pytest.raises(InvalidSectionKey):
        delete_section(ID, key)
