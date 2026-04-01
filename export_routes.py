"""
Export and style-profile routes for 5dToxReport.

Provides endpoints for exporting the complete NIEHS Report 10-structured
document as tagged PDF/UA-1, plus managing the global writing style
profile that the LLM uses to match user preferences.

Extracted from background_server.py (Phase 4) to keep the main server
file focused on app creation, middleware, and router mounting.

Endpoints:
  GET    /api/style-profile          — Retrieve the global style profile
  DELETE /api/style-profile/{idx}    — Delete a style rule by index
  POST   /api/export-pdf             — Export full report to tagged PDF/UA-1
  GET    /api/export-pdf-scaffold    — Generate scaffold PDF with placeholders
  GET    /api/export-bm2/{dtxsid}    — Download enriched .bm2 file
"""

import asyncio
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from session_store import safe_filename
from style_learning import (
    load_style_profile, save_style_profile,
)
from server_state import get_bm2_uploads

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
# POST /api/export-pdf — export full report to tagged PDF/UA-1
# ---------------------------------------------------------------------------

@router.post("/api/export-pdf")
async def api_export_pdf(request: Request):
    """
    Export the full 5dToxReport to a PDF/UA-1 compliant PDF file.

    Accepts the same JSON payload as /api/export-docx for consistency.
    Marshals the data into the Typst template schema and compiles it
    using the Typst compiler (embedded Rust binary via typst-py).

    The output PDF has:
      - Full StructTreeRoot with H1-H3, P, Table/TH/TD/TR tags
      - PDF/UA-1 identifier in XMP metadata
      - /Lang set to "en" in the document catalog
      - /MarkInfo << /Marked true >>
      - Proper heading hierarchy matching NIEHS Report 10
      - Running header and page numbers marked as Artifacts

    Returns the PDF file as a downloadable attachment.
    """
    from report_pdf import build_report_pdf, marshal_export_data

    body = await request.json()

    # Resolve table_data for apical sections that reference uploaded .bm2 files.
    # The web UI may send bm2_id references instead of inline table_data,
    # so we need to look up the cached data from the upload store.
    _bm2_uploads = get_bm2_uploads()
    for sec in body.get("apical_sections", []):
        if "table_data" not in sec or not sec["table_data"]:
            bm2_id = sec.get("bm2_id", "")
            upload = _bm2_uploads.get(bm2_id)
            if upload and upload.get("table_data"):
                sec["table_data"] = upload["table_data"]

    # Also inject narrative from server cache if not provided inline
    for sec in body.get("apical_sections", []):
        if not sec.get("narrative_paragraphs"):
            bm2_id = sec.get("bm2_id", "")
            upload = _bm2_uploads.get(bm2_id)
            if upload and upload.get("narrative"):
                sec["narrative_paragraphs"] = upload["narrative"]

    # Optional section filter for per-tab PDF previews.
    # When set to "apical", "genomics", or "charts", the marshalled data
    # is stripped down to only that section — producing a focused PDF
    # suitable for embedding in a tab's iframe.
    section_filter = body.get("section_filter")

    # Debug: log apical section data when section filter is active
    if section_filter:
        asecs = body.get("apical_sections", [])
        logger.info(
            "section_filter=%s, apical_sections=%d, table_data_sizes=%s",
            section_filter,
            len(asecs),
            [(s.get("section_title", "?"), list(s.get("table_data", {}).keys())) for s in asecs],
        )

    # --- Server-side chart rendering for all organ×sex combos ---
    # Instead of relying on client-captured screenshots of the active
    # Plotly tab, render charts server-side so the PDF includes every
    # organ×sex combination.  Iterates genomics_sections from the
    # payload, groups gene_set entries by organ×sex, and calls
    # render_chart_images() for each group.
    chart_images = None
    genomics_secs = body.get("genomics_sections", [])
    gene_set_secs = [s for s in genomics_secs if s.get("type") == "gene_set"]
    if gene_set_secs:
        from genomics_viz import render_chart_images

        # Group gene_set sections by organ×sex — each group produces
        # one UMAP + one cluster scatter chart pair.
        by_organ_sex: dict[str, dict] = {}
        for sec in gene_set_secs:
            organ = sec.get("organ", "")
            sex = sec.get("sex", "")
            key = f"{organ}_{sex}"
            if key not in by_organ_sex:
                by_organ_sex[key] = {
                    "organ": organ,
                    "sex": sex,
                    "dose_unit": sec.get("dose_unit", "mg/kg"),
                    "gene_sets": [],
                }
            by_organ_sex[key]["gene_sets"].extend(sec.get("gene_sets", []))

        # Render chart images for each organ×sex combo
        chart_images = []
        for key, group in by_organ_sex.items():
            if not group["gene_sets"]:
                continue
            try:
                result = render_chart_images(
                    gene_sets=group["gene_sets"],
                    organ=group["organ"],
                    sex=group["sex"],
                    dose_unit=group["dose_unit"],
                )
                organ_title = group["organ"].capitalize() or "Unknown"
                sex_title = group["sex"].capitalize() or ""
                result["label"] = f"{organ_title} ({sex_title})"
                chart_images.append(result)
            except Exception as e:
                logger.warning(
                    "Chart rendering failed for %s: %s", key, e,
                )

        if not chart_images:
            chart_images = None

    try:
        # Marshal the DOCX-format payload into the Typst template schema
        report_data = marshal_export_data(body, section_filter=section_filter)

        # Compile to PDF/UA-1 — sub-second for typical report sizes.
        # Chart images are written to temp files alongside the Typst
        # template so it can reference them as local images.
        pdf_bytes = build_report_pdf(report_data, chart_images=chart_images)
    except Exception as e:
        logging.exception("PDF export failed")
        return JSONResponse(
            {"error": f"PDF generation failed: {e}"},
            status_code=500,
        )

    # Write to a temp file for FileResponse
    chemical_name = body.get("chemical_name", "Chemical")
    safe_name = safe_filename(chemical_name)
    filename = f"5dToxReport_{safe_name}.pdf"

    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".pdf", prefix="5dtox_",
    )
    tmp.write(pdf_bytes)
    tmp.close()

    return FileResponse(
        tmp.name,
        filename=filename,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# GET /api/export-pdf-scaffold — generate a scaffold PDF showing all sections
# ---------------------------------------------------------------------------

@router.get("/api/export-pdf-scaffold")
async def api_export_pdf_scaffold(
    chemical_name: str = "Test Article",
    casrn: str = "000-00-0",
    dtxsid: str = "DTXSID0000000",
):
    """
    Generate a complete scaffold PDF with placeholder content in every section.

    This endpoint produces a full NIEHS Report 10-structured PDF with all
    sections populated by clearly-marked placeholder text (wrapped in angle
    quotes).  The purpose is to show the exact page flow, typography, table
    layout, landscape pages, and pagination that the final report will have.

    Every template code path is exercised: title page, roman-numeral front
    matter (foreword, TOC, tables list, about, peer review, pub details,
    acknowledgments, abstract), arabic body pages (background, M&M with
    Table 1, results with landscape dose-response tables, internal dose
    portrait table, BMD summary sex-grouped table, genomics gene set
    and gene tables with GO/gene descriptions), summary, and references.

    Query parameters allow customizing the chemical identity on the
    title page and throughout the document:
      ?chemical_name=Perfluorohexanesulfonamide&casrn=41997-13-1&dtxsid=DTXSID50469320

    Returns the PDF as a downloadable attachment.
    """
    from report_pdf import build_report_pdf, scaffold_report_data

    try:
        data = scaffold_report_data(
            chemical_name=chemical_name,
            casrn=casrn,
            dtxsid=dtxsid,
        )
        pdf_bytes = build_report_pdf(data)
    except Exception as e:
        logging.exception("Scaffold PDF generation failed")
        return JSONResponse(
            {"error": f"Scaffold PDF generation failed: {e}"},
            status_code=500,
        )

    # Clean filename from chemical name
    safe_name = safe_filename(chemical_name)
    filename = f"5dToxReport_Scaffold_{safe_name}.pdf"

    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".pdf", prefix="5dtox_scaffold_",
    )
    tmp.write(pdf_bytes)
    tmp.close()

    return FileResponse(
        tmp.name,
        filename=filename,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

    if not json_path.exists():
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
