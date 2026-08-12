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
  POST   /api/compile-pdf               — Compile report to a preview PDF (tect)
  POST   /api/preview-latex-html        — Render a TOC subtree to preview HTML
  GET    /api/export-bm2/{dtxsid}       — Download enriched .bm2 file
"""

import asyncio
import io
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from session_store import safe_filename
from narrative.style_learning import (
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


def _session_tree_for(body: dict):
    """
    Resolve the per-session document tree for a request body, or None.

    Reads dtxsid from the body and returns that session's structure override
    (document_config.build_session_tree) when one exists, else None so the
    render path falls back to the global DOCUMENT_TREE.  A malformed stored
    override is logged and treated as absent, so a bad file can never 500 a
    render (the save route validates before writing, so this is defensive).
    """
    dtxsid = (body or {}).get("dtxsid", "")
    if not dtxsid:
        return None
    try:
        from document_config import build_session_tree
        return build_session_tree(dtxsid)
    except Exception:
        logger.exception("per-session document tree failed to build for %s; "
                          "falling back to the global structure", dtxsid)
        return None


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
    session_tree = _session_tree_for(body)

    from render_common import PendingContentError

    try:
        report_data = marshal_export_data(body, tree=session_tree)
        # Build the zip in memory.  build_overleaf_bundle writes to a
        # path, so we pipe through a tmpfile-shaped buffer to keep the
        # streaming simple and avoid filesystem chatter on every export.
        # strict=True: this endpoint produces a DOWNLOADABLE deliverable, so
        # gate on unresolved "[... pending]" markers (issue #3) rather than
        # hand the user a report with visible gaps.
        import tempfile
        with tempfile.NamedTemporaryFile(
            suffix=".zip", prefix="5dtox_bundle_", delete=False,
        ) as tmp:
            build_overleaf_bundle(report_data, Path(tmp.name), strict=True, tree=session_tree)
            zip_bytes = Path(tmp.name).read_bytes()
            Path(tmp.name).unlink(missing_ok=True)
    except PendingContentError as e:
        # A gated build wrote nothing; tell the caller exactly which sections
        # are unresolved so the UI can surface them.  422 (not 500): the
        # request is well-formed, the report just isn't ready to ship.
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except NameError:
            pass
        return JSONResponse(
            {
                "error": "Report has unresolved placeholder sections and "
                         "cannot be exported as a deliverable.",
                "pending": e.markers,
            },
            status_code=422,
        )
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
# POST /api/compile-pdf — compile the LaTeX bundle locally to a preview PDF
# ---------------------------------------------------------------------------
# The engine command is indirected so a deployment can point at its own
# offline wrapper.  Default `tect` = the seeded-bundle tectonic wrapper
# (/usr/local/bin/tect); NEVER plain `tectonic` (its package CDN is
# firewalled).  See ADR-0007 and the tect-offline-compile tooling note.
TECT_CMD = os.environ.get("TECT_CMD", "tect")
_COMPILE_TIMEOUT_S = int(os.environ.get("COMPILE_PDF_TIMEOUT", "120"))


@router.post("/api/compile-pdf")
async def api_compile_pdf(request: Request):
    """
    Compile the current report to a PDF locally, for the in-app live preview.

    This is the DRAFT-preview sibling of /api/export-overleaf-bundle: it
    assembles the identical LaTeX bundle (main.tex + report.tex + niehs.cls
    + figures/) but, instead of zipping it for Overleaf, materializes it in
    a temp dir and runs the local offline TeX engine (`tect`) to produce a
    byte-accurate PDF of the deliverable — so the author sees real LaTeX
    pagination / float placement / overflow WITHOUT an Overleaf round trip
    (ADR-0007).

    Pipeline:
      body → marshal_export_data → _assemble_bundle_files → tmpdir
           → tect main.tex → main.pdf

    strict=False (unlike the bundle export): this is a working draft, so
    pending markers should be VISIBLE in the compiled PDF, not gate it.

    Returns application/pdf on success; 422 with the tail of the compile log
    on a non-zero engine exit (so the UI can show what broke); 503 if the
    engine binary is not installed on this host.
    """
    import shutil as _shutil
    import subprocess
    import tempfile

    from report_data import marshal_export_data
    from latex_export import _assemble_bundle_files, _write_files_to_dir

    body = await request.json()
    _resolve_bm2_into_body(body)
    session_tree = _session_tree_for(body)

    if _shutil.which(TECT_CMD) is None:
        return JSONResponse(
            {
                "error": f"LaTeX engine '{TECT_CMD}' is not available on the "
                         f"server, so the PDF preview cannot be compiled here. "
                         f"The HTML preview and Overleaf export are unaffected.",
            },
            status_code=503,
        )

    def _compile() -> "tuple[bytes | None, str]":
        """Assemble + compile in a scratch dir; return (pdf_bytes|None, log)."""
        data = marshal_export_data(body, tree=session_tree)
        files = _assemble_bundle_files(data, strict=False, tree=session_tree)
        with tempfile.TemporaryDirectory(prefix="5dtox_compile_") as tmp:
            tmp_path = Path(tmp)
            _write_files_to_dir(files, tmp_path)
            out_dir = tmp_path / "out"
            out_dir.mkdir(exist_ok=True)
            proc = subprocess.run(
                [TECT_CMD, "main.tex", "--outdir", str(out_dir)],
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=_COMPILE_TIMEOUT_S,
            )
            log = (proc.stdout or "") + (proc.stderr or "")
            pdf = out_dir / "main.pdf"
            if proc.returncode != 0 or not pdf.exists():
                return None, log
            return pdf.read_bytes(), log

    # Compilation is blocking CPU/IO (subprocess); keep the event loop free.
    loop = asyncio.get_running_loop()
    try:
        pdf_bytes, log = await loop.run_in_executor(None, _compile)
    except subprocess.TimeoutExpired:
        return JSONResponse(
            {"error": f"PDF compile exceeded {_COMPILE_TIMEOUT_S}s and was "
                      f"aborted."},
            status_code=422,
        )
    except Exception as e:
        logging.exception("PDF compile failed")
        return JSONResponse(
            {"error": f"PDF compile failed: {e}"}, status_code=500,
        )

    if pdf_bytes is None:
        # Non-zero engine exit: hand back the tail of the log so the UI can
        # show the LaTeX error the author needs to fix (the whole point of
        # catching it here instead of in Overleaf).
        tail = "\n".join(log.splitlines()[-40:])
        return JSONResponse(
            {"error": "LaTeX compilation failed.", "log": tail},
            status_code=422,
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="preview.pdf"'},
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
# GET/POST /api/repo-binding/{dtxsid} — link a report to its GitHub repo
# ---------------------------------------------------------------------------
# Renamed from /api/overleaf-binding (ADR-0005 Am.3): the binding holds only the
# git remote (and the last-pushed baseline).  The app talks to the repo, never to
# Overleaf, so there is no project_url any more.

@router.get("/api/repo-binding/{dtxsid}")
async def api_get_repo_binding(dtxsid: str):
    """Return the report's repo binding {git_remote?, baseline_commit?} ({} if unset)."""
    from roundtrip.transport import get_binding
    if safe_filename(dtxsid) != dtxsid:
        return JSONResponse({"error": f"Invalid dtxsid: {dtxsid!r}"}, status_code=400)
    return JSONResponse(get_binding(dtxsid))


