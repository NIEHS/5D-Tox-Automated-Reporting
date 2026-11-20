"""
safeguards.publish — the publish gate: the report ships only when every
section a data change regenerated has been read and accepted again, every
flagged apical BMD is reviewed, and its citations, checked on the report as it
stands, passed (rendering.citations_validate; the last act before publishing).

Readiness is derived state (workflow.engine.WorkflowEngine.publish_readiness,
from section currency); refusing to ship on it is the safeguard. Every route
that ships the report (the preview download, the Overleaf bundle) and the
command line apply it; the command line's ``--draft`` is the one named
override, logged. The notebook's renders are ungated: a working view.
"""

from __future__ import annotations

import logging

from safeguards.refusals import Refused

logger = logging.getLogger(__name__)


_CITATIONS = {
    "citations_not_checked": "its citations have not been checked",
    "citations_out_of_date": "it changed after its citations were checked",
    "citations_failed": "the check of its citations found errors",
}


def require_publishable(dtxsid: str, store=None, *, draft: bool = False) -> dict:
    """The study's publish readiness; refused (``publish_blocked``) when it is
    closed, unless ``draft`` — the override, logged."""
    from workflow.engine import WorkflowEngine
    from workflow.store import DiskPoolStore

    readiness = WorkflowEngine(dtxsid, store or DiskPoolStore()).publish_readiness()
    if readiness.get("can_publish", True):
        return readiness
    blocking = readiness.get("blocking") or []
    keys = ", ".join(b.get("section_key", "?") for b in blocking)
    if draft:
        logger.warning("publish gate closed for %s (%s): rendering anyway, as a draft",
                       dtxsid, keys)
        return readiness
    citations = [b for b in blocking if b.get("section_key") == "citations"]
    if citations and len(citations) == len(blocking):
        # Everything else is settled: the citation check is the last act.
        reason = citations[0].get("reason", "citations_not_checked")
        raise Refused(reason, f"Report is not publishable: {_CITATIONS[reason]}",
                      status_code=409, details={"keys": "citations", "blocking": blocking})
    sections = [b for b in blocking if b not in citations
                and not str(b.get("section_key", "")).startswith("bmd_review:")]
    if not sections:
        bmds = ", ".join(b["section_key"].split(":", 1)[1] for b in blocking
                         if b not in citations)
        raise Refused(
            "bmd_review_required",
            f"Report is not publishable: apical BMDs await review or a Process ({bmds})",
            status_code=409, details={"keys": bmds, "blocking": blocking})
    raise Refused(
        "publish_blocked",
        f"Report is not publishable: re-accept the sections a change of data or knowledge base "
        f"invalidated ({', '.join(b['section_key'] for b in sections)})",
        status_code=409, details={"keys": keys, "blocking": blocking})
