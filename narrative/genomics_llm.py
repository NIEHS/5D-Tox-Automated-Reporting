"""
narrative/genomics_llm.py — the KB-grounded, LLM-written transcriptomic
interpretation for one organ × sex.

What it does: for a given organ/sex it (1) runs the deterministic knowledge-
base analysis (narrative.interpret.build_genomics_interpretation → ranked GO
sets / genes + a [Pn] paper catalogue drawn from bmdx.duckdb), (2) builds the
prompt that forbids citing anything outside that catalogue, (3) calls the
model through the shared styling_export.llm_helpers chokepoint, and (4)
caches the organ×sex result under the session directory. That cache doubles
as the narrative *store*: a user's Lock/Unlock edits persist alongside it and
win over regeneration (see the overrides handling in the caller).

Where it fits: called by pipeline/process_integrated for every organ×sex in
parallel during content preparation, and by the two genomics-narrative HTTP
routes in web_routes/llm_routes (generate / regenerate).

MOVED 2026-09-18 from web_routes/llm_routes.py: it is a narrative generator,
not an HTTP handler, and pipeline/ importing it from the HTTP package inverted
the layering (ADR-0013).

Failure model: fail-soft — returns {"error": msg}; callers record it in
ProcessContext.content_errors so a degraded run is never cached.
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from common.paths import SESSIONS_DIR
from narrative.background_writer import DEFAULT_CLAUDE_MODEL
from narrative.interpret import build_genomics_interpretation
from narrative.style_learning import load_style_profile
from styling_export.llm_helpers import llm_generate_json_async

logger = logging.getLogger(__name__)


async def generate_genomics_narrative_async(
    *,
    dtxsid: str,
    compound: str,
    organ: str,
    sex: str,
    gene_sets: list,
    top_genes: list,
    all_genes: list,
    total_responsive: int,
    dose_unit: str = "mg/kg",
    force: bool = False,
    model: str = "",
) -> dict:
    """
    LLM-generate narrative paragraphs for a single organ × sex.

    Shared entry point used by both the /api/generate-genomics-narrative
    endpoint (user-triggered regeneration, legacy) and the
    process-integrated pipeline (auto-generation per organ × sex).  Pure
    async function — no Request/Response wrapping.  Handles enrichment
    context + interpretation cache + LLM call + result normalisation.

    `force` (default False) bypasses the per-(organ, sex) narrative store:
    when True we skip the cache lookup entirely and recompute enrichment +
    LLM from scratch, overwriting the stored narrative.  This is the escape
    hatch behind the Regenerate action (see the cache comment below); the
    normal callers leave it False so an existing narrative is reused.

    Returns:
        {
          "gene_set_narrative": list[str],
          "gene_narrative":     list[str],
          "model_used":         "claude-sonnet-4-6",
          "enrichment_available": bool,
        }
        or {"error": "..."} on failure.
    """
    chosen_model = model or DEFAULT_CLAUDE_MODEL

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

    # Candidate reference pool: a DETERMINISTIC, graph-grounded set of
    # DOI-anchored papers for this stratum's responsive genes, offered to the LLM
    # as a numbered [Pn] catalogue so its citations become a real reference list
    # (assembled report-wide from the persisted pools at surface time — see
    # narrative.references_builder).  Built once here; empty when there's no DB or
    # no genes, in which case the prompt carries no catalogue and no [Pn] rules.
    reference_pool: list[dict] = []

    # Only attempt enrichment if we have genes to analyze and the DB exists.
    has_genes = bool(all_genes or top_genes)
    db_path = Path("bmdx.duckdb")
    if has_genes and db_path.exists():
        # Responsive gene symbols for the pool — prefer the full all_genes list
        # (same input the enrichment uses), falling back to top_genes.
        _gene_syms = [
            g.get("gene_symbol") or g.get("symbol") or g.get("gene")
            for g in (all_genes or top_genes)
        ]
        _gene_syms = [s for s in _gene_syms if s]
        if _gene_syms:
            try:
                from narrative.references_builder import build_reference_pool_for_genes
                reference_pool = await asyncio.to_thread(
                    build_reference_pool_for_genes, _gene_syms, str(db_path),
                )
            except Exception:
                logger.warning("Reference pool build failed", exc_info=True)
        # --- Check interpretation cache ---
        #
        # Cache file naming: _cache_interpretation_{organ}_{sex}_{gene_hash}.json.
        # The gene_hash in the filename was originally a content-validation
        # key (regenerate when gene list changes).  That semantics is wrong
        # for our workflow: the user reads/edits/approves the generated
        # narrative, then locks it.  Regenerating because the gene-list
        # hash drifted (e.g., from a re-integration that picked up a
        # slightly different responsive set) would silently overwrite
        # narrative the user owns.
        #
        # New semantics: the cache file is a per-(organ, sex) **narrative
        # store**.  If ANY cache file exists for this organ×sex and has
        # both narratives populated, we return it — full stop.  We never
        # silently regenerate over narrative the user may have read,
        # edited, or approved.
        #
        # The escape hatch is the `force` flag, set by the Regenerate
        # action (POST /api/session/{dtxsid}/regenerate-genomics-narrative
        # → this function with force=True).  When force is set we skip the
        # lookup below, recompute, and write a fresh narrative; the cleanup
        # at the bottom of this function deletes the now-superseded
        # different-hash file(s) for the same organ×sex so disk stays tidy.
        #
        # The hash-keyed filename is retained as the *write* target for
        # fresh computes — so a regeneration lands at the name that
        # reflects the current gene list.
        gene_list_for_hash = all_genes or top_genes
        gene_hash = hashlib.md5(
            json.dumps(gene_list_for_hash, sort_keys=True).encode()
        ).hexdigest()[:16]
        cache_path = None
        existing_cache_path = None
        if dtxsid:
            # The organ×sex cache prefix is built by the shared helper so the
            # naming convention lives in one place (genomics_narratives).
            from genomics.genomics_narratives import interpretation_cache_prefix
            prefix = interpretation_cache_prefix(organ, sex)
            session_dir = SESSIONS_DIR / dtxsid
            cache_path = session_dir / f"{prefix}{gene_hash}.json"
            # Look for ANY existing narrative file for this (organ, sex),
            # not just the hash-keyed one.  Prefer the exact-hash match if
            # it exists (cleanest), otherwise fall back to the most recent
            # by mtime so a stale-hash narrative still wins over recompute.
            # `force` skips this entirely: existing_cache_path stays None,
            # so both the fast-path return and the stale-context reuse below
            # are bypassed and we recompute from scratch.
            if not force:
                if cache_path.exists():
                    existing_cache_path = cache_path
                else:
                    matches = sorted(
                        session_dir.glob(f"{prefix}*.json"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    if matches:
                        existing_cache_path = matches[0]

        cached = None
        if existing_cache_path is not None:
            try:
                cached = json.loads(existing_cache_path.read_text())
                logger.info(
                    "Interpretation cache hit: %s/%s for %s (%s)",
                    organ, sex, dtxsid, existing_cache_path.name,
                )
            except Exception:
                logger.warning(
                    "Corrupted interpretation cache at %s, recomputing",
                    existing_cache_path,
                )
                cached = None

        # Fast path: a previously generated narrative exists on disk for
        # this organ×sex.  Skip enrichment recompute AND the LLM call —
        # the narrative is the user's to edit/approve/unlock; we never
        # silently regenerate over it.
        #
        # ADR-0015 §Consolidation (deferred follow-up): this "return the store,
        # full stop" refusal + the `force` escape hatch above are the genomics
        # instance of the machine-guard predicate now unified in
        # workflow.ownership.may_machine_write(section, force=force).  Converging
        # THIS path onto it requires migrating the ad-hoc organ×sex narrative
        # cache (store 3) onto the section-fact shape may_machine_write reads —
        # explicitly out of scope for the narrow 4b step (predicate + render
        # wiring only).  Left as-is; the predicate is the target to converge on.
        if (
            cached
            and cached.get("gene_set_narrative")
            and cached.get("gene_narrative") is not None
        ):
            return {
                "gene_set_narrative": cached.get("gene_set_narrative") or [],
                "gene_narrative": cached.get("gene_narrative") or [],
                "model_used": cached.get("model_used", "claude-sonnet-4-6"),
                "enrichment_available": bool(cached.get("context_text")),
            }

        # Reuse cached enrichment context only when the matched file is
        # the current-hash one — a stale-hash file's context_text was
        # computed against a different gene list and would mislead a
        # fresh LLM regeneration.  When the user has explicitly cleared
        # the narrative (forcing this path), we want enrichment to
        # reflect the *current* gene list, not the prior one.
        if (
            cached
            and cached.get("context_text")
            and existing_cache_path == cache_path
        ):
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

                # Persist the stratum's candidate pool alongside the enrichment
                # context so surface-time assembly can reconstruct the report-wide
                # reference list without re-querying the graph.
                if reference_pool:
                    interp["reference_pool"] = reference_pool

                # Persist to cache so regenerations are instant.
                if cache_path and context_text:
                    try:
                        # Clean up old caches for this organ×sex (different hash
                        # means different gene list from a re-integration).
                        # `prefix` was computed once above via
                        # interpretation_cache_prefix and is still in scope here.
                        cache_dir = cache_path.parent
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
        # Offer the candidate reference pool as a numbered [Pn] catalogue and
        # ask the prose to cite it inline; those tokens become the report's
        # reference list (assembled report-wide at surface time).  Absent pool ⇒
        # no catalogue, no citation rules (byte-identical to the pre-feature
        # prompt), so the enrichment path degrades gracefully.
        catalogue_block = ""
        citation_rules = ""
        if reference_pool:
            from narrative.references_builder import format_reference_catalogue
            catalogue_block = "\n\n" + format_reference_catalogue(reference_pool)
            citation_rules = """

