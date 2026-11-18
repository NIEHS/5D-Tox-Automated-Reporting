"""
ui_api.demo — a finished report and its live copy, set apart as a pair.

tooling.demo_copy makes a live copy of a finished report for a demonstration
and names the two in the store's partitions (sessions/_partitions.json,
``{"Demo": [<report>, <report>_live]}``).  This module tells a front end what
it needs of that:

* ``partitions``: the declared partitions, each with the sessions it names;
* ``pair_of``: for a session of a pair (a report, or one of its studies), its
  role (``finished`` or ``live``) and the session that corresponds to it on
  the other side.  The role is read from the copy's marker (demo_copy.json),
  not from the partition's order: a copy says what it was copied from;
* ``require_not_reference``: the finished side of a pair is what the live run
  is compared with, so the interface's acts leave it as it is.

All of it is read from disk on every call; nothing is stored here.
"""

from __future__ import annotations

import json
from pathlib import Path

from tooling.demo_copy import MARKER, PARTITIONS_FILE


def _root() -> Path:
    import common.paths
    return common.paths.SESSIONS_DIR


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def partitions(root: Path | None = None) -> list[dict]:
    """``[{name, sessions: [id, …]}]`` as declared, in the file's order."""
    data = _json((root or _root()) / PARTITIONS_FILE)
    if not isinstance(data, dict):
        return []
    return [{"name": str(name), "sessions": [i for i in ids if isinstance(i, str)]}
            for name, ids in data.items() if isinstance(ids, list)]


def _partition_of(ids: set[str], root: Path) -> str | None:
    for p in partitions(root):
        if ids & set(p["sessions"]):
            return p["name"]
    return None


def pair_of(dtxsid: str, root: Path | None = None) -> dict | None:
    """``{partition, role, counterpart, counterpart_exists, report}`` for a
    session of a pair; None for any other session.  ``report``: the report of
    the session's own side (itself, for a report)."""
    root = root or _root()
    marker = _json(root / dtxsid / MARKER)
    if isinstance(marker, dict) and isinstance(marker.get("source"), str):
        source, of = marker["source"], marker.get("of")
        mine = next((p.parent.name for p in sorted(root.glob(f"*/{MARKER}"))
                     if (_json(p) or {}).get("source") == of), dtxsid)
        return {"partition": _partition_of({mine, of}, root), "role": "live",
                "counterpart": source, "counterpart_exists": (root / source).is_dir(),
                "report": mine}
    for path in sorted(root.glob(f"*/{MARKER}")):
        other = _json(path)
        if isinstance(other, dict) and other.get("source") == dtxsid:
            of = other.get("of")
            live_report = next((p.parent.name for p in sorted(root.glob(f"*/{MARKER}"))
                                if (_json(p) or {}).get("source") == of), None)
            return {"partition": _partition_of({of, live_report} - {None}, root),
                    "role": "finished", "counterpart": path.parent.name,
                    "counterpart_exists": True, "report": of}
    return None


def require_not_reference(dtxsid: str) -> None:
    """Refuse an act on the finished side of a pair (``demo_reference``)."""
    from ui_api.studies import StudyRefusal

    pair = pair_of(dtxsid)
    if pair and pair["role"] == "finished":
        raise StudyRefusal(
            "demo_reference", f"{dtxsid} is the finished report of a pair; acts go to "
            f"its live copy {pair['counterpart']}", 409,
            {"id": dtxsid, "counterpart": pair["counterpart"]})


_MADE_FROM = {
    "integrated.json": "the combined dataset",
    "animal_report.json": "the accounting of the animals",
    "references.json": "the reference list",
    "background.json": "the Background",
    "summary.json": "the Summary",
    "history": "the earlier versions of its sections",
    "narrative_runs": "the record of what the language model was sent",
}


def _made_words(names: list[str]) -> str:
    """What a live session holds beyond its start state, in plain words."""
    words = [w for name, w in _MADE_FROM.items() if name in names]
    tables = sum(1 for n in names if n.startswith("bm2_"))
    if tables:
        words.append(f"{tables} results section{'s' if tables != 1 else ''}")
    if any(n.startswith("_cache_") or n.startswith("session") for n in names):
        words.append("the results of Process")
    return ", ".join(words)


def reset_preview(report: str) -> dict:
    """What a reset of the live copy would delete and keep (MODULES.md §4.3)."""
    from tooling import demo_copy
    from ui_api.studies import StudyRefusal

    try:
        status = demo_copy.status(report)
    except demo_copy.DemoCopyError as e:
        raise StudyRefusal("study_not_found", str(e), 404, {"id": report}) from None
    live = [s for s in status["sessions"] if s["exists"] and s["is_copy"]]
    if not live:
        raise StudyRefusal("demo_copy_refused", f"{report} has no live copy", 409,
                           {"id": report, "why": "this report has no live copy"})
    deletes = [{"what": s["id"], "say": f"{s['id']}: {_made_words(s['beyond_start'])}"}
               for s in live if _made_words(s["beyond_start"])]
    return {
        "act": "reset_live_copy", "strength": "costly", "deletes": deletes,
        "keeps": [
            {"what": report, "say": f"The finished report {report} and its studies: they "
                                    "are only read."},
            {"what": "start", "say": "The live copy's files, as checked, with the study "
                                     "facts, the analysis method and the report definition "
                                     "already stated."}],
        "approvals_lost": [],
        "cost": {"say": "To come back to where the live copy is now, each study is "
                        "combined and processed again."} if deletes else None,
        "reason_required": False,
    }


def reset_live_copy(report: str) -> dict:
    """Put the live copy of ``report`` back to its start state, and drop what
    this process holds in memory of its sessions.  Refused while a long act
    runs on any of them, and with the tool's own reason otherwise."""
    from pipeline.pool_globals import forget_session
    from tooling import demo_copy
    from ui_api import runs
    from ui_api.studies import StudyRefusal

    try:
        plan = demo_copy.plan(report)
    except demo_copy.DemoCopyError as e:
        raise StudyRefusal("study_not_found", str(e), 404, {"id": report}) from None
    copies = [plan["report"][1], *(copy for _, copy in plan["members"].values())]
    with runs.running(copies[0], "the reset of the live copy", *copies[1:]):
        try:
            out = demo_copy.reset(report)
        except demo_copy.DemoCopyError as e:
            raise StudyRefusal("demo_copy_refused", str(e), 409,
                               {"id": report, "why": str(e)}) from None
        for copy in copies:
            forget_session(copy, _root() / copy / "files")
    return out
