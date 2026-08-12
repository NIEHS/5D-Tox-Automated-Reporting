"""
Read/write barrier for integrated.json — the BMDProject seam.

bmdx-pipe produces sessions/{dtxsid}/integrated.json (the merged
"BMDProject" dict).  Every consumer in rlm-bmdx — table builders, NTP
stats, BMDS modeling, genomics extraction, export — reads from it.
This module is the single chokepoint through which that read passes,
plus the single chokepoint for writing it back when the metadata-edit
UI mutates fields.

ADR-0001 (docs/adr/0001-bmdproject-schema-as-load-barrier.md) sets out
why: bmdx-pipe is a separate project and the integrated.json contract
is informal.  Without a validation gate, schema drift surfaces as
confusing errors deep in the pipeline (the 2026-05-10 customer-facing
duplicate-experiments bug being the precedent).  load_integrated and
save_integrated together close that gate: nothing reaches downstream
consumers unvalidated, and nothing gets written without first passing
the schema.

What lives here:

  - _load_integrated      — read + cache + validate.  Prefers the
    in-memory `_integrated_pool` cache (pool_globals); falls back to
    disk.  Validates every call (sub-100ms cost, accepted per ADR).
    The `_category_lookup.json` sidecar gets merged back in at read
    time.
  - load_integrated       — the public alias.  External modules
    (export_routes, llm_routes, session_routes) import this name,
    not the underscore-prefixed form.
  - save_integrated       — validate first, then persist.  Inverts
    the load barrier on the write side: invalid data never reaches
    disk in the first place.  Updates the in-memory cache after a
    successful write.
  - api_integrated_full   — GET /api/integrated/{dtxsid} — stream
    integrated.json straight from disk (chunked, for Oboe.js).
  - api_integrated_summary — GET /api/integrated-summary/{dtxsid} —
    lightweight summary view (counts + per-experiment probe counts;
    full response arrays stay server-side).

Supporting helpers (numeric coercion + GO-stat picker + source-files
backfill) also live here because they are first-call dependencies of
_load_integrated and api_integrated_summary.  A few of them
(_safe_float, _safe_float_from_bmdl, _pick_go_stat) are also reached
for by the process-integrated god function elsewhere; that call site
keeps working via the pool_orchestrator re-export shim.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import json
import logging

from fastapi.responses import FileResponse, JSONResponse

from pipeline.bmd_project_schema import (
    BMDProjectValidationError,
    load_and_validate as _load_and_validate_bmd_project,
)

from pipeline.pool_globals import router, _session_dir, _integrated_pool


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Numeric coercion helpers
# ---------------------------------------------------------------------------
# Java serializes NaN/Infinity as the strings "NaN"/"Infinity", and BMDS
# results use formatted strings ("<0.1", "NVM", "UREP", "—") that need a
# numeric sort key.  These helpers keep the surrounding logic clean.

def _safe_float(val, default=float("inf")):
    """
    Coerce a value to float, returning *default* for None, NaN, or unparseable
    strings.  Used for sorting BMD values where Java serializes NaN/Infinity
    as strings.
    """
    if val is None:
        return default
    try:
        v = float(val)
        # NaN sorts inconsistently — treat as infinity
        return default if v != v else v
    except (TypeError, ValueError):
        return default


def _safe_float_from_bmdl(bmdl_str: str, default=float("inf")) -> float:
    """
    Extract a numeric sort key from a formatted BMDL string.

    BMDL strings can be:
      - numeric: "12.3", "0.00679"
      - NR threshold: "<0.1" (strip the '<' prefix)
      - status codes: "NVM", "UREP", "—" → sort to end (infinity)

    Used to sort BMD summary tables by BMDL within each sex group,
    so the most potent (lowest BMDL) endpoints appear first.
    """
    if not bmdl_str or bmdl_str in ("—", "NVM", "UREP", "ND"):
        return default
    # Strip "<" prefix from NR thresholds like "<0.1"
    cleaned = bmdl_str.lstrip("<")
    return _safe_float(cleaned, default)


def _pick_go_stat(go_entry: dict, metric: str, stat: str):
    """
    Pick a specific BMD statistic from a GO category's stat block.

    Returns None (not a fallback) if the stat isn't available, so that
    categories missing the stat get excluded from the table rather than
    showing a misleading value from a different statistic.

    Args:
        go_entry: A GO BP category dict with optional bmd_stats/bmdl_stats blocks.
        metric:   "bmd", "bmdl", or "bmdu".
        stat:     The statistic key (e.g., "mean", "median", "fifth_pct").
    """
    block = go_entry.get(f"{metric}_stats", {})
    if block:
        return block.get(stat)
    # Legacy data only has median (pre-stat-block format)
    if stat == "median":
        return go_entry.get(f"{metric}_median")
    return None


# ---------------------------------------------------------------------------
# Source-files experiment-count backfill
# ---------------------------------------------------------------------------

def _enrich_source_experiment_counts(
    source_files: dict[str, dict],
    experiments: list[dict],
) -> None:
    """
    Backfill experiment_count on each source_files entry.

    Uses bidirectional substring matching: checks if the normalized platform
    name is in the experiment name OR vice versa (handles abbreviations like
    "tissue_conc" matching "Tissue Concentration").  Falls back to augmented
    ExperimentDescription metadata.  When multiple source_files entries share
    the same base platform (e.g., "Hematology|tox_study" and
    "Hematology|inferred"), both get the count.

    Mutates source_files entries in place — adds 'experiment_count' key.

    Why this exists: integrate_pool() in bmdx-pipe now writes experiment_count
    at integration time, but sessions saved before that change have source_files
    entries without it.  The summary endpoint calls this to backfill on the fly
    so the integrated dataset preview table shows correct counts instead of 0.
    """
    # Build normalized base platform → list of original keys mapping.
    # Multiple compound keys can share a base (e.g., "Hematology|tox_study"
    # and "Hematology|inferred" both normalize to "hematology").
    plat_norm: dict[str, list[str]] = {}
    for plat_key in source_files:
        base = plat_key.split("|")[0] if "|" in plat_key else plat_key
        normalized = base.lower().replace(" ", "").replace("_", "")
        plat_norm.setdefault(normalized, []).append(plat_key)

    # Count experiments per base platform
    base_counts: dict[str, int] = {}
    for exp in experiments:
        exp_name = (exp.get("name") or "").lower().replace("_", "")
        matched = False
        for norm_key in plat_norm:
            # Bidirectional substring: platform name in experiment name
            # (e.g., "hematology" in "hematologytruthfemale") OR a long
            # shared prefix (handles abbreviations like "tissueconc" from
            # experiment "tissue_conc_truth_male" vs "tissueconcentration"
            # from platform "Tissue Concentration").  Prefix must be at
            # least 6 chars to avoid false positives.
            if norm_key in exp_name:
                base_counts[norm_key] = base_counts.get(norm_key, 0) + 1
                matched = True
                break
            # Common-prefix check for abbreviated experiment names
            prefix_len = 0
            for a, b in zip(norm_key, exp_name):
                if a == b:
                    prefix_len += 1
                else:
                    break
            if prefix_len >= min(6, len(norm_key)):
                base_counts[norm_key] = base_counts.get(norm_key, 0) + 1
                matched = True
                break
        if not matched:
            # Check augmented ExperimentDescription metadata
            desc = exp.get("experimentDescription") or {}
            aug = desc.get("_augmented") or {}
            exp_platform = aug.get("platform", "")
            if exp_platform:
                norm_aug = exp_platform.lower().replace(" ", "").replace("_", "")
                if norm_aug in plat_norm:
                    base_counts[norm_aug] = base_counts.get(norm_aug, 0) + 1

    # Apply counts to all compound keys sharing the same base platform
    for norm_key, count in base_counts.items():
        for orig_key in plat_norm.get(norm_key, []):
            source_files[orig_key]["experiment_count"] = count


# ---------------------------------------------------------------------------
# The load barrier: read + validate + cache
# ---------------------------------------------------------------------------

def _load_integrated(dtxsid: str) -> dict | None:
    """
    Load and schema-validate the integrated BMDProject for a session.

    Prefers the in-memory cache (_integrated_pool).  Falls back to reading
    sessions/{dtxsid}/integrated.json from disk and populating the cache.

    Schema validation runs on every call (whether the data came from the
    cache or freshly off disk).  This makes _load_integrated the single
    runtime barrier between bmdx-pipe's BMDProject format and rlm-bmdx's
    downstream consumers — anything this function returns is guaranteed
    to conform to `bmd_project_schema.BMDProject`.  The cost is one
    Pydantic validation per call (sub-100ms on real session data), which
    is acceptable on every API hit.  See ADR-0001 for the design.

    The _category_lookup is stored in a separate sidecar file
    (_category_lookup.json) to keep integrated.json lean for fast summary
    loads.  It's merged back into the in-memory dict on first access.

    Returns None if no integrated data exists (caller should return 400).
    Raises BMDProjectValidationError if integrated.json fails the schema
    check — FastAPI handlers catch it as a ValueError subclass and
    translate to a structured 4xx response.
    """
    integrated = _integrated_pool.get(dtxsid)
    if integrated is None:
        session = _session_dir(dtxsid)
        integrated_path = session / "integrated.json"
        if integrated_path.exists():
            try:
                integrated = json.loads(integrated_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                logger.warning("Failed to load integrated.json for %s", dtxsid)
                return None

            # Load the _category_lookup sidecar if it exists and the key
            # is not already in the integrated dict (backward compat with
            # old sessions that still have it inline).
            if "_category_lookup" not in integrated:
                cat_path = session / "_category_lookup.json"
                if cat_path.exists():
                    try:
                        integrated["_category_lookup"] = json.loads(
                            cat_path.read_text(encoding="utf-8")
                        )
                    except (json.JSONDecodeError, Exception):
                        logger.warning("Failed to load _category_lookup.json for %s", dtxsid)
                        integrated["_category_lookup"] = {}

            _integrated_pool[dtxsid] = integrated

    # Validate the (possibly cached) data against the schema before
    # returning.  Validating on every call rather than once per cache
    # population means fresh-from-integration data is gated too — see
    # ADR-0001 for why we accepted the per-call cost.  The validated
    # form is written back to the cache so subsequent calls operate on
    # the dict-dump form (which is shape-equivalent to the original
    # plus the model's normalizations).
    if integrated is not None:
        try:
            integrated = _load_and_validate_bmd_project(
                integrated, source=f"DTXSID={dtxsid}",
            )
        except BMDProjectValidationError:
            # Re-raise after logging.  Don't swallow — the whole point
            # of the barrier is to surface contract violations loudly.
            logger.exception(
                "BMDProject schema validation failed for %s", dtxsid,
            )
            raise
        _integrated_pool[dtxsid] = integrated

    return integrated


# ---------------------------------------------------------------------------
# Public alias for the load function
# ---------------------------------------------------------------------------
# External modules (export_routes, llm_routes, session_routes, etc.) need
# to read integrated.json through the schema-validating barrier.  Rather
# than import the underscore-prefixed `_load_integrated` directly (which
# would violate the module-privacy convention), we expose this public
# alias.  The implementation stays in `_load_integrated`; the alias is
# only the import-facing name.
load_integrated = _load_integrated


# ---------------------------------------------------------------------------
# Schema-validated writer for integrated.json
# ---------------------------------------------------------------------------
# Implements ADR-0001 commit-sequence step 3.  Mirrors `load_integrated`
# on the write side: a single chokepoint where every mutation of
# integrated.json passes through the BMDProject schema validator before
# touching disk.  Without this, the metadata-edit code path in
# session_routes.py could persist invalid data (e.g. a typo in the sex
# field) that would only be caught on the NEXT read — by which time the
# .bm2 re-export, approval marker, and cache invalidation may have
# already happened against bad data.
def save_integrated(dtxsid: str, data: dict) -> dict:
    """
    Validate-then-write integrated.json for a session.

    Runs the BMDProject schema over `data` first; only on a successful
    validation does anything touch disk.  After the write, updates the
    in-memory `_integrated_pool` cache so subsequent `load_integrated`
    calls return the new content without re-reading from disk.

    Args:
        dtxsid: Session identifier (DTXSID).  The integrated.json path
                is derived from this via `_session_dir`.
        data:   The dict to persist.  Should already be in BMDProject
                shape — typically the result of a `load_integrated`
                call followed by in-place edits to
                `experimentDescription` fields or similar.

    Returns:
        The validated (and round-tripped through the model) dict.
        Callers that need a guaranteed-clean copy can rely on this
        return value rather than the input.

    Raises:
        BMDProjectValidationError: when `data` does not match the
        schema.  Nothing is written in this case; the existing
        integrated.json on disk is untouched.  The global FastAPI
        handler in `background_server.py` translates this to a 422.
    """
    # Validation FIRST — only persist what passes the schema.  This is
    # the load barrier inverted: invalid data never reaches disk in the
    # first place, so we don't have to clean up after a bad write.
    validated = _load_and_validate_bmd_project(
        data, source=f"DTXSID={dtxsid}",
    )

    # Write the validated form (after model round-trip) so the file on
    # disk is the canonical post-model shape — never the raw input.
    session = _session_dir(dtxsid)
    integrated_path = session / "integrated.json"
    integrated_path.write_text(
        json.dumps(validated, indent=2), encoding="utf-8",
    )

    # Keep the in-memory cache consistent with disk.  Future
    # `load_integrated` calls hit the cache and re-validate (cheap),
    # but they should see the just-written content immediately.
    _integrated_pool[dtxsid] = validated
    return validated


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
