"""
pool_integrator — Merge validated pool files into a unified BMDProject JSON.

After file upload, fingerprinting, and cross-validation, the pool contains
multiple files (xlsx, txt/csv, bm2) covering different endpoint domains
(body_weight, organ_weights, clin_chem, hematology, hormones, gene_expression,
etc.) at different processing tiers.

This module's job is *integration*: select the best file for each domain
(respecting user conflict resolutions), parse raw data into the BMDProject
experiment format, and merge everything into a single JSON structure — the
unified source of truth that drives all downstream section generation.

Data flow:
    Validate → Resolve conflicts → integrate_pool() → integrated.json
        → build_table_data() → section cards with tables & narratives

The merged BMDProject JSON has the same shape as a real BMDExpress .bm2 export:
    {
        "doseResponseExperiments": [...],  # from all sources
        "bMDResult": [...],                # only from .bm2 sources
        "categoryAnalysisResults": [...],  # only from .bm2 sources
        "_meta": { ... },                  # our provenance metadata
    }

This means build_table_data() (apical_report.py) can process it directly —
it already iterates all doseResponseExperiments regardless of source.

Usage:
    from pool_integrator import integrate_pool

    integrated = integrate_pool(dtxsid, session_dir, fingerprints,
                                coverage_matrix, precedence)
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import json
import logging
import os
from datetime import datetime, timezone

import bm2_cache
from file_integrator import (
    _BM2_DOMAIN_MAP,
    _detect_sex_from_filename,
    detect_domain,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# Reverse of _BM2_DOMAIN_MAP — maps our canonical domain names to the
# BMDExpress experiment name prefixes.  Used when constructing experiment
# names for txt/csv data that doesn't come from BMDExpress.
#
# Example: domain "body_weight" → prefix "BodyWeight"
#          experiment name = "BodyWeightMale" or "BodyWeightFemale"
_DOMAIN_TO_BM2_PREFIX: dict[str, str] = {
    "body_weight":    "BodyWeight",
    "organ_weights":  "OrganWeight",
    "clin_chem":      "ClinicalChemistry",
    "hematology":     "Hematology",
    "hormones":       "Hormone",
    "tissue_conc":    "TissueConcentration",
    "clinical_obs":   "ClinicalObservation",
}

# Tier priority for auto-selection: .bm2 preferred (has BMD results),
# then txt/csv (BMDExpress-importable pivot), then xlsx (raw long-format).
# This is the OPPOSITE of data-truth precedence in file_integrator.py —
# here we want the most processed file because it carries BMD analysis.
# NOTE: the coverage_matrix from validate_pool() uses "txt_csv" as the
# tier name (not separate "txt" and "csv"), so we map that here too.
_TIER_PREFERENCE = {"bm2": 1, "txt": 2, "csv": 2, "txt_csv": 2, "xlsx": 3}


# ---------------------------------------------------------------------------
# Parsers — convert raw files into BMDProject experiment structures
# ---------------------------------------------------------------------------


def txt_csv_to_experiments(
    path: str,
    filename: str,
    file_type: str,
) -> list[dict]:
    """
    Parse a txt/csv pivot table into BMDProject doseResponseExperiment dicts.

    NTP txt/csv files are transposed tables:
        Row 1: Animal IDs (first cell blank or label, rest are IDs)
        Row 2: Dose concentrations per animal (same column order)
        Row 3+: Endpoint measurements (first cell = endpoint name, rest = values)

    Each file typically represents one sex × one domain (e.g., "female_body_weight.txt").
    We detect sex from the filename and domain from filename patterns.

    The output matches the BMDExpress doseResponseExperiments schema so
    build_table_data() can process it identically to real .bm2 data.

    Args:
        path:       Absolute path to the txt/csv file.
        filename:   Original filename (used for sex/domain detection).
        file_type:  "txt" or "csv" (determines separator).

    Returns:
        List of experiment dicts, one per sex found in the file.
        Each has {name, treatments[], probeResponses[]}.
        Empty list if the file can't be parsed or is gene expression.
    """
    separator = "," if file_type == "csv" else "\t"

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        logger.warning("Could not read %s: %s", filename, e)
        return []

    # Strip trailing whitespace, skip empty lines
    lines = [ln.rstrip("\n\r") for ln in lines if ln.strip()]
    if len(lines) < 3:
        # Need at least: animal IDs, doses, one endpoint row
        return []

    # --- Parse the pivot structure ---
    # Row 1: [label, animal_id_1, animal_id_2, ...]
    row1_cells = lines[0].split(separator)
    animal_ids = [c.strip() for c in row1_cells[1:] if c.strip()]

    # Row 2: [label, dose_1, dose_2, ...] — one dose per animal column
    row2_cells = lines[1].split(separator)
    doses_raw = row2_cells[1:]

    # Parse doses into floats, paired with their column index
    animal_doses: list[float | None] = []
    for d in doses_raw:
        try:
            animal_doses.append(float(d.strip()))
        except (ValueError, TypeError):
            animal_doses.append(None)

    # Detect sex and domain from filename
    sexes = _detect_sex_from_filename(filename)
    if not sexes:
        # Default to a single "Unknown" sex if filename doesn't indicate
        sexes = ["Unknown"]

    file_size = os.path.getsize(path) if os.path.exists(path) else 0
    domain = detect_domain(filename, file_type, file_size)

    # Gene expression txt/csv files are raw probe-level expression matrices
    # (thousands of rows), not clinical endpoint pivot tables.  They can't be
    # parsed into meaningful dose-response experiments here.  Gene expression
    # is instead handled via the .bm2 tier in integrate_pool(), which extracts
    # genomics results using the BMDExpress 3 Java API (ExportGenomics.java).
    if domain == "gene_expression":
        return []

    # Get the BM2-style experiment name prefix for this domain
    prefix = _DOMAIN_TO_BM2_PREFIX.get(domain, "Unknown")

    # --- Build treatments array ---
    # IMPORTANT: BMDProject treatments have ONE entry per animal column,
    # NOT one per unique dose group.  Each treatment stores the dose for
    # that specific animal.  The responses array is 1:1 with treatments —
    # responses[i] is the value for the animal whose dose is treatments[i].dose.
    # This matches how BMDExpress 3 serializes its data model.
    treatments = []
    for d in animal_doses:
        treatments.append({"dose": d if d is not None else 0.0})

    # --- Build probeResponses ---
    # Each endpoint row (row 3+) becomes one probeResponse.
    # The responses array has one value per animal column, parallel to treatments.
    probe_responses = []
    for line in lines[2:]:
        cells = line.split(separator)
        if not cells or not cells[0].strip():
            continue

        endpoint_name = cells[0].strip()
        values = cells[1:]

        # Parse response values — one per animal column
        responses: list[float] = []
        for v in values:
            try:
                responses.append(float(v.strip()))
            except (ValueError, TypeError):
                # Missing/invalid values: use NaN so the stats pipeline
                # can detect and handle them (same as BMDExpress behavior)
                responses.append(float("nan"))

        probe_responses.append({
            "probe": {"id": endpoint_name},
            "responses": responses,
        })

    # Skip if no endpoints parsed (file was empty or malformed)
    if not probe_responses:
        return []

    # --- Build one experiment per sex ---
    # Most NTP txt/csv files are single-sex (e.g., "female_body_weight.txt").
    # The experiment name follows BMDExpress convention: PrefixSex.
    experiments = []
    for sex in sexes:
        exp_name = f"{prefix}{sex}"
        experiments.append({
            "name": exp_name,
            "treatments": treatments,
            "probeResponses": probe_responses,
        })

    return experiments


def xlsx_to_experiments(path: str) -> list[dict]:
    """
    Parse an NTP xlsx "Data" sheet into BMDProject experiment dicts.

    NTP xlsx files are long-format: one row per animal × observation day.
    Columns:
        A: NTP Study Number
        B: Concentration (dose)
        C: Animal ID
        D: Sex
        E+: domain-specific endpoint measurements

    We group rows by (sex, endpoint_column) and pivot the long-format data
    into the transposed BMDProject structure that build_table_data() expects.

    Args:
        path: Absolute path to the xlsx file.

    Returns:
        List of experiment dicts (one per domain-sex combination).
        Empty list if the file can't be parsed.
    """
    try:
        import openpyxl
    except ImportError:
        logger.error("openpyxl not installed — cannot parse xlsx")
        return []

    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as e:
        logger.warning("Could not open xlsx %s: %s", path, e)
        return []

    # Find the "Data" sheet — fall back to the last sheet if not named "Data"
    data_sheet = wb["Data"] if "Data" in wb.sheetnames else wb[wb.sheetnames[-1]]

    # --- Read all rows into memory ---
    headers: list[str] = []
    # Accumulate: {(sex, endpoint_col_name): {animal_id: {dose: value}}}
    data_by_sex_endpoint: dict[tuple[str, str], dict[str, dict[float, float]]] = {}
    # Track animal → dose mapping for treatment construction
    animal_dose_map: dict[str, float] = {}

    for row_idx, row in enumerate(data_sheet.iter_rows(values_only=True)):
        if row_idx == 0:
            # Header row: standard NTP columns [0..4], endpoints [5+]
            headers = [str(c) if c is not None else "" for c in row]
            continue

        # Data rows: cols are [study_number, concentration, animal_id, sex, ...]
        if row[1] is None or row[2] is None:
            continue  # skip rows without dose or animal ID

        try:
            dose = float(row[1])
        except (ValueError, TypeError):
            continue

        animal_id = str(row[2]).strip()
        sex = str(row[3]).strip().title() if row[3] is not None else "Unknown"
        animal_dose_map[animal_id] = dose

        # Endpoint columns start at index 4 or 5 depending on the sheet.
        # Standard NTP: [StudyNum, Concentration, AnimalID, Sex, ...endpoints].
        # Some sheets have a "Selection" or "Terminal Flag" column at index 4.
        # We skip non-numeric standard columns.
        standard_cols = {
            "NTP Study Number", "Concentration", "Animal ID", "Sex",
            "Selection", "Terminal Flag", "",
        }
        for col_idx in range(4, len(headers)):
            col_name = headers[col_idx].strip()
            if col_name in standard_cols or not col_name:
                continue

            val = row[col_idx] if col_idx < len(row) else None
            if val is None:
                continue

            try:
                fval = float(val)
            except (ValueError, TypeError):
                continue

            key = (sex, col_name)
            data_by_sex_endpoint.setdefault(key, {})
            data_by_sex_endpoint[key][animal_id] = {
                **data_by_sex_endpoint[key].get(animal_id, {}),
                dose: fval,
            }

    wb.close()

    if not data_by_sex_endpoint:
        return []

    # --- Detect domain from filename ---
    filename = os.path.basename(path)
    file_size = os.path.getsize(path) if os.path.exists(path) else 0
    domain = detect_domain(filename, "xlsx", file_size)
    prefix = _DOMAIN_TO_BM2_PREFIX.get(domain, "Unknown")

    # --- Group endpoints by sex, then build one experiment per sex ---
    # Each experiment gets all endpoints for that sex as probeResponses.
    experiments_by_sex: dict[str, dict] = {}

    for (sex, endpoint_name), animal_data in data_by_sex_endpoint.items():
        if sex not in experiments_by_sex:
            # Collect all unique animals for this sex, ordered by dose then ID.
            # We need a canonical animal ordering so treatments and responses
            # arrays are parallel (treatments[i].dose = animal i's dose).
            all_doses: set[float] = set()
            for aid_vals in animal_data.values():
                all_doses.update(aid_vals.keys())
            for (s2, _), ad2 in data_by_sex_endpoint.items():
                if s2 == sex:
                    for av in ad2.values():
                        all_doses.update(av.keys())

            sorted_doses = sorted(all_doses)

            all_animals_for_sex: list[str] = []
            seen = set()
            for d in sorted_doses:
                for aid, dose_val in animal_dose_map.items():
                    if dose_val == d and aid not in seen:
                        for (s3, _), ad3 in data_by_sex_endpoint.items():
                            if s3 == sex and aid in ad3:
                                all_animals_for_sex.append(aid)
                                seen.add(aid)
                                break

            # IMPORTANT: treatments has ONE entry per animal (not per unique dose).
            # Each treatment stores the dose for that specific animal, parallel
            # to the responses array.  This matches BMDExpress 3's data model.
            treatments = [
                {"dose": animal_dose_map.get(aid, 0.0)}
                for aid in all_animals_for_sex
            ]

            experiments_by_sex[sex] = {
                "name": f"{prefix}{sex}",
                "treatments": treatments,
                "probeResponses": [],
                "_animal_order": all_animals_for_sex,
                "_dose_list": sorted_doses,
            }

        exp = experiments_by_sex[sex]
        animal_order = exp["_animal_order"]

        # Build the responses array: one float per animal in the canonical order.
        # NaN for missing values (animal didn't have this endpoint measured).
        responses = []
        for aid in animal_order:
            aid_data = animal_data.get(aid, {})
            # For xlsx long-format, an animal may have multiple observations
            # at the same dose (e.g., body weight at different study days).
            # We take the most recent (last written) value from the dict.
            dose = animal_dose_map.get(aid)
            val = aid_data.get(dose, float("nan")) if dose is not None else float("nan")
            # If the value is itself a dict (multiple doses), take the animal's dose
            if isinstance(val, dict):
                val = float("nan")
            responses.append(val)

        exp["probeResponses"].append({
            "probe": {"id": endpoint_name},
            "responses": responses,
        })

    # --- Clean up internal keys and return ---
    result = []
    for exp in experiments_by_sex.values():
        # Remove private keys used during construction
        exp.pop("_animal_order", None)
        exp.pop("_dose_list", None)
        result.append(exp)

    return result


# ---------------------------------------------------------------------------
# Main integration orchestrator
# ---------------------------------------------------------------------------


def integrate_pool(
    dtxsid: str,
    session_dir: str,
    fingerprints: dict[str, dict],
    coverage_matrix: dict[str, dict[str, list[str]]],
    precedence: list[dict],
) -> dict:
    """
    Merge all pool files into a single unified BMDProject JSON.

    For each domain in the coverage matrix:
      1. If the user resolved a conflict → use that chosen file.
      2. Otherwise, prefer .bm2 (has BMD/category results), then txt/csv, then xlsx.
      3. Parse the chosen file into BMDProject experiment structures.
      4. If the source is .bm2, also include its bMDResult and categoryAnalysisResults.

    The merged structure drives build_table_data() (apical_report.py) directly,
    producing table rows for every domain grouped by sex.

    Args:
        dtxsid:          The DTXSID identifying this session.
        session_dir:     Absolute path to sessions/{dtxsid}/.
        fingerprints:    Dict mapping file_id → fingerprint dict (from validation).
        coverage_matrix: Dict mapping domain → tier_name → list[file_id].
                         Example: {"body_weight": {"bm2": ["id1"], "txt": ["id2"]}}
        precedence:      List of user conflict resolutions from precedence.json.
                         Each entry: {issue_index, chosen_file_id, ...}.

    Returns:
        The merged BMDProject dict, also saved to sessions/{dtxsid}/integrated.json.
    """
    files_dir = os.path.join(session_dir, "files")

    # Collect user-resolved file IDs for quick lookup.
    # precedence entries may specify a domain, but they always have a chosen_file_id.
    resolved_file_ids: dict[str, str] = {}
    for entry in precedence:
        fid = entry.get("chosen_file_id", "")
        if not fid:
            continue
        # Find which domain this file belongs to, by looking it up in fingerprints
        fp = fingerprints.get(fid, {})
        domain = fp.get("domain") if isinstance(fp, dict) else getattr(fp, "domain", None)
        if domain:
            resolved_file_ids[domain] = fid

    # Accumulators for the merged BMDProject
    all_experiments: list[dict] = []
    all_bmd_results: list[dict] = []
    all_category_results: list[dict] = []
    # Merged category lookup: (experiment_prefix, endpoint_name) → BMD info.
    # This is the LMDB-cached result from build_category_lookup() — already in
    # the right format for build_table_data().  We merge across all .bm2 sources.
    merged_category_lookup: dict[tuple[str, str], dict] = {}
    source_files: dict[str, dict] = {}

    for domain, tiers in coverage_matrix.items():
        # Gene expression is now integrated alongside clinical endpoints.
        # The .bm2 file contains the full BMDExpress pipeline output:
        #   raw data → prefilter → curve fit → bMDResult (per-probe BMD)
        #   → categoryAnalysisResults (GO_BP, GENE, Adversity Signatures)
        # For gene expression, only the .bm2 tier is meaningful — the .txt
        # files are raw expression matrices that BMDExpress already consumed.

        # --- Select the best file for this domain ---
        chosen_fid = None
        chosen_tier = None

        # 1. Check user conflict resolution first
        if domain in resolved_file_ids:
            chosen_fid = resolved_file_ids[domain]
            fp = fingerprints.get(chosen_fid, {})
            chosen_tier = (
                fp.get("file_type") if isinstance(fp, dict)
                else getattr(fp, "file_type", None)
            )

        # 2. Auto-select by tier preference: bm2 > txt/csv > xlsx
        if not chosen_fid:
            # Flatten all file IDs across tiers, pick the one with best tier.
            # Coverage matrix values can be either a single string (file_id)
            # or a list of file_ids — normalize to list for uniform handling.
            best_priority = 999
            for tier_name, fids_raw in tiers.items():
                # Normalize to list and filter out None/empty entries.
                # Coverage matrix values can be a single string, a list, or None.
                if fids_raw is None:
                    continue
                fids = fids_raw if isinstance(fids_raw, list) else [fids_raw]
                fids = [f for f in fids if f]  # drop None/empty strings
                priority = _TIER_PREFERENCE.get(tier_name, 999)
                if priority < best_priority and fids:
                    best_priority = priority
                    chosen_fid = fids[0]  # take first file in this tier
                    chosen_tier = tier_name

        if not chosen_fid:
            logger.warning("No file found for domain %s — skipping", domain)
            continue

        # Resolve the file path and fingerprint
        fp = fingerprints.get(chosen_fid, {})
        filename = fp.get("filename") if isinstance(fp, dict) else getattr(fp, "filename", "")
        # Determine the actual file type from the fingerprint — the tier name
        # in the coverage matrix may be "txt_csv" (combined), so we need the
        # real extension to choose the right parser.
        actual_file_type = (
            fp.get("file_type") if isinstance(fp, dict)
            else getattr(fp, "file_type", chosen_tier)
        )
        file_path = os.path.join(files_dir, filename) if filename else ""

        if not file_path or not os.path.exists(file_path):
            logger.warning(
                "File not found for domain %s (id=%s, path=%s) — skipping",
                domain, chosen_fid, file_path,
            )
            continue

        logger.info(
            "Integrating domain=%s from %s (%s, tier=%s)",
            domain, filename, actual_file_type, chosen_fid,
        )

        # --- Parse the chosen file ---
        # Normalize tier: "txt_csv" → check actual_file_type for "txt" or "csv"
        if chosen_tier == "bm2" or actual_file_type == "bm2":
            # .bm2 files: load the full BMDProject from LMDB cache.
            # This gives us experiments WITH BMD results and category analysis.
            #
            # The LMDB cache may have been populated with either absolute or
            # relative paths depending on how the file was first processed.
            # Try the path we have, then fall back to the other form.
            bm2_json = bm2_cache.get_json(file_path)
            alt_path = None
            if bm2_json is None:
                # Try relative path if we have absolute, or vice versa
                cwd = os.getcwd()
                if os.path.isabs(file_path) and file_path.startswith(cwd):
                    alt_path = os.path.relpath(file_path, cwd)
                else:
                    alt_path = os.path.abspath(file_path)
                bm2_json = bm2_cache.get_json(alt_path)

            if bm2_json is None:
                logger.warning(
                    "BM2 cache miss for %s (also tried %s) — file may not have been processed yet",
                    filename, alt_path,
                )
                continue

            # Use whichever path found the cache hit for the category lookup
            cache_path = file_path if bm2_cache.get_json(file_path) is not None else alt_path

            # Take experiments, BMD results, and category results from this .bm2
            exps = bm2_json.get("doseResponseExperiments", [])
            all_experiments.extend(exps)
            all_bmd_results.extend(bm2_json.get("bMDResult", []))
            all_category_results.extend(bm2_json.get("categoryAnalysisResults", []))

            # Merge category lookup from LMDB cache — this is the pre-parsed
            # (prefix, endpoint) → BMD info dict that build_table_data() uses
            # to decide whether to report BMD values for each endpoint.
            cat_lookup = bm2_cache.get_categories(cache_path)
            if cat_lookup is None and alt_path:
                cat_lookup = bm2_cache.get_categories(
                    file_path if cache_path == alt_path else alt_path
                )
            if cat_lookup:
                merged_category_lookup.update(cat_lookup)

            source_files[domain] = {
                "file_id": chosen_fid,
                "filename": filename,
                "tier": "bm2",
                "experiment_count": len(exps),
            }

        elif actual_file_type in ("txt", "csv") or chosen_tier == "txt_csv":
            # txt/csv pivot tables: parse into experiment structures.
            # No BMD results available — only raw dose-response data.
            ft = actual_file_type if actual_file_type in ("txt", "csv") else "txt"
            exps = txt_csv_to_experiments(file_path, filename, ft)
            all_experiments.extend(exps)

            source_files[domain] = {
                "file_id": chosen_fid,
                "filename": filename,
                "tier": actual_file_type,
                "experiment_count": len(exps),
            }

        elif actual_file_type == "xlsx" or chosen_tier == "xlsx":
            # NTP xlsx long-format: parse and pivot into experiments.
            # No BMD results available — only raw dose-response data.
            exps = xlsx_to_experiments(file_path)
            all_experiments.extend(exps)

            source_files[domain] = {
                "file_id": chosen_fid,
                "filename": filename,
                "tier": "xlsx",
                "experiment_count": len(exps),
            }

        else:
            logger.warning("Unknown tier %s for domain %s — skipping", chosen_tier, domain)

    # --- Assemble the unified BMDProject ---
    integrated = {
        "doseResponseExperiments": all_experiments,
        "bMDResult": all_bmd_results,
        "categoryAnalysisResults": all_category_results,
        "oneWayANOVAResults": [],
        "williamsTrendResults": [],
        "curveFitPrefilterResults": [],
        "oriogenResults": [],
        "_meta": {
            "dtxsid": dtxsid,
            "integrated_at": datetime.now(tz=timezone.utc).isoformat(),
            "source_files": source_files,
        },
        # Serialized category lookup: pipe-separated tuple keys → BMD info.
        # Stored alongside the BMDProject so the process-integrated endpoint
        # can reconstruct the tuple-keyed dict for build_table_data().
        "_category_lookup": {
            f"{k[0]}|{k[1]}": v
            for k, v in merged_category_lookup.items()
        },
    }

    # Persist to disk so session restore can reload it
    out_path = os.path.join(session_dir, "integrated.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(integrated, f, indent=2, default=str)

    logger.info(
        "Integration complete: %d experiments, %d BMD results, %d category results → %s",
        len(all_experiments), len(all_bmd_results),
        len(all_category_results), out_path,
    )

    return integrated
