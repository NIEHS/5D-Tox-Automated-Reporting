"""
ui_api.files — a study's data files: what each one is, what the check found,
and what can be done about it (module M2, docs/ui-redesign/modules/m2/).

  files_view   everything the Study files page shows, derived on each read:
               one row per file a person brought in, what the check recognized
               it as and whether a person has said otherwise, the check's own
               state and its findings in plain words, what the report would be
               built from, and which acts are allowed with the reason when one
               is not.

The read has no side effects: the session folder is located, never created,
nothing is re-scanned, no file id is minted and nothing is written. It reads
only what the check itself wrote — ``_fingerprints.json``,
``validation_report.json``, the sidecars and units files the application
writes beside a converted table, and what a person stated
(``classifications.json``) — never the bytes of a study file (CONTEXT.md
invariant 1), and never ``integrated.json``.

**Nothing is worked out here that the backend records.** The phase, the legal
actions and the run come from the read model; the findings' words come from
``workflow.file_issues``; the kinds of data a file can hold come from
``pipeline.classifications``. Where a record is missing, the field says so
rather than carrying a guess.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from ui_api.dataset import _converted_from, _fingerprints, _read
from ui_api.studies import StudyRefusal

logger = logging.getLogger(__name__)

#: What a study's files can be brought in as (no size limit: Q-M2-8).
ACCEPTED = (".bm2", ".csv", ".txt", ".xlsx", ".zip", ".units.json")

_SIDECAR = ".sidecar.json"
_UNITS = ".units.json"

#: A file's kind, from its ending, as a person speaks of it.
KIND_SAY = {"workbook": "Study workbook", "table": "Study table",
            "bm2": "BMDExpress project"}


# ---------------------------------------------------------------------------
# The files on disk, and which of them a person brought in
# ---------------------------------------------------------------------------

def _session(dtxsid: str) -> Path:
    """The study's folder; refused when the id is malformed or there is no such
    study. A report over several studies and a published book's companion are
    NOT refused here: the page shows each of them why it takes no files."""
    from common.dtxsid import validate_dtxsid
    from pipeline.session_store import session_path

    validate_dtxsid(dtxsid)
    session = session_path(dtxsid)
    if not session.is_dir():
        raise StudyRefusal("study_not_found", f"no session {dtxsid}", 404, {"id": dtxsid})
    return session



def _stem(name: str) -> str:
    for suffix in (_UNITS, _SIDECAR):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def _kind_of(name: str) -> str:
    from pipeline.classifications import kind_of
    return kind_of(Path(name).suffix.lstrip(".").lower())


def _listing(directory: Path) -> dict[str, dict]:
    """Each file of a directory with its size and when it last changed. One
    listing; the files themselves are never opened."""
    out: dict[str, dict] = {}
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return out
    for entry in entries:
        try:
            if not entry.is_file():
                continue
            stat = entry.stat()
        except OSError:
            continue
        out[entry.name] = {"size": stat.st_size, "mtime": stat.st_mtime}
    return out


def _rows_and_companions(session: Path, files: dict[str, dict],
                         fps: dict[str, dict]) -> dict[str, list[dict]]:
    """Which files are rows of their own, and what rides on each.

    A row is a file a person brought in. The sidecar and the units file beside
    a table ride on it, and so does a table the check wrote from a study
    workbook — the workbook is what was brought in (ADR-0032).
    """
    companions_of: dict[str, list[dict]] = {}
    rides_on: dict[str, str] = {}

    for name in files:
        if name.endswith(_SIDECAR) or name.endswith(_UNITS):
            owner = _stem(name)
            role = "sidecar" if name.endswith(_SIDECAR) else "units"
            for candidate in files:
                if candidate != name and _stem(candidate) == owner \
                        and not candidate.endswith((_SIDECAR, _UNITS)):
                    rides_on[name] = candidate
                    companions_of.setdefault(candidate, []).append(
                        {"name": name, "role": role,
                         "say": ("What the check recorded of the table"
                                 if role == "sidecar" else
                                 "The units of its measurements")})
                    break
            continue
        source = _converted_from(session, name, fps.get(name) or {})
        if source and source["filename"] in files:
            rides_on[name] = source["filename"]
            companions_of.setdefault(source["filename"], []).append(
                {"name": name, "role": "table",
                 "say": f"The table the check wrote from it "
                        f"({'recorded in the table' if source['recorded_in'] == 'sidecar' else 'recorded by the check'})"})

    # A file conversion set aside: the original the person brought in.
    for name in _listing(session / "_originals"):
        owner = next((f for f in files if _stem(f) == _stem(name)
                      and not f.endswith((_SIDECAR, _UNITS))), None)
        if owner:
            companions_of.setdefault(owner, []).append(
                {"name": name, "role": "original",
                 "say": "The file as it was brought in, kept after it was converted"})

    for name in files:
        if name not in rides_on and not name.endswith((_SIDECAR, _UNITS)):
            companions_of.setdefault(name, [])

    # A sidecar rides on the table it describes, and that table may itself ride
    # on the workbook it was written from. Everything is shown under the file a
    # person brought in, however long the chain.
    def gather(name: str, seen: set[str]) -> list[dict]:
        out = []
        for rides in companions_of.get(name, []):
            if rides["name"] in seen:
                continue
            seen.add(rides["name"])
            out.append(rides)
            out += gather(rides["name"], seen)
        return out

    return {name: sorted(gather(name, {name}), key=lambda c: c["name"])
            for name in companions_of if name not in rides_on}


# ---------------------------------------------------------------------------
# What a file is
# ---------------------------------------------------------------------------

def _units_of(session: Path, name: str, kind: str, checked: bool,
              data_type: str | None) -> dict:
    """The units of a table's measurements, as the application recorded them."""
    from pipeline.classifications import READ_FOR_ITSELF
    if kind in ("workbook", "bm2") or data_type in READ_FOR_ITSELF:
        return {"state": "not_needed", "values": {}, "say": None}
    units = _read(session / "files" / f"{_stem(name)}{_UNITS}")
    if isinstance(units, dict) and units:
        return {"state": "stated", "values": units,
                "say": ", ".join(f"{k}: {v}" for k, v in list(units.items())[:3])}
    sidecar = _read(session / "files" / f"{_stem(name)}{_SIDECAR}")
    recorded = sidecar.get("units") if isinstance(sidecar, dict) else None
    if isinstance(recorded, dict) and recorded:
        return {"state": "stated", "values": recorded,
                "say": ", ".join(f"{k}: {v}" for k, v in list(recorded.items())[:3])}
    if not checked:
        return {"state": "not_read", "values": {},
                "say": "The file check has not read this file yet."}
    return {"state": "missing", "values": {},
            "say": "No units were recorded, so its tables print [units pending]."}


