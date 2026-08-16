"""
File-pool lifecycle route handlers (thin transport layer).

Four POST endpoints that together drive the upload → validate →
confirm-metadata → integrate flow that the UI moves through before the
(expensive) processing step:

  POST /api/pool/validate/{dtxsid}
      Re-fingerprints every file and runs full cross-validation (coverage
      matrix, dose consistency, animal counts, sex coverage, redundancy).
      Persists the ValidationReport to validation_report.json.

  POST /api/pool/resolve
      Persists a single user decision when validation surfaces a conflict
      (append-only to precedence.json).

  POST /api/pool/confirm-metadata/{dtxsid}
      Accepts reviewed platform/data-type assignments, updates the in-memory
      fingerprints, and (for txt/csv) writes header lines into the file so
      Java's ExperimentDescriptionParser picks them up at integration.

  POST /api/pool/integrate/{dtxsid}
      The merge step. Hands off to bmdx-pipe's integrate_pool, caches the
      result, and returns a lightweight summary (not the full integrated JSON —
      it can exceed Cloud Run's 32 MiB response cap).

ADR-0014 (step 2): these handlers are now a THIN transport layer. All logic
lives in `workflow/steps.py` as HTTP-free, store-driven functions that a TUI or
test can call identically. Each handler here does: construct a DiskPoolStore,
parse the request, call the step (blocking steps run in an executor to keep the
event loop free), translate StepError → status code, serialize the result.

`_write_metadata_headers` moved to workflow.steps with its only caller; it is
re-exported here because pool_orchestrator's compatibility shim imports it by
name from this module.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import asyncio
import logging

import orjson
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from pipeline.pool_globals import router
from workflow.errors import StepError
from workflow.store import DiskPoolStore
from workflow.steps import (
    confirm_metadata_step,
    integrate_step,
    resolve_step,
    validate_step,
)

# Re-exported for pool_orchestrator's back-compat shim (imports it by name here).
from workflow.steps import _write_metadata_headers  # noqa: F401


logger = logging.getLogger(__name__)


def _step_error_response(exc: StepError) -> JSONResponse:
    """Translate an HTTP-free StepError into the JSON error response the UI
    expects (same {'error': msg} shape + status the pre-unwrap handlers used)."""
    return JSONResponse({"error": exc.message}, status_code=exc.status_code)


# ---------------------------------------------------------------------------
# Validation route
# ---------------------------------------------------------------------------

@router.post("/api/pool/validate/{dtxsid}")
async def api_pool_validate(dtxsid: str):
    """Run full cross-validation on a session's file pool."""
    try:
        report_dict = validate_step(dtxsid, DiskPoolStore())
    except StepError as e:
        return _step_error_response(e)
    return Response(content=orjson.dumps(report_dict), media_type="application/json")


# ---------------------------------------------------------------------------
# Conflict-resolution route
# ---------------------------------------------------------------------------

@router.post("/api/pool/resolve")
async def api_pool_resolve(request: Request):
    """Record a user's precedence decision for a specific validation conflict."""
    body = await request.json()
    try:
        result = resolve_step(
            body.get("dtxsid", ""),
            body.get("issue_index"),
            body.get("chosen_file_id", ""),
            DiskPoolStore(),
        )
    except StepError as e:
        return _step_error_response(e)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Metadata-confirmation route
# ---------------------------------------------------------------------------

@router.post("/api/pool/confirm-metadata/{dtxsid}")
async def api_pool_confirm_metadata(dtxsid: str, request: Request):
    """Confirm file metadata and write headers into txt/csv file copies."""
    body = await request.json()
    try:
        result = confirm_metadata_step(dtxsid, body.get("metadata", {}), DiskPoolStore())
    except StepError as e:
        return _step_error_response(e)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Integration route
# ---------------------------------------------------------------------------

@router.post("/api/pool/integrate/{dtxsid}")
async def api_pool_integrate(dtxsid: str, request: Request):
    """Merge all pool files into a unified BMDProject JSON.

    integrate_step is CPU/IO-heavy (xlsx parsing via openpyxl is blocking), so it
    runs in a thread pool to keep the event loop responsive.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    identity = body.get("identity")

    store = DiskPoolStore()
    loop = asyncio.get_running_loop()
    try:
        summary = await loop.run_in_executor(
            None, lambda: integrate_step(dtxsid, identity, store)
        )
    except StepError as e:
        return _step_error_response(e)
    return JSONResponse(summary)
