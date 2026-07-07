"""
FastAPI application shell for 5dToxReport.

This file is the entry point and wiring layer — it creates the FastAPI app,
applies the user-gate middleware, mounts all endpoint routers, and serves
the web UI.  All actual endpoint logic lives in dedicated router modules:

  pool_orchestrator.py  — file pool lifecycle (/api/pool/*, /api/integrated/*, etc.)
  session_routes.py     — session load, approve, unapprove, history, restore, BMD summary
  upload_routes.py      — upload-bm2, upload-csv, upload-zip, process-bm2, process-genomics, preview
  llm_routes.py         — generate (SSE), generate-methods, methods-context, generate-summary, generate-genomics-narrative
  export_routes.py      — export-overleaf-bundle, preview-latex-html, sync/commit/push/pull-document, export-bm2, style-profile

Shared mutable state (upload dicts, pool fingerprints) lives in server_state.py.
Pure-function modules: session_store.py, llm_helpers.py, style_learning.py.

Usage:
    python background_server.py                   # start on port 9000
    python background_server.py --port 8080       # custom port
    python background_server.py --host 0.0.0.0    # listen on all interfaces
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.staticfiles import StaticFiles

from chem_resolver import resolve_chemical
from session_store import SESSIONS_DIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="5dToxReport",
    description=(
        "Generate toxicology reports for 5-day genomic dose-response studies. "
        "Includes background sections and NTP-style apical endpoint tables."
    ),
    version="2.0.0",
)


# ---------------------------------------------------------------------------
# Schema-validation error handler — ADR-0001 (BMDProject load barrier).
#
# Any endpoint that calls `load_integrated()` may raise
# `BMDProjectValidationError` when the integrated.json on disk fails
# schema validation.  Without this handler that exception would bubble
# up as a 500 Internal Server Error; with it, we return a structured
# 422 (Unprocessable Entity) so the UI can surface a useful message
# instead of a generic crash.
#
# 422 is the right status because the *content* of integrated.json is
# what's wrong — the request itself was well-formed and authenticated.
# It signals "I understood the request, but the underlying data is
# semantically invalid for this operation."
# ---------------------------------------------------------------------------

from bmd_project_schema import BMDProjectValidationError


@app.exception_handler(BMDProjectValidationError)
async def bmdproject_validation_error_handler(
    request: Request, exc: BMDProjectValidationError,
):
    """
    Translate a load-barrier validation failure to a 422 with structured
    detail.  The session id (carried on `exc.source`) and the first
    Pydantic error are included so the UI can show the user something
    more useful than "server error."
    """
    # Pull the first per-field error out of the wrapped pydantic.ValidationError
    # for a tight summary.  Full structured details are also available
    # if the UI ever wants them.
    errors = exc.pydantic_error.errors()
    first = errors[0] if errors else {}
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Integrated dataset failed schema validation.",
            "source": exc.source,
            "first_error": {
                "loc": ".".join(str(x) for x in first.get("loc", ())),
                "msg": first.get("msg", ""),
                "type": first.get("type", ""),
            },
            "error_count": len(errors),
        },
    )


# ---------------------------------------------------------------------------
# User gate — lightweight access control via ?user= query parameter.
#
# If ALLOWED_USERS is set (comma-separated list), every /api/ request must
# include ?user=<name> matching one of the allowed values.  Static assets
# (HTML, CSS, JS) are served without the check — the app shell loads but
# all API calls fail with 403 if the user is invalid.
#
# This is security-through-obscurity, not real auth.  Good enough to keep
# random visitors out of a Cloud Run deployment without adding login flows.
#
# If ALLOWED_USERS is unset or empty, the gate is disabled (open mode for
# local dev).
# ---------------------------------------------------------------------------

_ALLOWED_USERS_RAW = os.environ.get("ALLOWED_USERS", "")
ALLOWED_USERS: set[str] = {
    u.strip().lower() for u in _ALLOWED_USERS_RAW.split(",") if u.strip()
}

if ALLOWED_USERS:
    logger.info("User gate enabled — %d allowed user(s)", len(ALLOWED_USERS))
else:
    logger.info("User gate disabled (ALLOWED_USERS not set) — open mode")


@app.middleware("http")
async def user_gate_middleware(request: Request, call_next):
    """
    Check ?user= on every /api/ request against the allowed users list.

    Skips the check for:
      - Non-API routes (static assets, the root HTML page)
      - Open mode (ALLOWED_USERS is empty)
    """
    path = request.url.path

    # Only gate /api/ endpoints — let static assets through
    if ALLOWED_USERS and path.startswith("/api/"):
        user = request.query_params.get("user", "").strip().lower()
        if not user:
            return JSONResponse(
                status_code=403,
                content={"detail": "Missing ?user= parameter."},
            )
        if user not in ALLOWED_USERS:
            return JSONResponse(
                status_code=403,
                content={"detail": f"User '{user}' is not authorized."},
            )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Router mounts — each module defines an APIRouter with its endpoints
# ---------------------------------------------------------------------------

# File pool lifecycle: /api/pool/*, /api/integrated/*, /api/process-integrated/*,
# /api/generate-animal-report/*
import pool_orchestrator
app.include_router(pool_orchestrator.router)

# Session persistence: load, approve, unapprove, history, restore, BMD summary
import session_routes
app.include_router(session_routes.router)

# Upload and processing: upload-bm2, upload-csv, upload-zip, process-bm2,
# process-genomics, preview
import upload_routes
app.include_router(upload_routes.router)

# LLM generation: generate (SSE), generate-methods, methods-context,
# generate-summary, generate-genomics-narrative
import llm_routes
app.include_router(llm_routes.router)

# Export and style: export-overleaf-bundle, preview-latex-html,
# sync/commit/push/pull-document, export-bm2, style-profile GET/DELETE
import export_routes
app.include_router(export_routes.router)

# Genomics visualization: clustering endpoint and server-side chart rendering
import genomics_viz
app.include_router(genomics_viz.router)


# ---------------------------------------------------------------------------
# GET / — serve the web UI
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """
    Serve the main web UI (web/index.html).

    The HTML file contains the full single-page application with chemical
    ID form, .bm2 upload area, output panels, and copy/export buttons.

    The document tree JSON is injected as a global variable so it's
    available synchronously before Alpine processes the DOM.  This
    avoids the async fetch + Alpine.initTree race condition where
    dynamically added elements with Alpine directives don't get
    processed by Alpine's initial DOM walk.
    """
    import json

    html_path = Path(__file__).parent / "web" / "index.html"
    if not html_path.exists():
        return HTMLResponse(
            "<h1>Error</h1><p>web/index.html not found</p>",
            status_code=404,
        )
    html = html_path.read_text(encoding="utf-8")

    # Inject the document tree as a global variable before any other
    # scripts run.  The tree is static (computed at module load), so
    # this adds no per-request cost beyond string interpolation.
    # Placed right before </head> so it's available when state.js and
    # layout.js execute.
    # Inject the document tree plus the chart styling config and chart-type
    # registry as globals before any other scripts run.  All three are static
    # (computed at module load), so this adds no per-request cost beyond string
    # interpolation.  The JS chart surfaces read __CHART_STYLE__/__CHART_REGISTRY__
    # to resolve the IDENTICAL effective style the Python export path uses (so the
    # interactive browser view and the PDF can't drift); when absent (stale page)
    # the JS falls back to its literals.
    tree_json = json.dumps(_SERIALIZED_TREE)
    chart_style_json = json.dumps(_CHART_STYLE_CFG)
    chart_registry_json = json.dumps(_CHART_REGISTRY_PAYLOAD)
    tree_script = (
        f'<script>window.__DOCUMENT_TREE__ = {tree_json};'
        f'window.__CHART_STYLE__ = {chart_style_json};'
        f'window.__CHART_REGISTRY__ = {chart_registry_json};</script>\n'
    )
    html = html.replace('</head>', tree_script + '</head>')

    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# GET /api/document-tree — serialized document structure tree
# ---------------------------------------------------------------------------
# Returns the NIEHS report document structure as JSON so the frontend
# can derive the navigation panel, platform maps, and Results containers
# from the single source of truth (document_tree.py) instead of
# hardcoding them in HTML/JS.

from document_tree import serialize_tree, compute_table_numbers, DOCUMENT_TREE
from render_capabilities import annotate_capabilities

# Ensure table numbers are computed before serializing
compute_table_numbers()
# Annotate each node with its rendering capabilities (orientable / breakable
# / editable) from the single-source-of-truth dictionary, so the frontend
# reads capabilities straight off the served tree instead of duplicating the
# type→capability mapping in JavaScript.
_SERIALIZED_TREE = annotate_capabilities(serialize_tree())

# Chart styling + chart-type registry, loaded once from the SAME active template
# as the document tree (contract C8).  __CHART_STYLE__ is the raw chart_style
# block; __CHART_REGISTRY__ is one entry per chart type ({name, type, spec?}).
# Both are injected into the served HTML so the JS chart surfaces resolve the
# same effective style the Python export path uses.
from document_tree import ACTIVE_TEMPLATE
from document_template import load_chart_style, load_chart_types
from chart_registry import registry_payload

_CHART_STYLE_CFG = load_chart_style(ACTIVE_TEMPLATE)
_CHART_REGISTRY_PAYLOAD = registry_payload(load_chart_types(ACTIVE_TEMPLATE))


@app.get("/api/document-tree")
async def get_document_tree(dtxsid: str | None = None):
    """
    Return the document structure tree as JSON.

    The tree includes node IDs, titles, levels, types, platform mappings,
    narrative keys, table numbers, and ready_key flags — everything the
    frontend needs to generate the navigation panel, Results containers, and
    platform routing without any hardcoded document structure.

    With no ``dtxsid`` this returns the frozen global default (_SERIALIZED_TREE,
    computed once at import).  With ``?dtxsid=…`` and a per-session structure
    override present (ADR-0007 follow-on), it serializes that session's own tree
    instead — so after editing the document config the client can re-fetch the
    new structure without a restart.  No override ⇒ the global default.
    """
    if dtxsid:
        try:
            from document_config import build_session_tree
            session_tree = build_session_tree(dtxsid)
            if session_tree is not None:
                return JSONResponse(
                    annotate_capabilities(serialize_tree(session_tree))
                )
        except Exception:
            logging.exception(
                "per-session document tree failed to build for %s; serving "
                "the global default", dtxsid,
            )
    return JSONResponse(_SERIALIZED_TREE)


# ---------------------------------------------------------------------------
# POST /api/resolve — chemical identity resolution
# ---------------------------------------------------------------------------

@app.post("/api/resolve")
async def api_resolve(request: Request):
    """
    Resolve a chemical identifier to all known identifiers.

    Input JSON:
      {"identifier": "95-50-1", "id_type": "auto"}

    Returns the full ChemicalIdentity as JSON, with all resolved fields
    (name, CASRN, DTXSID, CID, EC number, formula, etc.).
    """
    body = await request.json()
    identifier = body.get("identifier", "").strip()
    id_type = body.get("id_type", "auto")

    if not identifier:
        return JSONResponse(
            {"error": "No identifier provided"},
            status_code=400,
        )

    # Run resolution in a thread pool to avoid blocking the event loop
    # (it makes multiple HTTP requests to PubChem and CTX)
    loop = asyncio.get_running_loop()
    identity = await loop.run_in_executor(
        None, resolve_chemical, identifier, id_type, "",
    )

    return JSONResponse(identity.to_dict())


# ---------------------------------------------------------------------------
# Admin: session state export for sync workflow
# ---------------------------------------------------------------------------
# Used by sync.sh pull to download session data from the running Cloud Run
# instance back to the local machine.  Returns a .tar.gz of the sessions/
# directory (excluding _bm2_cache which is an ephemeral LMDB cache that
# rebuilds on demand and uses mmap — not suitable for transfer).

@app.get("/api/admin/sessions/export")
async def export_sessions_tar():
    """
    Stream the sessions/ directory as a .tar.gz download.

    Excludes _bm2_cache/ (LMDB — ephemeral, rebuilds on demand) and any
    __pycache__ directories.  The tarball preserves the directory structure
    so sync.sh can untar it directly into the project root.

    Returns:
        StreamingResponse with application/gzip content type.
    """
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if SESSIONS_DIR.exists():
            for item in SESSIONS_DIR.rglob("*"):
                # Skip the LMDB cache (mmap-based, not portable) and __pycache__
                rel = item.relative_to(SESSIONS_DIR)
                if "_bm2_cache" in rel.parts or "__pycache__" in rel.parts:
                    continue
                # Archive with the sessions/ prefix so untar restores correctly
                tar.add(str(item), arcname=f"sessions/{rel}")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/gzip",
        headers={"Content-Disposition": "attachment; filename=sessions.tar.gz"},
    )


@app.get("/api/admin/sessions/summary")
async def sessions_summary():
    """
    Return a quick summary of what's in the sessions/ directory.

    Lists each DTXSID session with its section count and last-modified time.
    Useful for verifying that a sync push/pull moved the expected data.
    """
    summary = []
    try:
        if SESSIONS_DIR.exists():
            for d in sorted(SESSIONS_DIR.iterdir()):
                # Skip non-directories and internal dirs (underscore-prefixed)
                if not d.is_dir() or d.name.startswith("_"):
                    continue
                section_files = list(d.glob("*.json"))
                # Exclude meta.json from the section count
                sections = [f.stem for f in section_files if f.stem != "meta"]
                summary.append({
                    "dtxsid": d.name,
                    "sections": len(sections),
                    "section_keys": sections,
                })
    except OSError:
        # GCS FUSE mount may not be ready or bucket may be empty —
        # treat as empty sessions dir rather than crashing the login probe.
        pass
    return {"sessions": summary, "count": len(summary)}


# ---------------------------------------------------------------------------
# Dev no-cache middleware — prevent stale JS/CSS during development.
# Forces the browser to re-fetch scripts on every load so you never
# have to manually bump ?v= query strings or hard-refresh.
# ---------------------------------------------------------------------------
@app.middleware("http")
async def no_cache_dev_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.endswith((".js", ".css")):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Static file serving — CSS, JS, and other assets under web/
# ---------------------------------------------------------------------------
# Mounted AFTER all explicit @app routes so that named endpoints (like GET /)
# take priority.  The StaticFiles handler is a catch-all that serves anything
# inside the web/ directory (style.css, js/state.js, js/utils.js, js/main.js,
# images, etc.) with correct MIME types and caching headers.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "web"), name="static")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    host = "127.0.0.1"
    port = 9000

    # Parse CLI args
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        else:
            i += 1

    import webbrowser

    print(f"Starting 5dToxReport on http://{host}:{port}")

    # Open the browser after a short delay so the server is ready
    import threading
    threading.Timer(1.0, webbrowser.open, args=[f"http://{host}:{port}"]).start()

    uvicorn.run(app, host=host, port=port)
