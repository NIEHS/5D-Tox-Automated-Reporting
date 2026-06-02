"""
document_overrides.py — per-node user-owned content overrides (ADR-0005).

When a human edits the generated report in Overleaf, those edits are pulled back
and reconciled into a per-region override store keyed by the SAME anchor id the
LaTeX generator emits as sentinel comments (node grain "node.id", or
sub-addressable genomics item grain "<node-id>::<item-id>").  The renderer then
emits the human's version verbatim instead of regenerating over it — the
"override wins, never silently recomputed" rule, generalized from the genomics
user-owned narrative store to every anchored region.

Why this module is transport-agnostic
--------------------------------------
The store knows nothing about WHERE an edit came from.  It is written by the
reconciler regardless of whether the two report.tex revisions being diffed came
from a plain working-tree edit (the simplest dev loop), a local git "stand-in"
for Overleaf (the next step), or the real Overleaf git-bridge once access lands.
All three feed the same {anchor_id -> override record} mapping.

Storage
-------
One JSON file per session, sessions/<dtxsid>/_document_overrides.json:

    {
      "version": 1,
      "overrides": {
        "<anchor_id>": {
          "latex_region": "<the edited LaTeX region, as it sits between the
                            generator's begin/end sentinels>",
          "base_hash":    "<region_hash() of the GENERATED region this override
                            was derived from — used to detect that the
                            underlying data has since drifted>",
          "edited_at":    "<ISO-8601 timestamp>",
          "source":       "overleaf" | "stand-in" | "manual"
        },
        ...
      }
    }

Stale detection: at render time the generator recomputes region_hash() of the
freshly generated region and compares it to the stored base_hash.  A mismatch
means the data changed under the user's edit — the override still wins (it is
emitted), but the region is flagged for human review rather than clobbered.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
# hashlib  — deterministic region fingerprint shared with the renderer's
#            stale-check (single source of truth for the hash).
# datetime — default edit timestamp.
# json/pathlib — the on-disk store.

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Session caches live under <repo>/sessions/<dtxsid>/ — resolved relative to
# this module so callers can run from any working directory.
_DEFAULT_SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"

# Per-session override file name (sits alongside the other session-cache JSON).
_OVERRIDES_FILENAME = "_document_overrides.json"

# Bump if the on-disk schema changes incompatibly.
_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------

def _store_path(dtxsid: str, sessions_dir: Path) -> Path:
    """Filesystem path of a session's override store (accepts a str path too)."""
    return Path(sessions_dir) / dtxsid / _OVERRIDES_FILENAME


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string (the default edit timestamp)."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def region_hash(text: str) -> str:
    """
    Deterministic fingerprint of a rendered region.

    The reconciler records this over the GENERATED region when it captures an
    override; the renderer recomputes it over the freshly generated region to
    decide whether the underlying data has drifted.  Both sides MUST use this
    one function so the hashes are comparable — that is the whole point of
    defining it here rather than in either caller.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_overrides(
    dtxsid: str,
    *,
    sessions_dir: Path = _DEFAULT_SESSIONS_DIR,
) -> "dict[str, dict]":
    """
    Return a session's override mapping {anchor_id -> record}.

    Empty dict when the store is absent or unreadable — a session with no human
    edits simply has no overrides, which the renderer treats as "regenerate
    everything" (the byte-identical default).
    """
    path = _store_path(dtxsid, sessions_dir)
    if not path.exists():
        return {}
    try:
        blob = json.loads(path.read_text())
    except Exception:
        # A corrupt store must not break rendering; treat as "no overrides".
        return {}
    overrides = blob.get("overrides")
    return overrides if isinstance(overrides, dict) else {}


def save_overrides(
    dtxsid: str,
    overrides: "dict[str, dict]",
    *,
    sessions_dir: Path = _DEFAULT_SESSIONS_DIR,
) -> Path:
    """
    Write the full override mapping back to the session store (overwriting).

    Keys are sorted so the file is stable across writes (meaningful diffs when
    the store is committed).  Returns the path written.
    """
    path = _store_path(dtxsid, sessions_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = {
        "version": _SCHEMA_VERSION,
        "overrides": {k: overrides[k] for k in sorted(overrides)},
    }
    path.write_text(json.dumps(blob, indent=2, ensure_ascii=False) + "\n")
    return path


def set_override(
    dtxsid: str,
    anchor_id: str,
    latex_region: str,
    base_hash: str,
    *,
    source: str = "overleaf",
    edited_at: "str | None" = None,
    sessions_dir: Path = _DEFAULT_SESSIONS_DIR,
) -> dict:
    """
    Record (or replace) the override for one anchor id and persist the store.

    Args:
        anchor_id:    the generator's anchor key (node.id or "<node>::<item>").
        latex_region: the edited LaTeX region (what sits between the sentinels).
        base_hash:    region_hash() of the GENERATED region it was derived from.
        source:       provenance tag — "overleaf" / "stand-in" / "manual".
        edited_at:    ISO timestamp; defaults to now (UTC).

    Returns the stored record.
    """
    overrides = load_overrides(dtxsid, sessions_dir=sessions_dir)
    record = {
        "latex_region": latex_region,
        "base_hash": base_hash,
        "edited_at": edited_at or _now_iso(),
        "source": source,
    }
    overrides[anchor_id] = record
    save_overrides(dtxsid, overrides, sessions_dir=sessions_dir)
    return record


def clear_override(
    dtxsid: str,
    anchor_id: str,
    *,
    sessions_dir: Path = _DEFAULT_SESSIONS_DIR,
) -> bool:
    """
    Drop the override for one anchor id (the explicit "regenerate" escape
    hatch — the next render falls back to freshly generated content).

    Returns True if an override was present and removed, False otherwise.
    """
    overrides = load_overrides(dtxsid, sessions_dir=sessions_dir)
    if anchor_id not in overrides:
        return False
    del overrides[anchor_id]
    save_overrides(dtxsid, overrides, sessions_dir=sessions_dir)
    return True


def get_override(
    dtxsid: str,
    anchor_id: str,
    *,
    sessions_dir: Path = _DEFAULT_SESSIONS_DIR,
) -> "dict | None":
    """Return one override record, or None if the anchor has no override."""
    return load_overrides(dtxsid, sessions_dir=sessions_dir).get(anchor_id)
