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
import os
import re
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Root directory for all session data.  Defaults to ./sessions/ (relative to
# this source file), but can be overridden via the SESSIONS_DIR environment
# variable — used when mounting a GCS bucket locally via gcsfuse or when
# Cloud Run's GCS FUSE volume is mounted at a non-default path.
SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", Path(__file__).parent / "sessions"))


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
    for exported .docx and .pdf reports.

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

    Version history layout:
        sessions/{dtxsid}/history/{section_key}/{safe_timestamp}.json
    The current file ({section_key}.json) is always the latest version.
    """
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
