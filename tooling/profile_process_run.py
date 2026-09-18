"""Per-layer wall-clock profile of pipeline.process_integrated.run_process.

Wraps every Layer 1 / 2 / 2.5 / 3 / 3.5a-d function and _build_query_substrate
in a timer, then drives run_process directly (not through the HTTP worker) so we
get a real cold-run breakdown. Confirms/refutes the prior diagnosis that the
session.duckdb build — not the LLM — is the long pole.

Run:  <live-pipeline env> python tooling/profile_process_run.py DTXSID50469320
Caches for the session should be cleared first for a COLD run (the harness does
NOT clear them — the caller decides, so a warm-vs-cold delta can be measured).
"""
import asyncio
import sys
import time

import pipeline.process_integrated as P

# (attr name on the module, human label, layer tag)
_LAYERS = [
    ("_build_ntp_stats",              "Layer 1  NTP stats",            "compute"),
    ("_get_sections",                 "Layer 2  sections",            "compute"),
    ("_get_bmds",                     "Layer 2  BMDS modeling",       "compute"),
    ("_get_genomics",                 "Layer 2  genomics extract",    "compute"),
    ("_get_methods",                  "Layer 2  methods (LLM)",       "llm"),
    ("_build_charts",                 "Layer 2.5 charts + enrichr",   "compute"),
    ("_build_bmd_summary",            "Layer 3  BMD summary",         "compute"),
    ("_build_genomics_llm_narratives","Layer 3.5a genomics LLM narr", "llm"),
    ("_build_genomics_body_narratives","Layer 3.5b body narratives",  "compute"),
    ("_build_apical_bmd_narrative",   "Layer 3.5c apical BMD narr",   "llm"),
    ("_build_query_substrate",        "Substrate session.duckdb",     "duckdb"),
]

_timings: list[tuple[str, str, float]] = []


def _wrap(name, label, tag):
    orig = getattr(P, name)
    if asyncio.iscoroutinefunction(orig):
        async def wrapper(*a, **k):
            t0 = time.perf_counter()
            try:
                return await orig(*a, **k)
            finally:
                _timings.append((label, tag, time.perf_counter() - t0))
        wrapper.__name__ = name
        setattr(P, name, wrapper)
    else:
        def wrapper(*a, **k):
            t0 = time.perf_counter()
            try:
                return orig(*a, **k)
            finally:
                _timings.append((label, tag, time.perf_counter() - t0))
        wrapper.__name__ = name
        setattr(P, name, wrapper)


async def main(dtxsid: str):
    from workflow.store import DiskPoolStore
    for name, label, tag in _LAYERS:
        _wrap(name, label, tag)

    # Ensure fingerprints are in the in-memory pool (methods layer reads them).
    store = DiskPoolStore()
    try:
        store.ensure_fingerprints(dtxsid)
    except Exception as e:
        print(f"[warn] ensure_fingerprints: {e}")

    params = {"compound_name": "Perfluorohexanesulfonamide", "dose_unit": "mg/kg",
              "bmd_stats": ["median"]}

    t0 = time.perf_counter()
    await P.run_process(dtxsid, params, store)
    total = time.perf_counter() - t0

    print("\n================ PER-LAYER WALL CLOCK ================")
    _timings.sort(key=lambda r: r[2], reverse=True)
    measured = sum(t for _, _, t in _timings)
    for label, tag, dt in _timings:
        pct = 100 * dt / total
        bar = "#" * int(pct / 2)
        print(f"  {dt:7.1f}s {pct:5.1f}%  [{tag:7}] {label:32} {bar}")
    print("  " + "-" * 60)
    print(f"  {measured:7.1f}s        (sum of measured layers)")
    print(f"  {total:7.1f}s        TOTAL run_process")
    print(f"  {total-measured:7.1f}s        (unmeasured: assembly/hashing/orchestration)")

    # Roll up by tag
    print("\n================ ROLLUP BY KIND ====================")
    kinds: dict[str, float] = {}
    for _, tag, dt in _timings:
        kinds[tag] = kinds.get(tag, 0) + dt
    for tag, dt in sorted(kinds.items(), key=lambda x: -x[1]):
        print(f"  {dt:7.1f}s {100*dt/total:5.1f}%  {tag}")


if __name__ == "__main__":
    dtxsid = sys.argv[1] if len(sys.argv) > 1 else "DTXSID50469320"
    asyncio.run(main(dtxsid))
