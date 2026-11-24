"""
pipeline.intake — checking files before they join a study.

A file that should not be in a study is cheapest to refuse before it is
written, and a file that would replace one already there must not be written
until a person says so.  This module decides, for a batch of files waiting in
a scratch directory, what each one is and what would happen to it:

    plan(session_dir, batch_dir, answers) -> list[Row]

Nothing here writes into the study.  The caller moves in only the rows whose
verdict says to, and only once every row that needs an answer has one.

The rules in order, each a verdict on one row rather than a refusal of the
whole batch, except where noted:

  * the name is usable, the file is not empty, its ending is one a study's
    data comes in, and it is not a file the application writes itself;
  * the content matches the ending: a BMDExpress project begins with Java's
    serialization header, a workbook or a zip with the zip header, a table is
    text;
  * a zip opens, holds no zip, and has no two entries of one name;
  * a units file is a list of measurement to unit, and has a table;
  * same name and same content as a file in the study: already there;
  * same name, other content: replaces one, and needs an answer;
  * same content under another name: a copy, and needs an answer;
  * a one-row-per-animal table with no units file: needs an answer.

Only public things are read: a file's first bytes, its size and its name.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: What a study's data comes in (no size limit).
ACCEPTED = (".bm2", ".csv", ".txt", ".xlsx", ".zip", ".units.json")

#: Files the application writes beside a table; never brought in.
WRITTEN_BY_THE_APPLICATION = (".sidecar.json",)

_UNITS = ".units.json"
_MAX_NAME = 200
#: A zip that would unpack to more than this is refused rather than unpacked.
_MAX_UNPACKED = 4 * 1024 * 1024 * 1024

#: The first bytes each kind of file begins with.
_BM2_HEADER = b"\xac\xed\x00\x05"      # a Java serialized stream
_ZIP_HEADER = b"PK\x03\x04"


@dataclass
class Row:
    """One file of a batch, and what would become of it."""
    name: str
    size: int
    content_hash: str
    type: str
    verdict: str                  # add|units|replace|unchanged|copy|units_missing|refused|left_out
    say: str
    code: str | None = None
    needs_answer: str | None = None   # replace|copy|without_units
    from_zip: str | None = None
    pairs_with: str | None = None
    replaces: dict | None = None
    copy_of: dict | None = None
    path: Path | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        out = {k: v for k, v in self.__dict__.items() if k != "path"}
        return out


# ---------------------------------------------------------------------------
# Reading a file's name and first bytes
# ---------------------------------------------------------------------------

def ending_of(name: str) -> str:
    """The ending a file is taken by, with ``.units.json`` as one ending."""
    low = name.lower()
    if low.endswith(_UNITS):
        return _UNITS
    return Path(low).suffix


def stem_of(name: str) -> str:
    """The name a units file shares with its table."""
    if name.lower().endswith(_UNITS):
        return name[: -len(_UNITS)]
    return Path(name).stem


def name_problem(name: str) -> str | None:
    """Why this file name cannot be used, or None."""
    if not name or name != os.path.basename(name):
        return "it is a path, not a file name"
    if name.startswith("."):
        return "it starts with a dot"
    if len(name) > _MAX_NAME:
        return f"it is longer than {_MAX_NAME} characters"
    if any(ord(c) < 32 for c in name):
        return "it holds a character that cannot be printed"
    return None


def hash_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()[:16]


def looks_like(path: Path, ending: str) -> bool:
    """Whether a file's first bytes match the ending it carries."""
    try:
        head = path.open("rb").read(4096)
    except OSError:
        return False
    if ending == ".bm2":
        return head.startswith(_BM2_HEADER)
    if ending in (".xlsx", ".zip"):
        return head.startswith(_ZIP_HEADER)
    if ending in (".csv", ".txt", _UNITS):
        if b"\x00" in head:
            return False
        try:
            head.decode("utf-8")
        except UnicodeDecodeError:
            return head.decode("latin-1", errors="strict") is not None
        return True
    return True


def looks_long_format(path: Path) -> bool:
    """Whether a table has one row per animal, from its header line alone."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            header = f.readline().lower()
    except OSError:
        return False
    columns = [c.strip().strip('"') for c in header.replace("\t", ",").split(",")]
    return "animal id" in columns or "animal_id" in columns


def units_problem(path: Path, table_columns: set[str] | None = None) -> str | None:
    """Why a units file cannot be read as a list of measurement to unit."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "it is not readable as JSON"
    if not isinstance(data, dict) or not data:
        return "it is not a list of measurement to unit"
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in data.items()):
        return "it is not a list of measurement to unit"
    return None


# ---------------------------------------------------------------------------
# What is in the study already
# ---------------------------------------------------------------------------

