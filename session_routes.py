"""
session_routes.py — Session persistence and history API endpoints.

Extracted from background_server.py.  These endpoints manage the on-disk
session state: loading saved sessions, approving/unapproving report sections,
browsing version history, restoring past versions, and computing the
apical endpoint BMD summary from approved .bm2 data.

All endpoints are mounted as a FastAPI APIRouter on the /api prefix.

Endpoints:
  GET  /api/session/{dtxsid}                        — Load a saved session
  POST /api/session/approve                         — Approve (save) a section
  POST /api/session/unapprove                       — Unapprove (delete) a section
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
import os
import shutil
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from bmdx_pipe import bm2_cache
from session_store import (
    SESSIONS_DIR, now_iso, session_dir, bm2_slug, safe_filename,
    save_section, delete_section,
)
from style_learning import (
    load_style_profile, extract_and_merge_style_rules,
)
from pool_orchestrator import (
    fingerprint_and_store, run_lightweight_validation, _js_dose_key,
    load_cached_fingerprint, restore_fingerprint,
)
from server_state import (
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


# ---------------------------------------------------------------------------
# GET /api/session/{dtxsid}/bmd-summary — auto-derive apical endpoint BMD summary
# ---------------------------------------------------------------------------

@router.get("/api/session/{dtxsid}/bmd-summary")
async def api_bmd_summary(dtxsid: str):
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
    d = SESSIONS_DIR / dtxsid
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
async def api_session_load(dtxsid: str):
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
    _bm2_uploads = get_bm2_uploads()
    _data_uploads = get_data_uploads()

    d = SESSIONS_DIR / dtxsid
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

    # Helper: read a JSON file if it exists, else return None
    def _read_json(name: str):
        p = d / name
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
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
        section = json.loads(f.read_text(encoding="utf-8"))

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
        genomics_sections[slug] = json.loads(f.read_text(encoding="utf-8"))

    # Load the raw organ_sex-keyed genomics cache first — used by both
    # the narrative assembler and (Bug C fallback) by the client when
    # no approved `genomics_*.json` files exist for this session.
    genomics_cache = None
    genomics_cache_path = None
    try:
        for gc in sorted(d.glob("_cache_genomics_*.json")):
            genomics_cache = json.loads(gc.read_text(encoding="utf-8"))
            genomics_cache_path = gc
            break
    except Exception:
        pass

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
    chart_cache_path = None
    try:
        for cc in sorted(d.glob("_cache_charts_*.json")):
            chart_images = json.loads(cc.read_text(encoding="utf-8"))
            chart_cache_path = cc
            break
    except Exception:
        pass

    if chart_images and genomics_cache and chart_cache_path:
        try:
            from genomics_viz import (
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
                rerendered = render_chart_images_for_sections(
                    genomics_sections=genomics_cache,
                    bmd_stat=bmd_stat,
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
            for mc in sorted(d.glob("_cache_methods_*.json")):
                methods_payload = json.loads(mc.read_text(encoding="utf-8"))
                methods_ctx = methods_payload.get("context")
                break
            identity = _read_json("identity.json")
            if identity:
                chem_name = identity.get("name") or identity.get("chemical_name")

            from genomics_narratives import build_genomics_body_narratives
            narratives = build_genomics_body_narratives(
                genomics_sections=genomics_cache,
                methods_context=methods_ctx,
                chemical_name=chem_name or "the test article",
            )
            gene_set_narrative = narratives.get("gene_set_narrative")
            gene_narrative = narratives.get("gene_narrative")

            # --- LLM tier (by_organ_llm) from interpretation caches ---
            # Iterate the organ_sex keys, look up the latest
            # interpretation cache for each, and aggregate the
            # `gene_set_narrative` / `gene_narrative` paragraphs with
            # a leading sex label so male/female read naturally in
            # sequence under each organ.
            llm_gs: dict[str, list[str]] = {}
            llm_gn: dict[str, list[str]] = {}
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
                # be defensive).
                prefix = f"_cache_interpretation_{organ_k}_{sex_k}_"
                latest = None
                latest_mtime = -1.0
                for cf in d.glob(f"{prefix}*.json"):
                    try:
                        mt = cf.stat().st_mtime
                        if mt > latest_mtime:
                            latest_mtime = mt
                            latest = cf
                    except Exception:
                        continue
                if latest is None:
                    continue
                try:
                    interp = json.loads(latest.read_text(encoding="utf-8"))
                except Exception:
                    continue
                per_organ_bundles.setdefault(organ_k, {})[sex_k] = {
                    "gs": interp.get("gene_set_narrative") or [],
                    "gn": interp.get("gene_narrative") or [],
                }

            _sex_order = ("male", "female")
            for organ_k, by_sex in per_organ_bundles.items():
                gs_paras, gn_paras = [], []
                for sx in _sex_order:
                    blk = by_sex.get(sx)
                    if not blk:
                        continue
                    sex_label = sx.capitalize()
                    if blk["gs"]:
                        gs_paras.append(f"{sex_label}: " + blk["gs"][0])
                        gs_paras.extend(blk["gs"][1:])
                    if blk["gn"]:
                        gn_paras.append(f"{sex_label}: " + blk["gn"][0])
                        gn_paras.extend(blk["gn"][1:])
                if gs_paras:
                    llm_gs[organ_k] = gs_paras
                if gn_paras:
                    llm_gn[organ_k] = gn_paras

            # --- User override tier ---
            overrides_path = d / "genomics_narrative_overrides.json"
            if overrides_path.exists():
                try:
                    raw = json.loads(overrides_path.read_text())
                    for organ_k, paras in (raw.get("gene_set") or {}).items():
                        if paras:
                            llm_gs[organ_k.lower()] = paras
                    for organ_k, paras in (raw.get("gene_bmd") or {}).items():
                        if paras:
                            llm_gn[organ_k.lower()] = paras
                except Exception:
                    pass

            # Attach to the narrative dicts — same shape as what
            # process-integrated produces in Layer 3.5.
            if gene_set_narrative is not None:
                gene_set_narrative["by_organ_llm"] = llm_gs
            if gene_narrative is not None:
                gene_narrative["by_organ_llm"] = llm_gn
    except Exception:
        # Non-fatal — falls back to empty on the client.  The user can
        # re-run process-integrated to populate them; the PDF export
        # still auto-populates on its own.
        pass

    # Load cached validation report and precedence decisions if they exist.
    # These are generated by POST /api/pool/validate/{dtxsid} and
    # POST /api/pool/resolve respectively, and persisted to disk so
    # they survive page reloads without re-running validation.
    validation_report = _read_json("validation_report.json")
    precedence = _read_json("precedence.json")

    return JSONResponse({
        "exists": True,
        "meta": _read_json("meta.json"),
        "identity": _read_json("identity.json"),
        "background": _read_json("background.json"),
        "methods": _read_json("methods.json"),
        "bm2_sections": bm2_sections,
        "pending_files": pending_files,
        "animal_report": _read_json("animal_report.json"),
        "bmd_summary": _read_json("bmd_summary.json"),
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
        "summary": _read_json("summary.json"),
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

@router.post("/api/session/{dtxsid}/genomics-narrative-override")
async def api_genomics_narrative_override(dtxsid: str, request: Request):
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

    session_dir = SESSIONS_DIR / dtxsid
    if not session_dir.exists():
        return JSONResponse(
            {"error": f"Session {dtxsid} not found"}, status_code=404,
        )

    overrides_path = session_dir / "genomics_narrative_overrides.json"
    # Read-modify-write — defensive against partial writes by other
    # endpoints.  No locking because this is a single-user app and
    # override edits happen on explicit user action (Lock click).
    existing = {"gene_set": {}, "gene_bmd": {}}
    if overrides_path.exists():
        try:
            raw = json.loads(overrides_path.read_text(encoding="utf-8"))
            existing["gene_set"] = raw.get("gene_set", {}) or {}
            existing["gene_bmd"] = raw.get("gene_bmd", {}) or {}
        except Exception:
            pass

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
    Approve a report section and persist it to disk.

    Input JSON:
      {
        "dtxsid": "DTXSID6020430",
        "identity": {ChemicalIdentity dict},   // saved on first approve
        "section_type": "background" | "bm2" | "methods" | "bmd_summary"
                        | "genomics" | "summary",
        "data": {
          // For background: paragraphs, references, model_used, notes,
          //                 original_paragraphs, original_references
          // For bm2: filename, section_title, table_caption, compound_name,
          //          dose_unit, narrative, tables_json, original_narrative
          // For methods/summary: paragraphs, original_paragraphs
          // For bmd_summary: endpoints
          // For genomics: organ, sex, gene_sets, top_genes
        }
      }

    Saves the section data with an approved_at timestamp.  Also saves/updates
    identity.json and meta.json on every approve call.

    For bm2 sections, the .bm2 file is copied from /tmp to
    sessions/{dtxsid}/files/ so it survives server restarts.

    Style learning: if the user edited the generated text before approving,
    the original and edited versions are compared to extract writing style
    rules.  Extraction runs asynchronously in a background thread so the
    approve response is immediate.
    """
    _bm2_uploads = get_bm2_uploads()
    _csv_uploads = get_csv_uploads()

    # Valid section types — the original two plus the new NIEHS sections
    VALID_SECTION_TYPES = {
        "background", "bm2", "methods", "bmd_summary", "genomics", "summary",
    }

    body = await request.json()
    dtxsid = body.get("dtxsid", "")
    identity = body.get("identity")
    section_type = body.get("section_type", "")
    data = body.get("data", {})

    if not dtxsid:
        return JSONResponse({"error": "dtxsid is required"}, status_code=400)
    if section_type not in VALID_SECTION_TYPES:
        return JSONResponse(
            {"error": f"section_type must be one of: {', '.join(sorted(VALID_SECTION_TYPES))}"},
            status_code=400,
        )

    # Ensure the session directory exists
    d = session_dir(dtxsid)

    # Save / update identity.json on every approve so it stays current
    if identity:
        (d / "identity.json").write_text(
            json.dumps(identity, indent=2, default=str), encoding="utf-8",
        )

    # Save / update meta.json with chemical name and CASRN
    meta_path = d / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = {"dtxsid": dtxsid, "created_at": now_iso()}
    meta["updated_at"] = now_iso()
    if identity:
        meta["name"] = identity.get("name", "")
        meta["casrn"] = identity.get("casrn", "")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Stamp the data with the approval time + flag and clear any stale flag.
    # The 'approved' boolean is the source of truth for the editor lock state;
    # 'approved_at' is a human-readable timestamp.  ('stale' is set by
    # invalidate_pool_artifacts when the file pool changes after a section
    # was already approved — re-approval clears it.)
    data["approved"] = True
    data["approved_at"] = now_iso()
    data.pop("stale", None)

    if section_type == "background":
        save_section(dtxsid, "background", data)
    elif section_type == "bm2":
        # Build the section key from the original .bm2 filename
        filename = data.get("filename", "")
        slug = bm2_slug(filename) if filename else ""
        if not slug:
            return JSONResponse(
                {"error": "bm2 data must include a filename"},
                status_code=400,
            )
        section_key = f"bm2_{slug}"
        save_section(dtxsid, section_key, data)

        # Copy the .bm2 file from /tmp into the session's files/ directory
        # so it persists across server restarts.  (Processed data is cached
        # in LMDB via bm2_cache, so no sidecar files need copying.)
        bm2_id = data.get("bm2_id", "")
        upload = _bm2_uploads.get(bm2_id)
        if upload and os.path.exists(upload["temp_path"]):
            files_dir = d / "files"
            files_dir.mkdir(exist_ok=True)
            src = upload["temp_path"]
            dest = files_dir / filename
            if not dest.exists():
                shutil.copy2(src, dest)

    elif section_type == "methods":
        # Materials and Methods — single section, saved as methods.json
        save_section(dtxsid, "methods", data)

    elif section_type == "bmd_summary":
        # Apical Endpoint BMD Summary — auto-derived, saved as bmd_summary.json
        save_section(dtxsid, "bmd_summary", data)

    elif section_type == "genomics":
        # Genomics section — one file per organ × sex combination.
        # The section_key is built from organ and sex (e.g., "genomics_liver_male").
        organ = data.get("organ", "").lower().replace(" ", "_")
        sex = data.get("sex", "").lower().replace(" ", "_")
        if not organ or not sex:
            return JSONResponse(
                {"error": "genomics data must include organ and sex"},
                status_code=400,
            )
        section_key = f"genomics_{organ}_{sex}"
        save_section(dtxsid, section_key, data)

        # Copy uploaded CSV into files/ for future reprocessing
        csv_id = data.get("csv_id", "")
        csv_upload = _csv_uploads.get(csv_id)
        if csv_upload and os.path.exists(csv_upload["temp_path"]):
            files_dir = d / "files"
            files_dir.mkdir(exist_ok=True)
            dest = files_dir / csv_upload["filename"]
            if not dest.exists():
                shutil.copy2(csv_upload["temp_path"], dest)

    elif section_type == "summary":
        # Summary section — saved as summary.json
        save_section(dtxsid, "summary", data)

    # --- Style learning: detect edits and extract rules ---
    # The client sends the original LLM-generated text alongside the
    # (possibly edited) approved text.  If they differ, the user made
    # deliberate style changes — we extract rules from those changes
    # in a background thread to avoid blocking the approve response.
    user_edited = False
    original_text = ""
    edited_text = ""

    if section_type == "background":
        original_paragraphs = data.get("original_paragraphs")
        edited_paragraphs = data.get("paragraphs")
        if original_paragraphs and edited_paragraphs:
            user_edited = original_paragraphs != edited_paragraphs
            if user_edited:
                original_text = "\n\n".join(original_paragraphs)
                edited_text = "\n\n".join(edited_paragraphs)

    elif section_type == "bm2":
        original_narrative = data.get("original_narrative", "")
        edited_narrative = data.get("narrative", "")
        if original_narrative and edited_narrative:
            user_edited = original_narrative != edited_narrative
            if user_edited:
                original_text = original_narrative
                edited_text = edited_narrative

    elif section_type in ("methods", "summary"):
        # Methods and summary sections use the same paragraph-based
        # style learning as background — compare original vs. edited paragraphs
        original_paragraphs = data.get("original_paragraphs")
        edited_paragraphs = data.get("paragraphs")
        if original_paragraphs and edited_paragraphs:
            user_edited = original_paragraphs != edited_paragraphs
            if user_edited:
                original_text = "\n\n".join(original_paragraphs)
                edited_text = "\n\n".join(edited_paragraphs)

    if user_edited:
        # Fire-and-forget: extract style rules in a background thread.
        # We don't await the result — the user gets their approve response
        # immediately, and the rules are saved asynchronously.
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None, extract_and_merge_style_rules, original_text, edited_text,
        )
        logger.info("Style learning triggered for %s/%s", dtxsid, section_type)

    # Read back the saved version number so the UI can display "v1", "v2", etc.
    # The version was stamped onto `data` by save_section() before writing.
    version = data.get("version", 1)

    return JSONResponse({
        "ok": True,
        "section_type": section_type,
        "user_edited": user_edited,
        "version": version,
    })


