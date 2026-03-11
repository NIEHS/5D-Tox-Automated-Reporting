"""
Pool orchestrator — file pool fingerprinting, validation, integration, and
processing endpoints extracted from background_server.py.

This module owns the full lifecycle of the "file pool" concept:

  1. **Fingerprinting** — extract structural metadata (doses, animals, endpoints,
     domain) from each uploaded file so we can cross-validate them.
  2. **Validation** — check for dose group mismatches, coverage gaps, and
     redundancy across the pool.
  3. **Conflict resolution** — persist user precedence decisions when files
     disagree.
  4. **Integration** — merge the best file per domain into a single unified
     BMDProject JSON via bmdx-core's native Java classes.
  5. **Processing** — run NTP stats on the integrated data to produce per-domain
     section cards (tables + narratives) for the UI, plus genomics extraction
     from gene-expression .bm2 files.
  6. **Animal traceability** — per-animal cross-tier/cross-domain report.

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
from llm_helpers import llm_generate_json as _llm_generate_json_imported

from file_integrator import (
    FileFingerprint,
    ValidationReport,
    fingerprint_file,
    validate_pool,
    lightweight_validate,
    _BM2_DOMAIN_MAP,
    detect_domain,
)
from pool_integrator import integrate_pool
from animal_report import (
    build_animal_report,
    report_to_dict,
)
from apical_report import (
    build_table_data,
    export_genomics,
    generate_results_narrative,
)

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
    (matching the NIEHS reference report structure: domain tables + Table 8).
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
            tables_json[sex].append({
                "label": row.label,
                "doses": sorted_doses,
                "values": {_js_dose_key(d): v for d, v in row.values_by_dose.items()},
                "n": {_js_dose_key(d): n for d, n in row.n_by_dose.items()},
                "trend_marker": row.trend_marker,
            })
    return tables_json


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

    Args:
        file_id:   UUID from upload.
        filename:  Original filename.
        path:      Absolute path to the file on disk.
        file_type: "xlsx", "txt", "csv", or "bm2".
        dtxsid:    The DTXSID session this file belongs to.
        bm2_json:  Pre-loaded BMDProject dict (optional, for bm2 files).

    Returns:
        The created FileFingerprint.
    """
    ts_added = datetime.now(tz=timezone.utc).isoformat()
    fp = fingerprint_file(file_id, filename, path, file_type, ts_added, bm2_json)

    if dtxsid:
        if dtxsid not in _pool_fingerprints:
            _pool_fingerprints[dtxsid] = {}
        _pool_fingerprints[dtxsid][file_id] = fp
        # Persist to disk so session restore can skip the expensive LLM call
        # in _deduce_metadata_from_experiments().  Keyed by filename (stable
        # across restarts) rather than file_id (regenerated each session load).
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
    # n_animals_by_dose keys are floats but JSON serializes them as strings —
    # convert back to float keys.
    if entry.get("n_animals_by_dose"):
        entry["n_animals_by_dose"] = {
            float(k): v for k, v in entry["n_animals_by_dose"].items()
        }
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

    # 2. Fingerprint files registered in _data_uploads
    for fid, entry in _data_uploads.items():
        path = entry.get("temp_path", "")
        if path and os.path.exists(path) and str(files_dir) in path:
            fingerprint_and_store(fid, entry["filename"], path, entry["type"], dtxsid)
            fingerprinted.add(entry["filename"])

    # 3. Scan files/ directory for anything not yet registered
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
      - coverage_matrix: domain -> tier -> file_id(s)
      - issues: list of { severity, domain, issue_type, message, ... }
      - is_complete: whether all domains have full tier coverage

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


