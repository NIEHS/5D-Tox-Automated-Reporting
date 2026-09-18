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
import json
import logging
import os

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from bmdx_pipe import bm2_cache
from pipeline.session_store import SESSIONS_DIR
from styling_export.llm_helpers import llm_generate_json_async
from narrative.style_learning import load_style_profile
from narrative.chem_resolver import ChemicalIdentity
from narrative.data_gatherer import gather_all
from narrative.background_writer import DEFAULT_CLAUDE_MODEL, generate_background
from web_routes.server_state import get_pool_fingerprints
from pipeline.pool_orchestrator import load_integrated
from narrative.interpret import resolve_anthropic_api_key
from narrative.genomics_llm import generate_genomics_narrative_async

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
# GET /api/models — live model catalog from the LiteLLM proxy
# ---------------------------------------------------------------------------
# The frontend Models modal lists whatever the proxy currently serves, grouped
# by provider.  The proxy routes every model (Claude, Gemini, Llama, ...)
# through the Anthropic-format /v1/messages endpoint, so any id here is usable
# for generation without per-provider routing.

# Embedding/OCR ids the proxy exposes that can't generate prose — hidden so a
# user can't pick one and hit a confusing failure.
_NON_CHAT_MODELS = frozenset({
    "text-embedding-3-large",
    "text-embedding-3-small",
    "mxbai-embed-large",
    "ollama-nomic-embed-text",
    "mistral-ocr-2505",
})

# Degraded fallback when the proxy's /v1/models is unreachable — the modal must
# still open with at least the canonical Claude tiers.
_FALLBACK_CATEGORIES = [
    {"name": "Anthropic (Claude)", "models": [
        "claude-opus-4.8", "claude-sonnet-4-6", "claude-haiku-4.5",
    ]},
]


def _model_category(model_id: str) -> str:
    """Infer a provider category from a model id prefix.

    The proxy reports owned_by:"openai" for everything, so the id prefix is the
    only real signal for grouping.
    """
    s = model_id.lower()
    if s.startswith("azure"):
        return "Azure (hosted)"
    if "claude" in s or "fable" in s:
        return "Anthropic (Claude)"
    if "gpt" in s or s.startswith(("o1", "o3", "o4")):
        return "OpenAI (GPT)"
    if "gemini" in s:
        return "Google (Gemini)"
    if "ollama" in s:
        return "Ollama (local)"
    if "llama" in s:
        return "Meta (Llama)"
    if "mistral" in s or "nemo" in s or "mixtral" in s:
        return "Mistral"
    return "Other"


@router.get("/api/models")
async def api_models():
    """Return the proxy's chat-capable models grouped by provider category.

    Response: {"categories": [{"name": str, "models": [id, ...]}, ...],
               "degraded": bool}
    Never raises — on any proxy failure it returns a small static fallback with
    degraded=True so the UI modal always opens.
    """
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    api_key = resolve_anthropic_api_key()
    ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")

    if not base_url or not api_key:
        return JSONResponse({"categories": _FALLBACK_CATEGORIES, "degraded": True})

    try:
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(None, lambda: requests.get(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
            verify=ca_bundle or True,
        ))
        resp.raise_for_status()
        ids = [m["id"] for m in resp.json().get("data", []) if m.get("id")]
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.warning("Failed to fetch proxy /v1/models: %s", e)
        return JSONResponse({"categories": _FALLBACK_CATEGORIES, "degraded": True})

    grouped: dict[str, list[str]] = {}
    for mid in sorted(ids):
        if mid in _NON_CHAT_MODELS:
            continue
        grouped.setdefault(_model_category(mid), []).append(mid)

    # Stable, sensible category order; unknown categories ("Other") sink last.
    order = [
        "Anthropic (Claude)", "Azure (hosted)", "OpenAI (GPT)",
        "Google (Gemini)", "Meta (Llama)", "Mistral", "Ollama (local)", "Other",
    ]
    categories = [
        {"name": name, "models": grouped[name]}
        for name in order if name in grouped
    ]
    return JSONResponse({"categories": categories, "degraded": False})


