"""
Wizard UI convenience routes (thin transport layer).

The wizard front-end (served at /wizard, source in wizard-ui/) drives the SAME
UI-agnostic workflow core (ADR-0014) as the legacy app and the notebook:
workflow.steps.* + WorkflowEngine over a DiskPoolStore. Every real step
(validate / resolve / confirm-metadata / integrate / approve / process / state /
reset / upload) already has a thin route elsewhere and is reused verbatim.

This module adds only the two read-only helpers the wizard needs that aren't
already a single clean call:

  GET /api/wizard/{dtxsid}/files
      List the raw study files uploaded into sessions/{dtxsid}/files/.
      (There is no existing "list files" route.)

  GET /api/wizard/{dtxsid}/fingerprints
      The detected per-file classification for the confirm-metadata screen
      (filename, file_type, platform, data_type, sexes). This is the notebook's
      Cell 4 review table as JSON. Backed by store.ensure_fingerprints so it is
      correct even on a cold process (re-derives from disk when the in-memory
      fingerprint pool is empty).
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from workflow.store import DiskPoolStore

logger = logging.getLogger(__name__)

router = APIRouter()


def _fp_get(fp, key, default=""):
    """Read a field from a fingerprint that may be a dataclass or a dict.

    Coerces an explicit None (present-but-unset) to the default so the JSON is
    predictable for the client.
    """
    val = getattr(fp, key, default) if hasattr(fp, key) else fp.get(key, default)
    return default if val is None else val


@router.get("/api/wizard/{dtxsid}/files")
async def api_wizard_files(dtxsid: str):
    """List uploaded study files in the session's files/ directory."""
    store = DiskPoolStore()
    files_dir = store.session_dir(dtxsid) / "files"
    files = []
    if files_dir.exists():
        for p in sorted(files_dir.iterdir()):
            if p.is_file():
                files.append({"name": p.name, "size": p.stat().st_size})
    return JSONResponse({"files": files, "count": len(files)})


@router.get("/api/wizard/{dtxsid}/fingerprints")
async def api_wizard_fingerprints(dtxsid: str):
    """Detected per-file classification for the confirm-metadata screen.

    Uses ensure_fingerprints (disk-safe): re-derives from files/ when the
    in-memory pool is cold, so the confirm screen is correct on a fresh process.
    """
    store = DiskPoolStore()
    fps = store.ensure_fingerprints(dtxsid)
    rows = []
    for fid, fp in fps.items():
        rows.append({
            "file_id": fid,
            "filename": _fp_get(fp, "filename", fid),
            "file_type": _fp_get(fp, "file_type", ""),
            "platform": _fp_get(fp, "platform", ""),
            "data_type": _fp_get(fp, "data_type", ""),
            "sexes": _fp_get(fp, "sexes", []) or [],
        })
    rows.sort(key=lambda r: r["filename"])
    return JSONResponse({"fingerprints": rows, "count": len(rows)})