def _classification(session: Path, name: str, fp: dict, kind: str,
                    stated: dict, on_disk: dict, checked: bool) -> dict:
    """What the file is taken to be, and on whose word.

    The check reads it from the file's name; a person can say otherwise, and
    that statement stands (pipeline.classifications). Nothing passes as
    confirmed by default.
    """
    from pipeline.classifications import DATA_TYPES, READ_FOR_ITSELF, changed_since

    said = stated.get(name)
    detected_platform, detected_type = fp.get("platform"), fp.get("data_type")
    platform = said["platform"] if said else detected_platform
    data_type = said["data_type"] if said else detected_type

    if data_type in READ_FOR_ITSELF:
        # Nobody states this: the file either holds it or it does not, and the
        # check reads which. It is not waiting for anyone.
        status = "read_for_itself"
    elif said:
        status = "changed" if (said.get("platform"), said.get("data_type")) != \
            (detected_platform, detected_type) else "confirmed"
        if changed_since(session, name, said):
            status = "needs_reconfirm"
    elif not checked:
        status = "not_checked"
    elif not data_type:
        status = "not_recognized"
    else:
        status = "unconfirmed"

    def say_of(p, d):
        words = (DATA_TYPES.get(d) or READ_FOR_ITSELF.get(d) or d) if d else None
        if p and words:
            return f"{p} · {words}"
        return words or p or "not recognized"

    return {
        "platform": platform,
        "data_type": data_type,
        "say": say_of(platform, data_type),
        "detected": {
            "platform": detected_platform, "data_type": detected_type,
            "basis": "file_name" if detected_type else "none",
            "say": ("From the file's name" if detected_type else
                    "The check could not tell what this file is from its name."),
            "say_full": say_of(detected_platform, detected_type),
        },
        "stated": ({"platform": said.get("platform"), "data_type": said.get("data_type"),
                    "by": said.get("by"), "at": said.get("at")} if said else None),
        "status": status,
        "flags": [],
    }


