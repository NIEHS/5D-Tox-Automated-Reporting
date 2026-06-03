"""
Export and style-profile routes for 5dToxReport.

Provides endpoints for exporting the complete NIEHS Report 10-structured
document as an Overleaf-ready LaTeX bundle (.zip with report.tex +
niehs.cls + figures/), plus managing the global writing style profile
that the LLM uses to match user preferences.

The export pipeline runs:

    marshal_export_data(body)            ← report_data.py: data assembly
        → generate_latex(data, …)        ← latex_generator.py: tree walk
        → build_overleaf_bundle(data, …) ← latex_export.py: zip writer

Endpoints:
  GET    /api/style-profile             — Retrieve the global style profile
  DELETE /api/style-profile/{idx}       — Delete a style rule by index
  POST   /api/export-overleaf-bundle    — Download full report as Overleaf .zip
  POST   /api/preview-latex-fragment    — Fetch .tex source for one TOC subtree
  GET    /api/export-bm2/{dtxsid}       — Download enriched .bm2 file
"""

import asyncio
import io
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from session_store import safe_filename
from style_learning import (
    load_style_profile, save_style_profile,
)
from server_state import get_bm2_uploads
from pool_orchestrator import load_integrated

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router — mounted by background_server.py as app.include_router(...)
# ---------------------------------------------------------------------------
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/style-profile — retrieve the global style profile
# ---------------------------------------------------------------------------

@router.get("/api/style-profile")
async def api_style_profile():
    """
    Return the global style profile (learned writing preferences).

    Returns the full profile JSON including version, updated_at, and rules
    array.  If no profile exists yet, returns an empty structure with zero
    rules so the client can always expect the same shape.
    """
    profile = load_style_profile()
    return JSONResponse(profile)


# ---------------------------------------------------------------------------
# DELETE /api/style-profile/{idx} — delete a specific style rule by index
# ---------------------------------------------------------------------------

@router.delete("/api/style-profile/{idx}")
async def api_delete_style_rule(idx: int):
    """
    Delete a style rule at the given index from the global profile.

    The index is 0-based and corresponds to the rule's position in the
    rules array.  After deletion, the profile is rewritten to disk.

    Returns the updated profile so the client can re-render immediately.
    """
    profile = load_style_profile()
    rules = profile.get("rules", [])

    if idx < 0 or idx >= len(rules):
        return JSONResponse(
            {"error": f"Rule index {idx} out of range (0..{len(rules) - 1})"},
            status_code=404,
        )

    removed = rules.pop(idx)
    save_style_profile(profile)
    logger.info("Deleted style rule #%d: %s", idx, removed.get("rule", ""))

    return JSONResponse(profile)


# ---------------------------------------------------------------------------
# Helpers for the LaTeX export and preview endpoints
# ---------------------------------------------------------------------------

def _resolve_bm2_into_body(body: dict) -> None:
    """
    Inline-resolve any apical_sections that reference uploaded .bm2 files.

    The web UI may send bm2_id references instead of inline table_data
    (it does this to keep the request payload small).  The export
    pipeline expects fully-inlined table_data, so we look up the
    cached data from the upload store and splice it in.

    Mutates body in place.
    """
    _bm2_uploads = get_bm2_uploads()
    for sec in body.get("apical_sections", []):
        if "table_data" not in sec or not sec["table_data"]:
            bm2_id = sec.get("bm2_id", "")
            upload = _bm2_uploads.get(bm2_id)
            if upload and upload.get("table_data"):
                sec["table_data"] = upload["table_data"]
        if not sec.get("narrative_paragraphs"):
            bm2_id = sec.get("bm2_id", "")
            upload = _bm2_uploads.get(bm2_id)
            if upload and upload.get("narrative"):
                sec["narrative_paragraphs"] = upload["narrative"]


# ---------------------------------------------------------------------------
# POST /api/export-overleaf-bundle — download the LaTeX Overleaf bundle (zip)
# ---------------------------------------------------------------------------

