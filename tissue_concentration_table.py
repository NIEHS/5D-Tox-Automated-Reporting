"""
tissue_concentration_table.py — Build NIEHS Table 7 (Tissue Concentration).

Produces the pharmacokinetic plasma concentration table:

    Table 7. Summary of Plasma Concentration Data for Male and Female Rats
    Administered {compound} for Five Days

This table is fundamentally different from all other NIEHS tables:
  - Only Biosampling Animals (opposite of all other tables which use Core)
  - Only dose groups that have biosampling animals (typically 2 of 10 doses)
  - No BMD/BMDL columns — not a dose-response analysis
  - No NTP stats or significance markers
  - Rows = timepoints (e.g., "2 h postdose", "24 h postdose")
  - Columns = dose groups
  - LOQ handling: when a value is below the limit of quantification,
    substitute LOQ/2 for statistical computation

Structure:
    Columns: Timepoint | dose₁ | dose₂ | ...
    Per sex:
        n           — biosampling animals per dose
        2 h postdose — mean ± SE of plasma concentration
        24 h postdose — mean ± SE of plasma concentration

    Values are in ng/mL (or whatever the concentration unit is).

The sidecar provides raw per-animal concentration values and LOQ data.
No NTP stats are used — this is purely descriptive statistics.
"""

from __future__ import annotations

import re

