"""
clinical_pathology_table.py — Build NIEHS Tables 4/5/6 from sidecar data.

Handles three platforms with identical table structure:
  - Table 4: Clinical Chemistry
  - Table 5: Hematology
  - Table 6: Hormones

All three share the same layout: a combined Male + Female table with sex
separator rows, n-row per sex showing the maximum sample size across shown
endpoints, endpoint rows with mean ± SE and significance markers (*/**),
and BMD/BMDL columns from the NTP stats pipeline.

Only responsive endpoints are shown — those that passed the NTP gate
(significant Jonckheere trend p ≤ 0.01 AND at least one significant
Dunnett pairwise p ≤ 0.05).  The table title includes "Select" to
indicate this filtering.

NIEHS caption pattern:
    "Summary of Select {Platform} Data for Male and Female Rats
     Administered {compound} for Five Days"

Output structure (per sex block):
    n       — max sample size across shown endpoints per dose group
    rows    — one per responsive endpoint: label, mean±SE per dose, BMD, BMDL

The sidecar provides raw animal-level data for computing N counts
(Core Animals only, excluding Biosampling Animals).  The NTP stats
pipeline provides significance markers and BMD/BMDL values.
"""

from __future__ import annotations

from table_builder_common import (
    BMD_DEFINITION,
    FOOTNOTE_STAT_METHOD,
    SIGNIFICANCE_LEGEND,
    js_dose_key,
    mean_se,
    format_mean_se,
    adaptive_decimals,
    load_sidecar,
    find_sidecar_paths,
    build_n_row,
    bmd_display_from_stats,
    format_dose_label,
)


# ---------------------------------------------------------------------------
# Constants — NIEHS caption and footnote templates
# ---------------------------------------------------------------------------

# Caption template.  {platform} is "Clinical Chemistry", "Hematology", etc.
# {compound} is the full chemical name.
CAPTION_TEMPLATE = (
    "Summary of Select {platform} Data for Male and Female Rats "
    "Administered {compound} for Five Days"
)

