"""
Session-id (DTXSID) validation — the path-traversal gate.

Before 2026-09-18 the `{dtxsid}` URL segment and body-supplied ids were used
verbatim as filesystem path components (`SESSIONS_DIR / dtxsid`), and
`/api/session/reset/{dtxsid}` called shutil.rmtree on the result, so a request
to `/api/session/reset/%2e%2e` (Starlette decodes it to "..") targeted the
PARENT of the sessions directory. These tests pin both layers of the fix:
the pure validator and the HTTP behavior through the real app.
"""

import pytest

from common.dtxsid import DTXSID_RE, InvalidDtxsid, is_valid_dtxsid, validate_dtxsid


@pytest.mark.parametrize("good", [
    "DTXSID50469320",          # a real EPA id
    "DTXSID_TEST",             # the test-suite convention
    "DTXSID_TEST_NO_SESSION",
    "DTXSIDTEST01",
    "DTXSID-alt_form-1",
])
def test_accepts_well_formed_ids(good):
    assert is_valid_dtxsid(good)
    assert validate_dtxsid(good) is good   # returned unchanged (drop-in wrapper)


@pytest.mark.parametrize("bad", [
    "..",
    "../DTXSID50469320",
    "DTXSID50469320/../../etc",
    "DTXSID50469320/files",
    "DTXSID50469320\\..",
    "DTXSID.50469320",
    "DTXSID 50469320",
    "DTXSID",                  # prefix only
    "dtxsid50469320",          # wrong case
    "XYZ50469320",             # wrong prefix
    "",
    "DTXSID" + "A" * 65,       # over the length cap
    "DTXSID5046\x009320",     # embedded NUL
])
def test_rejects_traversal_and_malformed_ids(bad):
    assert not is_valid_dtxsid(bad)
    with pytest.raises(InvalidDtxsid):
        validate_dtxsid(bad)


def test_rejects_non_strings():
    for v in (None, 123, ["DTXSID50469320"]):
        assert not is_valid_dtxsid(v)
        with pytest.raises(InvalidDtxsid):
            validate_dtxsid(v)


def test_regex_cannot_admit_a_path_separator_or_dot():
    """Structural guarantee, independent of the example lists above."""
    for ch in "/\\. \t\n":
        assert not DTXSID_RE.match(f"DTXSID1{ch}2")


# ---------------------------------------------------------------------------
# Through the app — the shapes an attacker would actually send
# ---------------------------------------------------------------------------

def test_reset_with_dotdot_segment_is_rejected_and_deletes_nothing(client, sessions_dir):
    """`/api/session/reset/%2e%2e` decodes to ".." — must be a 400 and must
    leave the sessions root (and its parent) untouched."""
    (sessions_dir / "DTXSID_KEEP").mkdir()
    sentinel = sessions_dir.parent / "sentinel.txt"
    sentinel.write_text("still here")

    resp = client.post("/api/session/reset/%2e%2e")

    assert resp.status_code == 400
    assert "invalid session id" in resp.json()["error"]
    assert sentinel.exists() and (sessions_dir / "DTXSID_KEEP").exists()


@pytest.mark.parametrize("path", [
    "/api/session/load/DTXSID..X",     # dot inside the id
    "/api/workflow/%2e%2e%2f%2e%2e/state",
    "/api/integrated/not-a-dtxsid",
    "/api/integrated/%2e%2e",
])
def test_bad_path_ids_never_reach_a_handler(client, path):
    resp = client.get(path)
    assert resp.status_code in (400, 404), (path, resp.status_code, resp.text[:200])
    if resp.status_code == 400:
        assert "invalid session id" in resp.json()["error"]


def test_body_supplied_traversal_id_is_rejected(client, sessions_dir):
    """Ids in JSON bodies bypass the path dependency, so the sink-level check
    (session_dir / SESSIONS_DIR wrappers) must catch them: nothing may be
    written outside the sessions root."""
    outside = sessions_dir.parent / "x"
    resp = client.post("/api/session/approve", json={
        "dtxsid": "../x",
        "section_type": "background",
        "data": {"paragraphs": ["p"], "references": []},
    })
    assert resp.status_code == 400
    assert "invalid session id" in resp.json()["error"]
    assert not outside.exists()


def test_good_path_id_still_reaches_the_handler(client):
    """Control: a well-formed id passes the dependency (404/200 from the
    handler itself, never the 400 validator shape)."""
    resp = client.get("/api/integrated/DTXSID_NOT_THERE")
    assert resp.status_code == 404
    assert "invalid session id" not in resp.text
