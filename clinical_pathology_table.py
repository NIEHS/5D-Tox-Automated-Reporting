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
    js_dose_key,
    load_sidecar,
    build_n_row,
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

# Clinical pathology uses nonparametric methods (Shirley/Dunn) instead of
# the parametric methods (Williams/Dunnett) used for body weight and organ
# weight.  The NIEHS reference explains: "Clinical pathology data, which
# typically have skewed distributions, were analyzed using the nonparametric
# multiple comparison methods of Shirley and Dunn."
FOOTNOTE_STAT_METHOD_CLINICAL = (
    "Statistical analysis performed by the Jonckheere (trend) "
    "and Shirley or Dunn (pairwise) tests."
)

# Significance explanation paragraph — appears above the lettered footnotes
# in the reference report.  Explains what significance markers mean on
# control vs dosed group cells.
SIGNIFICANCE_EXPLANATION = (
    "Statistical significance for a dosed group indicates a significant "
    "pairwise test compared to the vehicle control group. Statistical "
    "significance for the vehicle control group indicates a significant "
    "trend test."
)

# Significance marker legend — both * and ** for clinical pathology
SIGNIFICANCE_MARKER_LEGEND = (
    "*Statistically significant at p \u2264 0.05; "
    "**p \u2264 0.01."
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
    # We also track the total Core Animals per dose (including those with
    # all-NA values) to detect sample availability issues — animals that
    # exist but whose samples were not received, had clots, etc.
    core_n_by_sex_dose: dict[str, dict[float, int]] = {}
    # Total Core Animals per dose (including all-NA animals)
    total_core_by_sex_dose: dict[str, dict[float, int]] = {}
    # Animals with no data: {sex: {dose: [animal_id, ...]}}
    missing_sample_animals: dict[str, dict[float, list[str]]] = {}

    for sex, sc in sidecar_data.items():
        dose_with_data: dict[float, set[str]] = {}
        dose_all: dict[float, set[str]] = {}
        dose_missing: dict[float, list[str]] = {}

        for aid, rec in sc.get("animals", {}).items():
            selection = rec.get("selection", "Unknown")
            # Include Core Animals and animals with unknown selection.
            # "Unknown" means the CSV had no Selection column — these are
            # implicitly Core Animals (e.g., Hormones CSV has no Biosampling
            # Animals, so no Selection column is provided).
            if "biosampling" in selection.lower():
                continue
            dose = rec["dose"]
            dose_all.setdefault(dose, set()).add(aid)

            # Check if animal has at least one non-null, non-NA observation
            has_data = any(
                obs.get("value") and obs["value"].strip()
                and obs["value"].strip().upper() != "NA"
                for obs in rec.get("observations", [])
            )
            if has_data:
                dose_with_data.setdefault(dose, set()).add(aid)
            else:
                # This animal is a Core Animal at this dose but has no
                # usable data — sample not received, clotted, etc.
                dose_missing.setdefault(dose, []).append(aid)

        core_n_by_sex_dose[sex] = {
            dose: len(aids) for dose, aids in dose_with_data.items()
        }
        total_core_by_sex_dose[sex] = {
            dose: len(aids) for dose, aids in dose_all.items()
        }
        missing_sample_animals[sex] = dose_missing

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
            else:
                label = stat_row.label
                vbd = stat_row.values_by_dose
                bmd_str = stat_row.bmd_str
                bmdl_str = stat_row.bmdl_str
                trend_marker = stat_row.trend_marker

            # BMD/BMDL display: pass through the .bm2-sourced values directly.
            # BMDExpress 3 modeling and NTP statistical significance are
            # INDEPENDENT concerns (see apical_report.py lines 810-816).
            # The .bm2 bMDResult determines what appears in the BMD column:
            #   "viable" → numeric BMD/BMDL
            #   "NVM"    → "NVM" (no viable model)
            #   "UREP"   → "UREP" (unreliable estimate)
            #   "NR"     → "<LNZD/3" (not reportable)
            #   None     → "—" (endpoint not modeled by BMDExpress 3)
            # This is NOT gated by NTP responsiveness — an endpoint can
            # have a viable BMD even if it's not NTP-significant.
            bmd_text = bmd_str if bmd_str else "\u2014"
            bmdl_text = bmdl_str if bmdl_str else "\u2014"

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
    # NIEHS reference footnote structure for clinical pathology tables:
    #   1. Significance explanation paragraph (unnumbered, above markers)
    #   2. Significance marker legend (*p ≤ 0.05; **p ≤ 0.01)
    #   3. BMD definition paragraph (unnumbered)
    #   4. (a) Data format description
    #   5. (b) Statistical method (Shirley/Dunn for clinical pathology)
    #   6. (c,d,...) Sample availability notes (per dose group, dynamic)
    #   7. Attrition footnote (333/1000 mg/kg, if applicable)
    #
    # The significance_explanation and marker_legend are passed as separate
    # keys so the Typst template can render them above the lettered footnotes.
    footnotes = [
        FOOTNOTE_DATA_FORMAT,              # (a)
        FOOTNOTE_STAT_METHOD_CLINICAL,     # (b)
    ]

    # ── Sample availability footnotes (c,d,...) ───────────────────────────
    # Detect animals whose samples were not available (all-NA observations).
    # These are Core Animals that exist in the sidecar but have no usable
    # data — sample not received, clotted, insufficient volume, etc.
    # Each unique (sex, dose, count) combination gets a lettered footnote.
    # Markers are placed on the n-row cells where N is reduced.
    next_letter_ord = ord("c")
    n_row_markers: dict[str, dict[float, str]] = {}

    for sex in ("Male", "Female"):
        missing = missing_sample_animals.get(sex, {})
        n_row_markers.setdefault(sex, {})
        for dose in sorted_doses:
            missing_at_dose = missing.get(dose, [])
            if not missing_at_dose:
                continue
            count = len(missing_at_dose)
            letter = chr(next_letter_ord)
            next_letter_ord += 1
            n_row_markers[sex][dose] = letter

            # Format: "One sample in the indicated dose group was not received."
            # or "N samples from each of the indicated dose groups..."
            if count == 1:
                footnotes.append(
                    "One sample in the indicated dose group was not received."
                )
            else:
                footnotes.append(
                    f"{count} samples in the indicated dose group "
                    f"were not received."
                )

    # ── Attrition footnote (333/1000 mg/kg dead animals) ──────────────────
    # If the high-dose groups have no data at all (all animals dead before
    # sample collection), add the standard attrition footnote.
    for sex in ("Male", "Female"):
        total = total_core_by_sex_dose.get(sex, {})
        with_data = core_n_by_sex_dose.get(sex, {})
        for dose in sorted_doses:
            total_n = total.get(dose, 0)
            data_n = with_data.get(dose, 0)
            if total_n > 0 and data_n == 0:
                # Entire dose group dead — check if we already have an
                # attrition footnote (avoid duplicates across sexes)
                attrition_text = (
                    "All male and female 333 and 1,000 mg/kg rats were "
                    "found dead or moribund and euthanized by study day 1."
                )
                if attrition_text not in footnotes:
                    letter = chr(next_letter_ord)
                    next_letter_ord += 1
                    footnotes.append(attrition_text)
                    # Place marker on the n-row dash for this dose/sex
                    n_row_markers.setdefault(sex, {})[dose] = letter
                break  # one footnote covers all dead dose groups

    # Inject markers into the n-rows that were already built
    for sex, rows in serialized.items():
        sex_markers = n_row_markers.get(sex, {})
        if sex_markers and rows:
            n_row = rows[0]  # first row is always the n-row
            if n_row.get("is_n_row"):
                existing = n_row.get("markers", {})
                existing.update({
                    js_dose_key(d): letter
                    for d, letter in sex_markers.items()
                })
                if existing:
                    n_row["markers"] = existing

    return {
        "title": platform,
        "caption": CAPTION_TEMPLATE.replace("{platform}", platform).replace("{compound}", compound_name),
        "compound": compound_name,
        "dose_unit": dose_unit,
        "first_col_header": "Endpoint",
        "table_data": serialized,
        "footnotes": footnotes,
        "bmd_definition": BMD_DEFINITION,
        # Extra footnote fields rendered above the lettered footnotes
        # by the Typst template, matching the NIEHS reference layout.
        "significance_explanation": SIGNIFICANCE_EXPLANATION,
        "significance_marker_legend": SIGNIFICANCE_MARKER_LEGEND,
    }
