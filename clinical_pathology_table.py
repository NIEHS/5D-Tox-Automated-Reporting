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
    SIGNIFICANCE_EXPLANATION,
    SIGNIFICANCE_MARKER_LEGEND,
    js_dose_key,
    load_sidecar,
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

# The significance-marker text (SIGNIFICANCE_EXPLANATION + the */** legend)
# is shared across every apical table and lives in table_builder_common -
# imported above rather than re-declared here.  It used to be a per-builder
# copy, which drifted into three slightly different wordings.


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_clinical_pathology_table_from_sidecar(
    platform: str,
    sidecar_paths: dict[str, str],
    ntp_stats: dict[str, list],
    compound_name: str = "Chemical",
    dose_unit: str = "mg/kg",
    imputed_cells: dict | None = None,
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
        imputed_cells:  {sex: {dose_str: count}} for THIS platform — dose
                        groups whose legacy/inferred file filled missing
                        values with the dose-group mean.  Recorded by the
                        BMDProject schema's legacy/truth dedup and threaded
                        in via _build_section_cards.  None when no
                        imputation was detected for this platform; drives
                        the imputation footnote.

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

    # ── Detect Core Animal availability per dose (shared helper) ──────────
    # Splits each dose group's Core Animals into "has usable data" vs
    # "all-NA" (sample not received, clotted, etc.).  Shared with
    # organ_weight_table.py — see table_builder_common.
    (
        core_n_by_sex_dose,
        total_core_by_sex_dose,
        missing_sample_animals,
    ) = detect_core_animal_availability(sidecar_data)

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
                # `responsive` is the Jonckheere+Dunnett gate (see
                # body_weight_table.py docstring at line 49).  Carried into
                # the row dict so the HTML preview and Typst template can
                # bold responsive endpoints \u2014 the NIEHS-style visual cue
                # for "this endpoint contributed a BMD."
                responsive = stat_row.get("responsive", False)
            else:
                label = stat_row.label
                vbd = stat_row.values_by_dose
                bmd_str = stat_row.bmd_str
                bmdl_str = stat_row.bmdl_str
                trend_marker = stat_row.trend_marker
                responsive = getattr(stat_row, "responsive", False)

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

            # Row emphasis (bold) rule.  A row is emphasized when EITHER:
            #   - it passed the NTP statistical gate (`responsive`), OR
            #   - BMDExpress modeled it at all — i.e. the BMD column shows
            #     anything other than "—" (viable, <LNZD/3, NVM, or UREP).
            # The two criteria are independent (see the comment above), so
            # the union catches both "statistically significant" and "has
            # a modeled potency" rows.  Computed here, in the table builder,
            # so the HTML preview (cards.js) and the Typst template read a
            # single boolean rather than each re-deriving the business rule.
            # `is_reportable_bmd` (shared with organ/body weight) decides
            # what counts as a real modeled BMD value.
            emphasize = bool(responsive) or is_reportable_bmd(bmd_text)

            entry = {
                "label": label,
                "doses": sorted_doses,
                "values": values,
                "bmd": bmd_text,
                "bmdl": bmdl_text,
                "responsive": bool(responsive),
                "emphasize": emphasize,
            }
            if trend_marker:
                entry["trend_marker"] = trend_marker

            rows.append(entry)

        serialized[sex] = rows

    # ── Footnotes (typed model — see table_builder_common) ────────────────
    # Order in the list IS the render order; finalize_footnotes assigns the
    # a/b/c... letters to the `lettered` records (legend/definition skipped):
    #
    #   legend      — significance explanation                [Canonical]
    #   legend      — */** marker key                         [Canonical]
    #   definition  — BMD/BMDL abbreviation paragraph          [Canonical]
    #   (a)         — data format                             [Canonical]
    #   (b)         — statistical method (Shirley/Dunn)        [Canonical]
    #   (c,d,...)   — sample-availability, per (sex, dose)     [Canonical]
    #   (next)      — attrition (333/1,000 mg/kg dead)         [Canonical]
    #   (next)      — imputation (BMDExpress on clin-path)     [Extended-canonical]
    #
    # Provenance tiers:
    #   Canonical          — anchored in NIEHS Report 10; the reference PDF
    #                        is the authority.
    #   Extended-canonical — no NIEHS-PDF precedent; covers analysis beyond
    #                        the reference's scope (BMDExpress dose-response
    #                        modeling of clinical-pathology endpoints).  Same
    #                        authority, new addition — see the imputation
    #                        block below.
    footnotes: list[dict] = [
        legend_footnote(SIGNIFICANCE_EXPLANATION),
        legend_footnote(SIGNIFICANCE_MARKER_LEGEND),
        definition_footnote(BMD_DEFINITION),
        lettered_footnote(FOOTNOTE_DATA_FORMAT, "data_format"),
        lettered_footnote(FOOTNOTE_STAT_METHOD_CLINICAL, "stat_method"),
    ]

    # ── Sample-availability + attrition footnotes (shared helpers) ────────
    # [Canonical] — both anchored in NIEHS Report 10.  The detection and
    # footnote-building logic is shared with organ_weight_table.py; see
    # table_builder_common.
    #   - build_sample_availability_footnotes: one deduped footnote per
    #     distinct missing-sample count (a per-(sex,dose) footnote — the old
    #     behavior — produced a dozen near-duplicates for hematology).
    #   - build_attrition_footnote: one footnote for whole dose groups with
    #     no surviving animals; partial-missing doses are NOT double-counted
    #     here (the sample-availability helper filters whole-group doses out).
    # n_row_marker_refs holds the {sex: {dose: footnote_id}} bindings;
    # finalize_footnotes (called later) turns the ids into displayed letters.
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

    # Merge both helpers' n-row marker refs into one dict.
    for sex, dose_refs in sa_refs.items():
        n_row_marker_refs.setdefault(sex, {}).update(dose_refs)
    for sex, dose_refs in attr_refs.items():
        n_row_marker_refs.setdefault(sex, {}).update(dose_refs)

    # ── Imputation footnote [Extended-canonical] ──────────────────────────
    # The BMD/BMDL values come from an inferred dataset in which missing
    # individual values were replaced with the dose-group mean (the truth
    # file leaves them missing; BMDExpress can't fit a curve with gaps).
    # Per Auerbach (Weekly Meeting 7, ~00:28) the report must footnote which
    # dose groups that affected.  marker target is "none" — the affected
    # dose groups are named inline in the text, and the imputation touched
    # the modeling input, not the mean +/- SE shown in the table.
    #
    # imputed_cells is {sex: {dose_str: count}} for this platform, recorded
    # by the BMDProject schema's legacy/truth dedup.
    if imputed_cells:
        affected_doses: set[float] = set()
        total_imputed = 0
        for sex_doses in imputed_cells.values():
            for dose_str, count in sex_doses.items():
                try:
                    affected_doses.add(float(dose_str))
                except (TypeError, ValueError):
                    continue
                total_imputed += count
        if affected_doses:
            dose_list = ", ".join(
                format_dose_label(d, dose_unit)
                for d in sorted(affected_doses)
            )
            value_word = "value" if total_imputed == 1 else "values"
            was_were = "was" if total_imputed == 1 else "were"
            group_word = "group" if len(affected_doses) == 1 else "groups"
            footnotes.append(lettered_footnote(
                f"Benchmark dose modeling used an inferred dataset in which "
                f"{total_imputed} missing individual {value_word} {was_were} "
                f"replaced with the dose-group mean (affected dose "
                f"{group_word}: {dose_list} {dose_unit}).",
                "imputation",
                target="none",
            ))

    # ── Attach marker_refs to the n-rows, then finalize ───────────────────
    # The n-rows were built early (before footnotes existed), so attach each
    # sex's marker_refs to its n-row now.  finalize_footnotes then assigns
    # letters and derives the `markers` dict from marker_refs across all rows.
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
        "title": platform,
        "caption": CAPTION_TEMPLATE.replace("{platform}", platform).replace("{compound}", compound_name),
        "compound": compound_name,
        "dose_unit": dose_unit,
        "first_col_header": "Endpoint",
        "table_data": serialized,
        # Typed footnote list: legend + definition + lettered records, with
        # letters already assigned by finalize_footnotes.  The old separate
        # bmd_definition / significance_* keys are folded in as records.
        "footnotes": footnotes,
    }
