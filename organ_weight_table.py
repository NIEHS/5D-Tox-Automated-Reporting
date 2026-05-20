"""
organ_weight_table.py — Build NIEHS Table 3 (Organ Weights) from sidecar data.

Produces the exact structure of NIEHS Report 10 Table 3:

    Table 3. Summary of Select Organ Weight Data for Male and Female Rats
    Administered {compound} for Five Days

Structure:
    Columns: Endpoint^(a,b) | dose₀ | dose₁ | ... | doseₙ | BMD₁Std (unit) | BMDL₁Std (unit)
    Row groups per sex:
        n                          — sample sizes per dose group
        Terminal Body Weight (g)   — context row (BMD = ND, always shown)
        {Organ} Absolute (g)      — absolute organ weight, mean ± SE
        {Organ} Relative (mg/g)   — relative = (absolute / TBW) × 1000, mean ± SE

    Only organs with at least one responsive endpoint (absolute or relative)
    are shown.  Terminal Body Weight is always included as a context row.

Business rules:
    - Relative organ weight = (absolute organ weight / terminal body weight) × 1000
      Computed per-animal from raw sidecar values, then mean ± SE is taken.
    - Terminal Body Weight row always shows BMD = "ND" (it's context, not an
      organ endpoint — even though TBW data exists in the pivot, it's not
      a candidate for BMD modeling in the organ weight context).
    - Only Core Animals contribute to statistics (Biosampling Animals excluded).
    - Organs not in the NTP stats (not modeled) are excluded.
    - All dose groups appear, including those where all animals died.

Footnotes:
    BMD definition line (always present)
    (a) Data format description
    (b) Statistical method
    (c,d,...) Attrition notes (if applicable)
"""

from __future__ import annotations

import math