#: What a reading of a project's test article rests on, in plain words, and
#: whether it is a reading at all.  "none" and "project_not_read" are not the
#: same thing and must never be shown alike: one says the names carry no test
#: article, the other says nothing was read.
_TEST_ARTICLE_BASIS = {
    "experiment_names_llm": (
        "read by a language model from the names of the project's experiments"),
    "experiment_names_regex": (
        "read from the names of the project's experiments by a name pattern"),
    "none": (
        "the names of the project's experiments carry no test article, so the "
        "application cannot tell what this project is of"),
    "unavailable": (
        "the names of the project's experiments could not be read, so this was "
        "not checked"),
    "project_not_read": (
        "the project itself was not opened, so nothing in it has been read"),
}


def _bm2_of(fp: dict) -> dict:
    """What a BMDExpress project holds, and on whose word.

    A project of more than one test article carries another study's data. The
    reading travels with where it came from, so a person is never shown a
    language model's reading as though the file had stated it, nor silence as
    though it were agreement.
    """
    basis = fp.get("test_article_basis")
    articles = list(fp.get("test_articles") or [])
    experiments = list(fp.get("experiment_names") or fp.get("endpoint_names") or [])
    return {
        "experiments": experiments,
        "species": fp.get("species"),
        "genes": fp.get("gene_count"),
        "test_articles": articles,
        "test_article_basis": basis,
        "test_article_say": (
            f"Of {', '.join(articles)}" if articles else "Test article not established"),
        "test_article_from": _TEST_ARTICLE_BASIS.get(basis or "", (
            "where this reading came from is not recorded")),
        # A reading by a language model is a reading, not a record.
        "test_article_is_a_reading": basis in ("experiment_names_llm",
                                               "experiment_names_regex"),
    }


def _tables_of(fp: dict) -> list[dict]:
    """What the check recorded of a file's contents. Read as written."""
    if not fp:
        return []
    endpoints = list(fp.get("endpoint_names") or [])
    return [{
        "sexes": list(fp.get("sexes") or []),
        "doses": list(fp.get("dose_groups") or []),
        "dose_unit": fp.get("dose_unit"),
        "animals": len(fp.get("animal_ids") or []),
        "animals_by_dose": dict(fp.get("n_animals_by_dose") or {}),
        "measurements": len(endpoints),
        "measurement_sample": endpoints[:5],
        "selection_groups": list(fp.get("selection_groups") or []),
    }]


def _file_row(session: Path, name: str, files: dict[str, dict], fps: dict[str, dict],
              stated: dict, companions: list[dict], issues: list[dict],
              acts: dict) -> dict:
    fp = fps.get(name) or {}
    kind = _kind_of(name)
    checked = bool(fp)
    on_disk = files.get(name) or {}
    classification = _classification(session, name, fp, kind, stated, on_disk, checked)
    units = _units_of(session, name, kind, checked, classification["data_type"])

    pending = []
    if units["state"] == "missing":
        pending.append({"what": "units", "say": "[units pending]", "fix": "M2"})
    if classification["status"] in ("not_recognized", "unconfirmed", "needs_reconfirm"):
        pending.append({"what": "classification",
                        "say": "[not confirmed]" if classification["status"] != "not_recognized"
                               else "[not recognized]", "fix": "M2"})

    return {
        "name": name,
        "kind": kind,
        "kind_say": KIND_SAY[kind],
        "type": Path(name).suffix.lstrip(".").lower(),
        "size": on_disk.get("size"),
        "added_at": fp.get("ts_added"),
        "companions": companions,
        "units": units,
        "tables": _tables_of(fp) if kind != "bm2" else [],
        "bm2": (_bm2_of(fp) if kind == "bm2" else None),
        "bm2_changes": None,       # what a project fills in or leaves out: not built yet
        "narrow_choices": None,    # keeping only this study's experiments: not built yet
        "study_number": fp.get("study_number"),
        "checked": checked,
        "classification": classification,
        "issues": [one["id"] for one in issues if name in one["files"]],
        "pending": pending,
        "acts": {"remove": acts["remove"], "classify": acts["classify"], "narrow": None},
    }


# ---------------------------------------------------------------------------
# The check, its findings and what the report would be built from
# ---------------------------------------------------------------------------

def _disagreeing(report: dict, statements: dict) -> set[str]:
    """The files a person said something other than what the check concluded."""
    recorded = {fp.get("filename"): (fp.get("platform"), fp.get("data_type"))
                for fp in (report.get("fingerprints") or {}).values()
                if isinstance(fp, dict)}
    return {name for name, said in statements.items()
            if name in recorded
            and (said.get("platform"), said.get("data_type")) != recorded[name]}