@router.post("/api/pool/integrate/{dtxsid}")
async def api_pool_integrate(dtxsid: str, request: Request):
    """
    Merge all pool files into a unified BMDProject JSON.

    Reads fingerprints from _pool_fingerprints, coverage_matrix from the
    persisted validation_report.json, and precedence decisions from
    precedence.json.  Calls integrate_pool() to select the best file per
    domain and produce the merged structure.

    The result is stored both in-memory (_integrated_pool) and on disk
    (sessions/{dtxsid}/integrated.json) for session restore.

    Returns the full integrated BMDProject JSON, including a _meta block
    with provenance: which file was chosen for each domain and why.
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

    # Invalidate any stale processed-results caches from previous integration
    # runs — the input data has changed, so cached NTP stats are stale.
    for old_cache in _session_dir(dtxsid).glob("_processed_cache_*.json"):
        old_cache.unlink(missing_ok=True)
        logger.debug("Invalidated stale process cache: %s", old_cache.name)

    # Return a lightweight summary instead of the full integrated JSON
    # (which can be 50+ MB and exceeds Cloud Run's 32 MiB response limit).
    # The client can fetch the full data via GET /api/integrated/{dtxsid}
    # if needed (that endpoint uses FileResponse with chunked streaming).
    #
    # The summary mirrors the structure the client's renderIntegratedPreview()
    # expects: _meta.source_files for the domain table, plus top-level counts.
    meta = integrated.get("_meta", {})
    experiments = integrated.get("doseResponseExperiments", [])
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

    Loads from in-memory cache or disk, then extracts only the metadata
    and per-experiment names/probe counts -- NOT the full response arrays.
    """
    integrated = _integrated_pool.get(dtxsid)
    if integrated is None:
        integrated_path = _session_dir(dtxsid) / "integrated.json"
        if integrated_path.exists():
            try:
                integrated = json.loads(integrated_path.read_text(encoding="utf-8"))
                _integrated_pool[dtxsid] = integrated
            except (json.JSONDecodeError, Exception):
                pass

    if not integrated:
        return JSONResponse(
            {"error": "No integrated data found"},
            status_code=404,
        )

    meta = integrated.get("_meta", {})
    experiments = integrated.get("doseResponseExperiments", [])
    bmd_results = integrated.get("bMDResult", [])
    cat_results = integrated.get("categoryAnalysisResults", [])

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


