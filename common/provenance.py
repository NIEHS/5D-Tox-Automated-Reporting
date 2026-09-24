"""
common/provenance.py — a per-request record of each report section's FATE.

For a workflow where "did this section LOAD from cache or get REGENERATED?" is a live
correctness question, the app had no way to answer it after the fact (only ad-hoc
printf logs, no request correlation). This module is that side channel: instrumentation
points across the load / process / materialize paths call `record(event, ...)`, and at
request end `flush(dtxsid)` writes the collected events as one JSON object to
`sessions/<dtxsid>/.provenance.jsonl` (a durable per-session audit trail) — while each
event is ALSO emitted live on the `provenance` logger (stdout, one JSON line).

It is a pure OBSERVABILITY side channel: it never enters the report payload, never
changes load/process/materialize behavior, and every operation is fail-soft — a logging
error must never break a request. Correlation is server-minted: the middleware
(web_routes.background_server) opens a context with a fresh `request_id` per request;
events recorded within it share that id. Kept in the dependency-free `common` package so
any layer (pipeline/, workflow/, web_routes/) can record without an import cycle.

Event vocabulary (the `event` field):
  cache_hit / cache_miss / cache_corrupt / cache_saved   (pipeline.cache_plumbing)
  regenerated / content_skipped / content_regenerated     (pipeline.process_integrated)
  materialized                                            (workflow.steps)
  disk_read                                               (web_routes.session_routes load)
Common fields where in scope: dtxsid, unit / section_key, hash, ms, bytes.
"""

from __future__ import annotations

import contextvars
import json
import logging
from contextlib import contextmanager

import sys

from common.clock import now_iso

# The `provenance` logger streams one JSON line per event to stdout. It configures
# its OWN StreamHandler at INFO rather than relying on the ambient config, because
# the app installs no logging config — a bare getLogger sits at the root's default
# level and would silently drop these INFO lines (the reason early events reached the
# per-session JSONL sink but never the server log). propagate=False keeps them off the
# root handlers so uvicorn's access log doesn't double-print them. Idempotent: guarded
# so re-import (or a test re-running the module) never stacks duplicate handlers.
logger = logging.getLogger("provenance")
if not any(getattr(h, "_provenance_sink", False) for h in logger.handlers):
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("provenance %(message)s"))
    _handler._provenance_sink = True  # marker so the guard above is idempotent
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

# The active request's id and its accumulating event list. Both are ContextVars so
# concurrent requests (async handlers) never bleed into each other's record. Default
# request_id None + a None event-sink means "no active request" — record() still emits
# the live log line but has nowhere to accumulate for a flush (harmless).
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "provenance_request_id", default=None
)
_events: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "provenance_events", default=None
)


def current_request_id() -> str | None:
    """The active request's id, or None outside a request context."""
    return _request_id.get()


@contextmanager
def request_context(request_id: str):
    """Open a provenance context for one request.

    Sets the request_id + a fresh event sink for the duration; resets both on exit
    (so a worker thread/task reused across requests never inherits a stale context).
    The middleware wraps each request in this; `flush()` reads the accumulated events.
    """
    id_token = _request_id.set(request_id)
    ev_token = _events.set([])
    try:
        yield
    finally:
        _request_id.reset(id_token)
        _events.reset(ev_token)


def record(event: str, **fields) -> None:
    """Record one section-fate event: accumulate it for the request's flush AND emit
    it live on the `provenance` logger as a single JSON line. Fail-soft — never raises
    into the caller (an instrumentation point must not be able to break the request)."""
    try:
        entry = {"ts": now_iso(), "request_id": _request_id.get(), "event": event}
        entry.update(fields)
        sink = _events.get()
        if sink is not None:
            sink.append(entry)
        logger.info("%s", json.dumps(entry, default=str))
    except Exception:  # pragma: no cover - observability must never break a request
        pass


def flush(dtxsid: str, *, path: str | None = None, total_ms: float | None = None) -> None:
    """Append the request's accumulated events to sessions/<dtxsid>/.provenance.jsonl.

    Writes one JSON object per line: {request_id, path, dtxsid, total_ms, events:[...]}.
    A dotfile, so the section/cache globs (`*.json`, `_cache_*`, `bm2_*`) never pick it
    up. No-op when there are no events (e.g. a request that touched no instrumented
    seam). Fail-soft: a write error (unwritable dir, bad dtxsid) is swallowed — the
    audit trail is best-effort, never load-bearing. SESSIONS_DIR is resolved at call
    time so a test's monkeypatch / env override is honored."""
    try:
        events = _events.get()
        if not events:
            return
        from common.paths import SESSIONS_DIR

        d = SESSIONS_DIR / dtxsid
        if not d.is_dir():
            return
        record_obj = {
            "request_id": _request_id.get(),
            "path": path,
            "dtxsid": dtxsid,
            "total_ms": total_ms,
            "events": events,
        }
        line = json.dumps(record_obj, default=str)
        with (d / ".provenance.jsonl").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # pragma: no cover - observability must never break a request
        pass
