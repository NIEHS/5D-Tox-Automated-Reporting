"""
excluded_values — the values a study's package says were left out of the analysis.

NIEHS reports leave single values out of the apical analysis: "Values from
animals suspected of illness from causes other than experimental exposure and
values that the laboratory indicated as inadequate because of measurement
problems were eliminated from the analysis" (NIEHS-12, Statistical Methods).
Which values is a fact about the study, not a result of a rule: the outlier
test only names the values NIEHS staff then examined, and no significance
level of that test reproduces what the books left out.  So the fact is data
(ADR-0037): the package carries a file that names each such value and why,
and the conversion leaves the named values out.

The file is a CSV with a header row:

    Animal ID, Endpoint, Observation Day, Reason, Note

``Endpoint`` is the column label of the study workbook's Data sheet
("Kidney-Right", "Bile salts/acids", "Body Weight").  ``Observation Day`` may
be empty (the value on every day is meant) and is needed for an endpoint
measured on several days.  ``Reason`` is one of REASONS.  ``Note`` says where
the fact comes from; a reason that requires one says so in NOTE_REQUIRED.

What was left out is recorded where the per-animal values are: the
observation in the platform's sidecar keeps no ``value`` and carries

    "excluded": {"value": "0.06", "reason": ..., "note": ..., "source": <file>}

so every reader of a sidecar treats it as a missing value, and the readers
that say why (table footnotes, the Methods, the file check) read the mark
(excluded_marks).
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

DATA_TYPE = "excluded_values"

# The platforms whose values the file may name: the apical measurements the
# reports test and model.  Internal dose values have the method's own outlier
# rule (internal_dose.outliers); clinical observations are findings, not values.
PLATFORMS = frozenset({"Body Weight", "Organ Weight", "Clinical Chemistry",
                       "Hematology", "Hormones"})

# Reason (as the file writes it) -> what it says, as the end of the sentence
# "The value was left out because ...".
REASONS: dict[str, str] = {
    "measurement problem":
        "the laboratory indicated the measurement as inadequate",
    "unrelated illness":
        "the animal was suspected of illness from causes other than exposure",
    "as published":
        "the published report left it out",
}
# Reasons whose rows must say where the fact comes from.
NOTE_REQUIRED = frozenset({"as published"})

# How a table's note ends for each reason: "One value was excluded ...".
# "as an outlier" is the books' own word for a value they left out (NIEHS-12
# Table 3: "n = 9. One value was excluded as an outlier.").
NOTE_PHRASES: dict[str, str] = {
    "measurement problem":
        "because the laboratory indicated the measurement as inadequate",
    "unrelated illness":
        "because the animal was suspected of illness from causes other than exposure",
    "as published": "as an outlier",
}

REQUIRED_COLUMNS = ("animal id", "endpoint", "reason")
_COLUMNS = {"animal id": "animal_id", "endpoint": "endpoint",
            "observation day": "day", "reason": "reason", "note": "note"}


@dataclass(frozen=True)
class ExcludedValue:
    """One value the package says was left out."""

    animal_id: str
    endpoint: str
    day: str          # "" when the file names no day
    reason: str       # a key of REASONS
    note: str
    source: str       # the file's name
    row: int          # its row in the file, the header being row 1

    def describe(self) -> str:
        day = f", {self.day}" if self.day else ""
        return f"animal {self.animal_id}, {self.endpoint}{day}"

    def key(self) -> str:
        """The row as one line, for a file's fingerprint: what the file says."""
        return " | ".join((self.animal_id, self.endpoint, self.day, self.reason))


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _day_number(day) -> int | None:
    m = re.search(r"-?\d+", str(day or ""))
    return int(m.group()) if m else None


def same_day(a, b) -> bool:
    """"SD5", "SD 5" and "5" name one day."""
    na, nb = _day_number(a), _day_number(b)
    if na is not None and nb is not None:
        return na == nb
    return _norm(a) == _norm(b)


def is_excluded_values_header(cells) -> bool:
    """Whether a header row is this file's: the required columns, and no dose
    column (a long-format data file has "Concentration")."""
    labels = {_norm(c) for c in cells}
    return all(c in labels for c in REQUIRED_COLUMNS) and "concentration" not in labels


def _rows(path) -> list[list[str]]:
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        lines = [line for line in f if not line.startswith("#")]
    if not lines:
        return []
    sep = "\t" if "\t" in lines[0] and "," not in lines[0] else ","
    return [r for r in csv.reader(lines, delimiter=sep)]


