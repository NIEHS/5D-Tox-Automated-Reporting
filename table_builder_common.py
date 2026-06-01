"""
table_builder_common.py — Shared utilities for NIEHS table builders.

All rule-based table builders (body_weight_table.py, clinical_pathology_table.py,
organ_weight_table.py, tissue_concentration_table.py) use common functions for:
  - Dose key formatting (matching JavaScript's String(number))
  - Mean ± SE computation and display formatting
  - Adaptive decimal place selection by value magnitude
  - Sidecar JSON loading and discovery
  - N-row construction with attrition markers
  - Shared footnote constants (BMD definition, stat method)

These were extracted from body_weight_table.py to avoid duplication across
the per-platform builders.  body_weight_table.py now imports from here too.
"""

from __future__ import annotations

import json
import math
import os


# ---------------------------------------------------------------------------
# Constants — shared NIEHS table text
# ---------------------------------------------------------------------------

# The BMD/BMDL definition line that appears ABOVE the lettered footnotes.
# It's not lettered — it's a standalone definition paragraph below the
# table rule, before footnote (a).  Used by all apical tables that show
# BMD/BMDL columns.
BMD_DEFINITION = (
    "BMD\u2081Std = benchmark dose corresponding to a benchmark response "
    "set to one standard deviation from the mean; "
    "BMDL\u2081Std = benchmark dose lower confidence limit corresponding "
    "to a benchmark response set to one standard deviation from the mean; "
    "NA = not applicable; ND = not determined."
)

# Fixed footnote about the statistical method used for NTP studies.
# Lettered as (b) in most tables (body weight, organ weight, clinical path).
FOOTNOTE_STAT_METHOD = (
    "Statistical analysis performed by the Jonckheere (trend) "
    "and Williams or Dunnett (pairwise) tests."
)

# Significance-marker text.  The `*` / `**` markers themselves are baked
# into the mean ± SE cell strings upstream by bmdx-pipe's build_table_data;
# these two strings are the legend that explains them.  Consolidated here
# (the per-builder copies in clinical_pathology_table.py and
# organ_weight_table.py drifted into three slightly different wordings).
# No test name is mentioned — the specific test (Williams/Dunnett vs
# Shirley/Dunn) is already named in each table's statistical-method
# footnote, and clinical pathology does not use Dunnett's.
SIGNIFICANCE_MARKER_LEGEND = (
    "*Statistically significant at p ≤ 0.05; **p ≤ 0.01."
)

# The semantics paragraph: what a marker on a dosed-group cell means
# versus a marker on the vehicle-control cell.  Applies to every apical
# table that carries `*` / `**` markers.
SIGNIFICANCE_EXPLANATION = (
    "Statistical significance for a dosed group indicates a significant "
    "pairwise test compared to the vehicle control group. Statistical "
    "significance for the vehicle control group indicates a significant "
    "trend test."
)


# ---------------------------------------------------------------------------
# Typed footnote model
# ---------------------------------------------------------------------------
# Apical-table footnotes used to be a bare `list[str]`, lettered a/b/c... by
# position in whichever renderer happened to walk the list — with the cell
# superscript markers lettered by a *separate* counter inside the builder.
# Two independent counters that only lined up by luck, plus a `*`/`**`
# significance legend that was computed and then never rendered at all.
#
# This model replaces that.  A footnote is now a typed record:
#
#   {"kind": "legend",     "text": str}
#       The `*`/`**` significance legend / explanation.  Rendered as an
#       unlettered block above the lettered footnotes.  No letter, no marker.
#
#   {"kind": "definition", "text": str}
#       An abbreviation / BMD definition paragraph.  Unlettered, rendered
#       above the lettered footnotes.
#
#   {"kind": "lettered",   "text": str, "id": str,
#    "marker": {"target": "header" | "cells" | "none"},
#    "letter": str}        # <- assigned by finalize_footnotes, not the builder
#       A lettered footnote.  `id` is a stable identity (NOT the letter);
#       `marker.target` declares where the letter also appears:
#         "header" — superscripted on the table's first-column header
#         "cells"  — superscripted on specific row cells; the rows name
#                    this footnote by `id` via their `marker_refs` dict
#         "none"   — appears only in the footnote list, no in-table marker
#
# A row that hosts a cell marker carries `marker_refs: {dose_key: footnote_id}`
# — the stable id, never a letter.  `finalize_footnotes` is the single place
# that turns ids into letters: it assigns the letters and derives each row's
# `markers: {dose_key: letter}` from `marker_refs`.  Because it always
# re-derives from `marker_refs`, it is idempotent and safe to run again after
# more footnotes are merged in downstream (see report_data.py).