from table_builder_common import (
    js_dose_key,
    mean_se,
    format_mean_se,
    adaptive_decimals,
    load_sidecar,
    find_sidecar_paths,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAPTION_TEMPLATE = (
    "Summary of Plasma Concentration Data for Male and Female Rats "
    "Administered {compound} for Five Days"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_timepoint(endpoint_name: str) -> str | None:
    """
    Extract the timepoint label from a tissue concentration endpoint name.

    NTP endpoint names follow the pattern:
        "Plasma {N} Hour {Chemical} Concentration"
    We extract "{N} h postdose" as the display label.

    Also filters out LOQ columns (endpoint names ending in "LOQ").

    Args:
        endpoint_name: Full endpoint name from the CSV/sidecar.

    Returns:
        Timepoint label like "2 h postdose" or None if this is an LOQ column
        or doesn't match the expected pattern.
    """
    # Skip LOQ columns — they contain detection limit values, not measurements
    if endpoint_name.strip().upper().endswith("LOQ"):
        return None

    # Match "Plasma {N} Hour" pattern (case-insensitive)
    m = re.search(r"Plasma\s+(\d+)\s+Hour", endpoint_name, re.IGNORECASE)
    if m:
        hours = m.group(1)
        return f"{hours} h postdose"

    # Fallback: use the endpoint name as-is if it contains "Concentration"
    if "Concentration" in endpoint_name:
        return endpoint_name

    return None


def _find_loq_value(
    observations: list[dict],
    endpoint_name: str,
    day: str | None = None,
) -> float | None:
    """
    Find the LOQ value for a given concentration endpoint from sidecar observations.

    LOQ columns are named like the concentration column but ending in "LOQ":
        "Plasma 2 Hour ... Concentration" → "Plasma 2 Hour ... LOQ"

    When day is provided, only LOQ observations from the same study day are
    considered.  This prevents cross-day LOQ substitution: a null 2h concentration
    on SD5 should NOT be substituted with the LOQ from SD4 (the measurement
    simply wasn't taken on that day).

    Args:
        observations:  The animal's observation list from the sidecar.
        endpoint_name: The concentration endpoint name.
        day:           Optional study day to filter by (e.g., "SD4").

    Returns:
        The LOQ float value, or None if not found.
    """
    # Derive LOQ column name: replace "Concentration" with "LOQ"
    loq_name = endpoint_name.replace("Concentration", "LOQ").strip()

    for obs in observations:
        if obs.get("endpoint", "").strip() == loq_name:
            # Filter by study day if specified
            if day is not None and obs.get("day") != day:
                continue
            val_str = obs.get("value")
            if val_str:
                try:
                    return float(val_str)
                except (ValueError, TypeError):
                    pass
    return None


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_tissue_concentration_table_from_sidecar(
    sidecar_paths: dict[str, str],
    compound_name: str = "Chemical",
    dose_unit: str = "mg/kg",
) -> dict:
    """
    Build NIEHS Table 7 (Tissue Concentration) from sidecar data.

    Reads raw per-animal plasma concentration values from the sidecar JSON
    and computes mean ± SE per dose group per timepoint.  Only Biosampling
    Animals are included (this is the opposite of all other tables).

    LOQ handling: if a concentration value is missing but the LOQ is present,
    the value is substituted with LOQ/2 (standard analytical chemistry
    convention for below-detection-limit samples).

    Args:
        sidecar_paths:  {"Male": "/path/to/male.sidecar.json", ...}.
        compound_name:  Full chemical name for the caption.
        dose_unit:      Dose unit string (default "mg/kg").

    Returns:
        Dict with keys matching the Typst apical_sections schema, plus
        table_type="pharmacokinetic" flag for specialized Typst rendering.
        Returns empty dict if no tissue concentration data found.
    """
    # ── Load sidecars ─────────────────────────────────────────────────────
    sidecar_data: dict[str, dict] = {}
    for sex, sc_path in sidecar_paths.items():
        sidecar_data[sex] = load_sidecar(sc_path)

    if not sidecar_data:
        return {}

    # ── Extract per-timepoint, per-dose concentration values ──────────────
    # Only Biosampling Animals.  Group by (sex, timepoint, dose).
    #
    # Structure: {sex: {timepoint_label: {dose: [value, ...]}}}
    conc_by_sex: dict[str, dict[str, dict[float, list[float]]]] = {}
    # Also track N (biosampling animals per dose)
    n_by_sex_dose: dict[str, dict[float, set[str]]] = {}
    # All doses that have biosampling animals
    bio_doses: set[float] = set()
    # All timepoints discovered
    all_timepoints: list[str] = []
    timepoint_set: set[str] = set()

    for sex, sc in sidecar_data.items():
        tp_dose_vals: dict[str, dict[float, list[float]]] = {}
        dose_animals: dict[float, set[str]] = {}

        for aid, rec in sc.get("animals", {}).items():
            selection = rec.get("selection", "Unknown")
            # Only Biosampling Animals for tissue concentration
            if "biosampling" not in selection.lower():
                continue

            dose = rec["dose"]
            bio_doses.add(dose)
            dose_animals.setdefault(dose, set()).add(aid)

            # Group observations by timepoint.
            # Each observation has a study day (e.g., "SD4", "SD5") and an
            # endpoint name.  We only collect values where either:
            #   (a) the concentration value is non-null, OR
            #   (b) the LOQ for the SAME endpoint on the SAME day is non-null
            #       (indicating the sample was taken but was below detection
            #       limit — substitute with LOQ/2).
            # If both concentration and LOQ are null, the measurement wasn't
            # collected on that day (e.g., 2h concentration on SD5) — skip it.
            for obs in rec.get("observations", []):
                ep_name = obs.get("endpoint", "")
                obs_day = obs.get("day", "")
                timepoint = _parse_timepoint(ep_name)
                if timepoint is None:
                    continue

                if timepoint not in timepoint_set:
                    timepoint_set.add(timepoint)
                    all_timepoints.append(timepoint)

                val_str = obs.get("value")
                if val_str and val_str.strip():
                    try:
                        fval = float(val_str)
                        tp_dose_vals.setdefault(timepoint, {}).setdefault(dose, []).append(fval)
                        continue
                    except (ValueError, TypeError):
                        pass

                # Value missing — check for LOQ substitution, but ONLY on the
                # same study day.  A null "2h Concentration" on SD5 means the
                # measurement wasn't collected (skip), not that it was below LOQ.
                loq = _find_loq_value(rec.get("observations", []), ep_name, day=obs_day)
                if loq is not None and loq > 0:
                    tp_dose_vals.setdefault(timepoint, {}).setdefault(dose, []).append(loq / 2)

        conc_by_sex[sex] = tp_dose_vals
        n_by_sex_dose[sex] = {d: aids for d, aids in dose_animals.items()}

    if not bio_doses or not all_timepoints:
        return {}

    sorted_doses = sorted(bio_doses)

    # Sort timepoints by hour number for consistent ordering
    def _tp_sort_key(tp: str) -> int:
        m = re.match(r"(\d+)", tp)
        return int(m.group(1)) if m else 999
    all_timepoints.sort(key=_tp_sort_key)

    # ── Build the table rows ──────────────────────────────────────────────
    serialized: dict[str, list[dict]] = {}

    for sex in ("Male", "Female"):
        tp_data = conc_by_sex.get(sex, {})
        dose_animals = n_by_sex_dose.get(sex, {})

        if not tp_data:
            continue

        rows: list[dict] = []

        # ── n-row: biosampling animals per dose ───────────────────────────
        n_vals: dict[str, str] = {}
        for dose in sorted_doses:
            dk = js_dose_key(dose)
            n = len(dose_animals.get(dose, set()))
            n_vals[dk] = str(n) if n > 0 else "\u2013"

        rows.append({
            "label": "n",
            "doses": sorted_doses,
            "values": n_vals,
            "is_n_row": True,
        })

        # ── Timepoint rows ────────────────────────────────────────────────
        for tp in all_timepoints:
            dose_vals = tp_data.get(tp, {})
            values: dict[str, str] = {}

            for dose in sorted_doses:
                dk = js_dose_key(dose)
                vals = dose_vals.get(dose, [])
                if vals:
                    m, s = mean_se(vals)
                    dec = adaptive_decimals(m)
                    values[dk] = format_mean_se(m, s, dec)
                else:
                    values[dk] = "\u2013"

            rows.append({
                "label": tp,
                "doses": sorted_doses,
                "values": values,
            })

        serialized[sex] = rows

    if not serialized:
        return {}

    # ── Footnotes ─────────────────────────────────────────────────────────
    # Tissue concentration tables typically have minimal footnotes:
    # data format and concentration unit.
    footnotes = [
        "Data are displayed as mean \u00b1 standard error of the mean; "
        "plasma concentration data are presented in ng/mL.",
    ]

    return {
        "title": "Tissue Concentration",
        "caption": CAPTION_TEMPLATE.replace("{compound}", compound_name),
        "compound": compound_name,
        "dose_unit": dose_unit,
        "first_col_header": "Timepoint",
        "table_data": serialized,
        "footnotes": footnotes,
        # Flag for Typst template to use pharmacokinetic layout:
        # no BMD columns, narrow format, different column headers.
        "table_type": "pharmacokinetic",
    }
