"""
web_routes.preview_routes — the materialized, versioned, docx-default preview.

Replaces the pull-based ephemeral srcdoc preview (POST /api/preview-latex-html, kept
for the legacy app) with a persisted ARTIFACT
(project_integrated_wizard_versioned_preview Decision 5): on a report-update event the
client POSTs …/materialize, which renders the report to disk under
`sessions/<dtxsid>/preview/<version>/`; the frame then points at …/view (the
materialized HTML file) and the deliverable downloads from …/download.

docx is the default deliverable surface; the HTML view is always materialized as the
on-screen proxy (docx can't render in an iframe). `sessions/` has no StaticFiles mount,
so files are served via per-session FileResponse — the /api/export-bm2 pattern.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from pipeline.session_store import safe_filename
from rendering.preview_surface import (
    DEFAULT_SURFACE,
    KNOWN_SURFACES,
    materialize_preview,
    preview_file_path,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_MEDIA_TYPES: dict[str, str] = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html",
    "latex": "application/x-tex",
    "jats": "application/xml",
}


def _reject_bad_dtxsid(dtxsid: str) -> JSONResponse | None:
    """Guard against path traversal in the session id (mirrors export_routes)."""
    if safe_filename(dtxsid) != dtxsid:
        return JSONResponse({"error": f"Invalid dtxsid: {dtxsid!r}"}, status_code=400)
    return None


@router.post("/api/preview/{dtxsid}/materialize")
async def api_preview_materialize(dtxsid: str, request: Request):
    """Render + persist the preview artifact set for a session.

    Body (all optional): {surface?: str = "docx", version?: str = "default"}. Writes
    the deliverable surface + the always-emitted HTML view under the session dir,
    archiving the prior set. Returns the manifest {version, ts, deliverable, files}.
    Fired on report-update events (accepted edit, reprocess, restyle).
    """
    if (bad := _reject_bad_dtxsid(dtxsid)) is not None:
        return bad
    try:
        body = await request.json()
    except Exception:
        body = {}
    surface = (body or {}).get("surface") or DEFAULT_SURFACE
    version = (body or {}).get("version")

    if surface not in KNOWN_SURFACES:
        return JSONResponse({"error": f"Unknown surface: {surface!r}"}, status_code=400)

    try:
        manifest = materialize_preview(dtxsid, surface=surface, version=version)
    except NotImplementedError as e:
        return JSONResponse({"error": str(e)}, status_code=501)
    except Exception as e:
        logger.exception("Preview materialization failed for %s", dtxsid)
        return JSONResponse({"error": f"Preview failed: {e}"}, status_code=500)

    return JSONResponse(manifest)


@router.get("/api/preview/{dtxsid}/view")
async def api_preview_view(dtxsid: str, version: str | None = None, surface: str = "html"):
    """Serve a materialized preview file inline for the iframe.

    Defaults to the HTML view (the always-viewable proxy). Returns 404 if the file
    has not been materialized yet.
    """
    if (bad := _reject_bad_dtxsid(dtxsid)) is not None:
        return bad
    path = preview_file_path(dtxsid, surface, version)
    if not path.exists():
        return JSONResponse(
            {"error": "No preview materialized yet — POST …/materialize first"},
            status_code=404,
        )
    media_type = _MEDIA_TYPES.get(surface, "text/html")
    # Inline (not attachment) so the browser renders it in the frame.
    return FileResponse(str(path), media_type=media_type)


@router.get("/api/preview/{dtxsid}/download")
async def api_preview_download(dtxsid: str, version: str | None = None, surface: str = DEFAULT_SURFACE):
    """Download a materialized deliverable (default docx) as an attachment."""
    if (bad := _reject_bad_dtxsid(dtxsid)) is not None:
        return bad
    path = preview_file_path(dtxsid, surface, version)
    if not path.exists():
        return JSONResponse(
            {"error": "No preview materialized yet — POST …/materialize first"},
            status_code=404,
        )
    media_type = _MEDIA_TYPES.get(surface, "application/octet-stream")
    filename = f"{safe_filename(dtxsid)}_{path.name}"
    return FileResponse(
        str(path),
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
