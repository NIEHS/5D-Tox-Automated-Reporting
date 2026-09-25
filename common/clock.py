"""
common/clock.py — the one place that knows what "now" is.

`now_iso()` returns the current UTC time as an ISO 8601 string; it stamps
approval times, version events, view/config saves and corpus-curation records.
Kept in the dependency-free `common` package so document_model/ and
knowledge_base/ can timestamp their own files without importing pipeline/.
(pipeline/session_store re-exports it for backward compatibility.)
"""

from datetime import datetime, timezone


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string (timezone-aware)."""
    return datetime.now(timezone.utc).isoformat()
