"""
llm_routes.py — LLM-powered generation API endpoints.

Extracted from background_server.py.  These endpoints call Claude to generate
report text: background sections, Materials & Methods, Summary, and genomics
narratives.  Also includes the SSE-streaming /generate endpoint.

All endpoints are mounted as a FastAPI APIRouter on the /api prefix.

Endpoints:
  POST /api/generate                    — Gather data + generate 6-paragraph background (SSE)
  POST /api/generate-methods            — LLM-generate Materials and Methods
  GET  /api/methods-context/{dtxsid}    — Preview extracted M&M context (no LLM)
  POST /api/generate-summary            — LLM-generate Summary section
  POST /api/generate-genomics-narrative — LLM-generate genomics narratives
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from bmdx_pipe import bm2_cache
from session_store import SESSIONS_DIR
from llm_helpers import llm_generate_json_async
from style_learning import load_style_profile
from chem_resolver import ChemicalIdentity
from data_gatherer import gather_all
from background_writer import generate_background
from server_state import get_pool_fingerprints
from interpret import build_genomics_interpretation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event message."""
    json_str = json.dumps(data, default=str)
    return f"event: {event_type}\ndata: {json_str}\n\n"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/generate — full pipeline: gather data + generate background
# ---------------------------------------------------------------------------

