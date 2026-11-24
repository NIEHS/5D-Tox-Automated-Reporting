"""
pipeline.classifications — what a person says a study file is, kept.

The file check works out each file's platform and its kind of data from the
file's name (``bmdx_pipe.file_integrator.detect_platform_and_type``).  When it
gets one wrong, a person corrects it.  That correction is a statement about the
study's data, so it is kept with the study and applied on every check — until
this module, a correction lived only in the fingerprints the check rewrote, and
the next check silently put the detected value back.

The statements are in ``sessions/<id>/classifications.json``, keyed by the file
name as the study holds it:

    {"hormones_truth_male.txt": {
        "platform": "Hormones", "data_type": "tox_study",
        "by": "person", "at": "2026-11-24T10:17:03+00:00",
        "seen": {"size": 6387, "modified_at": "2026-11-20T15:44:19+00:00"}}}

``seen`` is the file as it was when the statement was made.  A file whose size
or time has changed since is reported as needing a look again, rather than
carrying a statement that may no longer describe it.  It is a cheap comparison,
not a cryptographic one: reading every byte of a 250 MB project to draw a page
is not worth it, and the statement is a person's word about a file, not a seal
on its contents.

A value outside the vocabularies, or a pair the kind of file cannot have (a
workbook of gene expression, a BMDExpress project of "the study's own
measurements"), is refused here rather than written and found later.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

FILE_NAME = "classifications.json"

#: The kinds of data a person can state, as the interface words them.  They are
#: the ``dataType`` vocabulary; the kinds the application writes for itself
#: (a sample sheet, removal reasons, the values left out) are not stated.
DATA_TYPES = {
    "tox_study": "the study's own measurements",
    "inferred": "gap-filled for benchmark dose modeling",
    "gene_expression": "gene expression",
}

#: Which kinds of data each kind of file can hold.
BY_KIND: dict[str, tuple[str, ...]] = {
    "workbook": ("tox_study",),
    "table": ("tox_study", "inferred"),
    "bm2": ("inferred", "gene_expression"),
}


def kind_of(file_type: str) -> str:
    """The kind of file a fingerprint's ``file_type`` is."""
    if file_type == "xlsx":
        return "workbook"
    if file_type == "bm2":
        return "bm2"
    return "table"


def platforms() -> list[str]:
    """The platforms a person can state for apical data."""
    from workflow.phases import APICAL_PLATFORMS
    return sorted(set(APICAL_PLATFORMS) | {"Clinical", "Tissue Concentration"})


def problem(platform: str | None, data_type: str, kind: str) -> str | None:
    """Why this statement cannot be made, or None when it can.

    The text is the backend's own; the interface shows it as the refusal's
    plain words (``classification_not_allowed``).
    """
    if data_type not in DATA_TYPES:
        return f"{data_type!r} is not a kind of data this application knows."
    allowed = BY_KIND.get(kind)
    if allowed is None:
        return f"{kind!r} is not a kind of file this application knows."
    if data_type not in allowed:
        says = ", or ".join(DATA_TYPES[d] for d in allowed)
        a_kind = {"workbook": "A study workbook", "table": "A study table",
                  "bm2": "A BMDExpress project"}[kind]
        return f"{a_kind} holds {says} — not {DATA_TYPES[data_type]}."
    if data_type == "gene_expression":
        if platform:
            return "Gene expression has no assay of its own; leave the assay empty."
        return None
    if not platform:
        return f"A file of {DATA_TYPES[data_type]} needs the assay it measures."
    if platform not in platforms():
        return f"{platform!r} is not an assay this application knows."
    return None


# ---------------------------------------------------------------------------
# Reading and writing
# ---------------------------------------------------------------------------

def path_of(session_dir) -> Path:
    return Path(session_dir) / FILE_NAME


def read(session_dir) -> dict[str, dict]:
    """Every statement of this study, by file name; {} when there is none."""
    try:
        data = json.loads(path_of(session_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(session_dir, statements: dict[str, dict]) -> None:
    path_of(session_dir).write_text(
        json.dumps(statements, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seen_of(session_dir, name: str) -> dict | None:
    """The file as it is now (its size and time), or None when it is not there."""
    f = Path(session_dir) / "files" / name
    try:
        stat = f.stat()
    except OSError:
        return None
    return {"size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()}


def changed_since(session_dir, name: str, statement: dict) -> bool:
    """Whether the file differs from what it was when the statement was made."""
    was = statement.get("seen")
    now = seen_of(session_dir, name)
    if not was or not now:
        return False
    return was.get("size") != now.get("size") or was.get("modified_at") != now.get("modified_at")


def state(session_dir, name: str, platform: str | None, data_type: str,
          kind: str, by: str = "person") -> dict:
    """Keep what a person says this file is.  Raises ValueError when the
    statement cannot be made (the text is for the person to read)."""
    why = problem(platform, data_type, kind)
    if why:
        raise ValueError(why)
    statements = read(session_dir)
    statements[name] = {
        "platform": platform or None,
        "data_type": data_type,
        "by": by,
        "at": datetime.now(tz=timezone.utc).isoformat(),
        "seen": seen_of(session_dir, name),
    }
    _write(session_dir, statements)
    logger.info("%s stated as %s/%s", name, platform, data_type)
    return statements[name]


def clear(session_dir, name: str) -> bool:
    """Drop the statement about this file.  False when there was none."""
    statements = read(session_dir)
    if name not in statements:
        return False
    del statements[name]
    _write(session_dir, statements)
    logger.info("the statement about %s was dropped", name)
    return True


# ---------------------------------------------------------------------------
# Applying them to what the check found
# ---------------------------------------------------------------------------

def apply(session_dir, fingerprints: dict) -> int:
    """Put each statement over what was detected, in a pool of fingerprints
    keyed by file id.  Returns how many files a statement spoke for.

    Called wherever the files are fingerprinted, so a check never reverts a
    person's correction.  A statement about a file that is no longer in the
    study is left alone: it applies again if the file comes back.
    """
    statements = read(session_dir)
    if not statements:
        return 0
    spoken = 0
    for fp in fingerprints.values():
        name = fp.filename if hasattr(fp, "filename") else fp.get("filename", "")
        said = statements.get(name)
        if not said:
            continue
        platform, data_type = said.get("platform"), said.get("data_type")
        if hasattr(fp, "filename"):
            fp.platform, fp.data_type = platform, data_type
        else:
            fp["platform"], fp["data_type"] = platform, data_type
        spoken += 1
    return spoken
