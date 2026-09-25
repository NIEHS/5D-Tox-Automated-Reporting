"""
File-pool fingerprinting and lightweight validation.

When the user uploads a file to a session, we extract a structural
fingerprint from it (doses, animal counts, endpoints, platform, data
type) so the rest of the pool lifecycle — cross-validation, conflict
resolution, integration — has something compact to reason about
without re-parsing the raw file every time.

This module owns the in-memory side of the fingerprint lifecycle:

  - fingerprint_and_store        — extract fingerprint + store in the
    pool, with automatic long-format → wide-format conversion for NTP
    "tall and skinny" CSV/txt files
  - _save_fingerprints_to_disk   — persist the in-memory pool to
    _fingerprints.json so session restore can rehydrate without
    re-running expensive metadata deduction
  - load_cached_fingerprint      — read one cached fingerprint back,
    swapping in a fresh file_id (file_ids are regenerated each session)
  - restore_fingerprint          — inject a pre-loaded FileFingerprint
    into the pool without re-running the extractor
  - run_lightweight_validation   — immediate post-upload check of a
    single new file against the existing pool
  - ensure_fingerprints          — top-level: if the in-memory cache
    is empty (e.g. after a server restart), re-fingerprint everything
    in the session's files/ directory by walking bm2/data uploads and
    the filesystem

All state lives in pool_globals (_pool_fingerprints dict, _data_uploads
dict, _session_dir helper, _get_bm2_uploads accessor).  This module
mutates those dicts via name — they're the same dict objects across
modules because Python imports bind to the underlying object.

The original pool_orchestrator.py re-exports every symbol here so
external importers (background_server.py, session_routes.py,
upload_routes.py, test suite) keep working unchanged.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from bmdx_pipe import (
    FileFingerprint,
    fingerprint_file,
    lightweight_validate,
)

from pipeline.pool_globals import (
    _session_dir,
    _pool_fingerprints,
    _data_uploads,
    _get_bm2_uploads,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fingerprint extraction + storage
# ---------------------------------------------------------------------------

def fingerprint_and_store(
    file_id: str,
    filename: str,
    path: str,
    file_type: str,
    dtxsid: str,
    bm2_json: dict | None = None,
) -> FileFingerprint:
    """
    Fingerprint a single file and store the result in _pool_fingerprints.

    Called on upload (both direct and zip extraction) and on session load.
    The fingerprint is stored in the dtxsid-keyed pool so it's available
    for lightweight_validate() on subsequent uploads and for full
    validate_pool() when the user clicks "Validate & Integrate".

    Long-format files (NTP tall-and-skinny CSV/txt) are automatically
    converted to wide format during this step.  The original file is
    replaced in the pool by one wide-format file per sex.  This ensures
    all files are in BMDExpress-compatible format before validation runs.

    Args:
        file_id:   UUID from upload.
        filename:  Original filename.
        path:      Absolute path to the file on disk.
        file_type: "xlsx", "txt", "csv", or "bm2".
        dtxsid:    The DTXSID session this file belongs to.
        bm2_json:  Pre-loaded BMDProject dict (optional, for bm2 files).

    Returns:
        The created FileFingerprint, or a list of FileFingerprints if the
        file was long-format and got split into multiple wide-format files.
    """
    ts_added = datetime.now(tz=timezone.utc).isoformat()
    fp = fingerprint_file(file_id, filename, path, file_type, ts_added, bm2_json)

    # --- Long-format conversion ---
    # If a txt/csv file is long-format (one row per animal), convert it to
    # wide-format (BMDExpress pivot) immediately.  The original file is
    # replaced by one wide-format file per sex.  This happens before
    # validation so all comparisons use the same format.
    if fp.is_long_format and dtxsid:
        from bmdx_pipe import tox_study_csv_to_pivot_txt
        import uuid

        session_dir = _session_dir(dtxsid)
        files_dir = session_dir / "files"

        platform = fp.platform or "Unknown"
        data_type = fp.data_type or "tox_study"

        wide_files = tox_study_csv_to_pivot_txt(
            path, str(files_dir), platform, data_type,
        )

        if wide_files:
            logger.info(
                "Converted long-format %s → %d wide-format file(s)",
                filename, len(wide_files),
            )

            # Move the original long-format file out of files/ so it
            # won't be picked up by ensure_fingerprints directory scans.
            originals_dir = session_dir / "_originals"
            originals_dir.mkdir(exist_ok=True)
            original_path = Path(path)
            if original_path.exists() and original_path.parent == files_dir:
                original_path.rename(originals_dir / original_path.name)
                logger.info("Moved original %s → _originals/", filename)

            # Fingerprint each wide-format output and store in the pool.
            # The original long-format file is NOT added to the pool.
            first_fp = None
            for wide_path in wide_files:
                wide_name = os.path.basename(wide_path)
                wide_id = str(uuid.uuid4())
                wide_fp = fingerprint_file(
                    wide_id, wide_name, wide_path, "txt", ts_added, None,
                )
                if dtxsid not in _pool_fingerprints:
                    _pool_fingerprints[dtxsid] = {}
                _pool_fingerprints[dtxsid][wide_id] = wide_fp
                if first_fp is None:
                    first_fp = wide_fp

            _save_fingerprints_to_disk(dtxsid)
            # Return first wide-format fingerprint as representative.
            # All wide-format files are in the pool; callers only need
            # one result for the upload response.
            return first_fp or fp

    # Standard (non-long-format) path — store the fingerprint as-is
    if dtxsid:
        if dtxsid not in _pool_fingerprints:
            _pool_fingerprints[dtxsid] = {}
        _pool_fingerprints[dtxsid][file_id] = fp
        _save_fingerprints_to_disk(dtxsid)

    return fp


def _save_fingerprints_to_disk(dtxsid: str) -> None:
    """
    Persist all fingerprints for a DTXSID to sessions/{dtxsid}/_fingerprints.json.

    Keyed by filename (not file_id) because file_ids are freshly generated
    UUIDs on each session restore.  The fingerprint data is a plain dict
    serialized from the FileFingerprint dataclass.

    Called after every fingerprint_and_store() so the cache stays current.
    """
    if dtxsid not in _pool_fingerprints:
        return
    d = _session_dir(dtxsid)
    cache: dict[str, dict] = {}
    for fp in _pool_fingerprints[dtxsid].values():
        cache[fp.filename] = asdict(fp)
    try:
        (d / "_fingerprints.json").write_text(
            json.dumps(cache, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:
        logger.warning("Failed to persist fingerprints for %s", dtxsid, exc_info=True)


# ---------------------------------------------------------------------------
# Cache reload (session-restore path)
# ---------------------------------------------------------------------------

def load_cached_fingerprint(
    dtxsid: str,
    filename: str,
    file_id: str,
) -> FileFingerprint | None:
    """
    Load a single cached fingerprint from sessions/{dtxsid}/_fingerprints.json.

    Returns a FileFingerprint with file_id updated to the new session's UUID,
    or None if no cache exists or the filename isn't found.

    This avoids the expensive LLM call in _deduce_metadata_from_experiments()
    that would otherwise run on every session restore for each pending .bm2 file.

    Args:
        dtxsid:   The DTXSID session directory to look in.
        filename: Original filename to look up (stable key across restarts).
        file_id:  New UUID for this session — replaces the cached file_id.

    Returns:
        FileFingerprint with updated file_id, or None on cache miss.
    """
    d = _session_dir(dtxsid)
    cache_path = d / "_fingerprints.json"
    if not cache_path.exists():
        return None
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    entry = cache.get(filename)
    if not entry:
        return None
    # Rebuild the FileFingerprint from the cached dict, swapping in the new
    # file_id (since file_ids are regenerated each session load).
    entry["file_id"] = file_id
    # Dict fields with float dose keys are serialized with string keys by JSON —
    # convert them back to float keys so FileFingerprint gets the right types.
    for float_key_field in (
        "n_animals_by_dose",
        "animals_by_dose_selection",
        "core_animals_by_dose_sex",
    ):
        if entry.get(float_key_field):
            entry[float_key_field] = {
                float(k): v for k, v in entry[float_key_field].items()
            }
    # FileFingerprint may have new fields not present in old caches —
    # filter to only known fields to avoid TypeError on **entry.
    known_fields = {f.name for f in FileFingerprint.__dataclass_fields__.values()}
    entry = {k: v for k, v in entry.items() if k in known_fields}
    return FileFingerprint(**entry)


def restore_fingerprint(
    dtxsid: str,
    file_id: str,
    fp: FileFingerprint,
) -> None:
    """
    Store a pre-loaded fingerprint into the in-memory pool without re-running
    fingerprint_file().  Used by session restore to inject cached fingerprints.

    Args:
        dtxsid:  Session DTXSID.
        file_id: New file_id for this session.
        fp:      The cached FileFingerprint to store.
    """
    if dtxsid not in _pool_fingerprints:
        _pool_fingerprints[dtxsid] = {}
    _pool_fingerprints[dtxsid][file_id] = fp


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def run_lightweight_validation(
    fp: FileFingerprint,
    dtxsid: str,
) -> list[dict]:
    """
    Run lightweight validation on a new file against the existing pool.

    Returns a list of issue dicts (may be empty).  Called after fingerprinting
    a newly uploaded file to give immediate feedback.

    Args:
        fp:      Fingerprint of the newly added file.
        dtxsid:  The DTXSID session this file belongs to.

    Returns:
        List of validation issue dicts for JSON serialization.
    """
    if not dtxsid or dtxsid not in _pool_fingerprints:
        return []
    existing = {
        fid: efp for fid, efp in _pool_fingerprints[dtxsid].items()
        if fid != fp.file_id
    }
    issues = lightweight_validate(fp, existing)
    return [asdict(issue) for issue in issues]


def ensure_fingerprints(dtxsid: str, force: bool = False) -> dict:
    """
    Ensure fingerprints are populated for a session's file pool.

    Checks the in-memory _pool_fingerprints cache first.  If empty (e.g.,
    after a server restart), re-fingerprints all files from the session's
    files/ directory by scanning _bm2_uploads, _data_uploads, and the
    filesystem.

    Args:
        dtxsid: The DTXSID identifying the session.
        force:  If True, clear existing fingerprints and re-scan from disk.
                Used by the validation endpoint which always wants a fresh scan.

    Returns:
        The fingerprint dict {file_id: FileFingerprint} for this session.
    """
    fps = _pool_fingerprints.get(dtxsid, {})
    if fps and not force:
        return fps

    # Re-fingerprint all files from disk
    files_dir = _session_dir(dtxsid) / "files"
    if not files_dir.exists():
        return {}

    _pool_fingerprints[dtxsid] = {}
    fingerprinted: set[str] = set()

    # 1. Fingerprint files registered in _bm2_uploads
    bm2_uploads = _get_bm2_uploads()
    for fid, entry in bm2_uploads.items():
        path = entry.get("temp_path", "")
        if path and os.path.exists(path) and str(files_dir) in path:
            bm2_json = entry.get("bm2_json")
            fingerprint_and_store(fid, entry["filename"], path, "bm2", dtxsid, bm2_json)
            fingerprinted.add(entry["filename"])

    # 2. Fingerprint files registered in _data_uploads.
    # Skip files that no longer exist (moved to _originals after flattening).
    for fid, entry in _data_uploads.items():
        path = entry.get("temp_path", "")
        if path and os.path.exists(path) and str(files_dir) in path:
            result = fingerprint_and_store(fid, entry["filename"], path, entry["type"], dtxsid)
            fingerprinted.add(entry["filename"])
            # If long-format conversion happened, also mark the flattened
            # output filenames so step 3 doesn't re-fingerprint them.
            if result and hasattr(result, "filename"):
                fingerprinted.add(result.filename)
            # Check if more files were added to the pool by the conversion
            for pool_fp in _pool_fingerprints.get(dtxsid, {}).values():
                fingerprinted.add(pool_fp.filename)

    # 3. Scan files/ directory for anything not yet fingerprinted
    for data_file in sorted(files_dir.iterdir()):
        if not data_file.is_file() or data_file.name in fingerprinted:
            continue
        ext = data_file.suffix.lower().lstrip(".")
        if ext not in ("xlsx", "txt", "csv", "bm2"):
            continue
        fid = f"scan-{data_file.name}"
        fingerprint_and_store(fid, data_file.name, str(data_file), ext, dtxsid)

    return _pool_fingerprints.get(dtxsid, {})
