"""
Pool orchestrator — file pool fingerprinting, validation, integration, and
processing endpoints extracted from background_server.py.

This module owns the full lifecycle of the "file pool" concept:

  1. **Fingerprinting** — extract structural metadata (doses, animals, endpoints,
     platform, data_type) from each uploaded file so we can cross-validate them.
  2. **Validation** — check for dose group mismatches, coverage gaps, and
     redundancy across the pool.
  3. **Conflict resolution** — persist user precedence decisions when files
     disagree.
  4. **Integration** — merge the best file per platform into a single unified
     BMDProject JSON via bmdx-core's native Java classes.
  5. **Processing** — run NTP stats on the integrated data to produce per-platform
     section cards (tables + narratives) for the UI, plus genomics extraction
     from gene-expression .bm2 files.
  6. **Animal traceability** — per-animal cross-tier/cross-platform report.

All endpoints are mounted as a FastAPI APIRouter, included by the main app.

Shared state (module-level dicts):
  - _pool_fingerprints:  dtxsid -> {file_id -> FileFingerprint}
  - _integrated_pool:    dtxsid -> merged BMDProject dict
  - _data_uploads:       file_id -> {filename, temp_path, type}

These are accessed by other modules (upload handlers, session restore) via the
public accessor functions exported at the bottom of this file.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orjson
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from session_store import session_dir as _session_dir_imported
from llm_helpers import (
    llm_generate_json as _llm_generate_json_imported,
    llm_generate_json_async as _llm_generate_json_async,
)

from bmdx_pipe import (
    FileFingerprint,
    TableRow,
    ValidationReport,
    fingerprint_file,
    validate_pool,
    lightweight_validate,
    _BM2_PLATFORM_MAP,
    detect_platform_and_type_from_bm2,
    integrate_pool,
    build_animal_report,
    report_to_dict,
    annotate_missing_animals,
    backfill_missing_doses,
    build_table_data,
    build_clinical_obs_tables,
    export_genomics,
    generate_results_narrative,
)
from apical_bmds import run_bmds_for_endpoints

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
# These module-level dicts hold the in-memory state for the file pool.
# They are accessed by background_server.py (upload handlers, session restore)
# via the public accessor functions below.

# Maps dtxsid -> {file_id -> FileFingerprint} for cross-validation.
# Populated when files are fingerprinted (on upload or validation request).
# Persisted to disk as validation_report.json per session directory.
_pool_fingerprints: dict[str, dict[str, FileFingerprint]] = {}

# Maps dtxsid -> merged BMDProject dict from pool integration.
# Populated by /api/pool/integrate/{dtxsid} and persisted to
# sessions/{dtxsid}/integrated.json for cross-session restore.
_integrated_pool: dict[str, dict] = {}

# Maps file_id (UUID string) -> dict with filename, temp_path, type.
# Used for raw dose-response experimental data (.csv, .txt, .xlsx) extracted
# from zip archives.  These are BMDExpress-importable input data, not
# gene-level BMD results.  The client references these by ID in the file pool.
_data_uploads: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Direct imports replace the old init_orchestrator() injection pattern.
# session_store and llm_helpers are leaf modules with no circular dependency.
# bm2_uploads is imported lazily from server_state to break the import cycle
# (server_state imports from pool_orchestrator, so we can't import at module level).
# ---------------------------------------------------------------------------

def _session_dir(dtxsid: str) -> Path:
    """Return the session directory for a DTXSID, creating it if needed."""
    return _session_dir_imported(dtxsid)


def _get_bm2_uploads() -> dict[str, dict]:
    """Lazy import of bm2_uploads from server_state to avoid circular import."""
    from server_state import get_bm2_uploads
    return get_bm2_uploads()


# ---------------------------------------------------------------------------
# Public accessors for shared state
# ---------------------------------------------------------------------------
# background_server.py needs to read/write these dicts from upload handlers
# and session restore code.  Rather than importing the raw dicts (which would
# make the dependency invisible), we provide explicit accessor functions.

def get_pool_fingerprints() -> dict[str, dict[str, FileFingerprint]]:
    """Return the full pool fingerprints dict (dtxsid -> {fid -> fp})."""
    return _pool_fingerprints


def get_integrated_pool() -> dict[str, dict]:
    """Return the full integrated pool dict (dtxsid -> BMDProject dict)."""
    return _integrated_pool


def get_data_uploads() -> dict[str, dict]:
    """Return the data uploads dict (file_id -> upload info)."""
    return _data_uploads


# ---------------------------------------------------------------------------
# Pool mutation — invalidation and cleanup when files change after workflow
# ---------------------------------------------------------------------------
# When the user uploads new files or replaces existing ones after the pool
# has already been validated/integrated/approved, downstream artifacts become
# stale.  These functions handle the cleanup:
#
#   remove_old_file_entries()     — remove a replaced file's fingerprint and
#                                   upload dict entry by filename
#   invalidate_pool_artifacts()   — delete validation/integration/cache artifacts
#                                   and mark approved sections as stale
#   pool_has_progressed()         — check whether the pool has moved past UPLOADED
#                                   (i.e., whether invalidation is needed)


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


# ---------------------------------------------------------------------------
# Table serialization helpers
# ---------------------------------------------------------------------------
# Moved here from background_server.py because process-integrated is the
# primary consumer.  Also used by process-bm2 (which imports from here).

def _js_dose_key(dose: float) -> str:
    """
    Convert a float dose to the string key JavaScript would produce via
    String(number).

    JavaScript's String(0.3) produces "0.3" but String(1.0) produces "1"
    (drops trailing ".0").  We replicate this so Python-generated table data
    matches the keys the browser expects when rendering dose columns.

    Args:
        dose: A numeric dose value (e.g., 0.0, 0.3, 1.0, 10.0).

    Returns:
        String representation matching JavaScript's String(number) behavior.
    """
    if dose == int(dose):
        return str(int(dose))
    return str(dose)


def serialize_table_rows(table_data: dict) -> dict:
    """
    Convert a {sex: [TableRow, ...]} dict to JSON-friendly nested dicts.

    Each TableRow has values_by_dose, n_by_dose, and trend_marker attributes.
    BMD/BMDL are excluded — they belong in the separate BMD summary table
    (matching the NIEHS reference report structure: platform tables + Table 8).
    Dose float keys are converted via _js_dose_key() to match JavaScript's
    String(number) behavior.

    Used by /api/process-bm2 and /api/process-integrated to serialize
    the NTP stats pipeline output for the browser.

    Args:
        table_data: Dict mapping sex label ("Male", "Female") to lists of
                    TableRow objects from apical_report.build_table_data().

    Returns:
        Dict mapping sex label to lists of JSON-serializable row dicts.
    """
    tables_json = {}
    for sex, rows in table_data.items():
        tables_json[sex] = []
        for row in rows:
            sorted_doses = sorted(row.values_by_dose.keys())
            entry = {
                "label": row.label,
                "doses": sorted_doses,
                "values": {_js_dose_key(d): v for d, v in row.values_by_dose.items()},
                "n": {_js_dose_key(d): n for d, n in row.n_by_dose.items()},
                "trend_marker": row.trend_marker,
            }
            # Include missing-animal data when present, so the UI can
            # render footnotes for dose groups with dead animals.
            if row.missing_animals_by_dose:
                entry["missing_animals"] = {
                    _js_dose_key(d): n
                    for d, n in row.missing_animals_by_dose.items()
                }
            tables_json[sex].append(entry)
    return tables_json


def serialize_incidence_rows(incidence_data: dict) -> dict:
    """
    Convert a {sex: [IncidenceRow, ...]} dict to JSON-friendly nested dicts.

    Similar to serialize_table_rows() but for clinical observation incidence
    data.  Each row has pre-formatted "n/N" strings instead of mean±SE values.
    Dose keys are converted via _js_dose_key() for JavaScript compatibility.

    The output includes a "table_type": "incidence" marker so the frontend
    can detect this is an incidence table and render it differently (no "n"
    row, "Finding" header instead of "Endpoint", cells are literal strings).

    Args:
        incidence_data: Dict mapping sex label to lists of IncidenceRow
                        objects from build_clinical_obs_tables().

    Returns:
        Dict mapping sex label to lists of JSON-serializable row dicts.
    """
    tables_json = {}
    for sex, rows in incidence_data.items():
        tables_json[sex] = []
        for row in rows:
            sorted_doses = sorted(row.incidence_by_dose.keys())
            entry = {
                "label": row.label,
                "doses": sorted_doses,
                # Values are pre-formatted "n/N" strings — the frontend
                # renders them directly without further formatting.
                "values": {
                    _js_dose_key(d): v
                    for d, v in row.incidence_by_dose.items()
                },
                # Total N per dose group (for the frontend to use if needed)
                "n": {
                    _js_dose_key(d): n
                    for d, n in row.total_n_by_dose.items()
                },
            }
            tables_json[sex].append(entry)
    return tables_json


def _build_clinical_obs_section(
    integrated: dict,
    compound_name: str,
    dose_unit: str,
) -> dict | None:
    """
    Build the Clinical Observations section card from stored CSV paths.

    Reads the CSV paths from integrated._meta.clinical_obs_files, calls
    build_clinical_obs_tables() to produce incidence data, then serializes
    it into the same shape as apical section cards — but with
    table_type="incidence" so the frontend knows to render differently.

    Args:
        integrated:    The full merged BMDProject dict with _meta overlay.
        compound_name: Chemical name for narrative/caption.
        dose_unit:     Dose unit string (e.g., "mg/kg").

    Returns:
        Section card dict, or None if no clinical obs files or no findings.
    """
    meta = integrated.get("_meta", {})
    csv_paths = meta.get("clinical_obs_files", [])
    if not csv_paths:
        return None

    incidence_data = build_clinical_obs_tables(csv_paths)
    if not incidence_data:
        return None

    tables_json = serialize_incidence_rows(incidence_data)

    return {
        "platform": "Clinical Observations",
        "title": "Clinical Observations",
        "tables_json": tables_json,
        "table_type": "incidence",
        "narrative": [],  # No auto-generated narrative for incidence tables
    }


# ---------------------------------------------------------------------------
# Fingerprinting helpers
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


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------

router = APIRouter()


@router.post("/api/pool/validate/{dtxsid}")
async def api_pool_validate(dtxsid: str):
    """
    Run full cross-validation on a session's file pool.

    Fingerprints (or re-fingerprints) every file in the session's files/
    directory, then runs all validation checks: coverage, dose consistency,
    animal counts, sex coverage, and redundancy detection.

    Returns a ValidationReport as JSON with:
      - coverage_matrix: platform -> tier -> file_id(s)
      - issues: list of { severity, platform, issue_type, message, ... }
      - is_complete: whether all platforms have full tier coverage

    Saves the report to sessions/{dtxsid}/validation_report.json for
    persistence across page reloads.
    """
    # Re-fingerprint all files from disk to catch any out-of-band changes
    # (e.g., files added manually or by other processes).
    files_dir = _session_dir(dtxsid) / "files"
    if not files_dir.exists():
        return JSONResponse({
            "error": "No files directory found for this session",
        }, status_code=404)

    # Force a full re-scan of all files in the session
    fps = ensure_fingerprints(dtxsid, force=True)
    report = validate_pool(dtxsid, fps)

    # Persist the report to disk
    report_dict = {
        "dtxsid": report.dtxsid,
        "run_at": report.run_at,
        "file_count": report.file_count,
        "fingerprints": report.fingerprints,
        "issues": report.issues,
        "coverage_matrix": report.coverage_matrix,
        "is_complete": report.is_complete,
    }
    report_path = _session_dir(dtxsid) / "validation_report.json"
    report_path.write_text(
        json.dumps(report_dict, indent=2, default=str),
        encoding="utf-8",
    )

    return Response(
        content=orjson.dumps(report_dict),
        media_type="application/json",
    )


@router.post("/api/pool/resolve")
async def api_pool_resolve(request: Request):
    """
    Record a user's precedence decision for a specific validation conflict.

    When the validation report shows an error (e.g., dose group mismatch),
    the user picks which file is authoritative.  This endpoint persists
    that decision to sessions/{dtxsid}/precedence.json so it survives
    page reloads.

    Input JSON:
      {
        "dtxsid": "DTXSID50469320",
        "issue_index": 0,
        "chosen_file_id": "abc123-..."
      }

    Returns { "ok": true } on success.
    """
    body = await request.json()
    dtxsid = body.get("dtxsid", "")
    issue_index = body.get("issue_index")
    chosen_file_id = body.get("chosen_file_id", "")

    if not dtxsid or issue_index is None or not chosen_file_id:
        return JSONResponse(
            {"error": "dtxsid, issue_index, and chosen_file_id are required"},
            status_code=400,
        )

    # Load existing precedence decisions
    precedence_path = _session_dir(dtxsid) / "precedence.json"
    precedence: list[dict] = []
    if precedence_path.exists():
        try:
            precedence = json.loads(precedence_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            precedence = []

    # Record the new decision
    precedence.append({
        "issue_index": issue_index,
        "chosen_file_id": chosen_file_id,
        "resolved_at": datetime.now(tz=timezone.utc).isoformat(),
    })

    # Persist to disk
    precedence_path.write_text(
        json.dumps(precedence, indent=2),
        encoding="utf-8",
    )

    return JSONResponse({"ok": True})


@router.post("/api/pool/confirm-metadata/{dtxsid}")
async def api_pool_confirm_metadata(dtxsid: str, request: Request):
    """
    Confirm file metadata and write headers into file copies.

    Called after validation when the user has reviewed and corrected the
    platform + data_type assignments for each file.  For txt/csv files,
    this prepends metadata header lines (# Platform:, # Data Type:, etc.)
    so that Java's ExperimentDescriptionParser picks them up during import.

    Updates the fingerprints in memory with any user corrections.
    .bm2 files cannot have headers written — their metadata is set via
    the metadata sidecar in IntegrateProject.java.

    Input JSON:
      { "metadata": { "file_id": { "platform": "Body Weight", "data_type": "tox_study" }, ... } }
    """
    body = await request.json()
    confirmed = body.get("metadata", {})

    session_dir = _session_dir(dtxsid)
    files_dir = session_dir / "files"

    fps = get_pool_fingerprints().get(dtxsid, {})
    updated = 0

    for fid, corrections in confirmed.items():
        fp = fps.get(fid)
        if not fp:
            continue

        # Update fingerprint with user corrections
        new_platform = corrections.get("platform")
        new_data_type = corrections.get("data_type")
        if new_platform and hasattr(fp, "platform"):
            fp.platform = new_platform
        elif new_platform and isinstance(fp, dict):
            fp["platform"] = new_platform
        if new_data_type and hasattr(fp, "data_type"):
            fp.data_type = new_data_type
        elif new_data_type and isinstance(fp, dict):
            fp["data_type"] = new_data_type

        # Write metadata headers into txt/csv files.
        # We prepend headers to the file in-place in the session files dir.
        # .bm2 files are binary — metadata goes through the sidecar instead.
        fname = fp.filename if hasattr(fp, "filename") else fp.get("filename", "")
        ftype = fp.file_type if hasattr(fp, "file_type") else fp.get("file_type", "")

        if ftype in ("txt", "csv"):
            file_path = files_dir / fname
            if file_path.exists():
                _write_metadata_headers(
                    file_path,
                    platform=new_platform or (fp.platform if hasattr(fp, "platform") else fp.get("platform")),
                    data_type=new_data_type or (fp.data_type if hasattr(fp, "data_type") else fp.get("data_type")),
                )
                updated += 1

    # Re-persist fingerprints with corrections — same format as _persist_fingerprints
    cache: dict[str, dict] = {}
    for fp_obj in fps.values():
        fname = fp_obj.filename if hasattr(fp_obj, "filename") else fp_obj.get("filename", "")
        cache[fname] = asdict(fp_obj) if hasattr(fp_obj, "filename") else fp_obj
    fp_path = session_dir / "_fingerprints.json"
    fp_path.write_text(
        json.dumps(cache, indent=2, default=str),
        encoding="utf-8",
    )

    logger.info("Confirmed metadata for %d files in %s", updated, dtxsid)
    return JSONResponse({"ok": True, "updated": updated})


def _write_metadata_headers(file_path, platform: str, data_type: str) -> None:
    """
    Prepend # Provider / # Platform / # Data Type headers to a txt/csv file.

    If the file already has metadata headers (lines starting with #),
    replaces them.  Otherwise prepends before the first data line.

    These headers are parsed by ExperimentDescriptionParser in Java
    so that ExperimentDescription fields are set during import.
    """
    path = Path(file_path)
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)

    # Build new header block
    headers = []
    headers.append(f"# Provider: Apical\n")
    if platform:
        headers.append(f"# Platform: {platform}\n")
    if data_type:
        headers.append(f"# Data Type: {data_type}\n")

    # Strip any existing metadata header lines (start with #)
    data_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            data_start = i
            break

    # Write back: new headers + data lines
    path.write_text("".join(headers + lines[data_start:]), encoding="utf-8")


@router.post("/api/pool/integrate/{dtxsid}")
async def api_pool_integrate(dtxsid: str, request: Request):
    """
    Merge all pool files into a unified BMDProject JSON.

    Reads fingerprints from _pool_fingerprints, coverage_matrix from the
    persisted validation_report.json, and precedence decisions from
    precedence.json.  Calls integrate_pool() to select the best file per
    platform and produce the merged structure.

    The result is stored both in-memory (_integrated_pool) and on disk
    (sessions/{dtxsid}/integrated.json) for session restore.

    Returns the full integrated BMDProject JSON, including a _meta block
    with provenance: which file was chosen for each platform and why.
    """
    session_dir = _session_dir(dtxsid)
    files_dir = session_dir / "files"
    if not files_dir.exists():
        return JSONResponse(
            {"error": "No files directory found for this session"},
            status_code=404,
        )

    # Load fingerprints -- prefer in-memory, fall back to validation_report.json
    fps = _pool_fingerprints.get(dtxsid, {})
    if not fps:
        report_path = session_dir / "validation_report.json"
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                fps = report.get("fingerprints", {})
            except (json.JSONDecodeError, Exception):
                pass

    if not fps:
        return JSONResponse(
            {"error": "No fingerprints found -- run validation first"},
            status_code=400,
        )

    # Load the coverage matrix from the validation report
    report_path = session_dir / "validation_report.json"
    coverage_matrix: dict = {}
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            coverage_matrix = report.get("coverage_matrix", {})
        except (json.JSONDecodeError, Exception):
            pass

    if not coverage_matrix:
        return JSONResponse(
            {"error": "No coverage matrix found -- run validation first"},
            status_code=400,
        )

    # Load user precedence decisions (may be empty if no conflicts resolved)
    precedence_path = session_dir / "precedence.json"
    precedence: list[dict] = []
    if precedence_path.exists():
        try:
            precedence = json.loads(precedence_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            pass

    # Persist identity.json early — the client sends the resolved chemical
    # identity in the request body so it's available for LLM metadata inference.
    # Previously this was only written on section approve, which meant integration
    # (which happens before any approve) couldn't find the test article.
    try:
        body = await request.json()
    except Exception:
        body = {}
    if body.get("identity"):
        identity_path = session_dir / "identity.json"
        identity_path.write_text(
            json.dumps(body["identity"], indent=2, default=str),
            encoding="utf-8",
        )

    # Load test article identity for metadata inference.
    # The LLM uses this to populate testArticle on each experiment.
    # Try identity.json (written above or on section approve), then fall back
    # to meta.json (legacy — written on section approve with name/casrn).
    test_article = None
    for identity_file in ("identity.json", "meta.json"):
        id_path = session_dir / identity_file
        if id_path.exists():
            try:
                id_data = json.loads(id_path.read_text(encoding="utf-8"))
                name = id_data.get("name", "")
                casrn = id_data.get("casrn", "")
                dsstox = id_data.get("dtxsid", dtxsid)
                if name or casrn:
                    test_article = {
                        "name": name,
                        "casrn": casrn,
                        "dsstox": dsstox,
                        "synonyms": id_data.get("synonyms", []),
                    }
                    break
            except (json.JSONDecodeError, Exception):
                continue

    # Run integration in a thread pool -- xlsx parsing uses openpyxl (blocking I/O)
    loop = asyncio.get_running_loop()
    try:
        integrated = await loop.run_in_executor(
            None,
            lambda: integrate_pool(
                dtxsid,
                str(session_dir),
                fps,
                coverage_matrix,
                precedence,
                test_article=test_article,
                llm_generate_json=_llm_generate_json_imported,
            ),
        )
    except Exception as e:
        logger.exception("Pool integration failed for %s", dtxsid)
        return JSONResponse(
            {"error": f"Integration failed: {e}"},
            status_code=500,
        )

    # Cache in memory for the process-integrated endpoint
    _integrated_pool[dtxsid] = integrated

    # Invalidate all per-section caches from previous integration runs —
    # the input data has changed, so all cached results are stale.
    # Also clean up any leftover monolithic caches from the old format.
    for pattern in ("_cache_*.json", "_processed_cache_*.json"):
        for old_cache in _session_dir(dtxsid).glob(pattern):
            old_cache.unlink(missing_ok=True)
            logger.debug("Invalidated stale cache: %s", old_cache.name)

    # Return a lightweight summary instead of the full integrated JSON
    # (which can be 50+ MB and exceeds Cloud Run's 32 MiB response limit).
    # The client can fetch the full data via GET /api/integrated/{dtxsid}
    # if needed (that endpoint uses FileResponse with chunked streaming).
    #
    # The summary mirrors the structure the client's renderIntegratedPreview()
    # expects: _meta.source_files for the platform table, plus top-level counts.
    meta = integrated.get("_meta", {})
    experiments = integrated.get("doseResponseExperiments", [])

    # Backfill experiment_count per platform if integrate_pool() didn't
    # populate it (shouldn't happen with current bmdx-pipe, but safety net).
    source_files = meta.get("source_files", {})
    if source_files and experiments:
        needs_backfill = any(
            "experiment_count" not in info for info in source_files.values()
        )
        if needs_backfill:
            _enrich_source_experiment_counts(source_files, experiments)

    return JSONResponse({
        "ok": True,
        "_meta": meta,
        "experiment_count": len(experiments),
        "bmd_result_count": len(integrated.get("bMDResult", [])),
        "category_analysis_count": len(integrated.get("categoryAnalysisResults", [])),
        "experiments": [
            {
                "name": exp.get("name", ""),
                "probe_count": len(exp.get("probeResponses", [])),
            }
            for exp in experiments
        ],
    })


@router.get("/api/integrated/{dtxsid}")
async def api_integrated_full(dtxsid: str):
    """
    Stream the full integrated BMDProject JSON from disk.

    Returns the cached integrated.json via FileResponse (chunked streaming)
    so the browser can parse it progressively with Oboe.js.  If no cached
    file exists, returns 404 -- the caller should trigger integration first.
    """
    integrated_path = _session_dir(dtxsid) / "integrated.json"
    if not integrated_path.exists():
        return JSONResponse(
            {"error": "No integrated data found -- run integration first"},
            status_code=404,
        )
    return FileResponse(
        path=str(integrated_path),
        media_type="application/json",
        filename="integrated.json",
    )


@router.get("/api/integrated-summary/{dtxsid}")
async def api_integrated_summary(dtxsid: str):
    """
    Return a lightweight summary of the integrated BMDProject.

    Uses _load_integrated() which handles both the main integrated.json
    and the _category_lookup.json sidecar.  Only summary fields are
    returned — the full response arrays and category lookup stay server-side.
    """
    integrated = _load_integrated(dtxsid)

    if not integrated:
        return JSONResponse(
            {"error": "No integrated data found"},
            status_code=404,
        )

    meta = integrated.get("_meta", {})
    experiments = integrated.get("doseResponseExperiments", [])
    bmd_results = integrated.get("bMDResult", [])
    cat_results = integrated.get("categoryAnalysisResults", [])

    # --- Backfill experiment_count per platform if missing ---
    # Sessions saved before the enrichment was added to integrate_pool()
    # won't have experiment_count in source_files.  Compute it on the fly
    # using the same name-matching heuristic so the preview table shows
    # correct values instead of 0.
    source_files = meta.get("source_files", {})
    needs_backfill = source_files and any(
        "experiment_count" not in info for info in source_files.values()
    )
    if needs_backfill and experiments:
        _enrich_source_experiment_counts(source_files, experiments)

    # Build experiment summaries (name + probe count only -- no response data)
    exp_summaries = []
    for exp in experiments:
        exp_summaries.append({
            "name": exp.get("name", ""),
            "probe_count": len(exp.get("probeResponses", [])),
        })

    return JSONResponse({
        "_meta": meta,
        "experiment_count": len(experiments),
        "experiments": exp_summaries,
        "bmd_result_count": len(bmd_results),
        "category_analysis_count": len(cat_results),
    })


# ---------------------------------------------------------------------------
# Process-integrated helpers
# ---------------------------------------------------------------------------
# These private functions implement the phases of the process-integrated
# pipeline.  Extracted from the monolithic api_process_integrated() endpoint
# to improve readability and testability.  Each function handles one phase
# of the pipeline: loading data, restoring category lookups, filtering
# gene expression experiments, partitioning by platform, building section
# cards, extracting genomics, and building BMD summaries.

# Human-readable labels for BMD statistics, used by the UI to set table
# column headers (e.g. "BMD 5th Pct").
_BMD_STAT_LABELS = {
    "mean": "Mean",
    "median": "Median",
    "minimum": "Minimum",
    "weighted_mean": "Weighted Mean",
    "fifth_pct": "5th %ile",
    "tenth_pct": "10th %ile",
    "lower95": "Lower 95%",
    "upper95": "Upper 95%",
}


def _safe_float(val, default=float("inf")):
    """
    Coerce a value to float, returning *default* for None, NaN, or unparseable
    strings.  Used for sorting BMD values where Java serializes NaN/Infinity
    as strings.
    """
    if val is None:
        return default
    try:
        v = float(val)
        # NaN sorts inconsistently — treat as infinity
        return default if v != v else v
    except (TypeError, ValueError):
        return default


def _safe_float_from_bmdl(bmdl_str: str, default=float("inf")) -> float:
    """
    Extract a numeric sort key from a formatted BMDL string.

    BMDL strings can be:
      - numeric: "12.3", "0.00679"
      - NR threshold: "<0.1" (strip the '<' prefix)
      - status codes: "NVM", "UREP", "—" → sort to end (infinity)

    Used to sort BMD summary tables by BMDL within each sex group,
    so the most potent (lowest BMDL) endpoints appear first.
    """
    if not bmdl_str or bmdl_str in ("—", "NVM", "UREP", "ND"):
        return default
    # Strip "<" prefix from NR thresholds like "<0.1"
    cleaned = bmdl_str.lstrip("<")
    return _safe_float(cleaned, default)


def _pick_go_stat(go_entry: dict, metric: str, stat: str):
    """
    Pick a specific BMD statistic from a GO category's stat block.

    Returns None (not a fallback) if the stat isn't available, so that
    categories missing the stat get excluded from the table rather than
    showing a misleading value from a different statistic.

    Args:
        go_entry: A GO BP category dict with optional bmd_stats/bmdl_stats blocks.
        metric:   "bmd", "bmdl", or "bmdu".
        stat:     The statistic key (e.g., "mean", "median", "fifth_pct").
    """
    block = go_entry.get(f"{metric}_stats", {})
    if block:
        return block.get(stat)
    # Legacy data only has median (pre-stat-block format)
    if stat == "median":
        return go_entry.get(f"{metric}_median")
    return None


def _enrich_source_experiment_counts(
    source_files: dict[str, dict],
    experiments: list[dict],
) -> None:
    """
    Backfill experiment_count on each source_files entry.

    Uses bidirectional substring matching: checks if the normalized platform
    name is in the experiment name OR vice versa (handles abbreviations like
    "tissue_conc" matching "Tissue Concentration").  Falls back to augmented
    ExperimentDescription metadata.  When multiple source_files entries share
    the same base platform (e.g., "Hematology|tox_study" and
    "Hematology|inferred"), both get the count.

    Mutates source_files entries in place — adds 'experiment_count' key.

    Why this exists: integrate_pool() in bmdx-pipe now writes experiment_count
    at integration time, but sessions saved before that change have source_files
    entries without it.  The summary endpoint calls this to backfill on the fly
    so the integrated dataset preview table shows correct counts instead of 0.
    """
    # Build normalized base platform → list of original keys mapping.
    # Multiple compound keys can share a base (e.g., "Hematology|tox_study"
    # and "Hematology|inferred" both normalize to "hematology").
    plat_norm: dict[str, list[str]] = {}
    for plat_key in source_files:
        base = plat_key.split("|")[0] if "|" in plat_key else plat_key
        normalized = base.lower().replace(" ", "").replace("_", "")
        plat_norm.setdefault(normalized, []).append(plat_key)

    # Count experiments per base platform
    base_counts: dict[str, int] = {}
    for exp in experiments:
        exp_name = (exp.get("name") or "").lower().replace("_", "")
        matched = False
        for norm_key in plat_norm:
            # Bidirectional substring: platform name in experiment name
            # (e.g., "hematology" in "hematologytruthfemale") OR a long
            # shared prefix (handles abbreviations like "tissueconc" from
            # experiment "tissue_conc_truth_male" vs "tissueconcentration"
            # from platform "Tissue Concentration").  Prefix must be at
            # least 6 chars to avoid false positives.
            if norm_key in exp_name:
                base_counts[norm_key] = base_counts.get(norm_key, 0) + 1
                matched = True
                break
            # Common-prefix check for abbreviated experiment names
            prefix_len = 0
            for a, b in zip(norm_key, exp_name):
                if a == b:
                    prefix_len += 1
                else:
                    break
            if prefix_len >= min(6, len(norm_key)):
                base_counts[norm_key] = base_counts.get(norm_key, 0) + 1
                matched = True
                break
        if not matched:
            # Check augmented ExperimentDescription metadata
            desc = exp.get("experimentDescription") or {}
            aug = desc.get("_augmented") or {}
            exp_platform = aug.get("platform", "")
            if exp_platform:
                norm_aug = exp_platform.lower().replace(" ", "").replace("_", "")
                if norm_aug in plat_norm:
                    base_counts[norm_aug] = base_counts.get(norm_aug, 0) + 1

    # Apply counts to all compound keys sharing the same base platform
    for norm_key, count in base_counts.items():
        for orig_key in plat_norm.get(norm_key, []):
            source_files[orig_key]["experiment_count"] = count


def _load_integrated(dtxsid: str) -> dict | None:
    """
    Load the integrated BMDProject for a session.

    Prefers the in-memory cache (_integrated_pool).  Falls back to reading
    sessions/{dtxsid}/integrated.json from disk and populating the cache.

    The _category_lookup is stored in a separate sidecar file
    (_category_lookup.json) to keep integrated.json lean for fast summary
    loads.  It's merged back into the in-memory dict on first access.

    Returns None if no integrated data exists (caller should return 400).
    """
    integrated = _integrated_pool.get(dtxsid)
    if integrated is None:
        session = _session_dir(dtxsid)
        integrated_path = session / "integrated.json"
        if integrated_path.exists():
            try:
                integrated = json.loads(integrated_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                logger.warning("Failed to load integrated.json for %s", dtxsid)
                return None

            # Load the _category_lookup sidecar if it exists and the key
            # is not already in the integrated dict (backward compat with
            # old sessions that still have it inline).
            if "_category_lookup" not in integrated:
                cat_path = session / "_category_lookup.json"
                if cat_path.exists():
                    try:
                        integrated["_category_lookup"] = json.loads(
                            cat_path.read_text(encoding="utf-8")
                        )
                    except (json.JSONDecodeError, Exception):
                        logger.warning("Failed to load _category_lookup.json for %s", dtxsid)
                        integrated["_category_lookup"] = {}

            _integrated_pool[dtxsid] = integrated
    return integrated


# ---------------------------------------------------------------------------
# Per-section cache infrastructure
# ---------------------------------------------------------------------------
# Instead of one monolithic cache that invalidates on ANY parameter change,
# each pipeline stage has its own cache file with its own hash key.  This
# means changing compound_name only re-runs the ~1s section card builder,
# not the ~8min BMDS modeling.
#
# Cache file naming: _cache_{unit}_{hash}.json
# Units: ntp, sections, bmds, genomics, bmd_summary
#
# See the design table in CLAUDE.md (HIGH priority TODO) for the full
# hash-input matrix showing which changes invalidate which caches.

def _load_cache(dtxsid: str, unit: str, hash_val: str) -> dict | None:
    """
    Load a per-section cache file from disk.

    Returns the cached data dict, or None on cache miss / corruption.
    Uses orjson for fast deserialization (10-50x faster than json.loads
    on the multi-MB NTP stats cache).

    Args:
        dtxsid:   Session identifier — cache lives in sessions/{dtxsid}/.
        unit:     Cache unit name (ntp, sections, bmds, genomics, bmd_summary).
        hash_val: 16-char hex hash of the inputs that affect this unit.
    """
    cache_path = _session_dir(dtxsid) / f"_cache_{unit}_{hash_val}.json"
    if not cache_path.exists():
        return None
    try:
        data = orjson.loads(cache_path.read_bytes())
        logger.info("Cache hit: %s for %s (hash %s)", unit, dtxsid, hash_val)
        return data
    except Exception:
        logger.warning("Corrupted %s cache for %s, recomputing", unit, dtxsid)
        return None


def _save_cache(dtxsid: str, unit: str, hash_val: str, data: dict) -> None:
    """
    Persist a per-section cache to disk, cleaning up old hashes for the
    same unit.

    Each unit keeps at most one cache file on disk.  When the hash changes
    (because an input changed), the old file is deleted and the new one
    written.  Errors are logged but not raised — caching is a performance
    optimization, not a correctness requirement.

    Args:
        dtxsid:   Session identifier.
        unit:     Cache unit name.
        hash_val: 16-char hex hash of current inputs.
        data:     The payload to cache (must be JSON-serializable).
    """
    session = _session_dir(dtxsid)
    cache_path = session / f"_cache_{unit}_{hash_val}.json"
    try:
        # Remove stale caches for this unit (different hash = different inputs)
        for old in session.glob(f"_cache_{unit}_*.json"):
            if old != cache_path:
                old.unlink(missing_ok=True)
        cache_path.write_bytes(orjson.dumps(data))
        logger.info("Cached %s for %s (%s)", unit, dtxsid, cache_path.name)
    except Exception:
        logger.warning("Failed to cache %s for %s", unit, dtxsid, exc_info=True)


# ---------------------------------------------------------------------------
# Per-unit hash functions
# ---------------------------------------------------------------------------
# Each returns a 16-char hex string.  The hash inputs are chosen so that
# each unit only invalidates when its actual inputs change.  For example,
# BMDS hashes the raw dose-response data (doses/means/SEs/Ns), NOT the
# bmd_stat — so switching from "median" to "mean" doesn't re-run the
# 8-minute pybmds session.

def _hash_ntp(integrated: dict, bmd_stat: str) -> str:
    """
    Hash inputs that affect NTP stats computation.

    Inputs: integrated data identity (experiment names + count) and
    the primary BMD statistic (affects category lookup → BMD/BMDL
    values on TableRows).  xlsx_rosters are part of _meta and only
    change on re-integration, which deletes all caches anyway.
    """
    experiments = integrated.get("doseResponseExperiments", [])
    key = json.dumps({
        "bmd_stat": bmd_stat,
        "n_experiments": len(experiments),
        "experiment_names": sorted(e.get("name", "") for e in experiments),
    }, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _hash_sections(ntp_hash: str, compound_name: str, dose_unit: str) -> str:
    """
    Hash inputs that affect section card building.

    Depends on NTP stats output (via ntp_hash) plus display parameters
    that affect narrative text.  dtxsid is implicit (cache directory).
    """
    key = json.dumps({
        "ntp": ntp_hash,
        "compound_name": compound_name,
        "dose_unit": dose_unit,
    }, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _hash_bmds(bmds_inputs: list[dict]) -> str:
    """
    Hash the raw dose-response data for BMDS modeling.

    Uses CONTENT of _bmds_input dicts (doses, means, SEs, Ns) — NOT the
    ntp_hash.  This means BMDS stays cached even when bmd_stat changes,
    because the underlying dose-response data hasn't changed.
    """
    # Sort by endpoint key for deterministic hashing
    content = []
    for inp in sorted(bmds_inputs, key=lambda x: x.get("key", "")):
        content.append({
            "key": inp.get("key", ""),
            "doses": inp.get("doses", []),
            "ns": inp.get("ns", []),
            "means": inp.get("means", []),
            "stdevs": inp.get("stdevs", []),
        })
    key = json.dumps(content, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _hash_genomics(
    bmd_stats: list[str],
    go_pct: float,
    go_min_genes: int,
    go_max_genes: int,
    go_min_bmd: int,
    ge_filename: str,
) -> str:
    """
    Hash inputs that affect genomics extraction.

    bmd_stats (the full array) matters because each stat gets its own
    GO table.  GO filter cutoffs and the GE filename determine which
    categories pass and from which file.
    """
    key = json.dumps({
        "bmd_stats": list(bmd_stats),
        "ge_filename": ge_filename,
        "go_max_genes": go_max_genes,
        "go_min_bmd": go_min_bmd,
        "go_min_genes": go_min_genes,
        "go_pct": go_pct,
    }, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _hash_bmd_summary(ntp_hash: str, bmds_hash: str) -> str:
    """
    Hash inputs for the BMD summary tables.

    Depends on NTP stats (apical BMD summary uses platform_tables) and
    BMDS results (BMDS BMD summary merges pybmds output with TableRows).
    """
    key = f"{ntp_hash}:{bmds_hash}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _hash_methods(dtxsid: str, fingerprints: dict) -> str:
    """
    Hash inputs for the Materials and Methods section.

    Depends on the DTXSID (chemical identity) and fingerprint keys
    (which files are in the pool determines which M&M subsections
    appear — e.g., Transcriptomics only if gene expression exists).
    Content of fingerprints matters too (dose groups, endpoints, etc.
    feed into the LLM prompt), so we hash the full fingerprint dict.
    """
    fp_key = json.dumps(
        {k: str(v) for k, v in sorted(fingerprints.items())},
        sort_keys=True,
    )
    key = f"methods:{dtxsid}:{fp_key}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# TableRow serialization for NTP cache
# ---------------------------------------------------------------------------
# The NTP stats cache stores platform_tables: {platform -> {sex -> [TableRow]}}.
# TableRow is a dataclass, so we use asdict() for serialization.  Two wrinkles:
#   1. Float dict keys (values_by_dose, n_by_dose, missing_animals_by_dose)
#      must be converted to strings for JSON, then back to floats on load.
#   2. _bmds_input is dynamically attached (not a dataclass field), so
#      asdict() won't capture it — we handle it manually.

def _serialize_platform_tables(platform_tables: dict[str, dict[str, list]]) -> dict:
    """
    Convert platform_tables ({platform -> {sex -> [TableRow]}}) to a
    JSON-serializable dict for caching.

    Preserves all TableRow fields plus the dynamically-attached _bmds_input
    dict.  Float dict keys are converted to strings for JSON compatibility.

    Args:
        platform_tables: The partitioned NTP stats output.

    Returns:
        Nested dict structure safe for orjson serialization.
    """
    result = {}
    for platform, sex_rows in platform_tables.items():
        result[platform] = {}
        for sex, rows in sex_rows.items():
            serialized = []
            for row in rows:
                # asdict() handles all dataclass fields
                d = asdict(row)
                # Float keys → string keys for JSON roundtrip
                for fk_field in ("values_by_dose", "n_by_dose", "missing_animals_by_dose"):
                    if d.get(fk_field):
                        d[fk_field] = {str(k): v for k, v in d[fk_field].items()}
                # Coerce numpy scalar types to native Python types so orjson
                # can serialize them.  The Java stats pipeline (Williams/Dunnett)
                # returns numpy.bool_ for the responsive flag and occasionally
                # numpy.float64/numpy.int64 for other fields.  asdict() preserves
                # these numpy types rather than converting them.
                for key, val in d.items():
                    if hasattr(val, "item"):  # numpy scalar → .item() → native
                        d[key] = val.item()
                # Preserve dynamically-attached _bmds_input (not a dataclass field)
                if hasattr(row, "_bmds_input") and row._bmds_input:
                    d["_bmds_input"] = row._bmds_input
                serialized.append(d)
            result[platform][sex] = serialized
    return result


def _deserialize_platform_tables(data: dict) -> dict[str, dict[str, list]]:
    """
    Reconstruct platform_tables from a cached dict back to
    {platform -> {sex -> [TableRow]}} with proper types.

    String dict keys are converted back to floats.  _bmds_input is
    re-attached as a dynamic attribute.  Unknown keys (from future
    schema changes) are filtered out to avoid TypeError.

    Args:
        data: The cached dict from _serialize_platform_tables().

    Returns:
        platform_tables with live TableRow objects.
    """
    # Known dataclass fields — filter out _bmds_input and any future extras
    known_fields = {f.name for f in TableRow.__dataclass_fields__.values()}

    result = {}
    for platform, sex_rows in data.items():
        result[platform] = {}
        for sex, rows in sex_rows.items():
            deserialized = []
            for d in rows:
                # Pop _bmds_input before constructing TableRow (not a field)
                bmds_input = d.pop("_bmds_input", None)
                # String keys → float keys
                for fk_field in ("values_by_dose", "n_by_dose", "missing_animals_by_dose"):
                    if d.get(fk_field):
                        d[fk_field] = {float(k): v for k, v in d[fk_field].items()}
                # Filter to known fields only (forward compat)
                filtered = {k: v for k, v in d.items() if k in known_fields}
                row = TableRow(**filtered)
                if bmds_input:
                    row._bmds_input = bmds_input
                deserialized.append(row)
            result[platform][sex] = deserialized
    return result


def _restore_category_lookup(integrated: dict, bmd_stat: str) -> dict[tuple[str, str], dict]:
    """
    Restore the category lookup from the serialized pipe-separated keys in
    the integrated BMDProject.

    integrate_pool() stored this as _category_lookup with "prefix|endpoint"
    string keys; we restore them to (prefix, endpoint) tuple keys that
    build_table_data() expects.

    Also re-selects BMD/BMDL/BMDU values using the requested bmd_stat.
    build_category_lookup() stores the full stat blocks (bmd_stats,
    bmdl_stats, bmdu_stats) alongside the pre-selected values, so we can
    re-pick the statistic without re-running Java.

    Args:
        integrated: The merged BMDProject dict.
        bmd_stat:   The first (primary) BMD statistic key to select.

    Returns:
        Dict mapping (experiment_prefix, endpoint_name) to category info dicts.
    """
    flat_cat = integrated.get("_category_lookup", {})
    cat_lookup: dict[tuple[str, str], dict] = {}

    # Collect experiment names so we can resolve BMDExpress pipeline
    # suffixes in category keys.  Old integrated.json files may have
    # keys like "female_clin_chem_williams_0.05_NOMTC_nofoldfilter|endpoint"
    # but build_table_data() queries with "female_clin_chem".
    all_exp_names = sorted(
        [exp.get("name", "") for exp in integrated.get("doseResponseExperiments", [])],
        key=len, reverse=True,
    )

    for k, v in flat_cat.items():
        entry = dict(v)
        # Re-select from stored stat blocks if they exist.
        cat_bmd_blk = entry.get("bmd_stats", {})
        cat_bmdl_blk = entry.get("bmdl_stats", {})
        cat_bmdu_blk = entry.get("bmdu_stats", {})
        if cat_bmd_blk:
            entry["bmd"] = cat_bmd_blk.get(bmd_stat, cat_bmd_blk.get("mean", ""))
        if cat_bmdl_blk:
            entry["bmdl"] = cat_bmdl_blk.get(bmd_stat, cat_bmdl_blk.get("mean", ""))
        if cat_bmdu_blk:
            entry["bmdu"] = cat_bmdu_blk.get(bmd_stat, cat_bmdu_blk.get("mean", ""))

        prefix, endpoint = k.split("|", 1) if "|" in k else (k, "")

        # Resolve suffixed prefix to raw experiment name.
        # This handles both new (already resolved) and old (suffixed) keys.
        resolved = prefix
        for exp_name in all_exp_names:
            if prefix == exp_name:
                resolved = exp_name
                break
            if prefix.startswith(exp_name) and prefix[len(exp_name):len(exp_name) + 1] == "_":
                resolved = exp_name
                break

        cat_lookup[(resolved, endpoint)] = entry
        # Also keep the original key for backward compat
        if resolved != prefix:
            cat_lookup[(prefix, endpoint)] = entry

    return cat_lookup


def _filter_gene_expression(integrated: dict) -> dict:
    """
    Return a copy of the integrated BMDProject with gene expression
    experiments removed.

    Gene expression .bm2 data has thousands of probes — running Dunnett's
    test on each would be extremely slow and isn't meaningful for clinical
    endpoints.  Genomics is handled separately by export_genomics().

    Identifies gene expression experiments by checking which experiment names
    DON'T match any clinical platform prefix in _BM2_PLATFORM_MAP.

    Args:
        integrated: The full merged BMDProject dict.

    Returns:
        A shallow copy of integrated with gene expression experiments
        filtered from doseResponseExperiments.  Returns the original dict
        unchanged if no gene expression experiments were found.
    """
    meta = integrated.get("_meta", {})
    source_files = meta.get("source_files", {})
    ge_source = source_files.get("gene_expression")
    if not ge_source:
        return integrated

    # Gene expression experiments have names starting with the organ
    # (e.g., "Liver_PFHxSAm_Male_No0") — identify them by checking
    # which experiments DON'T match any clinical platform prefix.
    ge_exp_names = set()
    for exp in integrated.get("doseResponseExperiments", []):
        exp_name = exp.get("name", "")
        exp_lower = exp_name.lower().replace("_", "")
        matched = False
        for prefix in _BM2_PLATFORM_MAP:
            clean = exp_lower.replace("female", "").replace("male", "").strip()
            if clean.startswith(prefix) or prefix.startswith(clean):
                matched = True
                break
        if not matched:
            ge_exp_names.add(exp_name)

    if not ge_exp_names:
        return integrated

    logger.info(
        "Filtered %d gene expression experiments from NTP stats pipeline",
        len(ge_exp_names),
    )
    return {
        **integrated,
        "doseResponseExperiments": [
            exp for exp in integrated.get("doseResponseExperiments", [])
            if exp.get("name", "") not in ge_exp_names
        ],
    }


def _partition_by_platform(
    apical_integrated: dict,
    source_files: dict,
    table_data: dict[str, list],
) -> dict[str, dict[str, list]]:
    """
    Partition NTP stats TableRows by platform, preserving sex grouping.

    build_table_data() returns {"Male": [TableRow, ...], "Female": [...]}.
    We need to split these into per-platform sections so the UI can create
    separate section cards for Body Weight, Organ Weight, etc.

    Strategy: look at the experiment names in the integrated data to build
    a mapping of endpoint_name -> platform, then partition the table rows.

    Args:
        apical_integrated: The integrated BMDProject with GE experiments filtered out.
        source_files:      The _meta.source_files dict mapping platform -> file info.
        table_data:        The NTP stats output: {sex -> [TableRow, ...]}.

    Returns:
        Nested dict: {platform -> {sex -> [TableRow, ...]}}.
    """
    # Build experiment_name -> platform mapping.
    #
    # Primary: use the authoritative experimentDescription.platform field
    # (set by _stamp_domains in pool_integrator.py from fingerprint data).
    # Fallback for old sessions: try experimentDescription.domain (which
    # in newer sessions is already a platform string), then heuristics.
    exp_name_to_platform: dict[str, str] = {}

    for exp in apical_integrated.get("doseResponseExperiments", []):
        exp_name = exp.get("name", "")

        # --- Primary: authoritative platform from experimentDescription ---
        desc = exp.get("experimentDescription")
        if isinstance(desc, dict):
            # Prefer explicit platform field; fall back to domain field
            # (which in newer sessions contains a platform string like
            # "Body Weight" rather than the old "body_weight_inferred").
            platform_val = desc.get("platform") or desc.get("domain")
            if platform_val:
                exp_name_to_platform[exp_name] = platform_val
                continue

        # --- Fallback: legacy heuristics for old sessions ---
        exp_lower = exp_name.lower()

        # Strip sex suffix/prefix for matching.
        # IMPORTANT: strip "female" BEFORE "male" — "female" contains
        # "male" as a substring, so stripping "male" first leaves "fe".
        stripped = exp_lower.replace("female", "").replace("male", "").replace("_", "").strip()

        platform_for_exp = None
        for prefix, plat in _BM2_PLATFORM_MAP.items():
            if stripped.startswith(prefix) or prefix.startswith(stripped):
                platform_for_exp = plat
                break

        # Fallback: try detect_platform_and_type_from_bm2() which uses
        # the same _BM2_PLATFORM_MAP but with additional normalization.
        if not platform_for_exp:
            detected_platform, detected_dtype = detect_platform_and_type_from_bm2([exp_name])
            if detected_platform:
                platform_for_exp = detected_platform

        # Last resort: check if experiment name overlaps with source_files
        # platform keys (e.g., "Body Weight" → "bodyweight" matches in name).
        if not platform_for_exp:
            for plat_key in source_files:
                plat_normalized = plat_key.lower().replace(" ", "").replace("_", "")
                if plat_normalized in exp_lower.replace("_", ""):
                    platform_for_exp = plat_key
                    break

        if platform_for_exp:
            exp_name_to_platform[exp_name] = platform_for_exp

    # Build endpoint -> platform map using the experiment mapping.
    # Each probe/endpoint in an experiment inherits that experiment's platform.
    endpoint_platform_map: dict[str, str] = {}
    for exp in apical_integrated.get("doseResponseExperiments", []):
        exp_name = exp.get("name", "")
        plat = exp_name_to_platform.get(exp_name)
        if plat:
            for pr in exp.get("probeResponses", []):
                probe_id = pr.get("probe", {}).get("id", "")
                if probe_id:
                    endpoint_platform_map[(exp_name, probe_id)] = plat

    # Build a secondary map: (sex, probe_name) -> platform.
    # Since build_table_data doesn't preserve the experiment name on
    # TableRow, we match back using the probe label.
    sex_probe_platform: dict[tuple[str, str], str] = {}
    for (exp_name, probe_id), plat in endpoint_platform_map.items():
        sex = "Female" if "female" in exp_name.lower() else \
              "Male" if "male" in exp_name.lower() else "Unknown"
        sex_probe_platform[(sex, probe_id)] = plat

    # Partition: {platform: {sex: [TableRow, ...]}}
    platform_tables: dict[str, dict[str, list]] = {}
    for sex, rows in table_data.items():
        for row in rows:
            plat = sex_probe_platform.get((sex, row.label), "unknown")
            platform_tables.setdefault(plat, {}).setdefault(sex, []).append(row)

    return platform_tables


def _build_section_cards(
    platform_tables: dict[str, dict[str, list]],
    compound_name: str,
    dose_unit: str,
    dtxsid: str | None = None,
) -> list[dict]:
    """
    Build the UI section cards array: one per platform that has data.

    For each platform, serializes TableRow objects to JSON-friendly dicts
    and generates an auto-written results narrative.

    Special handling for Body Weight: when a tox_study sidecar JSON exists
    (written by tox_study_csv_to_pivot_txt), the body weight section uses
    build_body_weight_table_from_sidecar() instead of the generic path.
    This fixes three mismatches vs the NIEHS reference:
      1. Missing dose groups (333/1000 mg/kg where all animals died)
      2. Inflated N counts (Biosampling Animals included)
      3. Incorrect mean±SE (follows from #2)

    Args:
        platform_tables: The partitioned {platform -> {sex -> [TableRow, ...]}} dict.
        compound_name:   Chemical name for the narrative (e.g., "PFHxSAm").
        dose_unit:       Dose unit string (e.g., "mg/kg").
        dtxsid:          The DTXSID for this session.  Needed to locate sidecar
                         files for body weight.  If None, the generic path is used.

    Returns:
        List of section dicts, each with platform, title, tables_json, narrative.
        The platform string IS the display title (e.g., "Body Weight").
    """
    sections = []
    for platform, sex_rows in sorted(platform_tables.items()):
        # All endpoints appear in every table (CLAUDE.md business rule).
        # The NTP responsive gate does NOT control row inclusion — it
        # controls significance markers and the BMD summary only.
        # responsive_rows is kept as a convenience for the narrative
        # generator, which describes only the significant findings.
        responsive_rows = {
            sex: [r for r in rows if r.responsive]
            for sex, rows in sex_rows.items()
        }
        # Drop sex groups that have no responsive endpoints (for narrative only)
        responsive_rows = {s: rs for s, rs in responsive_rows.items() if rs}

        # ── Body Weight: use sidecar builder when available ──────────────
        # Body weight bypasses the responsive filter because the NIEHS
        # reference ALWAYS includes Table 2 (body weights) regardless of
        # whether the statistical gate passed.  The gate controls only
        # the BMD column values (ND vs numeric), not table inclusion.
        # When responsive_rows is empty (gate didn't pass), the sidecar
        # builder still produces the full table with ND in BMD columns.
        # The sidecar JSON has per-animal metadata (Selection, Observation
        # Day, Terminal Flag) that the generic build_table_data path loses.
        # This produces correct N counts (Core Animals only), all dose
        # groups (including those where animals died), and proper attrition
        # footnotes.
        if platform == "Body Weight" and dtxsid:
            from body_weight_table import (
                build_body_weight_table_from_sidecar,
                find_sidecar_paths,
            )
            session_dir = str(_session_dir(dtxsid))
            sidecar_paths = find_sidecar_paths(session_dir, platform="Body Weight")

            if sidecar_paths:
                # Extract BMD/BMDL results from the pipeline's TableRow data
                # so the sidecar builder can display them in the BMD columns.
                # The pipeline computes BMD from the pivoted data — we just
                # carry those results through to the sidecar-built table.
                bmd_results: dict[str, dict[str, str]] = {}
                for sex, rows in responsive_rows.items():
                    for row in rows:
                        # row.label is "SD0", "SD5", etc.
                        if row.label not in bmd_results:
                            bmd_results[row.label] = {
                                "bmd": row.bmd_str if row.bmd_str else "ND",
                                "bmdl": row.bmdl_str if row.bmdl_str else "ND",
                            }

                bw_result = build_body_weight_table_from_sidecar(
                    sidecar_paths,
                    bmd_results=bmd_results,
                    compound_name=compound_name,
                    dose_unit=dose_unit,
                )

                # The sidecar builder returns a full apical_sections entry
                # (title, caption, table_data, footnotes, bmd_definition,
                # etc.).  We need to reshape it to match the section card
                # format expected by the UI.
                # Pass only responsive rows to the narrative generator.
                # When empty (gate didn't pass), it produces "no significant
                # changes" text — which is correct.  DO NOT fall back to
                # sex_rows because that includes the old pre-sidecar pivot
                # rows which may have stale responsive=True flags.
                narrative = generate_results_narrative(
                    responsive_rows, compound_name, dose_unit,
                )
                sections.append({
                    "platform": platform,
                    "title": platform,
                    "tables_json": bw_result["table_data"],
                    "narrative": narrative,
                    # Pass through body-weight-specific fields that the
                    # Typst template and UI use for specialized rendering.
                    "first_col_header": bw_result.get("first_col_header"),
                    "caption": bw_result.get("caption"),
                    "footnotes": bw_result.get("footnotes"),
                    "bmd_definition": bw_result.get("bmd_definition"),
                })
                logger.info(
                    "Body Weight section built from sidecar (%d sexes, %d footnotes)",
                    len(bw_result["table_data"]),
                    len(bw_result.get("footnotes", [])),
                )
                continue  # skip generic path below

        # ── Clinical Pathology platforms (Tables 4/5/6): shared sidecar builder ─
        # Clinical Chemistry, Hematology, and Hormones share identical table
        # structure: sex-grouped rows, n-row, endpoint rows with mean±SE and
        # significance markers, BMD/BMDL columns.  The sidecar provides correct
        # Core Animals N counts; the NTP stats provide mean±SE with markers.
        if platform in ("Clinical Chemistry", "Hematology", "Hormones") and dtxsid:
            from table_builder_common import find_sidecar_paths as _find_sidecar
            from clinical_pathology_table import build_clinical_pathology_table_from_sidecar

            session_dir = str(_session_dir(dtxsid))
            sidecar_paths = _find_sidecar(session_dir, platform=platform)

            if sidecar_paths:
                # All endpoints appear in the table (not just responsive).
                # The responsive gate controls BMD column values (ND vs numeric),
                # not row inclusion — matching the body weight pattern.
                cp_result = build_clinical_pathology_table_from_sidecar(
                    platform=platform,
                    sidecar_paths=sidecar_paths,
                    ntp_stats=sex_rows,
                    compound_name=compound_name,
                    dose_unit=dose_unit,
                )

                if cp_result.get("table_data"):
                    narrative = generate_results_narrative(
                        responsive_rows, compound_name, dose_unit,
                    )
                    sections.append({
                        "platform": platform,
                        "title": platform,
                        "tables_json": cp_result["table_data"],
                        "narrative": narrative,
                        "first_col_header": cp_result.get("first_col_header"),
                        "caption": cp_result.get("caption"),
                        "footnotes": cp_result.get("footnotes"),
                        "bmd_definition": cp_result.get("bmd_definition"),
                        "significance_explanation": cp_result.get("significance_explanation"),
                        "significance_marker_legend": cp_result.get("significance_marker_legend"),
                    })
                    logger.info(
                        "%s section built from sidecar (%d sexes)",
                        platform, len(cp_result["table_data"]),
                    )
                    continue

        # ── Organ Weight (Table 3): sidecar builder with relative weights ──
        # The organ weight builder computes absolute + relative (per-animal
        # absolute/TBW × 1000) weights from raw sidecar data.  All organs
        # appear; the responsive gate controls BMD column values only.
        # Terminal Body Weight is always shown as a context row.
        if platform == "Organ Weight" and dtxsid:
            from table_builder_common import find_sidecar_paths as _find_sidecar
            from organ_weight_table import build_organ_weight_table_from_sidecar

            session_dir = str(_session_dir(dtxsid))
            sidecar_paths = _find_sidecar(session_dir, platform="Organ Weight")

            if sidecar_paths:
                ow_result = build_organ_weight_table_from_sidecar(
                    sidecar_paths=sidecar_paths,
                    ntp_stats=sex_rows,
                    compound_name=compound_name,
                    dose_unit=dose_unit,
                )

                if ow_result and ow_result.get("table_data"):
                    narrative = generate_results_narrative(
                        responsive_rows, compound_name, dose_unit,
                    )
                    sections.append({
                        "platform": platform,
                        "title": platform,
                        "tables_json": ow_result["table_data"],
                        "narrative": narrative,
                        "first_col_header": ow_result.get("first_col_header"),
                        "caption": ow_result.get("caption"),
                        "footnotes": ow_result.get("footnotes"),
                        "bmd_definition": ow_result.get("bmd_definition"),
                        "significance_explanation": ow_result.get("significance_explanation"),
                        "significance_marker_legend": ow_result.get("significance_marker_legend"),
                    })
                    logger.info(
                        "Organ Weight section built from sidecar (%d sexes)",
                        len(ow_result["table_data"]),
                    )
                    continue

        # ── Generic fallback for platforms without dedicated builders ───────
        # Also handles cases where sidecar data isn't available (e.g., data
        # uploaded as .bm2 without going through the integration pipeline).
        # All endpoints appear in the table (business rule) — sex_rows has
        # every row, not just responsive ones.  The narrative uses
        # responsive_rows so it only describes significant findings.
        if not sex_rows:
            continue

        tables_json = serialize_table_rows(sex_rows)
        narrative = generate_results_narrative(responsive_rows, compound_name, dose_unit)
        sections.append({
            "platform": platform,
            "title": platform,
            "tables_json": tables_json,
            "narrative": narrative,
        })
    return sections


async def _extract_genomics(
    dtxsid: str,
    integrated: dict,
    bmd_stats: list[str],
    go_pct: float,
    go_min_genes: int,
    go_max_genes: int,
    go_min_bmd: int,
) -> dict:
    """
    Extract gene expression genomics data from the integrated .bm2 file.

    If the integration included gene_expression, runs the BMDExpress 3 Java
    export to extract per-gene BMD and GO Biological Process category results.
    Applies user-configured GO filtering cutoffs, then builds per-organ/sex
    sections with ranked gene_sets tables and top_genes lists.

    Args:
        dtxsid:       The DTXSID for this session.
        integrated:   The full merged BMDProject dict.
        bmd_stats:    List of BMD statistic keys to generate tables for.
        go_pct:       Minimum % of genes in a category that must have BMD values.
        go_min_genes: Minimum total genes annotated to the GO category.
        go_max_genes: Maximum total genes (excludes overly broad categories).
        go_min_bmd:   Minimum genes with a BMD value in the category.

    Returns:
        Dict mapping "organ_sex" keys to genomics section dicts.
        Empty dict if no gene expression data exists.
    """
    genomics_sections = {}
    meta = integrated.get("_meta", {})
    ge_source = meta.get("source_files", {}).get("gene_expression")

    # Only proceed if gene expression data was included at the bm2 tier
    if not ge_source or ge_source.get("tier") != "bm2":
        return genomics_sections

    ge_filename = ge_source.get("filename", "")
    ge_path = _session_dir(dtxsid) / "files" / ge_filename

    if not ge_path.exists():
        return genomics_sections

    # Run the Java export in a thread pool (JVM startup ~0.5s)
    tmp_json = tempfile.NamedTemporaryFile(
        delete=False, suffix=".json", prefix="genomics_",
    )
    tmp_json.close()

    loop = asyncio.get_running_loop()
    try:
        ge_result = await loop.run_in_executor(
            None, export_genomics, str(ge_path), tmp_json.name,
        )

        # Reshape into the format the UI expects: keyed by organ_sex
        for exp in ge_result.get("experiments", []):
            organ = exp.get("organ", "unknown").lower()
            sex = exp.get("sex", "unknown").lower()
            key = f"{organ}_{sex}"

            # Sort genes by BMD ascending (lowest = most sensitive)
            genes = sorted(
                exp.get("genes", []),
                key=lambda g: _safe_float(g.get("bmd")),
            )

            # Filter GO terms by user-configured cutoffs
            raw_go = exp.get("go_bp", [])
            filtered_go = []
            for g in raw_go:
                n_total = g.get("n_genes", 0) or 0
                n_passed = g.get("n_passed", 0) or 0
                if n_total < go_min_genes or n_total > go_max_genes:
                    continue
                if n_passed < go_min_bmd:
                    continue
                pct = (n_passed / n_total * 100) if n_total > 0 else 0
                if pct < go_pct:
                    continue
                filtered_go.append(g)

            # Build a separate gene_sets table for each requested BMD statistic.
            # Categories where the stat is null (not computed by BMDExpress) are
            # excluded from that table entirely rather than falling back.
            gene_sets_by_stat = {}
            for stat in bmd_stats:
                stat_go = [
                    g for g in filtered_go
                    if _pick_go_stat(g, "bmd", stat) is not None
                ]
                stat_go.sort(
                    key=lambda g: _safe_float(_pick_go_stat(g, "bmd", stat)),
                )
                gene_sets_by_stat[stat] = [
                    {
                        "rank": i + 1,
                        "go_id": g["go_id"],
                        "go_term": g["go_term"],
                        "bmd": _pick_go_stat(g, "bmd", stat),
                        "bmdl": _pick_go_stat(g, "bmdl", stat),
                        "n_genes": g.get("n_genes", 0),
                        "n_genes_with_bmd": g.get("n_passed", 0),
                        "direction": g.get("direction", ""),
                        "fishers_p": g.get("fishers_two_tail"),
                        "genes": g.get("gene_symbols", ""),
                    }
                    for i, g in enumerate(stat_go[:20])
                ]

            genomics_sections[key] = {
                "organ": organ,
                "sex": sex,
                "total_probes": exp.get("total_probes", 0),
                "total_responsive_genes": len(genes),
                "gene_sets_by_stat": gene_sets_by_stat,
                # top_genes: ranked subset (top 20) shown in the UI gene table.
                "top_genes": [
                    {
                        "rank": i + 1,
                        "gene_symbol": g["gene_symbol"],
                        "bmd": g.get("bmd"),
                        "bmdl": g.get("bmdl"),
                        "bmdu": g.get("bmdu"),
                        "direction": g.get("direction", ""),
                        "fold_change": g.get("fold_change"),
                        "r_squared": g.get("r_squared"),
                    }
                    for i, g in enumerate(genes[:20])
                ],
                # all_genes: full responsive gene list for pathway/GO enrichment
                # in build_genomics_interpretation(). Kept lean (no rank/r²/bmdu)
                # because these are only used for enrichment input, not display.
                "all_genes": [
                    {
                        "gene_symbol": g["gene_symbol"],
                        "bmd": g.get("bmd"),
                        "bmdl": g.get("bmdl"),
                        "direction": g.get("direction", ""),
                        "fold_change": g.get("fold_change"),
                    }
                    for g in genes  # full list, not genes[:20]
                ],
            }
    finally:
        os.unlink(tmp_json.name)

    return genomics_sections



def _build_apical_bmd_summary(platform_tables: dict[str, dict[str, list]]) -> list[dict]:
    """
    Build the apical BMD summary (Table 8 equivalent) from BMDExpress 3 results.

    Collects BMD, BMDL, LOEL, NOEL, direction from ALL platform TableRows into
    a flat list for the separate BMD summary card.  Matches the NIEHS reference
    report structure where platform tables (Tables 2-7) show dose-response data
    and Table 8 summarizes BMDs.

    Only includes endpoints that have a BMD result OR significant trend/pairwise
    findings (LOEL exists).  Endpoints with neither are uninteresting.
    """
    summary = []
    for platform, sex_rows in sorted(platform_tables.items()):
        for sex, rows in sex_rows.items():
            # Sort within each sex group by BMDL (ascending).
            # Numeric BMDL values first; non-numeric statuses (NVM, UREP, "—")
            # sort to the end so the most potent endpoints appear at top.
            sorted_rows = sorted(
                rows,
                key=lambda r: _safe_float_from_bmdl(r.bmdl_str),
            )
            for row in sorted_rows:
                has_bmd = row.bmd_status is not None
                has_loel = row.loel is not None
                if not has_bmd and not has_loel:
                    continue
                summary.append({
                    "endpoint": row.label,
                    "sex": sex,
                    "platform": platform,
                    "bmd": row.bmd_str,
                    "bmdl": row.bmdl_str,
                    "bmd_status": row.bmd_status,
                    "loel": row.loel,
                    "noel": row.noel,
                    "direction": row.direction,
                })
    return summary


def _build_bmds_bmd_summary(
    platform_tables: dict[str, dict[str, list]],
    bmds_results: dict,
) -> list[dict]:
    """
    Build the BMDS-based BMD summary (second Table 8) using pybmds results.

    Same structure as the BMDExpress 3 summary, but using EPA BMDS continuous
    model results.  Only includes endpoints where pybmds produced a result AND
    there's either a viable model or a significant LOEL.

    Formats BMD/BMDL strings matching NIEHS conventions:
      - viable: numeric value (e.g., "12.3")
      - NR:     "<lowest_nonzero_dose/3" (e.g., "<0.1")
      - UREP:   "UREP" (unreliable endpoint)
      - NVM:    "NVM" (no viable model)
    """
    if not bmds_results:
        return []

    summary = []
    for platform, sex_rows in sorted(platform_tables.items()):
        for sex, rows in sex_rows.items():
            # Sort within each sex group by BMDL (ascending), matching
            # the apical BMD summary sort order.
            sorted_rows = sorted(
                rows,
                key=lambda r: _safe_float_from_bmdl(r.bmdl_str),
            )
            for row in sorted_rows:
                bmds_key = f"{sex}::{row.label}"
                bmds_res = bmds_results.get(bmds_key)
                if not bmds_res:
                    continue

                # Inclusion gate: significant LOEL or viable BMDS result
                has_viable_bmds = bmds_res["status"] == "viable"
                has_loel = row.loel is not None
                if not has_viable_bmds and not has_loel:
                    continue

                # Format BMD/BMDL strings matching NIEHS conventions
                status = bmds_res["status"]
                if status == "viable" and bmds_res["bmd"] is not None:
                    bmd_str = f"{bmds_res['bmd']:.3g}"
                    bmdl_str = f"{bmds_res['bmdl']:.3g}" if bmds_res["bmdl"] else "—"
                elif status == "NR":
                    nonzero = [d for d in row.values_by_dose if d > 0]
                    lnzd = min(nonzero) if nonzero else 0
                    bmd_str = f"<{lnzd / 3:.3g}" if lnzd > 0 else "NR"
                    bmdl_str = "—"
                elif status == "UREP":
                    bmd_str = "UREP"
                    bmdl_str = "UREP"
                else:
                    bmd_str = "NVM"
                    bmdl_str = "NVM"

                summary.append({
                    "endpoint": row.label,
                    "sex": sex,
                    "platform": platform,
                    "bmd": bmd_str,
                    "bmdl": bmdl_str,
                    "bmd_status": status,
                    "model_name": bmds_res.get("model_name"),
                    "loel": row.loel,
                    "noel": row.noel,
                    "direction": row.direction,
                })
    return summary


@router.post("/api/process-integrated/{dtxsid}")
async def api_process_integrated(dtxsid: str, request: Request):
    """
    Process the integrated BMDProject JSON into section cards with tables
    and narratives for each apical endpoint platform.

    Input JSON:
      {
        "compound_name": "PFHxSAm",
        "dose_unit": "mg/kg",
        "bmd_stats": ["median"],  // optional: mean, median, minimum, etc.
        "go_pct": 5,              // optional: GO category filter cutoffs
        "go_min_genes": 20,
        "go_max_genes": 500,
        "go_min_bmd": 3
      }

    Orchestrates the processing pipeline:
      1. Load integrated data (memory or disk)
      2. Check disk cache (return instantly on hit)
      3. Restore category lookup from serialized keys
      4. Filter gene expression experiments
      5. Run NTP stats (Williams trend + Dunnett's pairwise + Jonckheere)
      6. Partition results by platform
      7. Build section cards with narratives
      8. Run BMDS modeling (pybmds)
      9. Extract genomics from gene expression .bm2
      10. Build BMD summaries (BMDExpress 3 + BMDS)
      11. Cache and return
    """
    # --- Parse request parameters ---
    # Tolerate empty or missing request bodies — the UI sometimes sends
    # POST with no content (e.g., from a simple fetch without JSON body).
    try:
        body = await request.json()
    except Exception:
        body = {}
    compound_name = body.get("compound_name", "Test Compound")
    dose_unit = body.get("dose_unit", "mg/kg")

    # BMD statistics — array of stat keys, each producing a separate GO table.
    # Accepts both the old single "bmd_stat" and the new "bmd_stats" array.
    bmd_stats_raw = body.get("bmd_stats", None)
    bmd_stats = bmd_stats_raw if bmd_stats_raw and isinstance(bmd_stats_raw, list) \
        else [body.get("bmd_stat", "median")]
    bmd_stat = bmd_stats[0]  # primary stat for category lookup

    # GO category filter cutoffs from the Settings panel
    go_pct = body.get("go_pct", 5)
    go_min_genes = body.get("go_min_genes", 20)
    go_max_genes = body.get("go_max_genes", 500)
    go_min_bmd = body.get("go_min_bmd", 3)

    # --- Load integrated data ---
    integrated = _load_integrated(dtxsid)
    if not integrated:
        return JSONResponse(
            {"error": "No integrated data found -- run integration first"},
            status_code=400,
        )

    # --- Migrate old monolithic cache files ---
    # The old _processed_cache_{hash}.json format is replaced by per-section
    # caches.  Delete any leftover monolithic files so they don't accumulate.
    for old_cache in _session_dir(dtxsid).glob("_processed_cache_*.json"):
        old_cache.unlink(missing_ok=True)
        logger.info("Migrated old monolithic cache: %s", old_cache.name)

    try:
        # ══════════════════════════════════════════════════════════════
        # Layer 1 — NTP stats (depends only on integrated data + bmd_stat)
        # ══════════════════════════════════════════════════════════════
        # This is the foundation: category lookup → filter GE experiments →
        # build_table_data (Java Williams/Dunnett/Jonckheere) → partition
        # by platform → annotate missing animals.  ~5s on miss.
        ntp_hash = _hash_ntp(integrated, bmd_stat)
        ntp_cached = _load_cache(dtxsid, "ntp", ntp_hash)

        if ntp_cached:
            platform_tables = _deserialize_platform_tables(ntp_cached)
        else:
            cat_lookup = _restore_category_lookup(integrated, bmd_stat)
            apical_integrated = _filter_gene_expression(integrated)

            loop = asyncio.get_running_loop()
            table_data = await loop.run_in_executor(
                None, build_table_data, apical_integrated, cat_lookup,
            )

            source_files = integrated.get("_meta", {}).get("source_files", {})
            platform_tables = _partition_by_platform(
                apical_integrated, source_files, table_data,
            )

            # Annotate missing animals from xlsx study file rosters —
            # compare bm2 N counts against xlsx Core Animals roster to
            # detect animals that died before terminal sacrifice.
            xlsx_rosters = integrated.get("_meta", {}).get("xlsx_rosters", {})
            if xlsx_rosters:
                annotate_missing_animals(platform_tables, xlsx_rosters)
                # Backfill absent dose columns with "–" so every platform
                # table shows the full study dose design (NIEHS convention).
                backfill_missing_doses(platform_tables, xlsx_rosters)

            _save_cache(
                dtxsid, "ntp", ntp_hash,
                _serialize_platform_tables(platform_tables),
            )

        # ══════════════════════════════════════════════════════════════
        # Layer 2 — Sections + BMDS + Genomics (independent, parallel)
        # ══════════════════════════════════════════════════════════════
        # These three units depend on Layer 1 output but NOT on each other,
        # so they can run concurrently.  BMDS (~8min) is the bottleneck;
        # sections (<1s) and genomics (~10s) finish quickly alongside it.

        # Collect _bmds_input dicts from all TableRows for BMDS modeling
        bmds_inputs = [
            row._bmds_input
            for sex_rows in platform_tables.values()
            for rows in sex_rows.values()
            for row in rows
            if hasattr(row, "_bmds_input") and row._bmds_input
        ]

        # Compute per-unit hashes
        sections_hash = _hash_sections(ntp_hash, compound_name, dose_unit)
        bmds_hash = _hash_bmds(bmds_inputs) if bmds_inputs else "empty"

        meta = integrated.get("_meta", {})
        ge_source = meta.get("source_files", {}).get("gene_expression")
        ge_filename = ge_source.get("filename", "") if ge_source else ""
        genomics_hash = _hash_genomics(
            bmd_stats, go_pct, go_min_genes, go_max_genes, go_min_bmd,
            ge_filename,
        )

        # Check each cache independently
        sections_cached = _load_cache(dtxsid, "sections", sections_hash)
        bmds_cached = _load_cache(dtxsid, "bmds", bmds_hash)
        genomics_cached = _load_cache(dtxsid, "genomics", genomics_hash)

        # --- Async wrappers: return cached data or compute + cache ---

        async def _get_sections():
            """Build section cards with narratives + unified narratives, or return cached."""
            if sections_cached:
                return (
                    sections_cached["sections"],
                    sections_cached.get("unified_narratives", {}),
                )
            # _build_section_cards is sync (reads sidecar files, generates
            # narratives from templates) — wrap in executor to avoid
            # blocking the event loop during parallel execution.
            loop = asyncio.get_running_loop()
            sections = await loop.run_in_executor(
                None,
                lambda: _build_section_cards(
                    platform_tables, compound_name, dose_unit, dtxsid=dtxsid,
                ),
            )
            # Clinical obs tables bypass Java integration (categorical data).
            # Built separately and appended as an incidence section card.
            clin_obs = _build_clinical_obs_section(
                integrated, compound_name, dose_unit,
            )
            if clin_obs:
                sections.append(clin_obs)

            # ── Tissue Concentration (Table 7): pharmacokinetic table ──────
            # Tissue Concentration data only exists for Biosampling Animals
            # and is NOT processed through NTP stats or BMDExpress.  It has
            # no entries in platform_tables, so it must be built separately
            # from sidecar data (similar to Clinical Observations).
            if dtxsid:
                from table_builder_common import find_sidecar_paths as _find_sidecar
                from tissue_concentration_table import build_tissue_concentration_table_from_sidecar

                session_dir = str(_session_dir(dtxsid))
                tc_sidecar_paths = _find_sidecar(session_dir, platform="Tissue Concentration")
                if tc_sidecar_paths:
                    tc_result = build_tissue_concentration_table_from_sidecar(
                        sidecar_paths=tc_sidecar_paths,
                        compound_name=compound_name,
                        dose_unit=dose_unit,
                    )
                    if tc_result and tc_result.get("table_data"):
                        narrative = (
                            f"Plasma concentrations of {compound_name} were "
                            f"measured in biosampling animals."
                        )
                        sections.append({
                            "platform": "Tissue Concentration",
                            "title": "Tissue Concentration",
                            "tables_json": tc_result["table_data"],
                            "narrative": narrative,
                            "first_col_header": tc_result.get("first_col_header"),
                            "caption": tc_result.get("caption"),
                            "footnotes": tc_result.get("footnotes"),
                            "table_type": tc_result.get("table_type"),
                        })
                        logger.info(
                            "Tissue Concentration section built from sidecar (%d sexes)",
                            len(tc_result["table_data"]),
                        )

            # ── Unified cross-platform narratives ─────────────────────────
            # The NIEHS reference report groups narrative prose into two
            # unified sections that span multiple platforms, rather than
            # per-platform isolated narratives.  These are generated here
            # alongside the per-card narratives (which are kept for backward
            # compatibility with old approved sessions).
            from unified_narrative import (
                extract_mortality,
                generate_apical_narrative,
                generate_clinical_pathology_narrative,
            )
            from body_weight_table import find_sidecar_paths

            # 1. Load mortality data from body weight sidecars
            session_dir = str(_session_dir(dtxsid))
            sidecar_paths = find_sidecar_paths(session_dir, platform="Body Weight")
            sidecar_mortality = extract_mortality(sidecar_paths) if sidecar_paths else None

            # 2. Load clinical obs incidence for the animal condition paragraph
            meta = integrated.get("_meta", {})
            csv_paths = meta.get("clinical_obs_files", [])
            clin_obs_incidence = None
            if csv_paths:
                clin_obs_incidence = build_clinical_obs_tables(csv_paths)

            # 3. Generate the two unified narratives
            apical_narrative = generate_apical_narrative(
                platform_tables, compound_name, dose_unit,
                sidecar_mortality=sidecar_mortality,
                clinical_obs_incidence=clin_obs_incidence,
            )
            clin_path_narrative = generate_clinical_pathology_narrative(
                platform_tables, compound_name, dose_unit,
            )

            unified_narratives = {}
            if apical_narrative:
                unified_narratives["apical"] = {
                    "title": "Animal Condition, Body Weights, and Organ Weights",
                    "paragraphs": apical_narrative,
                }
            if clin_path_narrative:
                unified_narratives["clinical_pathology"] = {
                    "title": "Clinical Pathology",
                    "paragraphs": clin_path_narrative,
                }

            _save_cache(dtxsid, "sections", sections_hash, {
                "sections": sections,
                "unified_narratives": unified_narratives,
            })
            return sections, unified_narratives

        async def _get_bmds():
            """Run pybmds modeling on all endpoints, or return cached."""
            if bmds_cached:
                return bmds_cached
            if not bmds_inputs:
                return {}
            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(
                None, run_bmds_for_endpoints, bmds_inputs,
            )
            _save_cache(dtxsid, "bmds", bmds_hash, results)
            return results

        async def _get_genomics():
            """Extract gene expression + GO filtering, or return cached."""
            if genomics_cached:
                return genomics_cached
            result = await _extract_genomics(
                dtxsid, integrated, bmd_stats,
                go_pct, go_min_genes, go_max_genes, go_min_bmd,
            )
            _save_cache(dtxsid, "genomics", genomics_hash, result)
            return result

        # --- Materials and Methods (LLM-generated, cached) ---
        # Uses fingerprints + .bm2 metadata + animal report to extract
        # study context, then calls the LLM to produce structured prose
        # for each M&M subsection.  Runs in parallel with the other
        # Layer 2 tasks since it has no dependency on NTP stats output.

        # Collect fingerprints as plain dicts for the methods context extractor
        _fps_for_methods = {}
        session_fps = _pool_fingerprints.get(dtxsid, {})
        for fid, fp in session_fps.items():
            if hasattr(fp, "__dataclass_fields__"):
                _fps_for_methods[fid] = {
                    k: getattr(fp, k) for k in fp.__dataclass_fields__
                }
            else:
                _fps_for_methods[fid] = fp

        methods_hash = _hash_methods(dtxsid, _fps_for_methods)
        methods_cached = _load_cache(dtxsid, "methods", methods_hash)

        async def _get_methods():
            """
            Generate Materials and Methods via LLM, or return cached.

            Extracts study metadata from fingerprints, animal report, and
            .bm2 caches (dose groups, sample sizes, BMDExpress parameters),
            then calls the LLM to produce structured prose for each NIEHS
            M&M subsection.  The result is cached so subsequent calls
            (page reloads, PDF exports) return instantly.
            """
            if methods_cached:
                return methods_cached

            from methods_report import (
                MethodsReport,
                MethodsSection,
                build_methods_prompt,
                build_subsection_skeleton,
                build_table1_data,
                extract_methods_context,
            )
            from bmdx_pipe import bm2_cache as _bm2_cache

            # Load identity from session (chemical name, casrn, dtxsid)
            identity = {"dtxsid": dtxsid}
            identity_path = _session_dir(dtxsid) / "identity.json"
            if identity_path.exists():
                try:
                    identity = json.loads(identity_path.read_text())
                except Exception:
                    pass

            # Collect .bm2 JSON caches for BMDExpress metadata extraction
            bm2_jsons = {}
            session_files_dir = _session_dir(dtxsid) / "files"
            if session_files_dir.exists():
                for bm2_path in session_files_dir.glob("*.bm2"):
                    try:
                        cached = _bm2_cache.get_json(str(bm2_path))
                        if cached:
                            bm2_jsons[bm2_path.stem] = cached
                    except Exception:
                        pass

            # Load animal report from session
            animal_report_data = None
            ar_path = _session_dir(dtxsid) / "animal_report.json"
            if ar_path.exists():
                try:
                    animal_report_data = json.loads(ar_path.read_text())
                except Exception:
                    pass

            # Default study params — the NIEHS 5-day gavage protocol
            study_params = {
                "vehicle": "corn oil",
                "route": "gavage",
                "duration_days": 5,
                "species": "Sprague Dawley",
            }

            # Extract structured context from all data sources
            ctx = extract_methods_context(
                identity=identity,
                fingerprints=_fps_for_methods,
                animal_report=animal_report_data,
                study_params=study_params,
                bm2_jsons=bm2_jsons,
            )

            # Build and call the LLM
            system, prompt = build_methods_prompt(ctx)
            try:
                subsection_texts = await _llm_generate_json_async(
                    "methods-generator", prompt, system,
                )
            except Exception as e:
                logger.warning("Methods LLM generation failed: %s", e)
                return None

            # Assemble into structured sections
            skeleton = build_subsection_skeleton(ctx)
            sections = []
            for key, heading, level in skeleton:
                text = subsection_texts.get(key, "")
                if not text:
                    continue
                paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
                sections.append(MethodsSection(
                    heading=heading,
                    level=level,
                    key=key,
                    paragraphs=paragraphs,
                ))

            table1 = build_table1_data(ctx)
            report = MethodsReport(sections=sections, context=ctx)
            report_dict = report.to_dict()

            if table1:
                report_dict["table1"] = table1

            report_dict["section_key"] = "methods"
            report_dict["model_used"] = "claude-sonnet-4-6"

            _save_cache(dtxsid, "methods", methods_hash, report_dict)
            return report_dict

        # Launch all four concurrently — cached units return instantly,
        # uncached units run in parallel (BMDS in thread pool, genomics
        # in thread pool via _extract_genomics, sections in thread pool,
        # methods via async LLM call).
        # _get_sections returns a 2-tuple: (sections, unified_narratives).
        sections_result, bmds_results, genomics_sections, methods_result = \
            await asyncio.gather(
                _get_sections(), _get_bmds(), _get_genomics(), _get_methods(),
            )
        sections, unified_narratives = sections_result

        # ══════════════════════════════════════════════════════════════
        # Layer 2.5 — Charts + Enrichr (depends on genomics output)
        # ══════════════════════════════════════════════════════════════
        # Server-side Plotly rendering of UMAP scatter and cluster scatter
        # charts, plus Enrichr enrichment analysis for each gene-overlap
        # cluster.  Cached as _cache_charts_{hash}.json so that PDF
        # previews and exports never re-render charts or re-call Enrichr.
        #
        # The hash is the same as genomics (same inputs determine the
        # gene sets that feed the charts).  Chart images are base64 PNGs.
        chart_images = []
        if genomics_sections:
            charts_hash = genomics_hash  # same inputs → same cache lifetime
            charts_cached = _load_cache(dtxsid, "charts", charts_hash)

            if charts_cached:
                chart_images = charts_cached
            else:
                from genomics_viz import render_chart_images

                loop = asyncio.get_running_loop()
                for key, gen_data in genomics_sections.items():
                    # Use the primary BMD stat's gene_sets for chart rendering
                    gs_by_stat = gen_data.get("gene_sets_by_stat", {})
                    gene_sets = gs_by_stat.get(bmd_stat, [])
                    if not gene_sets:
                        continue

                    organ = gen_data.get("organ", "")
                    sex = gen_data.get("sex", "")
                    organ_title = organ.capitalize() or "Unknown"
                    sex_title = sex.capitalize() or ""

                    try:
                        result = await loop.run_in_executor(
                            None,
                            lambda gs=gene_sets, o=organ, s=sex: render_chart_images(
                                gene_sets=gs,
                                organ=o,
                                sex=s,
                                dose_unit=dose_unit,
                            ),
                        )
                        result["label"] = f"{organ_title} ({sex_title})"
                        result["organ"] = organ
                        result["sex"] = sex
                        chart_images.append(result)
                    except Exception as e:
                        logger.warning(
                            "Chart rendering failed for %s: %s", key, e,
                        )

                if chart_images:
                    _save_cache(dtxsid, "charts", charts_hash, chart_images)

        # ══════════════════════════════════════════════════════════════
        # Layer 3 — BMD summary (depends on NTP + BMDS)
        # ══════════════════════════════════════════════════════════════
        # Two summary tables: one from BMDExpress 3 results (apical) and
        # one from pybmds results (BMDS).  Both need platform_tables +
        # bmds_results, so they run after Layers 1 and 2 complete.
        bmd_summary_hash = _hash_bmd_summary(ntp_hash, bmds_hash)
        bmd_summary_cached = _load_cache(dtxsid, "bmd_summary", bmd_summary_hash)

        if bmd_summary_cached:
            apical_bmd_summary = bmd_summary_cached["apical"]
            apical_bmd_summary_bmds = bmd_summary_cached["bmds"]
        else:
            apical_bmd_summary = _build_apical_bmd_summary(platform_tables)
            apical_bmd_summary_bmds = _build_bmds_bmd_summary(
                platform_tables, bmds_results,
            )
            _save_cache(dtxsid, "bmd_summary", bmd_summary_hash, {
                "apical": apical_bmd_summary,
                "bmds": apical_bmd_summary_bmds,
            })

        # ══════════════════════════════════════════════════════════════
        # Assembly — combine all results into response payload
        # ══════════════════════════════════════════════════════════════
        # Identical structure to the old monolithic response so the
        # frontend doesn't need any changes.
        stat_labels = {
            s: _BMD_STAT_LABELS.get(s, s.replace("_", " ").title())
            for s in bmd_stats
        }
        result_payload = {
            "sections": sections,
            "unified_narratives": unified_narratives,
            "genomics_sections": genomics_sections,
            "chart_images": chart_images if chart_images else None,
            "apical_bmd_summary": apical_bmd_summary,
            "apical_bmd_summary_bmds": apical_bmd_summary_bmds,
            "bmd_stats": list(bmd_stats),
            "bmd_stat_labels": stat_labels,
            # Materials and Methods — LLM-generated structured sections.
            # Included so the frontend can auto-populate the M&M section
            # without requiring a separate generate button click.
            "methods": methods_result,
        }

        return JSONResponse(result_payload)

    except Exception as e:
        logger.exception("Processing integrated data failed for %s", dtxsid)
        return JSONResponse(
            {"error": f"Processing failed: {e}"},
            status_code=500,
        )


@router.post("/api/generate-animal-report/{dtxsid}")
async def api_generate_animal_report(dtxsid: str):
    """
    Generate a per-animal traceability report for a session's file pool.

    Reads all fingerprinted files from disk, extracts per-animal data
    (animal_id -> dose, sex, selection), and cross-references across
    tiers and platforms.  Persists the result to
    sessions/{dtxsid}/animal_report.json.

    Requires fingerprints to exist (from prior /api/pool/validate call).
    If no fingerprints are cached, re-fingerprints all files first.

    Returns the full AnimalReport as JSON.
    """
    session_path = _session_dir(dtxsid)
    files_dir = session_path / "files"

    if not files_dir.exists():
        return JSONResponse(
            {"error": "No files directory found for this session"},
            status_code=404,
        )

    # Ensure we have fingerprints -- re-fingerprint if the pool is empty.
    # This can happen if the server restarted since the last validation.
    fps = ensure_fingerprints(dtxsid)

    if not fps:
        return JSONResponse(
            {"error": "No fingerprinted files found -- upload files first"},
            status_code=400,
        )

    # Build the animal report in a thread executor to avoid blocking
    # the event loop (xlsx/bm2 parsing can take a few seconds).
    loop = asyncio.get_running_loop()
    try:
        report = await loop.run_in_executor(
            None,
            build_animal_report,
            str(session_path),
            fps,
        )
    except Exception as e:
        logger.exception("Failed to build animal report for %s", dtxsid)
        return JSONResponse(
            {"error": f"Animal report generation failed: {e}"},
            status_code=500,
        )

    # Serialize and persist to disk
    report_dict = report_to_dict(report)
    report_path = session_path / "animal_report.json"
    report_path.write_text(
        json.dumps(report_dict, indent=2, default=str),
        encoding="utf-8",
    )

    return Response(
        content=orjson.dumps(report_dict),
        media_type="application/json",
    )
