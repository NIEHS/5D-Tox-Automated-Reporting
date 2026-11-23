"""
ui_api.writing_acts — the acts of the Written sections page (the demo path,
spec §4 S3): write the Background, run the Summary, take a Summary run into
the report.

Each act is the core's own, behind the safeguards:

  * **Write the Background**: gather the public sources about the chemical
    (narrative.data_gatherer), refuse when the hazard assessments could not
    be reached (safeguards.sources.require_sources), let the model write
    (narrative.background_writer.generate_background), refuse a text with no
    references (require_references), save it as a draft through the section
    write gate (safeguards.guarded.write_section: an approved Background is
    never replaced), and keep the run with the exact prompt sent
    (pipeline.prompt_store.save_run). The sequence is
    tooling.generate_report.background's.
  * **Run the Summary**: narrative.summary_llm.generate_summary under the
    current prompt template. The run is kept with its prompt; the report's
    Summary is not changed by it.
  * **Take a run into the report**: the run's text becomes the Summary
    section, through the same gate.

No act is done on the finished side of a demo pair (ui_api.demo), and one
long act at a time runs on a study (ui_api.runs).

The two long acts answer as a run's event stream (MODULES.md §4.4): ``step``
events while it works, then one ``result`` or one ``error``. A refusal known
before the work starts is raised, so the route answers it as an ordinary
error. The work runs to its end in a thread of its own: leaving the page does
not stop it, and the study is held until it ends.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from ui_api.studies import StudyRefusal
from ui_api.writing import _json, _kind, runs_of, session_of

logger = logging.getLogger(__name__)

BACKGROUND, SUMMARY, CITATIONS = "background", "summary", "citations"

_LIVE_ONLY_SAY = ("For now, writing is offered here only on the live copy of a "
                  "demonstration pair.")


# ---------------------------------------------------------------------------
# What may be done now
# ---------------------------------------------------------------------------

def _require_act(dtxsid: str, act: str, kind: dict | None = None) -> None:
    """Refuse an act that cannot be done on this session, before any work:
    the finished side of a pair, a session of the wrong kind, a text a person
    approved."""
    from ui_api.demo import require_not_reference
    from ui_api.read_model import ReadOnlyDiskPoolStore
    from workflow.section_writes import is_locked, read_prior

    require_not_reference(dtxsid)
    kind = kind or _kind(dtxsid)
    if kind["kind"] == "companion":
        raise StudyRefusal("read_only_session", f"{dtxsid} is a published book's content",
                           409, {"id": dtxsid})
    if act == CITATIONS and kind["kind"] == "member":
        parent = kind["relations"]["parent"]
        raise StudyRefusal("citations_are_the_reports",
                           f"{dtxsid} is a study of the report {parent}; the report prints "
                           "the reference list", 409, {"id": dtxsid, "parent": parent})
    if act == CITATIONS:
        # The check reads the report as it is presented: there must be one.
        from ui_api.studies import _bookshelf
        shelf = _bookshelf(dtxsid, kind["kind"], kind.get("relations") or {})
        if not shelf["on_shelf"]:
            raise StudyRefusal("citations_no_report_yet",
                               f"{dtxsid} has no report to check: {shelf['say']}", 409,
                               {"id": dtxsid, "why": shelf["say"]})
    if act == BACKGROUND and kind["kind"] == "member":
        parent = kind["relations"]["parent"]
        raise StudyRefusal("background_is_the_reports",
                           f"{dtxsid} is a study of the report {parent}; the Background is "
                           "the report's", 409, {"id": dtxsid, "parent": parent})
    if act == SUMMARY and kind["kind"] == "report":
        raise StudyRefusal("summary_is_a_studys",
                           f"{dtxsid} is a report over several studies; a Summary is "
                           "written for each study", 409, {"id": dtxsid})
    if act == BACKGROUND and is_locked(read_prior(dtxsid, BACKGROUND, ReadOnlyDiskPoolStore())):
        from safeguards.sections import owned
        raise owned(BACKGROUND, "writing it again")


def act_verdicts(dtxsid: str, kind: dict) -> dict:
    """``{background, summary}``: whether the page offers each act now, and
    why not (``{allowed, say}``). An act is offered on the live copy of a demo
    pair only; ``counterpart`` names the live copy on the finished side."""
    from ui_api.demo import pair_of
    from ui_api.refusals import explain

    pair = pair_of(dtxsid)
    out = {}
    for act in (BACKGROUND, SUMMARY):
        verdict: dict = {"allowed": True, "say": None}
        try:
            _require_act(dtxsid, act, kind)
        except Exception as exc:  # noqa: BLE001 — shown as the reason, in plain words
            verdict = {"allowed": False, "say": explain(exc)["error"]["say"]}
        if verdict["allowed"] and not (pair and pair["role"] == "live"):
            verdict = {"allowed": False, "say": _LIVE_ONLY_SAY}
        if pair and pair["role"] == "finished":
            verdict["counterpart"] = pair["counterpart"]
        out[act] = verdict
    return out


def citation_check_verdict(dtxsid: str, kind: dict) -> dict:
    """Whether the page offers "Check the citations" now, and why not
    (``{allowed, say}``). Offered on a report or a study on its own, live copy
    or not; never on the finished side of a demo pair, where ``counterpart``
    names the live copy."""
    from ui_api.demo import pair_of
    from ui_api.refusals import explain

    verdict: dict = {"allowed": True, "say": None}
    try:
        _require_act(dtxsid, CITATIONS, kind)
    except Exception as exc:  # noqa: BLE001 — shown as the reason, in plain words
        verdict = {"allowed": False, "say": explain(exc)["error"]["say"]}
    pair = pair_of(dtxsid)
    if pair and pair["role"] == "finished":
        verdict["counterpart"] = pair["counterpart"]
    return verdict


# ---------------------------------------------------------------------------
# A long act as a run's event stream
# ---------------------------------------------------------------------------

class _Steps:
    """The step events of one run: a step starts, then is done or failed."""

    def __init__(self, emit: Callable[[dict], None]):
        self._emit = emit
        self._open: tuple[str, str, float] | None = None

    def start(self, unit: str, say: str) -> None:
        self.done()
        self._open = (unit, say, time.monotonic())
        self._emit({"event": "step", "unit": unit, "status": "computing", "say": say})

    def _close(self, status: str) -> None:
        if self._open is None:
            return
        unit, say, since = self._open
        self._open = None
        self._emit({"event": "step", "unit": unit, "status": status, "say": say,
                    "ms": round((time.monotonic() - since) * 1000)})

    def done(self) -> None:
        self._close("done")

    def failed(self) -> None:
        self._close("failed")


def _run_events(dtxsid: str, what: str, work: Callable[[_Steps], dict]) -> Iterator[dict]:
    """Hold the study, run ``work`` in its own thread, and yield its events:
    its steps, then ``result`` with what it returned, or ``error`` with the
    envelope of what it raised. ``run_in_flight`` is raised here, before any
    event. The work ends whether or not anyone reads the events."""
    from ui_api import runs
    from ui_api.refusals import explain

    hold = runs.running(dtxsid, what)
    hold.__enter__()
    events: queue.Queue = queue.Queue()
    steps = _Steps(events.put)

    def run() -> None:
        try:
            summary = work(steps)
            steps.done()
            events.put({"event": "result", "ok": True, "summary": summary})
        except BaseException as exc:  # noqa: BLE001 — every failure ends the stream with its envelope
            steps.failed()
            body = explain(exc)["error"]
            if body["code"] == "unexpected":
                logger.error("%s failed for %s", what, dtxsid, exc_info=exc)
            events.put({"event": "error", "error": body})
        finally:
            hold.__exit__(None, None, None)
            events.put(None)

    threading.Thread(target=run, name=f"writing-{dtxsid}", daemon=True).start()

    def stream() -> Iterator[dict]:
        while (event := events.get()) is not None:
            yield event

    return stream()


# ---------------------------------------------------------------------------
# Write the Background
# ---------------------------------------------------------------------------

def _chemical_identity(dtxsid: str, session: Path) -> dict:
    """The chemical the Background is about: the session's stated identity,
    under the chemical's own DTXSID (a copy's or a report's id may carry a
    suffix), with the PubChem compound id looked up when it is not stated (the
    gatherer reads PubChem by it)."""
    from ui_api.studies import chemical_dtxsid

    identity = dict(_json(session / "identity.json") or {})
    identity["dtxsid"] = chemical_dtxsid(dtxsid) or identity.get("dtxsid") or ""
    if not identity.get("pubchem_cid"):
        try:
            from narrative.chem_resolver import resolve_chemical
            resolved = resolve_chemical(identity.get("casrn") or identity.get("name")
                                        or identity["dtxsid"], "auto", "").to_dict()
            identity = {**resolved, **{k: v for k, v in identity.items() if v}}
        except Exception as exc:  # noqa: BLE001 — PubChem then reads as unreachable
            logger.warning("Chemical of %s not resolved: %s", dtxsid, exc)
    return identity


def _write_background(dtxsid: str, steps: _Steps) -> dict:
    from narrative.background_writer import (
        DEFAULT_CLAUDE_MODEL, background_run_record, generate_background,
    )
    from narrative.chem_resolver import ChemicalIdentity
    from narrative.data_gatherer import gather_all
    from pipeline import prompt_store
    from safeguards.guarded import write_section
    from safeguards.sources import require_references, require_sources
    from workflow.store import DiskPoolStore

    session = session_of(dtxsid)
    steps.start("chemical", "Looking up the chemical")
    identity = _chemical_identity(dtxsid, session)

    count = 0

    def gathering(message: str) -> None:
        nonlocal count
        text = message.strip().rstrip(".").strip()
        if not text or text.lower().startswith("data gathering complete"):
            return
        count += 1
        steps.start(f"source_{count}", text)

    data = gather_all(ChemicalIdentity.from_dict(identity), gathering)

    steps.start("sources", "Checking that the hazard assessments were reached")
    require_sources(dtxsid, data)

    steps.start("model", "The language model writes the Background")
    result = generate_background(data, DEFAULT_CLAUDE_MODEL)

    steps.start("references", "Checking that the text cites its sources")
    require_references(dtxsid, result)

    steps.start("save", "Saving the Background as a draft")
    model = result.get("model_used", DEFAULT_CLAUDE_MODEL)
    out = write_section(dtxsid, BACKGROUND, {
        "paragraphs": result["paragraphs"],
        "references": result.get("references", []),
        "sources": result.get("sources", []),
        "citation_report": result.get("citation_report"),
        "abstract_background": result.get("abstract_background", ""),
        "model_used": model,
        "approved": False,
    }, DiskPoolStore(), act="background", actor="person", author="model",
        extra_event={"model": model})

    steps.start("record", "Keeping the prompt with the run")
    run = prompt_store.save_run(dtxsid, BACKGROUND,
                                background_run_record(dtxsid, result, version=out.get("version")))
    report = result.get("citation_report") or {}
    return {"paragraphs": len(result["paragraphs"]),
            "references": len(result.get("references") or []),
            "untraced_citations": report.get("unresolved_count", 0),
            "outcome": out["outcome"], "version": out.get("version"),
            "run_id": run["run_id"], "model": model}


def write_background(dtxsid: str) -> Iterator[dict]:
    """Write the report's Background and save it as a draft; the run's events."""
    session_of(dtxsid)
    _require_act(dtxsid, BACKGROUND)
    return _run_events(dtxsid, "the writing of the Background",
                       lambda steps: _write_background(dtxsid, steps))


# ---------------------------------------------------------------------------
# Run the Summary
# ---------------------------------------------------------------------------

def _run_summary(dtxsid: str, steps: _Steps) -> dict:
    import asyncio

    from narrative.model_policy import ModelNotAllowed
    from narrative.prompt_templates import TemplateError
    from narrative.summary_llm import generate_summary, render_for_session

    steps.start("facts", "Picking the facts from the study's results")
    try:
        render_for_session(dtxsid)
    except TemplateError as exc:
        raise StudyRefusal("summary_not_ready", str(exc), 409,
                           {"id": dtxsid, "why": str(exc)}) from None
    steps.start("model", "The language model words the Summary; the run is kept with its prompt")
    try:
        run = asyncio.run(generate_summary(dtxsid))
    except ModelNotAllowed as exc:
        raise StudyRefusal("model_not_allowed", str(exc), 403, {"id": dtxsid}) from None
    except TemplateError as exc:
        raise StudyRefusal("summary_not_ready", str(exc), 409,
                           {"id": dtxsid, "why": str(exc)}) from None
    if not run.get("paragraphs"):
        raise StudyRefusal("writing_failed", f"the model returned no Summary for {dtxsid} "
                           f"(run {run.get('run_id')})", 502, {"id": dtxsid})
    return {"run_id": run["run_id"], "template_version": run.get("template_version"),
            "model": (run.get("prompt") or {}).get("model"),
            "paragraphs": len(run["paragraphs"]),
            "unmatched_numbers": list(run.get("unmatched_numbers") or [])}


def run_summary(dtxsid: str) -> Iterator[dict]:
    """Have the model word the study's Summary under the current template;
    the run's events. The report's Summary is not changed."""
    session_of(dtxsid)
    _require_act(dtxsid, SUMMARY)
    return _run_events(dtxsid, "a Summary run", lambda steps: _run_summary(dtxsid, steps))


def use_summary_run(dtxsid: str, run_id: str) -> dict:
    """Make a recorded run's text the study's Summary section: a new,
    unapproved version, through the section write gate (an approved Summary
    is never replaced: ``section_owned``)."""
    from safeguards.guarded import write_section
    from ui_api import runs
    from workflow.store import DiskPoolStore

    session = session_of(dtxsid)
    _require_act(dtxsid, SUMMARY)
    run = next((r for r in runs_of(session, SUMMARY, limit=1000) if r.get("run_id") == run_id), None)
    if run is None:
        raise StudyRefusal("summary_run_not_found", f"{dtxsid} has no Summary run {run_id!r}",
                           404, {"id": dtxsid, "run": run_id})
    model = (run.get("prompt") or {}).get("model", "")
    with runs.running(dtxsid, "taking a Summary run into the report"):
        out = write_section(dtxsid, SUMMARY, {
            "paragraphs": run.get("paragraphs") or [],
            "source": "model",
            "approved": False,
            "run_id": run["run_id"],
            "template_version": run.get("template_version"),
            "model_used": model,
        }, DiskPoolStore(), act="use_run", actor="person", author="model",
            extra_event={"run_id": run["run_id"], "model": model,
                         "template_version": run.get("template_version")})
    result = {"ok": True, "version": out["version"], "outcome": out["outcome"]}
    if out["outcome"] == "unchanged":
        result["noop"] = {"code": "unchanged",
                          "say": "This run's text is already the Summary in the report. "
                                 "Nothing was changed."}
    return result


# ---------------------------------------------------------------------------
# Check the citations
# ---------------------------------------------------------------------------

def _check_citations(dtxsid: str, steps: _Steps) -> dict:
    from document_model.view_config import DEFAULT_VIEW
    from rendering.citations_validate import validate
    from rendering.preview_surface import _preview_inputs

    steps.start("report", "Reading the report as it is presented")
    inputs = _preview_inputs(dtxsid, DEFAULT_VIEW)
    steps.start("citations", "Checking every citation against the recorded sources, "
                             "and every source against the DOI system or its address")
    record = validate(dtxsid, view=DEFAULT_VIEW, inputs=inputs)
    counts = record["counts"]
    return {"passed": record["passed"], "checked_at": record["checked_at"],
            "citations": counts["citations"], "listed": counts["listed"],
            "errors": counts["errors"], "warnings": counts["warnings"]}


def check_citations(dtxsid: str) -> Iterator[dict]:
    """Check the report's citations as it is presented and record the result
    (rendering.citations_validate, ADR-0038); the run's events."""
    session_of(dtxsid)
    _require_act(dtxsid, CITATIONS)
    return _run_events(dtxsid, "the check of the citations",
                       lambda steps: _check_citations(dtxsid, steps))

