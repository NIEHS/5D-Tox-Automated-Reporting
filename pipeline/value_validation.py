"""
value_validation.py — value-level provenance cross-check (xlsx ↔ derived CSV).

The customer supplies the animal roster as a derived tox_study CSV, overriding the
original NTP study xlsx. Structural validation (validate_pool) checks counts and
dose groups but never the measured VALUES. This module adds the strong guarantee:
when the original study xlsx is present alongside the derived CSV for a platform,
every per-animal measured value must match — otherwise the report would run on
data that no longer traces to the source study.

It runs from workflow.steps.validate_step (which has the session files dir;
validate_pool receives only fingerprints), and appends ValidationIssue dicts into
the report. A session with no original xlsx simply gets a WARNING that its derived
data is unverified — it is never blocked.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from bmdx_pipe import extract_xlsx_value_map
from bmdx_pipe.file_integrator import ValidationIssue, TIER_XLSX

from tables.table_builder_common import load_sidecar, find_sidecar_paths

# How many concrete example divergences to embed in an issue's details payload.
_MAX_EXAMPLES = 5


def _fp_get(fp, key, default=None):
    """Read a field from a fingerprint that may be a dataclass or a dict."""
    if isinstance(fp, dict):
        return fp.get(key, default)
    return getattr(fp, key, default)


def _norm_value_equal(a, b) -> bool:
    """Value equality: float-aware when both parse as numbers (so 285.10 == 285.1
    and 0 == 0.0), else stripped-string (so 'NA' == 'NA', '' == None)."""
    if a is None:
        a = ""
    if b is None:
        b = ""
    sa, sb = str(a).strip(), str(b).strip()
    if sa == sb:
        return True
    try:
        return abs(float(sa) - float(sb)) < 1e-9
    except (ValueError, TypeError):
        return False


def _sidecar_value_map(sc: dict) -> dict[tuple[str, str, str, str], dict]:
    """Reduce a loaded sidecar to the same key shape extract_xlsx_value_map uses:
    (sex, animal_id, endpoint, day) -> {value, terminal, selection, dose}."""
    out: dict[tuple[str, str, str, str], dict] = {}
    sex = sc.get("sex", "Unknown")
    for aid, animal in (sc.get("animals") or {}).items():
        selection = animal.get("selection", "Unknown")
        try:
            dose = float(animal.get("dose"))
        except (ValueError, TypeError):
            dose = None
        for obs in animal.get("observations") or []:
            key = (sex, str(aid), obs.get("endpoint", ""), obs.get("day", ""))
            out[key] = {
                "value": obs.get("value"),
                "terminal": bool(obs.get("terminal")),
                "selection": selection,
                "dose": dose,
            }
    return out


def _compare_platform(platform, xmap, smap, files_involved) -> list[ValidationIssue]:
    """Compare one platform's xlsx value map against its CSV sidecar value map.
    Emits at most one issue per issue_type (capped, with examples in details)."""
    # issue_type namespace is distinct from validate_pool's STRUCTURAL checks
    # (which also emit "dose_mismatch"/"animal_count_mismatch" from fingerprints).
    # These are VALUE-level provenance divergences (xlsx cell vs CSV sidecar cell),
    # so they're prefixed "value_" to keep the two channels legible in the report.
    buckets: dict[str, list] = {
        "value_mismatch": [],
        "value_dose_mismatch": [],
        "value_selection_mismatch": [],
        "value_terminal_mismatch": [],
        "value_missing_in_csv": [],   # in xlsx, absent from sidecar (dropped measurement)
        "value_missing_in_xlsx": [],  # in sidecar, absent from xlsx (invented measurement)
    }

    all_keys = set(xmap) | set(smap)
    for key in all_keys:
        sex, aid, endpoint, day = key
        x = xmap.get(key)
        s = smap.get(key)
        if x is None:
            buckets["value_missing_in_xlsx"].append((key, None, s.get("value")))
            continue
        if s is None:
            buckets["value_missing_in_csv"].append((key, x.get("value"), None))
            continue
        if not _norm_value_equal(x.get("value"), s.get("value")):
            buckets["value_mismatch"].append((key, x.get("value"), s.get("value")))
        if x.get("dose") != s.get("dose"):
            buckets["value_dose_mismatch"].append((key, x.get("dose"), s.get("dose")))
        if (x.get("selection") or "") != (s.get("selection") or ""):
            buckets["value_selection_mismatch"].append((key, x.get("selection"), s.get("selection")))
        if bool(x.get("terminal")) != bool(s.get("terminal")):
            buckets["value_terminal_mismatch"].append((key, x.get("terminal"), s.get("terminal")))

    total = len(all_keys)
    issues: list[ValidationIssue] = []
    for issue_type, hits in buckets.items():
        if not hits:
            continue
        examples = [
            {"sex": k[0], "animal_id": k[1], "endpoint": k[2], "day": k[3],
             "xlsx": xv, "csv": sv}
            for (k, xv, sv) in hits[:_MAX_EXAMPLES]
        ]
        first = hits[0]
        ex = first[0]
        msg = (
            f"{platform}: {len(hits)} of {total} records in the derived CSV "
            f"differ from the source NTP xlsx ({issue_type}; e.g. animal "
            f"{ex[1]} {ex[3]} '{ex[2]}': xlsx={first[1]!r} csv={first[2]!r}). "
            f"Derived data must trace back to the source study."
        )
        issues.append(ValidationIssue(
            severity="error",
            platform=platform,
            issue_type=issue_type,
            message=msg,
            files_involved=list(files_involved),
            details={"count": len(hits), "total_compared": total, "examples": examples},
        ))
    return issues


def check_value_provenance(dtxsid, fps, coverage_matrix, session_dir) -> list[dict]:
    """Value-level xlsx↔derived-CSV cross-check for a session.

    For every platform that has an ORIGINAL study xlsx (identified by internal
    structure via fp.is_study_file, not extension), compare its per-animal values
    against the derived CSV sidecar; any divergence is a blocking error. For a
    platform that has a derived tox_study CSV but NO study xlsx, emit a
    non-blocking warning that the data is unverified.

    Returns a list of ValidationIssue-as-dict, appended into the validation report.
    A session with no study xlsx and no tox_study CSV adds nothing.
    """
    session_dir = Path(session_dir)
    issues: list[ValidationIssue] = []

    # platform -> (xlsx_path, xlsx_file_id), only for ORIGINAL study xlsx files.
    study_xlsx: dict[str, tuple[str, str]] = {}
    for fid, fp in fps.items():
        if _fp_get(fp, "tier") != TIER_XLSX:
            continue
        if not _fp_get(fp, "is_study_file"):
            continue
        platform = _fp_get(fp, "platform")
        filename = _fp_get(fp, "filename", "")
        if platform and filename:
            study_xlsx[platform] = (str(session_dir / "files" / filename), fid)

    # platforms that have a derived tox_study CSV (via the coverage matrix).
    tox_study_platforms: set[str] = set()
    for group_key in (coverage_matrix or {}):
        if "|" in group_key:
            plat, dtype = group_key.split("|", 1)
            if dtype == "tox_study":
                tox_study_platforms.add(plat)

    # 1. Platforms with an original xlsx → value cross-check against the sidecar.
    for platform, (xlsx_path, xlsx_fid) in study_xlsx.items():
        sidecar_paths = find_sidecar_paths(str(session_dir), platform)
        if not sidecar_paths:
            continue  # xlsx-only platform (e.g. Clinical Observations) — nothing to compare
        try:
            xmap = extract_xlsx_value_map(xlsx_path)
        except Exception:
            continue
        if not xmap:
            continue
        smap: dict = {}
        sidecar_fids = []
        for sc_path in sidecar_paths.values():
            try:
                smap.update(_sidecar_value_map(load_sidecar(sc_path)))
            except Exception:
                continue
        files_involved = [xlsx_fid]
        issues.extend(_compare_platform(platform, xmap, smap, files_involved))

    # 2. Platforms with a derived CSV but NO original xlsx → unverified warning.
    for platform in sorted(tox_study_platforms - set(study_xlsx)):
        issues.append(ValidationIssue(
            severity="warning",
            platform=platform,
            issue_type="unverified_derived_data",
            message=(
                f"{platform}: using derived tox_study data with no original NTP "
                f"study xlsx to cross-check it against. Values cannot be verified "
                f"against the source study."
            ),
            files_involved=[],
            details={},
        ))

    return [dataclasses.asdict(i) for i in issues]
