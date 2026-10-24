"""
session_routes.py — Session persistence and history API endpoints.

Extracted from background_server.py.  These endpoints manage the on-disk
session state: loading saved sessions, approving/unapproving report sections,
browsing version history, restoring past versions, and computing the
apical endpoint BMD summary from approved .bm2 data.

All endpoints are mounted as a FastAPI APIRouter on the /api prefix.

Endpoints:
  GET  /api/session/{dtxsid}                        — Load a saved session
  POST /api/session/approve                         — Accept a section as it is (fenced, C2 D5)
  POST /api/session/unapprove                       — Reopen a section, with a reason
  GET  /api/session/{dtxsid}/history/{section_key}  — Version history
  POST /api/session/{dtxsid}/restore                — Restore a past version
  GET  /api/session/{dtxsid}/bmd-summary            — Auto-derive BMD summary
  GET  /api/experiment-metadata/{dtxsid}            — Retrieve experiment metadata
  POST /api/experiment-metadata/{dtxsid}            — Save user-edited metadata
  POST /api/pool/reset/{dtxsid}                     — Full pool reset (destructive)
  POST /api/session/reset/{dtxsid}                  — Full session reset (nuclear)
"""

import asyncio
import json
import logging
from common.dtxsid import validate_dtxsid
import os
import shutil
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from web_routes.dtxsid_param import Dtxsid
from workflow.errors import StepError

