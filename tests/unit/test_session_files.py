"""
Session JSON reads: absent is "not available", unreadable is an error.

common.session_files and the session_store readers built on it replaced ~a
dozen `try: json.loads(...) except Exception: pass` sites that turned a corrupt
identity.json / animal_report.json / override store into `{}` without a word.
"""

import json
import os

import pytest

from common.dtxsid import InvalidDtxsid
from common.session_files import UnreadableSessionFile, read_session_json
from pipeline.session_store import (
    NARRATIVE_OVERRIDES_FILE, latest_session_cache, read_narrative_overrides,
)

DTXSID = "DTXSID_TEST"


@pytest.fixture
def session(sessions_dir):
    d = sessions_dir / DTXSID
    d.mkdir()
    return d


def test_absent_file_reads_as_none(session):
    assert read_session_json(DTXSID, "identity.json") is None


def test_present_file_is_parsed(session):
    (session / "identity.json").write_text(json.dumps({"name": "PFHxSAm"}))
    assert read_session_json(DTXSID, "identity.json") == {"name": "PFHxSAm"}


def test_unreadable_file_raises_naming_it(session):
    (session / "identity.json").write_text('{"name": "PFHx')   # truncated write
    with pytest.raises(UnreadableSessionFile, match="DTXSID_TEST/identity.json"):
        read_session_json(DTXSID, "identity.json")


def test_read_does_not_create_the_session(sessions_dir):
    assert read_session_json("DTXSID_NONE", "identity.json") is None
    assert not (sessions_dir / "DTXSID_NONE").exists()


def test_bad_id_is_rejected():
    with pytest.raises(InvalidDtxsid):
        read_session_json("../etc", "identity.json")


def test_overrides_absent_are_empty_buckets(session):
    assert read_narrative_overrides(session) == {"gene_set": {}, "gene_bmd": {}}


def test_overrides_corrupt_raise(session):
    (session / NARRATIVE_OVERRIDES_FILE).write_text("{not json")
    with pytest.raises(UnreadableSessionFile):
        read_narrative_overrides(session)


def test_latest_cache_is_newest_not_lexically_first(session):
    old, new = session / "_cache_genomics_ffff.json", session / "_cache_genomics_0000.json"
    old.write_text("{}")
    new.write_text("{}")
    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))
    assert latest_session_cache(session, "_cache_genomics_*.json") == new


def test_lock_does_not_overwrite_a_corrupt_override_store(client, sessions_dir):
    """The Lock endpoint read-modify-writes the store; reading a corrupt one as
    empty used to replace every other organ's locked text with this one edit."""
    d = sessions_dir / DTXSID
    d.mkdir()
    store = d / NARRATIVE_OVERRIDES_FILE
    store.write_text('{"gene_set": {"liver": ["locked text"]')     # truncated
    r = client.post(
        f"/api/session/{DTXSID}/genomics-narrative-override",
        json={"kind": "gene_set", "organ": "kidney", "paragraphs": ["new"]},
    )
    assert r.status_code == 422
    assert NARRATIVE_OVERRIDES_FILE in r.json()["error"]
    assert store.read_text() == '{"gene_set": {"liver": ["locked text"]'