CITATION RULES:
- Support literature claims by citing candidate references inline as their token \
in square brackets, e.g. "... consistent with Nrf2 pathway activation [P3]."
- Cite ONLY papers from the CANDIDATE REFERENCES list above, using their exact \
[Pn] token. Do NOT invent citations or cite papers not in the list.
- Cite the papers that genuinely support each claim; you need not cite all of them."""

        prompt = f"""Generate narrative paragraphs for the genomics Results section of an \
NIEHS/NTP 5-day study technical report on {compound}.

The study examined gene expression in the {organ} of {sex} Sprague Dawley rats.
A total of {total_responsive} genes had significant dose-responsive changes.

{context_text}{catalogue_block}

Return a JSON object with two keys:
1. "gene_set_narrative": 2–3 paragraphs covering biological processes, pathway \
enrichment, BMD ordering, and organ predictions. Ground claims in the pathway \
and GO enrichment results above. Note mechanism of action and whether responses \
are adaptive or adverse. For each key biological process, comment on the predominant \
direction of regulation using the ↑/↓ gene counts in the table (e.g., "87% of \
lipid metabolism genes were upregulated, consistent with PPAR-alpha induction"). \
When counts are roughly equal (conflict), note the bidirectional response explicitly.

2. "gene_narrative": 2–3 paragraphs covering individual gene sensitivity, literature \
support (consensus vs single-study genes), and confidence assessment.

