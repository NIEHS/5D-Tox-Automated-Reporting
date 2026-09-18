"""
web_routes/integrated_routes.py — HTTP transport for the integrated dataset
and the processing step.

Routes (all thin: parse → call the HTTP-free pipeline function → serialize):
  GET  /api/integrated/{dtxsid}             stream integrated.json from disk
  GET  /api/integrated-summary/{dtxsid}     counts-only summary (schema-checked)
  GET  /api/integrated-tree/{dtxsid}        slim structural tree for a viewer
  POST /api/process-integrated/{dtxsid}     run the processing pipeline
  POST /api/generate-animal-report/{dtxsid} per-animal traceability report

MOVED 2026-09-18 out of pipeline/integrated_io.py and
pipeline/process_integrated.py. Those modules registered these handlers on a
router that lived in pipeline/pool_globals, which made the processing package
depend on FastAPI and on web_routes (ADR-0013 layering inversion). The
handler bodies are unchanged; only their home and the router they attach to
moved. The pipeline functions they call (`_load_integrated`,
`_enrich_source_experiment_counts`, `run_process`, `generate_animal_report_step`)
are the same HTTP-free cores as before.
"""

import asyncio

import orjson
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from pipeline.integrated_io import _enrich_source_experiment_counts, _load_integrated
from pipeline.pool_globals import _session_dir
from pipeline.process_integrated import run_process
from workflow.errors import StepError
from workflow.steps import generate_animal_report_step
from workflow.store import DiskPoolStore

router = APIRouter()


# ---------------------------------------------------------------------------
# Read-side route handlers
# ---------------------------------------------------------------------------
# Two GETs that surface integrated.json to the browser.  The "full" form
# streams the file straight from disk (FileResponse), letting Oboe.js
# parse it progressively without loading the whole thing into memory on
# the server side.  The "summary" form goes through _load_integrated so
# it also passes the schema barrier, then collapses the heavy bits down
# to counts.

@router.get("/api/integrated/{dtxsid}")
async def api_integrated_full(dtxsid: str):
    """
    Stream the full integrated BMDProject JSON from disk.

    Returns the cached integrated.json via FileResponse (chunked streaming)
    so the browser can parse it progressively with Oboe.js.  If no cached
    file exists, returns 404 -- the caller should trigger integration first.
    """
    integrated_path = _session_dir(dtxsid) / "integrated.json"
    if not integrated_path.exists():
        return JSONResponse(
            {"error": "No integrated data found -- run integration first"},
            status_code=404,
        )
    return FileResponse(
        path=str(integrated_path),
        media_type="application/json",
        filename="integrated.json",
    )


@router.get("/api/integrated-summary/{dtxsid}")
async def api_integrated_summary(dtxsid: str):
    """
    Return a lightweight summary of the integrated BMDProject.

    Uses _load_integrated() which handles both the main integrated.json
    and the _category_lookup.json sidecar.  Only summary fields are
    returned — the full response arrays and category lookup stay server-side.
    """
    integrated = _load_integrated(dtxsid)

    if not integrated:
        return JSONResponse(
            {"error": "No integrated data found"},
            status_code=404,
        )

    meta = integrated.get("_meta", {})
    experiments = integrated.get("doseResponseExperiments", [])
    bmd_results = integrated.get("bMDResult", [])
    cat_results = integrated.get("categoryAnalysisResults", [])

    # --- Backfill experiment_count per platform if missing ---
    # Sessions saved before the enrichment was added to integrate_pool()
    # won't have experiment_count in source_files.  Compute it on the fly
    # using the same name-matching heuristic so the preview table shows
    # correct values instead of 0.
    source_files = meta.get("source_files", {})
    needs_backfill = source_files and any(
        "experiment_count" not in info for info in source_files.values()
    )
    if needs_backfill and experiments:
        _enrich_source_experiment_counts(source_files, experiments)

    # Build experiment summaries (name + probe count only -- no response data)
    exp_summaries = []
    for exp in experiments:
        exp_summaries.append({
            "name": exp.get("name", ""),
            "probe_count": len(exp.get("probeResponses", [])),
        })

    return JSONResponse({
        "_meta": meta,
        "experiment_count": len(experiments),
        "experiments": exp_summaries,
        "bmd_result_count": len(bmd_results),
        "category_analysis_count": len(cat_results),
    })


