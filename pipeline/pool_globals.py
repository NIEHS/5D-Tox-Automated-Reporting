"""
Shared mutable state, FastAPI router, and path helpers for the pool-
orchestrator subsystem.

This module exists ONLY to hold concerns that more than one of the
split pool_* modules (pool_state, pool_fingerprints, pool_routes,
integrated_io, cache_plumbing, section_serializers, process_integrated)
need to reach for in common:

  - the FastAPI APIRouter that every pool/integrated/process route
    handler registers on
  - the in-memory dicts that hold per-DTXSID session state
  - the most-referenced path helper (_session_dir, 21+ call sites)

It has no logic of its own — all real behavior lives in the consumer
modules.  The original monolithic pool_orchestrator.py is kept as a
thin shim that re-exports everything here for backward compatibility
with the many external importers (background_server, session_routes,
upload_routes, llm_routes, export_routes, server_state, and the test
suite).

Why a separate module rather than leaving these in pool_orchestrator.py?
After the split, route handlers in pool_routes.py and process_integrated.py
need `router` to register their decorators on.  If they imported it from
pool_orchestrator.py, and pool_orchestrator.py imports back from them for
re-export, we'd have a load-order cycle that breaks at import time.
A dedicated globals module — imported by everyone but importing from
nobody in the split — breaks that cycle by construction.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import logging
from pathlib import Path

from fastapi import APIRouter

# FileFingerprint is the value type stored in _pool_fingerprints; importing
# it here keeps the type annotation honest without forcing every consumer
# to repeat the bmdx_pipe import for type purposes alone.
from bmdx_pipe import FileFingerprint

# session_store.session_dir is the canonical session-directory locator.
# Aliased on import to avoid a name collision with our _session_dir wrapper.
from pipeline.session_store import session_dir as _session_dir_imported


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------
# Every pool/integrated/process route handler across the split modules
# attaches to this single router object via @router.post / @router.get.
# background_server.py mounts it via `pool_orchestrator.router` (the shim
# re-exports it).

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared in-memory state
# ---------------------------------------------------------------------------
# These module-level dicts hold the live per-session state for the file
# pool.  Multiple split modules mutate them.  Because Python imports are
# bindings to the same object, `from pool_globals import _pool_fingerprints`
# in a consumer module gives a name that refers to the same dict — reads,
# writes, and mutations all stay in sync.
#
# Reassignment (e.g., `_pool_fingerprints = {}` inside a function) would
# desync the consumer's binding from this one; no existing code does that,
# and any future code that needs to wipe state should call .clear() on the
# dict instead.

# Maps dtxsid -> {file_id -> FileFingerprint}.  Populated when files are
# fingerprinted on upload or validation, persisted to validation_report.json
# in the session directory.
_pool_fingerprints: dict[str, dict[str, FileFingerprint]] = {}

# Maps dtxsid -> merged BMDProject dict produced by pool integration.
# Populated by /api/pool/integrate and mirrored to sessions/{dtxsid}/integrated.json
# so cross-session restore can rehydrate it.
_integrated_pool: dict[str, dict] = {}

# Maps file_id (UUID string) -> {filename, temp_path, type} for raw
# dose-response experimental data (.csv, .txt, .xlsx) extracted from
# uploaded zip archives.  These are BMDExpress-importable input data,
# distinct from .bm2 (which are stored in server_state.bm2_uploads) and
# from gene-level BMD CSVs.
_data_uploads: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Path + lazy-import helpers
# ---------------------------------------------------------------------------

def _session_dir(dtxsid: str) -> Path:
    """Return the session directory for a DTXSID, creating it if needed.

    Thin pass-through to session_store.session_dir.  The wrapper exists
    so consumers can `from pool_globals import _session_dir` and avoid
    naming the aliased import directly.
    """
    return _session_dir_imported(dtxsid)


def _get_bm2_uploads() -> dict[str, dict]:
    """Return the live bm2 uploads dict from server_state.

    Implemented as a lazy import because server_state imports from
    pool_orchestrator (and therefore transitively from us).  Taking the
    import inside the function body defers it until first call, by which
    time both modules have finished loading and the cycle is harmless.
    """
    from server_state import get_bm2_uploads
    return get_bm2_uploads()


# ---------------------------------------------------------------------------
# Public accessors for shared state
# ---------------------------------------------------------------------------
# External consumers (background_server, session_routes, upload_routes)
# reach for the live state via these accessor functions rather than
# importing the raw dicts.  Each returns the live mutable dict so callers
# can read and write through it.

def get_pool_fingerprints() -> dict[str, dict[str, FileFingerprint]]:
    """Return the full pool fingerprints dict (dtxsid -> {fid -> fp})."""
    return _pool_fingerprints


def get_integrated_pool() -> dict[str, dict]:
    """Return the full integrated pool dict (dtxsid -> BMDProject dict)."""
    return _integrated_pool


def get_data_uploads() -> dict[str, dict]:
    """Return the data uploads dict (file_id -> upload info)."""
    return _data_uploads