@router.post("/api/process-integrated/{dtxsid}")
async def api_process_integrated(dtxsid: str, request: Request):
    """
    Process the integrated BMDProject JSON into section cards with tables
    and narratives for each apical endpoint domain.

    Input JSON:
      {
        "compound_name": "PFHxSAm",
        "dose_unit": "mg/kg",
        "bmd_stat": "mean"        // optional: mean, median, minimum, etc.
      }

    Loads the integrated JSON from _integrated_pool (in-memory) or from
    sessions/{dtxsid}/integrated.json (disk fallback).  Calls
    build_table_data() to run NTP stats on all experiments, then partitions
    the results by domain for the UI's section cards.

    Returns:
      {
        "sections": [
          {
            "domain": "body_weight",
            "title": "Body Weight",
            "tables_json": {"Male": [...], "Female": [...]},
            "narrative": ["paragraph1", "paragraph2", ...]
          },
          ...
        ]
      }
    """
    body = await request.json()
    compound_name = body.get("compound_name", "Test Compound")
    dose_unit = body.get("dose_unit", "mg/kg")
    # BMD statistics — array of stat keys, each producing a separate GO table.
    # Accepts both the old single "bmd_stat" and the new "bmd_stats" array.
    bmd_stats_raw = body.get("bmd_stats", None)
    if bmd_stats_raw and isinstance(bmd_stats_raw, list):
        bmd_stats = bmd_stats_raw
    else:
        bmd_stats = [body.get("bmd_stat", "median")]

    # First stat is also used for apical category lookup
    bmd_stat = bmd_stats[0]

    # GO category filter cutoffs — sent from the Settings panel.
    # go_pct:       minimum % of genes in a category that must have BMD values
    # go_min_genes: minimum total genes annotated to the GO category
    # go_min_bmd:   minimum genes with a BMD value in the category
    go_pct = body.get("go_pct", 5)
    go_min_genes = body.get("go_min_genes", 20)
    go_max_genes = body.get("go_max_genes", 500)
    go_min_bmd = body.get("go_min_bmd", 3)

    # Load integrated data -- prefer in-memory, fall back to disk
    integrated = _integrated_pool.get(dtxsid)
    if integrated is None:
        integrated_path = _session_dir(dtxsid) / "integrated.json"
        if integrated_path.exists():
            try:
                integrated = json.loads(integrated_path.read_text(encoding="utf-8"))
                _integrated_pool[dtxsid] = integrated
            except (json.JSONDecodeError, Exception):
                pass

    if not integrated:
        return JSONResponse(
            {"error": "No integrated data found -- run integration first"},
            status_code=400,
        )

    # --- Check processed-results cache ---
    # Computing NTP stats (Java Williams/Dunnett) + pybmds + genomics takes
    # 30-60 seconds.  Cache the full response keyed by a hash of the inputs
    # that affect the output: integrated data identity + processing settings.
    # On page refresh the client re-sends process-integrated with the same
    # settings, so we can return the cached result instantly.
    cache_key_parts = json.dumps({
        "bmd_stats": list(bmd_stats),
        "go_pct": go_pct,
        "go_min_genes": go_min_genes,
        "go_max_genes": go_max_genes,
        "go_min_bmd": go_min_bmd,
        # Include a fingerprint of the integrated data so the cache
        # invalidates if the user re-integrates with different files.
        "n_experiments": len(integrated.get("doseResponseExperiments", [])),
        "experiment_names": sorted(
            e.get("name", "") for e in integrated.get("doseResponseExperiments", [])
        ),
    }, sort_keys=True)
    cache_hash = hashlib.sha256(cache_key_parts.encode()).hexdigest()[:16]
    cache_path = _session_dir(dtxsid) / f"_processed_cache_{cache_hash}.json"

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            logger.info(
                "Returning cached processed results for %s (hash %s)",
                dtxsid, cache_hash,
            )
            return JSONResponse(cached)
        except (json.JSONDecodeError, Exception):
            # Corrupted cache — fall through to recompute
            logger.warning("Corrupted process cache for %s, recomputing", dtxsid)

    try:
        # Restore category lookup from the serialized pipe-separated keys.
        # integrate_pool() stored this as _category_lookup with "prefix|endpoint"
        # string keys; we restore them to (prefix, endpoint) tuple keys that
        # build_table_data() expects.
        #
        # Re-select BMD/BMDL/BMDU values using the requested bmd_stat.
        # build_category_lookup() stores the full stat blocks (bmd_stats,
        # bmdl_stats, bmdu_stats) alongside the pre-selected values, so we
        # can re-pick the statistic without re-running Java.
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
            # Use prefixed names to avoid shadowing the outer bmd_stats list.
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

        loop = asyncio.get_running_loop()

        # Filter out gene expression experiments before running NTP stats.
        # Gene expression .bm2 data has thousands of probes -- running Dunnett's
        # test on each would be extremely slow and isn't meaningful for clinical
        # endpoints.  Genomics is handled separately by export_genomics().
        meta = integrated.get("_meta", {})
        source_files = meta.get("source_files", {})
        ge_source = source_files.get("gene_expression")
        ge_exp_names = set()
        if ge_source:
            # Gene expression experiments have names starting with the organ
            # (e.g., "Liver_PFHxSAm_Male_No0") -- identify them by checking
            # which experiments DON'T match any clinical domain prefix.
            for exp in integrated.get("doseResponseExperiments", []):
                exp_name = exp.get("name", "")
                exp_lower = exp_name.lower().replace("_", "")
                matched = False
                for prefix in _BM2_DOMAIN_MAP:
                    clean = exp_lower.replace("female", "").replace("male", "").strip()
                    if clean.startswith(prefix) or prefix.startswith(clean):
                        matched = True
                        break
                if not matched:
                    ge_exp_names.add(exp_name)

        # Build a filtered copy without gene expression experiments for NTP stats
        if ge_exp_names:
            apical_integrated = {
                **integrated,
                "doseResponseExperiments": [
                    exp for exp in integrated.get("doseResponseExperiments", [])
                    if exp.get("name", "") not in ge_exp_names
                ],
            }
            logger.info(
                "Filtered %d gene expression experiments from NTP stats pipeline",
                len(ge_exp_names),
            )
        else:
            apical_integrated = integrated

        # Run the NTP stats pipeline on clinical endpoint experiments only.
        # This is pure Python (no JVM) and typically takes <1s.
        table_data = await loop.run_in_executor(
            None, build_table_data, apical_integrated, cat_lookup,
        )

        # --- Partition table rows by domain ---
        # build_table_data() returns {"Male": [TableRow, ...], "Female": [...]}.
        # We need to split these into per-domain sections so the UI can create
        # separate section cards for body weight, organ weights, etc.
        #
        # Strategy: look at the experiment names in the integrated data to build
        # a mapping of endpoint_name -> domain, then partition the table rows.

        # Build experiment_name -> domain mapping.
        # Strategy: use _meta.source_files to know which experiment names
        # belong to which domain.  Each source file contributed experiments
        # whose names we can map back.  Also use detect_domain() on the
        # experiment name itself as fallback.
        exp_name_to_domain: dict[str, str] = {}

        # Use the filtered (apical-only) experiments for domain mapping --
        # gene expression experiments were already excluded above.
        for exp in apical_integrated.get("doseResponseExperiments", []):
            exp_name = exp.get("name", "")
            exp_lower = exp_name.lower()

            # Strip sex suffix/prefix for matching.
            # IMPORTANT: strip "female" BEFORE "male" -- "female" contains
            # "male" as a substring, so stripping "male" first leaves "fe".
            stripped = exp_lower.replace("female", "").replace("male", "").replace("_", "").strip()

            domain_for_exp = None
            for prefix, dom in _BM2_DOMAIN_MAP.items():
                if stripped.startswith(prefix) or prefix.startswith(stripped):
                    domain_for_exp = dom
                    break

            # Fallback: try detect_domain() which uses regex patterns.
            # This handles abbreviated names like "clin_chem" that don't
            # match the full BM2 prefix "clinicalchemistry".
            if not domain_for_exp:
                domain_for_exp = detect_domain(exp_name, "bm2", 0)

            # Last resort: check if experiment name overlaps with source domain keys
            if not domain_for_exp:
                for dom in source_files:
                    dom_key = dom.replace("_", "")
                    if dom_key in exp_lower.replace("_", ""):
                        domain_for_exp = dom
                        break

            if domain_for_exp:
                exp_name_to_domain[exp_name] = domain_for_exp

        # Build endpoint -> domain map using the experiment mapping.
        # Each probe/endpoint in an experiment inherits that experiment's domain.
        endpoint_domain_map: dict[str, str] = {}
        for exp in apical_integrated.get("doseResponseExperiments", []):
            exp_name = exp.get("name", "")
            dom = exp_name_to_domain.get(exp_name)
            if dom:
                for pr in exp.get("probeResponses", []):
                    probe_id = pr.get("probe", {}).get("id", "")
                    if probe_id:
                        # Key by (sex, probe_id) to avoid collisions when
                        # the same endpoint name appears in different domains
                        # (unlikely but possible for generic names like "Day")
                        endpoint_domain_map[(exp_name, probe_id)] = dom

        # Partition TableRows by domain, preserving sex grouping.
        # build_table_data() groups by sex and uses probe_name as the label.
        # We need to match back to the (exp_name, probe_id) key.
        #
        # Since build_table_data doesn't preserve the experiment name on
        # TableRow, we build a secondary map: (sex, probe_name) -> domain.
        sex_probe_domain: dict[tuple[str, str], str] = {}
        for (exp_name, probe_id), dom in endpoint_domain_map.items():
            sex = "Female" if "female" in exp_name.lower() else \
                  "Male" if "male" in exp_name.lower() else "Unknown"
            sex_probe_domain[(sex, probe_id)] = dom

        # Structure: {domain: {sex: [TableRow, ...]}}
        domain_tables: dict[str, dict[str, list]] = {}
        for sex, rows in table_data.items():
            for row in rows:
                dom = sex_probe_domain.get((sex, row.label), "unknown")
                domain_tables.setdefault(dom, {}).setdefault(sex, []).append(row)

        # Human-readable domain titles for section headers
        _DOMAIN_TITLES = {
            "body_weight":    "Body Weight",
            "organ_weights":  "Organ Weights",
            "clin_chem":      "Clinical Chemistry",
            "hematology":     "Hematology",
            "hormones":       "Hormones",
            "tissue_conc":    "Tissue Concentration",
            "clinical_obs":   "Clinical Observations",
        }

        # Build sections array: one per domain that has data
        sections = []
        for dom, sex_rows in sorted(domain_tables.items()):
            # Serialize TableRow objects to JSON-friendly dicts
            tables_json = serialize_table_rows(sex_rows)

            # Generate narrative for this domain's data only
            narrative = generate_results_narrative(
                sex_rows, compound_name, dose_unit,
            )

            sections.append({
                "domain": dom,
                "title": _DOMAIN_TITLES.get(dom, dom.replace("_", " ").title()),
                "tables_json": tables_json,
                "narrative": narrative,
            })

        # --- BMDS modeling (pybmds) for apical endpoints ---
        # Run the EPA BMDS continuous models on the same dose-response data
        # to produce a second BMD summary that matches the NIEHS reference
        # report methodology (BMDS 2.7.0 via pybmds).  This gives users
        # both the BMDExpress 3-native results AND the BMDS results.
        from apical_bmds import run_bmds_for_endpoints

        bmds_inputs = []
        for _dom, sex_rows in domain_tables.items():
            for _sex, rows in sex_rows.items():
                for row in rows:
                    if hasattr(row, "_bmds_input") and row._bmds_input:
                        bmds_inputs.append(row._bmds_input)

        # Run BMDS in a thread pool — pybmds model fitting is CPU-bound
        # and takes ~0.5-2s per endpoint (total ~10-30s for a full study).
        bmds_results = {}
        if bmds_inputs:
            bmds_results = await loop.run_in_executor(
                None, run_bmds_for_endpoints, bmds_inputs,
            )

        # --- Gene expression genomics (from integrated .bm2) ---
        # If the integration included gene_expression, extract per-gene BMD
        # and GO BP category results directly from the .bm2 using the
        # BMDExpress 3 Java API.  This replaces the old CSV-based workflow.
        genomics_sections = {}
        meta = integrated.get("_meta", {})
        ge_source = meta.get("source_files", {}).get("gene_expression")
        if ge_source and ge_source.get("tier") == "bm2":
            ge_filename = ge_source.get("filename", "")
            ge_path = str(_session_dir(dtxsid) / "files" / ge_filename)

            if os.path.exists(ge_path):
                # Run the Java export in a thread pool (JVM startup ~0.5s)
                tmp_json = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".json", prefix="genomics_",
                )
                tmp_json.close()

                try:
                    ge_result = await loop.run_in_executor(
                        None, export_genomics, ge_path, tmp_json.name,
                    )

                    # Reshape into the format the UI expects: keyed by organ_sex
                    for exp in ge_result.get("experiments", []):
                        organ = exp.get("organ", "unknown").lower()
                        sex = exp.get("sex", "unknown").lower()
                        key = f"{organ}_{sex}"

                        # Sort genes by BMD ascending (lowest = most sensitive).
                        # Java serializes NaN/Infinity as strings -- coerce to float.
                        def _safe_float(val, default=float("inf")):
                            if val is None:
                                return default
                            try:
                                v = float(val)
                                # NaN sorts inconsistently -- treat as infinity
                                return default if v != v else v
                            except (TypeError, ValueError):
                                return default

                        genes = sorted(
                            exp.get("genes", []),
                            key=lambda g: _safe_float(g.get("bmd")),
                        )

                        # Filter and sort GO terms.
                        # Apply the three user-configured cutoffs:
                        #   1. go_min_genes: category must have at least this many
                        #      genes annotated (n_genes from ExportGenomics)
                        #   2. go_min_bmd:   at least this many genes must have a
                        #      BMD value (n_passed from ExportGenomics)
                        #   3. go_pct:       the ratio n_passed/n_genes must be at
                        #      least this percentage
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

                        # Helper: pick a specific BMD stat from the stat block.
                        # Returns None (not a fallback) if the stat isn't available,
                        # so that categories missing the stat get excluded.
                        def _pick_stat_strict(g, metric, stat):
                            block = g.get(f"{metric}_stats", {})
                            if block:
                                return block.get(stat)
                            # Legacy data only has median
                            if stat == "median":
                                return g.get(f"{metric}_median")
                            return None

                        # Build a separate gene_sets table for each requested
                        # BMD statistic.  Categories where the stat is null
                        # (not computed by BMDExpress) are excluded from that
                        # table entirely rather than falling back to another stat.
                        gene_sets_by_stat = {}
                        for stat in bmd_stats:
                            # Filter to categories that have a non-null value
                            stat_go = [
                                g for g in filtered_go
                                if _pick_stat_strict(g, "bmd", stat) is not None
                            ]
                            # Sort by BMD ascending (most sensitive first)
                            stat_go.sort(
                                key=lambda g: _safe_float(
                                    _pick_stat_strict(g, "bmd", stat),
                                ),
                            )
                            gene_sets_by_stat[stat] = [
                                {
                                    "rank": i + 1,
                                    "go_id": g["go_id"],
                                    "go_term": g["go_term"],
                                    "bmd": _pick_stat_strict(g, "bmd", stat),
                                    "bmdl": _pick_stat_strict(g, "bmdl", stat),
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
                        }
                finally:
                    os.unlink(tmp_json.name)

        # Human-readable labels for BMD statistics, used by the UI
        # to set table column headers (e.g. "BMD 5th Pct").
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
        stat_labels = {
            s: _BMD_STAT_LABELS.get(s, s.replace("_", " ").title())
            for s in bmd_stats
        }

        # --- Build apical BMD summary (Table 8 equivalent) ---
        # Collects BMD, BMDL, LOEL, NOEL, direction from ALL domain
        # TableRows into a flat list for the separate BMD summary card.
        # Matches the NIEHS reference report structure where domain tables
        # (Tables 2-7) show dose-response data and Table 8 summarizes BMDs.
        apical_bmd_summary = []
        for dom, sex_rows in sorted(domain_tables.items()):
            for sex, rows in sex_rows.items():
                for row in rows:
                    # Include the row if it has a BMD result OR significant
                    # trend/pairwise findings (LOEL exists).  Endpoints with
                    # neither are uninteresting for the summary.
                    has_bmd = row.bmd_status is not None
                    has_loel = row.loel is not None
                    if not has_bmd and not has_loel:
                        continue
                    apical_bmd_summary.append({
                        "endpoint": row.label,
                        "sex": sex,
                        "domain": dom,
                        "bmd": row.bmd_str,
                        "bmdl": row.bmdl_str,
                        "bmd_status": row.bmd_status,
                        "loel": row.loel,
                        "noel": row.noel,
                        "direction": row.direction,
                    })

        # --- Build BMDS-based BMD summary (second Table 8) ---
        # Same structure as the BMDExpress 3 summary, but using pybmds
        # results.  Only includes endpoints that pybmds modeled.
        apical_bmd_summary_bmds = []
        if bmds_results:
            for dom, sex_rows in sorted(domain_tables.items()):
                for sex, rows in sex_rows.items():
                    for row in rows:
                        bmds_key = f"{sex}::{row.label}"
                        bmds_res = bmds_results.get(bmds_key)
                        if not bmds_res:
                            continue
                        # Match the NIEHS reference Table 8 inclusion gate:
                        # include only endpoints that have a significant trend
                        # + pairwise finding (LOEL exists) OR a viable BMDS
                        # result.  This filters out the many endpoints where
                        # pybmds produces a UREP/NVM but there's no statistical
                        # significance — those aren't informative for the summary.
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

                        apical_bmd_summary_bmds.append({
                            "endpoint": row.label,
                            "sex": sex,
                            "domain": dom,
                            "bmd": bmd_str,
                            "bmdl": bmdl_str,
                            "bmd_status": status,
                            "model_name": bmds_res.get("model_name"),
                            "loel": row.loel,
                            "noel": row.noel,
                            "direction": row.direction,
                        })

        result_payload = {
            "sections": sections,
            "genomics_sections": genomics_sections,
            "apical_bmd_summary": apical_bmd_summary,
            "apical_bmd_summary_bmds": apical_bmd_summary_bmds,
            "bmd_stats": list(bmd_stats),
            "bmd_stat_labels": stat_labels,
        }

        # Persist the fully-computed result so page refreshes are instant.
        # Also clean up stale caches from previous settings combinations.
        try:
            # Remove old cache files for this session (different settings hash)
            for old in _session_dir(dtxsid).glob("_processed_cache_*.json"):
                if old != cache_path:
                    old.unlink(missing_ok=True)
            cache_path.write_text(
                json.dumps(result_payload, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Cached processed results for %s (hash %s)", dtxsid, cache_hash)
        except Exception:
            logger.warning("Failed to cache processed results for %s", dtxsid, exc_info=True)

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
    tiers and domains.  Persists the result to
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