def _in_study(session_dir: Path) -> dict[str, dict]:
    """Each file of the study by name, with its size and content."""
    out: dict[str, dict] = {}
    files = Path(session_dir) / "files"
    if not files.is_dir():
        return out
    for f in sorted(files.iterdir()):
        if not f.is_file():
            continue
        try:
            out[f.name] = {"size": f.stat().st_size, "hash": hash_of(f)}
        except OSError:
            continue
    return out


# ---------------------------------------------------------------------------
# Unpacking a zip
# ---------------------------------------------------------------------------

def _unpack(path: Path, into: Path) -> tuple[list[tuple[str, Path, str]], str | None]:
    """Every data file of a zip, unpacked one by one. Returns the entries and,
    when the zip cannot be taken, why."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return [], "zip_invalid"
    with archive:
        entries = [e for e in archive.infolist() if not e.is_dir()]
        if sum(e.file_size for e in entries) > _MAX_UNPACKED:
            return [], "zip_invalid"
        by_name: dict[str, str] = {}
        inner_zips = [e for e in entries if os.path.basename(e.filename).lower().endswith(".zip")]
        data = [e for e in entries
                if ending_of(os.path.basename(e.filename)) in ACCEPTED
                and not os.path.basename(e.filename).lower().endswith(".zip")]
        if inner_zips and not data:
            # A wrapper around another package, rather than a package.
            return [], "zip_nested"
        for entry in entries:
            name = os.path.basename(entry.filename)
            if name.lower().endswith(".zip") or ending_of(name) not in ACCEPTED:
                continue
            if name in by_name and by_name[name] != entry.filename:
                return [], "zip_name_clash"
            by_name[name] = entry.filename

        out: list[tuple[str, Path, str]] = []
        for entry in entries:
            name = os.path.basename(entry.filename)
            if name.lower().endswith(".zip") or name_problem(name):
                continue
            if ending_of(name) not in ACCEPTED:
                # Kept as a row so the person sees it was left out, not lost.
                out.append((name, None, os.path.dirname(entry.filename)))
                continue
            target = into / name
            with archive.open(entry) as source, target.open("wb") as sink:
                while block := source.read(1024 * 1024):
                    sink.write(block)
            out.append((name, target, os.path.dirname(entry.filename)))
        # The supplementary archives a package carries are not study data.
        for entry in inner_zips:
            out.append((os.path.basename(entry.filename), None,
                        os.path.dirname(entry.filename)))
    return out, None


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

def plan(session_dir, batch_dir, answers: dict | None = None) -> list[Row]:
    """What would become of each file waiting in ``batch_dir``.

    ``answers`` carries the names a person has answered for:
    ``{"replace": [...], "copy_anyway": [...], "without_units": [...]}``.
    A row that needs an answer and has none keeps ``needs_answer`` set; the
    caller refuses the batch rather than writing it.
    """
    session_dir, batch_dir = Path(session_dir), Path(batch_dir)
    answered = {k: set(v or []) for k, v in (answers or {}).items()}
    already = _in_study(session_dir)
    by_hash = {f["hash"]: name for name, f in already.items()}

    # A zip stands for the files inside it.
    waiting: list[tuple[str, Path, str | None]] = []
    rows: list[Row] = []
    for f in sorted(batch_dir.iterdir()):
        if not f.is_file():
            continue
        if ending_of(f.name) == ".zip" and looks_like(f, ".zip"):
            unpacked_dir = batch_dir / f"_unpacked_{f.stem}"
            unpacked_dir.mkdir(exist_ok=True)
            entries, why = _unpack(f, unpacked_dir)
            if why:
                rows.append(_refused(f, why, _ZIP_SAY[why].format(name=f.name)))
                continue
            waiting += [(name, path, folder or f.name) for name, path, folder in entries]
            continue
        waiting.append((f.name, f, None))

    names = {name for name, path, _ in waiting if path is not None}
    seen: dict[str, str] = {}

    for name, path, from_zip in waiting:
        if path is None:
            kind = ("a zip of supplementary files" if name.lower().endswith(".zip")
                    else f"a {ending_of(name) or 'file with no ending'}")
            rows.append(Row(name=name, size=0, content_hash="",
                            type=ending_of(name).lstrip("."), verdict="left_out",
                            say=f"Left out: {kind}, not study data.", from_zip=from_zip))
            continue
        row = _row_for(name, path, from_zip, already, by_hash, names, seen, session_dir)
        if row.verdict not in ("refused", "left_out", "unchanged"):
            seen.setdefault(row.content_hash, name)
        # A row that needs an answer, and has one, is an ordinary add.
        if row.needs_answer and name in answered.get(_ANSWER_KEY[row.needs_answer], set()):
            row.needs_answer = None
            if row.verdict in ("replace", "copy", "units_missing"):
                row.say += " Answered."
        rows.append(row)
    return rows


_ANSWER_KEY = {"replace": "replace", "copy": "copy_anyway", "without_units": "without_units"}

_ZIP_SAY = {
    "zip_invalid": "{name} cannot be opened; it may be damaged or only partly sent.",
    "zip_nested": "{name} holds another zip. Unpack the inner one and bring its files in.",
    "zip_name_clash": "{name} holds two files of the same name in different folders. "
                      "Only one could be kept, and the application cannot know which. "
                      "Unpack it and choose.",
}


def _refused(path: Path, code: str, say: str, from_zip: str | None = None) -> Row:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return Row(name=path.name, size=size, content_hash="", type=ending_of(path.name).lstrip("."),
               verdict="refused", say=say, code=code, from_zip=from_zip, path=path)


def _row_for(name: str, path: Path, from_zip: str | None, already: dict,
             by_hash: dict, names: set[str], seen: dict, session_dir: Path) -> Row:
    ending = ending_of(name)
    size = path.stat().st_size

    why = name_problem(name)
    if why:
        return _refused(path, "name_invalid", f"{name} cannot be used as a file name: {why}.", from_zip)
    if size == 0:
        return _refused(path, "empty_file", f"{name} is empty.", from_zip)
    if name.lower().endswith(WRITTEN_BY_THE_APPLICATION):
        return _refused(path, "sidecar_refused",
                        f"{name} is a file the application writes itself. Bring in the "
                        f"table it belongs to instead.", from_zip)
    if ending not in ACCEPTED:
        kind = ending or "file with no ending"
        return Row(name=name, size=size, content_hash="", type=ending.lstrip("."),
                   verdict="left_out" if from_zip else "refused",
                   code=None if from_zip else "file_type_refused",
                   say=(f"Left out: a {kind} is not a data file."
                        if from_zip else
                        f"A {kind} is not a data file. A study's data comes as .bm2, "
                        f".csv, .txt, .xlsx, or a zip of these."),
                   from_zip=from_zip, path=path)
    if not looks_like(path, ending):
        return _refused(path, "content_mismatch",
                        f"{name} is named {ending} but its contents are not. "
                        f"Check the file, or rename it to what it is.", from_zip)

    content_hash = hash_of(path)
    row = Row(name=name, size=size, content_hash=content_hash, type=ending.lstrip("."),
              verdict="add", say="Will be added.", from_zip=from_zip, path=path)

    # A units file belongs to a table.
    if ending == _UNITS:
        why = units_problem(path)
        if why:
            return _refused(path, "units_invalid",
                            f"{name} is not a list of measurement to unit: {why}.", from_zip)
        stem = stem_of(name)
        table = next((n for n in names if n != name and stem_of(n) == stem), None)
        if table is None:
            table = next((n for n in already if stem_of(n) == stem), None)
        if table is None:
            return _refused(path, "units_without_table",
                            f"{name} has no table: there is no {stem}.csv in the study "
                            f"or in this batch. Bring them in together.", from_zip)
        row.verdict, row.pairs_with = "units", table
        row.say = f"The units of {table}."
        return row

    # Already in the study, or replacing something, or a copy of something.
    there = already.get(name)
    if there and there["hash"] == content_hash:
        row.verdict, row.say = "unchanged", "Already in the study, unchanged. Not brought in again."
        return row
    if there:
        row.verdict, row.needs_answer = "replace", "replace"
        row.replaces = {"name": name, "size": there["size"], "content_hash": there["hash"]}
        row.say = (f"Replaces {name}, already in the study ({there['size']} bytes; this one "
                   f"{size} bytes, different contents). The old one is kept among the "
                   f"removed files.")
        return row
    twin = by_hash.get(content_hash) or seen.get(content_hash)
    if twin and twin != name:
        row.verdict, row.needs_answer = "copy", "copy"
        row.copy_of = {"name": twin, "where": "study" if content_hash in by_hash else "batch"}
        row.say = (f"The same contents as {twin}, under another name. Both would be "
                   f"combined, so the data would count twice.")
        return row

    # A one-row-per-animal table says what its measurements are measured in.
    if ending in (".csv", ".txt") and looks_long_format(path):
        stem = stem_of(name)
        has_units = (any(stem_of(n) == stem and n.lower().endswith(_UNITS) for n in names)
                     or any(stem_of(n) == stem and n.lower().endswith(_UNITS) for n in already))
        if not has_units:
            row.verdict, row.needs_answer = "units_missing", "without_units"
            row.say = (f"{name} has one row per animal and came without a units file "
                       f"({stem}{_UNITS}). Its tables will print [units pending] for "
                       f"every measurement.")
    return row


def counts(rows: list[Row]) -> dict[str, int]:
    """How many rows would be added, and how many wait on an answer."""
    adding = [r for r in rows if r.verdict in ("add", "units", "replace", "copy", "units_missing")
              and not r.needs_answer]
    return {"add": len(adding),
            "unchanged": sum(1 for r in rows if r.verdict == "unchanged"),
            "refused": sum(1 for r in rows if r.verdict == "refused"),
            "left_out": sum(1 for r in rows if r.verdict == "left_out"),
            "needs_answer": sum(1 for r in rows if r.needs_answer)}