# ---------------------------------------------------------------------------
# Section key resolver — shared by save / unapprove / delete endpoints
# ---------------------------------------------------------------------------

def _resolve_section_key(body: dict) -> tuple[str | None, str | None]:
    """
    Map a request body's (section_type, plus optional bm2_slug or organ/sex)
    onto the on-disk filename used by save_section / load_section.

    Returns (section_key, error_message).  Exactly one of the two will be
    None: the caller dispatches accordingly.
    """
    section_type = body.get("section_type", "")
    if section_type == "background":
        return ("background", None)
    if section_type == "methods":
        return ("methods", None)
    if section_type == "bmd_summary":
        return ("bmd_summary", None)
    if section_type == "summary":
        return ("summary", None)
    if section_type == "bm2":
        slug = body.get("bm2_slug", "")
        if not slug:
            return (None, "bm2_slug is required for bm2 sections")
        return (f"bm2_{slug}", None)
    if section_type == "genomics":
        organ = body.get("organ", "").lower().replace(" ", "_")
        sex = body.get("sex", "").lower().replace(" ", "_")
        if not organ or not sex:
            return (None, "organ and sex are required for genomics sections")
        return (f"genomics_{organ}_{sex}", None)
    return (None, f"Unknown section_type: {section_type}")


# ---------------------------------------------------------------------------
# POST /api/session/save-section — auto-save without changing approval
# ---------------------------------------------------------------------------