Use passive voice, formal scientific register matching NIEHS report style.
Do NOT include table data in the narrative — the tables are presented separately.{citation_rules}
{style_rules}

Return ONLY valid JSON, no markdown formatting."""
    else:
        # Fallback: basic gene/GO tables (original behavior for sessions
        # without bmdx.duckdb or with enrichment failures).
        gs_lines = []
        for gs in gene_sets[:10]:
            n_up = gs.get("n_up")
            n_down = gs.get("n_down")
            # Prefer explicit up/down counts over the categorical label so the
            # LLM can report proportions (e.g. "14 of 16 genes upregulated").
            dir_str = (
                f"{n_up} up / {n_down} down"
                if n_up is not None and n_down is not None
                else f"direction = {gs.get('direction', 'N/A')}"
            )
            gs_lines.append(
                f"  {gs.get('go_term', '')} (GO:{gs.get('go_id', '')}): "
                f"median BMD = {gs.get('bmd_median', 'N/A')} {dose_unit}, "
                f"{gs.get('n_genes', 0)} genes, {dir_str}"
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
   Note which biological processes were perturbed at the lowest doses. For each key
   process, report the predominant direction using the up/down counts provided (e.g.,
   "14 of 16 xenobiotic metabolism genes were upregulated"). When counts are roughly
   equal, note the bidirectional response explicitly.

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
            max_tokens=4096, model=chosen_model,
        )

        # Normalize: ensure both keys are arrays of strings
        gs_narr = result.get("gene_set_narrative", [])
        gene_narr = result.get("gene_narrative", [])
        if isinstance(gs_narr, str):
            gs_narr = [gs_narr]
        if isinstance(gene_narr, str):
            gene_narr = [gene_narr]

        # Persist the LLM output back into the interpretation cache so
        # session reloads and process-integrated re-runs find it
        # without triggering another LLM call.  Cache file already
        # exists (enrichment was either cached or just freshly written);
        # read-modify-write adds the narrative fields alongside
        # `context_text`.
        if cache_path and cache_path.exists():
            try:
                existing = json.loads(cache_path.read_text())
                existing["gene_set_narrative"] = gs_narr
                existing["gene_narrative"] = gene_narr
                existing["model_used"] = chosen_model
                # Ensure the stratum's reference pool is present even when the
                # enrichment context was a cache hit (so the pool wasn't written
                # on this run) — surface-time assembly reads it from here.
                if reference_pool and not existing.get("reference_pool"):
                    existing["reference_pool"] = reference_pool
                cache_path.write_text(json.dumps(existing))
            except Exception:
                logger.warning(
                    "Failed to cache LLM narrative", exc_info=True,
                )

        return {
            "gene_set_narrative": gs_narr,
            "gene_narrative": gene_narr,
            "model_used": chosen_model,
            "enrichment_available": enrichment_available,
        }

    except Exception as e:
        return {"error": f"Genomics narrative generation failed: {e}"}
