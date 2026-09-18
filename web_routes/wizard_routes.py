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

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from web_routes.dtxsid_param import Dtxsid

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
async def api_wizard_files(dtxsid: Dtxsid):
    """List uploaded study files in the session's files/ directory."""
    store = DiskPoolStore()
    files_dir = store.session_dir(dtxsid) / "files"
    files = []
    if files_dir.exists():
        for p in sorted(files_dir.iterdir()):
            if p.is_file():
                files.append({"name": p.name, "size": p.stat().st_size})
    return JSONResponse({"files": files, "count": len(files)})


@router.get("/api/wizard/{dtxsid}/processed")
async def api_wizard_processed(dtxsid: Dtxsid):
    """Whether this session has already been processed (its compute caches exist).

    The wizard uses this to decide if it can REHYDRATE the Results payload from
    the cache on load (a ~2s cache-hit re-call of process-integrated) rather than
    forcing the user to re-run the multi-minute processing after a page refresh.
    Gated on the NTP cache — the first process stage — so we never auto-trigger a
    real recompute on an unprocessed (or re-integrated, cache-wiped) session.
    """
    store = DiskPoolStore()
    session_dir = store.session_dir(dtxsid)
    processed = bool(list(session_dir.glob("_cache_ntp_*.json"))) if session_dir.exists() else False
    return JSONResponse({"processed": processed})


@router.get("/api/wizard/{dtxsid}/identity")
async def api_wizard_identity(dtxsid: Dtxsid):
    """The compound's cross-identifiers from identity.json (name, CASRN, DTXSID,
    PubChem CID, EC number, IUPAC name — whichever are present).

    A cheap read for the identifiers box shown on the session picker and the
    Integrate & Approve step. Returns {} when the session has no identity file.
    """
    store = DiskPoolStore()
    identity = store.read_json(dtxsid, "identity.json")
    if not isinstance(identity, dict):
        identity = {}
    return JSONResponse({"identity": identity})


@router.get("/api/document/{dtxsid}/front-matter")
async def api_get_front_matter(dtxsid: Dtxsid):
    """Read the session's human-set front-matter (authors, contributors, publication
    overrides) for the Configure surface. Returns {} when none is saved yet.

    Shape: {authors:[{name,affiliation,role}], contributors:[{name,role}],
    publication:{report_number,doi,report_date}}.
    """
    store = DiskPoolStore()
    fm = store.read_json(dtxsid, "front_matter.json")
    if not isinstance(fm, dict):
        fm = {}
    return JSONResponse({"front_matter": fm})


@router.post("/api/document/{dtxsid}/front-matter")
async def api_save_front_matter(dtxsid: Dtxsid, request: Request):
    """Persist the session's front-matter. Validates the top-level shape (authors /
    contributors lists, publication object), drops junk, writes front_matter.json.
    The About This Report + Publication Details sections fill from this on next
    render."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    fm = body.get("front_matter") if isinstance(body, dict) else None
    if not isinstance(fm, dict):
        return JSONResponse({"error": "front_matter object required"}, status_code=400)

    def _people(rows, keys):
        out = []
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict):
                out.append({k: str(r.get(k, "")).strip() for k in keys})
        return out

    clean = {
        "authors": _people(fm.get("authors"), ("name", "affiliation", "role")),
        "contributors": _people(fm.get("contributors"), ("name", "role")),
        "publication": {
            k: str(v).strip()
            for k, v in (fm.get("publication") or {}).items()
            if k in ("report_number", "doi", "report_date") and str(v).strip()
        },
    }
    DiskPoolStore().write_json(dtxsid, "front_matter.json", clean)
    return JSONResponse({"ok": True, "front_matter": clean})


@router.get("/api/wizard/{dtxsid}/fingerprints")
async def api_wizard_fingerprints(dtxsid: Dtxsid):
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
