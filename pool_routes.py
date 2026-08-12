"""
File-pool lifecycle route handlers.

Four POST endpoints + one private helper that together drive the
upload → validate → confirm-metadata → integrate flow that the UI
moves through before the (expensive) processing step:

  POST /api/pool/validate/{dtxsid}
      Re-fingerprints every file in sessions/{dtxsid}/files/ and runs
      full cross-validation (coverage matrix, dose consistency, animal
      counts, sex coverage, redundancy detection).  Persists the
      ValidationReport to validation_report.json.

  POST /api/pool/resolve
      Persists a single user decision when validation surfaces a
      conflict (e.g. dose-group mismatch).  Append-only — each call
      adds one entry to precedence.json so the integration step can
      apply user choices later.

  POST /api/pool/confirm-metadata/{dtxsid}
      Accepts the user's reviewed platform/data-type assignments,
      updates the in-memory fingerprints, and (for txt/csv files)
      writes # Provider / # Platform / # Data Type header lines into
      the file in place so Java's ExperimentDescriptionParser picks
      them up at integration.  .bm2 files use a metadata sidecar
      instead (binary format can't carry headers).

  POST /api/pool/integrate/{dtxsid}
      The merge step.  Reads fingerprints + coverage matrix +
      precedence decisions, hands off to bmdx-pipe's integrate_pool
      (run in a thread pool — xlsx parsing via openpyxl is blocking
      I/O), caches the result in-memory and on disk, and clears all
      per-section caches that would be stale against the new data.
      Returns a lightweight summary (not the full integrated JSON —
      it can exceed Cloud Run's 32 MiB response cap).

The private _write_metadata_headers helper lives here because it's
called only by api_pool_confirm_metadata.

All four handlers register on pool_globals.router (the same APIRouter
that's exposed as pool_orchestrator.router and mounted by
background_server.py), so no routing change is required to land this
split.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import orjson
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from bmdx_pipe import integrate_pool, validate_pool
from styling_export.llm_helpers import llm_generate_json as _llm_generate_json

from pool_globals import (
    router,
    _session_dir,
    _pool_fingerprints,
    _integrated_pool,
    get_pool_fingerprints,
)
from pool_fingerprints import ensure_fingerprints
from integrated_io import _enrich_source_experiment_counts


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation route
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Conflict-resolution route
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Metadata-confirmation route
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Integration route
# ---------------------------------------------------------------------------

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
                llm_generate_json=_llm_generate_json,
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
