"""
pool_integrator — Merge validated pool files into a unified BMDProject JSON.

After file upload, fingerprinting, and cross-validation, the pool contains
multiple files (xlsx, txt/csv, bm2) covering different endpoint domains
(body_weight, organ_weights, clin_chem, hematology, hormones, gene_expression,
etc.) at different processing tiers.

This module's job is *integration*: select the best file for each domain
(respecting user conflict resolutions), then delegate to bmdx-core's native
Java code for .bm2 merging and JSON serialization.

Data flow:
    Validate → Resolve conflicts → integrate_pool() → integrated.json
        → build_table_data() → section cards with tables & narratives

The Java layer (IntegrateProject) uses BMDExpress 3's native classes:
    - ProjectUtilities.addProjectToProject() for .bm2 merging
    - ExperimentFileUtil.readFile() for .txt/.csv parsing
    - Jackson ObjectMapper with NaN→null serializers for valid JSON output

Python handles:
    - Tier selection (which file to use per domain)
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
import math
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experiment_metadata import attach_metadata, infer_experiment_metadata
from file_integrator import (
    _BM2_DOMAIN_MAP,
    _detect_sex_from_filename,
    detect_domain,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# Tier priority for auto-selection: .bm2 preferred (has BMD results),
# then txt/csv (BMDExpress-importable pivot), then xlsx (raw long-format).
_TIER_PREFERENCE = {"bm2": 1, "txt": 2, "csv": 2, "txt_csv": 2, "xlsx": 3}

# Path to the Java helper directory containing IntegrateProject.class
JAVA_HELPER_DIR = Path(__file__).parent / "java"


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
    # Import here to avoid circular dependency at module load time
    from apical_report import _build_classpath

    cp = _build_classpath()
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

# Reverse of _BM2_DOMAIN_MAP — maps our canonical domain names to the
# BMDExpress experiment name prefixes.
_DOMAIN_TO_BM2_PREFIX: dict[str, str] = {
    "body_weight":    "BodyWeight",
    "organ_weights":  "OrganWeight",
    "clin_chem":      "ClinicalChemistry",
    "hematology":     "Hematology",
    "hormones":       "Hormone",
    "tissue_conc":    "TissueConcentration",
    "clinical_obs":   "ClinicalObservation",
}


def xlsx_to_pivot_txt(path: str, output_dir: str) -> list[str]:
    """
    Convert an NTP xlsx long-format file into tab-delimited pivot files
    that IntegrateProject can import via ExperimentFileUtil.

    NTP xlsx files are long-format: one row per animal × observation.
    We pivot to BMDExpress format:
        Row 1: column headers (probe_id, colname1, colname2, ...)
        Row 2: doses (label, dose1, dose2, ...)
        Row 3+: endpoint measurements (endpoint_name, value1, value2, ...)

    One output file per sex found in the data.

    Args:
        path:       Absolute path to the xlsx file.
        output_dir: Directory to write the pivot .txt files.

    Returns:
        List of paths to the generated pivot .txt files.
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

    data_sheet = wb["Data"] if "Data" in wb.sheetnames else wb[wb.sheetnames[-1]]

    # --- Read all rows ---
    headers: list[str] = []
    # {(sex, endpoint): {animal_id: value}}
    data_by_sex_endpoint: dict[tuple[str, str], dict[str, float]] = {}
    animal_dose_map: dict[str, float] = {}
    animal_sex_map: dict[str, str] = {}

    standard_cols = {
        "NTP Study Number", "Concentration", "Animal ID", "Sex",
        "Selection", "Terminal Flag", "",
    }

    for row_idx, row in enumerate(data_sheet.iter_rows(values_only=True)):
        if row_idx == 0:
            headers = [str(c) if c is not None else "" for c in row]
            continue

        if row[1] is None or row[2] is None:
            continue

        try:
            dose = float(row[1])
        except (ValueError, TypeError):
            continue

        animal_id = str(row[2]).strip()
        sex = str(row[3]).strip().title() if row[3] is not None else "Unknown"
        animal_dose_map[animal_id] = dose
        animal_sex_map[animal_id] = sex

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
            data_by_sex_endpoint.setdefault(key, {})[animal_id] = fval

    wb.close()

    if not data_by_sex_endpoint:
        return []

    # --- Detect domain from filename ---
    filename = os.path.basename(path)
    file_size = os.path.getsize(path) if os.path.exists(path) else 0
    domain = detect_domain(filename, "xlsx", file_size)
    prefix = _DOMAIN_TO_BM2_PREFIX.get(domain, "Unknown")

    # --- Group by sex and write pivot files ---
    # Collect all endpoints and animals per sex
    sex_data: dict[str, dict] = {}
    for (sex, endpoint), animal_vals in data_by_sex_endpoint.items():
        if sex not in sex_data:
            sex_data[sex] = {"endpoints": {}, "animals": set()}
        sex_data[sex]["endpoints"][endpoint] = animal_vals
        sex_data[sex]["animals"].update(animal_vals.keys())

    output_paths = []
    for sex, info in sex_data.items():
        # Sort animals by dose then ID for consistent column order
        animals = sorted(info["animals"],
                         key=lambda a: (animal_dose_map.get(a, 0), a))

        # Build the pivot file
        lines = []
        # Row 1: header — probe_id + animal IDs
        lines.append("\t".join([f"{prefix}{sex}"] + animals))
        # Row 2: doses
        lines.append("\t".join(["Dose"] + [
            str(animal_dose_map.get(a, 0)) for a in animals
        ]))
        # Row 3+: endpoints
        for endpoint, animal_vals in info["endpoints"].items():
            values = []
            for a in animals:
                v = animal_vals.get(a)
                values.append(str(v) if v is not None else "")
            lines.append("\t".join([endpoint] + values))

        # Write to file
        safe_sex = sex.replace(" ", "_")
        out_name = f"{prefix}{safe_sex}_pivot.txt"
        out_path = os.path.join(output_dir, out_name)
        with open(out_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        output_paths.append(out_path)
        logger.info("Converted xlsx → pivot: %s (%d endpoints, %d animals)",
                     out_name, len(info["endpoints"]), len(animals))

    return output_paths


# ---------------------------------------------------------------------------
# Main integration orchestrator
# ---------------------------------------------------------------------------


def integrate_pool(
    dtxsid: str,
    session_dir: str,
    fingerprints: dict[str, dict],
    coverage_matrix: dict[str, dict[str, list[str]]],
    precedence: list[dict],
    *,
    test_article: dict | None = None,
    llm_generate_json: Any = None,
) -> dict:
    """
    Merge all pool files into a single unified BMDProject JSON.

    For each domain in the coverage matrix:
      1. If the user resolved a conflict → use that chosen file.
      2. Otherwise, prefer .bm2 (has BMD results), then txt/csv, then xlsx.
      3. Collect .bm2 and .txt/.csv file paths for Java integration.
      4. Convert .xlsx files to pivot .txt format for Java import.
      5. Call IntegrateProject (Java) to merge everything with native
         BMDExpress classes and Jackson NaN-safe serialization.
      6. Read back the JSON, add _meta and _category_lookup for the
         process-integrated endpoint.

    Args:
        dtxsid:            The DTXSID identifying this session.
        session_dir:       Absolute path to sessions/{dtxsid}/.
        fingerprints:      Dict mapping file_id → fingerprint dict.
        coverage_matrix:   Dict mapping domain → tier_name → list[file_id].
        precedence:        List of user conflict resolutions.
        test_article:      Dict with 'name', 'casrn', 'dsstox' for metadata.
        llm_generate_json: Callable for LLM metadata inference.

    Returns:
        The merged BMDProject dict, also saved to sessions/{dtxsid}/integrated.json.
    """
    files_dir = os.path.join(session_dir, "files")
    out_path = os.path.join(session_dir, "integrated.json")

    # Collect user-resolved file IDs for quick lookup
    resolved_file_ids: dict[str, str] = {}
    for entry in precedence:
        fid = entry.get("chosen_file_id", "")
        if not fid:
            continue
        fp = fingerprints.get(fid, {})
        domain = fp.get("domain") if isinstance(fp, dict) else getattr(fp, "domain", None)
        if domain:
            resolved_file_ids[domain] = fid

    # --- Select files per domain ---
    # Separate into lists for Java integration
    bm2_paths: list[str] = []
    txt_paths: list[str] = []
    xlsx_paths: list[str] = []
    source_files: dict[str, dict] = {}

    for domain, tiers in coverage_matrix.items():
        chosen_fid = None
        chosen_tier = None

        # 1. Check user conflict resolution
        if domain in resolved_file_ids:
            chosen_fid = resolved_file_ids[domain]
            fp = fingerprints.get(chosen_fid, {})
            chosen_tier = (
                fp.get("file_type") if isinstance(fp, dict)
                else getattr(fp, "file_type", None)
            )

        # 2. Auto-select by tier preference: bm2 > txt/csv > xlsx
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
                    chosen_fid = fids[0]
                    chosen_tier = tier_name

        if not chosen_fid:
            logger.warning("No file found for domain %s — skipping", domain)
            continue

        # Resolve file path
        fp = fingerprints.get(chosen_fid, {})
        filename = fp.get("filename") if isinstance(fp, dict) else getattr(fp, "filename", "")
        actual_file_type = (
            fp.get("file_type") if isinstance(fp, dict)
            else getattr(fp, "file_type", chosen_tier)
        )
        file_path = os.path.join(files_dir, filename) if filename else ""

        if not file_path or not os.path.exists(file_path):
            logger.warning("File not found for domain %s (id=%s) — skipping", domain, chosen_fid)
            continue

        logger.info("Selected domain=%s from %s (%s)", domain, filename, actual_file_type)

        # Route to the appropriate list for Java integration
        if chosen_tier == "bm2" or actual_file_type == "bm2":
            bm2_paths.append(file_path)
            source_files[domain] = {
                "file_id": chosen_fid, "filename": filename, "tier": "bm2",
            }
        elif actual_file_type in ("txt", "csv") or chosen_tier == "txt_csv":
            # Gene expression txt/csv are raw matrices, not clinical pivots —
            # they can't be imported directly.  Skip them; gene expression
            # comes from the .bm2 tier via BMDExpress's analysis pipeline.
            if domain == "gene_expression":
                continue
            txt_paths.append(file_path)
            source_files[domain] = {
                "file_id": chosen_fid, "filename": filename, "tier": actual_file_type,
            }
        elif actual_file_type == "xlsx" or chosen_tier == "xlsx":
            xlsx_paths.append(file_path)
            source_files[domain] = {
                "file_id": chosen_fid, "filename": filename, "tier": "xlsx",
            }
        else:
            logger.warning("Unknown tier %s for domain %s — skipping", chosen_tier, domain)

    # --- Convert xlsx files to pivot format for Java import ---
    # NTP xlsx files are long-format (one row per animal).
    # ExperimentFileUtil expects tab-delimited pivot format.
    pivot_dir = os.path.join(session_dir, "_pivots")
    if xlsx_paths:
        os.makedirs(pivot_dir, exist_ok=True)
        for xlsx_path in xlsx_paths:
            pivot_files = xlsx_to_pivot_txt(xlsx_path, pivot_dir)
            txt_paths.extend(pivot_files)

    # --- Call Java to merge everything ---
    if not bm2_paths and not txt_paths:
        logger.warning("No files to integrate for %s", dtxsid)
        return {}

    _run_integrate_java(bm2_paths, txt_paths, out_path)

    # --- Read back the Java-produced JSON ---
    # IntegrateProject writes valid JSON (NaN→null) via Jackson.
    # We add our metadata overlay (_meta, _category_lookup) for the
    # process-integrated endpoint.
    with open(out_path, "r") as f:
        integrated = json.load(f)

    # Add provenance metadata
    integrated["_meta"] = {
        "dtxsid": dtxsid,
        "integrated_at": datetime.now(tz=timezone.utc).isoformat(),
        "source_files": source_files,
    }

    # --- Build category lookup from the category TSV ---
    # The Java-produced JSON contains categoryAnalysisResults as native
    # BMDExpress objects.  For the process-integrated endpoint, we need
    # a (prefix, endpoint) → BMD info lookup dict.  We export the category
    # TSV via ExportBm2, then parse it with build_category_lookup().
    cat_results = integrated.get("categoryAnalysisResults", [])
    if cat_results:
        from apical_report import build_category_lookup, _build_classpath, JAVA_HELPER_DIR

        # Write a temporary .bm2 from the combined data so we can call
        # ExportBm2 for the category TSV.  Actually — the category data
        # is already in the JSON.  We need to export the TSV from one of
        # the original .bm2 files.
        #
        # Simpler: export category TSV from each .bm2 file and merge the
        # lookups.  This is what the old code did via bm2_cache.
        merged_cat_lookup: dict[tuple[str, str], dict] = {}
        for bm2_path in bm2_paths:
            tsv_path = os.path.join(session_dir, f"_cat_{os.path.basename(bm2_path)}.tsv")
            try:
                from apical_report import export_bm2
                # Export category TSV only (JSON output not needed here)
                json_tmp = os.path.join(session_dir, f"_tmp_{os.path.basename(bm2_path)}.json")
                export_bm2(bm2_path, json_tmp, tsv_path)
                cat_lookup = build_category_lookup(tsv_path)
                merged_cat_lookup.update(cat_lookup)
                # Clean up temp files
                for tmp in (json_tmp, tsv_path):
                    if os.path.exists(tmp):
                        os.remove(tmp)
            except Exception as e:
                logger.warning("Category export failed for %s: %s", bm2_path, e)

        integrated["_category_lookup"] = {
            f"{k[0]}|{k[1]}": v
            for k, v in merged_cat_lookup.items()
        }
    else:
        integrated["_category_lookup"] = {}

    # --- Infer structured ExperimentDescription metadata via LLM ---
    if test_article and llm_generate_json:
        all_experiments = integrated.get("doseResponseExperiments", [])
        descriptions = infer_experiment_metadata(
            experiments=all_experiments,
            source_files=source_files,
            test_article=test_article,
            llm_generate_json=llm_generate_json,
        )
        attach_metadata(all_experiments, descriptions)

    # Re-write the JSON with our metadata additions
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(integrated, f, indent=2)

    logger.info(
        "Integration complete: %d experiments, %d BMD results, %d category results → %s",
        len(integrated.get("doseResponseExperiments", [])),
        len(integrated.get("bMDResult", [])),
        len(integrated.get("categoryAnalysisResults", [])),
        out_path,
    )

    return integrated