def is_excluded_values_file(path) -> bool:
    try:
        rows = _rows(path)
    except OSError:
        return False
    return bool(rows) and is_excluded_values_header(rows[0])


def read_excluded_values(path) -> tuple[list[ExcludedValue], list[str]]:
    """The values a file names, and what is wrong with the file.

    A row that is wrong (no animal, no endpoint, a reason that is not one of
    REASONS, a missing note where one is required, a value named twice) is
    not among the values returned; each is described in the second list, by
    row.  A file that is not an excluded-values file returns ([], [])."""
    rows = _rows(path)
    if not rows or not is_excluded_values_header(rows[0]):
        return [], []
    source = Path(path).name
    index = {_COLUMNS[_norm(c)]: i for i, c in enumerate(rows[0]) if _norm(c) in _COLUMNS}

    def cell(row, name):
        i = index.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    values: list[ExcludedValue] = []
    problems: list[str] = []
    seen: dict[tuple, int] = {}
    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        animal, endpoint = cell(row, "animal_id"), cell(row, "endpoint")
        reason, note = _norm(cell(row, "reason")), cell(row, "note")
        wrong = []
        if not animal:
            wrong.append("names no animal")
        if not endpoint:
            wrong.append("names no endpoint")
        if reason not in REASONS:
            wrong.append(f"its reason {cell(row, 'reason')!r} is not one of: "
                         + ", ".join(REASONS))
        elif reason in NOTE_REQUIRED and not note:
            wrong.append(f"the reason {reason!r} needs a note saying where the "
                         "report states it")
        ident = (animal, _norm(endpoint), _day_number(cell(row, "day")) or _norm(cell(row, "day")))
        if not wrong and ident in seen:
            wrong.append(f"names the same value as row {seen[ident]}")
        if wrong:
            problems.append(f"row {n}: " + "; ".join(wrong))
            continue
        seen[ident] = n
        values.append(ExcludedValue(animal, endpoint, cell(row, "day"), reason, note, source, n))
    return values, problems


def pool_excluded_values(files_dir) -> list[ExcludedValue]:
    """Every value the excluded-values files of a pool name (the rows that
    read; the file check reports the others)."""
    out: list[ExcludedValue] = []
    for f in sorted(Path(files_dir).glob("*.csv")):
        if is_excluded_values_file(f):
            out.extend(read_excluded_values(f)[0])
    return out


def match(excluded, animal_id: str, endpoint: str, day: str) -> ExcludedValue | None:
    """The entry that names this observation, if any."""
    for ev in excluded or ():
        if (ev.animal_id == animal_id and _norm(ev.endpoint) == _norm(endpoint)
                and (not ev.day or same_day(ev.day, day))):
            return ev
    return None


def mark(value: str, ev: ExcludedValue) -> dict:
    """The mark an observation left out carries in its sidecar."""
    return {"value": value, "reason": ev.reason, "note": ev.note, "source": ev.source}


def excluded_marks(sidecar: dict) -> list[dict]:
    """The observations a sidecar marks as left out: platform, sex, animal_id,
    dose, selection, endpoint, day, and the mark (value, reason, note, source)."""
    out = []
    for aid, rec in (sidecar or {}).get("animals", {}).items():
        for obs in rec.get("observations", []):
            ex = obs.get("excluded")
            if isinstance(ex, dict):
                out.append({"platform": sidecar.get("platform"), "sex": sidecar.get("sex"),
                            "animal_id": aid, "dose": rec.get("dose"),
                            "selection": rec.get("selection"),
                            "endpoint": obs.get("endpoint"), "day": obs.get("day"), **ex})
    return out


def session_excluded_marks(files_dir) -> list[dict]:
    """excluded_marks of every sidecar in a pool's files."""
    out: list[dict] = []
    for sc in sorted(Path(files_dir).glob("*.sidecar.json")):
        try:
            out.extend(excluded_marks(json.loads(sc.read_text())))
        except (OSError, ValueError):
            continue
    return out


def is_applied(ev: ExcludedValue, marks: list[dict]) -> bool:
    """Whether a named value is among the marks the sidecars carry."""
    return any(m["animal_id"] == ev.animal_id and _norm(m["endpoint"]) == _norm(ev.endpoint)
               and (not ev.day or same_day(ev.day, m.get("day"))) and m.get("source") == ev.source
               for m in marks)
