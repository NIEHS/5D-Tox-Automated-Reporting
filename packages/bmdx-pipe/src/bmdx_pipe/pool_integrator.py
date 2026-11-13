"""
pool_integrator — Merge validated pool files into a unified BMDProject JSON.

After file upload, fingerprinting, and cross-validation, the pool contains
multiple files (xlsx, txt/csv, bm2) covering different platforms (Body Weight,
Organ Weight, Clinical Chemistry, Hematology, Hormones, gene_expression, etc.)
at different processing tiers.

Each file has a *platform* (the Apical vocabulary name like "Body Weight") and
a *data_type* ("tox_study", "inferred", or "gene_expression").  The coverage
matrix groups files by platform, and this module selects the best file per
platform (respecting user conflict resolutions), then delegates to bmdx-core's
native Java code for .bm2 merging and JSON serialization.

Data flow:
    Validate → Resolve conflicts → integrate_pool() → integrated.json
        → build_table_data() → section cards with tables & narratives

The Java layer (IntegrateProject) uses BMDExpress 3's native classes:
    - ProjectUtilities.addProjectToProject() for .bm2 merging
    - ExperimentFileUtil.readFile() for .txt/.csv parsing
    - Jackson ObjectMapper with NaN→null serializers for valid JSON output

Python handles:
    - Tier selection (which file to use per platform)
    - xlsx pre-conversion (NTP long-format → pivot)
    - Post-integration metadata enrichment (_meta, _category_lookup)
    - LLM metadata inference (experiment descriptions)

Usage:
    from pool_integrator import integrate_pool

    integrated = integrate_pool(dtxsid, session_dir, fingerprints,
                                coverage_matrix, precedence)
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import csv
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any

from .experiment_metadata import (
    apply_described, attach_metadata, describe_from_structure, infer_experiment_metadata,
    record_provenance, workbook_disagreements,
)
from .study_workbook import META_COLS, read_study_workbook

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# Tier priority for auto-selection: .bm2 preferred (has BMD results),
# then txt/csv (BMDExpress-importable pivot), then xlsx (raw long-format).
# NOTE: xlsx files are the study-team source of truth for doses and animal
# roster, but bm2 files are needed for BMD modeling results.  When both
# exist, bm2 wins the integration (for BMD), and xlsx roster metadata
# is overlaid separately via _collect_xlsx_rosters().
_TIER_PREFERENCE = {"bm2": 1, "txt": 2, "csv": 2, "txt_csv": 2, "xlsx": 3}

# Non-endpoint columns in NTP long-format files (xlsx Data tab + tox_study CSV).
# Everything else in the header is treated as a measured endpoint.  One set
# (study_workbook.META_COLS) for the workbook reader and the CSV pivot, so the
# two agree on what counts as an endpoint.
_META_COLS = META_COLS

# Java helper directory — centralized in java_bridge.py
from .java_bridge import JAVA_HELPER_DIR, build_classpath


# ---------------------------------------------------------------------------
# Java integration — call bmdx-core's IntegrateProject
# ---------------------------------------------------------------------------


def _run_integrate_java(
    bm2_paths: list[str],
    txt_paths: list[str],
    output_path: str,
    metadata_path: str | None = None,
) -> None:
    """
    Call IntegrateProject (Java) to merge .bm2 and .txt/.csv files into
    a single BMDProject JSON.

    Uses bmdx-core's native classes:
      - ProjectUtilities.addProjectToProject() for .bm2 merge
      - ExperimentFileUtil.readFile() for .txt/.csv parsing
      - Jackson with NaN→null serializers for valid JSON output

    Args:
        bm2_paths:     List of .bm2 file paths to merge.
        txt_paths:     List of .txt/.csv pivot files to import.
        output_path:   Where to write the integrated JSON.
        metadata_path: Optional path to LLM metadata sidecar JSON.
    """
    from .java_bridge import build_classpath as _build_cp

    cp = _build_cp()
    helper_dir = str(JAVA_HELPER_DIR)

    cmd = [
        "java", "-cp", f"{cp}:{helper_dir}",
        "IntegrateProject",
        "--output", output_path,
    ]

    if bm2_paths:
        cmd.append("--bm2")
        cmd.extend(bm2_paths)

    if txt_paths:
        cmd.append("--txt")
        cmd.extend(txt_paths)

    if metadata_path:
        cmd.extend(["--metadata", metadata_path])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("IntegrateProject failed:\n%s\n%s", result.stdout, result.stderr)
        raise RuntimeError(f"Java integration failed: {result.stderr}")

    logger.info("IntegrateProject output:\n%s", result.stdout)


# ---------------------------------------------------------------------------
# xlsx parser — NTP long-format needs Python pre-conversion
# ---------------------------------------------------------------------------

# Maps Apical platform names (from FileFingerprint.platform) to the
# BMDExpress experiment name prefixes used when constructing pivot files.
# These prefixes become the first cell of the header row in the wide-format
# output (e.g., "BodyWeightMale"), which BMDExpress uses as the experiment name.
_PLATFORM_TO_BM2_PREFIX: dict[str, str] = {
    "Body Weight":          "BodyWeight",
    "Organ Weight":         "OrganWeight",
    "Clinical Chemistry":   "ClinicalChemistry",
    "Hematology":           "Hematology",
    "Hormones":             "Hormone",
    "Tissue Concentration": "TissueConcentration",
    "Clinical":             "ClinicalObservation",
}


def _collect_xlsx_rosters(
    coverage_matrix: dict,
    fingerprints: dict,
    files_dir: str,
) -> dict[str, dict]:
    """
    For each platform that has a study xlsx, extract the authoritative animal
    roster (doses, animal IDs, selection groups) from the fingerprint.

    Study xlsx files are the source of truth for which animals were in which
    dose groups — including animals that died before certain endpoints could
    be measured.  This data is stored on integrated._meta.xlsx_rosters so
    that build_table_data() can use it for accurate N counts and footnotes.

    Args:
        coverage_matrix: {platform → {tier_name → [file_ids]}}.
        fingerprints:    {file_id → FileFingerprint or dict}.
        files_dir:       Directory containing uploaded files.

    Returns:
        {platform → {
            "file_id": str,
            "filename": str,
            "dose_groups": [float, ...],
            "n_animals_by_dose": {dose: int},
            "selection_groups": [str, ...],
            "animals_by_dose_selection": {dose: {selection: [animal_ids]}},
        }}
    """
    rosters = {}
    for platform_key, tiers in coverage_matrix.items():
        xlsx_fids = tiers.get("xlsx")
        if not xlsx_fids:
            continue
        if isinstance(xlsx_fids, str):
            xlsx_fids = [xlsx_fids]
        xlsx_fids = [f for f in xlsx_fids if f]
        if not xlsx_fids:
            continue

        fid = xlsx_fids[0]
        fp = fingerprints.get(fid)
        if fp is None:
            continue

        # Support both dict and FileFingerprint attribute access
        def _get(obj, key, default=None):
            return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

        # Only include study files (two-tab NTP structure).
        # For fingerprints from old caches (before is_study_file was added),
        # fall back to assuming all xlsx files are study files — this is safe
        # because non-study xlsx files would never appear in the pool.
        is_study = _get(fp, "is_study_file", None)
        if is_study is None:
            # Legacy fingerprint without the field — assume xlsx = study file
            is_study = _get(fp, "file_type", "") == "xlsx"
        if not is_study:
            continue

        # Stringify float-keyed dicts for JSON serialization safety — the
        # integrated.json is written with json.dump() which rejects non-str keys.
        # Downstream annotate_missing_animals() converts back to float.
        def _str_keys(d):
            if not d:
                return d
            return {str(k): v for k, v in d.items()}

        rosters[platform_key] = {
            "file_id": fid,
            "filename": _get(fp, "filename", ""),
            "dose_groups": _get(fp, "dose_groups", []),
            "n_animals_by_dose": _str_keys(_get(fp, "n_animals_by_dose", {})),
            "selection_groups": _get(fp, "selection_groups", []),
            "animals_by_dose_selection": _str_keys(_get(fp, "animals_by_dose_selection", {})),
            "core_animals_by_dose_sex": _str_keys(_get(fp, "core_animals_by_dose_sex", {})),
        }

    return rosters


def key_sheet_units(path: str) -> dict[str, str]:
    """
    {endpoint column label: measurement unit} from an NTP Individual Animal
    workbook's "Key to Column Labels" sheet (study_workbook.explanation_unit).

    The Data sheet's headers carry no units ("Albumin", "Plasma 2 Hour X
    Concentration"); the Key sheet explains each column and states the unit.  A
    column whose explanation states none is left out rather than guessed.
    Metadata columns (META_COLS) are skipped.
    """
    return read_study_workbook(path).units


_BODY_WEIGHT_GAIN = "Body Weight Gain"


def _study_day_number(label: str) -> int | None:
    """"SD5" -> 5; None for anything else."""
    m = re.fullmatch(r"SD(\d+)", label or "")
    return int(m.group(1)) if m else None


def _body_weight_gain(
    data_by_sex_endpoint: dict[tuple[str, str], dict[str, float]],
) -> dict[tuple[str, str], dict[str, float]]:
    """{(sex, "Body Weight Gain"): {animal: last-day weight - first-day weight}}
    for the animals weighed on both the study's first and last day (the
    pivot's animals — Core only once _keep_core_animals has run)."""
    days = sorted({ep for (_s, ep) in data_by_sex_endpoint if _study_day_number(ep) is not None},
                  key=_study_day_number)
    if len(days) < 2:
        return {}
    first, last = days[0], days[-1]
    out: dict[tuple[str, str], dict[str, float]] = {}
    for sex in {s for (s, _ep) in data_by_sex_endpoint}:
        start = data_by_sex_endpoint.get((sex, first), {})
        end = data_by_sex_endpoint.get((sex, last), {})
        gains = {aid: round(end[aid] - start[aid], 6) for aid in start.keys() & end.keys()}
        if gains:
            out[(sex, _BODY_WEIGHT_GAIN)] = gains
    return out


