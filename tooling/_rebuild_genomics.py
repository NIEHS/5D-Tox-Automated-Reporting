"""Dev helper: regenerate the genomics cache (_cache_genomics_*.json) for a
session by re-running the real _extract_genomics pipeline layer.

Requires the Java extraction to work — set before running:
  export BMDX_PROJECT_ROOT=/workspace/BMDExpress-3
  export PATH=/opt/liberica-jdk-21/bin:$PATH

Not part of the shipped surface.
"""
import asyncio
import sys

import process_integrated as P
from pool_globals import _session_dir
from cache_plumbing import _hash_genomics

DTXSID = sys.argv[1] if len(sys.argv) > 1 else "DTXSID50469320"


async def main():
    integrated = P._load_integrated(DTXSID)
    if not integrated:
        raise SystemExit(f"no integrated data for {DTXSID}")

    bmd_stats = ["median"]
    go_pct, go_min_genes, go_max_genes, go_min_bmd = 5, 20, 500, 3

    result = await P._extract_genomics(
        DTXSID, integrated, bmd_stats,
        go_pct, go_min_genes, go_max_genes, go_min_bmd,
    )

    meta = integrated.get("_meta", {})
    ge_source = meta.get("source_files", {}).get("gene_expression")
    ge_filename = ge_source.get("filename", "") if ge_source else ""
    ghash = _hash_genomics(
        bmd_stats, go_pct, go_min_genes, go_max_genes, go_min_bmd, ge_filename,
    )

    # Delete stale genomics caches, then write fresh (same hash → same filename).
    for old in _session_dir(DTXSID).glob("_cache_genomics_*.json"):
        old.unlink()
        print("deleted stale genomics cache:", old.name)
    P._save_cache(DTXSID, "genomics", ghash, result)
    print("wrote _cache_genomics_%s.json (%d sections)" % (ghash, len(result)))
    for k, v in result.items():
        gs = (v.get("gene_sets_by_stat") or {}).get("median") or []
        tg = v.get("top_genes") or []
        print(f"  {k}: gene_sets={len(gs)} top_genes={len(tg)}"
              + (f"  gs0_keys={list(gs[0].keys())}" if gs else "")
              + (f"  tg0_keys={list(tg[0].keys())}" if tg else ""))


if __name__ == "__main__":
    asyncio.run(main())
