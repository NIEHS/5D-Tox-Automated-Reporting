"""
pipeline.excluded_values — the file check's pass over the package's excluded values.

A study's package may name the values that were left out of the analysis
(bmdx_pipe.excluded_values, ADR-0037).  The conversion of the study workbooks
leaves the named values out and marks them in the sidecars.  This pass makes
the file check refuse a file that cannot be followed exactly: a row that does
not read, and a row that names a value the derived files do not hold.  A row
is never applied in part or by a guess.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from bmdx_pipe.excluded_values import (
    DATA_TYPE,
    PLATFORMS,
    REASONS,
    is_applied,
    read_excluded_values,
    session_excluded_marks,
)
from bmdx_pipe.file_integrator import ValidationIssue

PLATFORM = "excluded values"


def _fp_get(fp, key):
    return fp.get(key) if isinstance(fp, dict) else getattr(fp, key, None)


def check_excluded_values(fps: dict, session_dir) -> list[dict]:
    """The issues of the pool's excluded-values files, as ValidationIssue dicts.

    Errors (each blocks combining the files):
      excluded_values_unreadable — a row names no animal or endpoint, gives a
          reason that is not one of the known ones, lacks a required note, or
          repeats another row;
      excluded_value_not_found — a row names a value that no file derived for
          a tested apical platform holds (another animal, endpoint or day; a
          cell the workbook leaves empty; a platform whose values cannot be
          named).
    Information: one line per file, what it leaves out.
    """
    files_dir = Path(session_dir) / "files"
    files = {fid: _fp_get(fp, "filename") for fid, fp in fps.items()
             if _fp_get(fp, "data_type") == DATA_TYPE}
    if not files:
        return []
    marks = session_excluded_marks(files_dir)
    issues: list[ValidationIssue] = []
    for fid, name in sorted(files.items(), key=lambda kv: str(kv[1])):
        values, problems = read_excluded_values(files_dir / name)
        if problems:
            issues.append(ValidationIssue(
                severity="error", platform=PLATFORM, issue_type="excluded_values_unreadable",
                message=(f"{name}: {len(problems)} row(s) cannot be followed: "
                         + "; ".join(problems)),
                files_involved=[fid], details={"rows": problems, "reasons": sorted(REASONS)},
            ))
        missing = [v for v in values if not is_applied(v, marks)]
        if missing:
            issues.append(ValidationIssue(
                severity="error", platform=PLATFORM, issue_type="excluded_value_not_found",
                message=(f"{name}: {len(missing)} value(s) it names are not among the "
                         f"study's values ({', '.join(sorted(PLATFORMS))}), so nothing "
                         "was left out for them: "
                         + "; ".join(f"row {v.row} ({v.describe()})" for v in missing)),
                files_involved=[fid],
                details={"rows": [{"row": v.row, "animal_id": v.animal_id,
                                   "endpoint": v.endpoint, "day": v.day} for v in missing]},
            ))
        applied = [v for v in values if is_applied(v, marks)]
        if applied:
            issues.append(ValidationIssue(
                severity="info", platform=PLATFORM, issue_type="excluded_values_applied",
                message=(f"{name}: {len(applied)} value(s) left out of the analysis: "
                         + "; ".join(f"{v.describe()} ({REASONS[v.reason]})" for v in applied)),
                files_involved=[fid],
                details={"values": [m for m in marks if m.get("source") == name]},
            ))
    return [dataclasses.asdict(i) for i in issues]
