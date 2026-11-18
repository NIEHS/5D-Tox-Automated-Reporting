"""
ui_api.process_run — Process, as one long act of the new interface (the demo
path's "Process" page, docs/ui-redesign/modules/demo/spec.md §4 S2).

``start_process`` runs what tooling/generate_report.py runs after the data
review, in its order and through the safeguards:

    process_step                  the statistics, the benchmark doses, the
                                  tables, the figures and the drafted text
    materialize_result_sections   the results sections written as files
    materialize_summary           the Summary

It takes no run parameters: the study's own declarations decide (its pinned
method, its stated facts).  The one value passed is the test article's short
name, as the command line passes it.

The result says what is known of the run and no more: the units of work the
core computed and the ones it reused (its own cache events, ui_api.long_acts.
unit_events; ``recorded: false`` when they were not being recorded), the
results sections written, the approvals the new numbers knocked down or left
standing, the Summary, and the citations the check removed.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Iterator

logger = logging.getLogger(__name__)

# The core's units of work (pipeline.cache_plumbing), in plain words.  A unit
# this table does not know is named as the core names it.
_UNIT_SAY = {
    "ntp": "Statistics of the apical endpoints",
    "bmds": "Benchmark dose modeling of the apical endpoints",
    "sections": "Results tables",
    "genomics": "Gene expression results",
    "bmd_summary": "Benchmark dose summary",
    "charts": "Figures",
    "methods": "Materials and Methods",
    "content": "Drafted text: the results sentences and the gene-level interpretation",
}
_INTERPRETATION = re.compile(r"^interpretation_(?P<organ>.+)_(?P<sex>[^_]+)$")


def unit_say(unit: str) -> str:
    if unit in _UNIT_SAY:
        return _UNIT_SAY[unit]
    m = _INTERPRETATION.match(unit)
    if m:
        return f"Gene-level interpretation: {m['organ'].replace('_', ' ')}, {m['sex']}"
    return unit


def _compound_name(dtxsid: str, store) -> str:
    """The name Process is given for the test article: the study's short
    name, else its name, else its id (as tooling/generate_report.py)."""
    identity = store.read_json(dtxsid, "identity.json")
    identity = identity if isinstance(identity, dict) else {}
    return identity.get("abbreviation") or identity.get("name") or dtxsid


def _citations_removed(dtxsid: str, store) -> int | None:
    """How many citations the check removed from the drafted text
    (references.json ``warnings``); None when the run wrote no reference list."""
    references = store.read_json(dtxsid, "references.json")
    if not isinstance(references, dict) or not isinstance(references.get("warnings"), list):
        return None
    return len(references["warnings"])


def start_process(dtxsid: str) -> Iterator[str]:
    """Run Process on the study, then write its results sections and its
    Summary: one act, told as it goes (ui_api.long_acts).  Refused, before
    anything is run or answered: on the finished side of a demo pair, when
    Process is not legal now (the phase, a method no person chose, a study
    parameter not recorded or stated: the safeguards), and while another long
    act runs on the study."""
    from common.dtxsid import validate_dtxsid
    from pipeline.session_store import session_path
    from safeguards import guarded
    from safeguards.acts import require
    from ui_api import long_acts
    from ui_api.demo import require_not_reference
    from ui_api.studies import StudyRefusal
    from workflow.phases import Action
    from workflow.store import DiskPoolStore

    validate_dtxsid(dtxsid)
    if not session_path(dtxsid).is_dir():
        raise StudyRefusal("study_not_found", f"no session {dtxsid}", 404, {"id": dtxsid})
    require_not_reference(dtxsid)
    store = DiskPoolStore()
    require(dtxsid, Action.PROCESS, store, method=True)
    params = {"compound_name": _compound_name(dtxsid, store)}

    def work(report) -> dict:
        def on_unit(unit: str, status: str, ms: float | None) -> None:
            report(f"unit:{unit}", status, unit_say(unit), ms)

        with long_acts.unit_events(dtxsid, on_unit) as units:
            with long_acts.timed_step(report, "process", "The analysis"):
                payload = asyncio.run(guarded.process_step(dtxsid, params, store))
            outcome = units()
        with long_acts.timed_step(report, "result_sections", "Writing the results sections"):
            written = guarded.materialize_result_sections(dtxsid, store)
        with long_acts.timed_step(report, "summary", "Writing the Summary"):
            summary = guarded.materialize_summary(dtxsid, store)

        said = {"recorded": outcome["recorded"]}
        if outcome["recorded"]:
            said["computed"] = [{"unit": u, "say": unit_say(u)} for u in outcome["computed"]]
            said["reused"] = [{"unit": u, "say": unit_say(u)} for u in outcome["reused"]]
        return {
            "test_article": params["compound_name"],
            "units": said,
            "analysis": {
                "apical_sections": len(payload.get("sections") or []),
                "genomics_sections": len(payload.get("genomics_sections") or []),
                "methods": bool(payload.get("methods")),
            },
            "result_sections": {
                "written": written.get("materialized") or [],
                "unchanged": written.get("unchanged") or [],
            },
            # Approved sections whose numbers or wording the run changed (the
            # approval is withdrawn, to be given again), and owned sections
            # the run left as they were.
            "approvals_affected": {
                "needs_review": [{"key": r["key"], "why": r["why"]}
                                 for r in written.get("needs_review") or []],
                "held": written.get("held") or [],
            },
            "summary": {
                "written": bool(summary.get("written")),
                "paragraphs": summary.get("paragraphs") or 0,
                "held": summary.get("held"),
            },
            "citations_removed": _citations_removed(dtxsid, store),
        }

    return long_acts.start(dtxsid, "the analysis (Process)", work,
                           path=f"/api/v2/studies/{dtxsid}/process")