# Imported for its NAME, not for use here: tests/conftest.py's mock_bmdx_pipe
# patches `web_routes.session_routes.bm2_cache` at this import site (the Java
# .bm2 reader seam). Removing it breaks the whole TestClient suite.
from bmdx_pipe import bm2_cache  # noqa: F401
from pipeline.session_store import (
    SESSIONS_DIR, now_iso, session_dir, bm2_slug,
    NARRATIVE_OVERRIDES_FILE, read_narrative_overrides, latest_session_cache,
)
from common.session_files import read_json_file
from pipeline.pool_orchestrator import (
    fingerprint_and_store, _js_dose_key,
    load_cached_fingerprint, restore_fingerprint,
    load_integrated,
)
from web_routes.server_state import (
    get_bm2_uploads,
    get_csv_uploads,
    get_data_uploads,
    get_pool_fingerprints,
    get_integrated_pool,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()


def _step_refusal(exc) -> JSONResponse:
    """A step's refusal in this module's {"error": …} shape, explained
    (web_routes.refusal_response)."""
    from web_routes.refusal_response import refusal_response
    return refusal_response(exc)


# ---------------------------------------------------------------------------
# GET /api/session/{dtxsid}/bmd-summary — auto-derive apical endpoint BMD summary
# ---------------------------------------------------------------------------

@router.get("/api/session/{dtxsid}/bmd-summary")
async def api_bmd_summary(dtxsid: Dtxsid):
    """
    Auto-derive an Apical Endpoint BMD Summary from all approved .bm2 sections.

    Iterates all bm2_*.json files in the session directory, extracts every
    endpoint where BMD ≠ "ND", and computes LOEL (lowest dose with a
    significance marker) and NOEL (highest dose below LOEL without a marker).

    This data is already present in the approved table JSON — we just need
    to aggregate it across sections into one sorted summary.

    Returns JSON:
      {
        "endpoints": [
          {
            "endpoint": "Liver Relative",
            "bmd": "4.23",
            "bmdl": "2.10",
            "loel": "5.0",
            "noel": "1.5",
            "direction": "Increased",
            "sex": "Male"
          }, ...
        ],
        "sorted_by": "bmd_asc"
      }
    """
    d = SESSIONS_DIR / validate_dtxsid(dtxsid)
    if not d.exists():
        return JSONResponse(
            {"error": f"No session found for {dtxsid}"},
            status_code=404,
        )

    # Gather all approved bm2_*.json files
    endpoints = []
    for f in sorted(d.glob("bm2_*.json")):
        try:
            section = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        tables_json = section.get("tables_json", {})

        # Each table is keyed by sex ("Male", "Female")
        for sex, rows in tables_json.items():
            for row in rows:
                bmd_str = row.get("bmd", "ND")
                bmdl_str = row.get("bmdl", "ND")

                # Skip endpoints without a numeric BMD.  Non-numeric values:
                #   "ND"   — not determined (gate not passed or modeling failed)
                #   "—"    — endpoint not modeled by BMDExpress 3
                #   "NVM"  — no viable model
                #   "UREP" — unreliable estimate of potency
                #   "NA"   — not applicable (n-row, context rows)
                # Only numeric values and "<LNZD/3" (NR) are included.
                if bmd_str in ("ND", "\u2014", "NVM", "UREP", "NA", ""):
                    continue

                label = row.get("label", "")
                # Skip the "n" row (sample sizes, not an endpoint)
                if label.lower() == "n":
                    continue

                # Derive LOEL and NOEL from significance markers in the
                # values_by_dose dict.  Each value string may end with
                # "*" or "**" if the dose group showed a significant
                # pairwise difference vs. control.
                values = row.get("values", {})
                doses = row.get("doses", [])

                # Sort doses numerically (they may be strings)
                try:
                    sorted_doses = sorted(
                        [float(d) for d in doses if float(d) > 0],
                    )
                except (ValueError, TypeError):
                    sorted_doses = []

                # Find LOEL: lowest treatment dose with a significance marker
                loel = None
                for dose in sorted_doses:
                    dose_key = _js_dose_key(dose)
                    val = values.get(dose_key, "")
                    if "*" in str(val):
                        loel = dose
                        break

                # Find NOEL: highest dose below LOEL without a marker.
                # If LOEL is the lowest dose, NOEL is None (below tested range).
                noel = None
                if loel is not None:
                    for dose in sorted_doses:
                        if dose >= loel:
                            break
                        dose_key = _js_dose_key(dose)
                        val = values.get(dose_key, "")
                        if "*" not in str(val):
                            noel = dose

                # Determine direction from the trend marker.
                # The trend_marker field has "*" or "**" for significant
                # Jonckheere trend.  To get direction, we check if the
                # highest-dose mean is greater or less than control mean.
                trend_marker = row.get("trend_marker", "")
                direction = ""
                if trend_marker:
                    # Try to parse control and highest-dose values to
                    # determine direction of change
                    try:
                        control_key = _js_dose_key(0.0)
                        control_val = values.get(control_key, "")
                        # Extract numeric part (before ±)
                        control_num = float(control_val.split("±")[0].replace("*", "").strip())
                        if sorted_doses:
                            high_key = _js_dose_key(sorted_doses[-1])
                            high_val = values.get(high_key, "")
                            high_num = float(high_val.split("±")[0].replace("*", "").strip())
                            direction = "Increased" if high_num > control_num else "Decreased"
                    except (ValueError, IndexError, AttributeError):
                        direction = ""

                endpoints.append({
                    "endpoint": label,
                    "bmd": bmd_str,
                    "bmdl": bmdl_str,
                    "loel": loel,
                    "noel": noel,
                    "direction": direction,
                    "sex": sex,
                })

    # Sort by BMD ascending (numeric sort; non-numeric values filtered above,
    # but NR entries like "<0.05" may remain — parse the numeric part).
    def _bmd_sort_key(e):
        try:
            return float(e["bmd"].lstrip("<"))
        except (ValueError, TypeError):
            return 9999
    endpoints.sort(key=_bmd_sort_key)

    return JSONResponse({
        "endpoints": endpoints,
        "sorted_by": "bmd_asc",
    })


# ---------------------------------------------------------------------------
# GET /api/session/{dtxsid} — load a previously saved session
# ---------------------------------------------------------------------------

@router.get("/api/session/{dtxsid}")
async def api_session_load(dtxsid: Dtxsid):
    """
    Load a previously-saved session for a given DTXSID.

    Looks up sessions/{dtxsid}/ on disk and returns all saved section data
    including the original sections (meta, identity, background, bm2) and
    the new NIEHS sections (methods, bmd_summary, genomics, summary).

    Returns JSON:
      {
        "exists": true/false,
        "meta": {...} or null,
        "identity": {...} or null,
        "background": {...} or null,
        "methods": {...} or null,
        "bm2_sections": { "organ-and-body-weights": {...}, ... },
        "bmd_summary": {...} or null,
        "genomics_sections": { "liver_male": {...}, ... },
        "summary": {...} or null
      }
    """
    import time as _time

    from common import provenance

    _load_t0 = _time.monotonic()

    _bm2_uploads = get_bm2_uploads()
    _data_uploads = get_data_uploads()

    d = SESSIONS_DIR / validate_dtxsid(dtxsid)
    if not d.exists():
        return JSONResponse({"exists": False})

    # Build reverse lookup: file path → existing file_id for both upload
    # dicts.  This prevents re-registering the same file with a new UUID
    # on every page reload / session restore, which would cause
    # ensure_fingerprints() to create duplicate fingerprint entries.
    _bm2_paths = {
        entry.get("temp_path"): fid
        for fid, entry in _bm2_uploads.items()
        if entry.get("temp_path")
    }
    _data_paths = {
        entry.get("temp_path"): fid
        for fid, entry in _data_uploads.items()
        if entry.get("temp_path")
    }

    # Helper: read a JSON file if it exists, else return None.
    # Records a `disk_read` provenance event (bytes + ms) per hit so the session-load
    # profile shows which reads dominate the "loading from cache" wait.
    def _read_json(name: str):
        p = d / name
        if p.exists():
            _t0 = _time.monotonic()
            text = p.read_text(encoding="utf-8")
            data = json.loads(text)
            provenance.record(
                "disk_read", dtxsid=dtxsid, unit=name, bytes=len(text),
                ms=round((_time.monotonic() - _t0) * 1000, 1),
            )
            return data
        return None

    # Gather all bm2_*.json files into a dict keyed by slug.
    # Also re-register any persisted .bm2 files into _bm2_uploads so they
    # are available for preview, reprocessing, and export without re-upload.
    # The returned section data includes a server_file_id that the client
    # can use as a real upload ID (not a synthetic "file-restored-*" key).
    bm2_sections = {}
    files_dir = d / "files"
    for f in sorted(d.glob("bm2_*.json")):
        # Filename is e.g. "bm2_organ-and-body-weights.json"
        slug = f.stem.removeprefix("bm2_")
        _t0 = _time.monotonic()
        _text = f.read_text(encoding="utf-8")
        section = json.loads(_text)
        provenance.record(
            "disk_read", dtxsid=dtxsid, unit=f.stem, bytes=len(_text),
            ms=round((_time.monotonic() - _t0) * 1000, 1),
        )

        # Re-register the .bm2 file in _bm2_uploads if it exists on disk.
        # This makes the file fully functional (preview, process, export)
        # without needing the user to re-upload it.
        # Reuse existing file_id if the path is already registered (avoids
        # accumulating duplicate entries on repeated page reloads).
        original_filename = section.get("filename", "")
        bm2_on_disk = files_dir / original_filename if original_filename else None
        if bm2_on_disk and bm2_on_disk.exists():
            disk_path = str(bm2_on_disk)
            file_id = _bm2_paths.get(disk_path)
            if not file_id:
                file_id = str(uuid.uuid4())
                _bm2_uploads[file_id] = {
                    "filename": original_filename,
                    "temp_path": disk_path,
                    "table_data": None,   # will be populated on first preview/process
                    "bm2_json": None,     # will be populated on first preview/process
                }
                _bm2_paths[disk_path] = file_id
            # Tell the client what server-side file_id to use
            section["server_file_id"] = file_id

        bm2_sections[slug] = section

    # Discover files in files/ that don't have a corresponding approved
    # section yet (uploaded but not yet processed/approved).  Register them
    # in the appropriate server-side store (_bm2_uploads or _data_uploads)
    # and return them as "pending_files" so the client can add them to the
    # file pool on restore.
    pending_files = []
    # Build a set of filenames that already have approved sections
    approved_filenames = {
        sec.get("filename", "") for sec in bm2_sections.values()
    }
    if files_dir.exists():
        for data_file in sorted(files_dir.iterdir()):
            if not data_file.is_file():
                continue
            ext = data_file.suffix.lower()

            if ext == ".bm2":
                if data_file.name in approved_filenames:
                    continue  # already handled above as an approved section
                # Unapproved .bm2 file — register in _bm2_uploads.
                # Reuse existing file_id if already registered (repeated
                # session loads would otherwise pile up duplicate entries).
                disk_path = str(data_file)
                file_id = _bm2_paths.get(disk_path)
                if not file_id:
                    file_id = str(uuid.uuid4())
                    _bm2_uploads[file_id] = {
                        "filename": data_file.name,
                        "temp_path": disk_path,
                        "table_data": None,
                        "bm2_json": None,
                    }
                    _bm2_paths[disk_path] = file_id
                pending_files.append({
                    "id": file_id,
                    "filename": data_file.name,
                    "type": "bm2",
                })
                # Try loading the fingerprint from the on-disk cache first.
                # This avoids the expensive LLM call in
                # _deduce_metadata_from_experiments() that runs inside
                # fingerprint_and_store() for .bm2 files without augmented
                # ExperimentDescription metadata.
                cached_fp = load_cached_fingerprint(dtxsid, data_file.name, file_id)
                if cached_fp:
                    restore_fingerprint(dtxsid, file_id, cached_fp)
                else:
                    # No cache — fall back to full fingerprinting (includes
                    # LLM call).  This only happens on the first load of a
                    # file; subsequent restores will use the cache.
                    fingerprint_and_store(
                        file_id, data_file.name, str(data_file), "bm2", dtxsid,
                    )

            elif ext in (".csv", ".txt", ".xlsx"):
                # Raw data file (dose-response experimental data or
                # spreadsheet).  Register in _data_uploads so the
                # preview endpoint can serve it.
                # Reuse existing file_id if already registered.
                file_type = ext.lstrip(".")
                disk_path = str(data_file)
                file_id = _data_paths.get(disk_path)
                if not file_id:
                    file_id = str(uuid.uuid4())
                    _data_uploads[file_id] = {
                        "filename": data_file.name,
                        "temp_path": disk_path,
                        "type": file_type,
                    }
                    _data_paths[disk_path] = file_id
                pending_files.append({
                    "id": file_id,
                    "filename": data_file.name,
                    "type": file_type,
                })
                # Try cached fingerprint first (xlsx/csv/txt fingerprinting
                # is cheaper than .bm2 but still worth caching for
                # consistency and to avoid re-parsing files).
                cached_fp = load_cached_fingerprint(dtxsid, data_file.name, file_id)
                if cached_fp:
                    restore_fingerprint(dtxsid, file_id, cached_fp)
                else:
                    fingerprint_and_store(
                        file_id, data_file.name, str(data_file), file_type, dtxsid,
                    )
            # Skip other file types (e.g., leftover pickle sidecars)

    # Gather all genomics_*.json files into a dict keyed by organ_sex
    # (e.g., "liver_male", "kidney_female")
    genomics_sections = {}
    for f in sorted(d.glob("genomics_*.json")):
        slug = f.stem.removeprefix("genomics_")
        _t0 = _time.monotonic()
        _text = f.read_text(encoding="utf-8")
        genomics_sections[slug] = json.loads(_text)
        provenance.record(
            "disk_read", dtxsid=dtxsid, unit=f.stem, bytes=len(_text),
            ms=round((_time.monotonic() - _t0) * 1000, 1),
        )

    # Load the raw organ_sex-keyed genomics cache first — used by both
    # the narrative assembler and (Bug C fallback) by the client when
    # no approved `genomics_*.json` files exist for this session.
    genomics_cache = None
    genomics_cache_path = latest_session_cache(d, "_cache_genomics_*.json")
    if genomics_cache_path is not None:
        _t0 = _time.monotonic()
        genomics_cache = read_json_file(genomics_cache_path)
        provenance.record(
            "disk_read", dtxsid=dtxsid, unit="_cache_genomics",
            bytes=genomics_cache_path.stat().st_size,
            ms=round((_time.monotonic() - _t0) * 1000, 1),
        )

    # Load cached chart images (PNG + SVG per organ × sex).  These are
    # the same figures the PDF uses — the HTML in-app view embeds the
    # SVGs inline, the PDF embeds the PNGs.  Both come from the same
    # `_cache_charts_*.json` written during process-integrated.
    #
    # Schema migration: caches written before SVGs were added lack
    # `umap_svg`/`cluster_svg`.  Re-render from genomics_cache on the
    # fly and overwrite the cache file, so subsequent reloads are
    # cheap.  Shared `cache_has_svg` + `render_chart_images_for_sections`
    # helpers in genomics_viz keep this in lockstep with the
    # pool_orchestrator path.
    chart_images = None
    chart_cache_path = latest_session_cache(d, "_cache_charts_*.json")
    if chart_cache_path is not None:
        _t0 = _time.monotonic()
        chart_images = read_json_file(chart_cache_path)
        provenance.record(
            "disk_read", dtxsid=dtxsid, unit="_cache_charts",
            bytes=chart_cache_path.stat().st_size,
            ms=round((_time.monotonic() - _t0) * 1000, 1),
        )

    if chart_images and genomics_cache and chart_cache_path:
        try:
            from genomics.genomics_viz import (
                cache_has_svg, render_chart_images_for_sections,
            )
            if not cache_has_svg(chart_images):
                logging.info(
                    "Chart cache for %s lacks SVG — re-rendering on "
                    "session load", dtxsid,
                )
                # Pick the primary BMD stat from the cached genomics
                # entries — mirrors what pool_orchestrator does.
                first_entry = next(iter(genomics_cache.values()), {})
                stats = list((first_entry.get("gene_sets_by_stat") or {}).keys())
                bmd_stat = stats[0] if stats else "median"
                # Chart styling + data-driven types come from the same active
                # template as the document structure (WP-6), so this migration
                # render matches the pool_orchestrator render.
                from document_model.document_tree import ACTIVE_TEMPLATE
                from document_model.document_template import load_chart_style, load_chart_types
                rerendered = render_chart_images_for_sections(
                    genomics_sections=genomics_cache,
                    bmd_stat=bmd_stat,
                    chart_style_cfg=load_chart_style(ACTIVE_TEMPLATE),
                    chart_types=load_chart_types(ACTIVE_TEMPLATE),
                )
                if rerendered:
                    chart_images = rerendered
                    # Overwrite the cache file so subsequent reloads
                    # skip the re-render.  Using orjson for speed on
                    # the ~2MB payload.
                    import orjson
                    chart_cache_path.write_bytes(
                        orjson.dumps(rerendered)
                    )
        except Exception:
            logging.exception(
                "Chart cache SVG migration failed for %s", dtxsid,
            )

    # Rebuild Gene Set / Gene BMD body narratives from caches on disk:
    #   * deterministic tier  — reproduced from genomics_sections +
    #     MethodsContext via the shared `build_genomics_body_narratives`
    #   * LLM tier           — pulled from the interpretation cache
    #     files `_cache_interpretation_{organ}_{sex}_{hash}.json` which
    #     carry `gene_set_narrative` / `gene_narrative` fields when the
    #     LLM has previously run (see `generate_genomics_narrative_async`)
    #   * user overrides     — `genomics_narrative_overrides.json` at
    #     session root, if the user has used the Lock/Unlock flow to
    #     edit a paragraph; wins over both cached tiers
    gene_set_narrative = None
    gene_narrative = None
    try:
        if genomics_cache:
            # --- Deterministic tier ---
            methods_ctx = None
            chem_name = None
            methods_cache = latest_session_cache(d, "_cache_methods_*.json")
            if methods_cache is not None:
                methods_ctx = (read_json_file(methods_cache) or {}).get("context")
            identity = _read_json("identity.json")
            if identity:
                chem_name = identity.get("name") or identity.get("chemical_name")

            from genomics.genomics_narratives import build_genomics_body_narratives
            narratives = build_genomics_body_narratives(
                genomics_sections=genomics_cache,
                methods_context=methods_ctx,
                chemical_name=chem_name or "the test article",
            )
            gene_set_narrative = narratives.get("gene_set_narrative")
            gene_narrative = narratives.get("gene_narrative")

            # --- LLM tier (by_organ_llm) from interpretation caches ---
            # Iterate the organ_sex keys, look up the latest interpretation
            # cache for each, and bundle the `gene_set_narrative` /
            # `gene_narrative` paragraphs per organ×sex.  The fold into
            # per-organ paragraph lists (sex-labelled, male-then-female) plus
            # the user-override merge happen in the shared
            # `aggregate_organ_llm_narratives` helper, so this reload path
            # stays byte-for-byte identical to process-integrated's Layer 3.5.
            per_organ_bundles: dict[str, dict[str, dict]] = {}
            for key in genomics_cache.keys():
                if "_" not in key:
                    continue
                organ_k, sex_k = key.split("_", 1)
                organ_k = organ_k.lower()
                sex_k = sex_k.lower()
                # Pick the most recent cache for this organ×sex (if
                # multiple gene_hashes linger — shouldn't happen after
                # the cleanup in generate_genomics_narrative_async, but
                # be defensive).  The prefix is built by the shared helper
                # so this reload path can't drift from the writer's naming.
                from genomics.genomics_narratives import interpretation_cache_prefix
                prefix = interpretation_cache_prefix(organ_k, sex_k)
                latest = latest_session_cache(d, f"{prefix}*.json")
                if latest is None:
                    continue
                interp = read_json_file(latest)
                per_organ_bundles.setdefault(organ_k, {})[sex_k] = {
                    "gs": interp.get("gene_set_narrative") or [],
                    "gn": interp.get("gene_narrative") or [],
                }

            # --- User override tier ---
            _overrides = read_narrative_overrides(d)

            from genomics.genomics_narratives import aggregate_organ_llm_narratives
            llm_gs, llm_gn = aggregate_organ_llm_narratives(
                per_organ_bundles, overrides=_overrides,
            )

            # Attach to the narrative dicts — same shape as what
            # process-integrated produces in Layer 3.5.
            if gene_set_narrative is not None:
                gene_set_narrative["by_organ_llm"] = llm_gs
            if gene_narrative is not None:
                gene_narrative["by_organ_llm"] = llm_gn
    except Exception:
        # Non-fatal for the session load — the client falls back to empty and
        # the user can re-run process-integrated; the PDF export assembles the
        # narratives on its own.  Logged: a failure here is a bug or a broken
        # cache, not an expected state.
        logger.exception("Session load %s: genomics narratives not assembled", dtxsid)

    # Load cached validation report and precedence decisions if they exist.
    # These are generated by POST /api/pool/validate/{dtxsid} and
    # POST /api/pool/resolve respectively, and persisted to disk so
    # they survive page reloads without re-running validation.
    validation_report = _read_json("validation_report.json")
    precedence = _read_json("precedence.json")

    # Singleton report-section reads, DERIVED from the section catalog: each
    # singleton spec's store file (e.g. background.json) becomes a payload field
    # keyed by its section_key (background, methods, bmd_summary, summary). Adding
    # a singleton section to the template adds its payload field here — no literal
    # to keep in step. Instance families (bm2_/genomics_) are assembled separately
    # into their keyed maps above.
    from workflow.section_catalog import singleton_section_files
    singleton_sections = {
        store[:-len(".json")]: _read_json(store)
        for store in singleton_section_files()
    }

    # Group narratives (animal_condition / clinical_pathology / internal_dose) are
    # PROGRAMMATIC prose overlays that live only in the process cache's
    # `unified_narratives` blob — they are never persisted as standalone section
    # files. The Sections screen reads each row's content as session[key], so
    # without this projection those rows read "not generated" even though the prose
    # exists and renders in the report. `load_group_narratives` is the SHARED accessor
    # (also used by the render/export path) that reads the cache and applies the
    # process→tree key crosswalk, so the two paths cannot drift.
    group_narratives: dict = {}
    try:
        from rendering.report_data_overlays import load_group_narratives
        group_narratives = load_group_narratives(d)
    except Exception:
        # Best-effort — an unreadable cache leaves the rows as "not generated"
        # and never fails the whole session load; logged, as it is not expected.
        logger.exception("Session load %s: group narratives not read", dtxsid)

    # Front-matter section STATUS for the Sections screen. The 7 authored/boilerplate
    # front-matter sections (foreword, authors, contributors, peer_review,
    # publication_details, acknowledgments, abstract) are display-only workflow rows; the screen needs their
    # filled-vs-pending status without rendering the whole report. Resolve it from the
    # two per-session variables: front_matter.json (authors/contributors) and
    # whether processing produced abstract content (a background abstract sentence or a
    # bmd summary). Boilerplate sections are always present. Keyed by data_key so the
    # UI's session[key] read finds each row's content, same as the group narratives.
    front_matter_status: dict = {}
    try:
        from rendering.front_matter import resolve_front_matter_status
        _fm = _read_json("front_matter.json") or {}
        # Reuse the catalog-derived singleton read (no second parse of
        # background.json, no double-counted disk_read provenance event).
        _bg = singleton_sections.get("background") or {}
        _abstract_filled = bool(
            (_bg.get("abstract_background") or "").strip()
            or any(d.glob("_cache_bmd_summary_*.json"))
        )
        _fm_status = resolve_front_matter_status(_fm, abstract_filled=_abstract_filled)
        # Shape each as a SectionData-like dict so the UI's paragraphCount +
        # generated/pending state derive the same way as any other row.
        for _k, _st in _fm_status.items():
            front_matter_status[_k] = {
                "paragraphs": [""] * _st["paragraphs"],
                "has_content": _st["has_content"],
            }
    except Exception:
        logger.exception("Session load %s: front-matter status not resolved", dtxsid)

    return JSONResponse({
        "exists": True,
        "meta": _read_json("meta.json"),
        "identity": _read_json("identity.json"),
        **singleton_sections,
        # Programmatic group narratives from the process cache (see above), keyed
        # by tree narrative_key so the Sections screen's session[key] read finds
        # them. Absent when the session hasn't been processed yet.
        **group_narratives,
        # Front-matter section status (foreword/authors/contributors/…); display-only rows.
        **front_matter_status,
        "bm2_sections": bm2_sections,
        "pending_files": pending_files,
        "animal_report": _read_json("animal_report.json"),
        "genomics_sections": genomics_sections,
        # Unapproved fallback: when no `genomics_*.json` approved files
        # exist but `_cache_genomics_*.json` does, surface the raw
        # organ_sex dict so the client can restore the gene-set +
        # gene-bmd panels without requiring approval or a fresh
        # process-integrated call.  Bug C in the 2026-04-24 HTML/PDF
        # alignment pass — page reloads were showing empty tables
        # because the approval path was the only route to populate
        # genomicsResults on the client.
        "genomics_cache": (
            genomics_cache if genomics_cache and not genomics_sections
            else None
        ),
        "gene_set_narrative": gene_set_narrative,
        "gene_narrative": gene_narrative,
        "chart_images": chart_images,
        # background/methods/bmd_summary/summary are spread in above from
        # singleton_sections (catalog-derived) — not repeated here.
        "validation_report": validation_report,
        "precedence": precedence,
    })


# ---------------------------------------------------------------------------
# POST /api/session/{dtxsid}/genomics-narrative-override
# ---------------------------------------------------------------------------
# Persists a user-edited LLM narrative for one organ × kind pair.
# Written by the Lock/Unlock flow in web/js/genomics.js when the user
# locks an edited paragraph block.  The override file merges over the
# cached LLM tier on subsequent session loads and process-integrated
# runs, so the user's edit survives regeneration.
#
# File shape at `sessions/{dtxsid}/genomics_narrative_overrides.json`:
#   {
#     "gene_set": {"liver": ["para1", "para2"], "kidney": [...]},
#     "gene_bmd": {"liver": [...], "kidney": [...]}
#   }
# Empty `paragraphs` on the request clears the override for that organ.
# ---------------------------------------------------------------------------

def _genomics_sexes(session_dir, organ: str) -> list[str]:
    """The sexes the Process genomics cache has for an organ (its keys are
    "<organ>_<sex>"), sorted; [] when there is no cache."""
    path = latest_session_cache(session_dir, "_cache_genomics_*.json")
    cache = read_json_file(path) if path else None
    if not isinstance(cache, dict):
        return []
    return sorted({k.split("_", 1)[1].lower() for k in cache
                   if "_" in k and k.split("_", 1)[0].lower() == organ.lower()})


@router.post("/api/session/{dtxsid}/genomics-narrative-override")
async def api_genomics_narrative_override(dtxsid: Dtxsid, request: Request):
    """
    Save (or clear) a user's edit to a genomics LLM narrative block.

    Input JSON:
      {
        "kind": "gene_set" | "gene_bmd",
        "organ": "liver",
        "paragraphs": ["edited paragraph 1", "edited paragraph 2"]
      }

    Returns {"saved": true}.  An empty `paragraphs` array clears the
    override for that organ (LLM output wins again on next render).
    """
    body = await request.json()
    kind = body.get("kind", "")
    organ = (body.get("organ") or "").lower()
    paragraphs = body.get("paragraphs") or []

    if kind not in ("gene_set", "gene_bmd"):
        return JSONResponse(
            {"error": f"Invalid kind: {kind}"}, status_code=400,
        )
    if not organ:
        return JSONResponse(
            {"error": "organ is required"}, status_code=400,
        )

    session_dir = SESSIONS_DIR / validate_dtxsid(dtxsid)
    if not session_dir.exists():
        return JSONResponse(
            {"error": f"Session {dtxsid} not found"}, status_code=404,
        )

    overrides_path = session_dir / NARRATIVE_OVERRIDES_FILE
    # Read-modify-write.  No locking because this is a single-user app and
    # override edits happen on explicit user action (Lock click).  An
    # unreadable store raises (422) instead of being replaced by this one edit.
    existing = read_narrative_overrides(session_dir)

    # C2 §4.12: the person's text this write replaces is archived first (to
    # history/genomics_<organ>/), so a later override or a regenerate never
    # loses it.
    from workflow.section_writes import archive_genomics_overrides
    archive_genomics_overrides(dtxsid, organ, existing, act="save", actor="person",
                               reason=None, sexes=_genomics_sexes(session_dir, organ))

    if paragraphs:
        existing[kind][organ] = [str(p) for p in paragraphs]
    else:
        existing[kind].pop(organ, None)

    overrides_path.write_text(json.dumps(existing, indent=2))
    return JSONResponse({"saved": True})


# ---------------------------------------------------------------------------
# POST /api/session/approve — approve (save) a report section
# ---------------------------------------------------------------------------

@router.post("/api/session/approve")
async def api_session_approve(request: Request):
    """
    Approve (accept) a report section as it is on disk. FENCED (C2 D5).

    Approving no longer saves text: the application is not an editor
    (ADR-0018), and a person's text comes back from Word or Overleaf. So:
      * the section file exists and the posted `data` is the same content →
        accept_section_step (a state change; the text is not touched);
      * the posted content differs → 409 ``approve_content_retired``;
      * no section file → 404 ``section_not_found``.
    It no longer writes identity.json or meta.json (C3 owns the identity).

    Input JSON: {"dtxsid", "section_type", "bm2_slug"? | "organ"/"sex"?, "data"}
    Returns {"ok", "section_type", "user_edited", "version"} (+ "noop").
    """
    from workflow.section_catalog import approvable_section_types
    from workflow.errors import StepError
    from workflow.ownership import content_hash
    from safeguards.guarded import accept_section_step
    from workflow.store import DiskPoolStore

    body = await request.json()
    dtxsid = body.get("dtxsid", "")
    section_type = body.get("section_type", "")
    data = body.get("data") or {}

    if not dtxsid:
        return JSONResponse({"error": "dtxsid is required"}, status_code=400)
    valid = approvable_section_types()
    if section_type not in valid:
        return JSONResponse(
            {"error": f"section_type must be one of: {', '.join(sorted(valid))}"},
            status_code=400,
        )
    section_key, err = _approve_section_key(body, data)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    validate_dtxsid(dtxsid)
    current_path = SESSIONS_DIR / dtxsid / f"{section_key}.json"
    current = read_json_file(current_path) if current_path.exists() else None
    if not isinstance(current, dict):
        return JSONResponse({"error": f"No '{section_key}' section to approve",
                             "code": "section_not_found"}, status_code=404)
    # The client re-sends the content it loaded (with the approval and
    # bookkeeping fields it carries): compare content only, and only the fields
    # the client sent, so a client that leaves out a field it never shows is not
    # "changing" it. original_* is the client's note of the generated text.
    sent = {k: v for k, v in data.items() if not k.startswith("original_")}
    if content_hash(sent) != content_hash({k: current.get(k) for k in sent}):
        return JSONResponse({
            "error": (f"Approving no longer saves text; accept '{section_key}' as it is, or "
                      "change it outside the application and bring the new version in"),
            "code": "approve_content_retired"}, status_code=409)

    try:
        result = accept_section_step(dtxsid, section_key, DiskPoolStore())
    except StepError as e:
        return _step_refusal(e)
    out = {"ok": True, "section_type": section_type, "user_edited": False,
           "version": result.get("version", 1)}
    if result.get("noop"):
        out["noop"] = result["noop"]
    return JSONResponse(out)


def _approve_section_key(body: dict, data: dict) -> tuple[str | None, str | None]:
    """The section key an approve body names: the catalog's resolver, with the
    two older spellings the approve body allowed (a bm2 section named by its
    .bm2 file name; a genomics section's organ/sex inside `data`)."""
    from workflow.section_catalog import resolve_section_key
    section_type = body.get("section_type", "")
    if section_type == "bm2" and not body.get("bm2_slug"):
        filename = data.get("filename", "")
        if not (filename and bm2_slug(filename)):
            return None, "bm2 sections need bm2_slug (or data.filename)"
        body = {**body, "bm2_slug": bm2_slug(filename)}
    if section_type == "genomics" and not (body.get("organ") and body.get("sex")):
        body = {**body, "organ": data.get("organ", ""), "sex": data.get("sex", "")}
    return resolve_section_key(body)


# ---------------------------------------------------------------------------
# Section key resolver — shared by save / unapprove / delete endpoints
# ---------------------------------------------------------------------------

def _resolve_section_key(body: dict) -> tuple[str | None, str | None]:
    """
    Map a request body's (section_type, plus optional bm2_slug or organ/sex)
    onto the on-disk filename used by save_section / load_section.

    Returns (section_key, error_message).  Exactly one of the two will be
    None: the caller dispatches accordingly.

    Delegates to the tree-driven section catalog so the section vocabulary
    (which types are valid, how bm2/genomics keys are built) lives in ONE place
    (workflow.section_catalog) instead of being re-implemented here.
    """
    from workflow.section_catalog import resolve_section_key
    return resolve_section_key(body)  # memoized allowlist inside


# ---------------------------------------------------------------------------
# POST /api/session/{dtxsid}/models — persist per-concern model selections
# ---------------------------------------------------------------------------

# Valid model-selection concerns.  Each maps to a group of LLM generation
# routes (Background; Methods + Summary; Analysis = genomics narrative).
_MODEL_CONCERNS = ("background", "methods_summary", "analysis")


@router.post("/api/session/{dtxsid}/models")
async def api_session_models(dtxsid: Dtxsid, request: Request):
    """
    Persist the user's per-concern model selections into meta.json.

    The Models modal lets the user pick a model for each generation concern.
    The picks travel with the report so a reload (or another machine reading
    the same session bucket) restores them.  They are merged under a "models"
    key in meta.json, leaving timestamps and identity fields intact.

    Input JSON: {"background": "...", "methods_summary": "...", "analysis": "..."}
      Any subset of the three keys may be present; unknown keys are ignored.

    Returns: {"ok": True, "models": {...the merged selections...}}
    """
    if not dtxsid:
        return JSONResponse({"error": "dtxsid is required"}, status_code=400)

    body = await request.json()
    selections = {
        k: str(body[k]) for k in _MODEL_CONCERNS
        if isinstance(body.get(k), str) and body[k]
    }

    d = session_dir(dtxsid)
    meta_path = d / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = {"dtxsid": dtxsid, "created_at": now_iso()}
    meta.setdefault("models", {}).update(selections)
    meta["updated_at"] = now_iso()
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return JSONResponse({"ok": True, "models": meta["models"]})


# ---------------------------------------------------------------------------
# POST /api/session/save-section — auto-save without changing approval
# ---------------------------------------------------------------------------

@router.post("/api/session/save-section")
async def api_session_save_section(request: Request):
    """
    Save a section's text WITHOUT approving it (an auto-save of freshly
    generated text), through the section write gate (C2 §4.6):
      * the section is owned (approved, released with PROTECTED, edited) →
        409 ``section_owned``; release it first, with a reason;
      * `approved: true` in the body → 400 ``approve_via_accept`` (saving
        never approves; accept does);
      * otherwise the prior text is archived, the new one written, and a
        version event recorded; unchanged text writes nothing.

    Input JSON:
      {
        "dtxsid": "DTXSID...",
        "section_type": "background" | "methods" | ...,
        "data": {...},        // the section payload (paragraphs, references, etc.)
        "bm2_slug": "...",    // required for bm2 sections
        "organ": "...",       // required for genomics sections
        "sex": "..."          // required for genomics sections
      }

    Kept for the old interface (C2 D5); the new interface never calls it.
    Returns {"ok": true, "version": n}.
    """
    from workflow.errors import StepError
    from safeguards.guarded import write_section
    from workflow.store import DiskPoolStore

    body = await request.json()
    dtxsid = body.get("dtxsid", "")
    if not dtxsid:
        return JSONResponse({"error": "dtxsid is required"}, status_code=400)

    section_key, err = _resolve_section_key(body)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    if body.get("approved") or (body.get("data") or {}).get("approved"):
        return JSONResponse({"error": "save-section cannot approve a section; use accept",
                             "code": "approve_via_accept"}, status_code=400)

    data = dict(body.get("data") or {})
    data["approved"] = False
    data.setdefault("saved_at", now_iso())
    author = data.get("source") if data.get("source") in ("generated", "model") else "client"
    try:
        out = write_section(validate_dtxsid(dtxsid), section_key, data, DiskPoolStore(),
                            act="save", actor="person", author=author)
    except StepError as e:
        return _step_refusal(e)
    return JSONResponse({"ok": True, "version": out["version"]})


# ---------------------------------------------------------------------------
# POST /api/session/unapprove — flip approved=False (does NOT delete data)
# ---------------------------------------------------------------------------

@router.post("/api/session/unapprove")
async def api_session_unapprove(request: Request):
    """
    REVISE (reopen) an approved section, preserving its content:
    workflow.steps.release_section_step (C2 §4.4). FINAL is withdrawn,
    PROTECTED stands, and the reason — now required (C2 D3) — is kept on the
    version trail.

    Input JSON:
      {
        "dtxsid": "DTXSID...",
        "section_type": "background" | "bm2" | "methods" | ...,
        "reason": "why the person is reopening it",   // required
        "bm2_slug": "...",  // required for bm2
        "organ": "...",     // required for genomics
        "sex": "..."        // required for genomics
      }

    Refusals: 404 ``section_not_found`` (no such section), 400
    ``reason_required``. A section that is not approved answers ok with
    ``noop not_approved``.
    """
    from workflow.errors import StepError
    from safeguards.guarded import release_section_step
    from workflow.store import DiskPoolStore

    body = await request.json()
    dtxsid = body.get("dtxsid", "")
    if not dtxsid:
        return JSONResponse({"error": "dtxsid is required"}, status_code=400)

    section_key, err = _resolve_section_key(body)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    try:
        result = release_section_step(validate_dtxsid(dtxsid), section_key, DiskPoolStore(),
                                      reason=str(body.get("reason") or ""))
    except StepError as e:
        return _step_refusal(e)
    out = {"ok": True, "version": result.get("version")}
    if result.get("noop"):
        out["noop"] = result["noop"]
    return JSONResponse(out)


# ---------------------------------------------------------------------------
# POST /api/session/discard-section — delete a section's content from disk
# ---------------------------------------------------------------------------

@router.post("/api/session/discard-section")
async def api_session_discard_section(request: Request):
    """
    Discard a section's text: workflow.steps.discard_section_step (C2 §4.7).
    The file is archived first, then deleted, and the discard recorded, so
    restore can still bring it back. An approved section is released first
    (409 ``section_owned``); the reason is required (400 ``reason_required``).

    Input JSON: same shape as save-section, plus "reason".
    Kept for the old interface (C2 D4); the new interface never calls it.
    """
    from workflow.errors import StepError
    from safeguards.guarded import discard_section_step
    from workflow.store import DiskPoolStore

    body = await request.json()
    dtxsid = body.get("dtxsid", "")
    if not dtxsid:
        return JSONResponse({"error": "dtxsid is required"}, status_code=400)

    section_key, err = _resolve_section_key(body)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    try:
        result = discard_section_step(validate_dtxsid(dtxsid), section_key, DiskPoolStore(),
                                      reason=str(body.get("reason") or ""))
    except StepError as e:
        return _step_refusal(e)
    return JSONResponse({"ok": True, "archived": result["archived"],
                         "version": result["version"]})


# ---------------------------------------------------------------------------
# GET /api/session/{dtxsid}/history/{section_key} — version history for a section
# ---------------------------------------------------------------------------

@router.get("/api/session/{dtxsid}/history/{section_key}")
async def api_session_history(dtxsid: Dtxsid, section_key: str, version: int = 0):
    """
    Return version history for a section, through
    workflow.section_writes.section_history (C2): the key is validated, it
    works after a discard, and it lists every version whose text is kept.

    URL pattern:
        GET /api/session/{dtxsid}/history/{section_key}           → version list
        GET /api/session/{dtxsid}/history/{section_key}?version=1 → full content

    Response (list mode; unchanged shape):
    {
      "section_key": "background",
      "current_version": 3,              // null after a discard
      "versions": [
        {"version": 1, "approved_at": "…", "is_current": false},
        {"version": 3, "approved_at": "…", "is_current": true}
      ]
    }
    """
    from workflow import section_writes as sw
    from workflow.errors import StepError
    from workflow.store import DiskPoolStore

    store = DiskPoolStore()
    try:
        if version > 0:
            return JSONResponse(sw.read_version(dtxsid, section_key, version, store))
        hist = sw.section_history(dtxsid, section_key, store)
    except StepError as e:
        return _step_refusal(e)
    return JSONResponse({
        "section_key": hist["section_key"],
        "current_version": hist["current_version"],
        "versions": [{"version": v["version"], "approved_at": v.get("approved_at") or "",
                      "is_current": v["current"]}
                     for v in hist["versions"] if v["retrievable"]],
    })


# ---------------------------------------------------------------------------
# POST /api/session/{dtxsid}/restore — restore a past version as current
# ---------------------------------------------------------------------------

@router.post("/api/session/{dtxsid}/restore")
async def api_session_restore(dtxsid: Dtxsid, request: Request):
    """
    Restore a past version of a section as the new current one:
    workflow.steps.restore_section_step (C2 §4.8). The key is validated, it
    works after a discard, the current text is archived first, and the
    restored version comes back as a draft a person owns: not approved,
    protected from the machine (C2 D3; accepting it is a separate act). The
    reason is required.

    Input JSON: {"section_key": "background", "version": 1, "reason": "…"}
    Returns {"ok", "version", "section_key", "from_version"}; restoring the
    current version answers ok with "message": "Already the current version".
    """
    from workflow.errors import StepError
    from safeguards.guarded import restore_section_step
    from workflow.store import DiskPoolStore

    try:
        body = await request.json()
    except Exception:
        body = {}
    section_key = body.get("section_key", "")
    target_version = body.get("version", 0)
    if not section_key or not target_version:
        return JSONResponse(
            {"error": "section_key and version are required"}, status_code=400,
        )
    try:
        result = restore_section_step(dtxsid, section_key, target_version, DiskPoolStore(),
                                      reason=str(body.get("reason") or ""))
    except StepError as e:
        return _step_refusal(e)
    if result.get("noop"):
        return JSONResponse({"ok": True, "message": "Already the current version",
                             "version": target_version, "noop": result["noop"]})
    return JSONResponse({"ok": True, "version": result["version"],
                         "section_key": section_key, "from_version": target_version})


# ---------------------------------------------------------------------------
# GET /api/experiment-metadata/{dtxsid} — retrieve experiment metadata
# ---------------------------------------------------------------------------

@router.get("/api/experiment-metadata/{dtxsid}")
async def api_get_experiment_metadata(dtxsid: Dtxsid):
    """
    Return experiment metadata for all experiments in the integrated data.

    Reads integrated.json and extracts experimentDescription from each
    DoseResponseExperiment.  Also returns the controlled vocabularies so
    the frontend can build dropdown menus.

    Returns:
      {
        "experiments": [
          {
            "name": "BodyWeightFemale",
            "probe_count": 2,
            "experimentDescription": { "species": "rat", "sex": "female", ... }
          },
          ...
        ],
        "vocabularies": { "species": [...], "sex": [...], ... },
        "approved": true/false
      }
    """
    # Route through the schema-validating loader (ADR-0001).  Returns
    # None when no integrated.json exists for this session; raises
    # BMDProjectValidationError if the file is on disk but malformed
    # (handled globally in background_server.py → 422).
    integrated = load_integrated(dtxsid)
    if integrated is None:
        return JSONResponse(
            {"error": "No integrated data found"}, status_code=404,
        )

    # sess_path is still needed below for sibling artifacts (e.g.
    # metadata_approved.json).  load_integrated() doesn't surface it.
    sess_path = session_dir(dtxsid)

    # Extract experiment summaries with their metadata
    experiments = []
    for exp in integrated.get("doseResponseExperiments", []):
        ed = exp.get("experimentDescription", {})
        # Strip computed fields that Jackson serialized — they're derived
        # from the stored fields and would just clutter the form.
        for key in ("columnHeaders", "columnValues", "experimentType",
                     "formattedString", "inVivo", "inVitro", "statusBarString"):
            ed.pop(key, None)

        # Extract probe IDs for this experiment — used by the frontend to
        # build organ selection modals for organ weight experiments.
        probe_ids = []
        for pr in exp.get("probeResponses", []):
            pid = pr.get("probe", {}).get("id", "") or pr.get("name", "")
            if pid:
                probe_ids.append(pid)

        experiments.append({
            "name": exp.get("name", ""),
            "probe_count": len(exp.get("probeResponses", [])),
            "experimentDescription": ed,
            "probe_ids": probe_ids,
        })

    # Check if metadata was already approved
    meta_approved_path = sess_path / "metadata_approved.json"
    approved = meta_approved_path.exists()

    # Controlled vocabularies — same as experiment_metadata.py VOCABULARIES
    from bmdx_pipe import VOCABULARIES

    return JSONResponse({
        "experiments": experiments,
        "vocabularies": VOCABULARIES,
        "approved": approved,
    })


# ---------------------------------------------------------------------------
# POST /api/experiment-metadata/{dtxsid} — save user-edited metadata
# ---------------------------------------------------------------------------

@router.post("/api/experiment-metadata/{dtxsid}")
async def api_save_experiment_metadata(dtxsid: Dtxsid, request: Request):
    """
    Save user-edited experiment metadata back to integrated.json.

    The request body contains the edited metadata for each experiment,
    keyed by experiment name:
      {
        "metadata": {
          "BodyWeightFemale": { "species": "rat", "sex": "female", ... },
          "OrganWeightMale": { "species": "rat", "sex": "male", ... },
          ...
        }
      }

    Updates each experiment's experimentDescription in integrated.json,
    then re-exports integrated.bm2 so the .bm2 file reflects the
    user-approved metadata.

    Also writes metadata_approved.json: the approval marker the UI reads,
    and the approved descriptions themselves — integration re-infers
    metadata from experiment names, and re-applies these over it
    (workflow.steps.integrate_step), so a re-integration keeps them.  The
    genomics sidecar's organ/sex are reconciled with the approved metadata
    here, so the next process run reports the approved organ.
    """
    body = await request.json()
    metadata_by_name = body.get("metadata", {})

    if not metadata_by_name:
        return JSONResponse(
            {"error": "No metadata provided"}, status_code=400,
        )

    # pipeline.metadata_approval: onto integrated.json (schema-validated —
    # a malformed description → 422 globally, disk untouched), the genomics
    # sidecar reconciled, .bm2 re-exported, metadata_approved.json written.
    from safeguards.guarded import approve_experiment_metadata
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, approve_experiment_metadata, dtxsid, metadata_by_name)
    except LookupError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except StepError as e:  # the safeguards (R6, C1)
        return _step_refusal(e)
    updated_count, bm2_ok = result["updated"], result["bm2_exported"]

    return JSONResponse({
        "ok": True,
        "updated": updated_count,
        "bm2_exported": bm2_ok,
    })


