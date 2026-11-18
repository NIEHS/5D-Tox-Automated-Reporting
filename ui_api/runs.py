"""
ui_api.runs — which study a long act is running on, in this process.

Process, integration and a section's generation each take seconds to minutes,
and two of them on one study would write over each other (MODULES.md §1: "no
run lock").  Until the core has a run lock of its own (C5), every long act the
new interface starts goes through ``running`` here: a second act on the same
study is refused (``run_in_flight``) while the first is under way, and the
read model says a run is in flight, since when and what it is.

The record is this process's memory.  The application is one server process
over one store (docs/ui-redesign/BOARD.md, the ports), so that covers every
browser tab; it does not cover a command line run beside the server.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timezone

_lock = threading.Lock()
_runs: dict[str, dict] = {}


def current(dtxsid: str) -> dict | None:
    """``{"what", "started_at"}`` of the act under way on the study, or None."""
    with _lock:
        run = _runs.get(dtxsid)
        return dict(run) if run else None


def running_since(dtxsid: str) -> str | None:
    run = current(dtxsid)
    return run["started_at"] if run else None


@contextmanager
def running(dtxsid: str, what: str, *also: str):
    """Hold the study (and ``also``: other sessions the act writes) for one
    long act; refused with ``run_in_flight`` when any of them is held."""
    from ui_api.studies import StudyRefusal

    ids = (dtxsid, *also)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _lock:
        for i in ids:
            busy = _runs.get(i)
            if busy:
                raise StudyRefusal(
                    "run_in_flight", f"{i}: {busy['what']} is running since "
                    f"{busy['started_at']}", 409,
                    {"id": i, "time": busy["started_at"], "what": busy["what"]})
        for i in ids:
            _runs[i] = {"what": what, "started_at": started}
    try:
        yield
    finally:
        with _lock:
            for i in ids:
                _runs.pop(i, None)
