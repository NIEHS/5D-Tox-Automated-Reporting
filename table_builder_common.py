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

# Significance marker explanations — the NIEHS reference includes these
# as superscript legends in the table or as a footnote.
SIGNIFICANCE_LEGEND = (
    "* Statistically significant (p ≤ 0.05) by Dunnett's test; "
    "** p ≤ 0.01."
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
    attrition_markers: dict[float, str] | None = None,
) -> dict:
    """
    Build an n-row dict showing sample sizes per dose group.

    The n-row is the first data row in every NIEHS table, showing how many
    animals contributed to each dose group's statistics.  It has BMD/BMDL
    set to "NA" (not applicable — sample size is not a dose-response endpoint).

    Args:
        animals_by_dose:   {dose: [list of animal values/IDs]} — the length
                           of each list is the N for that dose.
        sorted_doses:      Ordered list of dose values for column layout.
        attrition_markers: Optional {dose: "c"} mapping for superscript
                           footnote markers on N cells where animals died.

    Returns:
        Row dict with: label="n", doses, values (N per dose), markers,
        bmd="NA", bmdl="NA", is_n_row=True.
    """
    if attrition_markers is None:
        attrition_markers = {}

    n_vals: dict[str, str] = {}
    markers: dict[str, str] = {}

    for dose in sorted_doses:
        dk = js_dose_key(dose)
        n = len(animals_by_dose.get(dose, []))
        n_vals[dk] = str(n) if n > 0 else "\u2013"

        marker = attrition_markers.get(dose)
        if marker:
            markers[dk] = marker

    row = {
        "label": "n",
        "doses": sorted_doses,
        "values": n_vals,
        "bmd": "NA",
        "bmdl": "NA",
        "is_n_row": True,
    }
    if markers:
        row["markers"] = markers

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