# ---------------------------------------------------------------------------
# POST /api/generate — full pipeline: gather data + generate background
# ---------------------------------------------------------------------------

@router.post("/api/generate")
async def api_generate(request: Request):
    """
    Run the full background generation pipeline.

    Input JSON:
      {"identity": {...ChemicalIdentity fields...}, "model": ""}

    Returns a streaming SSE response with progress updates, followed by
    the final generated background as JSON.

    SSE events:
      event: progress   data: {"message": "Querying ATSDR ToxProfiles..."}
      event: complete   data: {"paragraphs": [...], "references": [...], ...}
      event: error      data: {"error": "..."}
    """
    body = await request.json()
    identity_dict = body.get("identity", {})
    model = body.get("model", "") or DEFAULT_CLAUDE_MODEL

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
                "message": f"Generating background with {model}..."
            })

            result = await loop.run_in_executor(
                None, generate_background, bg_data, model,
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
    from narrative.methods_report import (
        MethodsReport,
        MethodsSection,
        build_methods_prompt,
        build_subsection_skeleton,
        build_sample_counts_table,
        extract_methods_context,
    )

    _pool_fingerprints = get_pool_fingerprints()

    body = await request.json()
    identity = body.get("identity", {})
    study_params = body.get("study_params", {})
    animal_report_data = body.get("animal_report")
    model = body.get("model", "") or DEFAULT_CLAUDE_MODEL
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
    # Route through the schema-validating loader (ADR-0001).  If the
    # session has no integrated data yet, load_integrated returns None
    # and we proceed without it — the methods narrative is best-effort
    # context.  If integrated.json fails schema validation, the raised
    # BMDProjectValidationError propagates to the global handler in
    # background_server.py which returns a structured 422.
    integrated_data = load_integrated(dtxsid) if dtxsid else None

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
            "methods-generator", prompt, system, model=model,
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
        table1 = build_sample_counts_table(ctx)

        report = MethodsReport(sections=sections, context=ctx)
        report_dict = report.to_dict()

        # Include Table 1 data separately for the frontend to render
        if table1:
            report_dict["table1"] = table1

        report_dict["section_key"] = "methods"
        report_dict["model_used"] = model

        return JSONResponse(report_dict)

    except json.JSONDecodeError as e:
        # If the LLM didn't return valid JSON, try to salvage as flat paragraphs
        logger.warning("Methods LLM response was not valid JSON: %s", e)
        # Fall back: treat the entire response as a single paragraph per line.
        # The raw text is only reachable through the exception itself
        # (json.JSONDecodeError.doc) — there is no local `response` variable
        # here, which made this branch a NameError until 2026-09-18.
        raw_text = e.doc or ""
        paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
        sections = [MethodsSection(
            heading="Materials and Methods",
            level=3,
            key="fallback",
            paragraphs=paragraphs,
        )]
        report = MethodsReport(sections=sections, context=ctx)
        report_dict = report.to_dict()
        report_dict["section_key"] = "methods"
        report_dict["model_used"] = model
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
    from narrative.methods_report import (
        extract_methods_context,
        build_subsection_skeleton,
        build_sample_counts_table,
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
    table1 = build_sample_counts_table(ctx)
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
    model = body.get("model", "") or DEFAULT_CLAUDE_MODEL

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
            max_tokens=4096, model=model,
        )
        if not isinstance(paragraphs, list):
            paragraphs = [str(paragraphs)]

        return JSONResponse({
            "paragraphs": paragraphs,
            "section_key": "summary",
            "model_used": model,
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


# ---------------------------------------------------------------------------
# Genomics narrative routes (generate / regenerate)
# ---------------------------------------------------------------------------
# The generators themselves live in narrative/genomics_llm.py and
# narrative/apical_bmd_llm.py (moved 2026-09-18; see those headers).
@router.post("/api/generate-genomics-narrative")
async def api_generate_genomics_narrative(request: Request):
    """
    HTTP wrapper over `generate_genomics_narrative_async`.  Preserves
    the legacy Generate-button flow for ad-hoc regenerations, though
    process-integrated now calls the shared function directly.

    Input JSON (same as before):
      {dtxsid, identity, organ, sex, gene_sets, top_genes, all_genes,
       total_responsive_genes, dose_unit}
    """
    body = await request.json()
    identity = body.get("identity", {})
    result = await generate_genomics_narrative_async(
        dtxsid=body.get("dtxsid", ""),
        compound=identity.get("name", "the test article"),
        organ=body.get("organ", ""),
        sex=body.get("sex", ""),
        gene_sets=body.get("gene_sets", []),
        top_genes=body.get("top_genes", []),
        all_genes=body.get("all_genes", []),
        total_responsive=body.get("total_responsive_genes", 0),
        dose_unit=body.get("dose_unit", "mg/kg"),
        force=bool(body.get("force", False)),
        model=body.get("model", ""),
    )
    if "error" in result:
        return JSONResponse(result, status_code=500)
    return JSONResponse(result)


@router.post("/api/session/{dtxsid}/regenerate-genomics-narrative")
async def api_regenerate_genomics_narrative(dtxsid: str, request: Request):
    """
    Force-regenerate the LLM genomics narrative for ONE organ.

    This is the server side of the per-organ Regenerate button in the
    genomics panel.  The narrative is normally generated server-side during
    process-integrated and treated as user-owned thereafter (never silently
    recomputed — see the cache comment in
    `generate_genomics_narrative_async`).  This endpoint is the explicit
    escape hatch: it discards the stored narrative AND any manual edit for
    the organ and produces a fresh one.

    Why server-side: the browser only holds the rendered `by_organ_llm`
    paragraphs, not the gene lists the generator needs.  So we reload the
    gene data from the session's `_cache_genomics_*.json` (the same cache
    process-integrated wrote) rather than expecting the client to re-send it.

    Steps:
      1. Reload the organ×sex gene-data cache + the chemical identity.
      2. Clear the user override for this organ (both kinds) so the freshly
         generated text actually surfaces — otherwise the override tier
         would keep winning on render and the regenerate would be invisible.
      3. Force-generate each sex of the organ (force=True bypasses the
         narrative store; the generator's own cleanup drops stale-hash files).
      4. Aggregate the per-sex results into per-organ paragraph lists via the
         shared helper (overrides=None — we just cleared them).

    Input JSON:  {"organ": "liver"}
    Returns:     {"organ": "liver", "gene_set": [...], "gene_bmd": [...]}
                 — the two narratives to drop straight into the client's
                 `by_organ_llm[organ]` slots.
    """
    body = await request.json()
    organ = (body.get("organ") or "").strip().lower()
    if not organ:
        return JSONResponse({"error": "organ is required"}, status_code=400)
    model = body.get("model", "")

    session_dir = SESSIONS_DIR / dtxsid
    if not session_dir.exists():
        return JSONResponse(
            {"error": f"Session {dtxsid} not found"}, status_code=404,
        )

    # --- (1) Reload the organ×sex gene-data cache ---------------------------
    # `_cache_genomics_*.json` is the organ_sex-keyed dict process-integrated
    # wrote; each entry carries the gene_sets_by_stat / top_genes / all_genes
    # the LLM prompt needs.  Without it there is nothing to regenerate from.
    # A session accumulates one file per content hash, so take the NEWEST by
    # mtime — the same selection every other genomics-cache reader uses.  The
    # previous `sorted(...)[break]` grabbed the lexically-first file, which in a
    # multi-hash session is the STALE one, exactly the case regenerate defends
    # against.
    genomics_cache = None
    _genomics_matches = sorted(
        session_dir.glob("_cache_genomics_*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if _genomics_matches:
        try:
            genomics_cache = json.loads(_genomics_matches[-1].read_text(encoding="utf-8"))
        except Exception:
            genomics_cache = None
    if not genomics_cache:
        return JSONResponse(
            {"error": "No genomics data cached for this session"},
            status_code=404,
        )

    # Chemical name for the prompt's phrasing; fall back gracefully.
    compound = "the test article"
    identity_path = session_dir / "identity.json"
    if identity_path.exists():
        try:
            compound = json.loads(identity_path.read_text()).get(
                "name", compound
            )
        except Exception:
            pass

    # Pick the primary BMD stat the same way the chart/narrative paths do —
    # the first key of any entry's gene_sets_by_stat (defaults to "median").
    first_entry = next(iter(genomics_cache.values()), {})
    stats = list((first_entry.get("gene_sets_by_stat") or {}).keys())
    bmd_stat = stats[0] if stats else "median"

    # Collect this organ's organ×sex keys (key shape: "<organ>_<sex>", split
    # on the first underscore exactly as the reload path does).
    organ_keys = []
    for key in genomics_cache.keys():
        if "_" not in key:
            continue
        organ_k, _sex_k = key.split("_", 1)
        if organ_k.lower() == organ:
            organ_keys.append(key)
    if not organ_keys:
        return JSONResponse(
            {"error": f"No genomics data for organ '{organ}'"},
            status_code=404,
        )

    # --- (2) Clear the user override for this organ (both kinds) ------------
    # Regenerate means "throw away my edits for this organ too" — otherwise
    # the override tier (which wins on render) would mask the new LLM text.
    overrides_path = session_dir / "genomics_narrative_overrides.json"
    if overrides_path.exists():
        try:
            raw = json.loads(overrides_path.read_text())
            for kind in ("gene_set", "gene_bmd"):
                bucket = raw.get(kind)
                if isinstance(bucket, dict):
                    # Match case-insensitively — the override file may have
                    # stored the organ with different casing.
                    for k in [k for k in bucket if k.lower() == organ]:
                        bucket.pop(k, None)
            overrides_path.write_text(json.dumps(raw))
        except Exception:
            logger.warning(
                "Failed to clear override during regenerate", exc_info=True,
            )

    # --- (3) Force-generate each sex of the organ (in parallel) ------------
    async def _one(key):
        entry = genomics_cache[key]
        gs_by_stat = entry.get("gene_sets_by_stat") or {}
        gene_sets_for_llm = gs_by_stat.get(bmd_stat) or []
        try:
            out = await generate_genomics_narrative_async(
                dtxsid=dtxsid,
                compound=compound,
                organ=entry.get("organ", organ),
                sex=entry.get("sex", ""),
                gene_sets=gene_sets_for_llm,
                top_genes=entry.get("top_genes") or [],
                all_genes=entry.get("all_genes") or [],
                total_responsive=entry.get("total_responsive_genes", 0),
                dose_unit=entry.get("dose_unit", "mg/kg"),
                force=True,
                model=model,
            )
            return key, out
        except Exception as e:
            logger.warning("Regenerate failed for %s: %s", key, e)
            return key, {"error": str(e)}

    results = await asyncio.gather(*[_one(k) for k in organ_keys])

    # If every sex errored, surface a failure rather than a silent empty.
    if all(("error" in out) for _key, out in results):
        return JSONResponse(
            {"error": "Genomics narrative regeneration failed for all sexes"},
            status_code=500,
        )

    # --- (4) Aggregate per-sex results into per-organ paragraph lists ------
    per_organ_bundles: dict[str, dict[str, dict[str, list]]] = {}
    for key, out in results:
        if not out or "error" in out:
            continue
        entry = genomics_cache[key]
        organ_l = (entry.get("organ") or organ).lower()
        sex_l = (entry.get("sex") or "").lower()
        per_organ_bundles.setdefault(organ_l, {})[sex_l] = {
            "gs": out.get("gene_set_narrative") or [],
            "gn": out.get("gene_narrative") or [],
        }

    from genomics.genomics_narratives import aggregate_organ_llm_narratives
    gs_by_organ, gn_by_organ = aggregate_organ_llm_narratives(
        per_organ_bundles, overrides=None,
    )

    return JSONResponse({
        "organ": organ,
        "gene_set": gs_by_organ.get(organ, []),
        "gene_bmd": gn_by_organ.get(organ, []),
    })