@router.post("/api/generate")
async def api_generate(request: Request):
    """
    Run the full background generation pipeline.

    Input JSON:
      {"identity": {...ChemicalIdentity fields...}, "use_ollama": false, "model": ""}

    Returns a streaming SSE response with progress updates, followed by
    the final generated background as JSON.

    SSE events:
      event: progress   data: {"message": "Querying ATSDR ToxProfiles..."}
      event: complete   data: {"paragraphs": [...], "references": [...], ...}
      event: error      data: {"error": "..."}
    """
    body = await request.json()
    identity_dict = body.get("identity", {})
    use_ollama = body.get("use_ollama", False)
    model = body.get("model", "")

    if not identity_dict.get("name") and not identity_dict.get("casrn"):
        return JSONResponse(
            {"error": "Identity must include at least a name or CASRN"},
            status_code=400,
        )

    # Reconstruct ChemicalIdentity from the JSON dict
    identity = ChemicalIdentity.from_dict(identity_dict)

    # Use SSE to stream progress updates
    async def event_stream():
        progress_messages = []

        def progress_callback(msg: str):
            """Collect progress messages from the data gathering step."""
            progress_messages.append(msg)

        try:
            # Step 1: Gather data (with progress callback)
            loop = asyncio.get_running_loop()

            # Yield initial progress
            yield _sse_event("progress", {"message": "Starting data gathering..."})

            # Run gather_all in a thread pool (it makes blocking HTTP calls)
            bg_data = await loop.run_in_executor(
                None, gather_all, identity, progress_callback,
            )

            # Yield all progress messages collected during gathering
            for msg in progress_messages:
                yield _sse_event("progress", {"message": msg})

            # Step 2: Load learned style preferences (if any) and generate
            # background with LLM.  Style rules are injected into the prompt
            # so the LLM writes in the user's preferred style from the start.
            style_rules = []
            profile = load_style_profile()
            if profile.get("rules"):
                style_rules = [r["rule"] for r in profile["rules"]]

            if style_rules:
                yield _sse_event("progress", {
                    "message": f"Applying {len(style_rules)} learned style preference{'s' if len(style_rules) != 1 else ''}..."
                })

            yield _sse_event("progress", {
                "message": f"Generating background with {'Ollama' if use_ollama else 'Claude'}..."
            })

            result = await loop.run_in_executor(
                None, generate_background, bg_data, use_ollama, model,
                style_rules or None,
            )

            # Step 3: Return the complete result
            # Include the raw data for the export endpoint
            result["raw_data"] = bg_data.to_dict()
            result["notes"] = bg_data.notes

            yield _sse_event("complete", result)

        except Exception as e:
            yield _sse_event("error", {"error": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# POST /api/generate-methods — generate Materials and Methods section
# ---------------------------------------------------------------------------

@router.post("/api/generate-methods")
async def api_generate_methods(request: Request):
    """
    Generate a structured Materials and Methods section for the 5dToxReport.

    Replicates the NIEHS Report 10 M&M structure with 6 major sections,
    10+ conditional subsections, and Table 1 (genomics sample counts).

    The approach is hybrid data + LLM:
      1. Extract study metadata from fingerprints, animal report, and .bm2
         analysisInfo.notes (doses, sample sizes, BMDExpress params, etc.)
      2. Build a structured LLM prompt that asks for prose per subsection key
      3. Parse the LLM's JSON response into a MethodsReport with heading hierarchy
      4. Subsections are CONDITIONAL — only included when the relevant data domain
         exists in the file pool (e.g., Transcriptomics only if gene_expression)

    Input JSON:
      {
        "identity": {ChemicalIdentity dict},
        "study_params": {"vehicle": "...", "route": "...", "duration_days": 5, "species": "..."},
        "animal_report": {optional animal_report.json dict}
      }
      All other study metadata (dose groups, sample sizes, endpoints, BMD params)
      is extracted automatically from the file pool fingerprints and .bm2 caches.

    Returns JSON:
      {
        "sections": [{heading, level, key, paragraphs, table}, ...],
        "context": {MethodsContext fields},
        "section_key": "methods",
        "model_used": "claude-sonnet-4-6"
      }
    """
    from methods_report import (
        MethodsReport,
        MethodsSection,
        build_methods_prompt,
        build_subsection_skeleton,
        build_table1_data,
        extract_methods_context,
    )

    _pool_fingerprints = get_pool_fingerprints()

    body = await request.json()
    identity = body.get("identity", {})
    study_params = body.get("study_params", {})
    animal_report_data = body.get("animal_report")
    dtxsid = identity.get("dtxsid", "")

    # --- Backwards compatibility: accept old flat fields too ---
    # The old frontend sent vehicle, route, etc. as top-level fields.
    # Merge them into study_params if present.
    for key in ("vehicle", "route", "duration_days", "species"):
        if key in body and key not in study_params:
            study_params[key] = body[key]

    # --- Collect fingerprints from the server's pool cache ---
    fingerprints = {}
    if dtxsid and dtxsid in _pool_fingerprints:
        for fid, fp in _pool_fingerprints[dtxsid].items():
            # Convert FileFingerprint to dict for extract_methods_context
            if hasattr(fp, "__dataclass_fields__"):
                fingerprints[fid] = {
                    k: getattr(fp, k) for k in fp.__dataclass_fields__
                }
            else:
                fingerprints[fid] = fp

    # --- Collect .bm2 JSON caches for BMDExpress metadata extraction ---
    # Each .bm2 file's analysisInfo.notes contains the BMDExpress version,
    # BMDS version, models fit, BMR type, etc.
    bm2_jsons = {}
    if dtxsid:
        session_files_dir = SESSIONS_DIR / dtxsid / "files"
        if session_files_dir.exists():
            for bm2_path in session_files_dir.glob("*.bm2"):
                try:
                    cached = bm2_cache.get_json(str(bm2_path))
                    if cached:
                        bm2_jsons[bm2_path.stem] = cached
                except Exception:
                    pass

    # --- Load animal report from session if not provided in request ---
    if not animal_report_data and dtxsid:
        ar_path = SESSIONS_DIR / dtxsid / "animal_report.json"
        if ar_path.exists():
            try:
                animal_report_data = json.loads(ar_path.read_text())
            except Exception:
                pass

    # --- Load integrated data for genomics assay identification ---
    integrated_data = None
    if dtxsid:
        int_path = SESSIONS_DIR / dtxsid / "integrated.json"
        if int_path.exists():
            try:
                integrated_data = json.loads(int_path.read_text())
            except Exception:
                pass

    # --- Extract structured context from all data sources ---
    ctx = extract_methods_context(
        identity=identity,
        fingerprints=fingerprints,
        animal_report=animal_report_data,
        study_params=study_params,
        bm2_jsons=bm2_jsons,
        session_dir=str(SESSIONS_DIR / dtxsid) if dtxsid else None,
        integrated=integrated_data,
    )

    # --- Build the structured LLM prompt ---
    system, prompt = build_methods_prompt(ctx)

    try:
        # Call Claude and parse the JSON response — keyed by subsection key,
        # e.g. {"study_design": "paragraph text", "dose_selection": "..."}
        subsection_texts = await llm_generate_json_async(
            "methods-generator", prompt, system,
        )

        # --- Assemble into MethodsReport ---
        skeleton = build_subsection_skeleton(ctx)
        sections = []
        for key, heading, level in skeleton:
            text = subsection_texts.get(key, "")
            if not text:
                continue
            # Split multi-paragraph strings on double newlines
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            sections.append(MethodsSection(
                heading=heading,
                level=level,
                key=key,
                paragraphs=paragraphs,
            ))

        # --- Add Table 1 data to the report context ---
        table1 = build_table1_data(ctx)

        report = MethodsReport(sections=sections, context=ctx)
        report_dict = report.to_dict()

        # Include Table 1 data separately for the frontend to render
        if table1:
            report_dict["table1"] = table1

        report_dict["section_key"] = "methods"
        report_dict["model_used"] = "claude-sonnet-4-6"

        return JSONResponse(report_dict)

    except json.JSONDecodeError as e:
        # If the LLM didn't return valid JSON, try to salvage as flat paragraphs
        logger.warning("Methods LLM response was not valid JSON: %s", e)
        # Fall back: treat the entire response as a single paragraph per line
        paragraphs = [p.strip() for p in response.split("\n\n") if p.strip()]
        sections = [MethodsSection(
            heading="Materials and Methods",
            level=3,
            key="fallback",
            paragraphs=paragraphs,
        )]
        report = MethodsReport(sections=sections, context=ctx)
        report_dict = report.to_dict()
        report_dict["section_key"] = "methods"
        report_dict["model_used"] = "claude-sonnet-4-6"
        report_dict["warning"] = "LLM response was not structured JSON; content placed in single section"
        return JSONResponse(report_dict)

    except Exception as e:
        logger.exception("Methods generation failed")
        return JSONResponse(
            {"error": f"Methods generation failed: {e}"},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# GET /api/methods-context/{dtxsid} — preview extracted M&M context data
# ---------------------------------------------------------------------------

@router.get("/api/methods-context/{dtxsid}")
async def api_methods_context(dtxsid: str):
    """
    Return the extracted MethodsContext for a DTXSID without running the LLM.

    This is a read-only inspection endpoint that lets the user verify what
    data the system has extracted from the file pool (fingerprints, animal
    report, .bm2 analysisInfo) before generating M&M prose.  The response
    is a JSON object with all MethodsContext fields plus the subsection
    skeleton (which headings will be included) and Table 1 data.

    Used by the "Preview Data" button in the Methods section UI.
    """
    from methods_report import (
        extract_methods_context,
        build_subsection_skeleton,
        build_table1_data,
    )

    _pool_fingerprints = get_pool_fingerprints()

    # --- Collect fingerprints ---
    fingerprints = {}
    if dtxsid in _pool_fingerprints:
        for fid, fp in _pool_fingerprints[dtxsid].items():
            if hasattr(fp, "__dataclass_fields__"):
                fingerprints[fid] = {
                    k: getattr(fp, k) for k in fp.__dataclass_fields__
                }
            else:
                fingerprints[fid] = fp

    # --- Collect .bm2 JSON caches ---
    bm2_jsons = {}
    session_files_dir = SESSIONS_DIR / dtxsid / "files"
    if session_files_dir.exists():
        for bm2_path in session_files_dir.glob("*.bm2"):
            try:
                cached = bm2_cache.get_json(str(bm2_path))
                if cached:
                    bm2_jsons[bm2_path.stem] = cached
            except Exception:
                pass

    # --- Load animal report ---
    animal_report_data = None
    ar_path = SESSIONS_DIR / dtxsid / "animal_report.json"
    if ar_path.exists():
        try:
            animal_report_data = json.loads(ar_path.read_text())
        except Exception:
            pass

    # --- Load identity ---
    identity = {}
    id_path = SESSIONS_DIR / dtxsid / "identity.json"
    if id_path.exists():
        try:
            identity = json.loads(id_path.read_text())
        except Exception:
            pass

    # --- Extract context ---
    ctx = extract_methods_context(
        identity=identity,
        fingerprints=fingerprints,
        animal_report=animal_report_data,
        bm2_jsons=bm2_jsons,
    )

    # --- Build response ---
    result = ctx.to_dict()

    # Add the subsection skeleton so the user can see which headings
    # will be generated (and which conditional ones are active/skipped)
    skeleton = build_subsection_skeleton(ctx)
    result["_subsection_skeleton"] = [
        {"key": k, "heading": h, "level": lvl}
        for k, h, lvl in skeleton
    ]

    # Add Table 1 data
    table1 = build_table1_data(ctx)
    if table1:
        result["_table1"] = table1

    # Add fingerprint summary so user can see what data sources fed the context
    fp_summary = {}
    for fid, fp in fingerprints.items():
        _get = fp.get if isinstance(fp, dict) else lambda k, d=None: getattr(fp, k, d)
        domain = _get("domain")
        if domain:
            if domain not in fp_summary:
                fp_summary[domain] = []
            fp_summary[domain].append({
                "file_id": fid,
                "filename": _get("filename", fid),
                "tier": _get("tier"),
                "sexes": _get("sexes", []),
                "endpoint_count": len(_get("endpoint_names", [])),
                "dose_groups": _get("dose_groups", []),
            })
    result["_fingerprint_summary"] = fp_summary

    return JSONResponse(result)


# ---------------------------------------------------------------------------
# POST /api/generate-summary — generate report Summary section
# ---------------------------------------------------------------------------

@router.post("/api/generate-summary")
async def api_generate_summary(request: Request):
    """
    Generate a Summary section that synthesizes all approved report sections.

    Reads all approved sections from the session, builds a context block
    describing the key findings, and sends it to Claude to produce a
    NIEHS-style summary.

    Input JSON:
      {
        "dtxsid": "DTXSID...",
        "identity": {ChemicalIdentity dict}
      }

    Returns JSON:
      {
        "paragraphs": ["Summary paragraph 1...", ...],
        "section_key": "summary",
        "model_used": "claude-..."
      }
    """
    body = await request.json()
    dtxsid = body.get("dtxsid", "")
    identity = body.get("identity", {})

    if not dtxsid:
        return JSONResponse(
            {"error": "dtxsid is required"},
            status_code=400,
        )

    compound_name = identity.get("name", "the test chemical")

    # Gather context from all approved sections in the session
    d = SESSIONS_DIR / dtxsid
    context_parts = []

    # Background — extract a brief summary
    bg_path = d / "background.json"
    if bg_path.exists():
        try:
            bg = json.loads(bg_path.read_text(encoding="utf-8"))
            bg_paras = bg.get("paragraphs", [])
            if bg_paras:
                context_parts.append(
                    "=== BACKGROUND (first paragraph) ===\n"
                    + bg_paras[0][:500]
                )
        except (json.JSONDecodeError, OSError):
            pass

    # Apical endpoint findings — summarize from bm2 sections
    for f in sorted(d.glob("bm2_*.json")):
        try:
            section = json.loads(f.read_text(encoding="utf-8"))
            narrative = section.get("narrative", "")
            if isinstance(narrative, list):
                narrative = " ".join(narrative)
            if narrative:
                section_name = f.stem.removeprefix("bm2_").replace("-", " ").title()
                context_parts.append(
                    f"=== APICAL RESULTS: {section_name} ===\n"
                    + narrative[:800]
                )
        except (json.JSONDecodeError, OSError):
            continue

    # BMD summary — if available
    bmd_path = d / "bmd_summary.json"
    if bmd_path.exists():
        try:
            bmd_data = json.loads(bmd_path.read_text(encoding="utf-8"))
            eps = bmd_data.get("endpoints", [])
            if eps:
                lines = ["=== BMD SUMMARY (sorted by BMD) ==="]
                for ep in eps[:10]:
                    lines.append(
                        f"  {ep.get('endpoint', '')}: BMD={ep.get('bmd', 'ND')}, "
                        f"BMDL={ep.get('bmdl', 'ND')}, {ep.get('sex', '')}, "
                        f"{ep.get('direction', '')}"
                    )
                context_parts.append("\n".join(lines))
        except (json.JSONDecodeError, OSError):
            pass

    # Genomics findings — summarize from genomics_*.json files
    for f in sorted(d.glob("genomics_*.json")):
        try:
            genomics = json.loads(f.read_text(encoding="utf-8"))
            organ = genomics.get("organ", "")
            sex = genomics.get("sex", "")
            gene_sets = genomics.get("gene_sets", [])
            top_genes = genomics.get("top_genes", [])

            lines = [f"=== GENOMICS: {organ.title()} {sex.title()} ==="]
            if gene_sets:
                lines.append("Top gene sets by BMD:")
                for gs in gene_sets[:5]:
                    lines.append(
                        f"  {gs.get('go_term', '')}: median BMD={gs.get('bmd_median', '')}, "
                        f"{gs.get('n_genes', 0)} genes, {gs.get('direction', '')}"
                    )
            if top_genes:
                lines.append("Top genes by BMD:")
                for g in top_genes[:5]:
                    lines.append(
                        f"  {g.get('gene_symbol', '')}: BMD={g.get('bmd', '')}, "
                        f"{g.get('direction', '')}"
                    )
            context_parts.append("\n".join(lines))
        except (json.JSONDecodeError, OSError):
            continue

    if not context_parts:
        return JSONResponse(
            {"error": "No approved sections found to summarize"},
            status_code=400,
        )

    context_block = "\n\n".join(context_parts)

    prompt = f"""Based on the following approved report sections for {compound_name},
generate a Summary section in the style of an NIEHS/NTP 5-day study technical report.

{context_block}

---

Generate 3-4 summary paragraphs covering:
1. Overview — briefly restate the study design and the chemical tested
2. Key Apical Findings — which endpoints were most sensitive (lowest BMD), in which sex, and in what direction
3. Key Genomic Findings (if available) — which gene sets and genes were most sensitive, what biological processes they represent
4. Concordance — compare sensitivity across biological levels (gene < gene set < apical endpoint). Note whether transcriptomic changes occurred at lower doses than apical effects (as expected).

Return ONLY a JSON array of paragraph strings: ["paragraph1", "paragraph2", ...]"""

    system = (
        "You are a toxicology report writer specializing in NTP/NIEHS-style "
        "technical reports. Synthesize findings across biological levels "
        "(molecular, pathway, organism) into a coherent summary. Return ONLY "
        "valid JSON with no markdown formatting."
    )

    try:
        paragraphs = await llm_generate_json_async(
            "summary-generator", prompt, system,
            max_tokens=4096,
        )
        if not isinstance(paragraphs, list):
            paragraphs = [str(paragraphs)]

        return JSONResponse({
            "paragraphs": paragraphs,
            "section_key": "summary",
            "model_used": "claude-sonnet-4-6",
        })

    except Exception as e:
        return JSONResponse(
            {"error": f"Summary generation failed: {e}"},
            status_code=500,
        )


# ---------------------------------------------------------------------------
# POST /api/generate-genomics-narrative — LLM-generate narrative for genomics
# ---------------------------------------------------------------------------
#
# Generates 1–2 paragraphs each for:
#   - Gene Set BMD Analysis (which biological processes were most sensitive)
#   - Gene BMD Analysis (which individual genes were most sensitive)
#
# These narratives appear above the data tables in the NIEHS report.
# The endpoint is called separately from /api/process-genomics because
# the LLM call is slower than the table computation, and the user may
# want to review the tables before generating narrative.
# ---------------------------------------------------------------------------

@router.post("/api/generate-genomics-narrative")
async def api_generate_genomics_narrative(request: Request):
    """
    Generate narrative paragraphs for the genomics Results section.

    Takes gene set and gene ranking data (from /api/process-genomics)
    and produces LLM-generated narrative for each subsection.  When a
    dtxsid is provided, runs the full interpretation pipeline from
    interpret.py — pathway enrichment, GO enrichment, BMD ordering,
    organ signatures, per-gene literature evidence — so the LLM prompt
    is grounded in actual biological context rather than just raw tables.

    Input JSON:
      {
        "dtxsid": "DTXSID50469320",          (optional, enables enrichment)
        "identity": {ChemicalIdentity fields},
        "organ": "liver",
        "sex": "male",
        "gene_sets": [{go_id, go_term, bmd_median, n_genes, direction}, ...],
        "top_genes": [{gene_symbol, bmd, bmdl, fold_change, direction}, ...],
        "all_genes": [{gene_symbol, bmd, bmdl, direction, fold_change}, ...],
        "total_responsive_genes": 150,
        "dose_unit": "mg/kg"
      }

    Returns JSON:
      {
        "gene_set_narrative": ["paragraph1", "paragraph2"],
        "gene_narrative": ["paragraph1", "paragraph2"],
        "model_used": "claude-sonnet-4-6",
        "enrichment_available": true
      }
    """
    body = await request.json()
    identity = body.get("identity", {})
    dtxsid = body.get("dtxsid", "")
    organ = body.get("organ", "")
    sex = body.get("sex", "")
    gene_sets = body.get("gene_sets", [])
    top_genes = body.get("top_genes", [])
    all_genes = body.get("all_genes", [])
    total_responsive = body.get("total_responsive_genes", 0)
    dose_unit = body.get("dose_unit", "mg/kg")

    compound = identity.get("name", "the test article")

    # --- Attempt enrichment analysis via interpret.py pipeline ---
    # The enrichment pipeline queries bmdx.duckdb for pathway/GO/literature
    # evidence, producing a ~200-line structured context block that gives the
    # LLM real biological grounding instead of just raw gene/GO tables.
    context_text = ""
    enrichment_available = False

    # Build a synthetic genomics_section dict for build_genomics_interpretation().
    # The function accepts the same shape that _extract_genomics() produces.
    genomics_section = {
        "all_genes": all_genes,
        "top_genes": top_genes,
        "organ": organ,
        "sex": sex,
        "total_responsive_genes": total_responsive,
    }

    # Only attempt enrichment if we have genes to analyze and the DB exists.
    has_genes = bool(all_genes or top_genes)
    db_path = Path("bmdx.duckdb")
    if has_genes and db_path.exists():
        # --- Check interpretation cache (Phase 4) ---
        # Cache key is a hash of the gene list — if the genes haven't changed
        # (same integration run), reuse the cached enrichment result instead of
        # re-running the 2-5s DuckDB + Fisher's exact pipeline.
        gene_list_for_hash = all_genes or top_genes
        gene_hash = hashlib.md5(
            json.dumps(gene_list_for_hash, sort_keys=True).encode()
        ).hexdigest()[:16]
        cache_path = None
        if dtxsid:
            # Sanitize organ/sex for filename (e.g. "liver_female")
            organ_key = organ.lower().replace(" ", "_")
            sex_key = sex.lower().replace(" ", "_")
            cache_path = (
                SESSIONS_DIR / dtxsid
                / f"_cache_interpretation_{organ_key}_{sex_key}_{gene_hash}.json"
            )

        cached = None
        if cache_path and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
                logger.info(
                    "Interpretation cache hit: %s/%s for %s",
                    organ, sex, dtxsid,
                )
            except Exception:
                logger.warning("Corrupted interpretation cache, recomputing")
                cached = None

        if cached and cached.get("context_text"):
            # Cache hit — use the previously computed enrichment context.
            context_text = cached["context_text"]
            enrichment_available = True
        else:
            # Cache miss — run the full enrichment pipeline.
            try:
                interp = await asyncio.to_thread(
                    build_genomics_interpretation,
                    genomics_section,
                    str(db_path),
                )
                context_text = interp.get("context_text", "")
                enrichment_available = bool(context_text)

                # Persist to cache so regenerations are instant.
                if cache_path and context_text:
                    try:
                        # Clean up old caches for this organ×sex (different hash
                        # means different gene list from a re-integration).
                        cache_dir = cache_path.parent
                        prefix = f"_cache_interpretation_{organ_key}_{sex_key}_"
                        for old in cache_dir.glob(f"{prefix}*.json"):
                            if old != cache_path:
                                old.unlink(missing_ok=True)
                        cache_path.write_text(json.dumps(interp))
                        logger.info(
                            "Cached interpretation: %s/%s for %s",
                            organ, sex, dtxsid,
                        )
                    except Exception:
                        # Caching is optional — don't fail the request.
                        logger.warning(
                            "Failed to cache interpretation", exc_info=True,
                        )

            except Exception:
                # Enrichment failed — fall back to the basic prompt below.
                # This keeps the endpoint functional even if bmdx.duckdb has
                # schema issues or interpret.py raises on unusual data.
                logger.warning(
                    "Enrichment pipeline failed, falling back to basic prompt",
                    exc_info=True,
                )

    # --- Load style rules for consistent voice ---
    style_rules = ""
    try:
        profile = load_style_profile()
        rules = profile.get("rules", [])
        if rules:
            style_rules = "\n\nApply these writing style preferences:\n" + "\n".join(
                f"- {r['rule']}" for r in rules[:10]
            )
    except Exception:
        pass  # Style learning is optional

    # --- Build the LLM prompt ---
    # When enrichment is available, the prompt includes pathway enrichment,
    # GO enrichment, BMD-ordered pathways, organ signatures, and per-gene
    # literature evidence assembled by interpret.py.  When enrichment is not
    # available (no DB, no genes, or pipeline failure), fall back to the
    # basic gene/GO table format.
    if enrichment_available:
        prompt = f"""Generate narrative paragraphs for the genomics Results section of an \
NIEHS/NTP 5-day study technical report on {compound}.

The study examined gene expression in the {organ} of {sex} Sprague Dawley rats.
A total of {total_responsive} genes had significant dose-responsive changes.

{context_text}

Return a JSON object with two keys:
1. "gene_set_narrative": 2–3 paragraphs covering biological processes, pathway \
enrichment, BMD ordering, and organ predictions. Ground claims in the pathway \
and GO enrichment results above. Note mechanism of action and whether responses \
are adaptive or adverse.

2. "gene_narrative": 2–3 paragraphs covering individual gene sensitivity, literature \
support (consensus vs single-study genes), and confidence assessment.

Use passive voice, formal scientific register matching NIEHS report style.
Do NOT include table data in the narrative — the tables are presented separately.
{style_rules}

Return ONLY valid JSON, no markdown formatting."""
    else:
        # Fallback: basic gene/GO tables (original behavior for sessions
        # without bmdx.duckdb or with enrichment failures).
        gs_lines = []
        for gs in gene_sets[:10]:
            gs_lines.append(
                f"  {gs.get('go_term', '')} (GO:{gs.get('go_id', '')}): "
                f"median BMD = {gs.get('bmd_median', 'N/A')} {dose_unit}, "
                f"{gs.get('n_genes', 0)} genes, direction = {gs.get('direction', 'N/A')}"
            )
        gs_table = "\n".join(gs_lines) if gs_lines else "(no gene sets)"

        gene_lines = []
        for g in top_genes[:10]:
            gene_lines.append(
                f"  {g.get('gene_symbol', '')}: "
                f"BMD = {g.get('bmd', 'N/A')} {dose_unit}, "
                f"BMDL = {g.get('bmdl', 'N/A')} {dose_unit}, "
                f"fold change = {g.get('fold_change', 'N/A')}, "
                f"direction = {g.get('direction', 'N/A')}"
            )
        gene_table = "\n".join(gene_lines) if gene_lines else "(no genes)"

        prompt = f"""Generate narrative paragraphs for the genomics Results section of an \
NIEHS/NTP 5-day study technical report on {compound}.

The study examined gene expression in the {organ} of {sex} Sprague Dawley rats.
A total of {total_responsive} genes had significant dose-responsive changes.

=== GENE SET BENCHMARK DOSE ANALYSIS ===
Top gene sets ranked by median BMD (most sensitive first):
{gs_table}

=== GENE BENCHMARK DOSE ANALYSIS ===
Top individual genes ranked by BMD (most sensitive first):
{gene_table}

Return a JSON object with two keys:
1. "gene_set_narrative": An array of 1–2 paragraphs summarizing the gene set BMD analysis.
   Note which biological processes were perturbed at the lowest doses, the predominant
   direction of perturbation, and the number of responsive gene sets.

2. "gene_narrative": An array of 1–2 paragraphs summarizing the individual gene BMD analysis.
   Note which genes were most sensitive, the direction and magnitude of their response,
   and any notable patterns in the top genes.

Use the passive voice and formal scientific register matching NIEHS report style.
Do NOT include table data in the narrative — the tables are presented separately.
{style_rules}

Return ONLY valid JSON, no markdown formatting."""

    system = (
        "You are a toxicology report writer specializing in NTP/NIEHS-style "
        "technical reports. Write concise, data-driven narrative for the genomics "
        "Results section. Ground your interpretation in the pathway enrichment, "
        "GO term analysis, organ signatures, and literature evidence provided. "
        "Return ONLY valid JSON with no markdown formatting."
    )

    try:
        result = await llm_generate_json_async(
            "genomics-narrative-generator", prompt, system,
            max_tokens=4096,
        )

        # Normalize: ensure both keys are arrays of strings
        gs_narr = result.get("gene_set_narrative", [])
        gene_narr = result.get("gene_narrative", [])
        if isinstance(gs_narr, str):
            gs_narr = [gs_narr]
        if isinstance(gene_narr, str):
            gene_narr = [gene_narr]

        return JSONResponse({
            "gene_set_narrative": gs_narr,
            "gene_narrative": gene_narr,
            "model_used": "claude-sonnet-4-6",
            "enrichment_available": enrichment_available,
        })

    except Exception as e:
        return JSONResponse(
            {"error": f"Genomics narrative generation failed: {e}"},
            status_code=500,
        )
