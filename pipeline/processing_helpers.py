"""
Process-integrated pipeline phase functions.

The api_process_integrated endpoint runs a multi-stage pipeline against
the integrated BMDProject — filter, partition, build section cards,
extract genomics + adversity signatures, build BMD summaries.  Each
stage is a function here.  They were originally inlined into the
endpoint as one ~1500-line god function; they were broken out for
readability and testability before this split, and this commit lifts
the eight resulting helpers into a separate module so the endpoint
itself can sit in process_integrated.py at a manageable size.

Pipeline order (as orchestrated by api_process_integrated):

  1. _filter_gene_expression(integrated)
     Strip gene-expression .bm2 experiments from the dict that feeds
     the NTP stats pipeline.  Genomics has its own path (export_genomics
     via Java) — keeping it out of Williams/Dunnett saves minutes.

  2. _partition_by_platform(apical_integrated, source_files, table_data)
     The NTP stats produce {sex -> [TableRow]} — re-key the rows by
     platform using the experimentDescription.platform field as the
     primary signal (with multiple fallback heuristics for old sessions).

  3. _build_section_cards(platform_tables, compound_name, dose_unit,
                          dtxsid, imputed_cells)
     Per platform, decide between dedicated sidecar builders
     (body_weight_table, clinical_pathology_table, organ_weight_table)
     and the generic serializer.  Sidecar builders are preferred because
     the raw per-animal data has Selection / Observation Day / Terminal
     Flag context the pivot discards (see expertise_data_pipeline.md).

  4. _extract_adversity_signatures(integrated, bmd_stats)
     S1500 toxicity-signature category-analysis results from the gene
     expression .bm2.  Organ + sex come from the parent experiment
     (resolved via @ref), NOT name-parsing.

  5. _extract_genomics(integrated, bmd_stats, go_pct, go_min_genes,
                       go_max_genes, go_min_bmd, dtxsid)
     Async — runs the Java export_genomics in a thread pool and
     reshapes the result into {organ_sex -> {genes, go_bp, ...}} with
     user-configured GO filtering.

  6. _build_apical_bmd_summary(platform_tables)
     Per-platform Table 8 rows — flat list of {endpoint, sex, bmd,
     bmdl, ...} sorted by sex then BMDL.

  7. _build_bmds_bmd_summary(bmds_results, platform_tables)
     Merge pybmds output back onto TableRows for the BMDS-modeled
     view (vs. the Java-side category BMDs).

All eight functions are pure-ish: they read inputs, produce outputs,
and the only state they touch is via _session_dir for sidecar
location.  The pool_orchestrator.py shim re-exports them so the
existing test suite (tests/unit/test_partition.py imports
_filter_gene_expression + _partition_by_platform directly) keeps
working unchanged.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import asyncio
import json
import logging
import os
import tempfile

from bmdx_pipe import (
    _BM2_PLATFORM_MAP,
    detect_platform_and_type_from_bm2,
    export_genomics,
    generate_results_narrative,
)

from pipeline.pool_globals import _session_dir
from web_routes.section_serializers import serialize_table_rows
from pipeline.integrated_io import _pick_go_stat, _safe_float, _safe_float_from_bmdl


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline phase functions
# ---------------------------------------------------------------------------
# Originally inlined into api_process_integrated; broken out below in the
# order the endpoint invokes them.

def _filter_gene_expression(integrated: dict) -> dict:
    """
    Return a copy of the integrated BMDProject with gene expression
    experiments removed.

    Gene expression .bm2 data has thousands of probes — running Dunnett's
    test on each would be extremely slow and isn't meaningful for clinical
    endpoints.  Genomics is handled separately by export_genomics().

    Identifies gene expression experiments by checking which experiment names
    DON'T match any clinical platform prefix in _BM2_PLATFORM_MAP.

    Args:
        integrated: The full merged BMDProject dict.

    Returns:
        A shallow copy of integrated with gene expression experiments
        filtered from doseResponseExperiments.  Returns the original dict
        unchanged if no gene expression experiments were found.
    """
    meta = integrated.get("_meta", {})
    source_files = meta.get("source_files", {})
    ge_source = source_files.get("gene_expression")
    if not ge_source:
        return integrated

    # Gene expression experiments have names starting with the organ
    # (e.g., "Liver_PFHxSAm_Male_No0") — identify them by checking
    # which experiments DON'T match any clinical platform prefix.
    ge_exp_names = set()
    for exp in integrated.get("doseResponseExperiments", []):
        exp_name = exp.get("name", "")
        exp_lower = exp_name.lower().replace("_", "")
        matched = False
        for prefix in _BM2_PLATFORM_MAP:
            clean = exp_lower.replace("female", "").replace("male", "").strip()
            if clean.startswith(prefix) or prefix.startswith(clean):
                matched = True
                break
        if not matched:
            ge_exp_names.add(exp_name)

    if not ge_exp_names:
        return integrated

    logger.info(
        "Filtered %d gene expression experiments from NTP stats pipeline",
        len(ge_exp_names),
    )
    return {
        **integrated,
        "doseResponseExperiments": [
            exp for exp in integrated.get("doseResponseExperiments", [])
            if exp.get("name", "") not in ge_exp_names
        ],
    }


def _partition_by_platform(
    apical_integrated: dict,
    source_files: dict,
    table_data: dict[str, list],
) -> dict[str, dict[str, list]]:
    """
    Partition NTP stats TableRows by platform, preserving sex grouping.

    build_table_data() returns {"Male": [TableRow, ...], "Female": [...]}.
    We need to split these into per-platform sections so the UI can create
    separate section cards for Body Weight, Organ Weight, etc.

    Strategy: look at the experiment names in the integrated data to build
    a mapping of endpoint_name -> platform, then partition the table rows.

    Args:
        apical_integrated: The integrated BMDProject with GE experiments filtered out.
        source_files:      The _meta.source_files dict mapping platform -> file info.
        table_data:        The NTP stats output: {sex -> [TableRow, ...]}.

    Returns:
        Nested dict: {platform -> {sex -> [TableRow, ...]}}.
    """
    # Build experiment_name -> platform mapping.
    #
    # Primary: use the authoritative experimentDescription.platform field
    # (set by _stamp_domains in pool_integrator.py from fingerprint data).
    # Fallback for old sessions: try experimentDescription.domain (which
    # in newer sessions is already a platform string), then heuristics.
    exp_name_to_platform: dict[str, str] = {}

    for exp in apical_integrated.get("doseResponseExperiments", []):
        exp_name = exp.get("name", "")

        # --- Primary: authoritative platform from experimentDescription ---
        desc = exp.get("experimentDescription")
        if isinstance(desc, dict):
            # Prefer explicit platform field; fall back to domain field
            # (which in newer sessions contains a platform string like
            # "Body Weight" rather than the old "body_weight_inferred").
            platform_val = desc.get("platform") or desc.get("domain")
            if platform_val:
                exp_name_to_platform[exp_name] = platform_val
                continue

        # --- Fallback: legacy heuristics for old sessions ---
        exp_lower = exp_name.lower()

        # Strip sex suffix/prefix for matching.
        # IMPORTANT: strip "female" BEFORE "male" — "female" contains
        # "male" as a substring, so stripping "male" first leaves "fe".
        stripped = exp_lower.replace("female", "").replace("male", "").replace("_", "").strip()

        platform_for_exp = None
        for prefix, plat in _BM2_PLATFORM_MAP.items():
            if stripped.startswith(prefix) or prefix.startswith(stripped):
                platform_for_exp = plat
                break

        # Fallback: try detect_platform_and_type_from_bm2() which uses
        # the same _BM2_PLATFORM_MAP but with additional normalization.
        if not platform_for_exp:
            detected_platform, detected_dtype = detect_platform_and_type_from_bm2([exp_name])
            if detected_platform:
                platform_for_exp = detected_platform

        # Last resort: check if experiment name overlaps with source_files
        # platform keys (e.g., "Body Weight" → "bodyweight" matches in name).
        if not platform_for_exp:
            for plat_key in source_files:
                plat_normalized = plat_key.lower().replace(" ", "").replace("_", "")
                if plat_normalized in exp_lower.replace("_", ""):
                    platform_for_exp = plat_key
                    break

        if platform_for_exp:
            exp_name_to_platform[exp_name] = platform_for_exp

    # Build endpoint -> platform map using the experiment mapping.
    # Each probe/endpoint in an experiment inherits that experiment's platform.
    endpoint_platform_map: dict[str, str] = {}
    for exp in apical_integrated.get("doseResponseExperiments", []):
        exp_name = exp.get("name", "")
        plat = exp_name_to_platform.get(exp_name)
        if plat:
            for pr in exp.get("probeResponses", []):
                probe_id = pr.get("probe", {}).get("id", "")
                if probe_id:
                    endpoint_platform_map[(exp_name, probe_id)] = plat

    # Build a secondary map: (sex, probe_name) -> platform.
    # Since build_table_data doesn't preserve the experiment name on
    # TableRow, we match back using the probe label.
    sex_probe_platform: dict[tuple[str, str], str] = {}
    for (exp_name, probe_id), plat in endpoint_platform_map.items():
        sex = "Female" if "female" in exp_name.lower() else \
              "Male" if "male" in exp_name.lower() else "Unknown"
        sex_probe_platform[(sex, probe_id)] = plat

    # Partition: {platform: {sex: [TableRow, ...]}}
    platform_tables: dict[str, dict[str, list]] = {}
    for sex, rows in table_data.items():
        for row in rows:
            plat = sex_probe_platform.get((sex, row.label), "unknown")
            platform_tables.setdefault(plat, {}).setdefault(sex, []).append(row)

    return platform_tables


# Map the kebab-case assay AREA keys (REPORT_ASSAY_AREAS) to the display
# platform names used as keys in platform_tables.  The reference's "Select"
# tables (Clinical Chemistry / Hematology / Hormones) each show a hand-curated
# per-sex subset, so all three are assay-filterable through this one rail.
_ASSAY_AREA_TO_PLATFORM: dict[str, str] = {
    "clinical-chemistry": "Clinical Chemistry",
    "hematology": "Hematology",
    "hormones": "Hormones",
}


def apply_apical_filters(
    platform_tables: dict[str, dict[str, list]],
    sex_allow: list[str] | None = None,
    assay_filters: dict[str, list[str] | dict[str, list[str]]] | None = None,
) -> dict[str, dict[str, list]]:
    """
    Apply the report-level SEX and ASSAY allowlists to the partitioned
    ``{platform: {sex: [TableRow]}}`` dict, returning a new filtered dict (the
    input is not mutated).

    This is the SINGLE apical choke point.  It runs right after the NTP-stats
    layer, so everything downstream that reads ``platform_tables`` — the apical
    tables, the BMD summary, the BMDS modeling inputs, and the apical narratives
    — sees the same filtered set and stays consistent.  It is applied
    unconditionally (even on an NTP cache hit), which keeps the NTP cache itself
    sex/assay-agnostic (the same "filter after the agnostic cache" trick the
    genomics post-filter uses).

      - sex_allow: the "apical" area sex list.  Drops every non-allowed sex key
        from every platform (table_builder_common.sex_allowed, exact match).
      - assay_filters: {area: value} for the two assay platforms.  Each value is
        EITHER a flat token list (applies to BOTH sexes) OR a per-sex mapping
        {sex: [tokens]} (the reference's "Select" tables show different endpoints
        per sex).  Drops rows whose endpoint label fails the resolved allowlist
        (table_builder_common.assay_allowed, component-aware).  A per-sex mapping
        that omits a sex leaves that sex's rows unfiltered (only sex_allow governs
        whether the sex shows at all).

    Empty/None for either axis is a no-op for that axis, so an entirely
    unfiltered call returns the tables unchanged (the pre-feature behaviour).
    """
    if not sex_allow and not assay_filters:
        return platform_tables

    from tables.table_builder_common import sex_allowed, assay_allowed

    assay_filters = assay_filters or {}
    out: dict[str, dict[str, list]] = {}
    for platform, sex_rows in platform_tables.items():
        # Resolve this platform's raw assay filter (None ⇒ no row filter).  It is
        # either a flat list (both sexes) or a {sex: [tokens]} per-sex mapping.
        platform_assay = None
        for area, plat_name in _ASSAY_AREA_TO_PLATFORM.items():
            if platform == plat_name:
                platform_assay = assay_filters.get(area)
                break

        new_sex_rows: dict[str, list] = {}
        for sex, rows in sex_rows.items():
            if not sex_allowed(sex, sex_allow):
                continue
            # Per-sex mapping: pick this sex's list; flat list: same for all.
            if isinstance(platform_assay, dict):
                assay_allow = platform_assay.get(str(sex).strip().lower())
            else:
                assay_allow = platform_assay
            if assay_allow:
                rows = [
                    r for r in rows
                    if assay_allowed(
                        r.get("label", "") if isinstance(r, dict)
                        else getattr(r, "label", ""),
                        assay_allow,
                    )
                ]
            new_sex_rows[sex] = rows
        out[platform] = new_sex_rows
    return out


def apply_section_filters(
    sections: list[dict],
    *,
    sex_allow: list[str] | None = None,
    assay_filters: dict | None = None,
    organ_allowlist: list[str] | None = None,
    ow_sex_allow: list[str] | None = None,
    compound_name: str = "",
) -> list[dict]:
    """
    Apply the report-level apical filters to ALREADY-SERIALIZED section cards.

    Phase 2: the sections cache stores the FULL superset (every sex/assay/organ);
    the report-level filters are applied HERE, after the cache read, so a version
    with different filters reuses the same cached superset instead of forcing a
    rebuild.  Operates purely on the serialized card dicts (label / tables_json),
    so it needs no TableRows and can run against a cache-loaded blob.

    Filter dimensions (each a no-op when its allowlist is empty/None):
      - assay_filters {area: [tokens] | {sex: [tokens]}}: drop rows whose label
        fails the resolved allowlist, on the two assay platforms only (Clinical
        Chemistry / Hematology; area→platform via _ASSAY_AREA_TO_PLATFORM).
      - organ_allowlist: drop Organ Weight rows whose organ token fails, and
        RECOMPUTE that card's caption from the surviving rows (the caption reads
        "Liver Weights of Male Rats" vs the generic "…for Male and Female Rats",
        derived from what actually renders — so it must be rebuilt, not kept).
      - ow_sex_allow: prune the Organ Weight card's sexes only.
      - sex_allow: prune every card's sexes (the "apical" area).

    Returns a NEW list of NEW card dicts; the input (cached) cards are not mutated
    so the on-disk superset cache stays intact for the next version.
    """
    if not (sex_allow or assay_filters or organ_allowlist or ow_sex_allow):
        return sections

    from tables.table_builder_common import (
        sex_allowed, assay_allowed, organ_allowed,
    )
    from tables.organ_weight_table import _organ_weight_caption

    assay_filters = assay_filters or {}
    out: list[dict] = []
    for card in sections:
        card = dict(card)  # shallow copy; we rewrite tables_json/caption below
        platform = card.get("platform", "")
        tables = card.get("tables_json")
        if not isinstance(tables, dict):
            out.append(card)
            continue

        # Resolve this platform's assay allowlist (flat list or per-sex mapping).
        platform_assay = None
        for area, plat_name in _ASSAY_AREA_TO_PLATFORM.items():
            if platform == plat_name:
                platform_assay = assay_filters.get(area)
                break

        is_ow = platform == "Organ Weight"
        new_tables: dict[str, list] = {}
        for sex, rows in tables.items():
            # sex pruning: the apical allowlist prunes every card; the
            # organ-weight allowlist prunes only the Organ Weight card.
            if not sex_allowed(sex, sex_allow):
                continue
            if is_ow and not sex_allowed(sex, ow_sex_allow):
                continue

            kept = rows
            # assay row filter (per-sex mapping resolved inside the sex loop).
            # The n / sample-size row (label "n", is_n_row) is structural, not an
            # endpoint — always keep it (apply_apical_filters filtered TableRows
            # before the n-row was synthesized, so it was never dropped).
            if isinstance(platform_assay, dict):
                assay_allow = platform_assay.get(str(sex).strip().lower())
            else:
                assay_allow = platform_assay
            if assay_allow:
                kept = [
                    r for r in kept
                    if not isinstance(r, dict)
                    or r.get("is_n_row")
                    or r.get("label") == "n"
                    or assay_allowed(r.get("label", ""), assay_allow)
                ]
            # organ row filter (Organ Weight only): keep n-rows / Terminal Body
            # Weight context rows; filter organ rows by their leading token.
            if is_ow and organ_allowlist:
                filtered = []
                for r in kept:
                    if not isinstance(r, dict):
                        filtered.append(r); continue
                    label = r.get("label", "")
                    if r.get("is_n_row") or label.startswith("Terminal Body Weight"):
                        filtered.append(r); continue
                    token = label.split(" Absolute")[0].split(" Relative")[0].strip()
                    if organ_allowed(token, organ_allowlist):
                        filtered.append(r)
                kept = filtered
            new_tables[sex] = kept

        card["tables_json"] = new_tables
        # The Organ Weight caption is derived from what renders — rebuild it from
        # the filtered rows so it agrees with the pruned table.
        if is_ow and (organ_allowlist or ow_sex_allow or sex_allow):
            card["caption"] = _organ_weight_caption(new_tables, compound_name)
        out.append(card)
    return out


def prune_card_sexes(card: dict | None, sex_allow: list[str] | None) -> dict | None:
    """
    Drop non-allowed sex keys from a section card's ``tables_json`` in place,
    for the sidecar-built cards that bypass ``platform_tables`` (Tissue
    Concentration, Clinical Observations) — those are NOT reached by
    apply_apical_filters but key their table_data by sex just the same.

    No-op when there's no allowlist, no card, or no dict-shaped tables_json.
    Returns the (possibly mutated) card so it can be used inline.
    """
    if not sex_allow or not card:
        return card
    from tables.table_builder_common import sex_allowed

    tables = card.get("tables_json")
    if isinstance(tables, dict):
        card["tables_json"] = {
            sex: rows for sex, rows in tables.items()
            if sex_allowed(sex, sex_allow)
        }
    return card


def _build_section_cards(
    platform_tables: dict[str, dict[str, list]],
    compound_name: str,
    dose_unit: str,
    dtxsid: str | None = None,
    imputed_cells: dict | None = None,
    organ_allowlist: list[str] | None = None,
    sex_allow: list[str] | None = None,
    ow_sex_allow: list[str] | None = None,
) -> list[dict]:
    """
    Build the UI section cards array: one per platform that has data.

    For each platform, serializes TableRow objects to JSON-friendly dicts
    and generates an auto-written results narrative.

    Special handling for Body Weight: when a tox_study sidecar JSON exists
    (written by tox_study_csv_to_pivot_txt), the body weight section uses
    build_body_weight_table_from_sidecar() instead of the generic path.
    This fixes three mismatches vs the NIEHS reference:
      1. Missing dose groups (333/1000 mg/kg where all animals died)
      2. Inflated N counts (Biosampling Animals included)
      3. Incorrect mean±SE (follows from #2)

    Args:
        platform_tables: The partitioned {platform -> {sex -> [TableRow, ...]}} dict.
        compound_name:   Chemical name for the narrative (e.g., "PFHxSAm").
        dose_unit:       Dose unit string (e.g., "mg/kg").
        dtxsid:          The DTXSID for this session.  Needed to locate sidecar
                         files for body weight.  If None, the generic path is used.
        imputed_cells:   The `_meta.imputed_cells` map from the BMDProject
                         schema — {platform: {sex: {dose: count}}} of dose
                         groups whose legacy file imputed missing values.
                         Threaded to the clinical-pathology builder so it
                         can footnote imputation-backed BMDs.  None when no
                         imputation was detected (or the data was already
                         deduped before this load).
        organ_allowlist: Report-level organ allowlist (lower-cased tokens) for
                         the "organ-weight" area.  Threaded ONLY to the Organ
                         Weight builder (the one apical table grouped by organ).
                         Empty/None ⇒ no filtering.
        sex_allow:       Report-level "apical" sex allowlist.  apply_apical_filters
                         already narrowed the platform_tables this consumes, but
                         the Body Weight / Organ Weight sidecar builders iterate
                         the sidecar files directly over a fixed ("Male","Female")
                         loop, so their tables_json can still carry a dropped
                         sex.  Every built card's tables_json is pruned by this
                         at the end for a uniform guarantee.  Empty/None ⇒ no-op.
        ow_sex_allow:    Report-level "organ-weight" AREA sex allowlist — narrows
                         ONLY the Organ Weight table's sexes (the reference's
                         Table 3 shows just the responsive sex, e.g. male), while
                         leaving every other apical table's sexes intact.
                         Distinct from `sex_allow` (the "apical" area, which
                         prunes ALL cards).  Empty/None ⇒ both sexes.

    Returns:
        List of section dicts, each with platform, title, tables_json, narrative.
        The platform string IS the display title (e.g., "Body Weight").
    """
    sections = []
    for platform, sex_rows in sorted(platform_tables.items()):
        # All endpoints appear in every table (CLAUDE.md business rule).
        # The NTP responsive gate does NOT control row inclusion — it
        # controls significance markers and the BMD summary only.
        # responsive_rows is kept as a convenience for the narrative
        # generator, which describes only the significant findings.
        responsive_rows = {
            sex: [r for r in rows if r.responsive]
            for sex, rows in sex_rows.items()
        }
        # Drop sex groups that have no responsive endpoints (for narrative only)
        responsive_rows = {s: rs for s, rs in responsive_rows.items() if rs}

        # ── Body Weight: use sidecar builder when available ──────────────
        # Body weight bypasses the responsive filter because the NIEHS
        # reference ALWAYS includes Table 2 (body weights) regardless of
        # whether the statistical gate passed.  The gate controls only
        # the BMD column values (ND vs numeric), not table inclusion.
        # When responsive_rows is empty (gate didn't pass), the sidecar
        # builder still produces the full table with ND in BMD columns.
        # The sidecar JSON has per-animal metadata (Selection, Observation
        # Day, Terminal Flag) that the generic build_table_data path loses.
        # This produces correct N counts (Core Animals only), all dose
        # groups (including those where animals died), and proper attrition
        # footnotes.
        if platform == "Body Weight" and dtxsid:
            from tables.body_weight_table import (
                build_body_weight_table_from_sidecar,
                find_sidecar_paths,
            )
            session_dir = str(_session_dir(dtxsid))
            sidecar_paths = find_sidecar_paths(session_dir, platform="Body Weight")

            if sidecar_paths:
                # Extract BMD/BMDL results from the pipeline's TableRow data
                # so the sidecar builder can display them in the BMD columns.
                # The pipeline computes BMD from the pivoted data — we just
                # carry those results through to the sidecar-built table.
                bmd_results: dict[str, dict[str, str]] = {}
                for sex, rows in responsive_rows.items():
                    for row in rows:
                        # row.label is "SD0", "SD5", etc.
                        if row.label not in bmd_results:
                            bmd_results[row.label] = {
                                "bmd": row.bmd_str if row.bmd_str else "ND",
                                "bmdl": row.bmdl_str if row.bmdl_str else "ND",
                            }

                bw_result = build_body_weight_table_from_sidecar(
                    sidecar_paths,
                    bmd_results=bmd_results,
                    compound_name=compound_name,
                    dose_unit=dose_unit,
                )

                # The sidecar builder returns a full apical_sections entry
                # (title, caption, table_data, footnotes, bmd_definition,
                # etc.).  We need to reshape it to match the section card
                # format expected by the UI.
                # Pass only responsive rows to the narrative generator.
                # When empty (gate didn't pass), it produces "no significant
                # changes" text — which is correct.  DO NOT fall back to
                # sex_rows because that includes the old pre-sidecar pivot
                # rows which may have stale responsive=True flags.
                narrative = generate_results_narrative(
                    responsive_rows, compound_name, dose_unit,
                )
                sections.append({
                    "platform": platform,
                    "title": platform,
                    "tables_json": bw_result["table_data"],
                    "narrative": narrative,
                    # Pass through body-weight-specific fields that the
                    # Typst template and UI use for specialized rendering.
                    # `footnotes` is the typed footnote list (legend /
                    # definition / lettered records); the BMD definition is
                    # a `definition` record inside it, not a separate key.
                    "first_col_header": bw_result.get("first_col_header"),
                    "caption": bw_result.get("caption"),
                    "footnotes": bw_result.get("footnotes"),
                })
                logger.info(
                    "Body Weight section built from sidecar (%d sexes, %d footnotes)",
                    len(bw_result["table_data"]),
                    len(bw_result.get("footnotes", [])),
                )
                continue  # skip generic path below

        # ── Clinical Pathology platforms (Tables 4/5/6): shared sidecar builder ─
        # Clinical Chemistry, Hematology, and Hormones share identical table
        # structure: sex-grouped rows, n-row, endpoint rows with mean±SE and
        # significance markers, BMD/BMDL columns.  The sidecar provides correct
        # Core Animals N counts; the NTP stats provide mean±SE with markers.
        if platform in ("Clinical Chemistry", "Hematology", "Hormones") and dtxsid:
            from tables.table_builder_common import find_sidecar_paths as _find_sidecar
            from tables.clinical_pathology_table import build_clinical_pathology_table_from_sidecar

            session_dir = str(_session_dir(dtxsid))
            sidecar_paths = _find_sidecar(session_dir, platform=platform)

            if sidecar_paths:
                # All endpoints appear in the table (not just responsive).
                # The responsive gate controls BMD column values (ND vs numeric),
                # not row inclusion — matching the body weight pattern.
                # imputed_cells[platform] tells the builder which dose groups
                # had values imputed in the legacy file, for the imputation
                # footnote; None/missing means no imputation for this platform.
                platform_imputed = (imputed_cells or {}).get(platform)
                cp_result = build_clinical_pathology_table_from_sidecar(
                    platform=platform,
                    sidecar_paths=sidecar_paths,
                    ntp_stats=sex_rows,
                    compound_name=compound_name,
                    dose_unit=dose_unit,
                    imputed_cells=platform_imputed,
                )

                if cp_result.get("table_data"):
                    narrative = generate_results_narrative(
                        responsive_rows, compound_name, dose_unit,
                    )
                    sections.append({
                        "platform": platform,
                        "title": platform,
                        "tables_json": cp_result["table_data"],
                        "narrative": narrative,
                        "first_col_header": cp_result.get("first_col_header"),
                        "caption": cp_result.get("caption"),
                        # Typed footnote list — the significance legend and
                        # BMD definition are `legend`/`definition` records
                        # inside it, no longer separate keys.
                        "footnotes": cp_result.get("footnotes"),
                    })
                    logger.info(
                        "%s section built from sidecar (%d sexes)",
                        platform, len(cp_result["table_data"]),
                    )
                    continue

        # ── Organ Weight (Table 3): sidecar builder with relative weights ──
        # The organ weight builder computes absolute + relative (per-animal
        # absolute/TBW × 1000) weights from raw sidecar data.  All organs
        # appear; the responsive gate controls BMD column values only.
        # Terminal Body Weight is always shown as a context row.
        if platform == "Organ Weight" and dtxsid:
            from tables.table_builder_common import find_sidecar_paths as _find_sidecar
            from tables.organ_weight_table import build_organ_weight_table_from_sidecar

            session_dir = str(_session_dir(dtxsid))
            sidecar_paths = _find_sidecar(session_dir, platform="Organ Weight")

            if sidecar_paths:
                ow_result = build_organ_weight_table_from_sidecar(
                    sidecar_paths=sidecar_paths,
                    ntp_stats=sex_rows,
                    compound_name=compound_name,
                    dose_unit=dose_unit,
                    organ_allowlist=organ_allowlist,
                    sex_allow=ow_sex_allow,
                )

                if ow_result and ow_result.get("table_data"):
                    narrative = generate_results_narrative(
                        responsive_rows, compound_name, dose_unit,
                    )
                    sections.append({
                        "platform": platform,
                        "title": platform,
                        "tables_json": ow_result["table_data"],
                        "narrative": narrative,
                        "first_col_header": ow_result.get("first_col_header"),
                        "caption": ow_result.get("caption"),
                        # Typed footnote list — the significance legend and
                        # BMD definition are `legend`/`definition` records
                        # inside it, no longer separate keys.
                        "footnotes": ow_result.get("footnotes"),
                    })
                    logger.info(
                        "Organ Weight section built from sidecar (%d sexes)",
                        len(ow_result["table_data"]),
                    )
                    continue

        # ── Generic fallback for platforms without dedicated builders ───────
        # Also handles cases where sidecar data isn't available (e.g., data
        # uploaded as .bm2 without going through the integration pipeline).
        # All endpoints appear in the table (business rule) — sex_rows has
        # every row, not just responsive ones.  The narrative uses
        # responsive_rows so it only describes significant findings.
        if not sex_rows:
            continue

        tables_json = serialize_table_rows(sex_rows)
        narrative = generate_results_narrative(responsive_rows, compound_name, dose_unit)
        sections.append({
            "platform": platform,
            "title": platform,
            "tables_json": tables_json,
            "narrative": narrative,
        })
    # Uniform apical sex prune — covers the sidecar builders (Body/Organ Weight)
    # whose fixed ("Male","Female") loop ignores the narrowed platform_tables.
    # A no-op for the already-narrow clin-path cards and when sex_allow is empty.
    if sex_allow:
        for card in sections:
            prune_card_sexes(card, sex_allow)
    return sections


def _extract_adversity_signatures(
    integrated: dict,
    bmd_stats: list[str],
) -> dict[str, list[dict]]:
    """
    Extract S1500 adversity signature results from the integrated BMDProject.

    Adversity signatures are a second type of category analysis that lives
    alongside GO BP results in the gene expression .bm2 file.  They test
    whether the dose-response data resembles predefined S1500 toxicity
    signatures (e.g., Proliferation, Overt Toxicity).

    Uses two pieces of existing infrastructure rather than name-parsing:
      1. categoryAnalysisResults[i].doseResponseExperiment (@ref int) resolves
         to the parent doseResponseExperiment, which already has LLM-inferred
         experimentDescription (organ, sex, platform).  Organ/sex come from
         there — no name parsing required.
      2. integrated["_category_lookup"] (written by ExportCategories via
         integrate_pool) already contains BMD statistics for every category
         keyed as "{experiment_prefix}|{category_title}".

    The only name-based discriminator is checking for "Adversity Signatures"
    in the categoryAnalysisResults.name field — Java does not populate
    experimentDescription on categoryAnalysisResults, so there is no metadata
    field that marks the entry type.  This is an acknowledged gap; the @ref
    path above is the canonical organ/sex source.

    Args:
        integrated:  The full merged BMDProject dict (with _category_lookup).
        bmd_stats:   Ordered list of BMD statistic keys; first key is primary.

    Returns:
        Dict mapping "organ_sex" keys (e.g., "kidney_female") to a list of
        signature result dicts, one per signature category (e.g., Proliferation,
        Overt Toxicity).  Empty dict when no adversity signature data exists.
    """
    # Build @ref → doseResponseExperiment index so we can resolve the
    # integer reference stored in categoryAnalysisResults.doseResponseExperiment.
    ref_to_exp: dict[int, dict] = {}
    for exp in integrated.get("doseResponseExperiments", []):
        ref = exp.get("@ref")
        if ref is not None:
            ref_to_exp[ref] = exp

    flat_cat = integrated.get("_category_lookup", {})
    primary_stat = bmd_stats[0] if bmd_stats else "median"

    result: dict[str, list[dict]] = {}

    for cat_entry in integrated.get("categoryAnalysisResults", []):
        name = cat_entry.get("name", "")
        # Only process adversity-signature category analyses.  Gene expression
        # GO BP entries share the same parent experiment but have a different
        # name structure (they contain "GENE" not "Adversity Signatures").
        if "Adversity Signatures" not in name:
            continue

        # Resolve the parent experiment to get LLM-inferred organ and sex.
        parent_ref = cat_entry.get("doseResponseExperiment")
        if parent_ref is None:
            continue
        parent_exp = ref_to_exp.get(parent_ref)
        if not parent_exp:
            continue

        desc = parent_exp.get("experimentDescription") or {}
        organ = (desc.get("organ") or "").lower()
        sex = (desc.get("sex") or "").lower()
        if not organ or not sex:
            logger.warning(
                "Adversity signature entry %r: parent @ref=%s has no organ/sex in "
                "experimentDescription — skipping",
                name[:60], parent_ref,
            )
            continue

        key = f"{organ}_{sex}"
        if key not in result:
            result[key] = []

        exp_base_name = parent_exp.get("name", "")

        # Each inner item in categoryAnalsyisResults (note Java typo) is one
        # signature category (e.g., "S1500 Adversity Signature 1 — Proliferation").
        for sig_item in cat_entry.get("categoryAnalsyisResults", []):
            cat_id_obj = sig_item.get("categoryIdentifier") or {}
            sig_id = cat_id_obj.get("id", "")        # e.g., "S1500 Adversity Signature 1"
            sig_title = cat_id_obj.get("title", "")  # e.g., "Proliferation"

            # Look up pre-extracted BMD statistics from the category lookup.
            # Keys are "{experiment_name}|{category_title}" — the lookup was
            # built by ExportCategories during integrate_pool().
            lookup_key = f"{exp_base_name}|{sig_title}"
            lookup_entry = flat_cat.get(lookup_key) or {}

            bmd_stats_block = lookup_entry.get("bmd_stats") or {}
            bmdl_stats_block = lookup_entry.get("bmdl_stats") or {}
            bmdu_stats_block = lookup_entry.get("bmdu_stats") or {}

            # Select the requested primary statistic; fall back to mean if absent.
            bmd_val = bmd_stats_block.get(primary_stat) or bmd_stats_block.get("mean")
            bmdl_val = bmdl_stats_block.get(primary_stat) or bmdl_stats_block.get("mean")
            bmdu_val = bmdu_stats_block.get(primary_stat) or bmdu_stats_block.get("mean")

            n_passed = sig_item.get("genesThatPassedAllFilters") or 0
            n_genes = sig_item.get("geneAllCount") or 0

            result[key].append({
                # Human-readable label for the signature (e.g., "Proliferation")
                "title": sig_title,
                # Full S1500 identifier (e.g., "S1500 Adversity Signature 1")
                "signature_id": sig_id,
                # Whether this signature has a BMD result (n_passed > 0)
                "active": n_passed > 0,
                # Genes from the reference set that passed all BMDExpress filters
                "n_passed": n_passed,
                # Total genes in the S1500 reference signature set
                "n_genes": n_genes,
                # Fraction of reference set with BMD values (0–100)
                "percentage": sig_item.get("percentage"),
                # BMD statistics (primary statistic selected above)
                "bmd": bmd_val,
                "bmdl": bmdl_val,
                "bmdu": bmdu_val,
                # Full stat blocks so the UI can switch statistics without reload
                "bmd_stats": bmd_stats_block,
                "bmdl_stats": bmdl_stats_block,
                "bmdu_stats": bmdu_stats_block,
                # Direction of the signature response (up/down/conflict)
                "direction": lookup_entry.get("direction", ""),
                # Fisher's exact two-tail p-value for signature enrichment
                "fishers_p": sig_item.get("fishersExactTwoTailPValue"),
            })

    return result


# Cutoff-disabled sentinel values used to extract the FULL GO superset (phase 4):
# every GO term survives the extraction filter, so the genomics cache is cutoff-
# agnostic and the real cutoffs are applied at read (apply_genomics_cutoffs).
_GO_CUTOFFS_OFF = dict(go_pct=0.0, go_min_genes=0, go_max_genes=10**9, go_min_bmd=0)


def apply_genomics_cutoffs(
    genomics_sections: dict,
    *,
    go_pct: float,
    go_min_genes: int,
    go_max_genes: int,
    go_min_bmd: int,
) -> dict:
    """
    Apply the GO-category cutoffs to a cutoff-AGNOSTIC genomics superset (phase 4).

    The genomics cache now stores every GO term (extracted with cutoffs off), with
    each ``gene_sets_chart_by_stat`` row carrying ``n_genes`` / ``n_genes_with_bmd``.
    This re-applies the version's cutoffs the SAME way _extract_genomics used to at
    compute time — dropping rows that fail min/max total genes, min BMD-gene count,
    or the % threshold — then re-slices the top-10 ``gene_sets_by_stat`` with fresh
    positional ranks.  A version can thus change cutoffs with no Java re-extraction.

    Returns a NEW dict of NEW section dicts; the cached superset is not mutated.
    Cutoffs that are all at their permissive sentinel (0/0/inf/0) are a no-op.
    """
    out: dict = {}
    for key, sec in (genomics_sections or {}).items():
        sec = dict(sec)
        chart_by_stat = sec.get("gene_sets_chart_by_stat") or {}
        new_chart: dict[str, list] = {}
        new_top: dict[str, list] = {}
        for stat, rows in chart_by_stat.items():
            kept = []
            for r in rows:
                n_total = r.get("n_genes", 0) or 0
                n_passed = r.get("n_genes_with_bmd", 0) or 0
                if n_total < go_min_genes or n_total > go_max_genes:
                    continue
                if n_passed < go_min_bmd:
                    continue
                pct = (n_passed / n_total * 100) if n_total > 0 else 0
                if pct < go_pct:
                    continue
                kept.append(r)
            # Rows arrive already BMD-sorted (extraction sorts before caching);
            # filtering preserves that order.  Strip any stale rank, re-slice top-10.
            new_chart[stat] = [{k: v for k, v in r.items() if k != "rank"} for r in kept]
            new_top[stat] = [
                {"rank": i + 1, **{k: v for k, v in r.items() if k != "rank"}}
                for i, r in enumerate(new_chart[stat][:10])
            ]
        sec["gene_sets_chart_by_stat"] = new_chart
        sec["gene_sets_by_stat"] = new_top
        out[key] = sec
    return out


async def _extract_genomics(
    dtxsid: str,
    integrated: dict,
    bmd_stats: list[str],
    go_pct: float,
    go_min_genes: int,
    go_max_genes: int,
    go_min_bmd: int,
) -> dict:
    """
    Extract gene expression genomics data from the integrated .bm2 file.

    If the integration included gene_expression, runs the BMDExpress 3 Java
    export to extract per-gene BMD and GO Biological Process category results.
    Applies user-configured GO filtering cutoffs, then builds per-organ/sex
    sections with ranked gene_sets tables and top_genes lists.

    Args:
        dtxsid:       The DTXSID for this session.
        integrated:   The full merged BMDProject dict.
        bmd_stats:    List of BMD statistic keys to generate tables for.
        go_pct:       Minimum % of genes in a category that must have BMD values.
        go_min_genes: Minimum total genes annotated to the GO category.
        go_max_genes: Maximum total genes (excludes overly broad categories).
        go_min_bmd:   Minimum genes with a BMD value in the category.

    Returns:
        Dict mapping "organ_sex" keys to genomics section dicts.
        Empty dict if no gene expression data exists.
    """
    genomics_sections = {}
    meta = integrated.get("_meta", {})
    ge_source = meta.get("source_files", {}).get("gene_expression")

    # Only proceed if gene expression data was included at the bm2 tier
    if not ge_source or ge_source.get("tier") != "bm2":
        return genomics_sections

    ge_filename = ge_source.get("filename", "")
    ge_path = _session_dir(dtxsid) / "files" / ge_filename

    if not ge_path.exists():
        return genomics_sections

    # Run the Java export in a thread pool (JVM startup ~0.5s)
    tmp_json = tempfile.NamedTemporaryFile(
        delete=False, suffix=".json", prefix="genomics_",
    )
    tmp_json.close()

    loop = asyncio.get_running_loop()
    try:
        ge_result = await loop.run_in_executor(
            None, export_genomics, str(ge_path), tmp_json.name,
        )

        # Reshape into the format the UI expects: keyed by organ_sex
        for exp in ge_result.get("experiments", []):
            organ = exp.get("organ", "unknown").lower()
            sex = exp.get("sex", "unknown").lower()
            key = f"{organ}_{sex}"

            # Sort genes by BMD ascending (lowest = most sensitive)
            genes = sorted(
                exp.get("genes", []),
                key=lambda g: _safe_float(g.get("bmd")),
            )

            # Filter GO terms by user-configured cutoffs
            raw_go = exp.get("go_bp", [])
            filtered_go = []
            for g in raw_go:
                n_total = g.get("n_genes", 0) or 0
                n_passed = g.get("n_passed", 0) or 0
                if n_total < go_min_genes or n_total > go_max_genes:
                    continue
                if n_passed < go_min_bmd:
                    continue
                pct = (n_passed / n_total * 100) if n_total > 0 else 0
                if pct < go_pct:
                    continue
                filtered_go.append(g)

            # Build an all-caps direction lookup from the per-gene results.
            # gene_symbols in GO rows use lowercase (e.g. "cyp2b1"), while
            # all_genes uses mixed case (e.g. "CYP2B1").  Normalising both to
            # uppercase avoids silent mismatches when counting n_up/n_down.
            gene_dir_upper = {
                g["gene_symbol"].upper(): g.get("direction", "")
                for g in genes
            }

            # Build a separate gene_sets table for each requested BMD statistic.
            # Categories where the stat is null (not computed by BMDExpress) are
            # excluded from that table entirely rather than falling back.
            #
            # Two fields are written per stat:
            #   gene_sets_by_stat      — top-20 rows with rank, for report tables + LLM
            #   gene_sets_chart_by_stat — ALL passing rows (no cap), for UMAP + scatter
            #     charts.  Without the full set, charts only show the 20 table entries
            #     instead of the complete responsive GO term landscape.
            gene_sets_by_stat: dict[str, list] = {}
            gene_sets_chart_by_stat: dict[str, list] = {}
            for stat in bmd_stats:
                stat_go = [
                    g for g in filtered_go
                    if _pick_go_stat(g, "bmd", stat) is not None
                ]
                stat_go.sort(
                    key=lambda g: _safe_float(_pick_go_stat(g, "bmd", stat)),
                )

                # Build full row list first (no cap); slice for tables below.
                all_rows = []
                for g in stat_go:
                    # Count up/down among member genes that have a BMD.
                    # gene_symbols is a semicolon-separated string of the genes
                    # that passed all BMDExpress filters — the same population
                    # reflected in n_passed/n_genes_with_bmd.
                    member_syms = [
                        s.upper() for s in (g.get("gene_symbols") or "").split(";") if s
                    ]
                    n_up = sum(1 for s in member_syms if gene_dir_upper.get(s) == "up")
                    n_down = sum(1 for s in member_syms if gene_dir_upper.get(s) == "down")

                    all_rows.append({
                        "go_id": g["go_id"],
                        "go_term": g["go_term"],
                        "bmd": _pick_go_stat(g, "bmd", stat),
                        "bmdl": _pick_go_stat(g, "bmdl", stat),
                        # bmdu completes the reference's "Median BMDL–BMDU" range
                        # column (Table 9/10).  _pick_go_stat is generic over
                        # bmd/bmdl/bmdu and reads bmdu_stats / bmdu_median.
                        "bmdu": _pick_go_stat(g, "bmdu", stat),
                        "n_genes": g.get("n_genes", 0),
                        "n_genes_with_bmd": g.get("n_passed", 0),
                        "direction": g.get("direction", ""),
                        "n_up": n_up,
                        "n_down": n_down,
                        "fishers_p": g.get("fishers_two_tail"),
                        "genes": g.get("gene_symbols", ""),
                    })

                # Full list for charts — no cap, no rank (rank is table-specific).
                gene_sets_chart_by_stat[stat] = all_rows

                # Top-10 slice for report tables; rank is positional within this
                # subset.  The reference (Tables 9/10) shows the top 10 gene sets.
                gene_sets_by_stat[stat] = [
                    {"rank": i + 1, **r} for i, r in enumerate(all_rows[:10])
                ]

            genomics_sections[key] = {
                "organ": organ,
                "sex": sex,
                "total_probes": exp.get("total_probes", 0),
                "total_responsive_genes": len(genes),
                "gene_sets_by_stat": gene_sets_by_stat,
                "gene_sets_chart_by_stat": gene_sets_chart_by_stat,
                # top_genes: ranked subset (top 10) shown in the gene table.
                # The reference (Tables 11/12) shows the top 10 genes and carries
                # the probe id (e.g. "A2M_7932") as its own column.
                "top_genes": [
                    {
                        "rank": i + 1,
                        "gene_symbol": g["gene_symbol"],
                        "probe_id": g.get("probe_id", ""),
                        "bmd": g.get("bmd"),
                        "bmdl": g.get("bmdl"),
                        "bmdu": g.get("bmdu"),
                        "direction": g.get("direction", ""),
                        "fold_change": g.get("fold_change"),
                        "r_squared": g.get("r_squared"),
                    }
                    for i, g in enumerate(genes[:10])
                ],
                # all_genes: full responsive gene list for pathway/GO enrichment
                # in build_genomics_interpretation(). Kept lean (no rank/r²/bmdu)
                # because these are only used for enrichment input, not display.
                "all_genes": [
                    {
                        "gene_symbol": g["gene_symbol"],
                        "bmd": g.get("bmd"),
                        "bmdl": g.get("bmdl"),
                        "direction": g.get("direction", ""),
                        "fold_change": g.get("fold_change"),
                    }
                    for g in genes  # full list, not genes[:20]
                ],
            }
    finally:
        os.unlink(tmp_json.name)

    # Attach adversity signature results to each organ/sex section.
    # This reads from integrated["_category_lookup"] and the
    # categoryAnalysisResults @ref linkage — no additional Java call needed.
    adversity = _extract_adversity_signatures(integrated, bmd_stats)
    for key, sigs in adversity.items():
        if key in genomics_sections:
            genomics_sections[key]["adversity_signatures"] = sigs
        else:
            # Organ has adversity data but no GO BP results (edge case).
            # Create a minimal section so the data isn't silently dropped.
            organ, sex = key.split("_", 1) if "_" in key else (key, "")
            genomics_sections[key] = {
                "organ": organ,
                "sex": sex,
                "total_probes": 0,
                "total_responsive_genes": 0,
                "gene_sets_by_stat": {},
                "gene_sets_chart_by_stat": {},
                "top_genes": [],
                "all_genes": [],
                "adversity_signatures": sigs,
            }

    return genomics_sections



# Endpoint-label normalizations for the apical BMD summary (Table 8).  The raw
# row labels are the per-platform endpoint names ("Liver", "Neutrophil Count",
# "Triiodothyronine"); the reference Table 8 uses fuller, title-cased forms and
# — for organ weights — the "Absolute <Organ> Weight" phrasing (relative weight
# gets its own row when modeled).  Keys are matched case-insensitively on the raw
# label; unmatched labels pass through unchanged.
_SUMMARY_LABEL_OVERRIDES = {
    "triiodothyronine": "Total Triiodothyronine",
    "total triiodothyronine": "Total Triiodothyronine",
    "neutrophil count": "Neutrophils",
    "neutrophils": "Neutrophils",
    "sorbitol dehydrogenase": "Sorbitol Dehydrogenase",
    "manual hematocrit": "Manual Hematocrit",
    "total thyroxine": "Total Thyroxine",
    "free thyroxine": "Free Thyroxine",
    "thyroid stimulating hormone": "Thyroid Stimulating Hormone",
}

# Organ tokens that, on the Organ Weight platform, name an absolute organ weight.
_ORGAN_WEIGHT_TOKENS = {"liver", "kidney", "heart", "spleen", "thymus",
                        "adrenal", "brain", "lung", "testis", "epididymis"}


def _summary_endpoint_label(label: str, platform: str) -> str:
    """Normalize a raw endpoint label to the reference Table 8 phrasing.

    Organ-weight rows carry a bare organ token ("Liver"); the reference names the
    modeled absolute weight ("Absolute Liver Weight").  Other platforms get a
    small fixed set of title-case / full-name overrides.  Anything unmatched is
    returned unchanged."""
    raw = (label or "").strip()
    key = raw.lower()
    if platform == "Organ Weight":
        # Strip a laterality suffix ("Kidney-Right" -> "Kidney") for the token
        # test; the reference reports whole-organ weights.
        base = raw.split("-")[0].strip()
        if base.lower() in _ORGAN_WEIGHT_TOKENS:
            return f"Absolute {base} Weight"
    return _SUMMARY_LABEL_OVERRIDES.get(key, raw)


def _build_apical_bmd_summary(platform_tables: dict[str, dict[str, list]]) -> list[dict]:
    """
    Build the apical BMD summary (Table 8 equivalent) from BMDExpress 3 results.

    Collects BMD, BMDL, LOEL, NOEL, direction from ALL platform TableRows into
    a flat list for the separate BMD summary card.  Matches the NIEHS reference
    report structure where platform tables (Tables 2-7) show dose-response data
    and Table 8 summarizes BMDs.

    Only includes endpoints that have a BMD result OR significant trend/pairwise
    findings (LOEL exists).  Endpoints with neither are uninteresting.

    Anomalous BMDs (curve-fit values implausibly lower than the statistical
    NOEL/LOEL — model artifacts) are replaced with "UREP" (Unreliable
    Extrapolation) markers in the BMD/BMDL columns and the direction is
    blanked.  This matches NIEHS Report 10's Table 8 convention: keep the
    row so the LOEL/NOEL columns are still informative, but flag that the
    curve-fit BMD shouldn't be trusted.

    Sort order matches the reference report: rows with reliable numeric
    BMDs first (ascending by BMD), then unreliable rows (UREP/NVM) sorted
    by LOEL ascending — "Sorted by BMD or LOEL from Low to High".
    """
    # Import the anomaly heuristic from methods_report — same threshold
    # the abstract Results uses to drop endpoints from the "effects
    # included..." list, so the body table and abstract stay in sync.
    from narrative.methods_report import _is_anomalous_bmd

    raw_entries: list[dict] = []
    for platform, sex_rows in sorted(platform_tables.items()):
        for sex, rows in sex_rows.items():
            for row in rows:
                # ── Inclusion gate (matches the reference Table 8 row set) ──
                # An endpoint qualifies when EITHER it passed the NTP
                # responsive gate (significant trend + pairwise, so it has a
                # trend DIRECTION) OR BMDExpress produced a modeled result
                # (bmd_status is a real code: viable / NVM / UREP / NR).  A
                # bare LOEL from a lone pairwise hit with no trend direction
                # and no model (bmd_status None, direction '') is NOT enough —
                # that is what leaked spurious rows like "Kidney-Right" and
                # female "Free Thyroxine" into the summary.
                reportable_status = row.bmd_status not in (None, "failure")
                if not row.responsive and not reportable_status:
                    continue
                # Body-weight endpoints are context only, never apical BMD
                # candidates — the reference omits Terminal Body Weight and the
                # per-study-day body-weight rows from Table 8 even though the
                # terminal-day decrease is statistically responsive.
                if platform == "Body Weight" or row.label == "Terminal Body Weight":
                    continue
                raw_entries.append({
                    "endpoint": _summary_endpoint_label(row.label, platform),
                    "sex": sex,
                    "platform": platform,
                    "bmd": row.bmd_str,
                    "bmdl": row.bmdl_str,
                    "bmd_status": row.bmd_status,
                    "loel": row.loel,
                    "noel": row.noel,
                    "direction": row.direction,
                })

    # --- Apply UREP marking ---
    # An endpoint becomes UREP when the BMD parses as a finite number but
    # falls implausibly far below the statistically-observed NOEL/LOEL.
    # The original numeric values are preserved on the entry as
    # bmd_original / bmdl_original in case downstream consumers want them.
    for entry in raw_entries:
        if _is_anomalous_bmd(entry):
            entry["bmd_original"] = entry["bmd"]
            entry["bmdl_original"] = entry["bmdl"]
            entry["bmd"] = "UREP"
            entry["bmdl"] = "UREP"
            entry["direction"] = "–"  # en dash — matches reference Table 8
            entry["anomalous"] = True

    # --- Sort: reliable BMDs first (ascending), then by LOEL ascending ---
    # Reliable = numeric, parseable, non-empty bmd string.  Reference
    # Table 8 caption: "Sorted by BMD or LOEL from Low to High".
    def _sort_key(e: dict) -> tuple[int, float]:
        bmd_raw = e.get("bmd")
        try:
            bmd_f = float(str(bmd_raw).strip()) if bmd_raw is not None else float("inf")
            # NaN / inf → treat as non-reliable so they sort by LOEL
            import math as _math
            if _math.isnan(bmd_f) or _math.isinf(bmd_f):
                raise ValueError
            return (0, bmd_f)  # bucket 0: reliable BMDs
        except (TypeError, ValueError):
            loel = e.get("loel")
            try:
                loel_f = float(loel) if loel is not None else float("inf")
            except (TypeError, ValueError):
                loel_f = float("inf")
            return (1, loel_f)  # bucket 1: unreliable, sorted by LOEL

    summary: list[dict] = []
    # Sort within each sex independently so the table groups by sex,
    # with each sex's rows sorted by the BMD-or-LOEL rule.  Sex order
    # itself is fixed (Male, Female) per NIEHS convention.
    for sex in ("Male", "Female"):
        sex_entries = [e for e in raw_entries if e.get("sex") == sex]
        sex_entries.sort(key=_sort_key)
        summary.extend(sex_entries)

    return summary


def _build_bmds_bmd_summary(
    platform_tables: dict[str, dict[str, list]],
    bmds_results: dict,
) -> list[dict]:
    """
    Build the BMDS-based BMD summary (second Table 8) using pybmds results.

    Same structure as the BMDExpress 3 summary, but using EPA BMDS continuous
    model results.  Only includes endpoints where pybmds produced a result AND
    there's either a viable model or a significant LOEL.

    Formats BMD/BMDL strings matching NIEHS conventions:
      - viable: numeric value (e.g., "12.3")
      - NR:     "<lowest_nonzero_dose/3" (e.g., "<0.1")
      - UREP:   "UREP" (unreliable endpoint)
      - NVM:    "NVM" (no viable model)
    """
    if not bmds_results:
        return []

    summary = []
    for platform, sex_rows in sorted(platform_tables.items()):
        for sex, rows in sex_rows.items():
            # Sort within each sex group by BMDL (ascending), matching
            # the apical BMD summary sort order.
            sorted_rows = sorted(
                rows,
                key=lambda r: _safe_float_from_bmdl(r.bmdl_str),
            )
            for row in sorted_rows:
                bmds_key = f"{sex}::{row.label}"
                bmds_res = bmds_results.get(bmds_key)
                if not bmds_res:
                    continue

                # Inclusion gate: significant LOEL or viable BMDS result
                has_viable_bmds = bmds_res["status"] == "viable"
                has_loel = row.loel is not None
                if not has_viable_bmds and not has_loel:
                    continue

                # Format BMD/BMDL strings matching NIEHS conventions
                status = bmds_res["status"]
                if status == "viable" and bmds_res["bmd"] is not None:
                    bmd_str = f"{bmds_res['bmd']:.3g}"
                    bmdl_str = f"{bmds_res['bmdl']:.3g}" if bmds_res["bmdl"] else "—"
                elif status == "NR":
                    nonzero = [d for d in row.values_by_dose if d > 0]
                    lnzd = min(nonzero) if nonzero else 0
                    bmd_str = f"<{lnzd / 3:.3g}" if lnzd > 0 else "NR"
                    bmdl_str = "—"
                elif status == "UREP":
                    bmd_str = "UREP"
                    bmdl_str = "UREP"
                else:
                    bmd_str = "NVM"
                    bmdl_str = "NVM"

                summary.append({
                    "endpoint": row.label,
                    "sex": sex,
                    "platform": platform,
                    "bmd": bmd_str,
                    "bmdl": bmdl_str,
                    "bmd_status": status,
                    "model_name": bmds_res.get("model_name"),
                    "loel": row.loel,
                    "noel": row.noel,
                    "direction": row.direction,
                })
    return summary
