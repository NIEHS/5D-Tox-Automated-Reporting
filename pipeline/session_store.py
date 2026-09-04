"""
session_store.py — Session persistence and version history for per-chemical data.

Approved sections are persisted to disk as JSON files under sessions/{dtxsid}/.
This allows the user to close the browser, restart the server, and pick up
exactly where they left off — the UI auto-restores on DTXSID resolution.

Version history is maintained in sessions/{dtxsid}/history/{section_key}/,
where each previously-approved version is archived with a timestamped filename
before the current version is overwritten.  This provides full audit trail and
undo capability.

Layout:
    sessions/
        {dtxsid}/
            meta.json                          — created/updated timestamps
            {section_key}.json                 — current approved version
            files/                             — uploaded .bm2 files
            history/
                {section_key}/
                    {iso_timestamp}.json       — previous versions
        _style_profile.json                    — global writing style rules

Note: the LMDB bm2 cache lives at /tmp/_bm2_cache (not under sessions/)
because LMDB's mmap()/flock() are incompatible with GCS FUSE mounts.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Root directory for all session data.  Defaults to ./sessions/ (relative to
# this source file), but can be overridden via the SESSIONS_DIR environment
# variable — used when mounting a GCS bucket locally via gcsfuse or when
# Cloud Run's GCS FUSE volume is mounted at a non-default path.
SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", Path(__file__).parent.parent / "sessions"))

# Cause-tagged version-event manifest (Phase 4, dual-cause versioned snapshots).
# Append-only JSONL log, one file per section, colocated with that section's
# archived versions under history/{section_key}/.  Each line records WHICH act
# minted (or re-blessed) a version — `edit` (a human accepted) vs `reprocess`
# (the system rewrote on new data) — plus the version number, a status, and a
# timestamp.  Deliberately `.jsonl` (not `.json`): the version-count glob in
# save_section and the version-list glob in the history route both match
# `*.json`, and a `.jsonl` file is invisible to them, so the manifest can live
# beside the archives without inflating version numbers.  Absent on old sessions
# → read_version_history returns [] (missing cause = unknown, never a crash).
_VERSION_INDEX = "index.jsonl"

# The transient marker a caller stamps onto `data` to request a cause-tagged
# version event.  save_section POPS it before writing (so it never persists in
# the section JSON) and, when present, appends one manifest line for the version
# it just wrote.  Absent → save_section behaves exactly as before (no manifest
# side effect), so every existing caller (auto-save, unapprove, restore) stays
# byte-identical and old goldens are untouched.  Shape: {"cause", "status"}.
_VERSION_EVENT_KEY = "_version_event"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def session_dir(dtxsid: str) -> Path:
    """
    Return the session directory for a given DTXSID, creating it if needed.

    Each chemical gets its own directory under sessions/ (e.g.,
    sessions/DTXSID6020430/).  The directory is created on first approve.
    """
    d = SESSIONS_DIR / dtxsid
    d.mkdir(parents=True, exist_ok=True)
    return d


def bm2_slug(filename: str) -> str:
    """
    Slugify a .bm2 filename for use as a JSON key / filename stem.

    Strips the compound prefix (everything before the first hyphen), lowercases,
    replaces spaces/non-alphanum with hyphens, and strips the .bm2 extension.

    Example:
        'P3MP-Organ and Body Weights.bm2' → 'organ-and-body-weights'
        'P3MP-Clinical Pathology.bm2'     → 'clinical-pathology'
    """
    # Remove .bm2 extension
    stem = filename.rsplit(".bm2", 1)[0]
    # Drop the compound prefix before the first hyphen (e.g. "P3MP-")
    if "-" in stem:
        stem = stem.split("-", 1)[1]
    # Lowercase, replace non-alphanumeric runs with single hyphens, strip edges
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug


def safe_filename(name: str) -> str:
    """
    Sanitize a chemical name for use as a filename.

    Replaces non-alphanumeric characters (except spaces, hyphens, and
    underscores) with underscores.  Used when building download filenames
    for exported reports (the Overleaf .zip bundle).

    Args:
        name: The chemical name (e.g., "1,2-Dichlorobenzene").

    Returns:
        A filesystem-safe string (e.g., "1_2-Dichlorobenzene").
    """
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in name)


# ---------------------------------------------------------------------------
# Section persistence — write/read/delete session JSON files
# ---------------------------------------------------------------------------

def save_section(
    dtxsid: str,
    section_key: str,
    data: dict,
    archive: bool = True,
) -> None:
    """
    Write data as JSON to sessions/{dtxsid}/{section_key}.json.

    By default ('archive=True'), the previous version is copied into
    history/ before being overwritten and the new save gets an
    incremented version number — appropriate for approve actions and
    significant content updates.

    Pass 'archive=False' for in-place updates that should NOT create a
    new history entry (e.g., flipping the 'approved' flag, auto-save
    on generation).  In that mode the existing version number is
    preserved and no history file is written.

    Cause-tagged versions (Phase 4): a caller may stamp a transient
    '_version_event' = {"cause", "status"} onto `data` to record WHY this
    version came to be — "edit" (a human accepted) born "blessed", or
    "reprocess" (the system rewrote on new data) born "needs-re-bless".
    save_section pops that marker (it never persists in the section JSON)
    and appends one line to the section's version manifest for the version it
    just wrote.  With archive=False the version number is preserved, so a
    re-accept records a status flip (needs-re-bless → blessed) against the SAME
    version rather than minting a new one.  No marker → no manifest write, so
    unmarked callers (auto-save, unapprove, restore) are byte-unaffected.

    Version history layout:
        sessions/{dtxsid}/history/{section_key}/{safe_timestamp}.json  — versions
        sessions/{dtxsid}/history/{section_key}/index.jsonl            — cause log
    The current file ({section_key}.json) is always the latest version.
    """
    # Pull the transient cause marker off `data` before anything is written so
    # it never lands in the persisted section JSON (or an archived copy).
    version_event = data.pop(_VERSION_EVENT_KEY, None)

    d = session_dir(dtxsid)
    current_path = d / f"{section_key}.json"
    history_dir = d / "history" / section_key

    if archive:
        # --- Archive the current version before overwriting (if it exists) ---
        # Preserves every previously-approved version as a timestamped file
        # in the history/ subdirectory.  First-ever approve has no file to archive.
        if current_path.exists():
            existing = json.loads(current_path.read_text(encoding="utf-8"))
            # Use the existing file's approved_at as the archive filename
            # so timestamps reflect when that version was actually approved
            ts = existing.get("approved_at", now_iso())
            # Replace colons with hyphens so the filename is filesystem-safe
            # (ISO 8601 timestamps contain colons, e.g. "2026-03-02T19:23:59+00:00")
            safe_ts = ts.replace(":", "-")
            history_dir.mkdir(parents=True, exist_ok=True)
            (history_dir / f"{safe_ts}.json").write_text(
                json.dumps(existing, indent=2, default=str), encoding="utf-8",
            )

        # --- Compute the version number for this new save ---
        # Count existing history files (previous versions) and add 1 for the
        # new version.  First approve = 0 history files → version 1.
        version_count = len(list(history_dir.glob("*.json"))) if history_dir.exists() else 0
        data["version"] = version_count + 1
    else:
        # In-place update: keep the version number from the prior file if
        # one exists; otherwise stamp version=1.  No history entry written.
        if current_path.exists():
            try:
                existing = json.loads(current_path.read_text(encoding="utf-8"))
                data.setdefault("version", existing.get("version", 1))
            except (json.JSONDecodeError, OSError):
                data.setdefault("version", 1)
        else:
            data.setdefault("version", 1)

    # --- Write the new version as the canonical current file ---
    current_path.write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8",
    )

    # Touch meta.json's updated_at
    meta_path = d / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = {"dtxsid": dtxsid, "created_at": now_iso()}
    meta["updated_at"] = now_iso()
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # --- Cause-tagged version event (Phase 4) ---
    # Best-effort: a manifest failure must never undo the content write above
    # (invalidate_pool_artifacts relies on the stale flip persisting even if the
    # audit line can't be appended — the caller's try/except is the outer net,
    # this is the inner one).
    if version_event:
        _record_version_event(
            history_dir, data.get("version", 1), version_event,
        )


def _record_version_event(history_dir: Path, version: int, event: dict) -> None:
    """Append one cause-tagged line to the section's version manifest.

    `event` is the caller's {"cause", "status"} intent; the line also carries the
    version number it describes and a fresh timestamp.  Append-only: the manifest
    is a timeline, so a re-accept adds a new line for the same version (status
    changes; the current status is the most-recent line for that version) rather
    than editing an earlier one.  Fully fail-soft — never raises."""
    try:
        history_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "version": version,
            "cause": event.get("cause", "unknown"),
            "status": event.get("status", "unknown"),
            "ts": now_iso(),
        }
        with (history_dir / _VERSION_INDEX).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as e:  # pragma: no cover — defensive, audit must not abort work
        logger.warning(
            "Failed to record version event for %s: %s", history_dir, e,
        )


def read_version_history(dtxsid: str, section_key: str) -> list[dict]:
    """Return the cause-tagged version events for a section, oldest first.

    Parses history/{section_key}/index.jsonl into a list of
    {version, cause, status, ts} dicts.  Returns [] when no manifest exists
    (old, pre-Phase-4 sessions, or a section that never minted a tagged version)
    — a section with only un-tagged archives is not an error.  Corrupt lines are
    skipped, never raised."""
    idx = SESSIONS_DIR / dtxsid / "history" / section_key / _VERSION_INDEX
    if not idx.exists():
        return []
    events: list[dict] = []
    try:
        lines = idx.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # tolerate a partially-written line
    return events


def current_version_status(dtxsid: str, section_key: str) -> str | None:
    """The status of the section's CURRENT version, from the manifest.

    Reads the current file's version number, then returns the status of the most
    recent manifest event for that version (last line wins — a reprocess's
    needs-re-bless is superseded by a later re-accept's blessed against the same
    version).  None when the section or its manifest is absent, or the current
    version was never tagged (missing cause = unknown provenance, not a crash)."""
    current = SESSIONS_DIR / dtxsid / f"{section_key}.json"
    if not current.exists():
        return None
    try:
        version = json.loads(current.read_text(encoding="utf-8")).get("version", 1)
    except (json.JSONDecodeError, OSError):
        return None
    status = None
    for event in read_version_history(dtxsid, section_key):
        if event.get("version") == version:
            status = event.get("status")  # append order → last match is current
    return status


def delete_section(dtxsid: str, section_key: str) -> None:
    """
    Remove sessions/{dtxsid}/{section_key}.json if it exists.

    Called when the user clicks "Try Again" to unapprove a section.
    The .bm2 file in files/ is kept — it's still useful for reprocessing.
    """
    d = SESSIONS_DIR / dtxsid
    section_path = d / f"{section_key}.json"
    if section_path.exists():
        section_path.unlink()