@router.post("/api/session/save-section")
async def api_session_save_section(request: Request):
    """
    Persist a report section to disk WITHOUT changing its approval state.

    Used to auto-save freshly-generated content (e.g., when the LLM
    finishes producing the body Background) so it survives a page reload
    without requiring the user to click Approve.  Approval is a separate
    concern — it locks the editor and applies style learning.

    Input JSON:
      {
        "dtxsid": "DTXSID...",
        "section_type": "background" | "methods" | ...,
        "data": {...},        // the section payload (paragraphs, references, etc.)
        "approved": false,    // optional; defaults to false for fresh saves
        "bm2_slug": "...",    // required for bm2 sections
        "organ": "...",       // required for genomics sections
        "sex": "..."          // required for genomics sections
      }

    The save uses 'archive=False' so it does NOT create a new history
    entry — only approve actions bump the version count.
    """
    body = await request.json()
    dtxsid = body.get("dtxsid", "")
    if not dtxsid:
        return JSONResponse({"error": "dtxsid is required"}, status_code=400)

    section_key, err = _resolve_section_key(body)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    data = dict(body.get("data") or {})
    # Stamp the approval state (default False — fresh generations are
    # unapproved until the user explicitly clicks Approve).
    data["approved"] = bool(body.get("approved", False))
    data.setdefault("saved_at", now_iso())

    save_section(dtxsid, section_key, data, archive=False)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# POST /api/session/unapprove — flip approved=False (does NOT delete data)