@router.post("/api/export-overleaf-bundle")
async def api_export_overleaf_bundle(request: Request):
    """
    Export the full report as an Overleaf-ready zip bundle.

    Accepts the same JSON payload the old /api/export-pdf endpoint did.
    Marshals it through the shared report_data data-assembly pipeline,
    then renders to a .tex via the LaTeX generator and packages it
    alongside niehs.cls + figures/ + README.md into a zip the author
    drags into Overleaf.

    Pipeline:
      body → marshal_export_data → generate_latex → build_overleaf_bundle
    """
    from report_data import marshal_export_data
    from latex_export import build_overleaf_bundle

    body = await request.json()
    _resolve_bm2_into_body(body)

    try:
        report_data = marshal_export_data(body)
        # Build the zip in memory.  build_overleaf_bundle writes to a
        # path, so we pipe through a tmpfile-shaped buffer to keep the
        # streaming simple and avoid filesystem chatter on every export.
        import tempfile
        with tempfile.NamedTemporaryFile(
            suffix=".zip", prefix="5dtox_bundle_", delete=False,
        ) as tmp:
            build_overleaf_bundle(report_data, Path(tmp.name))
            zip_bytes = Path(tmp.name).read_bytes()
            Path(tmp.name).unlink(missing_ok=True)
    except Exception as e:
        logging.exception("Overleaf bundle export failed")
        return JSONResponse(
            {"error": f"Overleaf bundle generation failed: {e}"},
            status_code=500,
        )

    chemical_name = body.get("chemical_name", "Chemical")
    safe_name = safe_filename(chemical_name)
    filename = f"5dToxReport_{safe_name}_overleaf.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# POST /api/sync-document/{dtxsid} — refresh the dev document dir from cache
# ---------------------------------------------------------------------------

@router.post("/api/sync-document/{dtxsid}")
async def api_sync_document(dtxsid: str, request: Request):
    """
    Materialize/refresh the dev document directory documents/<dtxsid>/ from the
    session cache (the ADR-0005 git-bridge working tree), on demand.

    Outbound only (v1): regenerates report.tex + niehs.cls + figures/ + README
    from sessions/<dtxsid>/ and rewrites the .rlm-sync.json sidecar.  It does
    NOT yet absorb edits made in Overleaf — that's the ADR-0005 reconciliation
    step (override store + diff attribution).

    Optional JSON body: {chemical_name, casrn} for titles/captions; both fall
    back to the session metadata placeholders when omitted.

    Differs from /api/export-overleaf-bundle on purpose: that endpoint zips the
    LIVE marshaled request body for download; this one syncs the on-disk session
    CACHE into a tracked working directory.
    """
    from latex_export import sync_document, DOCUMENTS_DIR

    # dtxsid becomes a path segment under documents/ — reject anything that
    # isn't a clean filename so it can't escape the documents/ root.
    if safe_filename(dtxsid) != dtxsid:
        return JSONResponse({"error": f"Invalid dtxsid: {dtxsid!r}"}, status_code=400)

    # Body is optional; an empty/absent body just uses metadata defaults.
    try:
        body = await request.json()
    except Exception:
        body = {}
    chemical_name = body.get("chemical_name") or "Test Article"
    casrn = body.get("casrn") or "000-00-0"

    try:
        out_dir = sync_document(dtxsid, chemical_name=chemical_name, casrn=casrn)
    except Exception:
        logging.exception("Dev document sync failed for %s", dtxsid)
        return JSONResponse({"error": "Dev document sync failed"}, status_code=500)

    written = sorted(
        p.relative_to(out_dir).as_posix()
        for p in out_dir.rglob("*") if p.is_file()
    )
    return JSONResponse({
        "dtxsid": dtxsid,
        # Path relative to the repo root (documents/<dtxsid>) for display.
        "document_dir": out_dir.relative_to(DOCUMENTS_DIR.parent).as_posix(),
        "files": written,
    })


# ---------------------------------------------------------------------------
# GET/POST /api/overleaf-binding/{dtxsid} — link a report to its Overleaf project
# ---------------------------------------------------------------------------

@router.get("/api/overleaf-binding/{dtxsid}")
async def api_get_overleaf_binding(dtxsid: str):
    """Return the report's Overleaf binding {project_url?, git_remote?} ({} if unset)."""
    from overleaf_sync import get_binding
    if safe_filename(dtxsid) != dtxsid:
        return JSONResponse({"error": f"Invalid dtxsid: {dtxsid!r}"}, status_code=400)
    return JSONResponse(get_binding(dtxsid))