from table_builder_common import (
    BMD_DEFINITION,
    SIGNIFICANCE_EXPLANATION,
    SIGNIFICANCE_MARKER_LEGEND,
    js_dose_key,
    mean_se,
    format_mean_se,
    adaptive_decimals,
    load_sidecar,
    find_sidecar_paths,
    build_n_row,
    format_dose_label,
    legend_footnote,
    definition_footnote,
    lettered_footnote,
    finalize_footnotes,
    detect_core_animal_availability,
    build_sample_availability_footnotes,
    build_attrition_footnote,
    is_reportable_bmd,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAPTION_TEMPLATE = (
    "Summary of Select Organ Weight Data for Male and Female Rats "
    "Administered {compound} for Five Days"
)

FOOTNOTE_DATA_FORMAT = (
    "Data are displayed as mean \u00b1 standard error of the mean."
)

# Organ weight uses parametric methods (Williams/Dunnett), same as body weight.
FOOTNOTE_STAT_METHOD_ORGAN = (
    "Statistical analysis performed by the Jonckheere (trend) "
    "and Williams or Dunnett (pairwise) tests."
)

# Additional organ-weight-specific footnotes from the NIEHS reference:
FOOTNOTE_RELATIVE_WEIGHT = (
    "Relative organ weights (organ weight-to-body weight ratios) "
    "are given as mg organ weight/g body weight."
)

# The significance-marker text (SIGNIFICANCE_EXPLANATION + the */** legend)
# is shared across every apical table and lives in table_builder_common -
# imported above rather than re-declared here.  The reference organ-weight
# tables emphasize ** (p <= 0.01); the shared legend also names * for
# uniformity across the apical table set.


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_organ_weight_table_from_sidecar(
    sidecar_paths: dict[str, str],
    ntp_stats: dict[str, list],
    compound_name: str = "Chemical",
    dose_unit: str = "mg/kg",
) -> dict:
    """
    Build NIEHS Table 3 (Organ Weights) from sidecar + NTP stats.

    Computes absolute and relative organ weights from raw animal-level data
    in the sidecar JSON.  Only organs that have at least one responsive
    endpoint in the NTP stats are included.  Terminal Body Weight is shown
    as a context row (always ND for BMD).

    The sidecar provides raw per-animal organ weights and terminal body
    weights.  Relative weight is computed per-animal as:
        relative = (absolute_organ_weight / terminal_body_weight) × 1000

    Then mean ± SE is computed across animals at each dose.

    Args:
        sidecar_paths:  {"Male": "/path/to/male.sidecar.json", ...}.
        ntp_stats:      {sex: [TableRow-like dicts]} from NTP stats cache.
                        Each has: label, values_by_dose, bmd_str, bmdl_str,
                        responsive, trend_marker.
        compound_name:  Full chemical name for the caption.
        dose_unit:      Dose unit string (default "mg/kg").

    Returns:
        Dict matching the Typst apical_sections schema, or empty dict if
        no responsive organ endpoints exist.
    """
    # ── Load sidecars and extract per-animal organ data ───────────────────
    sidecar_data: dict[str, dict] = {}
    for sex, sc_path in sidecar_paths.items():
        sidecar_data[sex] = load_sidecar(sc_path)

    # ── Detect Core Animal availability per dose (shared helper) ──────────
    # Splits each dose group's Core Animals into "has usable data" vs
    # "all-NA" (organ not weighed — animal died before terminal sacrifice,
    # tissue not collected, etc.).  Shared with clinical_pathology_table.py;
    # see table_builder_common.  Feeds the sample-availability and attrition
    # footnotes built near the end of this function.
    (
        core_n_by_sex_dose,
        total_core_by_sex_dose,
        missing_sample_animals,
    ) = detect_core_animal_availability(sidecar_data)

    # Collect all doses for consistent column set
    all_doses: set[float] = set()
    for sc in sidecar_data.values():
        for rec in sc.get("animals", {}).values():
            all_doses.add(rec["dose"])
    for sex_rows in ntp_stats.values():
        for row in sex_rows:
            vbd = row.get("values_by_dose", {}) if isinstance(row, dict) else getattr(row, "values_by_dose", {})
            for d_str in vbd.keys():
                try:
                    all_doses.add(float(d_str))
                except (ValueError, TypeError):
                    pass
    sorted_doses = sorted(all_doses)

    # ── Collect all organ endpoints ───────────────────────────────────────
    # ALL organs in the data appear in the table (not just responsive ones).
    # The responsive gate controls BMD column values (ND vs numeric), not
    # row inclusion — matching the body weight and clinical pathology pattern.
    # Terminal Body Weight is excluded from the organ list — it's a context
    # row shown separately.
    all_organs: set[str] = set()
    ntp_by_sex_label: dict[str, dict[str, dict]] = {}
    for sex, sex_stats in ntp_stats.items():
        ntp_by_sex_label.setdefault(sex, {})
        for stat_row in sex_stats:
            label = stat_row.get("label") if isinstance(stat_row, dict) else stat_row.label
            ntp_by_sex_label[sex][label] = stat_row
            if label != "Terminal Body Weight":
                all_organs.add(label)

    if not all_organs:
        return {}

    # ── Extract raw values from sidecar ───────────────────────────────────
    # For each sex and dose, collect per-animal values for each endpoint.
    # Also collect Terminal Body Weight for relative weight computation.
    #
    # Structure: {sex: {endpoint: {dose: [value, ...]}}}
    raw_by_sex: dict[str, dict[str, dict[float, list[float]]]] = {}
    # TBW separately: {sex: {dose: {animal_id: tbw}}}
    tbw_by_sex: dict[str, dict[float, dict[str, float]]] = {}

    for sex, sc in sidecar_data.items():
        endpoint_vals: dict[str, dict[float, list[float]]] = {}
        tbw_vals: dict[float, dict[str, float]] = {}

        for aid, rec in sc.get("animals", {}).items():
            selection = rec.get("selection", "Unknown")
            # Only Core Animals contribute to organ weight stats
            if "biosampling" in selection.lower():
                continue

            dose = rec["dose"]

            # Parse observations into endpoint values for this animal.
            # Each observation has: day, endpoint, value.
            # For organ weights, each animal has ONE observation per endpoint
            # (all at the same Removal Day, typically SD5).
            for obs in rec.get("observations", []):
                ep_name = obs.get("endpoint", "")
                val_str = obs.get("value")
                if not ep_name or not val_str:
                    continue
                try:
                    fval = float(val_str)
                except (ValueError, TypeError):
                    continue

                if ep_name == "Terminal Body Weight":
                    tbw_vals.setdefault(dose, {})[aid] = fval
                endpoint_vals.setdefault(ep_name, {}).setdefault(dose, []).append(fval)

        raw_by_sex[sex] = endpoint_vals
        tbw_by_sex[sex] = tbw_vals

    # ── Compute relative weights per animal ───────────────────────────────
    # For each responsive organ, compute relative weight = (absolute / TBW) × 1000
    # per animal, then compute mean ± SE of the relative values.
    #
    # Structure: {sex: {organ: {dose: [relative_value, ...]}}}
    relative_by_sex: dict[str, dict[str, dict[float, list[float]]]] = {}

    for sex in ("Male", "Female"):
        ep_vals = raw_by_sex.get(sex, {})
        tbw = tbw_by_sex.get(sex, {})
        relatives: dict[str, dict[float, list[float]]] = {}

        for organ in all_organs:
            organ_vals = ep_vals.get(organ, {})
            for dose, abs_vals in organ_vals.items():
                tbw_at_dose = tbw.get(dose, {})
                # Match by position — animals at a dose appear in the same
                # order in both organ and TBW observations.  Since sidecar
                # observations are per-animal, we need animal IDs.
                # Re-extract animal-level data for matching.
                pass  # handled below with a different approach

        relative_by_sex[sex] = relatives

    # Re-extract with animal IDs for proper matching
    # Structure: {sex: {organ: {dose: [(aid, abs_val), ...]}}}
    raw_by_animal: dict[str, dict[str, dict[float, list[tuple[str, float]]]]] = {}
    for sex, sc in sidecar_data.items():
        organ_animal_vals: dict[str, dict[float, list[tuple[str, float]]]] = {}
        for aid, rec in sc.get("animals", {}).items():
            selection = rec.get("selection", "Unknown")
            if "biosampling" in selection.lower():
                continue
            dose = rec["dose"]
            for obs in rec.get("observations", []):
                ep_name = obs.get("endpoint", "")
                val_str = obs.get("value")
                if not ep_name or not val_str:
                    continue
                try:
                    fval = float(val_str)
                except (ValueError, TypeError):
                    continue
                organ_animal_vals.setdefault(ep_name, {}).setdefault(dose, []).append((aid, fval))
        raw_by_animal[sex] = organ_animal_vals

    # Now compute relative weights with proper animal matching
    relative_by_sex = {}
    for sex in ("Male", "Female"):
        organ_data = raw_by_animal.get(sex, {})
        tbw_data = tbw_by_sex.get(sex, {})
        rel_sex: dict[str, dict[float, list[float]]] = {}

        for organ in all_organs:
            organ_at_dose = organ_data.get(organ, {})
            rel_organ: dict[float, list[float]] = {}

            for dose, animal_vals in organ_at_dose.items():
                tbw_at_dose = tbw_data.get(dose, {})
                rel_vals = []
                for aid, abs_val in animal_vals:
                    animal_tbw = tbw_at_dose.get(aid)
                    if animal_tbw and animal_tbw > 0:
                        rel_vals.append((abs_val / animal_tbw) * 1000)
                if rel_vals:
                    rel_organ[dose] = rel_vals

            if rel_organ:
                rel_sex[organ] = rel_organ

        relative_by_sex[sex] = rel_sex

    # ── Build the table rows ──────────────────────────────────────────────
    serialized: dict[str, list[dict]] = {}

    for sex in ("Male", "Female"):
        ep_vals = raw_by_sex.get(sex, {})
        tbw = tbw_by_sex.get(sex, {})
        rel_data = relative_by_sex.get(sex, {})
        sex_ntp = ntp_by_sex_label.get(sex, {})

        # Check if this sex has any responsive organ data
        has_responsive = any(
            organ in ep_vals or organ in rel_data
            for organ in all_organs
        )
        if not has_responsive and not ep_vals:
            continue

        rows: list[dict] = []

        # ── n-row ─────────────────────────────────────────────────────────
        # N = number of Core Animals per dose with Terminal Body Weight data
        # (proxy for "animals that survived to terminal sacrifice").
        tbw_vals_list = ep_vals.get("Terminal Body Weight", {})
        n_animals = {
            dose: tbw_vals_list.get(dose, [])
            for dose in sorted_doses
        }
        rows.append(build_n_row(n_animals, sorted_doses))

        # ── Terminal Body Weight row (context) ────────────────────────────
        # Always shown as context, BMD = ND.  Mean ± SE of terminal body
        # weights at each dose.
        tbw_row_vals: dict[str, str] = {}
        for dose in sorted_doses:
            dk = js_dose_key(dose)
            dose_tbw_list = tbw_vals_list.get(dose, [])
            if dose_tbw_list:
                m, s = mean_se(dose_tbw_list)
                dec = adaptive_decimals(m)
                tbw_row_vals[dk] = format_mean_se(m, s, dec)
            else:
                tbw_row_vals[dk] = "\u2013"
        rows.append({
            "label": "Terminal Body Weight (g)",
            "doses": sorted_doses,
            "values": tbw_row_vals,
            "bmd": "ND",
            "bmdl": "ND",
            "is_context_row": True,
        })

        # ── Per-organ rows: Absolute + Relative ──────────────────────────
        # Sort organs alphabetically for consistent output
        for organ in sorted(all_organs):
            abs_at_dose = ep_vals.get(organ, {})
            rel_at_dose = rel_data.get(organ, {})

            # Get NTP stats for BMD/BMDL (on the absolute weight endpoint).
            # `responsive` is the NTP statistical gate \u2014 carried onto the
            # absolute row so the row-emphasis rule can use it.
            organ_ntp = sex_ntp.get(organ, {})
            if isinstance(organ_ntp, dict):
                organ_bmd = organ_ntp.get("bmd_str", "\u2014")
                organ_bmdl = organ_ntp.get("bmdl_str", "\u2014")
                organ_vbd = organ_ntp.get("values_by_dose", {})
                organ_trend = organ_ntp.get("trend_marker", "")
                organ_responsive = organ_ntp.get("responsive", False)
            else:
                organ_bmd = getattr(organ_ntp, "bmd_str", "\u2014")
                organ_bmdl = getattr(organ_ntp, "bmdl_str", "\u2014")
                organ_vbd = getattr(organ_ntp, "values_by_dose", {})
                organ_trend = getattr(organ_ntp, "trend_marker", "")
                organ_responsive = getattr(organ_ntp, "responsive", False)

            # Absolute weight row — use NTP stats values (includes significance markers)
            abs_values: dict[str, str] = {}
            for dose in sorted_doses:
                dk = js_dose_key(dose)
                # Try float key (live TableRow), then string key (cached dict)
                val = organ_vbd.get(dose)
                if val is None:
                    val = organ_vbd.get(str(dose), organ_vbd.get(str(float(dose))))
                if val:
                    abs_values[dk] = val
                elif abs_at_dose.get(dose):
                    # Fall back to computing from sidecar
                    m, s = mean_se(abs_at_dose[dose])
                    dec = adaptive_decimals(m)
                    abs_values[dk] = format_mean_se(m, s, dec)
                else:
                    abs_values[dk] = "\u2013"

            # BMD/BMDL: pass through .bm2-sourced values directly.
            # BMDExpress modeling is independent of NTP responsiveness.
            bmd_text = organ_bmd if organ_bmd else "\u2014"
            bmdl_text = organ_bmdl if organ_bmdl else "\u2014"

            # Row emphasis (bold) — same union rule as clinical pathology:
            # the absolute-weight row is emphasized when it passed the NTP
            # responsive gate OR BMDExpress produced a reportable BMD.
            abs_entry = {
                "label": f"{organ} Absolute (g)",
                "doses": sorted_doses,
                "values": abs_values,
                "bmd": bmd_text,
                "bmdl": bmdl_text,
                "responsive": bool(organ_responsive),
                "emphasize": (
                    bool(organ_responsive) or is_reportable_bmd(bmd_text)
                ),
            }
            if organ_trend:
                abs_entry["trend_marker"] = organ_trend
            rows.append(abs_entry)

            # Relative weight row — computed from sidecar, no NTP stats
            # BMD for relative weight is always "ND" unless separately modeled
            # (BMDExpress models absolute weights, not relative).
            rel_values: dict[str, str] = {}
            for dose in sorted_doses:
                dk = js_dose_key(dose)
                dose_rel = rel_at_dose.get(dose, [])
                if dose_rel:
                    m, s = mean_se(dose_rel)
                    dec = adaptive_decimals(m)
                    rel_values[dk] = format_mean_se(m, s, dec)
                else:
                    rel_values[dk] = "\u2013"

            # Relative-weight rows are never modeled by BMDExpress (bmd is
            # always "ND") and have no responsive gate, so emphasize is
            # always False — set it explicitly for uniformity with the
            # absolute rows.
            rows.append({
                "label": f"{organ} Relative (mg/g)",
                "doses": sorted_doses,
                "values": rel_values,
                "bmd": "ND",
                "bmdl": "ND",
                "emphasize": is_reportable_bmd("ND"),
            })

        serialized[sex] = rows

    if not serialized:
        return {}

    # ── Footnotes (typed model — see table_builder_common) ────────────────
    # Order in the list IS the render order; finalize_footnotes assigns the
    # a/b/c... letters to the `lettered` records (legend/definition skipped):
    #
    #   legend      — significance explanation               [Canonical]
    #   legend      — */** marker key                        [Canonical]
    #   definition  — BMD/BMDL abbreviation paragraph         [Canonical]
    #   (a)         — data format                            [Canonical]
    #   (b)         — statistical method (Williams/Dunnett)   [Canonical]
    #   (c)         — relative-weight definition              [Canonical]
    #   (d,e,...)   — sample-availability (organ not weighed) [Canonical]
    #   (next)      — attrition (whole dose group, no data)   [Canonical]
    #
    # The sample-availability and attrition footnotes are dynamic — they
    # only appear when an organ-weight sidecar actually has Core Animals
    # with no usable data — and are built by the shared helpers in
    # table_builder_common, identical to clinical pathology.
    #
    # Provenance: every organ-weight footnote is Canonical — anchored in
    # NIEHS Report 10 Table 3, with the reference PDF as the authority.
    footnotes: list[dict] = [
        legend_footnote(SIGNIFICANCE_EXPLANATION),
        legend_footnote(SIGNIFICANCE_MARKER_LEGEND),
        definition_footnote(BMD_DEFINITION),
        lettered_footnote(FOOTNOTE_DATA_FORMAT, "data_format"),
        lettered_footnote(FOOTNOTE_STAT_METHOD_ORGAN, "stat_method"),
        lettered_footnote(FOOTNOTE_RELATIVE_WEIGHT, "relative_weight"),
    ]

    # ── Sample-availability + attrition footnotes (shared helpers) ────────
    # Same detection and footnote-building as clinical pathology; see
    # table_builder_common.  For most organ-weight sessions these produce
    # nothing (terminal organ weights are recorded for every Core Animal),
    # but they fire correctly when an animal's tissue was not collected.
    n_row_marker_refs: dict[str, dict[float, str]] = {}

    sa_records, sa_refs = build_sample_availability_footnotes(
        missing_sample_animals, total_core_by_sex_dose, sorted_doses,
    )
    footnotes.extend(sa_records)

    attr_record, attr_refs = build_attrition_footnote(
        total_core_by_sex_dose, core_n_by_sex_dose, sorted_doses, dose_unit,
    )
    if attr_record is not None:
        footnotes.append(attr_record)

    for sex, dose_refs in sa_refs.items():
        n_row_marker_refs.setdefault(sex, {}).update(dose_refs)
    for sex, dose_refs in attr_refs.items():
        n_row_marker_refs.setdefault(sex, {}).update(dose_refs)

    # Attach the marker refs to each sex's n-row (built earlier in this
    # function), then finalize_footnotes assigns letters and derives the
    # rows' `markers` dicts from `marker_refs`.
    for sex, rows in serialized.items():
        sex_refs = n_row_marker_refs.get(sex, {})
        if sex_refs and rows and rows[0].get("is_n_row"):
            n_row = rows[0]
            refs = n_row.get("marker_refs", {})
            refs.update({
                js_dose_key(d): fid for d, fid in sex_refs.items()
            })
            n_row["marker_refs"] = refs

    finalize_footnotes(footnotes, serialized)

    return {
        "title": "Organ Weight",
        "caption": CAPTION_TEMPLATE.replace("{compound}", compound_name),
        "compound": compound_name,
        "dose_unit": dose_unit,
        "first_col_header": "Endpoint",
        "table_data": serialized,
        # Typed footnote list: legend + definition + lettered records, with
        # letters already assigned by finalize_footnotes.  The old separate
        # bmd_definition / significance_* keys are folded in as records.
        "footnotes": footnotes,
    }