# ---------------------------------------------------------------------------

@router.post("/api/session/unapprove")
async def api_session_unapprove(request: Request):
    """
    Mark a report section as not-approved while preserving its content.

    Approval is a UI lock state; unapproving simply unlocks the editor
    so the user can revise.  The on-disk content remains intact — they
    can re-approve without regenerating.

    Input JSON:
      {
        "dtxsid": "DTXSID...",
        "section_type": "background" | "bm2" | "methods" | ...,
        "bm2_slug": "...",  // required for bm2
        "organ": "...",     // required for genomics
        "sex": "..."        // required for genomics
      }

    No-op if the section file doesn't exist.  Returns ok regardless so
    the caller can always rely on a successful response.
    """
    body = await request.json()
    dtxsid = body.get("dtxsid", "")
    if not dtxsid:
        return JSONResponse({"error": "dtxsid is required"}, status_code=400)

    section_key, err = _resolve_section_key(body)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    section_path = session_dir(dtxsid) / f"{section_key}.json"
    if section_path.exists():
        try:
            data = json.loads(section_path.read_text(encoding="utf-8"))
            data["approved"] = False
            # Don't archive — flag flip isn't a content change worth
            # keeping in history.
            save_section(dtxsid, section_key, data, archive=False)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to flip approved flag for %s/%s: %s",
                           dtxsid, section_key, e)

    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# POST /api/session/discard-section — delete a section's content from disk
