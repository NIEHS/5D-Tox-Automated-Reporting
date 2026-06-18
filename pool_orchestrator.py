"""
Pool orchestrator — backward-compatible facade over the split modules.

This module no longer contains implementation.  The original ~3700-line
monolith was extracted into focused submodules (each with its own file
header explaining its concern) across this branch's commits:

  pool_globals.py           shared mutable state, the FastAPI APIRouter,
                            _session_dir, and the lazy bm2-uploads
                            accessor
  pool_state.py             pool progression check, file-replacement
                            cleanup, cascading artifact invalidation
  section_serializers.py    TableRow / IncidenceRow JSON serializers
                            and the Clinical Observations card builder
  pool_fingerprints.py      fingerprint lifecycle: extract, persist,
                            reload, restore, validate, ensure-scan
  pool_routes.py            POST /api/pool/{validate,resolve,
                            confirm-metadata,integrate}
  integrated_io.py          BMDProject load/save barrier (ADR-0001) +
                            GET /api/integrated/{,-summary}/{dtxsid}
  cache_plumbing.py         per-section disk cache, hash inputs,
                            schema-version constants, platform-table
                            (de)serializers, category-lookup restorer
  processing_helpers.py     pipeline phase functions consumed by the
                            process-integrated endpoint (filter,
                            partition, build section cards, extract
                            adversity + genomics, build BMD summaries)
  process_integrated.py     POST /api/process-integrated/{dtxsid} +
                            POST /api/generate-animal-report/{dtxsid}
                            + the _BMD_STAT_LABELS UI-label dict

This file's only remaining job is to re-export the public surface so
the many consumers that already import via `from pool_orchestrator
import …` keep working without churn.  Concretely the consumers are:

  - background_server.py   (mounts pool_orchestrator.router)
  - export_routes.py       (load_integrated)
  - llm_routes.py          (load_integrated)
  - server_state.py        (get_data_uploads / get_pool_fingerprints /
                            get_integrated_pool)
  - upload_routes.py       (fingerprint_and_store, run_lightweight_validation,
                            serialize_table_rows, remove_old_file_entries,
                            invalidate_pool_artifacts, pool_has_progressed)
  - session_routes.py      (fingerprint_and_store, run_lightweight_validation,
                            _js_dose_key, load_cached_fingerprint,
                            restore_fingerprint, load_integrated, save_integrated)
  - tests/                 (mostly private symbols: _filter_gene_expression,
                            _partition_by_platform, _safe_float, _hash_*,
                            _integrated_pool, save_integrated, load_integrated)

A future cleanup pass could rewrite each consumer to import from the
new modules directly and then delete this file, but that's an
independent commit — not part of the split itself.

Importing this module is also what causes the @router decorators in
pool_routes / integrated_io / process_integrated to fire against the
shared pool_globals.router.  background_server's
`include_router(pool_orchestrator.router)` therefore continues to
mount every endpoint without any other change.
"""

# ---------------------------------------------------------------------------
# Re-exports: shared state, router, path helpers
# ---------------------------------------------------------------------------
from pool_globals import (
    router,
    _pool_fingerprints,
    _integrated_pool,
    _data_uploads,
    _session_dir,
    _get_bm2_uploads,
    get_pool_fingerprints,
    get_integrated_pool,
    get_data_uploads,
)

# ---------------------------------------------------------------------------
# Re-exports: pool-state mutation
# ---------------------------------------------------------------------------
from pool_state import (
    pool_has_progressed,
    remove_old_file_entries,
    invalidate_pool_artifacts,
)

# ---------------------------------------------------------------------------
# Re-exports: section-card serialization helpers
# ---------------------------------------------------------------------------
from section_serializers import (
    _js_dose_key,
    serialize_table_rows,
    serialize_incidence_rows,
    _build_clinical_obs_section,
)

# ---------------------------------------------------------------------------
# Re-exports: fingerprint lifecycle
# ---------------------------------------------------------------------------
from pool_fingerprints import (
    fingerprint_and_store,
    _save_fingerprints_to_disk,
    load_cached_fingerprint,
    restore_fingerprint,
    run_lightweight_validation,
    ensure_fingerprints,
)

# ---------------------------------------------------------------------------
# Side-effect import: pool lifecycle POST handlers
# ---------------------------------------------------------------------------
# Importing pool_routes runs its @router.post decorators against the
# shared pool_globals.router, so the four /api/pool/* endpoints register
# at module load time.  The named re-exports preserve callers that import
# the handlers by name (background_server / session_routes for testing).
from pool_routes import (
    api_pool_validate,
    api_pool_resolve,
    api_pool_confirm_metadata,
    api_pool_integrate,
    _write_metadata_headers,
)

# ---------------------------------------------------------------------------
# Re-exports: BMDProject load/save barrier + GET routes
# ---------------------------------------------------------------------------
# Side-effect import also: integrated_io's @router.get decorators register
# /api/integrated/{dtxsid} and /api/integrated-summary/{dtxsid} on the
# shared router.
from integrated_io import (
    _safe_float,
    _safe_float_from_bmdl,
    _pick_go_stat,
    _enrich_source_experiment_counts,
    _load_integrated,
    load_integrated,
    save_integrated,
    api_integrated_full,
    api_integrated_summary,
)

# ---------------------------------------------------------------------------
# Re-exports: cache plumbing
# ---------------------------------------------------------------------------
from cache_plumbing import (
    _load_cache,
    _save_cache,
    _NTP_CACHE_SCHEMA_VERSION,
    _SECTIONS_CACHE_SCHEMA_VERSION,
    _GENOMICS_CACHE_SCHEMA_VERSION,
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

# ---------------------------------------------------------------------------
# Re-exports: process-integrated pipeline phase functions
# ---------------------------------------------------------------------------
from processing_helpers import (
    _filter_gene_expression,
    _partition_by_platform,
    _build_section_cards,
    _extract_adversity_signatures,
    _extract_genomics,
    _build_apical_bmd_summary,
    _build_bmds_bmd_summary,
)

# ---------------------------------------------------------------------------
# Side-effect import: process-integrated + animal-report POST handlers
# ---------------------------------------------------------------------------
# Importing process_integrated runs its @router.post decorators against
# the shared pool_globals.router, so /api/process-integrated/{dtxsid} and
# /api/generate-animal-report/{dtxsid} register at module load time.
from process_integrated import (
    api_process_integrated,
    api_generate_animal_report,
    _BMD_STAT_LABELS,
)
