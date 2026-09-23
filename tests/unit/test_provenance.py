"""
Unit tests for common.provenance — the per-request section-fate side channel.

Pins the load-bearing guarantees: events accumulate under a request context, two
concurrent contexts never bleed, flush writes a well-formed JSONL line to the session
dir, and every operation is fail-soft (a logging error never propagates into the caller,
because an instrumentation point must not be able to break the request it observes).
"""

import json

import pytest

from common import provenance


def test_record_accumulates_under_context():
    with provenance.request_context("req1"):
        provenance.record("cache_hit", dtxsid="X", unit="sections", hash="abc")
        provenance.record("disk_read", dtxsid="X", unit="bm2_liver", bytes=123)
        events = provenance._events.get()
        assert [e["event"] for e in events] == ["cache_hit", "disk_read"]
        assert all(e["request_id"] == "req1" for e in events)
        assert events[0]["unit"] == "sections" and events[1]["bytes"] == 123


def test_context_isolation():
    # A record outside any context has nowhere to accumulate (sink is None) but must
    # not raise — the live log line still emits.
    provenance.record("cache_miss", dtxsid="X", unit="ntp")  # no context — no raise
    assert provenance._events.get() is None

    with provenance.request_context("A"):
        provenance.record("cache_hit", dtxsid="X", unit="a")
        assert provenance.current_request_id() == "A"
    # Context cleanly reset on exit.
    assert provenance.current_request_id() is None
    assert provenance._events.get() is None


def test_flush_writes_jsonl(tmp_path, monkeypatch):
    import common.paths as paths_mod

    monkeypatch.setattr(paths_mod, "SESSIONS_DIR", tmp_path)
    dtxsid = "DTXSID_PROV"
    (tmp_path / dtxsid).mkdir()

    with provenance.request_context("req42"):
        provenance.record("cache_hit", dtxsid=dtxsid, unit="sections", hash="h")
        provenance.record("disk_read", dtxsid=dtxsid, unit="bm2_x", bytes=10, ms=0.5)
        provenance.flush(dtxsid, path="/api/session/" + dtxsid, total_ms=12.3)

    lines = (tmp_path / dtxsid / ".provenance.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["request_id"] == "req42"
    assert rec["dtxsid"] == dtxsid
    assert rec["path"] == "/api/session/" + dtxsid
    assert rec["total_ms"] == 12.3
    assert [e["event"] for e in rec["events"]] == ["cache_hit", "disk_read"]


def test_flush_appends(tmp_path, monkeypatch):
    import common.paths as paths_mod

    monkeypatch.setattr(paths_mod, "SESSIONS_DIR", tmp_path)
    dtxsid = "DTXSID_PROV"
    (tmp_path / dtxsid).mkdir()

    for rid in ("r1", "r2"):
        with provenance.request_context(rid):
            provenance.record("cache_hit", dtxsid=dtxsid, unit="u")
            provenance.flush(dtxsid)

    lines = (tmp_path / dtxsid / ".provenance.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(x)["request_id"] for x in lines] == ["r1", "r2"]


def test_flush_noop_without_events(tmp_path, monkeypatch):
    import common.paths as paths_mod

    monkeypatch.setattr(paths_mod, "SESSIONS_DIR", tmp_path)
    dtxsid = "DTXSID_PROV"
    (tmp_path / dtxsid).mkdir()
    with provenance.request_context("empty"):
        provenance.flush(dtxsid)  # no events recorded
    assert not (tmp_path / dtxsid / ".provenance.jsonl").exists()


def test_flush_fail_soft_on_missing_dir(tmp_path, monkeypatch):
    # An unwritable / absent session dir must not raise — the audit trail is
    # best-effort, never load-bearing.
    import common.paths as paths_mod

    monkeypatch.setattr(paths_mod, "SESSIONS_DIR", tmp_path)
    with provenance.request_context("req"):
        provenance.record("cache_hit", dtxsid="DTXSID_ABSENT", unit="u")
        provenance.flush("DTXSID_ABSENT")  # dir doesn't exist — no raise, no file
    assert not (tmp_path / "DTXSID_ABSENT" / ".provenance.jsonl").exists()


def test_record_fail_soft_on_bad_field(monkeypatch):
    # A non-JSON-serializable field must not break record() (default=str handles it,
    # and the whole thing is wrapped fail-soft regardless).
    class Weird:
        pass

    with provenance.request_context("req"):
        provenance.record("cache_hit", dtxsid="X", weird=Weird())  # no raise
        assert provenance._events.get()[0]["event"] == "cache_hit"