def _keep_core_animals(
    data_by_sex_endpoint: dict[tuple[str, str], dict[str, float]],
    sidecar_animals: dict[str, dict[str, dict]],
) -> int:
    """Drop every non-Core animal from the pivot values when the file marks a
    Core cohort; returns how many animals were dropped.

    NTP files tag each animal's Selection: "Core Animals" (the scheduled-
    sacrifice cohort) or the internal-dose cohort ("Biosampling Animals" /
    "Biosample Animals"), weighed and observed on its own schedule.  Every
    published summary counts Core animals only — the body weight n of
    NIEHS-07 … 13 equals the Core count per dose (NIEHS-12 mice, 250 ppm:
    8 Core → n = 8), the 3 internal-dose animals per group excluded — so the
    values that feed statistics and BMD modeling are Core only.  The sidecar
    keeps every animal (attrition, mortality footnotes).  A file that marks no
    Core animal at all (Tissue Concentration: internal-dose animals only) or
    has no Selection column is left as is."""
    core = {(sex, aid) for sex, animals in sidecar_animals.items()
            for aid, rec in animals.items() if "core" in str(rec.get("selection", "")).lower()}
    if not core:
        return 0
    dropped = set()
    for (sex, endpoint), vals in list(data_by_sex_endpoint.items()):
        for aid in [a for a in vals if (sex, a) not in core]:
            dropped.add((sex, aid))
            del vals[aid]
        if not vals:
            del data_by_sex_endpoint[(sex, endpoint)]
    return len(dropped)


def _removal_day(value) -> int | None:
    """A removal day ("SD5", "SD 5", "5") as its number; None when absent."""
    m = re.search(r"(-?\d+)", str(value or ""))
    return int(m.group(1)) if m else None


def _keep_scheduled_removals(
    data_by_sex_endpoint: dict[tuple[str, str], dict[str, float]],
    sidecar_animals: dict[str, dict[str, dict]],
) -> int:
    """Organ weights: drop from the pivot values every animal removed before
    the study's scheduled necropsy (found dead, euthanized moribund); returns
    how many were dropped.

    The scheduled necropsy is the latest removal day of the sex's Core
    animals.  An animal removed on an earlier day may have been weighed then
    (NIEHS-12 mouse 502, 250 ppm: 14.9 g on SD4), but every published organ
    weight table counts the scheduled removals only (NIEHS-12: 18.5 ± 0.4 g
    over the seven necropsied on SD5), as the report's organ weight table
    does from the sidecar.  The sidecar keeps every animal.  An animal whose
    removal day is not recorded is kept."""
    dropped = set()
    for sex, animals in sidecar_animals.items():
        day_of = {aid: _removal_day(next((o["day"] for o in rec.get("observations", [])
                                          if o.get("day")), None))
                  for aid, rec in animals.items()}
        core_days = [d for aid, d in day_of.items() if d is not None
                     and "core" in str(animals[aid].get("selection", "")).lower()]
        if not core_days:
            continue
        scheduled = max(core_days)
        early = {aid for aid, d in day_of.items() if d is not None and d != scheduled}
        for (s, endpoint), vals in list(data_by_sex_endpoint.items()):
            if s != sex:
                continue
            for aid in early & vals.keys():
                dropped.add((sex, aid))
                del vals[aid]
            if not vals:
                del data_by_sex_endpoint[(s, endpoint)]
    return len(dropped)


