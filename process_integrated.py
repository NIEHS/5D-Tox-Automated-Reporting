"""
The process-integrated endpoint and the animal-traceability endpoint.

This module owns the two heavy POST handlers that consume the
integrated BMDProject after the pool has been validated and merged:

  POST /api/process-integrated/{dtxsid}    api_process_integrated
  POST /api/generate-animal-report/{dtxsid} api_generate_animal_report

api_process_integrated is the "god function" of the codebase — it
orchestrates NTP statistics (Williams trend, Dunnett's pairwise), BMDS
modeling (pybmds in a thread pool), section-card assembly per platform,
LLM-driven methods narrative generation, BMD summary tables, genomics
extraction with GO enrichment, and adversity signatures.  Each phase
is delegated to a helper in processing_helpers.py and gated by a
hash-keyed disk cache from cache_plumbing.py, so unchanged inputs hit
the cache instead of re-running the work (BMDS alone can take 8+
minutes uncached).

api_generate_animal_report is much smaller: it fans out
build_animal_report (from bmdx_pipe) on the session's fingerprinted
files in a thread pool to produce a per-animal traceability report,
then persists the result as animal_report.json.

The _BMD_STAT_LABELS dict lives here because it's used only by
api_process_integrated to set human-readable column headers for the
selected BMD statistic.  It was kept in pool_orchestrator.py during the
earlier extractions (processing_helpers / cache_plumbing /
integrated_io) so the god function could reach for it without a
cross-module import; now that the god function moves here, the
constant follows.

Both handlers register on pool_globals.router so the existing
`include_router(pool_orchestrator.router)` mount in background_server.py
continues to expose them with no other change.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass

import orjson
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from bmdx_pipe import (
    annotate_missing_animals,
    backfill_missing_doses,
    build_animal_report,
    build_clinical_obs_tables,
    build_table_data,
    report_to_dict,
)
from apical_bmds import run_bmds_for_endpoints
from llm_helpers import llm_generate_json_async as _llm_generate_json_async

from pool_globals import router, _session_dir, _pool_fingerprints
from pool_fingerprints import ensure_fingerprints
from section_serializers import _build_clinical_obs_section
from integrated_io import _load_integrated, load_integrated, save_integrated
from cache_plumbing import (
    _load_cache,
    _save_cache,
    _CHARTS_CACHE_SCHEMA_VERSION,
    _hash_ntp,
    _hash_sections,
    _hash_sidecars,
    _hash_bmds,
    _hash_genomics,
    _hash_bmd_summary,
    _hash_methods,
    _serialize_platform_tables,
    _deserialize_platform_tables,
    _restore_category_lookup,
)
from processing_helpers import (
    _filter_gene_expression,
    _partition_by_platform,
    _build_section_cards,
    _extract_genomics,
    _build_apical_bmd_summary,
    _build_bmds_bmd_summary,
    apply_apical_filters,
    prune_card_sexes,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UI labels
# ---------------------------------------------------------------------------

# Human-readable labels for BMD statistics, used by the UI to set table
# column headers (e.g. "BMD 5th Pct").
_BMD_STAT_LABELS = {
    "mean": "Mean",
    "median": "Median",
    "minimum": "Minimum",
    "weighted_mean": "Weighted Mean",
    "fifth_pct": "5th %ile",
    "tenth_pct": "10th %ile",
    "lower95": "Lower 95%",
    "upper95": "Upper 95%",
}


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------


@dataclass
class ProcessContext:
    """
    State threaded through the api_process_integrated pipeline (ADR-0002).

    Two field groups: the immutable request inputs parsed once at the top of
    the orchestrator, and the accumulated state each Layer writes back as it
    runs.  Each Layer takes this object, reads the inputs (plus any upstream
    Layer's output it depends on) and writes its own output onto the matching
    field.  This is an internal implementation detail — NOT the HTTP payload
    and NOT a persisted schema, so it carries no compatibility obligations.

    bmd_stat (scalar, the primary stat) and bmd_stats (the full list) are kept
    as SEPARATE fields because their consumers diverge: NTP / charts / the LLM
    genomics narratives use the scalar, while genomics extraction, the
    genomics cache key, and the bmd_stats payload key use the list.
    """

    # --- immutable request inputs ---
    dtxsid: str
    integrated: dict
    compound_name: str
    dose_unit: str
    bmd_stats: list
    bmd_stat: str
    go_pct: int
    go_min_genes: int
    go_max_genes: int
    go_min_bmd: int

    # Per-area organ allowlist from the template's `organs:` block —
    # {area: [lower-cased tokens]} (areas: "genomics", "organ-weight").  A
    # missing area key ⇒ no filtering for it; None/{} ⇒ no filtering anywhere.
    # Defaulted so test scaffolds that build a context need not pass it.  See
    # document_template.load_report_organs / table_builder_common.organ_allowed.
    organ_filters: dict | None = None

    # The sibling report-level allowlists, same shape conventions:
    #   sex_filters   — {area: [tokens]}, areas "apical"/"genomics"
    #   assay_filters — {area: [tokens]}, areas "clinical-chemistry"/"hematology"
    #   gene_filter / gene_set_filter — flat [tokens], genomics-only
    # All default to None ⇒ no filtering, so existing scaffolds are unaffected.
    # See document_template.load_report_{sex,assays,genes,gene_sets} and the
    # table_builder_common matchers.
    sex_filters: dict | None = None
    assay_filters: dict | None = None
    gene_filter: list | None = None
    gene_set_filter: list | None = None

    # --- accumulated state (None until the producing Layer runs) ---
    platform_tables: dict | None = None
    ntp_hash: str | None = None
    bmds_inputs: list | None = None
    sections_hash: str | None = None
    bmds_hash: str | None = None
    genomics_hash: str | None = None
    methods_hash: str | None = None
    fps_for_methods: dict | None = None
    sections: list | None = None
    unified_narratives: dict | None = None
    bmds_results: dict | None = None
    genomics_sections: dict | None = None
    methods_result: dict | None = None
    apical_bmd_summary: list | None = None
    apical_bmd_summary_bmds: list | None = None
    chart_images: list | None = None
    llm_gs_by_organ: dict | None = None
    llm_gene_by_organ: dict | None = None
    gene_set_narrative: dict | None = None
    gene_narrative: dict | None = None
    apical_bmd_narrative: dict | None = None


# ---------------------------------------------------------------------------
# Pipeline layer functions
# ---------------------------------------------------------------------------
# Each function is one "Layer" of api_process_integrated, extracted from the
# old monolithic handler (ADR-0002).  They are module-level so each phase is
# independently testable; the orchestrator below sequences them, preserving
# the dependency ordering and the asyncio.gather parallelism.  Each takes the
# shared ProcessContext, reads its inputs and upstream outputs from it, and
# writes its own output back onto it.


async def _build_apical_bmd_narrative(ctx):
    """
    Layer 3.5c — Apical BMD Summary narratives.

    Two-part narrative for the "Apical Endpoint Benchmark Dose Summary"
    section:
      descriptive — programmatic summary of the BMD findings: most
                    sensitive endpoint, BMD range, per-sex.
      analytical  — LLM paragraph interpreting biological significance,
                    organ-system sensitivity, sex differences, and
                    dose-response coherence.
    Both are combined into apical_bmd_narrative["paragraphs"] which
    report_data.py prepends to the BMD summary table.
    """
    dtxsid = ctx.dtxsid
    apical_bmd_summary = ctx.apical_bmd_summary
    methods_result = ctx.methods_result
    compound_name = ctx.compound_name
    dose_unit = ctx.dose_unit

    apical_bmd_narrative: dict = {}
    if apical_bmd_summary:
        try:
            from methods_report import build_apical_bmd_summary_narrative
            _methods_ctx = (
                methods_result.get("context") if methods_result else None
            ) or {}
            _chem_name = _methods_ctx.get("chemical_name") or compound_name or "the test article"
            _dur = _methods_ctx.get("study_duration", "subchronic (90-day)")
            _dose_groups = _methods_ctx.get("dose_groups") or []

            # Descriptive paragraphs (deterministic, no LLM).
            desc_paras = build_apical_bmd_summary_narrative(
                apical_bmd_summary,
                compound_name=_chem_name,
                dose_unit=dose_unit,
            )

            # LLM analytical paragraph (async, cached per summary hash).
            llm_paras: list[str] = []
            try:
                from llm_routes import generate_apical_bmd_narrative_async
                llm_result = await generate_apical_bmd_narrative_async(
                    dtxsid=dtxsid,
                    compound_name=_chem_name,
                    dose_unit=dose_unit,
                    apical_bmd_summary=apical_bmd_summary,
                    study_duration=_dur,
                    dose_groups=_dose_groups,
                )
                llm_paras = llm_result.get("paragraphs", [])
            except Exception as _llm_e:
                logger.warning("Apical BMD LLM narrative failed: %s", _llm_e)

            apical_bmd_narrative = {
                "descriptive": desc_paras,
                "analytical": llm_paras,
                # Flat paragraphs list for the PDF renderer — descriptive
                # first, then LLM analytical paragraph(s) below.
                "paragraphs": desc_paras + llm_paras,
            }
        except Exception as _apical_narr_e:
            logger.warning("Apical BMD narrative build failed: %s", _apical_narr_e)
    ctx.apical_bmd_narrative = apical_bmd_narrative


def _build_genomics_body_narratives(ctx):
    """
    Layer 3.5b — Deterministic body narratives.

    Per-organ findings paragraphs (plus the methodology + caveat
    intros).  Built by the shared assembler so the HTML in-app
    view and the PDF render identical prose above each organ's
    genomics table — no divergence between the two renderers.
    The LLM output from Layer 3.5a is merged in as `by_organ_llm`.
    """
    genomics_sections = ctx.genomics_sections
    methods_result = ctx.methods_result
    compound_name = ctx.compound_name
    llm_gs_by_organ = ctx.llm_gs_by_organ
    llm_gene_by_organ = ctx.llm_gene_by_organ

    gene_set_narrative = None
    gene_narrative = None
    if genomics_sections:
        try:
            from genomics_narratives import build_genomics_body_narratives
            _methods_ctx = (
                methods_result.get("context") if methods_result else None
            )
            _chem_name = (
                (_methods_ctx or {}).get("chemical_name")
                or compound_name
                or "the test article"
            )
            narratives = build_genomics_body_narratives(
                genomics_sections=genomics_sections,
                methods_context=_methods_ctx,
                chemical_name=_chem_name,
            )
            gene_set_narrative = narratives.get("gene_set_narrative")
            gene_narrative = narratives.get("gene_narrative")
            # Attach the LLM tier under each narrative dict so both
            # the HTML (read from by_organ_llm) and the PDF (export
            # payload passes it through to Typst) see the same data.
            if gene_set_narrative is not None:
                gene_set_narrative["by_organ_llm"] = llm_gs_by_organ
            if gene_narrative is not None:
                gene_narrative["by_organ_llm"] = llm_gene_by_organ
        except Exception as e:
            # Non-fatal — the PDF export path still auto-populates
            # on its own if the in-app response is missing this.
            logger.warning(
                "Genomics body narrative assembly failed: %s", e,
            )
    ctx.gene_set_narrative = gene_set_narrative
    ctx.gene_narrative = gene_narrative


async def _build_genomics_llm_narratives(ctx):
    """
    Layer 3.5a — LLM-generated per-{organ,sex} narratives.

    Runs the shared `generate_genomics_narrative_async` once per
    organ × sex, in parallel.  Each call does enrichment against
    bmdx.duckdb (cached in `_cache_interpretation_*.json`) and
    then one LLM call for the biology interpretation.  Per-sex
    results are aggregated under each organ into the narrative
    dict's `by_organ_llm` field so both HTML and PDF render
    identical analysis under each organ's table.
    """
    dtxsid = ctx.dtxsid
    genomics_sections = ctx.genomics_sections
    compound_name = ctx.compound_name
    bmd_stat = ctx.bmd_stat
    dose_unit = ctx.dose_unit

    llm_gs_by_organ: dict[str, list[str]] = {}
    llm_gene_by_organ: dict[str, list[str]] = {}
    if genomics_sections:
        try:
            from llm_routes import generate_genomics_narrative_async

            # Load identity from session for chemical name — used in
            # the LLM prompt's "{compound} exposure" phrasing.  Falls
            # back to the request's compound_name if identity is missing.
            _identity = {}
            _identity_path = _session_dir(dtxsid) / "identity.json"
            if _identity_path.exists():
                try:
                    _identity = json.loads(_identity_path.read_text())
                except Exception:
                    pass
            _llm_compound = _identity.get("name", compound_name)

            # Override file: user's Lock/Unlock edits persist here and
            # WIN over any freshly generated LLM output for the same
            # organ×kind pair.  Load once; pass into the merge below.
            _overrides = {"gene_set": {}, "gene_bmd": {}}
            _overrides_path = (
                _session_dir(dtxsid) / "genomics_narrative_overrides.json"
            )
            if _overrides_path.exists():
                try:
                    raw = json.loads(_overrides_path.read_text())
                    _overrides["gene_set"] = raw.get("gene_set", {}) or {}
                    _overrides["gene_bmd"] = raw.get("gene_bmd", {}) or {}
                except Exception:
                    pass

            async def _one(key, gen_data):
                """LLM-generate narrative for a single organ×sex."""
                organ = gen_data.get("organ", "")
                sex = gen_data.get("sex", "")
                gs_by_stat = gen_data.get("gene_sets_by_stat") or {}
                gene_sets_for_llm = gs_by_stat.get(bmd_stat) or []
                try:
                    return key, await generate_genomics_narrative_async(
                        dtxsid=dtxsid,
                        compound=_llm_compound,
                        organ=organ,
                        sex=sex,
                        gene_sets=gene_sets_for_llm,
                        top_genes=gen_data.get("top_genes") or [],
                        all_genes=gen_data.get("all_genes") or [],
                        total_responsive=gen_data.get("total_responsive_genes", 0),
                        dose_unit=dose_unit,
                    )
                except Exception as e:
                    logger.warning(
                        "LLM narrative failed for %s: %s", key, e,
                    )
                    return key, {"error": str(e)}

            # Parallel fanout — N calls, wall-clock ≈ one LLM call.
            tasks = [_one(k, v) for k, v in genomics_sections.items()]
            llm_results = await asyncio.gather(*tasks)

            # Bundle the per-sex LLM results under each organ, then fold
            # them into per-organ paragraph lists (male-then-female, sex-
            # labelled) with user overrides winning — all in the shared
            # `aggregate_organ_llm_narratives` helper so the session-reload
            # and Regenerate paths stay in lockstep with this one.
            per_organ_bundles: dict[str, dict[str, dict[str, list[str]]]] = {}
            for key, llm_out in llm_results:
                if not llm_out or "error" in llm_out:
                    continue
                organ = (genomics_sections[key].get("organ") or "").lower()
                sex = (genomics_sections[key].get("sex") or "").lower()
                per_organ_bundles.setdefault(organ, {})[sex] = {
                    "gs": llm_out.get("gene_set_narrative") or [],
                    "gn": llm_out.get("gene_narrative") or [],
                }

            from genomics_narratives import aggregate_organ_llm_narratives
            llm_gs_by_organ, llm_gene_by_organ = aggregate_organ_llm_narratives(
                per_organ_bundles, overrides=_overrides,
            )
        except Exception as e:
            logger.warning(
                "LLM narrative pipeline failed: %s", e,
            )
    ctx.llm_gs_by_organ = llm_gs_by_organ
    ctx.llm_gene_by_organ = llm_gene_by_organ


def _build_bmd_summary(ctx):
    """
    Layer 3 — BMD summary (depends on NTP + BMDS).

    Two summary tables: one from BMDExpress 3 results (apical) and
    one from pybmds results (BMDS).  Both need platform_tables +
    bmds_results, so they run after Layers 1 and 2 complete.
    """
    dtxsid = ctx.dtxsid
    platform_tables = ctx.platform_tables
    bmds_results = ctx.bmds_results

    bmd_summary_hash = _hash_bmd_summary(ctx.ntp_hash, ctx.bmds_hash)
    bmd_summary_cached = _load_cache(dtxsid, "bmd_summary", bmd_summary_hash)

    if bmd_summary_cached:
        apical_bmd_summary = bmd_summary_cached["apical"]
        apical_bmd_summary_bmds = bmd_summary_cached["bmds"]
    else:
        apical_bmd_summary = _build_apical_bmd_summary(platform_tables)
        apical_bmd_summary_bmds = _build_bmds_bmd_summary(
            platform_tables, bmds_results,
        )
        _save_cache(dtxsid, "bmd_summary", bmd_summary_hash, {
            "apical": apical_bmd_summary,
            "bmds": apical_bmd_summary_bmds,
        })
    ctx.apical_bmd_summary = apical_bmd_summary
    ctx.apical_bmd_summary_bmds = apical_bmd_summary_bmds


def _chart_types_fingerprint(registry: dict) -> dict:
    """
    A JSON-stable fingerprint of a chart-type registry for the charts cache key.

    The registry holds ChartType objects (not JSON-serializable); we key on each
    type's NAME + data spec — the only parts that change the rendered output.
    Code types (umap/cluster) contribute just their name; a data-driven type
    contributes its spec, so editing a chart_types declaration re-renders.
    """
    return {name: getattr(ct, "spec", {}) for name, ct in sorted(registry.items())}


async def _build_charts(ctx):
    """
    Layer 2.5 — Charts + Enrichr (depends on genomics output).

    Server-side Plotly rendering of UMAP scatter and cluster scatter
    charts, plus Enrichr enrichment analysis for each gene-overlap
    cluster.  Cached as _cache_charts_{hash}.json so that PDF
    previews and exports never re-render charts or re-call Enrichr.

    The hash is the same as genomics (same inputs determine the
    gene sets that feed the charts).  Chart images are base64 PNGs.
    """
    dtxsid = ctx.dtxsid
    genomics_sections = ctx.genomics_sections
    genomics_hash = ctx.genomics_hash
    bmd_stat = ctx.bmd_stat
    dose_unit = ctx.dose_unit

    chart_images = []
    if genomics_sections:
        # Chart styling + data-driven chart types are authored in the SAME
        # document template that drives structure (chart_style / chart_types
        # blocks).  Load the raw blocks (for the cache key) and the built
        # registry (for rendering).  Absent config ⇒ {} / built-in types ⇒
        # today's render.
        from document_tree import ACTIVE_TEMPLATE
        from document_template import load_chart_style, load_chart_types
        chart_style_cfg = load_chart_style(ACTIVE_TEMPLATE)
        chart_types_reg = load_chart_types(ACTIVE_TEMPLATE)

        # Bump _CHARTS_CACHE_SCHEMA_VERSION (defined near the other
        # cache schema constants) when the chart-rendering algorithm
        # itself changes — e.g. when the jitter formula is fixed.
        # The chart cache normally tracks the genomics_hash so that
        # changes to which gene sets exist propagate; mixing in the
        # charts schema version on top of that lets us invalidate
        # *only* the chart SVGs/PNGs without forcing the (expensive)
        # genomics + LLM narrative pipeline to re-run.  The chart
        # style/type config is folded in too, so editing the template's
        # chart blocks re-renders the charts without touching genomics.
        charts_hash = hashlib.sha256(
            json.dumps({
                "genomics_hash": genomics_hash,
                "charts_schema": _CHARTS_CACHE_SCHEMA_VERSION,
                "chart_style": chart_style_cfg,
                "chart_types": _chart_types_fingerprint(chart_types_reg),
            }, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        charts_cached = _load_cache(dtxsid, "charts", charts_hash)

        # Schema migration: caches written before SVGs were added to
        # the chart payload lack `umap_svg`/`cluster_svg`.  Shared
        # `cache_has_svg` probe + `render_chart_images_for_sections`
        # batch render live in genomics_viz so this code path and
        # the session-load migration stay in lockstep.
        from genomics_viz import (
            cache_has_svg, render_chart_images_for_sections,
        )

        if charts_cached and cache_has_svg(charts_cached):
            chart_images = charts_cached
        else:
            if charts_cached:
                logger.info(
                    "Chart cache for %s lacks SVG — re-rendering",
                    dtxsid,
                )
            # Run in the thread pool so we don't block the event
            # loop while Plotly+kaleido serialises figures.
            loop = asyncio.get_running_loop()
            chart_images = await loop.run_in_executor(
                None,
                lambda: render_chart_images_for_sections(
                    genomics_sections=genomics_sections,
                    bmd_stat=bmd_stat,
                    dose_unit=dose_unit,
                    chart_style_cfg=chart_style_cfg,
                    chart_types=chart_types_reg,
                ),
            )
            if chart_images:
                _save_cache(dtxsid, "charts", charts_hash, chart_images)
    ctx.chart_images = chart_images


async def _build_ntp_stats(ctx):
    """
    Layer 1 — NTP stats (depends only on integrated data + bmd_stat).

    This is the foundation: category lookup → filter GE experiments →
    build_table_data (Java Williams/Dunnett/Jonckheere) → partition
    by platform → annotate missing animals.  ~5s on miss.
    """
    dtxsid = ctx.dtxsid
    integrated = ctx.integrated
    bmd_stat = ctx.bmd_stat

    ntp_hash = _hash_ntp(integrated, bmd_stat)
    ntp_cached = _load_cache(dtxsid, "ntp", ntp_hash)

    if ntp_cached:
        platform_tables = _deserialize_platform_tables(ntp_cached)
    else:
        cat_lookup = _restore_category_lookup(integrated, bmd_stat)
        apical_integrated = _filter_gene_expression(integrated)
        # NOTE: legacy-vs-truth deduplication used to happen here via
        # _dedup_legacy_apical_experiments().  As of ADR-0001 step 4
        # that responsibility moved into the BMDProject schema —
        # load_integrated() returns already-deduped data and
        # save_integrated() rejects duplicates outright.  No fix-up
        # is needed in the processing path.

        loop = asyncio.get_running_loop()
        table_data = await loop.run_in_executor(
            None, build_table_data, apical_integrated, cat_lookup,
        )

        source_files = integrated.get("_meta", {}).get("source_files", {})
        platform_tables = _partition_by_platform(
            apical_integrated, source_files, table_data,
        )

        # Annotate missing animals from xlsx study file rosters —
        # compare bm2 N counts against xlsx Core Animals roster to
        # detect animals that died before terminal sacrifice.
        xlsx_rosters = integrated.get("_meta", {}).get("xlsx_rosters", {})
        if xlsx_rosters:
            annotate_missing_animals(platform_tables, xlsx_rosters)
            # Backfill absent dose columns with "–" so every platform
            # table shows the full study dose design (NIEHS convention).
            backfill_missing_doses(platform_tables, xlsx_rosters)

        _save_cache(
            dtxsid, "ntp", ntp_hash,
            _serialize_platform_tables(platform_tables),
        )
    ctx.platform_tables = platform_tables
    ctx.ntp_hash = ntp_hash


# ---------------------------------------------------------------------------
# Layer 2 units — Sections + BMDS + Genomics + Methods (independent, parallel)
# ---------------------------------------------------------------------------
# These four units depend on Layer 1 output but NOT on each other, so the
# orchestrator launches them concurrently via asyncio.gather.  BMDS (~8min)
# is the bottleneck; sections (<1s), genomics (~10s), and methods (one LLM
# call) finish quickly alongside it.  Each takes its pre-loaded cache + hash
# so the orchestrator owns the cache-key computation.


async def _get_sections(ctx):
    """Build section cards with narratives + unified narratives, or return cached."""
    dtxsid = ctx.dtxsid
    integrated = ctx.integrated
    platform_tables = ctx.platform_tables
    compound_name = ctx.compound_name
    dose_unit = ctx.dose_unit
    sections_hash = ctx.sections_hash
    # Organ-weight area allowlist — applied to the Organ Weight table and its
    # narrative (both cached in the sections blob, so this is folded into
    # sections_hash upstream — see _hash_sections at the Layer-0 hash step).
    ow_allow = (ctx.organ_filters or {}).get("organ-weight")
    # Apical sex allowlist — the platform-table-derived cards are already
    # narrowed by apply_apical_filters, but the two sidecar-built cards
    # (Tissue Concentration, Clinical Observations) bypass platform_tables and
    # are pruned by sex here.  Also folded into sections_hash upstream.
    apical_sex_allow = (ctx.sex_filters or {}).get("apical")

    sections_cached = _load_cache(dtxsid, "sections", sections_hash)
    if sections_cached:
        ctx.sections = sections_cached["sections"]
        ctx.unified_narratives = sections_cached.get("unified_narratives", {})
        return
    # _build_section_cards is sync (reads sidecar files, generates
    # narratives from templates) — wrap in executor to avoid
    # blocking the event loop during parallel execution.
    loop = asyncio.get_running_loop()
    # imputed_cells is recorded on _meta by the BMDProject schema's
    # legacy/truth dedup — see _dedupe_legacy_apical_pre.
    imputed_cells = integrated.get("_meta", {}).get("imputed_cells")
    sections = await loop.run_in_executor(
        None,
        lambda: _build_section_cards(
            platform_tables, compound_name, dose_unit,
            dtxsid=dtxsid, imputed_cells=imputed_cells,
            organ_allowlist=ow_allow, sex_allow=apical_sex_allow,
        ),
    )
    # Clinical obs tables bypass Java integration (categorical data).
    # Built separately and appended as an incidence section card.
    clin_obs = prune_card_sexes(
        _build_clinical_obs_section(integrated, compound_name, dose_unit),
        apical_sex_allow,
    )
    if clin_obs and clin_obs.get("tables_json"):
        sections.append(clin_obs)

    # ── Tissue Concentration (Table 7): pharmacokinetic table ──────
    # Tissue Concentration data only exists for Biosampling Animals
    # and is NOT processed through NTP stats or BMDExpress.  It has
    # no entries in platform_tables, so it must be built separately
    # from sidecar data (similar to Clinical Observations).
    if dtxsid:
        from table_builder_common import find_sidecar_paths as _find_sidecar
        from tissue_concentration_table import build_tissue_concentration_table_from_sidecar

        session_dir = str(_session_dir(dtxsid))
        tc_sidecar_paths = _find_sidecar(session_dir, platform="Tissue Concentration")
        if tc_sidecar_paths:
            tc_result = build_tissue_concentration_table_from_sidecar(
                sidecar_paths=tc_sidecar_paths,
                compound_name=compound_name,
                dose_unit=dose_unit,
            )
            # Prune by the apical sex allowlist (this card bypasses
            # platform_tables / apply_apical_filters).
            if tc_result and apical_sex_allow:
                from table_builder_common import sex_allowed
                tc_result["table_data"] = {
                    sex: rows
                    for sex, rows in (tc_result.get("table_data") or {}).items()
                    if sex_allowed(sex, apical_sex_allow)
                }
            if tc_result and tc_result.get("table_data"):
                narrative = (
                    f"Plasma concentrations of {compound_name} were "
                    f"measured in biosampling animals."
                )
                sections.append({
                    "platform": "Tissue Concentration",
                    "title": "Tissue Concentration",
                    "tables_json": tc_result["table_data"],
                    "narrative": narrative,
                    "first_col_header": tc_result.get("first_col_header"),
                    "caption": tc_result.get("caption"),
                    "footnotes": tc_result.get("footnotes"),
                    "table_type": tc_result.get("table_type"),
                })
                logger.info(
                    "Tissue Concentration section built from sidecar (%d sexes)",
                    len(tc_result["table_data"]),
                )

    # ── Unified cross-platform narratives ─────────────────────────
    # The NIEHS reference report groups narrative prose into two
    # unified sections that span multiple platforms, rather than
    # per-platform isolated narratives.  These are generated here
    # alongside the per-card narratives (which are kept for backward
    # compatibility with old approved sessions).
    from unified_narrative import (
        extract_mortality,
        generate_apical_narrative,
        generate_clinical_pathology_narrative,
    )
    from body_weight_table import find_sidecar_paths

    # 1. Load mortality data from body weight sidecars
    session_dir = str(_session_dir(dtxsid))
    sidecar_paths = find_sidecar_paths(session_dir, platform="Body Weight")
    sidecar_mortality = extract_mortality(sidecar_paths) if sidecar_paths else None

    # 2. Load clinical obs incidence for the animal condition paragraph
    meta = integrated.get("_meta", {})
    csv_paths = meta.get("clinical_obs_files", [])
    clin_obs_incidence = None
    if csv_paths:
        clin_obs_incidence = build_clinical_obs_tables(csv_paths)

    # 3. Generate the two unified narratives
    apical_narrative = generate_apical_narrative(
        platform_tables, compound_name, dose_unit,
        sidecar_mortality=sidecar_mortality,
        clinical_obs_incidence=clin_obs_incidence,
        organ_allowlist=ow_allow,
    )
    clin_path_narrative = generate_clinical_pathology_narrative(
        platform_tables, compound_name, dose_unit,
    )

    unified_narratives = {}
    if apical_narrative:
        unified_narratives["apical"] = {
            "title": "Animal Condition, Body Weights, and Organ Weights",
            "paragraphs": apical_narrative,
        }
    if clin_path_narrative:
        unified_narratives["clinical_pathology"] = {
            "title": "Clinical Pathology",
            "paragraphs": clin_path_narrative,
        }

    _save_cache(dtxsid, "sections", sections_hash, {
        "sections": sections,
        "unified_narratives": unified_narratives,
    })
    ctx.sections = sections
    ctx.unified_narratives = unified_narratives


async def _get_bmds(ctx):
    """Run pybmds modeling on all endpoints, or return cached."""
    dtxsid = ctx.dtxsid
    bmds_inputs = ctx.bmds_inputs
    bmds_hash = ctx.bmds_hash

    bmds_cached = _load_cache(dtxsid, "bmds", bmds_hash)
    if bmds_cached:
        ctx.bmds_results = bmds_cached
        return
    if not bmds_inputs:
        ctx.bmds_results = {}
        return
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(
        None, run_bmds_for_endpoints, bmds_inputs,
    )
    _save_cache(dtxsid, "bmds", bmds_hash, results)
    ctx.bmds_results = results


async def _get_genomics(ctx):
    """Extract gene expression + GO filtering, or return cached."""
    dtxsid = ctx.dtxsid
    genomics_hash = ctx.genomics_hash

    genomics_cached = _load_cache(dtxsid, "genomics", genomics_hash)
    if genomics_cached:
        ctx.genomics_sections = genomics_cached
    else:
        result = await _extract_genomics(
            dtxsid, ctx.integrated, ctx.bmd_stats,
            ctx.go_pct, ctx.go_min_genes, ctx.go_max_genes, ctx.go_min_bmd,
        )
        # Cache the FULL (unfiltered) extraction so editing the organ allowlist
        # re-filters instantly without re-running the costly extraction.
        _save_cache(dtxsid, "genomics", genomics_hash, result)
        ctx.genomics_sections = result

    # Genomics post-filter — the single genomics choke point shared with the
    # Overleaf export (latex_export.load_session_data calls the SAME
    # filter_genomics_sections so both surfaces agree).  Applied AFTER the cache
    # save so the genomics cache stays filter-agnostic and editing any allowlist
    # re-filters instantly without re-running the costly extraction.  Drops
    # whole organ/sex sections and prunes the per-section gene / gene-set lists;
    # the result cascades to charts, narratives, and the gene tables, which all
    # read this dict.
    if ctx.genomics_sections:
        from table_builder_common import filter_genomics_sections
        ctx.genomics_sections = filter_genomics_sections(
            ctx.genomics_sections,
            organ=(ctx.organ_filters or {}).get("genomics"),
            sex=(ctx.sex_filters or {}).get("genomics"),
            genes=ctx.gene_filter,
            gene_sets=ctx.gene_set_filter,
        )


async def _get_methods(ctx):
    """
    Generate Materials and Methods via LLM, or return cached.

    Extracts study metadata from fingerprints, animal report, and
    .bm2 caches (dose groups, sample sizes, BMDExpress parameters),
    then calls the LLM to produce structured prose for each NIEHS
    M&M subsection.  The result is cached so subsequent calls
    (page reloads, PDF exports) return instantly.
    """
    dtxsid = ctx.dtxsid
    integrated = ctx.integrated
    fps_for_methods = ctx.fps_for_methods
    methods_hash = ctx.methods_hash

    methods_cached = _load_cache(dtxsid, "methods", methods_hash)
    if methods_cached:
        ctx.methods_result = methods_cached
        return

    from methods_report import (
        MethodsReport,
        MethodsSection,
        build_methods_prompt,
        build_subsection_skeleton,
        build_table1_data,
        extract_methods_context,
    )
    from bmdx_pipe import bm2_cache as _bm2_cache

    # Load identity from session (chemical name, casrn, dtxsid)
    identity = {"dtxsid": dtxsid}
    identity_path = _session_dir(dtxsid) / "identity.json"
    if identity_path.exists():
        try:
            identity = json.loads(identity_path.read_text())
        except Exception:
            pass

    # Collect .bm2 JSON caches for BMDExpress metadata extraction
    bm2_jsons = {}
    session_files_dir = _session_dir(dtxsid) / "files"
    if session_files_dir.exists():
        for bm2_path in session_files_dir.glob("*.bm2"):
            try:
                cached = _bm2_cache.get_json(str(bm2_path))
                if cached:
                    bm2_jsons[bm2_path.stem] = cached
            except Exception:
                pass

    # Load animal report from session
    animal_report_data = None
    ar_path = _session_dir(dtxsid) / "animal_report.json"
    if ar_path.exists():
        try:
            animal_report_data = json.loads(ar_path.read_text())
        except Exception:
            pass

    # Default study params — the NIEHS 5-day gavage protocol
    study_params = {
        "vehicle": "corn oil",
        "route": "gavage",
        "duration_days": 5,
        "species": "Sprague Dawley",
    }

    # Extract structured context from all data sources.
    # Pass session_dir so biosampling dose groups can be scanned
    # from sidecar files, and integrated so the genomics assay
    # (e.g., TempO-Seq) can be identified from chip metadata.
    methods_ctx = extract_methods_context(
        identity=identity,
        fingerprints=fps_for_methods,
        animal_report=animal_report_data,
        study_params=study_params,
        bm2_jsons=bm2_jsons,
        session_dir=str(_session_dir(dtxsid)),
        integrated=integrated,
    )

    # Build and call the LLM
    system, prompt = build_methods_prompt(methods_ctx)
    try:
        subsection_texts = await _llm_generate_json_async(
            "methods-generator", prompt, system,
        )
    except Exception as e:
        logger.warning("Methods LLM generation failed: %s", e)
        ctx.methods_result = None
        return

    # Assemble into structured sections
    skeleton = build_subsection_skeleton(methods_ctx)
    sections = []
    for key, heading, level in skeleton:
        text = subsection_texts.get(key, "")
        if not text:
            continue
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        sections.append(MethodsSection(
            heading=heading,
            level=level,
            key=key,
            paragraphs=paragraphs,
        ))

    table1 = build_table1_data(methods_ctx)
    report = MethodsReport(sections=sections, context=methods_ctx)
    report_dict = report.to_dict()

    if table1:
        report_dict["table1"] = table1

    report_dict["section_key"] = "methods"
    report_dict["model_used"] = "claude-sonnet-4-6"

    _save_cache(dtxsid, "methods", methods_hash, report_dict)
    ctx.methods_result = report_dict


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

@router.post("/api/process-integrated/{dtxsid}")
async def api_process_integrated(dtxsid: str, request: Request):
    """
    Process the integrated BMDProject JSON into section cards with tables
    and narratives for each apical endpoint platform.

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

    Orchestrates the processing pipeline:
      1. Load integrated data (memory or disk)
      2. Check disk cache (return instantly on hit)
      3. Restore category lookup from serialized keys
      4. Filter gene expression experiments
      5. Run NTP stats (Williams trend + Dunnett's pairwise + Jonckheere)
      6. Partition results by platform
      7. Build section cards with narratives
      8. Run BMDS modeling (pybmds)
      9. Extract genomics from gene expression .bm2
      10. Build BMD summaries (BMDExpress 3 + BMDS)
      11. Cache and return
    """
    # --- Parse request parameters ---
    # Tolerate empty or missing request bodies — the UI sometimes sends
    # POST with no content (e.g., from a simple fetch without JSON body).
    try:
        body = await request.json()
    except Exception:
        body = {}
    compound_name = body.get("compound_name", "Test Compound")
    dose_unit = body.get("dose_unit", "mg/kg")

    # BMD statistics — array of stat keys, each producing a separate GO table.
    # Accepts both the old single "bmd_stat" and the new "bmd_stats" array.
    bmd_stats_raw = body.get("bmd_stats", None)
    bmd_stats = bmd_stats_raw if bmd_stats_raw and isinstance(bmd_stats_raw, list) \
        else [body.get("bmd_stat", "median")]
    bmd_stat = bmd_stats[0]  # primary stat for category lookup

    # GO category filter cutoffs from the Settings panel
    go_pct = body.get("go_pct", 5)
    go_min_genes = body.get("go_min_genes", 20)
    go_max_genes = body.get("go_max_genes", 500)
    go_min_bmd = body.get("go_min_bmd", 3)

    # Per-area organ allowlist from the active template's `organs:` block
    # ({area: [tokens]}; {} ⇒ no filtering).  Loaded from the template like the
    # chart config.  See document_template.load_report_organs.
    from document_tree import ACTIVE_TEMPLATE
    from document_template import (
        load_report_organs,
        load_report_sex,
        load_report_assays,
        load_report_genes,
        load_report_gene_sets,
    )
    organ_filters = load_report_organs(ACTIVE_TEMPLATE)
    sex_filters = load_report_sex(ACTIVE_TEMPLATE)
    assay_filters = load_report_assays(ACTIVE_TEMPLATE)
    gene_filter = load_report_genes(ACTIVE_TEMPLATE)
    gene_set_filter = load_report_gene_sets(ACTIVE_TEMPLATE)

    # --- Load integrated data ---
    integrated = _load_integrated(dtxsid)
    if not integrated:
        return JSONResponse(
            {"error": "No integrated data found -- run integration first"},
            status_code=400,
        )

    # Bundle the parsed request inputs into the context object threaded
    # through every Layer.  Accumulated state (platform_tables, hashes,
    # cached blobs, each Layer's output) is filled in as the pipeline runs.
    ctx = ProcessContext(
        dtxsid=dtxsid,
        integrated=integrated,
        compound_name=compound_name,
        dose_unit=dose_unit,
        bmd_stats=bmd_stats,
        bmd_stat=bmd_stat,
        go_pct=go_pct,
        go_min_genes=go_min_genes,
        go_max_genes=go_max_genes,
        go_min_bmd=go_min_bmd,
        organ_filters=organ_filters,
        sex_filters=sex_filters,
        assay_filters=assay_filters,
        gene_filter=gene_filter,
        gene_set_filter=gene_set_filter,
    )

    # --- Migrate old monolithic cache files ---
    # The old _processed_cache_{hash}.json format is replaced by per-section
    # caches.  Delete any leftover monolithic files so they don't accumulate.
    for old_cache in _session_dir(dtxsid).glob("_processed_cache_*.json"):
        old_cache.unlink(missing_ok=True)
        logger.info("Migrated old monolithic cache: %s", old_cache.name)

    try:
        # ══════════════════════════════════════════════════════════════
        # Layer 1 — NTP stats (depends only on integrated data + bmd_stat)
        # ══════════════════════════════════════════════════════════════
        await _build_ntp_stats(ctx)

        # Report-level SEX + ASSAY allowlists — the single apical choke point.
        # Applied unconditionally right after the NTP layer (even on a cache
        # hit), so the NTP cache stays sex/assay-agnostic and EVERY downstream
        # consumer of platform_tables (apical tables, BMD summary, BMDS inputs,
        # narratives) sees the same filtered set.  No-op when neither is set.
        ctx.platform_tables = apply_apical_filters(
            ctx.platform_tables,
            sex_allow=(ctx.sex_filters or {}).get("apical"),
            assay_filters=ctx.assay_filters,
        )

        # ══════════════════════════════════════════════════════════════
        # Layer 2 — Sections + BMDS + Genomics (independent, parallel)
        # ══════════════════════════════════════════════════════════════
        # These three units depend on Layer 1 output but NOT on each other,
        # so they can run concurrently.  BMDS (~8min) is the bottleneck;
        # sections (<1s) and genomics (~10s) finish quickly alongside it.
        # The preamble below computes each unit's cache key onto ctx; each
        # unit loads its own cache from that key.

        # Collect _bmds_input dicts from all TableRows for BMDS modeling.
        # Runs AFTER Layer 1 (and the apical filter) so platform_tables is
        # populated AND already narrowed — dropped sexes/assays aren't modeled.
        ctx.bmds_inputs = [
            row._bmds_input
            for sex_rows in ctx.platform_tables.values()
            for rows in sex_rows.values()
            for row in rows
            if hasattr(row, "_bmds_input") and row._bmds_input
        ]

        # Compute per-unit hashes.  The sections stage reads sidecar JSONs
        # and the clinical-obs CSVs straight off disk and uses
        # _meta.imputed_cells — none of which flow through ntp_hash — so fold
        # a fingerprint of those inputs into the sections key, otherwise
        # editing a sidecar would silently serve a stale report.
        _meta = integrated.get("_meta", {})
        sections_sidecar_hash = _hash_sidecars(
            str(_session_dir(dtxsid)),
            extra_paths=_meta.get("clinical_obs_files", []),
        )
        ctx.sections_hash = _hash_sections(
            ctx.ntp_hash, compound_name, dose_unit,
            sidecar_hash=sections_sidecar_hash,
            imputed_cells=_meta.get("imputed_cells"),
            organ_allowlist=(ctx.organ_filters or {}).get("organ-weight"),
            sex_allowlist=(ctx.sex_filters or {}).get("apical"),
            assay_filters=ctx.assay_filters,
        )
        ctx.bmds_hash = _hash_bmds(ctx.bmds_inputs) if ctx.bmds_inputs else "empty"

        ge_source = _meta.get("source_files", {}).get("gene_expression")
        ge_filename = ge_source.get("filename", "") if ge_source else ""
        ctx.genomics_hash = _hash_genomics(
            bmd_stats, go_pct, go_min_genes, go_max_genes, go_min_bmd,
            ge_filename,
        )

        # --- Materials and Methods (LLM-generated, cached) ---
        # Uses fingerprints + .bm2 metadata + animal report to extract
        # study context, then calls the LLM to produce structured prose
        # for each M&M subsection.  Runs in parallel with the other
        # Layer 2 tasks since it has no dependency on NTP stats output.

        # Collect fingerprints as plain dicts for the methods context extractor
        _fps_for_methods = {}
        session_fps = _pool_fingerprints.get(dtxsid, {})
        for fid, fp in session_fps.items():
            if hasattr(fp, "__dataclass_fields__"):
                _fps_for_methods[fid] = {
                    k: getattr(fp, k) for k in fp.__dataclass_fields__
                }
            else:
                _fps_for_methods[fid] = fp
        ctx.fps_for_methods = _fps_for_methods
        ctx.methods_hash = _hash_methods(dtxsid, _fps_for_methods)

        # Launch all four concurrently — cached units return instantly,
        # uncached units run in parallel (BMDS in thread pool, genomics
        # in thread pool via _extract_genomics, sections in thread pool,
        # methods via async LLM call).  Each writes its output onto ctx;
        # they touch disjoint fields so the shared object is safe under
        # asyncio's single-threaded cooperative scheduling.
        await asyncio.gather(
            _get_sections(ctx),
            _get_bmds(ctx),
            _get_genomics(ctx),
            _get_methods(ctx),
        )

        # ══════════════════════════════════════════════════════════════
        # Layer 2.5 — Charts + Enrichr (depends on genomics output)
        # ══════════════════════════════════════════════════════════════
        await _build_charts(ctx)

        # ══════════════════════════════════════════════════════════════
        # Layer 3 — BMD summary (depends on NTP + BMDS)
        # ══════════════════════════════════════════════════════════════
        _build_bmd_summary(ctx)

        # ══════════════════════════════════════════════════════════════
        # Layer 3.5a — LLM-generated per-{organ,sex} narratives
        # ══════════════════════════════════════════════════════════════
        await _build_genomics_llm_narratives(ctx)

        # ══════════════════════════════════════════════════════════════
        # Layer 3.5b — Deterministic body narratives
        # ══════════════════════════════════════════════════════════════
        _build_genomics_body_narratives(ctx)

        # ══════════════════════════════════════════════════════════════
        # Layer 3.5c — Apical BMD Summary narratives
        # ══════════════════════════════════════════════════════════════
        await _build_apical_bmd_narrative(ctx)

        # ══════════════════════════════════════════════════════════════
        # Assembly — combine all results into response payload
        # ══════════════════════════════════════════════════════════════
        # Identical structure to the old monolithic response so the
        # frontend doesn't need any changes.
        stat_labels = {
            s: _BMD_STAT_LABELS.get(s, s.replace("_", " ").title())
            for s in bmd_stats
        }
        result_payload = {
            "sections": ctx.sections,
            "unified_narratives": ctx.unified_narratives,
            "genomics_sections": ctx.genomics_sections,
            # Per-organ body narratives for Gene Set / Gene BMD — HTML
            # renders `by_organ[organ]` above each organ's table; PDF
            # export consumes the same dict via marshal_export_data.
            "gene_set_narrative": ctx.gene_set_narrative,
            "gene_narrative": ctx.gene_narrative,
            "chart_images": ctx.chart_images if ctx.chart_images else None,
            "apical_bmd_summary": ctx.apical_bmd_summary,
            "apical_bmd_summary_bmds": ctx.apical_bmd_summary_bmds,
            # Apical BMD Summary section narratives (descriptive +
            # analytical).  The flat "paragraphs" list is consumed by
            # report_data.py and the frontend BMD summary card.
            "apical_bmd_narrative": ctx.apical_bmd_narrative,
            "bmd_stats": list(bmd_stats),
            "bmd_stat_labels": stat_labels,
            # Materials and Methods — LLM-generated structured sections.
            # Included so the frontend can auto-populate the M&M section
            # without requiring a separate generate button click.
            "methods": ctx.methods_result,
        }

        return JSONResponse(result_payload)

    except Exception as e:
        logger.exception("Processing integrated data failed for %s", dtxsid)
        return JSONResponse(
            {"error": f"Processing failed: {e}"},
            status_code=500,
        )


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
    """
    session_path = _session_dir(dtxsid)
    files_dir = session_path / "files"

    if not files_dir.exists():
        return JSONResponse(
            {"error": "No files directory found for this session"},
            status_code=404,
        )

    # Ensure we have fingerprints -- re-fingerprint if the pool is empty.
    # This can happen if the server restarted since the last validation.
    fps = ensure_fingerprints(dtxsid)

    if not fps:
        return JSONResponse(
            {"error": "No fingerprinted files found -- upload files first"},
            status_code=400,
        )

    # Build the animal report in a thread executor to avoid blocking
    # the event loop (xlsx/bm2 parsing can take a few seconds).
    loop = asyncio.get_running_loop()
    try:
        report = await loop.run_in_executor(
            None,
            build_animal_report,
            str(session_path),
            fps,
        )
    except Exception as e:
        logger.exception("Failed to build animal report for %s", dtxsid)
        return JSONResponse(
            {"error": f"Animal report generation failed: {e}"},
            status_code=500,
        )

    # Serialize and persist to disk
    report_dict = report_to_dict(report)
    report_path = session_path / "animal_report.json"
    report_path.write_text(
        json.dumps(report_dict, indent=2, default=str),
        encoding="utf-8",
    )

    return Response(
        content=orjson.dumps(report_dict),
        media_type="application/json",
    )