# ---------------------------------------------------------------------------

@router.post("/api/session/discard-section")
async def api_session_discard_section(request: Request):
    """
    Permanently delete a section's JSON file (and abandon its history).

    Use this for explicit user-initiated discards — e.g., a "Reset this
    section" action.  Distinct from unapprove, which preserves content.

    Input JSON: same shape as save-section.
    """
    body = await request.json()
    dtxsid = body.get("dtxsid", "")
    if not dtxsid:
        return JSONResponse({"error": "dtxsid is required"}, status_code=400)

    section_key, err = _resolve_section_key(body)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    delete_section(dtxsid, section_key)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# GET /api/session/{dtxsid}/history/{section_key} — version history for a section
# ---------------------------------------------------------------------------

@router.get("/api/session/{dtxsid}/history/{section_key}")
async def api_session_history(dtxsid: str, section_key: str, version: int = 0):
    """
    Return version history for an approved section.

    Lists all past versions (from the history/ subdirectory) plus the current
    version.  Each entry includes the version number, approved_at timestamp,
    and whether it's the current version.

    If the `version` query parameter is provided (e.g. ?version=1), returns
    the full JSON content of that specific version instead of the list.

    URL pattern:
        GET /api/session/{dtxsid}/history/{section_key}         → version list
        GET /api/session/{dtxsid}/history/{section_key}?version=1 → full content

    Response (list mode):
    {
      "section_key": "background",
      "current_version": 3,
      "versions": [
        {"version": 1, "approved_at": "2026-03-02T19:23:59...", "is_current": false},
        {"version": 2, "approved_at": "2026-03-02T19:45:12...", "is_current": false},
        {"version": 3, "approved_at": "2026-03-02T20:01:33...", "is_current": true}
      ]
    }
    """
    d = SESSIONS_DIR / dtxsid
    current_path = d / f"{section_key}.json"
    history_dir = d / "history" / section_key

    # The current file must exist — otherwise there's no history to show
    if not current_path.exists():
        return JSONResponse(
            {"error": f"No approved '{section_key}' section found"},
            status_code=404,
        )

    current_data = json.loads(current_path.read_text(encoding="utf-8"))
    current_version = current_data.get("version", 1)

    # --- Collect archived versions from history/ ---
    # Each file is named {safe_timestamp}.json where colons in the ISO
    # timestamp have been replaced with hyphens.
    archived_versions = []
    if history_dir.exists():
        for f in sorted(history_dir.glob("*.json")):
            try:
                v = json.loads(f.read_text(encoding="utf-8"))
                archived_versions.append(v)
            except (json.JSONDecodeError, OSError):
                # Skip corrupt history files
                continue

    # --- If a specific version was requested, return its full content ---
    if version > 0:
        # Check archived versions first
        for v in archived_versions:
            if v.get("version") == version:
                return JSONResponse(v)
        # Check if it's the current version
        if current_version == version:
            return JSONResponse(current_data)
        return JSONResponse(
            {"error": f"Version {version} not found"}, status_code=404,
        )

    # --- List mode: return metadata for all versions ---
    versions = []
    for v in archived_versions:
        versions.append({
            "version": v.get("version", 0),
            "approved_at": v.get("approved_at", ""),
            "is_current": False,
        })
    # Add the current version as the last entry
    versions.append({
        "version": current_version,
        "approved_at": current_data.get("approved_at", ""),
        "is_current": True,
    })

    return JSONResponse({
        "section_key": section_key,
        "current_version": current_version,
        "versions": versions,
    })


