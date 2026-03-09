"""
server_state.py — Central in-memory stores shared across route modules.

This module is the single source of truth for mutable server-side state that
multiple FastAPI routers need to read and write.  By putting all shared dicts
in one leaf module (no imports from route modules), we avoid circular imports
while keeping the dependency graph clean.

Shared stores:
  - _bm2_uploads:  bm2_id (UUID) → {filename, temp_path, table_data, bm2_json, narrative}
                   Populated by upload-bm2 / upload-zip; consumed by process-bm2,
                   preview, export-docx/pdf, and session load (re-registration).

  - _csv_uploads:  csv_id (UUID) → {filename, temp_path, temp_dir, df}
                   Populated by upload-csv; consumed by process-genomics.

Re-exports from pool_orchestrator (for convenience):
  - get_data_uploads()      — file_id → {filename, temp_path, type}
  - get_pool_fingerprints() — dtxsid → {file_id → FileFingerprint}
  - get_integrated_pool()   — dtxsid → merged BMDProject dict
"""

from pool_orchestrator import (
    get_data_uploads,
    get_pool_fingerprints,
    get_integrated_pool,
)


# ---------------------------------------------------------------------------
# .bm2 upload store
# ---------------------------------------------------------------------------
# Maps bm2_id (UUID string) → dict with filename, temp_path, and table_data
# (table_data is populated after /api/process-bm2 is called).
# This is an in-memory store; files live in a temp directory per upload.
_bm2_uploads: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Gene-level BMD CSV upload store
# ---------------------------------------------------------------------------
# Maps csv_id (UUID string) → dict with filename, temp_path, and parsed DataFrame.
# Used for gene-level BMD CSV uploads (transcriptomic data for the Gene Set
# and Gene BMD Analysis report sections).
_csv_uploads: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Accessors — typed entry points for other modules
# ---------------------------------------------------------------------------

def get_bm2_uploads() -> dict[str, dict]:
    """Return the bm2 uploads dict (bm2_id → upload info)."""
    return _bm2_uploads


def get_csv_uploads() -> dict[str, dict]:
    """Return the CSV uploads dict (csv_id → upload info)."""
    return _csv_uploads
