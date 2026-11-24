"""
ui_api.files_acts — what can be done to a study's data files (module M2).

  bring_in      take a batch of files into the study, each one checked first
  start_check   run the file check, told as it goes (a long act)

Both go through ``safeguards.guarded``, never ``workflow.steps``: whether an
act is legal in the study's phase is the safeguards' to say, not this layer's.

**Bringing files in is one act.**  The files are written to a scratch folder
beside the study's, planned against the study as it stands
(``pipeline.intake``), and only then moved in.  While any file in the batch
still waits on a person's answer — it would replace one already there, it
repeats another's contents under a new name, or a per-animal table came with
no units — nothing at all is written into the study, and the plan comes back
so the answer is given against what was actually found.  The scratch folder
goes either way.

``files_token`` is the study's files as the page last saw them.  A batch sent
against a token that no longer matches is refused (``files_changed``) rather
than applied to a study that changed underneath the page.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Iterator

from safeguards.refusals import Refusal, StudyRefusal, register

logger = logging.getLogger(__name__)

#: The refusals of this page's acts.  ``fix``: the place that clears it.
FILE_REFUSALS: dict[str, Refusal] = {
    "no_files_sent": Refusal(400, (
        "No files were sent. Choose the study's data files, or drop them on the page."),
        None),
    "answer_required": Refusal(409, (
        "{count} of the files sent need an answer before any of them is brought in: "
        "the batch is one act. Nothing was brought in."), "files"),
    "files_changed": Refusal(409, (
        "The study's files changed after this page read them. Nothing was brought in; "
        "read the page again and send the batch once more."), "files"),
    "batch_refused": Refusal(400, (
        "None of the {count} files sent can be brought into a study. Nothing was "
        "brought in."), "files"),
}
# ``no_files`` is the shared catalog's (safeguards.refusals): a study with no
# data files is refused in the same words wherever it is asked for one.
register(FILE_REFUSALS)

#: A name sent by a browser is never trusted as a path.
_MAX_NAME = 200


def _safe_name(name: str) -> str:
    """The bare file name a browser sent, with no path in it.  A name that
    cannot be used at all becomes one the plan will refuse in words."""
    bare = Path(str(name or "")).name.strip()
    bare = bare.replace("\x00", "")
    if not bare or bare in (".", ".."):
        return "unnamed"
    return bare[:_MAX_NAME]


def _scratch(session: Path) -> Path:
    """A folder for the batch, beside the study's own so the move into
    ``files/`` stays on one filesystem."""
    session.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="_intake_", dir=session))


def bring_in(dtxsid: str, uploads: list[tuple[str, BinaryIO]], *,
             answers: dict | None = None, files_token: str | None = None,
             dry_run: bool = False) -> dict:
    """Take a batch of files into the study, each one checked before it is
    written (``pipeline.intake`` through ``safeguards.guarded.bring_in_step``).

    ``uploads``: the browser's (name, bytes) pairs.  ``answers``: the names a
    person answered for, by what was asked (``replace``, ``copy_anyway``,
    ``without_units``).  ``dry_run``: plan and carry nothing out.

    Returns the plan — one row per file with its verdict and the words for it —
    with ``applied`` saying whether it was carried out.
    """
    from safeguards import guarded
    from ui_api.demo import require_not_reference
    from ui_api.files import _listing, _session, _token
    from workflow.store import DiskPoolStore

    session = _session(dtxsid)
    require_not_reference(dtxsid)
    if not uploads:
        raise StudyRefusal("no_files_sent", "no files in the request", 400, {})

    if files_token:
        now = _token(_listing(session / "files"), session)
        if now != files_token:
            raise StudyRefusal("files_changed",
                               f"files_token {files_token} is not {now}", 409,
                               {"sent": files_token, "now": now})

    batch = _scratch(session)
    try:
        for name, stream in uploads:
            target = batch / _safe_name(name)
            with target.open("wb") as out:
                shutil.copyfileobj(stream, out)
        out = guarded.bring_in_step(dtxsid, batch, DiskPoolStore(),
                                    answers=answers, apply=not dry_run)
    finally:
        shutil.rmtree(batch, ignore_errors=True)

    counts = out["counts"]
    if not dry_run and not out["applied"]:
        raise StudyRefusal("answer_required",
                           f"{counts['needs_answer']} rows need an answer", 409,
                           {"count": counts["needs_answer"], "rows": out["rows"],
                            "counts": counts})
    if not dry_run and not out["brought_in"] and not counts["unchanged"]:
        raise StudyRefusal("batch_refused", "nothing in the batch could be brought in",
                           400, {"count": len(out["rows"]), "rows": out["rows"],
                                 "counts": counts})

    logger.info("%s: intake %s (%d rows)", dtxsid,
                "planned" if dry_run else "applied", len(out["rows"]))
    return {"id": dtxsid, "applied": out["applied"], "dry_run": dry_run,
            "rows": out["rows"], "counts": counts,
            "brought_in": out["brought_in"], "replaced": out["replaced"],
            "files_token": _token(_listing(session / "files"), session)}


def answers_from(raw: str | None) -> dict:
    """The answers a browser sent as one JSON field, read back safely.  Only
    the three questions the plan asks are taken, and only lists of names."""
    try:
        sent = json.loads(raw) if raw else {}
    except ValueError:
        sent = {}
    if not isinstance(sent, dict):
        return {}
    return {key: [str(n) for n in sent.get(key) or [] if isinstance(n, str)]
            for key in ("replace", "copy_anyway", "without_units")}


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def start_check(dtxsid: str) -> Iterator[str]:
    """Check the study's files against each other and against its workbook:
    one long act, told as it goes (``ui_api.long_acts``).  A large BMDExpress
    project takes about half a minute the first time it is read.

    Refused, before anything is run or answered: on the finished side of a
    demo pair, when the act is not legal in the study's phase, and while
    another long act runs on the study.
    """
    from safeguards import guarded
    from ui_api import long_acts
    from ui_api.demo import require_not_reference
    from ui_api.files import _listing, _session
    from workflow import file_issues
    from workflow.store import DiskPoolStore

    session = _session(dtxsid)
    require_not_reference(dtxsid)
    if not _listing(session / "files"):
        # A check of nothing would write a report saying so, and the page
        # would then read the study as checked.
        raise StudyRefusal("no_files", f"{dtxsid} has no files", 404, {})
    store = DiskPoolStore()

    def work(report) -> dict:
        with long_acts.timed_step(report, "check", "Checking the study's files"):
            report_dict = guarded.validate_step(dtxsid, store)
        names = {fid: fp.get("filename", fid)
                 for fid, fp in (report_dict.get("fingerprints") or {}).items()
                 if isinstance(fp, dict)}
        said = [file_issues.say(one, names) for one in report_dict.get("issues") or []]
        counts = file_issues.counts(said)
        return {"files": len(report_dict.get("fingerprints") or {}),
                "fix": counts.get("fix", 0), "look": counts.get("look", 0),
                "expected": counts.get("expected", 0)}

    return long_acts.start(dtxsid, "checking the study's files", work,
                           path=f"/api/v2/studies/{dtxsid}/check")


__all__ = ["bring_in", "answers_from", "start_check", "FILE_REFUSALS"]
