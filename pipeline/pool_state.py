"""
Pool-state mutation: progression checks, file replacement, and artifact
invalidation.

These functions encode "what changes when a user uploads, replaces, or
re-integrates files after the pool has already progressed past the
UPLOADED phase."  They sit between the upload routes (which ask "should
I invalidate?") and the cache/disk layer (which the invalidator clears).

Three functions live here:

  - pool_has_progressed(dtxsid)        — true if the session has any
    server-authoritative downstream artifact (validation_report.json
    or integrated.json on disk).  Used by upload paths to decide
    whether a new file requires cascading invalidation.
  - remove_old_file_entries(dtxsid, filename) — when a re-upload uses
    the same filename, drop the stale fingerprint + upload-dict entry
    by filename (file_ids change each upload, so filename is the
    stable key).  Persists fingerprints back to disk.
  - invalidate_pool_artifacts(dtxsid)  — clear all downstream artifacts
    that depend on pool composition.  Surgical about what it keeps:
    BMDS caches survive (content-hash keyed, so unchanged endpoints
    still hit cache after re-integration) and approved-section
    narratives are marked stale rather than deleted (preserves user
    edits while flagging that the data may have shifted underneath).

All state lives in pool_globals (_pool_fingerprints, _data_uploads,
_integrated_pool, _session_dir, _get_bm2_uploads).  remove_old_file_entries
also calls _save_fingerprints_to_disk from pool_fingerprints to keep the
on-disk cache consistent.

pool_orchestrator.py re-exports the three names so the original API
(used by background_server, session_routes, upload_routes) keeps working.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import json
import logging

from pipeline.pool_globals import (
    _session_dir,
    _pool_fingerprints,
    _data_uploads,
    _integrated_pool,
    _get_bm2_uploads,
)
from pipeline.pool_fingerprints import _save_fingerprints_to_disk


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pool progression check
# ---------------------------------------------------------------------------

def pool_has_progressed(dtxsid: str) -> bool:
    """Check whether the pool has progressed past UPLOADED.

    Uses the existence of validation_report.json or integrated.json on disk
    as a server-authoritative signal — no client trust required.  If either
    file exists, the pool has been validated or integrated and any new upload
    requires invalidation.

    Args:
        dtxsid: The DTXSID identifying the session.

    Returns:
        True if the pool has downstream artifacts that need invalidation.
    """
    d = _session_dir(dtxsid)
    return (d / "validation_report.json").exists() or (d / "integrated.json").exists()


# ---------------------------------------------------------------------------
# File-replacement cleanup
# ---------------------------------------------------------------------------

def remove_old_file_entries(dtxsid: str, filename: str) -> str | None:
    """Remove fingerprint and upload dict entry for a file being replaced.

    When the user uploads a file with the same name as an existing one,
    the old file's metadata is stale.  This function finds the old entry
    by filename (not file_id — IDs change across uploads) and removes:
      - The fingerprint from _pool_fingerprints[dtxsid]
      - The entry from _bm2_uploads or _data_uploads

    Args:
        dtxsid:   The DTXSID identifying the session.
        filename: The filename being replaced (e.g., "Body Weight.bm2").

    Returns:
        The old file_id if found and removed, None otherwise.
    """
    fps = _pool_fingerprints.get(dtxsid, {})
    old_file_id = None

    # Find the fingerprint entry that matches this filename
    for fid, fp in list(fps.items()):
        if fp.filename == filename:
            old_file_id = fid
            del fps[fid]
            logger.info("Removed old fingerprint for %s (file_id=%s)", filename, fid)
            break

    if not old_file_id:
        return None

    # Remove from the appropriate upload dict
    bm2_uploads = _get_bm2_uploads()
    if old_file_id in bm2_uploads:
        del bm2_uploads[old_file_id]
        logger.info("Removed old bm2_upload entry for %s", filename)
    elif old_file_id in _data_uploads:
        del _data_uploads[old_file_id]
        logger.info("Removed old data_upload entry for %s", filename)

    # Persist updated fingerprints to disk so session restore stays consistent
    _save_fingerprints_to_disk(dtxsid)

    return old_file_id


# ---------------------------------------------------------------------------
# Cascading invalidation
# ---------------------------------------------------------------------------

def invalidate_pool_artifacts(dtxsid: str) -> dict:
    """Clear all downstream artifacts that depend on the file pool composition.

    Called when a file is added or replaced after the pool has already been
    validated, integrated, or approved.  Preserves:
      - Fingerprints for unchanged files (still valid)
      - BMDS caches (_cache_bmds_*.json) — content-hash keyed, so unchanged
        endpoints still hit cache after re-integration
      - Approved section narrative text — marked stale but not deleted, so
        user edits are preserved

    Args:
        dtxsid: The DTXSID identifying the session.

    Returns:
        A summary dict of what was cleared/marked, suitable for logging
        or including in the API response.
    """
    d = _session_dir(dtxsid)
    summary = {"deleted": [], "marked_stale": []}

    # --- Delete validation, integration, and approval artifacts from disk ---
    # animal_report.json is included because it was generated from the
    # integrated data that is now stale — the user must re-approve after
    # re-integrating.
    for name in ("validation_report.json", "precedence.json",
                 "integrated.json", "_category_lookup.json",
                 "animal_report.json"):
        p = d / name
        if p.exists():
            p.unlink()
            summary["deleted"].append(name)
            logger.info("Deleted %s for %s", name, dtxsid)

    # --- Delete processing caches (except BMDS — content-hash keyed) ---
    # BMDS caches survive because their hash is computed from actual data
    # content (doses, means, stdevs), not from pool identity.  After
    # re-integration, endpoints whose data didn't change will produce the
    # same hash and hit the existing cache.
    for cache_file in d.glob("_cache_*.json"):
        if cache_file.name.startswith("_cache_bmds_"):
            continue  # keep — content-hash keyed, survives re-integration
        cache_file.unlink()
        summary["deleted"].append(cache_file.name)
        logger.info("Deleted cache %s for %s", cache_file.name, dtxsid)

    # --- Delete the query substrate (ADR-0016) — derived from the now-deleted
    # integrated.json + caches, so it is stale; rebuilt on next process. ---
    import shutil
    qdb = d / "session.duckdb"
    if qdb.exists():
        qdb.unlink()
        summary["deleted"].append("session.duckdb")
    if (d / "session_parquet").exists():
        shutil.rmtree(d / "session_parquet", ignore_errors=True)
        summary["deleted"].append("session_parquet/")

    # --- Clear in-memory integrated pool ---
    if dtxsid in _integrated_pool:
        del _integrated_pool[dtxsid]
        logger.info("Cleared in-memory integrated pool for %s", dtxsid)

    # --- Mark approved sections as stale ---
    # Read each bm2_*.json and genomics_*.json, set "stale": true, write back.
    # This preserves the user's narrative edits while flagging that the
    # underlying data may have changed.
    for pattern in ("bm2_*.json", "genomics_*.json"):
        for section_file in d.glob(pattern):
            try:
                section_data = json.loads(section_file.read_text(encoding="utf-8"))
                if not section_data.get("stale"):
                    section_data["stale"] = True
                    section_file.write_text(
                        json.dumps(section_data, indent=2, default=str),
                        encoding="utf-8",
                    )
                    summary["marked_stale"].append(section_file.name)
                    logger.info("Marked %s as stale for %s", section_file.name, dtxsid)
            except Exception as e:
                logger.warning("Failed to mark %s as stale: %s", section_file.name, e)

    return summary