# ---------------------------------------------------------------------------
# POST /api/session/{dtxsid}/restore — restore a past version as current
# ---------------------------------------------------------------------------

@router.post("/api/session/{dtxsid}/restore")
async def api_session_restore(dtxsid: str, request: Request):
    """
    Restore a past version of a section by re-saving it as the new current.

    This is non-destructive: restoring v1 does NOT delete v2 or v3.  Instead
    it creates a new version (v4) whose content matches v1.  The old current
    is archived to history/ first, as usual.

    Input JSON:
      {"section_key": "background", "version": 1}

    The restored data gets a fresh approved_at timestamp and an incremented
    version number.
    """
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

    d = SESSIONS_DIR / dtxsid
    current_path = d / f"{section_key}.json"
    history_dir = d / "history" / section_key

    if not current_path.exists():
        return JSONResponse(
            {"error": f"No approved '{section_key}' section found"},
            status_code=404,
        )

    # Find the requested version in history files
    target_data = None
    if history_dir.exists():
        for f in sorted(history_dir.glob("*.json")):
            try:
                v = json.loads(f.read_text(encoding="utf-8"))
                if v.get("version") == target_version:
                    target_data = v
                    break
            except (json.JSONDecodeError, OSError):
                continue

    # Also check if they're restoring the current version (no-op but valid)
    if target_data is None:
        current_data = json.loads(current_path.read_text(encoding="utf-8"))
        if current_data.get("version") == target_version:
            return JSONResponse({
                "ok": True,
                "message": "Already the current version",
                "version": target_version,
            })
        return JSONResponse(
            {"error": f"Version {target_version} not found"}, status_code=404,
        )

    # Stamp the restored data with a fresh approval timestamp.
    # save_section() will archive the old current and assign a new version number.
    target_data["approved_at"] = now_iso()
    # Remove the old version number — save_section() will compute the new one
    target_data.pop("version", None)

    save_section(dtxsid, section_key, target_data)

    return JSONResponse({
        "ok": True,
        "version": target_data.get("version", 1),
        "section_key": section_key,
    })


# ---------------------------------------------------------------------------
# GET /api/experiment-metadata/{dtxsid} — retrieve experiment metadata
# ---------------------------------------------------------------------------