def _check_state(session: Path, report: dict | None, files: dict[str, dict],
                 statements: dict, counts: dict[str, int]) -> dict | None:
    """When the check last ran, and whether it still describes these files."""
    if not isinstance(report, dict) or not report.get("run_at"):
        return None
    recorded = {fp.get("filename") for fp in (report.get("fingerprints") or {}).values()
                if isinstance(fp, dict)}
    present = {n for n in files if not n.endswith((_SIDECAR, _UNITS))}
    why = None
    if present - recorded:
        why = _say_names(sorted(present - recorded), "came into the study after the check ran")
    elif recorded - present:
        why = _say_names(sorted(recorded - present), "is no longer in the study")
    else:
        # A statement that disagrees with what the check concluded leaves the
        # check describing something else. A confirmation that agrees with it
        # changes nothing, and does not send a person back to check again.
        disagree = sorted(_disagreeing(report, statements))
        if disagree:
            why = _say_names(disagree, "was corrected after the check ran")
    return {"run_at": report["run_at"], "current": why is None, "why_not_current": why,
            "counts": {"fix": counts.get("fix", 0), "look": counts.get("look", 0),
                       "expected": counts.get("expected", 0)},
            "not_shown": ({"count": counts["elsewhere"], "fix": "M5",
                           "say": f"{counts['elsewhere']} findings about the analysis "
                                  f"method are shown with the method."}
                          if counts.get("elsewhere") else None)}


