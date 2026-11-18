#!/usr/bin/env python3
"""tooling/demo_copy.py — a live copy of a finished report, for a demonstration.

A demonstration steps through the workflow in real time on a copy of a report
that is already finished, and falls back on the finished one.  The copy lives
in the same store under ids of its own:

    <report>_live                 the report over the studies
    <report>_live_<key>           each of its studies ("rat", "mouse")

(a report of one study is the report session alone).

The copy starts where a study stands when its files have been brought in and
checked, and what the files do not record has been stated:

  * the artifacts of workflow steps 1 to 4 (docs/ui-redesign/HANDOFF.md §5):
    files/, _originals/, _fingerprints.json, validation_report.json,
    precedence.json;
  * the declarations of steps 6 and 7: the stated study facts, the approved
    experiment descriptions, the front matter, the identity, the pinned method
    and report definition, the knowledge base, the model choices, the reviewer's
    decisions on flagged benchmark doses, the deposit and the eFDR record;
  * the report definition, FIXED (document_model.definition_pin.pin_like): a
    study's own definition is found by its session id, which a copy does not
    have, so the copy is pinned to the definition its source renders from.

Nothing else is copied: no combined dataset, no result, no written section, no
reference list, no history.  The phase is derived from what is there
(workflow.phases), so the copy reads as checked, with Integrate as its next step.

    python -m tooling.demo_copy make   DTXSID6020430          # refuses if a copy exists
    python -m tooling.demo_copy reset  DTXSID6020430          # back to the start state
    python -m tooling.demo_copy reset  DTXSID6020430 --cold   # … without the results cache
    python -m tooling.demo_copy remove DTXSID6020430
    python -m tooling.demo_copy status DTXSID6020430

``reset`` (and ``make --warm``) also puts the finished studies' results cache
(_cache_*.json) into the copy.  The cache is keyed by the content of its inputs
(HANDOFF §4.6), so a live Process over the same data reuses it and calls no
model; ``--cold`` leaves it out and Process computes and writes everything.

The pair is named in the store's partitions (sessions/_partitions.json,
{"Demo": [<report>, <report>_live]}), which a front end may list apart.

Safety: only a session that carries this tool's marker (demo_copy.json) is ever
deleted, and the finished report is only read.  A server that is running holds
some of a session in memory; reset a copy through the server
(POST /api/v2/demo/<report>/reset on the interface's branch), or restart it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from common import paths
from common.clock import now_iso
from common.dtxsid import validate_dtxsid

MARKER = "demo_copy.json"
PARTITIONS_FILE = "_partitions.json"
STUDIES_FILE = "studies.json"

# Steps 1–4: the files and what the check made of them.
CHECKED = ("files", "_originals", "_fingerprints.json", "validation_report.json",
           "precedence.json")
# Steps 6–7: what people state, and the pins.
DECLARED = ("identity.json", "study_design.json", "metadata_approved.json",
            "front_matter.json", "method_profile.json", "knowledge_base.json", "meta.json",
            "bmd_reviews.json", "deposit.json", "efdr.json", "supplemental")
RESULTS_CACHE = "_cache_*.json"


class DemoCopyError(RuntimeError):
    """The act is refused; the message says why."""


def _root() -> Path:
    return paths.SESSIONS_DIR


def live_id(report: str, suffix: str = "live") -> str:
    return validate_dtxsid(f"{report}_{suffix}")


def _members(report: str) -> dict[str, str]:
    """{key: session id} of the studies a report is composed of ({} for a
    report of one study)."""
    listing = _root() / report / STUDIES_FILE
    if not listing.is_file():
        return {}
    stated = json.loads(listing.read_text(encoding="utf-8"))
    return {str(k): validate_dtxsid(v) for k, v in stated.items()}


def plan(report: str, suffix: str = "live") -> dict:
    """What a copy of ``report`` consists of: {"report": (source, copy),
    "members": {key: (source, copy)}}."""
    validate_dtxsid(report)
    if not (_root() / report).is_dir():
        raise DemoCopyError(f"there is no session {report}")
    copy = live_id(report, suffix)
    return {"report": (report, copy),
            "members": {key: (source, validate_dtxsid(f"{copy}_{key}"))
                        for key, source in _members(report).items()}}


def _pairs(p: dict) -> list[tuple[str, str]]:
    return [p["report"], *p["members"].values()]


def _copy_entry(source: Path, target: Path, name: str) -> bool:
    src = source / name
    if src.is_dir():
        shutil.copytree(src, target / name)
    elif src.is_file():
        shutil.copy2(src, target / name)
    else:
        return False
    return True


def _is_copy(session: Path, of: str | None = None) -> bool:
    try:
        marker = json.loads((session / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(marker, dict) and (of is None or marker.get("of") == of)


def _build(source_id: str, copy_id: str, *, report: str, members: dict[str, str] | None,
           warm: bool) -> dict:
    source, target = _root() / source_id, _root() / copy_id
    if not source.is_dir():
        raise DemoCopyError(f"there is no session {source_id} to copy")
    target.mkdir()
    copied = [name for name in (*CHECKED, *DECLARED) if _copy_entry(source, target, name)]
    if members is not None:  # the report names its own copies of the studies
        (target / STUDIES_FILE).write_text(json.dumps(members, indent=2), encoding="utf-8")
        copied.append(STUDIES_FILE)
    # A study's own report definition is found by its id, which the copy does
    # not have: the copy is fixed to the definition its source renders from.
    from document_model.definition_pin import pin_like
    pin = pin_like(copy_id, source_id, by="demo_copy")
    copied.append(f"report definition {pin['name']} (fixed)")
    cache = 0
    if warm:
        for file in sorted(source.glob(RESULTS_CACHE)):
            shutil.copy2(file, target / file.name)
            cache += 1
    marker = {"of": report, "source": source_id, "made_at": now_iso(),
              "results_cache": "copied" if warm else "none"}
    (target / MARKER).write_text(json.dumps(marker, indent=2), encoding="utf-8")
    return {"id": copy_id, "source": source_id, "copied": copied, "cache_files": cache}


def _read_partitions() -> dict:
    path = _root() / PARTITIONS_FILE
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DemoCopyError(f"{path} is not a mapping of partition name to sessions")
    return data


def _write_partitions(data: dict) -> None:
    path = _root() / PARTITIONS_FILE
    if data:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    elif path.exists():
        path.unlink()


def _name_in_partition(partition: str, ids: list[str]) -> None:
    data = _read_partitions()
    listed = [i for i in data.get(partition, []) if isinstance(i, str)]
    data[partition] = listed + [i for i in ids if i not in listed]
    _write_partitions(data)


def _drop_from_partitions(ids: list[str]) -> None:
    data = _read_partitions()
    for name in list(data):
        kept = [i for i in data[name] if i not in ids]
        # A partition left with the finished report alone no longer sets a
        # pair apart.
        if len(kept) < 2:
            del data[name]
        else:
            data[name] = kept
    _write_partitions(data)


def make(report: str, *, suffix: str = "live", partition: str = "Demo",
         warm: bool = False) -> dict:
    """Build the live copy of ``report`` and name the pair in ``partition``.
    Refused when any session of the copy already exists."""
    p = plan(report, suffix)
    if _is_copy(_root() / report):
        raise DemoCopyError(f"{report} is itself a live copy; copy the report it was made of")
    existing = [copy for _, copy in _pairs(p) if (_root() / copy).exists()]
    if existing:
        raise DemoCopyError(f"a copy already exists ({', '.join(existing)}); "
                            "reset it, or remove it first")
    members = {key: copy for key, (_, copy) in p["members"].items()}
    built = [_build(*p["report"], report=report, members=members or None, warm=warm)]
    built += [_build(source, copy, report=report, members=None, warm=warm)
              for source, copy in p["members"].values()]
    _name_in_partition(partition, [report, p["report"][1]])
    return {"report": report, "copy": p["report"][1], "sessions": built,
            "partition": partition, "results_cache": "copied" if warm else "none"}


def _existing_copies(report: str, suffix: str) -> list[str]:
    """The copy's sessions that exist, each checked to be this tool's copy of
    ``report`` — the only folders this tool deletes."""
    p = plan(report, suffix)
    out = []
    for _, copy in _pairs(p):
        folder = _root() / copy
        if not folder.exists():
            continue
        if not _is_copy(folder, of=report):
            raise DemoCopyError(f"{copy} exists and is not a live copy of {report} "
                                f"(no {MARKER}); it is left alone")
        out.append(copy)
    return out


def remove(report: str, *, suffix: str = "live") -> dict:
    """Delete the live copy of ``report`` and take it out of its partition."""
    copies = _existing_copies(report, suffix)
    for copy in copies:
        shutil.rmtree(_root() / copy)
    _drop_from_partitions([live_id(report, suffix)])
    return {"report": report, "removed": copies}


def reset(report: str, *, suffix: str = "live", partition: str = "Demo",
          warm: bool = True) -> dict:
    """Put the live copy back to its start state: the copy is deleted and built
    again from the finished report.  ``warm``: the results cache the copy's
    own runs wrote is carried over (some units' keys name the session, so only
    the copy's own cache serves them), on top of the finished studies'."""
    import tempfile

    copies = _existing_copies(report, suffix)
    if not copies:
        raise DemoCopyError(f"{report} has no live copy to reset; make one first")
    with tempfile.TemporaryDirectory(dir=_root(), prefix="_demo_reset_") as stash:
        kept: dict[str, list[Path]] = {}
        for copy in copies:
            if warm:
                hold = Path(stash) / copy
                hold.mkdir()
                kept[copy] = [Path(shutil.move(str(f), str(hold / f.name)))
                              for f in sorted((_root() / copy).glob(RESULTS_CACHE))]
            shutil.rmtree(_root() / copy)
        out = make(report, suffix=suffix, partition=partition, warm=warm)
        for copy, files in kept.items():
            for f in files:
                shutil.move(str(f), str(_root() / copy / f.name))
    for session in out["sessions"]:
        session["cache_files"] = len(list((_root() / session["id"]).glob(RESULTS_CACHE)))
    return out


def status(report: str, *, suffix: str = "live") -> dict:
    """The copy's sessions, and for each whether it exists and what it holds
    beyond its start state."""
    p = plan(report, suffix)
    from document_model.definition_pin import PIN_FILE, SNAPSHOT_FILE
    start = {*CHECKED, *DECLARED, MARKER, STUDIES_FILE, PIN_FILE, SNAPSHOT_FILE}
    sessions = []
    for source, copy in _pairs(p):
        folder = _root() / copy
        exists = folder.is_dir()
        beyond = sorted(e.name for e in folder.iterdir()
                        if e.name not in start and not e.name.startswith("_cache_")) if exists else []
        sessions.append({"id": copy, "source": source, "exists": exists,
                         "is_copy": exists and _is_copy(folder, of=report),
                         "beyond_start": beyond,
                         "cache_files": len(list(folder.glob(RESULTS_CACHE))) if exists else 0})
    partitions = {name: ids for name, ids in _read_partitions().items()
                  if p["report"][1] in ids or report in ids}
    return {"report": report, "copy": p["report"][1], "sessions": sessions,
            "partitions": partitions}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("act", choices=("make", "reset", "remove", "status"))
    ap.add_argument("report", help="the finished report's session id")
    ap.add_argument("--suffix", default="live")
    ap.add_argument("--partition", default="Demo")
    ap.add_argument("--warm", action="store_true",
                    help="make: also copy the finished studies' results cache")
    ap.add_argument("--cold", action="store_true",
                    help="reset: leave the results cache out")
    a = ap.parse_args(argv)
    try:
        if a.act == "make":
            out = make(a.report, suffix=a.suffix, partition=a.partition, warm=a.warm)
        elif a.act == "reset":
            out = reset(a.report, suffix=a.suffix, partition=a.partition, warm=not a.cold)
        elif a.act == "remove":
            out = remove(a.report, suffix=a.suffix)
        else:
            out = status(a.report, suffix=a.suffix)
    except DemoCopyError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