def tox_study_csv_to_pivot_txt(
    path: str,
    output_dir: str,
    platform: str,
    data_type: str,
    units: dict[str, str] | None = None,
) -> list[str]:
    """
    Convert a long-format _tox_study CSV file into tab-delimited pivot files
    that IntegrateProject can import via ExperimentFileUtil.

    _tox_study CSV files are long-format like NTP xlsx files:
      Concentration, Animal ID, Sex, endpoint1, endpoint2, ...

    The output pivot format (long_rows_to_pivot):
      Row 0: # Provider/Platform/Data Type headers (for ExperimentDescriptionParser)
      Row 1: experiment_name, animal_id1, animal_id2, ...
      Row 2: Dose, dose1, dose2, ...
      Row 3+: endpoint_name, value1, value2, ...

    One output file per sex found in the data.

    When Observation Day is present (e.g., "SD0", "SD5"), each observation day
    becomes a separate endpoint row in the pivot.  This gives BMDExpress
    distinct probes for baseline vs terminal body weight, matching how the
    inferred .bm2 files already work.

    A **sidecar JSON** file is written alongside each pivot txt, capturing
    per-animal metadata that the wide format discards (Selection, Observation
    Day, Terminal Flag).  The sidecar is consumed by the body weight table
    builder to apply NIEHS business rules (Core Animals filtering, attrition
    footnotes).  BMDExpress never sees the sidecar — it reads only the txt.

    Args:
        path:       Absolute path to the _tox_study CSV file.
        output_dir: Directory to write the pivot .txt files.
        platform:   Apical platform name (e.g., "Body Weight") from fingerprint.
        data_type:  Data type (e.g., "tox_study") from fingerprint.
        units:      {endpoint column: unit} the CSV itself cannot carry (its
                    headers are the workbook's unit-less Data-sheet labels) —
                    e.g. key_sheet_units() of the source workbook.  Recorded in
                    each sidecar as "units" for the endpoints this file has.

    Returns:
        List of paths to the generated pivot .txt files.
    """
    # Read file, skipping # metadata header lines
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw_lines = [line for line in f if not line.startswith("#")]

    if not raw_lines:
        logger.warning("tox_study CSV empty after skipping headers: %s", path)
        return []

    # Detect separator from first data line
    sep = "\t" if "\t" in raw_lines[0] else ","

    reader = csv.reader(raw_lines, delimiter=sep)
    rows = list(reader)

    if len(rows) < 2:
        logger.warning("tox_study CSV too short: %s", path)
        return []

    source_stem = os.path.splitext(os.path.basename(path))[0]

    def out_name(sex: str, n_sexes: int) -> str:
        # Output filename = source filename with .txt extension.  If one source
        # file holds several sexes, the sex is appended to tell them apart.
        if n_sexes > 1:
            return f"{source_stem}_{sex.replace(' ', '_')}.txt"
        return f"{source_stem}.txt"

    return long_rows_to_pivot(rows[0], rows[1:], output_dir, platform, data_type,
                              source=os.path.basename(path), out_name=out_name,
                              units=units)


# The derived files' name stem per platform, as the pool's filename patterns
# (file_integrator.detect_platform_and_type) read them: "<stem>_truth_<sex>".
WORKBOOK_STEMS = {
    "Body Weight": "body_weight",
    "Organ Weight": "organ_weights",
    "Clinical Chemistry": "clin_chem",
    "Clinical": "clinical_obs",
    "Hematology": "hematology",
    "Hormones": "hormones",
    "Tissue Concentration": "tissue_conc",
}


def study_workbook_to_pool_files(path: str, output_dir: str, platform: str) -> list[str]:
    """
    The files the pool uses, derived from a study workbook — the workbook drives.

    For a measured platform: one BMDExpress pivot ``<stem>_truth_<sex>.txt`` and
    one sidecar per sex (long_rows_to_pivot), with the units the workbook's Key
    sheet states.  For clinical observations (categorical findings, not
    endpoints): one ``<stem>_truth_<sex>.csv`` per sex, the Data rows as they
    are, for the incidence tables; its first line ``# Source: <workbook>`` says
    where it came from.  A sex the workbook doesn't record (no Sex column and
    no single sex in the title) is written as "unknown".

    Returns the paths written; [] for a platform with no stem or a workbook with
    no rows.
    """
    from .study_workbook import read_study_workbook

    stem = WORKBOOK_STEMS.get(platform)
    if stem is None:
        return []
    wb = read_study_workbook(path)
    if not wb.rows or wb.col("Animal ID") is None:
        return []
    source = os.path.basename(path)

    if platform == "Clinical":
        sex_i = wb.col("Sex")
        by_sex: dict[str, list[list[str]]] = {}
        for r in wb.rows:
            sex = (r[sex_i] if sex_i is not None else "").strip().lower() or "unknown"
            by_sex.setdefault(sex, []).append(r)
        written = []
        for sex, rows in sorted(by_sex.items()):
            out = os.path.join(output_dir, f"{stem}_truth_{sex}.csv")
            with open(out, "w", newline="", encoding="utf-8") as f:
                f.write(f"# Source: {source}\n")
                w = csv.writer(f, lineterminator="\r\n")
                w.writerow(wb.header)
                w.writerows(rows)
            written.append(out)
        return written

    def out_name(sex: str, _n_sexes: int) -> str:
        return f"{stem}_truth_{(sex or 'unknown').lower().replace(' ', '_')}.txt"

    return long_rows_to_pivot(wb.header, wb.rows, output_dir, platform, "tox_study",
                              source=source, out_name=out_name, units=wb.units or None)