# ---------------------------------------------------------------------------
# POST /api/pool/reset/{dtxsid} — full pool reset (destructive)
# ---------------------------------------------------------------------------

@router.delete("/api/pool/{dtxsid}/files/{filename}")
async def api_pool_remove_file(dtxsid: Dtxsid, filename: str):
    """Remove ONE file (plus its sidecar/original companions) from the pool.

    Reversible on disk: files move to sessions/<dtxsid>/_removed/<timestamp>/.
    Invalidates validation/integration when the pool had progressed past upload.
    400 for an invalid name, a sidecar, or a file not in the pool."""
    from pipeline.pool_state import PoolFileError
    from safeguards.guarded import remove_pool_file
    if not (SESSIONS_DIR / validate_dtxsid(dtxsid)).exists():
        return JSONResponse({"error": f"No session found for {dtxsid}"}, status_code=404)
    try:
        result = remove_pool_file(dtxsid, filename)
    except PoolFileError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except StepError as e:  # the safeguards (R6, C1)
        return _step_refusal(e)
    return JSONResponse({"ok": True, **result})


@router.post("/api/pool/reset/{dtxsid}")
async def api_pool_reset(dtxsid: Dtxsid):
    """
    Completely reset the data pool for a given DTXSID.

    This is a destructive operation — it deletes:
      - files/           (all uploaded .bm2, .csv, .txt, .xlsx files)
      - integrated.json  (merged BMDProject from pool integration)
      - integrated.bm2   (binary export of integrated data)
      - metadata_approved.json  (experiment metadata approval marker)
      - All bm2_*.json   (approved apical endpoint sections)
      - All genomics_*.json (approved genomics sections)
      - methods.json, bmd_summary.json, summary.json (approved report sections)
      - validation_report.json, precedence.json (validation artifacts)
      - animal_report.json (cached animal report)

    Also clears the in-memory server-side state:
      - _bm2_uploads entries pointing to this session's files
      - _csv_uploads entries pointing to this session's files
      - _pool_fingerprints[dtxsid]
      - _integrated_pool[dtxsid]
      - _data_uploads entries for this session's files

    Also deletes everything derived from the pool: the fingerprint cache, all
    processing caches, the genomics sidecar, session.duckdb / session_parquet,
    rendered previews, converted-file originals (_originals/) and the
    per-file-removal holding area (_removed/).

    Every section file is archived to history/ before it is deleted, with a
    `discard` event (act "pool_reset"), so it can be restored (C2).

    Does NOT delete:
      - meta.json, identity.json (chemical identity — still valid)
      - history/ (version history of approved sections — archival)
      - views/ (report view configuration), references.json, background.json,
        .provenance.jsonl (audit log)

    The user is warned on the client side before this endpoint is called.
    After reset, the session directory still exists but is effectively empty
    (just meta.json and identity.json), ready for fresh uploads.
    """
    _bm2_uploads = get_bm2_uploads()
    _csv_uploads = get_csv_uploads()
    _pool_fingerprints = get_pool_fingerprints()
    _data_uploads = get_data_uploads()
    _integrated_pool = get_integrated_pool()

    d = SESSIONS_DIR / validate_dtxsid(dtxsid)
    if not d.exists():
        return JSONResponse(
            {"error": f"No session found for {dtxsid}"},
            status_code=404,
        )
    # The safeguards (R6, C1): no reset of a companion or a report, nor of a
    # study with no files.
    from safeguards.guarded import require_reset
    try:
        require_reset(dtxsid)
    except StepError as e:
        return _step_refusal(e)

    deleted_items = []

    # 1. Delete files/ directory (all uploaded raw data)
    files_dir = d / "files"
    if files_dir.exists():
        shutil.rmtree(files_dir)
        deleted_items.append("files/")

    # 2. Delete integration artifacts and everything DERIVED from the pool.
    #    _fingerprints.json matters most: it is a filename-keyed cache that
    #    session restore reuses, so leaving it would resurrect a deleted file's
    #    classification for a different file later uploaded under the same name.
    for artifact in ("integrated.json", "integrated.bm2",
                     "metadata_approved.json", "validation_report.json",
                     "precedence.json", "animal_report.json",
                     "integration_basis.json",
                     "_fingerprints.json", "_category_lookup.json",
                     "genomics.sidecar.json", "session.duckdb",
                     ".session_db.fingerprint", ".prepare_content.fingerprint",
                     ".prepare_content.outputs.json"):
        p = d / artifact
        if p.exists():
            p.unlink()
            deleted_items.append(artifact)
    for cache_file in d.glob("_cache_*.json"):
        cache_file.unlink()
        deleted_items.append(cache_file.name)
    #    Converted-file originals, per-file-removal holding area, the session's
    #    parquet export and rendered previews — all derived from the old pool.
    for sub in ("_originals", "_removed", "session_parquet", "preview"):
        p = d / sub
        if p.is_dir():
            shutil.rmtree(p)
            deleted_items.append(f"{sub}/")

    # 3. Delete the section files derived from the pool (bm2_*, genomics_*,
    #    methods, …). Each is archived first and its discard recorded (C2
    #    §4.15), so a reset section can be restored.
    from workflow.section_writes import discard as _discard_section
    from workflow.store import DiskPoolStore
    _store = DiskPoolStore()

    def _reset_section(stem: str) -> None:
        _discard_section(dtxsid, stem, _store, act="pool_reset", actor="person",
                         reason="pool reset")
        deleted_items.append(f"{stem}.json")

    for pattern in ("bm2_*.json", "genomics_*.json"):
        for f in sorted(d.glob(pattern)):
            _reset_section(f.stem)

    # Singleton report sections derived from the DATA pool. Enumerated from the
    # section catalog (rather than a hand-kept literal) but with background.json
    # EXCLUDED on purpose: Background is generated from the chemical IDENTITY,
    # which survives a pool reset (identity.json/meta.json are preserved below),
    # so wiping it here would discard authored work a reset must not touch.
    from workflow.section_catalog import singleton_section_files
    for section_file in singleton_section_files():
        if section_file == "background.json":
            continue
        if (d / section_file).exists():
            _reset_section(section_file[:-5])

    # 4. Clear in-memory server state for this DTXSID.
    #    Remove bm2/csv/data upload entries whose temp_path pointed into
    #    this session's files/ directory (now deleted).  Also remove any
    #    entries whose temp files no longer exist on disk (stale uploads).
    session_files_prefix = str(files_dir)
    for store in (_bm2_uploads, _csv_uploads, _data_uploads):
        stale_ids = [
            fid for fid, info in store.items()
            if info.get("temp_path", "").startswith(session_files_prefix)
            or not os.path.exists(info.get("temp_path", ""))
        ]
        for fid in stale_ids:
            del store[fid]

    # Clear pool fingerprints and integrated pool for this chemical
    _pool_fingerprints.pop(dtxsid, None)
    _integrated_pool.pop(dtxsid, None)

    logger.info(
        "Pool reset for %s: deleted %d items: %s",
        dtxsid, len(deleted_items), ", ".join(deleted_items),
    )

    return JSONResponse({
        "ok": True,
        "deleted": deleted_items,
    })


