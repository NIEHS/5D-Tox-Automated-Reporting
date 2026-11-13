"""
value_validation.py — value-level provenance cross-check (study workbook ↔ other sources).

The study workbooks drive the pool (ADR-0032): validation derives each covered
platform's pivots and sidecars from its workbook (pipeline.pool_fingerprints)
and sets every other source of that platform aside in _originals/ — a
tox_study CSV, or pivots derived from one.  Structural validation (validate_pool)
checks counts and dose groups but never the measured VALUES; this module checks
that every set-aside source agrees with the workbook value by value.  A
divergence is a blocking error: the session was given data that does not trace
to the study.

A platform with a derived tox_study CSV and no workbook gets a WARNING that its
data is unverified — it is never blocked.

It runs from workflow.steps.validate_step (which has the session directory;
validate_pool receives only fingerprints), and appends ValidationIssue dicts
into the report.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from bmdx_pipe import extract_xlsx_value_map
from bmdx_pipe.file_integrator import ValidationIssue, TIER_XLSX

from tables.table_builder_common import load_sidecar

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


def _compare_platform(platform, xmap, smap, files_involved, source=None) -> list[ValidationIssue]:
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
            f"{platform}: {len(hits)} of {total} records in "
            f"{source or 'the derived CSV'} differ from the study workbook ({issue_type}; e.g. animal "
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


def study_workbooks(fps, session_dir) -> dict[str, tuple[str, str]]:
    """{platform: (path, file_id)} of the pool's ORIGINAL study xlsx files —
    identified by internal structure (fp.is_study_file), not extension."""
    out: dict[str, tuple[str, str]] = {}
    for fid, fp in fps.items():
        if _fp_get(fp, "tier") != TIER_XLSX:
            continue
        if not _fp_get(fp, "is_study_file"):
            continue
        platform = _fp_get(fp, "platform")
        filename = _fp_get(fp, "filename", "")
        if platform and filename:
            out[platform] = (str(Path(session_dir) / "files" / filename), fid)
    return out


def _other_sources_value_maps(session_dir: Path, platform: str, workbook: str) -> dict[str, dict]:
    """{file name: value map} for every source of ``platform`` other than
    ``workbook``: sidecars in files/ or _originals/ written from another file,
    and the long-format tox_study CSVs in _originals/ (converted in a scratch
    folder).  Each is compared with the workbook on its own."""
    import tempfile
    from bmdx_pipe import tox_study_csv_to_pivot_txt
    from bmdx_pipe.file_integrator import detect_platform_and_type

    out: dict[str, dict] = {}
    for folder in (session_dir / "files", session_dir / "_originals"):
        for sc_path in sorted(folder.glob("*.sidecar.json")):
            try:
                sc = load_sidecar(str(sc_path))
            except Exception:
                continue
            if sc.get("platform") == platform and sc.get("source") != workbook:
                out[sc_path.name] = _sidecar_value_map(sc)
    originals = session_dir / "_originals"
    if not originals.is_dir():
        return out
    for f in sorted(originals.glob("*.csv")) + sorted(originals.glob("*.txt")):
        if f.with_suffix(".sidecar.json").exists():
            continue  # a pivot: its sidecar was compared above
        if detect_platform_and_type(f.name, f.suffix.lstrip("."), f.stat().st_size) \
                != (platform, "tox_study"):
            continue
        with tempfile.TemporaryDirectory() as tmp:
            try:
                tox_study_csv_to_pivot_txt(str(f), tmp, platform, "tox_study")
            except Exception:
                continue
            smap: dict = {}
            for sc_path in Path(tmp).glob("*.sidecar.json"):
                smap.update(_sidecar_value_map(load_sidecar(str(sc_path))))
        if smap:
            out[f.name] = smap
    return out


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
    study_xlsx = study_workbooks(fps, session_dir)

    # platforms that have a derived tox_study CSV (via the coverage matrix).
    tox_study_platforms: set[str] = set()
    for group_key in (coverage_matrix or {}):
        if "|" in group_key:
            plat, dtype = group_key.split("|", 1)
            if dtype == "tox_study":
                tox_study_platforms.add(plat)

    # 1. Platforms with a study workbook: the pool's data for them is derived
    #    from it (pipeline.pool_fingerprints), so what is checked is every OTHER
    #    source of the platform the session was given — a CSV or pivot the
    #    workbook superseded, kept in _originals/.  Each must agree with it.
    for platform, (xlsx_path, xlsx_fid) in study_xlsx.items():
        sources = _other_sources_value_maps(session_dir, platform, Path(xlsx_path).name)
        if not sources:
            continue
        try:
            xmap = extract_xlsx_value_map(xlsx_path)
        except Exception:
            continue
        for source, smap in sources.items():
            # Only the sexes the source covers (a male-only CSV is not missing
            # the females).
            sexes = {k[0] for k in smap}
            xs = {k: v for k, v in xmap.items() if k[0] in sexes}
            if xs:
                issues.extend(_compare_platform(platform, xs, smap, [xlsx_fid], source))

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