def long_rows_to_pivot(
    header: list[str],
    body: list[list[str]],
    output_dir: str,
    platform: str,
    data_type: str,
    *,
    source: str,
    out_name,
    units: dict[str, str] | None = None,
) -> list[str]:
    """
    The NTP long-format rows (one row per animal and observation) → one
    BMDExpress pivot .txt and one sidecar .json per sex, in ``output_dir``.

    The rows come from a tox_study CSV (tox_study_csv_to_pivot_txt) or from a
    study workbook's Data sheet (study_workbook_to_pool_files); both write the
    same files from the same rows.  ``source`` is the file the rows came from
    (recorded in each sidecar), ``out_name(sex, n_sexes)`` names the pivot of
    one sex, and ``units`` ({endpoint column: unit}) is recorded in the sidecar.
    Returns the paths of the pivots written.
    """
    path = source
    rows = [header] + list(body)
    header = [c.strip() for c in rows[0]]
    header_lower = [h.lower() for h in header]

    # Find key column indices — same structure as NTP xlsx
    _LONG_FORMAT_MARKERS = {"concentration", "animal id", "sex"}
    if not _LONG_FORMAT_MARKERS.issubset(set(header_lower)):
        logger.warning("tox_study CSV missing required columns: %s", path)
        return []

    dose_col = header_lower.index("concentration")
    animal_col = header_lower.index("animal id")
    sex_col = header_lower.index("sex") if "sex" in header_lower else None

    # Optional metadata columns — present in NTP tox_study CSVs but absent
    # from generic dose-response files.  When present, they enable:
    #   - Observation Day: split endpoints by study day (SD0, SD5 → separate rows)
    #   - Selection: Core Animals vs Biosampling Animals (for N-count filtering)
    #   - Terminal Flag: which measurement is the animal's last (for attrition)
    #
    # Different NTP platforms use different column names for the day:
    #   - Body Weight, Clinical Chemistry, Hematology: "Observation Day"
    #   - Organ Weight, Hormones: "Removal Day"
    #   - Tissue Concentration: "Phase" + "Day" (combined as "{Phase}{Day}")
    # We normalize all variants into a single obs_day_col so downstream code
    # doesn't need platform-specific branching.
    obs_day_col = header_lower.index("observation day") if "observation day" in header_lower else None
    removal_day_col = header_lower.index("removal day") if "removal day" in header_lower else None
    phase_col = header_lower.index("phase") if "phase" in header_lower else None
    day_col = header_lower.index("day") if "day" in header_lower else None
    selection_col = header_lower.index("selection") if "selection" in header_lower else None
    terminal_col = header_lower.index("terminal flag") if "terminal flag" in header_lower else None

    # Whether we should SPLIT endpoints by day in the pivot output.
    # When True, "Body Weight" at SD0 becomes "SD0" and at SD5 becomes "SD5"
    # in the pivot — giving BMDExpress separate probes per study day.
    #
    # This splitting only applies to "Observation Day" columns (Body Weight,
    # Clinical Chemistry, Hematology) where the SAME endpoint is measured on
    # MULTIPLE study days.  "Removal Day" (Organ Weight, Hormones) and
    # "Phase"+"Day" (Tissue Concentration) are NOT used for endpoint splitting
    # — those platforms have one measurement per endpoint per animal, so the
    # column name IS the endpoint.  The day information is still captured in
    # the sidecar for the table builders to use.
    has_obs_day = obs_day_col is not None

    # Note: obs_day is resolved per-row from whichever day column is present
    # (Observation Day, Removal Day, or Phase+Day).  The sidecar guard
    # `if obs_day or terminal` fires for ALL platforms that have any day info,
    # even though has_obs_day only controls endpoint-label splitting in pivots.

    # Endpoint columns: everything not in known metadata columns (module-level
    # _META_COLS, shared with extract_xlsx_value_map so both stay in sync).
    endpoint_cols = [
        i for i, h in enumerate(header_lower)
        if h not in _META_COLS and h
    ]

    if not endpoint_cols:
        logger.warning("No endpoint columns found in %s", path)
        return []

    # ── Parse data rows ──────────────────────────────────────────────────
    #
    # Build two structures simultaneously:
    #   1. data_by_sex_endpoint: {(sex, endpoint_label): {animal_id: value}}
    #      — the wide-format pivot input, where endpoint_label is either the
    #      raw column name ("Body Weight") or the observation day tag ("SD0",
    #      "SD5") when Observation Day is present.
    #   2. sidecar_animals: {sex: {animal_id: {dose, selection, observations}}}
    #      — per-animal metadata for the sidecar JSON, capturing everything
    #      the pivot discards.
    #
    # When Observation Day is present, we use the day tag AS the endpoint
    # label (not "Body Weight").  This means "SD0" and "SD5" become distinct
    # rows in the pivot, matching how the inferred .bm2 already encodes them.
    data_by_sex_endpoint: dict[tuple[str, str], dict[str, float]] = {}
    animal_dose_map: dict[str, float] = {}

    # Sidecar: per-sex, per-animal metadata
    # Structure: {sex: {animal_id: {dose, selection, observations: [{day, value, terminal, endpoint}]}}}
    sidecar_animals: dict[str, dict[str, dict]] = {}

    for row in rows[1:]:
        if len(row) <= max(dose_col, animal_col):
            continue

        aid = row[animal_col].strip()
        if not aid:
            continue

        try:
            dose = float(row[dose_col].strip())
        except (ValueError, TypeError):
            continue

        animal_dose_map[aid] = dose

        sex = "Unknown"
        if sex_col is not None and sex_col < len(row):
            s = row[sex_col].strip()
            if s:
                sex = s.title()

        # Read optional metadata columns.
        # Resolve the observation day from whichever column variant is present:
        #   - "Observation Day" (Body Weight, Clinical Chemistry, Hematology)
        #   - "Removal Day" (Organ Weight, Hormones)
        #   - "Phase" + "Day" combined (Tissue Concentration: "SD" + "5" → "SD5")
        obs_day = ""
        if obs_day_col is not None and obs_day_col < len(row):
            obs_day = row[obs_day_col].strip()
        elif removal_day_col is not None and removal_day_col < len(row):
            obs_day = row[removal_day_col].strip()
        elif phase_col is not None and day_col is not None:
            phase_val = row[phase_col].strip() if phase_col < len(row) else ""
            day_val = row[day_col].strip() if day_col < len(row) else ""
            if phase_val or day_val:
                obs_day = f"{phase_val}{day_val}"

        selection = ""
        if selection_col is not None and selection_col < len(row):
            selection = row[selection_col].strip()

        terminal = ""
        if terminal_col is not None and terminal_col < len(row):
            terminal = row[terminal_col].strip()

        # Ensure this animal exists in the sidecar structure
        sex_animals = sidecar_animals.setdefault(sex, {})
        animal_rec = sex_animals.setdefault(aid, {
            "dose": dose,
            "selection": selection or "Unknown",
            "observations": [],
        })
        # Update selection if we see a non-empty value (all rows for an
        # animal should have the same selection, but be defensive)
        if selection and animal_rec["selection"] == "Unknown":
            animal_rec["selection"] = selection

        for col_idx in endpoint_cols:
            col_name = header[col_idx]
            if col_idx >= len(row):
                continue
            val = row[col_idx].strip()

            # Record the observation in the sidecar regardless of whether the
            # value is numeric (we want to capture "NA" entries too — they
            # signal missing data, e.g., animal 203 at 1000 mg/kg with NA
            # body weight at SD0 because it was found dead).
            if obs_day or terminal:
                animal_rec["observations"].append({
                    "day": obs_day,
                    "endpoint": col_name,
                    "value": val if val else None,
                    "terminal": terminal.lower() in ("yes", "true", "1") if terminal else False,
                })

            if not val:
                continue
            try:
                fval = float(val)
            except (ValueError, TypeError):
                # Non-numeric values (like "NA") are not included in the
                # pivot (BMDExpress can't model them), but they ARE captured
                # in the sidecar for the table builder.
                continue

            # When Observation Day is present AND there is only one endpoint
            # column (e.g., Body Weight), use the day tag as the endpoint
            # label: "Body Weight" at "SD0" → endpoint "SD0", at "SD5" →
            # "SD5".  This gives BMDExpress separate probes per study day,
            # matching how the inferred .bm2 files encode them.
            #
            # When there are MULTIPLE endpoint columns (e.g., Clinical
            # Chemistry with ALT, Albumin, ALP, ..., all measured on the
            # same observation day "SD5"), using the day tag alone would
            # collapse every column onto the same dict key and silently
            # discard all but the last.  In that case, keep the original
            # column name as the endpoint label — the observation day is
            # still captured in the sidecar for table builders.
            if has_obs_day and obs_day and len(endpoint_cols) == 1:
                endpoint_label = obs_day
            else:
                endpoint_label = col_name

            key = (sex, endpoint_label)
            data_by_sex_endpoint.setdefault(key, {})[aid] = fval

    if not data_by_sex_endpoint:
        return []

    dropped = _keep_core_animals(data_by_sex_endpoint, sidecar_animals)
    if dropped:
        logger.info("%s: %d non-Core animal(s) kept out of the pivot (sidecar keeps them)",
                    os.path.basename(path), dropped)
    if not data_by_sex_endpoint:
        return []
    if platform == "Organ Weight" and removal_day_col is not None:
        early = _keep_scheduled_removals(data_by_sex_endpoint, sidecar_animals)
        if early:
            logger.info("%s: %d animal(s) removed before the scheduled necropsy kept out of "
                        "the pivot (sidecar keeps them)", os.path.basename(path), early)
        if not data_by_sex_endpoint:
            return []

    # Body Weight Gain — a derived endpoint NIEHS reports and models (the
    # BMD/LOEL/NOEL summaries; its own BMDExpress input in NIEHS-13): per
    # animal, the last study day's weight minus the first's (SD0 -> SD5).
    # NIEHS-13's mouse "Body Weight Gain" input holds exactly the Core animals
    # weighed on both days — the pivot's animals after _keep_core_animals.
    # Written as a pivot row so integration, statistics and BMD modeling
    # treat it like any other endpoint.
    if platform == "Body Weight" and has_obs_day and len(endpoint_cols) == 1:
        data_by_sex_endpoint.update(_body_weight_gain(data_by_sex_endpoint))

    # Build BMDExpress experiment name prefix from platform
    prefix = _PLATFORM_TO_BM2_PREFIX.get(platform, platform.replace(" ", ""))

    # Group by sex and write pivot files
    sex_data: dict[str, dict] = {}
    for (sex, endpoint), animal_vals in data_by_sex_endpoint.items():
        if sex not in sex_data:
            sex_data[sex] = {"endpoints": {}, "animals": set()}
        sex_data[sex]["endpoints"][endpoint] = animal_vals
        sex_data[sex]["animals"].update(animal_vals.keys())

    output_paths = []
    for sex, info in sex_data.items():
        animals = sorted(info["animals"],
                         key=lambda a: (animal_dose_map.get(a, 0), a))

        lines = []
        # Metadata headers for ExperimentDescriptionParser
        lines.append("# Provider: Apical")
        lines.append(f"# Platform: {platform}")
        lines.append(f"# Data Type: {data_type}")
        # Row 1: header — probe_id + animal IDs
        lines.append("\t".join([f"{prefix}{sex}"] + animals))
        # Row 2: doses
        lines.append("\t".join(["Dose"] + [
            str(animal_dose_map.get(a, 0)) for a in animals
        ]))
        # Row 3+: endpoints.  Sort endpoint keys so study days appear in
        # natural order (SD0 before SD1 before SD5).
        #
        # Animals missing from a given endpoint (e.g., no SD1 body weight
        # for low-dose animals, or no organ weight for animals that died
        # before terminal sacrifice) are written as "NaN".  Java's
        # ExperimentFileUtil rejects empty cells ("") as non-numeric, but
        # handles NaN as a missing-value marker that BMDExpress can skip
        # during modeling.
        for endpoint in sorted(info["endpoints"].keys()):
            animal_vals = info["endpoints"][endpoint]
            values = [str(animal_vals.get(a, "NaN")) for a in animals]
            lines.append("\t".join([endpoint] + values))

        pivot_name = out_name(sex, len(sex_data))
        out_path = os.path.join(output_dir, pivot_name)
        with open(out_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        output_paths.append(out_path)
        logger.info("Converted long-format → wide: %s (%d endpoints, %d animals)",
                     pivot_name, len(info["endpoints"]), len(animals))

        # ── Write sidecar JSON ───────────────────────────────────────────
        # The sidecar captures per-animal metadata that the wide-format pivot
        # discards: Selection (Core vs Biosampling), Observation Day, Terminal
        # Flag, and all raw observation values (including non-numeric "NA").
        #
        # Structure:
        #   {
        #     "source": "body_weight_truth_male.csv",
        #     "platform": "Body Weight",
        #     "sex": "Male",
        #     "animals": {
        #       "101": {
        #         "dose": 0.0,
        #         "selection": "Core Animals",
        #         "observations": [
        #           {"day": "SD0", "endpoint": "Body Weight", "value": "285.1", "terminal": false},
        #           {"day": "SD5", "endpoint": "Body Weight", "value": "300.3", "terminal": true}
        #         ]
        #       }, ...
        #     }
        #   }
        #
        # The body weight table builder reads this to:
        #   - Filter to Core Animals only (exclude Biosampling Animals)
        #   - Compute mean±SE from raw animal values
        #   - Generate attrition footnotes from terminal flags on non-SD5 days
        #   - Include all dose groups (even those where all animals died)
        if sex in sidecar_animals:
            sidecar_path = os.path.splitext(out_path)[0] + ".sidecar.json"
            # Include ALL animals from the source CSV for this sex, not just
            # those in the pivot.  Animals with all-NA values (sample not
            # received, clotted, etc.) are excluded from the pivot but need
            # to be in the sidecar for sample availability footnote generation.
            sidecar_data = {
                "source": source,
                "platform": platform,
                "sex": sex,
                "animals": dict(sidecar_animals[sex]),
            }
            # Measurement units, when the caller knows them — only for this
            # file's endpoint columns.  Absent ⇒ the unit was not recorded.
            file_units = {header[i]: units[header[i]]
                          for i in endpoint_cols if units and header[i] in units}
            if file_units:
                sidecar_data["units"] = file_units
            import json as json_mod
            with open(sidecar_path, "w") as sf:
                json_mod.dump(sidecar_data, sf, indent=2)
            logger.info("Wrote sidecar: %s (%d animals)",
                         os.path.basename(sidecar_path),
                         len(sidecar_data["animals"]))

    return output_paths


def extract_xlsx_value_map(path: str) -> dict[tuple[str, str, str, str], dict]:
    """
    Extract per-animal measured VALUES from an original NTP study xlsx, keyed for
    a value-level cross-check against the derived tox_study CSV sidecar.

    This mirrors the per-row loop of ``tox_study_csv_to_pivot_txt`` (the sidecar
    builder) so that, for faithful data, the xlsx and the CSV sidecar reduce to
    identical records.  It reads the workbook (study_workbook) and returns:

        {(sex, animal_id, endpoint, day): {
            "value": str | None,   # raw stripped cell (kept incl. "NA"); None if empty
            "terminal": bool,      # Terminal Flag
            "selection": str,      # Core Animals / Biosampling Animals / Unknown
            "dose": float,         # Concentration
        }}

    Only observations that carry a day (or a terminal flag) are emitted — the same
    ``if obs_day or terminal`` guard the sidecar uses — so both sides are symmetric.
    ``endpoint`` is the RAW stripped column header (NOT the pivot's day-tag
    relabel), because the sidecar stores the raw header too.  Returns ``{}`` when
    the workbook has no animal or dose column, or no endpoint columns.
    """
    wb = read_study_workbook(path)
    if wb.col("Animal ID") is None or wb.col("Concentration") is None or not wb.endpoint_cols:
        return {}
    out: dict[tuple[str, str, str, str], dict] = {}
    for ob in wb.observations():
        if ob.dose is None:
            continue
        if not (ob.day or ob.terminal):
            continue
        for endpoint, val in ob.values.items():
            out[(ob.sex or "Unknown", ob.animal_id, endpoint, ob.day)] = {
                "value": val or None,
                "terminal": ob.terminal,
                "selection": ob.selection or "Unknown",
                "dose": ob.dose,
            }
    return out


# ---------------------------------------------------------------------------
# Main integration orchestrator
# ---------------------------------------------------------------------------


def _apply_approved_metadata(experiments: list[dict], approved: dict[str, dict],
                             provenance: dict[str, dict] | None = None) -> int:
    """Put each approved ExperimentDescription back on its experiment.

    Approval is the user's sign-off on an experiment's metadata; integration
    re-infers metadata from names (and the LLM) every time, which must not undo
    it — NIEHS-13's heart experiment "rat_4D_HE_No0" re-inferred as "blood".
    Runs before the genomics sidecar and the .bm2 are written, so both carry
    the approved values.  Experiments the approval does not name keep their
    inferred metadata.  A field the study workbooks state (``provenance``
    "workbook") keeps the workbook's value: an approval cannot contradict it
    (safeguards.inputs refuses one that tries).  Returns how many experiments
    were restored."""
    provenance = provenance if provenance is not None else {}
    restored = 0
    for exp in experiments:
        name = exp.get("name", "")
        desc = approved.get(name)
        if not isinstance(desc, dict):
            continue
        current = exp.get("experimentDescription") or {}
        sources = provenance.setdefault(name, {})
        new = dict(desc)
        for k, src in sources.items():
            if src != "workbook":
                continue
            if new.get(k) not in (None, current.get(k)):
                logger.warning("%s: approved %s %r differs from the study workbook's %r; "
                               "the workbook's stands", name, k, new[k], current.get(k))
            new[k] = current.get(k)
        exp["experimentDescription"] = new
        for k, v in new.items():
            if v is not None and sources.get(k) != "workbook":
                sources[k] = "approved"
        restored += 1
    if restored:
        logger.info("Approved metadata restored on %d experiment(s)", restored)
    return restored


def integrate_pool(
    dtxsid: str,
    session_dir: str,
    fingerprints: dict[str, dict],
    coverage_matrix: dict[str, dict[str, list[str]]],
    precedence: list[dict],
    *,
    test_article: dict | None = None,
    llm_generate_json: Any = None,
    approved_metadata: dict[str, dict] | None = None,
    study_structure: dict | None = None,
) -> dict:
    """
    Merge all pool files into a single unified BMDProject JSON.

    For each platform in the coverage matrix:
      1. If the user resolved a conflict → use that chosen file.
      2. Otherwise, prefer .bm2 (has BMD results), then txt/csv, then xlsx.
      3. Collect .bm2 and .txt/.csv file paths for Java integration.
      4. Never merge a study workbook itself: its data comes as the pivots
         validation derived from it; a platform with only its workbook
         stops integration (ValueError).
      5. Call IntegrateProject (Java) to merge everything with native
         BMDExpress classes and Jackson NaN-safe serialization.
      6. Read back the JSON, add _meta and _category_lookup for the
         process-integrated endpoint.

    Args:
        dtxsid:            The DTXSID identifying this session.
        session_dir:       Absolute path to sessions/{dtxsid}/.
        fingerprints:      Dict mapping file_id → fingerprint dict.
        coverage_matrix:   Dict mapping platform → tier_name → list[file_id].
        precedence:        List of user conflict resolutions.
        test_article:      Dict with 'name', 'casrn', 'dsstox' for metadata.
        llm_generate_json: Callable for LLM metadata inference.
        approved_metadata: {experiment name: ExperimentDescription} the user
                           approved for an earlier integration of this pool.
                           Wins over inference for every experiment it names
                           (see _apply_approved_metadata).
        study_structure:   The StudyStructure (as a dict) the pool's study
                           workbooks describe; kept in _meta.study_structure.

    Returns:
        The merged BMDProject dict, also saved to sessions/{dtxsid}/integrated.json.
    """
    files_dir = os.path.join(session_dir, "files")
    out_path = os.path.join(session_dir, "integrated.json")

    # Collect user-resolved file IDs for quick lookup.
    # Keyed by the coverage matrix key (platform name or "gene_expression")
    # so we can match resolutions to the correct coverage matrix entry.
    resolved_file_ids: dict[str, str] = {}
    for entry in precedence:
        fid = entry.get("chosen_file_id", "")
        if not fid:
            continue
        fp = fingerprints.get(fid, {})
        # Determine the coverage matrix key for this file — same logic as
        # _build_coverage_matrix: gene_expression files use "gene_expression",
        # apical files use their platform name.
        fp_data_type = fp.get("data_type") if isinstance(fp, dict) else getattr(fp, "data_type", None)
        fp_platform = fp.get("platform") if isinstance(fp, dict) else getattr(fp, "platform", None)
        if fp_data_type == "gene_expression":
            resolved_file_ids["gene_expression"] = fid
        elif fp_platform:
            resolved_file_ids[fp_platform] = fid

    # --- Select files per platform ---
    # Coverage matrix keys are platform names (e.g., "Body Weight") or
    # "gene_expression".  Separate chosen files into lists for Java integration.
    bm2_paths: list[str] = []
    txt_paths: list[str] = []
    # The gene-expression .bm2 path, captured for the genomics sidecar (extracted
    # once here at integration so process-time never re-reads the raw upload).
    ge_bm2_path: str | None = None
    # Clinical observation CSVs bypass Java integration entirely —
    # they contain categorical findings (not numeric endpoints) and are
    # processed into incidence tables at report time instead.
    clinical_obs_files: list[str] = []
    source_files: dict[str, dict] = {}

    for platform_key, tiers in coverage_matrix.items():
        # Parse the compound key — "Body Weight|tox_study" → platform, data_type.
        # Gene expression uses plain "gene_expression" (no pipe).
        if "|" in platform_key:
            cm_platform, cm_data_type = platform_key.split("|", 1)
        elif platform_key == "gene_expression":
            cm_platform, cm_data_type = None, "gene_expression"
        else:
            cm_platform, cm_data_type = platform_key, None

        chosen_fid = None
        chosen_tier = None

        # 1. Check user conflict resolution
        if platform_key in resolved_file_ids:
            chosen_fid = resolved_file_ids[platform_key]
            fp = fingerprints.get(chosen_fid, {})
            chosen_tier = (
                fp.get("file_type") if isinstance(fp, dict)
                else getattr(fp, "file_type", None)
            )

        # 2. Auto-select by tier preference: bm2 > txt/csv > xlsx.
        # Include ALL files of the winning tier (e.g., both male and female
        # CSVs), not just the first — each sex is a separate file.
        chosen_fids: list[str] = []
        if not chosen_fid:
            best_priority = 999
            for tier_name, fids_raw in tiers.items():
                if fids_raw is None:
                    continue
                fids = fids_raw if isinstance(fids_raw, list) else [fids_raw]
                fids = [f for f in fids if f]
                priority = _TIER_PREFERENCE.get(tier_name, 999)
                if priority < best_priority and fids:
                    best_priority = priority
                    chosen_fids = fids
                    chosen_fid = fids[0]
                    chosen_tier = tier_name
        else:
            chosen_fids = [chosen_fid]

        if not chosen_fid:
            logger.warning("No file found for platform %s — skipping", platform_key)
            continue

        # Route ALL files of the winning tier to the appropriate list
        first_filename = None
        for fid in chosen_fids:
            fp = fingerprints.get(fid, {})
            filename = fp.get("filename") if isinstance(fp, dict) else getattr(fp, "filename", "")
            actual_file_type = (
                fp.get("file_type") if isinstance(fp, dict)
                else getattr(fp, "file_type", chosen_tier)
            )
            # Get data_type from the fingerprint for routing decisions
            fp_data_type = (
                fp.get("data_type") if isinstance(fp, dict)
                else getattr(fp, "data_type", None)
            )
            file_path = os.path.join(files_dir, filename) if filename else ""

            if not file_path or not os.path.exists(file_path):
                logger.warning("File not found for platform %s (id=%s) — skipping", platform_key, fid)
                continue

            if first_filename is None:
                first_filename = filename

            logger.info("Selected platform=%s from %s (%s)", platform_key, filename, actual_file_type)

            # Route to the appropriate list for Java integration
            if chosen_tier == "bm2" or actual_file_type == "bm2":
                bm2_paths.append(file_path)
                # Remember the gene-expression .bm2 so we can extract the genomics
                # sidecar below (mirrors how process-time locates it via the
                # gene_expression source file).
                if fp_data_type == "gene_expression" or platform_key == "gene_expression":
                    ge_bm2_path = file_path
            elif actual_file_type in ("txt", "csv") or chosen_tier == "txt_csv":
                # Gene expression txt/csv are raw matrices, not clinical pivots —
                # they can't be imported directly.  Skip them; gene expression
                # comes from the .bm2 tier via BMDExpress's analysis pipeline.
                if fp_data_type == "gene_expression":
                    continue
                # Clinical observation CSVs contain categorical findings (Normal,
                # Hunched, Discharge, etc.) — not numeric endpoints.  They have
                # no endpoint columns that survive _META_COLS filtering, so Java
                # integration would produce nothing.  Divert them to a separate
                # list for incidence table processing at report time.
                if cm_platform == "Clinical":
                    clinical_obs_files.append(file_path)
                    continue
                # All txt/csv files should be wide-format by now — long-format
                # CSVs were converted during fingerprint_and_store().
                txt_paths.append(file_path)
            elif actual_file_type == "xlsx" or chosen_tier == "xlsx":
                # A study workbook's data reaches integration as the pivots
                # validation derived from it (study_workbook_to_pool_files);
                # the workbook itself is never merged.  Chosen here means none
                # were derived (or validation set them aside): the platform's
                # data would be missing, so integration stops.
                raise ValueError(f"Platform {platform_key} has only its workbook {filename} "
                                 "and no pivot derived from it — validate the pool again")
            else:
                logger.warning("Unknown tier %s for platform %s — skipping", chosen_tier, platform_key)

        # Record source file metadata (use first file as representative)
        if first_filename:
            source_files[platform_key] = {
                "file_id": chosen_fids[0], "filename": first_filename,
                "tier": chosen_tier or actual_file_type,
                "file_count": len(chosen_fids),
            }

    # --- Call Java to merge everything ---
    # If the only files are clinical observation CSVs (categorical data),
    # there's nothing for Java to integrate.  But clinical obs can still
    # be processed into incidence tables — so we create a minimal shell.
    if not bm2_paths and not txt_paths:
        if not clinical_obs_files:
            logger.warning("No files to integrate for %s", dtxsid)
            return {}
        # Create a minimal BMDProject shell so the rest of the pipeline
        # has something to attach _meta to.  The doseResponseExperiments
        # list will be empty — only clinical obs incidence tables will
        # appear in the final report.
        logger.info("Only clinical obs files for %s — creating minimal shell", dtxsid)
        import json as _json
        with open(out_path, "w") as f:
            _json.dump({"doseResponseExperiments": []}, f)
    else:
        _run_integrate_java(bm2_paths, txt_paths, out_path)

    # --- Read back the Java-produced JSON ---
    # IntegrateProject writes valid JSON (NaN→null) via Jackson.
    # We add our metadata overlay (_meta, _category_lookup) for the
    # process-integrated endpoint.
    with open(out_path, "r") as f:
        integrated = json.load(f)

    # --- Collect xlsx animal rosters for all platforms ---
    # Even when bm2 wins the integration (for BMD results), the study xlsx
    # is authoritative for doses and animal roster.  Overlay this so
    # build_table_data() can use xlsx N counts and detect dead animals.
    xlsx_rosters = _collect_xlsx_rosters(coverage_matrix, fingerprints, files_dir)

    # Add provenance metadata
    integrated["_meta"] = {
        "dtxsid": dtxsid,
        "integrated_at": datetime.now(tz=timezone.utc).isoformat(),
        "source_files": source_files,
        "xlsx_rosters": xlsx_rosters,
        # Clinical observation CSV paths — bypassed Java integration because
        # they contain categorical findings, not numeric endpoints.  Processed
        # into incidence tables at report time by build_clinical_obs_tables().
        "clinical_obs_files": clinical_obs_files,
        # The study the workbooks describe (study_structure): its roster,
        # doses, design.  Empty when the pool has no study workbook.
        "study_structure": study_structure or {},
    }

    # --- Enrich source_files with per-platform experiment counts ---
    # The integrated JSON now has doseResponseExperiments from Java.
    # Match each experiment to a platform using bidirectional substring
    # matching: check if the normalized platform name is in the experiment
    # name, or if they share a long common prefix (handles abbreviations
    # like "tissue_conc" → "Tissue Concentration").
    all_experiments = integrated.get("doseResponseExperiments", [])
    if all_experiments and source_files:
        # Build normalized base platform → list of original keys mapping.
        # Multiple compound keys can share a base (e.g., "Hematology|tox_study"
        # and "Hematology|inferred" both normalize to "hematology").
        _plat_norm: dict[str, list[str]] = {}
        for plat_key in source_files:
            base = plat_key.split("|")[0] if "|" in plat_key else plat_key
            normalized = base.lower().replace(" ", "").replace("_", "")
            _plat_norm.setdefault(normalized, []).append(plat_key)

        # Count experiments per base platform
        base_counts: dict[str, int] = {}
        for exp in all_experiments:
            exp_name = (exp.get("name") or "").lower().replace("_", "")
            matched = False
            for norm_key in _plat_norm:
                if norm_key in exp_name:
                    base_counts[norm_key] = base_counts.get(norm_key, 0) + 1
                    matched = True
                    break
                # Common-prefix check for abbreviated experiment names
                # (e.g., "tissueconc" vs "tissueconcentration")
                prefix_len = 0
                for a, b in zip(norm_key, exp_name):
                    if a == b:
                        prefix_len += 1
                    else:
                        break
                if prefix_len >= min(6, len(norm_key)):
                    base_counts[norm_key] = base_counts.get(norm_key, 0) + 1
                    matched = True
                    break
            if not matched:
                # Check augmented ExperimentDescription metadata
                desc = exp.get("experimentDescription") or {}
                aug = desc.get("_augmented") or {}
                exp_platform = aug.get("platform", "")
                if exp_platform:
                    norm_aug = exp_platform.lower().replace(" ", "").replace("_", "")
                    if norm_aug in _plat_norm:
                        base_counts[norm_aug] = base_counts.get(norm_aug, 0) + 1

        # Apply counts to all compound keys sharing the same base platform
        for norm_key, count in base_counts.items():
            for orig_key in _plat_norm.get(norm_key, []):
                source_files[orig_key]["experiment_count"] = count

    # --- Build category lookup via native Java API ---
    # ExportCategories.java reads CategoryAnalysisResults directly from the
    # BMDProject — no DataCombinerService, no TSV.  This replaces the broken
    # TSV export path that crashed with IndexOutOfBoundsException.
    cat_results = integrated.get("categoryAnalysisResults", [])
    if cat_results:
        from .apical_report import export_categories, build_category_lookup

        # Collect all experiment names from the integrated data so
        # build_category_lookup can resolve BMDExpress pipeline suffixes
        # (e.g., "_williams_0.05_NOMTC_nofoldfilter") back to the raw
        # experiment names used by build_table_data().
        all_exp_names = [
            exp.get("name", "")
            for exp in integrated.get("doseResponseExperiments", [])
        ]

        merged_cat_lookup: dict[tuple[str, str], dict] = {}
        for bm2_path in bm2_paths:
            cat_json_path = os.path.join(
                session_dir, f"_cat_{os.path.basename(bm2_path)}.json",
            )
            try:
                categories_json = export_categories(bm2_path, cat_json_path)
                cat_lookup = build_category_lookup(
                    categories_json, experiment_names=all_exp_names,
                )
                merged_cat_lookup.update(cat_lookup)
            except Exception as e:
                logger.warning("Category export failed for %s: %s", bm2_path, e)
            finally:
                if os.path.exists(cat_json_path):
                    os.remove(cat_json_path)

        integrated["_category_lookup"] = {
            f"{k[0]}|{k[1]}": v
            for k, v in merged_cat_lookup.items()
        }
    else:
        integrated["_category_lookup"] = {}

    # --- ExperimentDescription metadata: the workbooks first (ADR-0032) ---
    # What the study workbooks state is set first and wins; the language model
    # infers only what is left; a person's approved metadata is laid over the
    # rest.  Each field's source is kept in _meta.metadata_provenance.
    all_experiments = integrated.get("doseResponseExperiments", [])
    provenance: dict[str, dict] = {}
    described = describe_from_structure(all_experiments, study_structure)
    apply_described(all_experiments, described, provenance)

    if test_article and llm_generate_json:
        before = {e["name"]: dict(e.get("experimentDescription") or {}) for e in all_experiments}
        descriptions = infer_experiment_metadata(
            experiments=all_experiments,
            source_files=source_files,
            test_article=test_article,
            llm_generate_json=llm_generate_json,
        )
        for line in workbook_disagreements(described, descriptions):
            logger.warning("Metadata inference disagrees with the study workbook — %s", line)
        attach_metadata(all_experiments, descriptions)
        record_provenance(all_experiments, before, provenance, "llm")

    if approved_metadata:
        _apply_approved_metadata(all_experiments, approved_metadata, provenance)
    integrated["_meta"]["metadata_provenance"] = provenance

    # --- Write _category_lookup to a separate sidecar file ---
    # The category lookup can be 10+ MB of JSON.  Keeping it out of
    # integrated.json makes session-restore loads ~5x faster (the summary
    # endpoint only needs _meta + experiment counts, not BMD statistics).
    # The lookup is loaded on demand by the process-integrated pipeline.
    cat_lookup_data = integrated.pop("_category_lookup", {})
    cat_lookup_path = os.path.join(session_dir, "_category_lookup.json")
    with open(cat_lookup_path, "w", encoding="utf-8") as f:
        json.dump(cat_lookup_data, f)

    # --- Extract the genomics sidecar (ADR-0016 Phase D) ---
    # Gene expression is the one platform whose report data used to be re-extracted
    # from the raw .bm2 at PROCESS time (violating "read from integrated + sidecars,
    # never raw uploads").  Extract it ONCE here — Java + the classpath are already
    # in use for the merge above — and persist the raw ExportGenomics JSON as a
    # sidecar the process step reads instead of the .bm2.  Fail-soft: a genomics
    # extraction failure must not break the merge (the report tolerates missing
    # genomics), so it's logged, not raised.
    if ge_bm2_path:
        from .apical_report import export_genomics
        genomics_sidecar_path = os.path.join(session_dir, "genomics.sidecar.json")
        try:
            export_genomics(ge_bm2_path, genomics_sidecar_path)
            logger.info("Wrote genomics sidecar: %s", genomics_sidecar_path)
        except Exception as e:
            logger.warning("Genomics sidecar extraction failed for %s: %s",
                           ge_bm2_path, e)
            # Don't leave a partial/stale file behind.
            if os.path.exists(genomics_sidecar_path):
                os.remove(genomics_sidecar_path)
        # ExportGenomics parses organ/sex from the experiment NAME; correct them
        # from the annotated metadata (and inherit a single-sex study's sex,
        # flagged in _meta.inferred) — see genomics_metadata.  Guarded on its own
        # so a reconcile failure never discards a good sidecar.
        try:
            from .genomics_metadata import reconcile_genomics_sidecar
            reconcile_genomics_sidecar(integrated, genomics_sidecar_path)
        except Exception as e:
            logger.warning("Genomics sidecar reconcile failed for %s: %s",
                           genomics_sidecar_path, e)

    # Re-write the JSON with our metadata additions (without _category_lookup)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(integrated, f, indent=2)

    # Re-attach for the in-memory return value so callers still see it
    integrated["_category_lookup"] = cat_lookup_data

    # --- Write enriched .bm2 file ---
    # Serialize the metadata-enriched BMDProject back to the canonical .bm2
    # format (Java ObjectOutputStream).  This closes the metadata loop:
    # the LLM inferred metadata, the user will approve it, and the .bm2
    # becomes the single source of truth — openable in BMDExpress 3 with
    # all ExperimentDescription fields pre-populated.
    #
    # The .bm2 is written alongside integrated.json in the session directory.
    # It can be re-exported on demand via export_integrated_bm2().
    bm2_out = os.path.join(session_dir, "integrated.bm2")
    try:
        export_integrated_bm2(out_path, bm2_out)
    except Exception as e:
        # Non-fatal: the JSON is the primary artifact; .bm2 is a convenience.
        logger.warning("Failed to write enriched .bm2: %s", e)

    logger.info(
        "Integration complete: %d experiments, %d BMD results, %d category results → %s",
        len(integrated.get("doseResponseExperiments", [])),
        len(integrated.get("bMDResult", [])),
        len(integrated.get("categoryAnalysisResults", [])),
        out_path,
    )

    return integrated


def subset_bm2(bm2_path: str, out_path: str, token: str) -> str:
    """
    Write a copy of a BMDExpress project keeping only the experiments whose
    name contains ``token`` (case-insensitive), with their analyses.

    NIEHS-07 … 10 publish one shared project holding four chemicals'
    experiments; a report must ingest only its own.  SubsetBm2.java edits the
    deserialized object graph, so shared objects (chip, probes) stay intact.

    Raises:
        RuntimeError: when no experiment matches or Java fails.
    """
    classpath = build_classpath()
    result = subprocess.run(
        ["java", "-cp", classpath, "SubsetBm2", bm2_path, out_path, token],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"SubsetBm2 failed (exit {result.returncode}): {result.stderr[-2000:]}")
    logger.info("%s", result.stdout.strip().splitlines()[-1] if result.stdout.strip() else out_path)
    return out_path


def export_integrated_bm2(json_path: str, bm2_path: str) -> str:
    """
    Convert a metadata-enriched integrated.json back to .bm2 format.

    Uses JsonToBm2.java to deserialize the Jackson-annotated JSON into a
    BMDProject object graph, then write it via ObjectOutputStream.  The
    resulting .bm2 file is a standard BMDExpress 3 project file that can
    be opened natively — with ExperimentDescription metadata pre-filled.

    Args:
        json_path: Path to the integrated.json (with @type/@ref annotations).
        bm2_path:  Path to write the output .bm2 file.

    Returns:
        The bm2_path on success.

    Raises:
        RuntimeError: If the Java process exits with a non-zero code.
    """
    classpath = build_classpath()
    cmd = [
        "java", "-cp", classpath,
        "JsonToBm2", json_path, bm2_path,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"JsonToBm2 failed (exit {result.returncode}): {result.stderr}"
        )
    logger.info("Wrote enriched .bm2: %s", bm2_path)
    return bm2_path
