"""
Pool orchestrator — file pool fingerprinting, validation, integration, and
processing endpoints extracted from background_server.py.

This module owns the full lifecycle of the "file pool" concept:

  1. **Fingerprinting** — extract structural metadata (doses, animals, endpoints,
     platform, data_type) from each uploaded file so we can cross-validate them.
  2. **Validation** — check for dose group mismatches, coverage gaps, and
     redundancy across the pool.
  3. **Conflict resolution** — persist user precedence decisions when files
     disagree.
  4. **Integration** — merge the best file per platform into a single unified
     BMDProject JSON via bmdx-core's native Java classes.
  5. **Processing** — run NTP stats on the integrated data to produce per-platform
     section cards (tables + narratives) for the UI, plus genomics extraction
     from gene-expression .bm2 files.
  6. **Animal traceability** — per-animal cross-tier/cross-platform report.

All endpoints are mounted as a FastAPI APIRouter, included by the main app.

Shared state (module-level dicts):
  - _pool_fingerprints:  dtxsid -> {file_id -> FileFingerprint}
  - _integrated_pool:    dtxsid -> merged BMDProject dict
  - _data_uploads:       file_id -> {filename, temp_path, type}

These are accessed by other modules (upload handlers, session restore) via the
public accessor functions exported at the bottom of this file.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orjson
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, Response

from bmd_project_schema import (
    BMDProjectValidationError,
    load_and_validate as _load_and_validate_bmd_project,
)
from llm_helpers import (
    llm_generate_json as _llm_generate_json_imported,
    llm_generate_json_async as _llm_generate_json_async,
)

from bmdx_pipe import (
    FileFingerprint,
    TableRow,
    ValidationReport,
    fingerprint_file,
    validate_pool,
    lightweight_validate,
    _BM2_PLATFORM_MAP,
    detect_platform_and_type_from_bm2,
    integrate_pool,
    build_animal_report,
    report_to_dict,
    annotate_missing_animals,
    backfill_missing_doses,
    build_table_data,
    build_clinical_obs_tables,
    export_genomics,
    generate_results_narrative,
)
from apical_bmds import run_bmds_for_endpoints

# Shared state, the FastAPI router, and the path helper have all moved to
# pool_globals.py so the upcoming split modules can reach for them without
# importing pool_orchestrator (which would create a load-order cycle, since
# pool_orchestrator re-exports those same modules' contents for backward
# compatibility).  Re-imported here under their original names so every
# function body and external `from pool_orchestrator import ...` keeps
# working unchanged.
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

logger = logging.getLogger(__name__)


# Pool-state mutation (pool_has_progressed, remove_old_file_entries,
# invalidate_pool_artifacts) moved to pool_state.py.  Re-imported under
# their original names so external `from pool_orchestrator import ...`
# from background_server.py and upload_routes.py keeps working.
from pool_state import (
    pool_has_progressed,
    remove_old_file_entries,
    invalidate_pool_artifacts,
)

# Table serialization + Clinical Observations card assembly moved to
# section_serializers.py.  Re-imported under their original names so any
# function body below and any external `from pool_orchestrator import ...`
# keeps working unchanged.
from section_serializers import (
    _js_dose_key,
    serialize_table_rows,
    serialize_incidence_rows,
    _build_clinical_obs_section,
)

# Fingerprinting + lightweight validation moved to pool_fingerprints.py.
# Re-imported under their original names so internal call sites and
# external `from pool_orchestrator import ...` (background_server,
# session_routes, upload_routes) keep working unchanged.
from pool_fingerprints import (
    fingerprint_and_store,
    _save_fingerprints_to_disk,
    load_cached_fingerprint,
    restore_fingerprint,
    run_lightweight_validation,
    ensure_fingerprints,
)

# Pool lifecycle POST handlers (validate / resolve / confirm-metadata /
# integrate) and the _write_metadata_headers helper moved to pool_routes.py.
# Importing the module here causes its @router.post decorators to run
# against the shared pool_globals.router, so background_server.py's
# `include_router(pool_orchestrator.router)` still mounts every endpoint.
# The names are re-bound so external `from pool_orchestrator import api_pool_*`
# keeps working.
from pool_routes import (
    api_pool_validate,
    api_pool_resolve,
    api_pool_confirm_metadata,
    api_pool_integrate,
    _write_metadata_headers,
)


# Integrated.json read/write barrier + GET routes moved to integrated_io.py.
# Re-imported under their original names so:
#   - external callers (export_routes, llm_routes, session_routes) that
#     `from pool_orchestrator import load_integrated, save_integrated` keep
#     working,
#   - internal callers below this point that use _safe_float et al. keep
#     working without an import shuffle,
#   - the routes still register on the shared APIRouter (the decorators in
#     integrated_io.py attach to pool_globals.router, which is the same
#     object exposed as pool_orchestrator.router).
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
# Per-section cache infrastructure (extracted)
# ---------------------------------------------------------------------------
# The disk cache, hash inputs, schema-version constants, platform-table
# (de)serializers, and the category-lookup restorer all live in
# cache_plumbing.py.  Re-imported here under their original names so
# every internal call site and external `from pool_orchestrator import ...`
# continues to work.

from cache_plumbing import (
    _load_cache,
    _save_cache,
    _NTP_CACHE_SCHEMA_VERSION,
    _SECTIONS_CACHE_SCHEMA_VERSION,
    _GENOMICS_CACHE_SCHEMA_VERSION,
    _CHARTS_CACHE_SCHEMA_VERSION,
    _hash_ntp,
    _hash_sections,
    _hash_bmds,
    _hash_genomics,
    _hash_bmd_summary,
    _hash_methods,
    _serialize_platform_tables,
    _deserialize_platform_tables,
    _restore_category_lookup,
)

# Pipeline phase functions (filter / partition / build cards / extract
# adversity + genomics / build BMD summaries) moved to processing_helpers.py.
# Re-imported so api_process_integrated (below) can call them by their
# original names, and so tests/unit/test_partition.py (which does
# `from pool_orchestrator import _filter_gene_expression, _partition_by_platform`)
# keeps working.
from processing_helpers import (
    _filter_gene_expression,
    _partition_by_platform,
    _build_section_cards,
    _extract_adversity_signatures,
    _extract_genomics,
    _build_apical_bmd_summary,
    _build_bmds_bmd_summary,
)

# api_process_integrated god function + api_generate_animal_report + the
# _BMD_STAT_LABELS UI-label dict moved to process_integrated.py.  Importing
# the module here triggers its @router.post decorators against the shared
# pool_globals.router, and the named re-exports below let any
# `from pool_orchestrator import api_process_integrated` / `_BMD_STAT_LABELS`
# call site keep working.
from process_integrated import (
    api_process_integrated,
    api_generate_animal_report,
    _BMD_STAT_LABELS,
)