# The data-format footnote differs slightly from body weight — clinical
# pathology tables say "data" not "body weight data".
FOOTNOTE_DATA_FORMAT = (
    "Data are displayed as mean \u00b1 standard error of the mean."
)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_clinical_pathology_table_from_sidecar(
    platform: str,
    sidecar_paths: dict[str, str],
    ntp_stats: dict[str, list],
    compound_name: str = "Chemical",
    dose_unit: str = "mg/kg",
) -> dict:
    """
    Build a clinical pathology table (Tables 4/5/6) from sidecar + NTP stats.

    Combines raw animal-level data from the sidecar JSON (for correct N counts
    limited to Core Animals) with NTP stats output (for mean±SE with significance
    markers and BMD/BMDL values).  Only responsive endpoints are included.

    The sidecar's main value here is providing per-dose-group N counts that
    correctly exclude Biosampling Animals.  The mean±SE and significance markers
    come from the NTP stats pipeline (which already computed them from the
    integrated data).

    Args:
        platform:       "Clinical Chemistry", "Hematology", or "Hormones".
        sidecar_paths:  {"Male": "/path/to/male.sidecar.json", ...}.
        ntp_stats:      {sex: [TableRow-like dicts]} from the NTP stats cache.
                        Each dict has: label, values_by_dose, n_by_dose,
                        bmd_str, bmdl_str, responsive, trend_marker,
                        missing_animals_by_dose.
        compound_name:  Full chemical name for the caption.
        dose_unit:      Dose unit string (default "mg/kg").

    Returns:
        Dict with keys matching the Typst apical_sections schema:
            title, caption, compound, dose_unit, first_col_header,
            table_data (serialized), footnotes, bmd_definition.
    """
    # ── Load sidecars to get per-dose Core Animals counts ─────────────────
    # The sidecar tells us exactly how many Core Animals contributed to each
    # dose group.  This is the N that goes in the n-row.  The NTP stats
    # n_by_dose may include Biosampling Animals depending on how the pivot
    # was built, so the sidecar is the source of truth.
    sidecar_data: dict[str, dict] = {}
    for sex, sc_path in sidecar_paths.items():
        sidecar_data[sex] = load_sidecar(sc_path)

    # Collect all doses across all sidecars for consistent column set
    all_doses: set[float] = set()
    for sc in sidecar_data.values():
        for rec in sc.get("animals", {}).values():
            all_doses.add(rec["dose"])
    # Also collect doses from NTP stats in case sidecar is incomplete
    for sex_rows in ntp_stats.values():
        for row in sex_rows:
            vbd = row.get("values_by_dose", {}) if isinstance(row, dict) else getattr(row, "values_by_dose", {})
            for d_str in vbd.keys():
                try:
                    all_doses.add(float(d_str))
                except (ValueError, TypeError):
                    pass
    sorted_doses = sorted(all_doses)

    # ── Count Core Animals per dose from sidecar ──────────────────────────
    # For the n-row, we need the number of Core Animals at each dose that
    # have at least one non-NA observation for any endpoint in this platform.
    core_n_by_sex_dose: dict[str, dict[float, int]] = {}
    for sex, sc in sidecar_data.items():
        dose_animals: dict[float, set[str]] = {}
        for aid, rec in sc.get("animals", {}).items():
            selection = rec.get("selection", "Unknown")
            if "core" not in selection.lower():
                continue
            dose = rec["dose"]
            # Check if animal has at least one non-null observation value
            has_data = any(
                obs.get("value") and obs["value"].strip()
                for obs in rec.get("observations", [])
            )
            if has_data:
                dose_animals.setdefault(dose, set()).add(aid)
        core_n_by_sex_dose[sex] = {
            dose: len(aids) for dose, aids in dose_animals.items()
        }

    # ── Build rows for ALL endpoints ─────────────────────────────────────
    # The NIEHS reference includes every measured endpoint in the table,
    # not just responsive ones.  The responsive/non-responsive distinction
    # controls the BMD column values (numeric vs "ND"), not row inclusion.
    # This matches the Body Weight pattern where all study days appear
    # regardless of the statistical gate.
    serialized: dict[str, list[dict]] = {}

    for sex in ("Male", "Female"):
        sex_stats = ntp_stats.get(sex, [])
        if not sex_stats:
            continue

        rows: list[dict] = []

        # ── n-row: max Core Animals N across shown endpoints per dose ─────
        # The NIEHS reference uses a single n-row per sex showing the
        # maximum N across all shown endpoints.  This represents the
        # starting Core Animals count at each dose.
        n_counts = core_n_by_sex_dose.get(sex, {})
        n_row_animals = {dose: ["x"] * n_counts.get(dose, 0) for dose in sorted_doses}
        rows.append(build_n_row(n_row_animals, sorted_doses))

        # ── Endpoint rows (all endpoints, not just responsive) ────────────
        for stat_row in sex_stats:
            # Support both dict and object access patterns
            if isinstance(stat_row, dict):
                label = stat_row.get("label", "")
                vbd = stat_row.get("values_by_dose", {})
                bmd_str = stat_row.get("bmd_str", "\u2014")
                bmdl_str = stat_row.get("bmdl_str", "\u2014")
                trend_marker = stat_row.get("trend_marker", "")
                responsive = stat_row.get("responsive", False)
            else:
                label = stat_row.label
                vbd = stat_row.values_by_dose
                bmd_str = stat_row.bmd_str
                bmdl_str = stat_row.bmdl_str
                trend_marker = stat_row.trend_marker
                responsive = stat_row.responsive

            # BMD/BMDL display rules (same as body weight):
            #   - Non-responsive endpoint → "ND" (gate didn't pass, BMD not computed)
            #   - Responsive with numeric BMD → show the value
            #   - Responsive but modeling failed → "ND"
            if not responsive:
                bmd_text = "ND"
                bmdl_text = "ND"
            else:
                bmd_text = bmd_str if bmd_str and bmd_str != "\u2014" else "ND"
                bmdl_text = bmdl_str if bmdl_str and bmdl_str != "\u2014" else "ND"

            # Build values dict with dose keys matching JS convention.
            # values_by_dose keys may be floats (TableRow objects from the
            # pipeline) or strings (dicts from the NTP stats cache).  Try
            # both: float first (live TableRow), then string (cached dict).
            values: dict[str, str] = {}
            for dose in sorted_doses:
                dk = js_dose_key(dose)
                # Try float key (TableRow.values_by_dose uses float keys)
                val = vbd.get(dose)
                if val is None:
                    # Try string key (NTP cache JSON uses string keys)
                    val = vbd.get(str(dose), vbd.get(str(float(dose))))
                values[dk] = val if val is not None else "\u2013"

            entry = {
                "label": label,
                "doses": sorted_doses,
                "values": values,
                "bmd": bmd_text,
                "bmdl": bmdl_text,
            }
            if trend_marker:
                entry["trend_marker"] = trend_marker

            rows.append(entry)

        serialized[sex] = rows

    # ── Footnotes ─────────────────────────────────────────────────────────
    # Clinical pathology tables have:
    #   (a) Data format description
    #   (b) Statistical method
    # Unlike body weight, there are typically no attrition footnotes since
    # clinical pathology endpoints are measured on surviving animals at
    # terminal sacrifice.  If attrition data exists in the future, it can
    # be added here following the body weight pattern.
    footnotes = [
        FOOTNOTE_DATA_FORMAT,       # (a)
        FOOTNOTE_STAT_METHOD,       # (b)
    ]

    return {
        "title": platform,
        "caption": CAPTION_TEMPLATE.replace("{platform}", platform).replace("{compound}", compound_name),
        "compound": compound_name,
        "dose_unit": dose_unit,
        "first_col_header": "Endpoint",
        "table_data": serialized,
        "footnotes": footnotes,
        "bmd_definition": BMD_DEFINITION,
    }