@router.post("/api/overleaf-binding/{dtxsid}")
async def api_set_overleaf_binding(dtxsid: str, request: Request):
    """
    Set the report's Overleaf binding.  Body: {project_url?, git_remote?} — only
    the provided fields are updated.  The project_url drives the "Open in
    Overleaf" link; git_remote is the push/pull target.
    """
    from overleaf_sync import set_binding
    if safe_filename(dtxsid) != dtxsid:
        return JSONResponse({"error": f"Invalid dtxsid: {dtxsid!r}"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    binding = set_binding(
        dtxsid,
        project_url=body.get("project_url"),
        git_remote=body.get("git_remote"),
    )
    return JSONResponse(binding)


# ---------------------------------------------------------------------------
# POST /api/preview-latex-html — render a section subtree to HTML
# ---------------------------------------------------------------------------

@router.post("/api/preview-latex-html")
async def api_preview_latex_html(request: Request):
    """
    Render a slice of the report to HTML for the in-app preview iframes.

    Accepts the same payload as /api/export-overleaf-bundle plus an
    optional "section_filter" field naming a DocNode id.  When set, only
    that subtree renders (the fragment-compile path); when omitted, the
    full report renders.

    Pipeline:
      body → marshal_export_data → generate_html(section_filter=…) → HTML

    Both the LaTeX export and this HTML preview walk the same
    DOCUMENT_TREE with the same data dict, dispatching on the same
    node_type set — they're semantically equivalent renderings of the
    same canonical structure.  A bug in apical-table rendering manifests
    in both outputs (so fixing once fixes both); the only difference is
    the output format each handler emits.

    The HTML is self-contained (inline CSS) and delivered with
    text/html so the browser can drop it straight into an iframe via
    srcdoc.
    """
    from report_data import marshal_export_data
    from html_generator import generate_html

    body = await request.json()
    _resolve_bm2_into_body(body)
    section_filter = body.get("section_filter")

    if section_filter:
        # Debug log to help diagnose "preview is empty" reports against
        # specific TOC nodes.  Tracks the same fields the old PDF path
        # used to log so existing dashboards / grep recipes keep working.
        asecs = body.get("apical_sections", [])
        logger.info(
            "preview-html section_filter=%s, apical_sections=%d, "
            "platforms=%s",
            section_filter, len(asecs),
            [s.get("platform", "?") for s in asecs],
        )

    try:
        report_data = marshal_export_data(body, section_filter=section_filter)
        html = generate_html(report_data, section_filter=section_filter)
    except Exception as e:
        logging.exception("HTML preview generation failed")
        return JSONResponse(
            {"error": f"HTML preview generation failed: {e}"},
            status_code=500,
        )

    return Response(content=html, media_type="text/html")


# ---------------------------------------------------------------------------
# GET /api/export-bm2/{dtxsid} — download enriched .bm2 file
# ---------------------------------------------------------------------------

@router.get("/api/export-bm2/{dtxsid}")
async def api_export_bm2(dtxsid: str):
    """
    Download the metadata-enriched .bm2 file for a session.

    Reads the session's integrated.json (which contains LLM-inferred and
    user-approved ExperimentDescription metadata) and converts it to the
    canonical .bm2 format (Java ObjectOutputStream) via JsonToBm2.

    The resulting file is a standard BMDExpress 3 project file — opening
    it in BMDExpress 3 shows experiments with metadata pre-filled (species,
    sex, organ, test article, study duration, etc.).

    If an integrated.bm2 already exists and is newer than integrated.json,
    it's served directly without re-export.

    Returns the .bm2 file as a download attachment.
    """
    from session_store import session_dir
    from bmdx_pipe import export_integrated_bm2

    sess_path = session_dir(dtxsid)
    json_path = sess_path / "integrated.json"
    bm2_path = sess_path / "integrated.bm2"

    # Run the schema-validating loader before continuing (ADR-0001).
    # The result is discarded — bmdx_pipe re-reads integrated.json
    # from disk internally — but the call still gates this endpoint
    # against malformed integrated data.  Returns None when no data
    # exists (which also implies the file is missing); raises
    # BMDProjectValidationError on a schema failure (handled globally
    # in background_server.py → 422).
    if load_integrated(dtxsid) is None:
        return JSONResponse(
            {"error": "No integrated data found — run integration first"},
            status_code=404,
        )

    # Re-export if .bm2 is missing or older than the JSON source.
    # This handles the case where the user edits metadata (re-runs
    # integration) and then downloads — always gets the latest.
    needs_export = (
        not bm2_path.exists()
        or bm2_path.stat().st_mtime < json_path.stat().st_mtime
    )
    if needs_export:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                export_integrated_bm2,
                str(json_path),
                str(bm2_path),
            )
        except Exception as e:
            logger.exception("Failed to export enriched .bm2 for %s", dtxsid)
            return JSONResponse(
                {"error": f"Export failed: {e}"},
                status_code=500,
            )

    # Derive a human-readable filename from the session identity
    identity_path = sess_path / "identity.json"
    filename = f"{dtxsid}_integrated.bm2"
    if identity_path.exists():
        try:
            import json
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            chem_name = identity.get("preferredName", "")
            if chem_name:
                safe_name = safe_filename(chem_name)
                filename = f"{safe_name}_integrated.bm2"
        except Exception:
            pass

    return FileResponse(
        str(bm2_path),
        filename=filename,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
