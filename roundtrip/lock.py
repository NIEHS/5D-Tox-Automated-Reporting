"""
edit_lock.py — single-writer checkout lock per report (ADR-0005).

Overleaf is real-time collaborative and exposes no API to force a project to a
single editor, so we cannot lock Overleaf itself.  What we CAN do — and what
actually prevents the damage — is a lock at OUR layer: while one app user has a
report "open in Overleaf", the app holds a checkout lock so other users can't
start a second editing session, and (once those actions exist) the app won't
push/regenerate over the in-progress edits.  This keeps the round-trip
single-writer, which the reconciler assumes.

Identity is the coarse ?user= the gate middleware already uses (background_server
user_gate_middleware); in open/local mode there is no user, so the holder is
recorded as "anonymous".

The lock is advisory and app-level: it governs app-mediated editing/sync, not
whoever already holds the Overleaf link.  That last mile is covered by how the
Overleaf project is shared.  A stale lock (holder closed their tab without
releasing) can be force-released; `since` lets the UI show its age.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import json
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# parent.parent: this module lives one level down in the roundtrip/ package, so
# the default storage root resolves to <repo>/sessions (overridable via
# sessions_dir=).
_DEFAULT_SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
_LOCK_FILENAME = "_edit_lock.json"

# Holder recorded when the user gate is disabled (no ?user= available).
_ANON = "anonymous"


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------

def _lock_path(dtxsid: str, sessions_dir: "Path | None") -> Path:
    base = Path(sessions_dir) if sessions_dir is not None else _DEFAULT_SESSIONS_DIR
    return base / dtxsid / _LOCK_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_user(user: "str | None") -> str:
    """Coerce a possibly-empty ?user= into a stable holder id."""
    return (user or "").strip() or _ANON


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_lock(dtxsid: str, *, sessions_dir: "Path | None" = None) -> "dict | None":
    """Return the current lock {locked_by, since}, or None if the report is free."""
    path = _lock_path(dtxsid, sessions_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) and data.get("locked_by") else None
    except Exception:
        # A corrupt lock file must not wedge the report — treat as unlocked.
        return None


def acquire_lock(
    dtxsid: str,
    user: "str | None",
    *,
    sessions_dir: "Path | None" = None,
) -> "tuple[bool, dict]":
    """
    Try to take the checkout lock for `user`.

    Returns (acquired, lock):
      - free, or already held by the SAME user → acquired=True (the lock is
        (re)written, refreshing `since` only on a fresh take);
      - held by ANOTHER user → acquired=False and the existing lock is returned
        unchanged (the caller surfaces "locked by X").
    """
    holder = _normalize_user(user)
    current = get_lock(dtxsid, sessions_dir=sessions_dir)
    if current and current.get("locked_by") != holder:
        return False, current
    # Free or ours: (re)write.  Preserve `since` if we already hold it so the
    # displayed age reflects when editing actually started.
    since = current["since"] if (current and current.get("locked_by") == holder) else _now_iso()
    lock = {"locked_by": holder, "since": since}
    path = _lock_path(dtxsid, sessions_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2) + "\n")
    return True, lock


def release_lock(
    dtxsid: str,
    user: "str | None",
    *,
    force: bool = False,
    sessions_dir: "Path | None" = None,
) -> bool:
    """
    Release the lock.  Succeeds when `user` is the holder, or when force=True
    (breaking a stale lock left by someone who closed their tab).  Returns True
    if a lock was removed, False if none / held by another and not forced.
    """
    holder = _normalize_user(user)
    current = get_lock(dtxsid, sessions_dir=sessions_dir)
    if current is None:
        return False
    if not force and current.get("locked_by") != holder:
        return False
    _lock_path(dtxsid, sessions_dir).unlink(missing_ok=True)
    return True