def _at(when: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat(when).timestamp()


def _say_names(names: list[str], tail: str) -> str:
    first = names[0]
    if len(names) == 1:
        return f"{first} {tail}."
    return f"{first} and {len(names) - 1} more {tail}."


def _coverage(report: dict | None, names: dict[str, str]) -> list[dict]:
    """What the report would be built from, per assay and kind of data."""
    matrix = report.get("coverage_matrix") if isinstance(report, dict) else None
    if not isinstance(matrix, dict):
        return []
    from pipeline.classifications import DATA_TYPES
    from workflow.file_issues import _platform_say

    out = []
    for key, slots in sorted(matrix.items()):
        if not isinstance(slots, dict):
            continue
        tables = [names.get(i, i) for i in (slots.get("txt_csv") or [])]
        workbook = names.get(slots.get("xlsx")) if slots.get("xlsx") else None
        bm2 = names.get(slots.get("bm2")) if slots.get("bm2") else None
        data_type = key.split("|", 1)[1] if "|" in key else key
        if tables or bm2:
            level, say = "ok", "This assay's data would be combined."
        elif workbook:
            level, say = "block", ("Only the study workbook is here. Nothing of this "
                                   "assay would be combined until a table is written "
                                   "from it, which the file check does.")
        else:
            level, say = "block", "Nothing of this assay would be combined."
        out.append({"key": key, "assay": _platform_say(key),
                    "data_type": data_type,
                    "data_type_say": DATA_TYPES.get(data_type, data_type),
                    "workbook": workbook, "tables": tables, "bm2": bm2,
                    "level": level, "say": say})
    return out


def _removed(session: Path) -> tuple[list[dict], int]:
    """The files taken out of the study, which are kept."""
    out, total = [], 0
    root = session / "_removed"
    if not root.is_dir():
        return out, 0
    for entry in sorted(root.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        listing = _listing(entry)
        size = sum(f["size"] for f in listing.values())
        total += size
        out.append({
            "id": f"rm_{entry.name}", "at": entry.name, "size": size,
            "files": sorted(listing),
            "say": "Removed from the study",
            # Putting one back is not built yet; the page says so rather than
            # offering a control that would refuse.
            "acts": {"restore": {"allowed": False, "code": "not_built_yet",
                                 "say": "Putting a removed file back is not built yet. "
                                        "The file is kept and can be brought in again."}},
        })
    return out, total


# ---------------------------------------------------------------------------
# What can be done, and what comes next
# ---------------------------------------------------------------------------

def _verdict(allowed: bool, code: str | None = None, say: str | None = None) -> dict:
    return {"allowed": allowed, "code": code, "say": say}


def _say(code: str, **fields) -> str:
    """A refusal's words from the catalog, so an act and the page that offers
    it never word the same refusal twice."""
    from ui_api import files_acts  # noqa: F401  (registers this page's codes)
    from ui_api.refusals import say
    return say(code, **fields)


def _acts(state: dict, has_files: bool, checked: bool) -> dict:
    """Each act with whether it is allowed now, and the reason when it is not.
    Which acts are legal is the backend's (workflow.phases)."""
    legal = set(state.get("legal_actions") or [])
    run = state.get("run") or {}
    if run.get("in_flight"):
        busy = _verdict(False, "run_in_flight",
                        f"{run.get('what') or 'An act'} is running on this study. "
                        f"The files cannot change while it runs.")
        return {act: busy for act in ("add", "check", "classify", "resolve", "remove", "reset")}

    stands = (state.get("stands") or {}).get("say") or "the study's stage"
    def by(action: str, reason: str) -> dict:
        return _verdict(True) if action in legal else _verdict(False, "phase_not_allowed", reason)

    return {
        "add": by("ADD_FILES", f"Files cannot be brought in now ({stands})."),
        "check": (by("VALIDATE", f"The files cannot be checked now ({stands}).")
                  if has_files else
                  # The act refuses this in the same words (ui_api.files_acts).
                  _verdict(False, "no_files", _say("no_files"))),
        "classify": (by("CONFIRM_CLASSIFICATION",
                        "Run the file check first: it says what each file is.")
                     if checked else
                     _verdict(False, "not_validated",
                              "Run the file check first: it says what each file is.")),
        "resolve": by("RESOLVE", "Run the file check first: it finds the conflicts."),
        "remove": by("REMOVE_FILE", f"A file cannot be removed now ({stands})."),
        "reset": by("RESET", f"The files cannot be started over now ({stands})."),
    }


def _progress(rows: list[dict], check: dict | None, counts: dict[str, int]) -> list[dict]:
    # A file the application reads for itself is not waiting for anyone.
    waiting = ("unconfirmed", "not_recognized", "needs_reconfirm", "not_checked")
    unconfirmed = [r for r in rows if r["classification"]["status"] in waiting]
    confirmable = [r for r in rows if r["classification"]["status"] != "read_for_itself"]
    steps = [{"step": "bring_in",
              "status": "done" if rows else "todo",
              "say": (f"{len(rows)} files in the study" if rows else "No files yet")}]
    if check is None:
        steps.append({"step": "check", "status": "todo" if rows else "waiting",
                      "say": "Not checked yet"})
    elif counts.get("fix"):
        steps.append({"step": "check", "status": "blocked",
                      "say": f"{counts['fix']} must be fixed"})
    else:
        steps.append({"step": "check",
                      "status": "todo" if not check["current"] else "done",
                      "say": ("The files changed since the check ran"
                              if not check["current"] else "Nothing blocks")})
    steps.append({"step": "confirm",
                  "status": "done" if rows and not unconfirmed else
                            ("waiting" if not rows or check is None else "todo"),
                  "say": (f"{len(unconfirmed)} of {len(confirmable)} not yet confirmed"
                          if unconfirmed else
                          (f"All {len(confirmable)} confirmed" if rows else "No files yet"))})
    return steps


def _next(rows: list[dict], check: dict | None, counts: dict[str, int],
          progress: list[dict]) -> dict:
    if not rows:
        return {"act": "ADD_FILES", "say": "Bring in the study's files", "fix": "M2"}
    if check is None or not check["current"]:
        return {"act": "VALIDATE", "say": "Check the files", "fix": "M2"}
    if counts.get("fix"):
        return {"act": None, "say": "Fix the problems the check found", "fix": "M2"}
    confirm = next(s for s in progress if s["step"] == "confirm")
    if confirm["status"] != "done":
        return {"act": "CONFIRM_CLASSIFICATION", "say": "Confirm what each file is", "fix": "M2"}
    return {"act": "INTEGRATE", "say": "Combine the files into one dataset", "fix": "M3"}


def _choices() -> dict[str, list[dict]]:
    """What a person can say a file is, per kind of file. The page never offers
    a value the backend did not list, and the backend checks against this same
    table (pipeline.classifications)."""
    from pipeline.classifications import BY_KIND, DATA_TYPES, platforms
    return {kind: [{"data_type": data_type, "label": DATA_TYPES[data_type],
                    "platforms": [] if data_type == "gene_expression" else platforms()}
                   for data_type in allowed]
            for kind, allowed in BY_KIND.items()}


def _token(files: dict[str, dict], session: Path) -> str:
    """What this list of files is, so an act can refuse when it changed."""
    parts = [f"{name}:{f['size']}:{f['mtime']}" for name, f in sorted(files.items())]
    from pipeline.classifications import path_of
    try:
        parts.append(f"statements:{path_of(session).stat().st_mtime}")
    except OSError:
        pass
    return "sha256:" + hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------------

def files_view(dtxsid: str) -> dict:
    """Everything the Study files page shows, derived from what is on disk."""
    from pipeline.classifications import read as read_statements
    from ui_api.read_model import study_state
    from workflow import file_issues

    session = _session(dtxsid)
    state = study_state(dtxsid)
    kind = state.get("kind")
    if kind in ("companion", "report"):
        # Its data is not its own (R6). The page says so and offers nothing,
        # rather than refusing the read: a person who opened it needs to read
        # why, and where the files belong instead.
        return _takes_no_files(dtxsid, state, kind)

    files = _listing(session / "files")
    fps = _fingerprints(session)
    statements = read_statements(session)
    report = _read(session / "validation_report.json")
    report = report if isinstance(report, dict) else None

    names = {fp.get("file_id"): name for name, fp in fps.items() if fp.get("file_id")}
    if report:
        names.update({fid: fp.get("filename", fid)
                      for fid, fp in (report.get("fingerprints") or {}).items()
                      if isinstance(fp, dict)})

    issues = [file_issues.say(one, names) for one in (report or {}).get("issues") or []]
    counts = file_issues.counts(issues)
    check = _check_state(session, report, files, statements, counts)
    companions = _rows_and_companions(session, files, fps)
    acts = _acts(state, bool(companions), check is not None)

    rows = [_file_row(session, name, files, fps, statements, rides, issues, acts)
            for name, rides in sorted(companions.items())]
    progress = _progress(rows, check, counts)
    removed, removed_size = _removed(session)

    return {
        "id": dtxsid,
        "phase": state.get("phase"),
        "takes_files": {"allowed": True, "code": None, "say": None},
        "files_token": _token(files, session),
        "progress": progress,
        "next": _next(rows, check, counts, progress),
        "acts": acts,
        "files": rows,
        "check": check,
        "issues": [one for one in issues if one["group"] != "elsewhere"],
        # Settling a disagreement between two files inside the application is
        # not built: each one says who settles it and how.
        "conflicts": [],
        "coverage": _coverage(report, names),
        "removed": removed,
        "removed_size": removed_size,
        "records": {"files": {"count": None}, "datasets": {"count": 0, "current": None}},
        "integration": _integration(dtxsid),
        "classification_choices": _choices(),
        "limits": {"accepted": list(ACCEPTED)},
    }


def _integration(dtxsid: str) -> dict | None:
    """Whether the dataset these files were combined into still matches them
    (workflow.integration_basis: the record integration kept of what it was
    built from)."""
    from ui_api.read_model import ReadOnlyDiskPoolStore
    from workflow.integration_basis import integration_status

    status = integration_status(dtxsid, ReadOnlyDiskPoolStore())
    if not status:
        return None
    say = {"current": "These files were combined into one dataset. Changing them "
                      "means combining them again, and processing again.",
           "out_of_date": "The files have changed since they were combined. The "
                          "dataset is kept but is not used until they are "
                          "combined again.",
           "unrecorded": "These files were combined, but no record says which "
                         "check the dataset was built from."}.get(status)
    return {"state": status, "say": say, "fix": "M3"}


def _takes_no_files(dtxsid: str, state: dict, kind: str) -> dict:
    """A published book's companion, or a report over several studies: its data
    is not its own, so it takes no files (R6)."""
    if kind == "companion":
        say = "This is the published book's own content. It takes no data files."
    else:
        listed = [m.get("id") for m in (state.get("members") or []) if isinstance(m, dict)]
        members = ", ".join(m for m in listed if m) or "its studies"
        say = (f"A report over several studies takes no files: its studies do. "
               f"Bring the files into {members}.")
    nothing = _verdict(False, "takes_no_files", say)
    return {
        "id": dtxsid, "phase": state.get("phase"),
        "takes_files": {"allowed": False, "code": "takes_no_files", "say": say},
        "files_token": None, "progress": [], "next": {"act": None, "say": say, "fix": "M1"},
        "acts": {act: nothing for act in
                 ("add", "check", "classify", "resolve", "remove", "reset")},
        "files": [], "check": None, "issues": [], "conflicts": [], "coverage": [],
        "removed": [], "removed_size": 0,
        "records": {"files": {"count": None}, "datasets": {"count": 0, "current": None}},
        "integration": None, "classification_choices": _choices(),
        "limits": {"accepted": list(ACCEPTED)},
    }


__all__ = ["files_view", "ACCEPTED", "StudyRefusal"]
