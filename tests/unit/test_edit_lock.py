r"""
test_edit_lock.py — single-writer checkout lock (ADR-0005).

Proves the lock semantics the "Open in Overleaf" flow relies on:
  - a free report can be acquired; the holder is recorded;
  - a SECOND user is blocked (acquire returns False with the existing holder);
  - the SAME user re-acquires idempotently, keeping the original `since`;
  - only the holder releases — others fail unless force=True (stale-lock break);
  - with no ?user= (open mode) the holder is "anonymous".
"""

import pytest

import roundtrip._io as rio
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


def test_failed_lock_write_preserves_prior_holder(tmp_path, monkeypatch):
    """
    A crash during the durable commit of a lock write must not corrupt the
    existing lock: get_lock keeps returning the prior holder, never None.

    Pre-fix (`path.write_text` directly) the target was truncated in place, so a
    failure mid-write left a garbage file that get_lock swallowed as unlocked —
    a second user could then steal the checkout.  The atomic write commits via
    os.replace, so a failure there leaves the original file untouched.
    """
    dt = "DTXSIDATOMIC"
    ok, lock = el.acquire_lock(dt, "alice", sessions_dir=tmp_path)
    assert ok

    # Simulate the durable-commit step failing.  Re-acquiring as the SAME holder
    # takes the write path (a different user would be blocked before any write),
    # so this both proves the atomic write is used AND exercises the failure
    # branch; the prior file must survive intact.
    monkeypatch.setattr(rio.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        el.acquire_lock(dt, "alice", sessions_dir=tmp_path)

    monkeypatch.undo()
    held = el.get_lock(dt, sessions_dir=tmp_path)
    assert held is not None and held["locked_by"] == "alice"
    assert held["since"] == lock["since"]
    # No orphaned temp file left beside the lock.
    leftovers = list((tmp_path / dt).glob("*.tmp"))
    assert leftovers == []