def legend_footnote(text: str) -> dict:
    """Build a `legend` footnote record (unlettered, e.g. the `*`/`**` key)."""
    return {"kind": "legend", "text": text}


def definition_footnote(text: str) -> dict:
    """Build a `definition` footnote record (unlettered abbreviation paragraph)."""
    return {"kind": "definition", "text": text}


def lettered_footnote(text: str, footnote_id: str, target: str = "none") -> dict:
    """
    Build a `lettered` footnote record.

    Args:
        text:        The footnote sentence.
        footnote_id: A stable identity string (e.g. "data_format",
                     "attrition_333_male").  Rows reference this id in their
                     `marker_refs`; it is NOT the displayed letter.
        target:      Where the assigned letter also appears in the table —
                     "header", "cells", or "none" (default).
    """
    if target not in ("header", "cells", "none"):
        raise ValueError(
            f"lettered_footnote target must be header/cells/none, got {target!r}"
        )
    return {
        "kind": "lettered",
        "text": text,
        "id": footnote_id,
        "marker": {"target": target},
    }


def finalize_footnotes(
    footnotes: list[dict],
    serialized_rows: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """
    Assign letters to lettered footnotes and derive row cell markers.

    This is the single lettering authority for the typed footnote model.
    It walks `footnotes` in order: every `kind == "lettered"` record gets
    the next sequential letter (a, b, c, ...) written into `fn["letter"]`;
    `legend` and `definition` records are skipped (they carry no letter).

    It then walks `serialized_rows` ({sex: [row, ...]}) and, for every row
    carrying a `marker_refs` dict ({dose_key: footnote_id}), derives a
    fresh `markers` dict ({dose_key: letter}) by resolving each id through
    the letter map.  `marker_refs` is the stable, builder-owned source of
    truth; `markers` is always rebuilt from it — so this function is
    idempotent and may be called again after additional footnotes are
    merged into the list (report_data.py does exactly that).

    Args:
        footnotes:       The typed footnote list.  Mutated in place — each
                         lettered record gains a `letter` field.
        serialized_rows: {sex: [row dict, ...]}.  Rows with `marker_refs`
                         gain/refresh a derived `markers` dict.  May be
                         None for footnote lists that have no cell markers.

    Returns:
        The same `footnotes` list (mutated), for call-site convenience.
    """
    # Pass 1: assign letters to lettered footnotes, build id -> letter map.
    letter_ord = ord("a")
    id_to_letter: dict[str, str] = {}
    for fn in footnotes:
        if not isinstance(fn, dict) or fn.get("kind") != "lettered":
            continue
        letter = chr(letter_ord)
        letter_ord += 1
        fn["letter"] = letter
        fid = fn.get("id")
        if fid:
            id_to_letter[fid] = letter

    # Pass 2: re-derive each row's `markers` dict from its stable
    # `marker_refs`.  A ref pointing at an unknown id (e.g. a footnote that
    # was removed) is dropped rather than rendered as a dangling marker.
    for rows in (serialized_rows or {}).values():
        for row in rows:
            refs = row.get("marker_refs")
            if not refs:
                continue
            row["markers"] = {
                dose_key: id_to_letter[fid]
                for dose_key, fid in refs.items()
                if fid in id_to_letter
            }

    return footnotes


# ---------------------------------------------------------------------------
# Shared apical missing-animal pipeline
# ---------------------------------------------------------------------------
# Apical tables built from sidecar data (clinical pathology, organ weight)
# share the same missing-animal story, so the detection and footnote-building
# live here rather than being copied per builder:
#
#   detect_core_animal_availability  — scans a sidecar's Core Animals and
#       splits each dose group into "has usable data" vs "all-NA"; also
#       reports the per-dose total.
#   build_sample_availability_footnotes — turns the all-NA animals into
#       deduped-by-count "sample not received" footnotes (one footnote per
#       distinct count, its marker on every affected n-row cell).
#   build_attrition_footnote — turns whole-dose-groups-with-no-data into a
#       single "all rats found dead" footnote.
#
# Body weight does NOT use this pipeline: its missing-animal model is
# death-based (per-animal terminal-day tracking), not all-NA, so it keeps
# its own attrition logic in body_weight_table.py.

def detect_core_animal_availability(
    sidecar_data: dict[str, dict],
) -> tuple[
    dict[str, dict[float, int]],
    dict[str, dict[float, int]],
    dict[str, dict[float, list[str]]],
]:
    """
    Scan sidecar Core Animals for sample availability, per sex and dose.

    Biosampling Animals are excluded — they are a separate cohort and
    never count toward an apical table's N.  A Core Animal is "available"
    if it has at least one non-empty, non-"NA" observation value; one
    whose every observation is empty/NA is a missing-sample animal
    (sample not received, clotted, insufficient volume, etc.).

    Args:
        sidecar_data: {sex: parsed-sidecar-dict}, as returned by
                      load_sidecar() per sex.

    Returns:
        A 3-tuple of per-sex, per-dose dicts:
          - core_n_by_sex_dose:     {sex: {dose: count with usable data}}
          - total_core_by_sex_dose: {sex: {dose: total Core Animals}}
          - missing_sample_animals: {sex: {dose: [animal_id, ...] with no data}}
    """
    core_n_by_sex_dose: dict[str, dict[float, int]] = {}
    total_core_by_sex_dose: dict[str, dict[float, int]] = {}
    missing_sample_animals: dict[str, dict[float, list[str]]] = {}

    for sex, sc in sidecar_data.items():
        dose_with_data: dict[float, set[str]] = {}
        dose_all: dict[float, set[str]] = {}
        dose_missing: dict[float, list[str]] = {}

        for aid, rec in sc.get("animals", {}).items():
            selection = rec.get("selection", "Unknown")
            # Include Core Animals and animals with unknown selection.
            # "Unknown" means the CSV had no Selection column — those are
            # implicitly Core Animals (e.g. a Hormones CSV with no
            # Biosampling cohort provides no Selection column).
            if "biosampling" in selection.lower():
                continue
            dose = rec["dose"]
            dose_all.setdefault(dose, set()).add(aid)

            has_data = any(
                obs.get("value") and obs["value"].strip()
                and obs["value"].strip().upper() != "NA"
                for obs in rec.get("observations", [])
            )
            if has_data:
                dose_with_data.setdefault(dose, set()).add(aid)
            else:
                dose_missing.setdefault(dose, []).append(aid)

        core_n_by_sex_dose[sex] = {
            dose: len(aids) for dose, aids in dose_with_data.items()
        }
        total_core_by_sex_dose[sex] = {
            dose: len(aids) for dose, aids in dose_all.items()
        }
        missing_sample_animals[sex] = dose_missing

    return core_n_by_sex_dose, total_core_by_sex_dose, missing_sample_animals


def build_sample_availability_footnotes(
    missing_sample_animals: dict[str, dict[float, list[str]]],
    total_core_by_sex_dose: dict[str, dict[float, int]],
    sorted_doses: list[float],
) -> tuple[list[dict], dict[str, dict[float, str]]]:
    """
    Build deduped "sample not received" footnotes from all-NA Core Animals.

    One footnote per DISTINCT missing-sample COUNT — NOT per (sex, dose).
    "One sample ... was not received" / "2 samples ... were not received"
    each appear once; the footnote's letter is superscripted on every
    n-row cell that has that count.  (A per-(sex, dose) footnote — the old
    behavior — produced a dozen near-duplicates for a dense table like
    hematology.)  Footnotes are created in first-appearance order — Male
    before Female, lowest dose first — so the first marker the reader
    meets is "c".

    A dose group where EVERY Core Animal is missing data is skipped here:
    that is whole-group attrition, handled by build_attrition_footnote(),
    not a sample-availability note.

    Args:
        missing_sample_animals: {sex: {dose: [animal_id, ...]}} from
                                detect_core_animal_availability().
        total_core_by_sex_dose: {sex: {dose: total Core Animals}} — used
                                to tell partial missing from whole-group
                                attrition.
        sorted_doses:           Ordered dose list (column order).

    Returns:
        (footnote_records, n_row_marker_refs) where footnote_records is a
        list of typed `lettered` footnote dicts (target "cells") and
        n_row_marker_refs is {sex: {dose: footnote_id}} for the caller to
        merge onto its n-rows before finalize_footnotes runs.
    """
    footnotes: list[dict] = []
    n_row_marker_refs: dict[str, dict[float, str]] = {}
    fid_by_count: dict[int, str] = {}

    for sex in ("Male", "Female"):
        missing = missing_sample_animals.get(sex, {})
        totals = total_core_by_sex_dose.get(sex, {})
        n_row_marker_refs.setdefault(sex, {})
        for dose in sorted_doses:
            missing_at_dose = missing.get(dose, [])
            if not missing_at_dose:
                continue
            count = len(missing_at_dose)
            # Whole-group attrition (every Core Animal missing) belongs to
            # build_attrition_footnote, not here — skip it so we don't emit
            # an orphaned "N samples not received" note for a dead group.
            if count >= totals.get(dose, 0) > 0:
                continue
            fid = fid_by_count.get(count)
            if fid is None:
                # First (sex, dose) seen with this count — emit the footnote.
                # "dose group(s)" because one footnote can span several.
                fid = f"sample_avail_count_{count}"
                if count == 1:
                    text = (
                        "One sample in the indicated dose group(s) was "
                        "not received."
                    )
                else:
                    text = (
                        f"{count} samples in the indicated dose group(s) "
                        f"were not received."
                    )
                footnotes.append(lettered_footnote(text, fid, target="cells"))
                fid_by_count[count] = fid
            n_row_marker_refs[sex][dose] = fid

    return footnotes, n_row_marker_refs


def build_attrition_footnote(
    total_core_by_sex_dose: dict[str, dict[float, int]],
    core_n_by_sex_dose: dict[str, dict[float, int]],
    sorted_doses: list[float],
    dose_unit: str = "mg/kg",
) -> tuple[dict | None, dict[str, dict[float, str]]]:
    """
    Build a single attrition footnote for whole dose groups with no data.

    A (sex, dose) group is "attrited" when it had Core Animals
    (total > 0) but none with usable data (core_n == 0) — every animal
    died or was moribund before the sample could be collected.  One
    footnote covers every such group; the affected dose groups are named
    in the text (derived, not hard-coded), and the footnote's letter is
    superscripted on the first attrited (sex, dose) n-row cell.

    Args:
        total_core_by_sex_dose: {sex: {dose: total Core Animals}}.
        core_n_by_sex_dose:     {sex: {dose: count with usable data}}.
        sorted_doses:           Ordered dose list.
        dose_unit:              Dose unit string for the footnote text.

    Returns:
        (footnote_record_or_None, n_row_marker_refs).  The record is a
        typed `lettered` footnote dict (target "cells"), or None when no
        whole-group attrition was found.  n_row_marker_refs is
        {sex: {dose: "attrition"}} for the caller to merge.
    """
    dead: list[tuple[str, float]] = []
    for sex in ("Male", "Female"):
        total = total_core_by_sex_dose.get(sex, {})
        with_data = core_n_by_sex_dose.get(sex, {})
        for dose in sorted_doses:
            if total.get(dose, 0) > 0 and with_data.get(dose, 0) == 0:
                dead.append((sex, dose))

    if not dead:
        return None, {}

    dead_doses = sorted({d for _, d in dead})
    dead_sexes = sorted({s for s, _ in dead})
    dose_str = " and ".join(
        format_dose_label(d, dose_unit) for d in dead_doses
    )
    sex_str = (
        "male and female" if len(dead_sexes) == 2
        else dead_sexes[0].lower()
    )
    text = (
        f"All {sex_str} {dose_str} {dose_unit} rats were found dead "
        f"or moribund and euthanized by study day 1."
    )
    # Marker on the first attrited (sex, dose) cell — the footnote text
    # names every affected group, so one marker introduces it.
    first_sex, first_dose = dead[0]
    n_row_marker_refs = {first_sex: {first_dose: "attrition"}}
    return (
        lettered_footnote(text, "attrition", target="cells"),
        n_row_marker_refs,
    )


# ---------------------------------------------------------------------------
# Dose key formatting
# ---------------------------------------------------------------------------

def js_dose_key(dose: float) -> str:
    """
    Format a dose float as a string matching JavaScript's String(number).

    JavaScript's String(0.15) produces "0.15", String(0.0) produces "0",
    String(1000.0) produces "1000".  Python's str(0.0) produces "0.0".
    We need consistent keys between Python serialization and JavaScript
    object property access.

    Args:
        dose: A numeric dose value (e.g., 0.0, 0.3, 1.0, 10.0).

    Returns:
        String representation matching JavaScript's String(number) behavior.
    """
    if dose == int(dose):
        return str(int(dose))
    return str(dose)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def mean_se(values: list[float]) -> tuple[float, float]:
    """
    Compute mean and standard error of the mean for a list of values.

    SE = SD / sqrt(N), where SD uses population-corrected (N-1) denominator
    (Bessel's correction), matching the standard biostatistical convention.

    Args:
        values: List of numeric values.  Empty list returns (0.0, 0.0).

    Returns:
        (mean, se) tuple.  If N < 2, SE is 0.0 (no variability estimable
        from a single observation).
    """
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    mean_val = sum(values) / n
    if n < 2:
        return (mean_val, 0.0)
    variance = sum((v - mean_val) ** 2 for v in values) / (n - 1)
    se_val = math.sqrt(variance) / math.sqrt(n)
    return (mean_val, se_val)


def format_mean_se(mean: float, se: float, decimals: int = 1) -> str:
    """
    Format mean ± SE as a display string matching NIEHS reference style.

    Uses non-breaking spaces (U+00A0) around the ± (U+00B1) so the value
    never wraps across lines in the PDF table — "296.5 ± 4.4" stays on
    one line regardless of column width.

    Args:
        mean:     The arithmetic mean.
        se:       The standard error of the mean.
        decimals: Number of decimal places (default 1).

    Returns:
        Formatted string like "296.5\u00a0±\u00a04.4".
    """
    return f"{mean:.{decimals}f}\u00a0\u00b1\u00a0{se:.{decimals}f}"


def adaptive_decimals(*values: float) -> int:
    """
    Choose decimal places by value magnitude for NIEHS table display.

    The NIEHS reference uses different decimal precision depending on the
    measurement scale:
      - Large values (≥100): 1 decimal (e.g., body weight "296.5 ± 4.4")
      - Medium values (≥1):  2 decimals (e.g., organ weight "1.06 ± 0.03")
      - Small values (≥0.01): 3 decimals (e.g., hormone "0.123 ± 0.012")
      - Very small (<0.01):  4 decimals

    Args:
        *values: One or more representative values (typically means) to
                 determine the appropriate scale.

    Returns:
        Number of decimal places to use for formatting.
    """
    # Use the maximum absolute value to determine scale
    max_val = max(abs(v) for v in values) if values else 0
    if max_val >= 100:
        return 1
    elif max_val >= 1:
        return 2
    elif max_val >= 0.01:
        return 3
    else:
        return 4


# ---------------------------------------------------------------------------
# Display precision (the configurable rounding "knob")
# ---------------------------------------------------------------------------
# How many digits after the decimal point a raw numeric value is rounded to
# when shown in a report table.  This is the single place the report's
# configurer changes display precision — it is a DISPLAY concern only.  We
# round at render time and never mutate the underlying data, so changing this
# value and re-rendering is enough; no pipeline re-run is needed and the full-
# precision number is always preserved upstream.
#
# Why this exists: some numbers reach the tables as raw modeling-step floats
# carrying ~17 digits of IEEE floating-point noise (e.g. a gene BMD of
# 0.05773500056931743).  Those extra digits are not measured precision — the
# source data has no inherent precision at that scale — so they only make
# columns needlessly wide.  Rounding them for display loses nothing real.
#
# Default is 2; a deployment that wants more or fewer digits overrides it
# (and per-call `decimals=` lets a specific column opt out).
DISPLAY_DECIMALS = 2


def format_display_number(value, decimals: int = DISPLAY_DECIMALS) -> str:
    """
    Round a single numeric value to `decimals` places for table display.

    - None  -> the em-dash placeholder "—" (matches the table convention for
      "no value").
    - Non-numeric input (an already-formatted string, a label, "—") is
      returned unchanged, so this is safe to call on any cell value.
    - A number (int / float / numeric string) is rendered with exactly
      `decimals` digits after the decimal point, e.g. with the default of 2:
      0.05773500056931743 -> "0.06", 1.388534135554733 -> "1.39", 19.85 ->
      "19.85".  Fixed (not stripped) decimals keep a numeric column visually
      aligned.

    `decimals` defaults to the module-level DISPLAY_DECIMALS knob; pass an
    explicit value to override the precision for one call.
    """
    if value is None:
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        # Already a string label / placeholder / pre-formatted value.
        return str(value)
    return f"{num:.{decimals}f}"


# ---------------------------------------------------------------------------
# Sidecar loading and discovery
# ---------------------------------------------------------------------------

def load_sidecar(path: str) -> dict:
    """
    Load a sidecar JSON file written by tox_study_csv_to_pivot_txt().

    The sidecar captures per-animal metadata that the wide-format pivot
    discards: Selection, observation day, terminal flag, and raw values.

    Args:
        path: Absolute path to the .sidecar.json file.

    Returns:
        Parsed dict: {source, platform, sex, animals: {aid: {dose, selection, observations}}}.

    Raises:
        FileNotFoundError: If the sidecar doesn't exist.
        json.JSONDecodeError: If the file isn't valid JSON.
    """
    with open(path, "r") as f:
        return json.load(f)


def find_sidecar_paths(session_dir: str, platform: str) -> dict[str, str]:
    """
    Scan a session's files/ directory for sidecar JSON files matching a platform.

    Sidecar files are named like `body_weight_truth_male.sidecar.json` and
    are written by tox_study_csv_to_pivot_txt() alongside the pivot txt.

    Args:
        session_dir: Absolute path to the session directory (e.g.,
                     sessions/DTXSID50469320/).
        platform:    The platform name to match (e.g., "Body Weight",
                     "Organ Weight", "Clinical Chemistry").

    Returns:
        {"Male": "/path/to/male.sidecar.json", "Female": "/path/to/female.sidecar.json"}
        Only present sexes are included.  Empty dict if no sidecars found.
    """
    files_dir = os.path.join(session_dir, "files")
    if not os.path.isdir(files_dir):
        return {}

    result: dict[str, str] = {}
    for fname in os.listdir(files_dir):
        if not fname.endswith(".sidecar.json"):
            continue
        sc_path = os.path.join(files_dir, fname)
        try:
            with open(sc_path, "r") as f:
                sc = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        # Only match sidecars for the requested platform
        if sc.get("platform") != platform:
            continue

        sex = sc.get("sex", "Unknown")
        if sex in ("Male", "Female"):
            result[sex] = sc_path

    return result


# ---------------------------------------------------------------------------
# N-row builder
# ---------------------------------------------------------------------------

def build_n_row(
    animals_by_dose: dict[float, list],
    sorted_doses: list[float],
    marker_refs: dict[float, str] | None = None,
) -> dict:
    """
    Build an n-row dict showing sample sizes per dose group.

    The n-row is the first data row in every NIEHS table, showing how many
    animals contributed to each dose group's statistics.  It has BMD/BMDL
    set to "NA" (not applicable — sample size is not a dose-response endpoint).

    Args:
        animals_by_dose: {dose: [list of animal values/IDs]} — the length
                         of each list is the N for that dose.
        sorted_doses:    Ordered list of dose values for column layout.
        marker_refs:     Optional {dose: footnote_id} mapping — the stable
                         footnote IDs whose letters should be superscripted
                         on this n-row's cells (e.g. an attrition or
                         sample-availability footnote).  finalize_footnotes
                         later resolves these ids into the displayed
                         `markers` dict; see the typed footnote model above.

    Returns:
        Row dict with: label="n", doses, values (N per dose), marker_refs
        (only when given), bmd="NA", bmdl="NA", is_n_row=True.
    """
    n_vals: dict[str, str] = {}
    refs: dict[str, str] = {}

    for dose in sorted_doses:
        dk = js_dose_key(dose)
        n = len(animals_by_dose.get(dose, []))
        n_vals[dk] = str(n) if n > 0 else "\u2013"

        ref = (marker_refs or {}).get(dose)
        if ref:
            refs[dk] = ref

    row = {
        "label": "n",
        "doses": sorted_doses,
        "values": n_vals,
        "bmd": "NA",
        "bmdl": "NA",
        "is_n_row": True,
    }
    if refs:
        row["marker_refs"] = refs

    return row


# ---------------------------------------------------------------------------
# BMD/BMDL display helpers
# ---------------------------------------------------------------------------

def bmd_display_from_stats(
    ntp_stats_row,
    responsive: bool | None = None,
) -> tuple[str, str]:
    """
    Apply NIEHS business rules to determine BMD/BMDL cell text from NTP stats.

    Rules:
        - If the endpoint is NOT responsive (Jonckheere trend AND Dunnett
          pairwise not both significant): "ND" (not determined).
        - If responsive AND BMDExpress produced a result: show numeric value.
        - If responsive BUT modeling failed: "ND".

    Args:
        ntp_stats_row:  A TableRow object with bmd_str, bmdl_str, responsive.
        responsive:     Override for responsiveness check (if None, uses
                        ntp_stats_row.responsive).

    Returns:
        (bmd_text, bmdl_text) tuple of display strings.
    """
    is_responsive = responsive if responsive is not None else getattr(ntp_stats_row, "responsive", False)

    if not is_responsive:
        return ("ND", "ND")

    bmd = getattr(ntp_stats_row, "bmd_str", None)
    bmdl = getattr(ntp_stats_row, "bmdl_str", None)
    bmd = bmd if bmd and bmd != "\u2014" else "ND"
    bmdl = bmdl if bmdl and bmdl != "\u2014" else "ND"
    return (bmd, bmdl)


# Sentinels the BMD column uses for "no real modeled value", across the
# apical builders: "\u2014" \u2014 endpoint not modeled by BMDExpress (clinical
# pathology); "ND" \u2014 not determined (gate didn't pass / modeling failed);
# "NA" \u2014 not applicable (the n-row); "" \u2014 empty.
_NON_REPORTABLE_BMD = {"\u2014", "ND", "NA", ""}


def is_reportable_bmd(bmd_text) -> bool:
    """
    True when a BMD cell holds a real modeled value \u2014 a number, or a
    BMDExpress status code (NVM, UREP, <LNZD/3) \u2014 rather than a
    "nothing here" sentinel.

    This is the `reportable` half of the row-emphasis rule the apical
    table builders share: a row is emphasized (bold) when it passed the
    NTP responsive gate OR its BMD column is reportable.  Defined here so
    all three builders test it the same way instead of each re-deriving
    the sentinel set.
    """
    if bmd_text is None:
        return False
    return str(bmd_text).strip() not in _NON_REPORTABLE_BMD


# ---------------------------------------------------------------------------
# Dose label formatting
# ---------------------------------------------------------------------------

def format_dose_label(dose: float, unit: str = "mg/kg") -> str:
    """
    Format a dose value for display in footnotes and captions.

    Drops trailing .0 for whole numbers and adds thousands separators.

    Args:
        dose: Numeric dose value.
        unit: Dose unit string (not appended — caller adds if needed).

    Returns:
        Formatted dose string like "333", "1,000", "0.15".
    """
    if dose == int(dose):
        return f"{int(dose):,}"
    return str(dose)