# ---------------------------------------------------------------------------
# POST /api/session/reset/{dtxsid} — full session reset (nuclear option)
# ---------------------------------------------------------------------------

@router.post("/api/session/reset/{dtxsid}")
async def api_session_reset(dtxsid: Dtxsid):
    """
    Completely delete the entire session for a given DTXSID.

    Unlike pool reset (which preserves identity and history), this removes
    EVERYTHING: the entire sessions/{dtxsid}/ directory including meta.json,
    identity.json, background.json, history/, files/, and all approved sections.

    Also clears all in-memory server state for this chemical (same as pool reset).

    After this, the chemical identity form is still filled (from localStorage)
    but the server has no record of any prior work.  The user starts completely
    from scratch.  A published book's companion and a study a report composes
    are refused (safeguards.acts.require_deletable); a report session may go,
    its studies stay.
    """
    _bm2_uploads = get_bm2_uploads()
    _csv_uploads = get_csv_uploads()
    _pool_fingerprints = get_pool_fingerprints()
    _data_uploads = get_data_uploads()
    _integrated_pool = get_integrated_pool()

    d = SESSIONS_DIR / validate_dtxsid(dtxsid)
    if not d.exists():
        return JSONResponse({"ok": True, "message": "No session to reset"})
    # Not a companion, not a study a report composes (safeguards.acts).
    from safeguards.acts import require_deletable
    try:
        require_deletable(dtxsid)
    except StepError as e:
        return _step_refusal(e)

    # Delete the entire session directory tree
    shutil.rmtree(d)

    # Clear in-memory server state (same cleanup as pool reset)
    session_files_prefix = str(d / "files")
    for store in (_bm2_uploads, _csv_uploads, _data_uploads):
        stale_ids = [
            fid for fid, info in store.items()
            if info.get("temp_path", "").startswith(session_files_prefix)
            or not os.path.exists(info.get("temp_path", ""))
        ]
        for fid in stale_ids:
            del store[fid]

    _pool_fingerprints.pop(dtxsid, None)
    _integrated_pool.pop(dtxsid, None)

    logger.info("Full session reset for %s — directory deleted", dtxsid)

    return JSONResponse({"ok": True})
