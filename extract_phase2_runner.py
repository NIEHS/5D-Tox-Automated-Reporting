"""Run Phase 2 extraction across all 9 new crawl dirs."""
import time
from extract import ParallelExtractionEngine

DIRS = [
    "citegraph_output_nrf2dose",
    "citegraph_output_inflammasome",
    "citegraph_output_celldeath",
    "citegraph_output_circadian",
    "citegraph_output_senescence",
    "citegraph_output_intestine",
    "citegraph_output_testis",
    "citegraph_output_vascular",
    "citegraph_output_genetox",
]

t0 = time.time()
for d in DIRS:
    print(f"\n{'#'*60}")
    print(f"# EXTRACTING: {d}")
    print(f"{'#'*60}")
    engine = ParallelExtractionEngine()
    extractions = engine.process_papers(f"{d}/papers.json")
    engine.save(extractions, f"{d}/extractions.json")

elapsed = time.time() - t0
print(f"\n\nALL EXTRACTIONS COMPLETE in {elapsed:.0f}s ({elapsed/60:.1f} min)")
