r"""
test_edit_lock.py — single-writer checkout lock (ADR-0005).

Proves the lock semantics the "Open in Overleaf" flow relies on:
  - a free report can be acquired; the holder is recorded;
  - a SECOND user is blocked (acquire returns False with the existing holder);
  - the SAME user re-acquires idempotently, keeping the original `since`;
  - only the holder releases — others fail unless force=True (stale-lock break);
  - with no ?user= (open mode) the holder is "anonymous".
"""

import roundtrip.lock as el


def test_acquire_blocks_other_and_releases(tmp_path):
    dt = "DTXSIDTEST"
    assert el.get_lock(dt, sessions_dir=tmp_path) is None

    ok, lock = el.acquire_lock(dt, "alice", sessions_dir=tmp_path)
    assert ok and lock["locked_by"] == "alice"

    # bob is blocked; the existing holder is reported.
    ok2, held = el.acquire_lock(dt, "bob", sessions_dir=tmp_path)
    assert ok2 is False
    assert held["locked_by"] == "alice"

    # alice re-acquires idempotently — same since (when editing started).
    ok3, lock3 = el.acquire_lock(dt, "alice", sessions_dir=tmp_path)
    assert ok3 and lock3["since"] == lock["since"]

    # bob can't release alice's lock; alice can.
    assert el.release_lock(dt, "bob", sessions_dir=tmp_path) is False
    assert el.release_lock(dt, "alice", sessions_dir=tmp_path) is True
    assert el.get_lock(dt, sessions_dir=tmp_path) is None


def test_force_release_breaks_stale_lock(tmp_path):
    dt = "DTXSIDSTALE"
    el.acquire_lock(dt, "alice", sessions_dir=tmp_path)
    assert el.release_lock(dt, "bob", sessions_dir=tmp_path) is False
    assert el.release_lock(dt, "bob", force=True, sessions_dir=tmp_path) is True
    assert el.get_lock(dt, sessions_dir=tmp_path) is None


def test_anonymous_holder_in_open_mode(tmp_path):
    dt = "DTXSIDANON"
    ok, lock = el.acquire_lock(dt, "", sessions_dir=tmp_path)
    assert ok and lock["locked_by"] == "anonymous"
    # None and "" both normalise to the same anonymous holder → re-acquire ok.
    ok2, _ = el.acquire_lock(dt, None, sessions_dir=tmp_path)
    assert ok2


def test_release_nonexistent_is_false(tmp_path):
    assert el.release_lock("DTXSIDNONE", "alice", sessions_dir=tmp_path) is False