@router.get("/api/experiment-metadata/{dtxsid}")
async def api_get_experiment_metadata(dtxsid: str):
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
    sess_path = session_dir(dtxsid)
    json_path = sess_path / "integrated.json"

    if not json_path.exists():
        return JSONResponse(
            {"error": "No integrated data found"}, status_code=404,
        )

    try:
        integrated = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to read integrated data: {e}"}, status_code=500,
        )

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
async def api_save_experiment_metadata(dtxsid: str, request: Request):
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

    Also writes a metadata_approved.json marker so the UI knows the
    user has explicitly reviewed and approved the metadata.
    """
    sess_path = session_dir(dtxsid)
    json_path = sess_path / "integrated.json"

    if not json_path.exists():
        return JSONResponse(
            {"error": "No integrated data found"}, status_code=404,
        )

    body = await request.json()
    metadata_by_name = body.get("metadata", {})

    if not metadata_by_name:
        return JSONResponse(
            {"error": "No metadata provided"}, status_code=400,
        )

    try:
        integrated = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to read integrated data: {e}"}, status_code=500,
        )

    # Apply user-edited metadata to each experiment
    updated_count = 0
    for exp in integrated.get("doseResponseExperiments", []):
        name = exp.get("name", "")
        if name in metadata_by_name:
            exp["experimentDescription"] = metadata_by_name[name]
            updated_count += 1

    # Write updated integrated.json
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(integrated, f, indent=2)

    # Re-export .bm2 with the approved metadata
    bm2_path = sess_path / "integrated.bm2"
    bm2_ok = False
    try:
        from bmdx_pipe import export_integrated_bm2
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            export_integrated_bm2,
            str(json_path),
            str(bm2_path),
        )
        bm2_ok = True
    except Exception as e:
        logger.warning("Failed to re-export .bm2 after metadata edit: %s", e)

    # Write approval marker
    meta_approved = {
        "approved_at": now_iso(),
        "experiments_updated": updated_count,
    }
    (sess_path / "metadata_approved.json").write_text(
        json.dumps(meta_approved, indent=2), encoding="utf-8",
    )

    logger.info(
        "Metadata approved for %s: %d experiments updated, bm2=%s",
        dtxsid, updated_count, "ok" if bm2_ok else "failed",
    )

    return JSONResponse({
        "ok": True,
        "updated": updated_count,
        "bm2_exported": bm2_ok,
    })


# ---------------------------------------------------------------------------
# POST /api/pool/reset/{dtxsid} — full pool reset (destructive)
# ---------------------------------------------------------------------------

@router.post("/api/pool/reset/{dtxsid}")
async def api_pool_reset(dtxsid: str):
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

    Does NOT delete:
      - meta.json, identity.json (chemical identity — still valid)
      - history/ (version history of approved sections — archival)

    The user is warned on the client side before this endpoint is called.
    After reset, the session directory still exists but is effectively empty
    (just meta.json and identity.json), ready for fresh uploads.
    """
    _bm2_uploads = get_bm2_uploads()
    _csv_uploads = get_csv_uploads()
    _pool_fingerprints = get_pool_fingerprints()
    _data_uploads = get_data_uploads()
    _integrated_pool = get_integrated_pool()

    d = SESSIONS_DIR / dtxsid
    if not d.exists():
        return JSONResponse(
            {"error": f"No session found for {dtxsid}"},
            status_code=404,
        )

    deleted_items = []

    # 1. Delete files/ directory (all uploaded raw data)
    files_dir = d / "files"
    if files_dir.exists():
        shutil.rmtree(files_dir)
        deleted_items.append("files/")

    # 2. Delete integration artifacts
    for artifact in ("integrated.json", "integrated.bm2",
                     "metadata_approved.json", "validation_report.json",
                     "precedence.json", "animal_report.json"):
        p = d / artifact
        if p.exists():
            p.unlink()
            deleted_items.append(artifact)

    # 3. Delete all approved section files (bm2_*, genomics_*, methods, etc.)
    for pattern in ("bm2_*.json", "genomics_*.json"):
        for f in d.glob(pattern):
            f.unlink()
            deleted_items.append(f.name)

    for section_file in ("methods.json", "bmd_summary.json", "summary.json"):
        p = d / section_file
        if p.exists():
            p.unlink()
            deleted_items.append(section_file)

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
async def api_session_reset(dtxsid: str):
    """
    Completely delete the entire session for a given DTXSID.

    Unlike pool reset (which preserves identity and history), this removes
    EVERYTHING: the entire sessions/{dtxsid}/ directory including meta.json,
    identity.json, background.json, history/, files/, and all approved sections.

    Also clears all in-memory server state for this chemical (same as pool reset).

    After this, the chemical identity form is still filled (from localStorage)
    but the server has no record of any prior work.  The user starts completely
    from scratch.
    """
    _bm2_uploads = get_bm2_uploads()
    _csv_uploads = get_csv_uploads()
    _pool_fingerprints = get_pool_fingerprints()
    _data_uploads = get_data_uploads()
    _integrated_pool = get_integrated_pool()

    d = SESSIONS_DIR / dtxsid
    if not d.exists():
        return JSONResponse({"ok": True, "message": "No session to reset"})

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