@router.get("/api/integrated-tree/{dtxsid}")
async def api_integrated_tree(dtxsid: str):
    """
    Return a slim, browser-safe structural tree of the integrated BMDProject.

    The full integrated.json is 60 MB+ (the per-animal `responses` float arrays
    dominate), so it must never be shipped to a UI. This endpoint deserializes
    server-side but emits only classification + endpoint NAMES per experiment —
    a few hundred KB even for large sessions — enough for a
    platform → sex/organ → experiment → endpoints tree viewer.
    """
    integrated = _load_integrated(dtxsid)
    if not integrated:
        return JSONResponse({"error": "No integrated data found"}, status_code=404)

    experiments = integrated.get("doseResponseExperiments", [])
    nodes = []
    for exp in experiments:
        desc = exp.get("experimentDescription") or {}
        probe_responses = exp.get("probeResponses", []) or []
        endpoints = []
        for pr in probe_responses:
            probe = (pr or {}).get("probe") or {}
            pid = probe.get("id")
            if pid:
                endpoints.append(pid)
        treatments = exp.get("treatments", []) or []
        # De-dup dose levels (treatments list is one entry per animal).
        doses = sorted({t.get("dose") for t in treatments if t.get("dose") is not None})
        nodes.append({
            "name": exp.get("name", ""),
            "platform": desc.get("platform"),
            "sex": desc.get("sex"),
            "organ": desc.get("organ"),
            "provider": desc.get("provider"),
            "probe_count": len(probe_responses),
            "endpoints": endpoints,
            "doses": doses,
        })

    return JSONResponse({
        "dtxsid": dtxsid,
        "experiment_count": len(experiments),
        "bmd_result_count": len(integrated.get("bMDResult", [])),
        "category_analysis_count": len(integrated.get("categoryAnalysisResults", [])),
        "experiments": nodes,
    })


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

@router.post("/api/process-integrated/{dtxsid}")
async def api_process_integrated(dtxsid: str, request: Request):
    """
    HTTP transport for the processing pipeline. Parses the request body and
    delegates to the HTTP-free core `run_process` (ADR-0014). A StepError from
    the core becomes the {'error': msg} JSONResponse the UI expects.

    Input JSON:
      {
        "compound_name": "PFHxSAm",
        "dose_unit": "mg/kg",
        "bmd_stats": ["median"],  // optional: mean, median, minimum, etc.
        "go_pct": 5,              // optional: GO category filter cutoffs
        "go_min_genes": 20,
        "go_max_genes": 500,
        "go_min_bmd": 3
      }
    """
    # Tolerate empty or missing request bodies — the UI sometimes sends
    # POST with no content (e.g., from a simple fetch without JSON body).
    try:
        params = await request.json()
    except Exception:
        params = {}

    try:
        result_payload = await run_process(dtxsid, params, DiskPoolStore())
    except StepError as e:
        return JSONResponse({"error": e.message}, status_code=e.status_code)
    return JSONResponse(result_payload)


@router.post("/api/generate-animal-report/{dtxsid}")
async def api_generate_animal_report(dtxsid: str):
    """
    Generate a per-animal traceability report for a session's file pool.

    Reads all fingerprinted files from disk, extracts per-animal data
    (animal_id -> dose, sex, selection), and cross-references across
    tiers and platforms.  Persists the result to
    sessions/{dtxsid}/animal_report.json.

    Requires fingerprints to exist (from prior /api/pool/validate call).
    If no fingerprints are cached, re-fingerprints all files first.

    Returns the full AnimalReport as JSON.

    ADR-0014 (step 2): logic lives in workflow.steps.generate_animal_report_step;
    this handler is the thin transport layer. The step is blocking (xlsx/bm2
    parsing), so it runs in a thread executor to keep the event loop free.
    """
    store = DiskPoolStore()
    loop = asyncio.get_running_loop()
    try:
        report_dict = await loop.run_in_executor(
            None, lambda: generate_animal_report_step(dtxsid, store)
        )
    except StepError as e:
        return JSONResponse({"error": e.message}, status_code=e.status_code)

    return Response(
        content=orjson.dumps(report_dict),
        media_type="application/json",
    )