@router.post("/api/repo-binding/{dtxsid}")
async def api_set_repo_binding(dtxsid: str, request: Request):
    """
    Set the report's repo binding.  Body: {git_remote} — the GitHub repo the app
    commits/pushes to and pulls committee edits from.
    """
    from roundtrip.transport import set_binding
    if safe_filename(dtxsid) != dtxsid:
        return JSONResponse({"error": f"Invalid dtxsid: {dtxsid!r}"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    binding = set_binding(dtxsid, git_remote=body.get("git_remote"))
    return JSONResponse(binding)


# ---------------------------------------------------------------------------
# GET /api/repo-status/{dtxsid} — derived state for the Report-tab controls
# ---------------------------------------------------------------------------

@router.get("/api/repo-status/{dtxsid}")
async def api_repo_status(dtxsid: str):
    """
    Report the clone's git state so the UI can *derive* which controls to offer
    (ADR-0005 Am.3 §F) — never imperatively set.  Returns:

      {has_remote, has_clone, ahead, baseline, remote_head, needs_pull}

    - ahead       — local commits not yet pushed (enables "Push to GitHub").
    - needs_pull  — the remote tip moved past our recorded baseline, i.e. the
                    committee pushed edits we haven't reconciled (Pull first).

    `ahead` is local/cheap; the needs_pull check fetches the remote head, so this
    is a deliberate (small) network call.
    """
    from roundtrip.transport import get_binding, repo_status, remote_head
    if safe_filename(dtxsid) != dtxsid:
        return JSONResponse({"error": f"Invalid dtxsid: {dtxsid!r}"}, status_code=400)

    binding = get_binding(dtxsid)
    has_remote = bool(binding.get("git_remote"))
    baseline = binding.get("baseline_commit")

    status = repo_status(dtxsid)

    head = None
    needs_pull = False
    if has_remote and status["has_clone"]:
        try:
            head = remote_head(dtxsid)
        except Exception:
            head = None
        # Only meaningful once we've pushed a baseline; a moved remote means
        # committee edits arrived that we must Pull + reconcile before pushing.
        if head and baseline and head != baseline:
            needs_pull = True

    return JSONResponse({
        "has_remote": has_remote,
        "has_clone": status["has_clone"],
        "ahead": status["ahead"],
        "baseline": baseline,
        "remote_head": head,
        "needs_pull": needs_pull,
    })


# ---------------------------------------------------------------------------
# POST /api/commit-local/{dtxsid} — render the working copy + commit it locally
# ---------------------------------------------------------------------------

@router.post("/api/commit-local/{dtxsid}")
async def api_commit_local(dtxsid: str, request: Request):
    """
    "Commit Local" (ADR-0005 Am.3 §B/§C): render the report from the **posted
    working copy** — the exact same body the HTML view renders from — and commit
    it to the local clone.  **No network.**

    This is the single-source fix: the push path renders from the working copy
    (marshal_export_data(body) → write_overleaf_dir), NOT from the on-disk
    session cache, so what the user sees is what gets committed.

    Body = the standard export payload (same as /api/export-overleaf-bundle).
    Returns {head, committed, ahead}: the new local HEAD, whether anything was
    recorded, and how many local commits now await Push.
    """
    from report_data import marshal_export_data
    from latex_export import write_overleaf_dir, DOCUMENTS_DIR
    from roundtrip.transport import get_binding, commit_document

    if safe_filename(dtxsid) != dtxsid:
        return JSONResponse({"error": f"Invalid dtxsid: {dtxsid!r}"}, status_code=400)

    binding = get_binding(dtxsid)
    remote = binding.get("git_remote")
    if not remote:
        return JSONResponse(
            {"error": "This report has no GitHub repo bound — link one first."},
            status_code=400,
        )

    try:
        body = await request.json()
    except Exception:
        body = {}
    _resolve_bm2_into_body(body)

    try:
        # Render from the working copy (body), write the bundle into the tracked
        # documents/<dtxsid>/ dir, then commit that into the clone bound to the
        # report's remote.
        report_data = marshal_export_data(body)
        out_dir = write_overleaf_dir(report_data, DOCUMENTS_DIR / dtxsid)
        result = commit_document(dtxsid, out_dir, remote=remote)
    except Exception as e:
        logging.exception("Commit Local failed for %s", dtxsid)
        return JSONResponse({"error": f"Commit failed: {e}"}, status_code=500)

    return JSONResponse(result)


# ---------------------------------------------------------------------------
# POST /api/push-to-github/{dtxsid} — push accumulated local commits to the remote
# ---------------------------------------------------------------------------

@router.post("/api/push-to-github/{dtxsid}")
async def api_push_to_github(dtxsid: str):
    """
    "Push to GitHub" (ADR-0005 Am.3 §C): push the working clone's local commits
    to the bound remote and record the pushed sha as the new baseline.

    Guard (reconcile-before-overwrite): if the remote advanced past our recorded
    baseline, the committee pushed edits we haven't reconciled — refuse with 409
    so the caller runs Pull first.  (Single-user app, so there is no longer any
    edit-lock check; concurrency is Overleaf's problem, not the app's.)

    Returns {pushed, remote}.
    """
    from roundtrip.transport import get_binding, set_binding, push_committed, remote_head

    if safe_filename(dtxsid) != dtxsid:
        return JSONResponse({"error": f"Invalid dtxsid: {dtxsid!r}"}, status_code=400)

    binding = get_binding(dtxsid)
    remote = binding.get("git_remote")
    if not remote:
        return JSONResponse(
            {"error": "This report has no GitHub repo bound — link one first."},
            status_code=400,
        )

    baseline = binding.get("baseline_commit")
    if baseline:
        try:
            head = remote_head(dtxsid)
        except Exception:
            head = None
        if head and head != baseline:
            return JSONResponse(
                {"error": "The committee has edited since the last push. "
                          "Pull their edits first, then push.",
                 "needs_pull": True},
                status_code=409,
            )

    try:
        sha = push_committed(dtxsid)
        set_binding(dtxsid, baseline_commit=sha)
    except Exception as e:
        logging.exception("Push to GitHub failed for %s", dtxsid)
        return JSONResponse({"error": f"Push failed: {e}"}, status_code=500)

    return JSONResponse({"pushed": sha, "remote": remote})


# ---------------------------------------------------------------------------
# POST /api/pull-from-github/{dtxsid} — pull committee edits + reconcile
# ---------------------------------------------------------------------------

@router.post("/api/pull-from-github/{dtxsid}")
async def api_pull_from_github(dtxsid: str):
    """
    "Pull from GitHub" (ADR-0005 Am.3 §A): pull the bound remote into the working
    clone and reconcile the committee's edits (made in Overleaf, pushed up via
    Overleaf's GitHub sync) against the recorded baseline, writing per-region
    overrides (which the next render preserves).

    Returns {written, structural, head}: the anchor ids that gained an override,
    any structural-drift warnings, and the new clone head.
    """
    from roundtrip.transport import get_binding, pull_document, reconcile_from_clone
    from roundtrip.transport import _clone_path, _REPO_ROOT  # clone-existence check

    if safe_filename(dtxsid) != dtxsid:
        return JSONResponse({"error": f"Invalid dtxsid: {dtxsid!r}"}, status_code=400)

    binding = get_binding(dtxsid)
    if not binding.get("git_remote"):
        return JSONResponse(
            {"error": "This report has no GitHub repo bound — link one first."},
            status_code=400,
        )
    if not (_clone_path(dtxsid, _REPO_ROOT) / ".git").exists():
        return JSONResponse(
            {"error": "Nothing to pull yet — Commit Local and Push to GitHub first."},
            status_code=409,
        )

    try:
        _clone, head = pull_document(dtxsid)
        baseline = binding.get("baseline_commit")
        if baseline:
            summary = reconcile_from_clone(dtxsid, baseline)
        else:
            summary = {"written": [], "structural": [], "parse_warnings": [],
                       "note": "no baseline recorded yet — nothing to attribute"}
    except Exception as e:
        logging.exception("Pull from GitHub failed for %s", dtxsid)
        return JSONResponse({"error": f"Pull failed: {e}"}, status_code=500)

    return JSONResponse({**summary, "head": head})


# ---------------------------------------------------------------------------
# POST /api/provision-report/{dtxsid} — originate (or adopt) the report's repo
# ---------------------------------------------------------------------------

@router.post("/api/provision-report/{dtxsid}")
async def api_provision_report(dtxsid: str, request: Request):
    """
    Provision the report's GitHub repo, app-driven — **init only** (ADR-0005
    Am.3 §E).

    create-or-adopt: if the convention-named repo (<DTXSID>-5D-Tox) already
    exists it's adopted; otherwise it's created.  The binding's git_remote is set
    to it.  No content is rendered or pushed here — the first content reaches the
    repo through the normal Commit Local → Push to GitHub turn, identical to every
    later turn.  Returns whether it created vs adopted so the UI can say which.

    After this, the human does the one manual step — Import from GitHub in
    Overleaf — once content has been pushed.

    Optional body {private}.
    """
    from styling_export.github_provision import ensure_repo, repo_slug
    from roundtrip.transport import set_binding

    if safe_filename(dtxsid) != dtxsid:
        return JSONResponse({"error": f"Invalid dtxsid: {dtxsid!r}"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    private = body.get("private", True)

    try:
        created, repo_url = ensure_repo(
            dtxsid, private=private,
            description=f"5-Day Tox report — {dtxsid}. GitHub round-trip via rlm-bmdx.",
        )
        set_binding(dtxsid, git_remote=repo_url)
    except Exception as e:
        logging.exception("Provision failed for %s", dtxsid)
        return JSONResponse({"error": f"Provision failed: {e}"}, status_code=500)

    return JSONResponse({
        "created": created,
        "adopted": not created,
        "repo": repo_url,
        "slug": repo_slug(dtxsid),
    })


# ---------------------------------------------------------------------------
# GET /api/report-for-project/{project_id} — reverse soft-link (id → dtxsid)
# ---------------------------------------------------------------------------

@router.get("/api/report-for-project/{project_id}")
async def api_report_for_project(project_id: str):
    """Resolve an Overleaf project id back to the report (dtxsid) bound to it."""
    from styling_export.overleaf_provision import dtxsid_for_project
    return JSONResponse({"dtxsid": dtxsid_for_project(project_id)})


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
    session_tree = _session_tree_for(body)
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
        report_data = marshal_export_data(body, section_filter=section_filter, tree=session_tree)
        html = generate_html(report_data, section_filter=section_filter, tree=session_tree)
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


# ---------------------------------------------------------------------------
# Document-structure config (ADR-0007 follow-on): per-session YAML that
# defines the document STRUCTURE, editable in the UI without re-integrating.
# ---------------------------------------------------------------------------

@router.get("/api/document-config/{dtxsid}")
async def api_get_document_config(dtxsid: str, default: int = 0):
    """
    Return the session's document-structure YAML for the config editor.

    When the session has no per-session override yet, returns the global default
    structure (so the editor opens on the real active document, not a blank box).
    `is_default` tells the UI whether it's showing the shared default (True) or
    this session's own saved copy (False).

    ``?default=1`` forces the shared default regardless of any saved copy — the
    "Load default" affordance, so a session that already has an override can
    still get back to the default in the editor (unsaved until the user saves).
    """
    from document_config import load_session_document_yaml, default_document_yaml

    if default:
        return JSONResponse({"yaml": default_document_yaml(), "is_default": True})
    text = load_session_document_yaml(dtxsid)
    if text is None:
        return JSONResponse({"yaml": default_document_yaml(), "is_default": True})
    return JSONResponse({"yaml": text, "is_default": False})


@router.post("/api/document-config/{dtxsid}")
async def api_save_document_config(dtxsid: str, request: Request):
    """
    Validate + persist the session's document-structure YAML.

    The save is gated on a full tree build (parse + catalog validation + unique
    ids); an invalid edit returns 422 with the validation message and writes
    nothing, so the previous structure stays intact.  On success the caller
    re-fetches /api/document-tree?dtxsid=… and re-renders (no re-integration —
    only the structure changed).
    """
    from document_config import save_session_document_yaml

    body = await request.json()
    text = body.get("yaml")
    if not isinstance(text, str) or not text.strip():
        return JSONResponse(
            {"error": "Request must include a non-empty 'yaml' string."},
            status_code=422,
        )
    try:
        save_session_document_yaml(dtxsid, text)
    except ValueError as e:
        # Well-formed request, invalid document structure — surface the exact
        # validation error in the editor rather than 500.
        return JSONResponse({"error": str(e)}, status_code=422)
    except Exception as e:
        logger.exception("Failed to save document config for %s", dtxsid)
        return JSONResponse({"error": f"Save failed: {e}"}, status_code=500)
    return JSONResponse({"saved": True})


# ---------------------------------------------------------------------------
# Default (global template) document structure — the structure EVERY report
# inherits without a per-session override.  Edits the git-tracked template and
# applies live (no restart).  Distinct from the per-session routes above.
# ---------------------------------------------------------------------------

@router.get("/api/document-config-default")
async def api_get_document_config_default():
    """Return the default (template) document-structure YAML for the editor."""
    from document_config import load_default_document_yaml
    return JSONResponse({"yaml": load_default_document_yaml()})


@router.post("/api/document-config-default")
async def api_save_document_config_default(request: Request):
    """
    Validate + persist + LIVE-APPLY an edit to the DEFAULT (template) structure.

    Same validate-before-write gate as the per-session route (422 on invalid,
    writing nothing).  On success the template file is rewritten (siblings
    preserved), the in-process document tree is rebuilt in place, and the golden
    fixture is regenerated — so every report without its own override, plus the
    nav/preview, reflect the new default with no restart.
    """
    from document_config import save_default_document_yaml

    body = await request.json()
    text = body.get("yaml")
    if not isinstance(text, str) or not text.strip():
        return JSONResponse(
            {"error": "Request must include a non-empty 'yaml' string."},
            status_code=422,
        )
    try:
        save_default_document_yaml(text)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    except Exception as e:
        logger.exception("Failed to save default document config")
        return JSONResponse({"error": f"Save failed: {e}"}, status_code=500)
    return JSONResponse({"saved": True})


# ---------------------------------------------------------------------------
# Layout STYLES config — per-content-type typography & page flow (fonts,
# alignment, spacing, breaks).  Pure presentation: it does NOT feed the
# integration pipeline, so both the per-session and default edits re-render with
# no re-integration (mirrors the document-structure routes above; the same
# scope decision as document_config's per-session styles helpers).
# ---------------------------------------------------------------------------

@router.get("/api/layout-style/{dtxsid}")
async def api_get_layout_style(dtxsid: str, default: int = 0):
    """
    Return the session's layout-styles config for the styles editor, as BOTH the
    raw ``yaml`` text (the CodeMirror tab) and the parsed ``config`` mapping (the
    visual builder, which is JSON-only so no client YAML parser is needed).

    When the session has no per-session styles override, returns the global
    default ``styles:`` block (so the editor opens on the active styling, not a
    blank box).  ``is_default`` tells the UI whether it's showing the shared
    default (True) or this session's own saved copy (False).  ``?default=1``
    forces the shared default — the "Load default" affordance.
    """
    import yaml as _yaml
    from document_config import (
        load_session_layout_style,
        default_layout_style_yaml,
        default_layout_style_config,
    )

    if default:
        return JSONResponse({
            "yaml": default_layout_style_yaml(),
            "config": default_layout_style_config(),
            "is_default": True,
        })
    cfg = load_session_layout_style(dtxsid)
    if cfg is None:
        return JSONResponse({
            "yaml": default_layout_style_yaml(),
            "config": default_layout_style_config(),
            "is_default": True,
        })
    text = _yaml.safe_dump({"styles": cfg}, sort_keys=False, allow_unicode=True)
    return JSONResponse({"yaml": text, "config": cfg, "is_default": False})


@router.post("/api/layout-style/{dtxsid}")
async def api_save_layout_style(dtxsid: str, request: Request):
    """
    Validate + persist the session's layout-styles config.

    Accepts EITHER a raw ``yaml`` string (the CodeMirror tab) or a parsed
    ``config`` mapping (the visual builder — dumped to YAML server-side so both
    paths hit the identical validated save).  Gated on the loud enum/length/color
    + catalog-type validation (422 on a bad value, writing nothing).  On success
    the caller re-renders the preview (no re-integration — styles are pure
    presentation).
    """
    import yaml as _yaml
    from document_config import save_session_layout_style

    body = await request.json()
    text = body.get("yaml")
    if text is None and isinstance(body.get("config"), dict):
        # Builder path: serialize the config mapping to the same YAML shape the
        # raw editor produces, then share the one validated save below.
        text = _yaml.safe_dump({"styles": body["config"]}, sort_keys=False,
                               allow_unicode=True)
    if not isinstance(text, str) or not text.strip():
        return JSONResponse(
            {"error": "Request must include a non-empty 'yaml' string or a "
                      "'config' object."},
            status_code=422,
        )
    try:
        save_session_layout_style(dtxsid, text)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    except Exception as e:
        logger.exception("Failed to save layout style for %s", dtxsid)
        return JSONResponse({"error": f"Save failed: {e}"}, status_code=500)
    return JSONResponse({"saved": True})


@router.get("/api/layout-style-default")
async def api_get_layout_style_default():
    """Return the default (template) layout-styles YAML for the editor."""
    from document_config import default_layout_style_yaml
    return JSONResponse({"yaml": default_layout_style_yaml()})


@router.post("/api/layout-style-default")
async def api_save_layout_style_default(request: Request):
    """
    Validate + persist an edit to the DEFAULT (template) ``styles:`` block.

    Same validate-before-write gate as the per-session route (422 on invalid).
    On success only the template's ``styles:`` sibling is rewritten; no tree
    rebuild is needed (styles are pure presentation, re-read live per render).
    """
    from document_config import save_default_layout_style

    body = await request.json()
    text = body.get("yaml")
    if not isinstance(text, str) or not text.strip():
        return JSONResponse(
            {"error": "Request must include a non-empty 'yaml' string."},
            status_code=422,
        )
    try:
        save_default_layout_style(text)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    except Exception as e:
        logger.exception("Failed to save default layout style")
        return JSONResponse({"error": f"Save failed: {e}"}, status_code=500)
    return JSONResponse({"saved": True})
