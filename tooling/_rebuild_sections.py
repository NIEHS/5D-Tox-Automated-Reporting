"""Dev helper: rebuild ONLY the cheap deterministic Layer-2/3 caches (sections,
bmd_summary) for a session, reusing the on-disk NTP/BMDS/genomics/methods caches.

This lets us iterate on the apical table builders (organ weight, hormones, BMD
summary) without re-running the ~8min BMDS / Java / LLM stages.  It drives the
SAME orchestrator layer functions the app uses, so the output is faithful.

Not part of the shipped surface.
"""
import asyncio
import sys

import pipeline.process_integrated as P
from pipeline.process_integrated import ProcessContext, _build_ntp_stats, _get_sections, _build_bmd_summary
from pipeline.pool_globals import _session_dir
from document_model.document_tree import ACTIVE_TEMPLATE
from document_model.document_template import (
    load_report_organs, load_report_sex, load_report_assays,
    load_report_genes, load_report_gene_sets,
)

DTXSID = sys.argv[1] if len(sys.argv) > 1 else "DTXSID50469320"
COMPOUND = "Perfluorohexanesulfonamide"
DOSE_UNIT = "mg/kg"


def _load_integrated(dtxsid):
    # Mirror the orchestrator's integrated load.
    return P._load_integrated(dtxsid)


async def main():
    integrated = _load_integrated(DTXSID)
    if not integrated:
        raise SystemExit(f"no integrated data for {DTXSID}")

    ctx = ProcessContext(
        dtxsid=DTXSID,
        integrated=integrated,
        compound_name=COMPOUND,
        dose_unit=DOSE_UNIT,
        bmd_stats=["median"],
        bmd_stat="median",
        go_pct=5, go_min_genes=20, go_max_genes=500, go_min_bmd=3,
        organ_filters=load_report_organs(ACTIVE_TEMPLATE),
        sex_filters=load_report_sex(ACTIVE_TEMPLATE),
        assay_filters=load_report_assays(ACTIVE_TEMPLATE),
        gene_filter=load_report_genes(ACTIVE_TEMPLATE),
        gene_set_filter=load_report_gene_sets(ACTIVE_TEMPLATE),
    )

    # Layer 1: NTP (reuses ntp cache -> no Java).
    await _build_ntp_stats(ctx)
    ctx.platform_tables = P.apply_apical_filters(
        ctx.platform_tables,
        sex_allow=(ctx.sex_filters or {}).get("apical"),
        assay_filters=ctx.assay_filters,
    )

    # Compute the sections hash exactly as the orchestrator does, then DELETE the
    # stale sections cache so _get_sections rebuilds (our logic changed; the hash
    # did not, so the same file is overwritten).
    _meta = integrated.get("_meta", {})
    sections_sidecar_hash = P._hash_sidecars(
        str(_session_dir(DTXSID)),
        extra_paths=_meta.get("clinical_obs_files", []),
    )
    ctx.sections_hash = P._hash_sections(
        ctx.ntp_hash, COMPOUND, DOSE_UNIT,
        sidecar_hash=sections_sidecar_hash,
        imputed_cells=_meta.get("imputed_cells"),
        organ_allowlist=(ctx.organ_filters or {}).get("organ-weight"),
        sex_allowlist=(ctx.sex_filters or {}).get("apical"),
        assay_filters=ctx.assay_filters,
        ow_sex_allowlist=(ctx.sex_filters or {}).get("organ-weight"),
    )
    sec_file = _session_dir(DTXSID) / f"_cache_sections_{ctx.sections_hash}.json"
    for old in _session_dir(DTXSID).glob("_cache_sections_*.json"):
        old.unlink()
        print("deleted stale sections cache:", old.name)

    # Rebuild sections (organ weight, hormones, clin-path, etc.).
    await _get_sections(ctx)
    print("rebuilt sections cache:", sec_file.name)

    # BMD summary (Table 8) depends on NTP + BMDS; reuse the bmds cache.
    ctx.bmds_inputs = [
        row._bmds_input
        for sex_rows in ctx.platform_tables.values()
        for rows in sex_rows.values()
        for row in rows
        if hasattr(row, "_bmds_input") and row._bmds_input
    ]
    ctx.bmds_hash = P._hash_bmds(ctx.bmds_inputs) if ctx.bmds_inputs else "empty"
    await P._get_bmds(ctx)
    # Clear the stale bmd_summary cache (logic changed; hash did not).
    for old in _session_dir(DTXSID).glob("_cache_bmd_summary_*.json"):
        old.unlink()
        print("deleted stale bmd_summary cache:", old.name)
    _build_bmd_summary(ctx)
    print("rebuilt bmd summary (endpoints:", len(ctx.apical_bmd_summary or []), ")")


if __name__ == "__main__":
    asyncio.run(main())
