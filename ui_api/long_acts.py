"""
ui_api.long_acts — one long act on a study, run to its end and told as it goes.

Combining a study's files takes half a minute and Process takes minutes.  The
interface waits for both in the foreground (MODULES.md §4.4), reading the
act's events as lines of JSON:

    {"event": "step", "unit": "integrate", "status": "computing", "say": "…"}
    {"event": "step", "unit": "integrate", "status": "done", "say": "…", "ms": 24100}
    {"event": "result", "ok": true, "summary": {…}}
  or
    {"event": "error", "error": {…the §4.2 envelope's body…}}

``start`` holds the study for the act (ui_api.runs: a second act is refused
``run_in_flight`` before anything is answered), then runs the act on a thread
of its own and returns the lines.  The act does not depend on who is reading:
a page that is closed or reloaded stops reading, and the act goes on to its
end and releases the study (the wait has no cancel, Q12).

``unit_events`` collects what the core says of its units of work while an act
runs: each cache lookup and save is a provenance event (common.provenance:
``cache_miss``, ``cache_hit``, ``cache_saved``; ``content_regenerated``,
``content_skipped`` for the drafted text as a whole), also sent to the
``provenance`` logger.  A unit whose first lookup missed was computed; one
whose first lookup hit was reused.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from typing import Callable, Iterator

logger = logging.getLogger(__name__)

# report(unit, status, say, ms=None): one step event.
Report = Callable[..., None]


def start(dtxsid: str, what: str, work: Callable[[Report], dict], *, path: str) -> Iterator[str]:
    """Hold ``dtxsid`` for the act ``what`` and run ``work(report)`` on its own
    thread; the lines of its event stream.  ``work`` returns the result's
    summary or raises; a raise becomes the stream's ``error`` (the envelope's
    body).  Refused ``run_in_flight`` here, before a line is answered, when
    the study is already held.  ``path``: the request's, for the provenance
    record (sessions/<id>/.provenance.jsonl)."""
    from common import provenance
    from ui_api import runs
    from ui_api.refusals import explain

    held = ExitStack()
    held.enter_context(runs.running(dtxsid, what))
    events: queue.Queue = queue.Queue()

    def report(unit: str, status: str, say: str, ms: float | None = None) -> None:
        event = {"event": "step", "unit": unit, "status": status, "say": say}
        if ms is not None:
            event["ms"] = round(ms)
        events.put(event)

    def run() -> None:
        began = time.monotonic()
        try:
            with provenance.request_context(uuid.uuid4().hex[:12]):
                try:
                    last = {"event": "result", "ok": True, "summary": work(report)}
                except Exception as exc:  # noqa: BLE001 — every failure is explained
                    body = explain(exc)["error"]
                    if body["code"] == "unexpected":
                        logger.error("%s failed for %s: %s", what, dtxsid, exc, exc_info=exc)
                    last = {"event": "error", "error": body}
                provenance.flush(dtxsid, path=path,
                                 total_ms=round((time.monotonic() - began) * 1000, 1))
        finally:
            # Released before the last line: whoever reads it re-reads the
            # study's state, which must no longer say a run is in flight.
            held.close()
        events.put(last)
        events.put(None)

    try:
        threading.Thread(target=run, name=f"long-act-{dtxsid}", daemon=True).start()
    except BaseException:
        held.close()
        raise

    def lines() -> Iterator[str]:
        while (event := events.get()) is not None:
            yield json.dumps(event, default=str) + "\n"

    return lines()


@contextmanager
def timed_step(report: Report, unit: str, say: str):
    """One step of an act: ``computing`` at entry, ``done`` with its time at
    exit, ``failed`` when it raises (the raise goes on)."""
    report(unit, "computing", say)
    began = time.monotonic()
    try:
        yield
    except BaseException:
        report(unit, "failed", say, (time.monotonic() - began) * 1000)
        raise
    report(unit, "done", say, (time.monotonic() - began) * 1000)


# The preparation of the drafted text (pipeline.process_integrated): prepared
# again, or left as it was because nothing it is built from changed.
CONTENT_UNIT = "content"
_CONTENT_EVENTS = {"content_regenerated": ("computed", "done"),
                   "content_skipped": ("reused", "reused")}


class _UnitEvents(logging.Handler):
    """Collects one study's cache events from the ``provenance`` logger."""

    def __init__(self, dtxsid: str, on_unit: Callable[[str, str, float | None], None] | None):
        super().__init__(level=logging.INFO)
        self.dtxsid = dtxsid
        self.on_unit = on_unit
        self.first: dict[str, str] = {}      # unit -> "computed" | "reused", by its first lookup
        self.began: dict[str, float] = {}
        self._guard = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = json.loads(record.getMessage())
        except ValueError:
            return
        if not isinstance(entry, dict) or entry.get("dtxsid") != self.dtxsid:
            return
        event, unit = entry.get("event"), entry.get("unit")
        if event in _CONTENT_EVENTS:
            # The drafted text is prepared as one unit, told when it ends.
            how, status = _CONTENT_EVENTS[event]
            with self._guard:
                self.first.setdefault(CONTENT_UNIT, how)
            if self.on_unit:
                self.on_unit(CONTENT_UNIT, status, entry.get("ms"))
            return
        if not isinstance(unit, str) or event not in ("cache_miss", "cache_hit", "cache_saved"):
            return
        told = None
        with self._guard:
            if unit not in self.first:
                # A save with no lookup before it is a unit computed all the same.
                self.first[unit] = "reused" if event == "cache_hit" else "computed"
                self.began[unit] = time.monotonic()
                told = ("reused", None) if event == "cache_hit" else ("computing", None)
            if event == "cache_saved" and self.first[unit] == "computed" and unit in self.began:
                told = ("done", (time.monotonic() - self.began.pop(unit)) * 1000)
        if told and self.on_unit:
            self.on_unit(unit, *told)


@contextmanager
def unit_events(dtxsid: str, on_unit: Callable[[str, str, float | None], None] | None = None):
    """While inside: collect the cache events the core records for ``dtxsid``.
    Yields ``outcome()``: ``{"recorded": True, "computed": [unit, …], "reused":
    [unit, …]}`` in the order the units were first looked up, or
    ``{"recorded": False}`` when the events were not being recorded (the
    ``provenance`` logger was switched off): then nothing is known, and
    nothing is said.  ``on_unit(unit, status, ms)`` is called as each unit is
    looked up (``computing`` or ``reused``) and saved (``done``)."""
    from common import provenance

    recording = provenance.logger.isEnabledFor(logging.INFO)
    handler = _UnitEvents(dtxsid, on_unit)
    provenance.logger.addHandler(handler)

    def outcome() -> dict:
        if not recording:
            return {"recorded": False}
        with handler._guard:
            first = dict(handler.first)
        return {"recorded": True,
                "computed": [u for u, how in first.items() if how == "computed"],
                "reused": [u for u, how in first.items() if how == "reused"]}

    try:
        yield outcome
    finally:
        provenance.logger.removeHandler(handler)
