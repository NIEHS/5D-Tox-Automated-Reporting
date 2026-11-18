"""A .zip upload is all-or-nothing (independent review, 2026-11-16): members
are staged and checked for name collisions before the session changes, and a
failure partway restores the session's files."""

import io
import zipfile
from unittest import mock

DTX = "DTXSID50469320"


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _upload(client, data: bytes):
    return client.post(f"/api/upload-zip?dtxsid={DTX}",
                       files={"file": ("pool.zip", data, "application/zip")})


def _files(sessions_dir):
    d = sessions_dir / DTX / "files"
    return {p.name: p.read_bytes() for p in d.iterdir()} if d.exists() else {}


def test_same_named_members_refuse_the_whole_archive(client, sessions_dir):
    (sessions_dir / DTX / "files").mkdir(parents=True)
    r = _upload(client, _zip({"a/body.csv": b"1", "b/body.csv": b"2", "organ.csv": b"3"}))
    assert r.status_code == 409
    assert r.json()["collisions"] == {"body.csv": ["a/body.csv", "b/body.csv"]}
    assert _files(sessions_dir) == {}


def test_a_good_archive_lands(client, sessions_dir):
    (sessions_dir / DTX / "files").mkdir(parents=True)
    r = _upload(client, _zip({"x/body.csv": b"1", "organ.csv": b"3", "readme.md": b"-"}))
    assert r.status_code == 200, r.text
    assert sorted(f["filename"] for f in r.json()["other_files"]) == ["body.csv", "organ.csv"]
    assert r.json()["skipped"] == ["readme.md"]
    assert _files(sessions_dir) == {"body.csv": b"1", "organ.csv": b"3"}


def test_a_failure_partway_restores_the_session_files(client, sessions_dir):
    files = sessions_dir / DTX / "files"
    files.mkdir(parents=True)
    (files / "body.csv").write_bytes(b"old")
    calls = []

    def flaky(file_id, name, path, kind, dtxsid):
        calls.append(name)
        if len(calls) == 2:
            raise RuntimeError("fingerprint failed")
        return mock.MagicMock()

    with mock.patch("web_routes.upload_routes.fingerprint_and_store", flaky), \
         mock.patch("web_routes.upload_routes.run_lightweight_validation", return_value=[]):
        r = _upload(client, _zip({"body.csv": b"new", "organ.csv": b"3"}))
    assert r.status_code == 500 and "rolled back" in r.json()["error"]
    assert _files(sessions_dir) == {"body.csv": b"old"}
