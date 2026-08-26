"""
Methods context extractor — derive structured study metadata from the file pool.

The methods-narrative pipeline starts here.  Given fingerprints,
identity, study parameters, the integrated BMDProject, and the
session's animal report + sidecar files, this module produces a
fully-populated MethodsContext that downstream steps consume:

  - build_methods_prompt    (LLM prompt assembly — methods_prompt.py)
  - build_subsection_skeleton (which subsections to include — methods_prompt.py)
  - build_sample_counts_table       (sample-count table — sample_counts_table.py)
  - build_abstract_methods  (Abstract paragraph 1 — abstract_methods.py)
  - build_abstract_results_* (apical / pk / genomics narratives)

Public entry point:

  extract_methods_context(fingerprints, identity, study_params,
                          integrated, animal_report, bm2_jsons,
                          session_dir)

Helpers (private):

  - _parse_bm2_analysis_info       parse the analysisInfo.notes list
                                   from a single .bm2 sub-result into
                                   {key: value} pairs
  - _collect_bm2_analysis_metadata aggregate _parse_bm2_analysis_info
                                   across all sub-results of one bm2
                                   into a single typed metadata dict
  - _extract_biosampling_doses     scan tissue_conc / body_weight
                                   sidecars for rows marked
                                   "biosampling" to get the dose groups
                                   that had blood collection
  - _extract_pk_data               aggregate per-animal plasma
                                   concentrations across timepoints +
                                   compute two-point half-lives via
                                   t½ = ln(2) × Δt / ln(C₁/C₂)
  - _extract_genomics_assay        infer assay name + chip from the
                                   integrated BMDProject's gene-expression
                                   experiments (S1500 in chip name implies
                                   TempO-Seq)
  - _build_genomics_sample_counts  per-(organ, sex, dose) sample counts
                                   for Table 1 from animal_report or
                                   gene_expression fingerprints

All extraction state is read-only on inputs; the function builds a
fresh MethodsContext, populates it, and returns it.  No disk writes,
no LLM calls.  methods_report.py re-exports extract_methods_context
so existing call sites (llm_routes, process_integrated) keep working.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

import logging
import re

from narrative.methods_models import MethodsContext


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extraction: parse bm2 analysisInfo.notes into structured metadata
# ---------------------------------------------------------------------------

def _parse_bm2_analysis_info(notes_list: list[str]) -> dict:
    """
    Parse the analysisInfo.notes list from a .bm2 file's bMDResult,
    williamsTrendResults, curveFitPrefilterResults, or categoryAnalysisResults.

    BMDExpress 3 stores analysis parameters as a flat list of "Key: Value"
    strings in each analysis node's analysisInfo.notes.  This function
    extracts the subset we need for the M&M report.

    Args:
        notes_list: List of strings like ["BMDExpress3 Version: BMDExpress 3.20.0156 BETA",
                    "Models fit: hill, power, exponential 3, exponential 5", ...]

    Returns:
        Dict with parsed fields.  Missing fields are absent (not None).
        Possible keys: bmdexpress_version, bmds_version, bmr_type, bmr_factor,
        models_fit, constant_variance, prefilter_method, prefilter_pvalue,
        fold_change_filter.
    """
    result = {}
    for note in notes_list:
        # Most notes follow "Key: Value" format
        if ": " not in note:
            # Some notes are just labels like "Williams Trend Test" or "Benchmark Dose Analyses"
            # Use these to identify the prefilter method
            lower = note.strip().lower()
            if "williams" in lower:
                result["prefilter_method"] = "Williams Trend Test"
            elif "curve fit" in lower:
                result["prefilter_method"] = "Curve Fit Prefilter"
            continue

        key, _, value = note.partition(": ")
        key = key.strip()
        value = value.strip()

        if key == "BMDExpress3 Version":
            result["bmdexpress_version"] = value
        elif key == "BMDS Major Version":
            result["bmds_version"] = value
        elif key == "BMR Type":
            result["bmr_type"] = value
        elif key == "BMR Factor":
            try:
                result["bmr_factor"] = float(value)
            except ValueError:
                result["bmr_factor_str"] = value
        elif key == "Models fit" or key == "Models Used":
            # "hill, power, exponential 3, exponential 5"
            # or "hill: Hill EPA BMDS MLE ToxicR,power: Power EPA BMDS MLE ToxicR,..."
            # Normalize to clean model names
            models = []
            for m in value.split(","):
                # Strip the "Hill EPA BMDS MLE ToxicR" suffix if present
                name = m.split(":")[0].strip()
                if name:
                    models.append(name)
            result["models_fit"] = models
        elif key == "Constant Variance":
            result["constant_variance"] = value in ("1", "true", "True")
        elif key == "Unadjusted P-Value Cutoff":
            try:
                result["prefilter_pvalue"] = float(value)
            except ValueError:
                pass
        elif key == "NOTEL/LOTEL Fold Change Threshold":
            try:
                result["fold_change_filter"] = float(value)
            except ValueError:
                pass

    return result


def _collect_bm2_analysis_metadata(bm2_json: dict) -> dict:
    """
    Collect analysis metadata from ALL analysis nodes in a .bm2 file.

    Merges notes from williamsTrendResults (prefilter), curveFitPrefilterResults,
    bMDResult (BMD modeling params), and categoryAnalysisResults.
    Later entries overwrite earlier ones for the same key, so the BMD result
    (most specific) takes priority.

    Args:
        bm2_json: The full deserialized BMDProject dict from Java export / LMDB cache.

    Returns:
        Merged dict of analysis parameters (same keys as _parse_bm2_analysis_info).
    """
    merged = {}

    # Parse in order of specificity: prefilter < BMD < category
    # Each overwrites the previous for shared keys like bmdexpress_version
    for section_key in ("williamsTrendResults", "curveFitPrefilterResults", "bMDResult", "categoryAnalysisResults"):
        items = bm2_json.get(section_key, [])
        if not items:
            continue
        # Only parse the first item — all experiments in a section share params
        first = items[0] if isinstance(items, list) else items
        if not isinstance(first, dict):
            continue
        notes = first.get("analysisInfo", {}).get("notes", [])
        if notes:
            parsed = _parse_bm2_analysis_info(notes)
            merged.update(parsed)

    return merged


# ---------------------------------------------------------------------------
# Extraction: build MethodsContext from file pool data
# ---------------------------------------------------------------------------

def extract_methods_context(
    identity: dict,
    fingerprints: dict,
    animal_report: dict | None = None,
    study_params: dict | None = None,
    bm2_jsons: dict | None = None,
    session_dir: str | None = None,
    integrated: dict | None = None,
) -> MethodsContext:
    """
    Build a MethodsContext from all available data sources.

    This is the main entry point for extracting study metadata that drives
    both the LLM prompt and the conditional subsection logic.

    Args:
        identity:      Chemical identity dict from the frontend (name, casrn, dtxsid, ...).
        fingerprints:  Dict of {file_id: FileFingerprint-as-dict-or-object} from the server's
                       _pool_fingerprints[dtxsid] cache.  Each fingerprint has domain, sexes,
                       dose_groups, endpoint_names, organ, etc.
        animal_report: Optional dict from animal_report.json (dose_design, domain_coverage, etc.).
        study_params:  Optional user-provided overrides: vehicle, route, duration_days, species.
        bm2_jsons:     Optional dict of {file_id: bm2_json_dict} for extracting BMDExpress
                       analysis metadata from analysisInfo.notes.
        session_dir:   Optional path to the session directory.  Used to scan sidecar files
                       for biosampling dose groups (animals with selection="biosampling").
        integrated:    Optional integrated BMDProject dict.  Used to extract the genomics
                       assay/chip from doseResponseExperiments[].chip — e.g., chip name
                       containing "S1500" identifies TempO-Seq.

    Returns:
        Populated MethodsContext with all available study metadata.
    """
    ctx = MethodsContext()
    study_params = study_params or {}
    bm2_jsons = bm2_jsons or {}

    # --- Chemical identity ---
    ctx.chemical_name = identity.get("name", "the test chemical")
    ctx.casrn = identity.get("casrn", "")
    ctx.dtxsid = identity.get("dtxsid", "")

    # --- Study params (user-provided overrides) ---
    # These are NIEHS 5-day protocol defaults.  The dose_design from the
    # animal report contains TOTAL animals per group (core + biosampling),
    # which inflates the counts.  The actual core group sizes (5/10) are
    # protocol constants, so we don't override from dose_design.
    ctx.vehicle = study_params.get("vehicle", "corn oil")
    ctx.route = study_params.get("route", "gavage")
    ctx.duration_days = study_params.get("duration_days", 5)
    ctx.species = study_params.get("species", "Sprague Dawley")
    ctx.n_per_group = study_params.get("n_per_group", 5)
    ctx.n_control = study_params.get("n_control", 10)

    # --- Scan fingerprints for platform presence and collect metadata ---
    all_doses: set[float] = set()
    all_sexes: set[str] = set()
    dose_unit_found = None

    for fid, fp in fingerprints.items():
        # Support both dict and object-style access
        _get = fp.get if isinstance(fp, dict) else lambda k, d=None: getattr(fp, k, d)

        # Use platform directly — no suffix stripping needed.
        # data_type "gene_expression" is checked separately since
        # gene expression files have platform=None.
        platform = _get("platform")
        data_type = _get("data_type")

        if not platform and data_type != "gene_expression":
            continue

        # Set platform presence flags using human-readable platform strings.
        if platform == "Body Weight":
            ctx.has_body_weight = True
        elif platform == "Organ Weights":
            ctx.has_organ_weights = True
            eps = _get("endpoint_names", [])
            ctx.organ_weight_endpoints = list(set(ctx.organ_weight_endpoints + eps))
        elif platform == "Clinical Chemistry":
            ctx.has_clin_chem = True
            eps = _get("endpoint_names", [])
            ctx.clin_chem_endpoints = list(set(ctx.clin_chem_endpoints + eps))
        elif platform == "Hematology":
            ctx.has_hematology = True
            eps = _get("endpoint_names", [])
            ctx.hematology_endpoints = list(set(ctx.hematology_endpoints + eps))
        elif platform == "Hormones":
            ctx.has_hormones = True
            eps = _get("endpoint_names", [])
            ctx.hormone_endpoints = list(set(ctx.hormone_endpoints + eps))
        elif platform == "Tissue Concentration":
            ctx.has_tissue_conc = True
        if data_type == "gene_expression":
            ctx.has_gene_expression = True
            organ = _get("organ")
            if organ and organ not in ctx.ge_organs:
                ctx.ge_organs.append(organ)

        # Collect doses and sexes from all fingerprints
        doses = _get("dose_groups", [])
        if doses:
            all_doses.update(float(d) for d in doses)
        sexes = _get("sexes", [])
        if sexes:
            all_sexes.update(sexes)
        du = _get("dose_unit")
        if du:
            dose_unit_found = du
        # Species from fingerprints (LLM-inferred) — only if user didn't override
        sp = _get("species")
        if sp and not study_params.get("species"):
            ctx.species = sp

    if all_doses:
        ctx.dose_groups = sorted(all_doses)
    if all_sexes:
        ctx.sexes = sorted(all_sexes)
    if dose_unit_found:
        ctx.dose_unit = dose_unit_found

    # --- Animal report: domain coverage and biosampling count ---
    if animal_report:
        # Biosampling count from animal_report
        ctx.n_biosampling = animal_report.get("biosampling_count", 0)

        # Fill dose_groups from animal_report if fingerprints didn't have them
        if not ctx.dose_groups and animal_report.get("dose_groups"):
            ctx.dose_groups = [float(d) for d in animal_report["dose_groups"]]

        # Domain coverage can confirm platform presence — keys are now
        # platform strings (e.g., "Body Weight", "Hematology").
        dc = animal_report.get("domain_coverage", {})
        for plat in dc:
            if plat == "Body Weight":
                ctx.has_body_weight = True
            elif plat == "Organ Weights":
                ctx.has_organ_weights = True
            elif plat == "Clinical Chemistry":
                ctx.has_clin_chem = True
            elif plat == "Hematology":
                ctx.has_hematology = True
            elif plat == "Hormones":
                ctx.has_hormones = True
            elif plat == "Tissue Concentration":
                ctx.has_tissue_conc = True
            elif plat == "Gene Expression":
                ctx.has_gene_expression = True

    # --- BMDExpress analysis metadata from .bm2 files ---
    for fid, bm2_json in bm2_jsons.items():
        if not isinstance(bm2_json, dict):
            continue
        meta = _collect_bm2_analysis_metadata(bm2_json)
        if meta:
            # Apply to context (first non-None wins for each field)
            if meta.get("bmdexpress_version") and not ctx.bmdexpress_version:
                ctx.bmdexpress_version = meta["bmdexpress_version"]
            if meta.get("bmds_version") and not ctx.bmds_version:
                ctx.bmds_version = meta["bmds_version"]
            if meta.get("bmr_type") and not ctx.bmr_type:
                ctx.bmr_type = meta["bmr_type"]
            if meta.get("bmr_factor") is not None and ctx.bmr_factor is None:
                ctx.bmr_factor = meta["bmr_factor"]
            if meta.get("models_fit") and not ctx.models_fit:
                ctx.models_fit = meta["models_fit"]
            if meta.get("constant_variance") is not None and ctx.constant_variance is None:
                ctx.constant_variance = meta["constant_variance"]
            if meta.get("prefilter_method") and not ctx.prefilter_method:
                ctx.prefilter_method = meta["prefilter_method"]
            if meta.get("prefilter_pvalue") is not None and ctx.prefilter_pvalue is None:
                ctx.prefilter_pvalue = meta["prefilter_pvalue"]
            if meta.get("fold_change_filter") is not None and ctx.fold_change_filter is None:
                ctx.fold_change_filter = meta["fold_change_filter"]

    # --- Build genomics sample counts for Table 1 ---
    # Structure: {organ: {sex: {dose: count}}}
    # Source: gene_expression fingerprints' n_animals_by_dose, grouped by organ and sex
    if ctx.has_gene_expression:
        ctx.genomics_sample_counts = _build_genomics_sample_counts(
            fingerprints, ctx.dose_groups,
        )

    # --- Biosampling dose groups (for Abstract-Methods) ---
    # Scan sidecar files for rows where selection contains "biosampling".
    # The reference report writes: "Blood was collected from animals
    # dedicated for internal dose assessment in the 4 and 37 mg/kg groups."
    if session_dir:
        ctx.biosampling_doses = _extract_biosampling_doses(session_dir)

    # --- Pharmacokinetics (for Abstract-Results) ---
    # Aggregate plasma concentrations + half-lives from tissue conc
    # sidecars.  Used by build_abstract_results_pk() to produce the
    # cross-sex comparison sentence (e.g., "Half-lives ... were 78.2
    # and 25.6 hours for the 4 and 37 mg/kg groups...").
    if session_dir:
        concs, t_half, timepoints = _extract_pk_data(session_dir)
        if concs:
            ctx.pk_concentrations = concs
        if t_half:
            ctx.pk_half_lives = t_half
        if timepoints:
            ctx.pk_timepoints = timepoints

    # --- Genomics assay and chip (for Abstract-Methods) ---
    # Extract from integrated.doseResponseExperiments[].chip.  The chip name
    # or ID identifies the assay — "S1500" implies TempO-Seq, "HG_U133" implies
    # Affymetrix, etc.
    if integrated and ctx.has_gene_expression:
        assay, chip = _extract_genomics_assay(integrated)
        ctx.genomics_assay = assay
        ctx.genomics_chip = chip

    return ctx


def _extract_biosampling_doses(session_dir: str) -> list[float]:
    """
    Scan session sidecar JSON files for biosampling animals and collect
    the set of dose groups they belong to.

    Biosampling animals are tagged in sidecar data via the per-animal
    `selection` field containing "biosampling".  Usually only 2 of the
    study's 10 doses have biosampling animals (the two chosen for
    pharmacokinetic/internal dose assessment).

    Returns a sorted list of dose values.  Empty list if no biosampling
    animals are found.
    """
    import os
    import json

    doses: set[float] = set()
    files_dir = os.path.join(session_dir, "files")
    if not os.path.isdir(files_dir):
        return []

    for fname in os.listdir(files_dir):
        if not fname.endswith(".sidecar.json"):
            continue
        try:
            with open(os.path.join(files_dir, fname)) as f:
                sc = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        for _aid, rec in sc.get("animals", {}).items():
            selection = str(rec.get("selection", ""))
            if "biosampling" in selection.lower():
                dose = rec.get("dose")
                if dose is not None:
                    try:
                        doses.add(float(dose))
                    except (TypeError, ValueError):
                        pass

    return sorted(doses)


def _extract_pk_data(session_dir: str) -> tuple[dict, dict, list[int]]:
    """
    Extract pharmacokinetic data from tissue concentration sidecars.

    Reads any tissue_conc_*.sidecar.json files in the session, scans
    biosampling animal records, and aggregates plasma concentrations
    by (sex, dose, timepoint).  Then computes per-(sex, dose) plasma
    half-lives using the standard two-point formula:

        t½ = ln(2) × Δt / ln(C_early / C_late)

    Half-life is only computed when:
      - Exactly two timepoints exist with positive mean concentrations
      - The early concentration is greater than the late concentration
        (monotonic decay — required for the log-linear assumption)

    Returns:
        (concentrations, half_lives, timepoints)
        concentrations: {sex: {dose: {hour_int: mean_value}}}
        half_lives:     {sex: {dose: hours_float}}
        timepoints:     sorted list of unique hour integers seen across
                        all observations (e.g., [2, 24])
    """
    import os
    import json
    import math
    import re

    files_dir = os.path.join(session_dir, "files")
    if not os.path.isdir(files_dir):
        return {}, {}, []

    # Per (sex, dose, hour) → list of concentration values
    raw_values: dict[tuple[str, float, int], list[float]] = {}
    timepoints_seen: set[int] = set()

    # Pattern to extract the timepoint hours from endpoint names like
    # "Plasma 2 Hour Perfluorohexanesulfonamide Concentration".
    _HOUR_RE = re.compile(r"Plasma\s+(\d+)\s+Hour", re.IGNORECASE)

    for fname in os.listdir(files_dir):
        if not fname.startswith("tissue_conc") or not fname.endswith(".sidecar.json"):
            continue
        try:
            with open(os.path.join(files_dir, fname)) as f:
                sc = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        # The sidecar's "sex" field carries the per-file sex (e.g., "Male"),
        # which we trust over per-animal sex (often None in tissue conc).
        sex = sc.get("sex") or ""
        if not sex:
            continue

        for _aid, rec in sc.get("animals", {}).items():
            selection = str(rec.get("selection", ""))
            if "biosampling" not in selection.lower():
                continue
            dose = rec.get("dose")
            if dose is None:
                continue
            try:
                dose = float(dose)
            except (TypeError, ValueError):
                continue

            for obs in rec.get("observations", []):
                ep = obs.get("endpoint", "")
                if "Concentration" not in ep:
                    continue  # skip LOQ rows
                m = _HOUR_RE.search(ep)
                if not m:
                    continue
                hour = int(m.group(1))
                val = obs.get("value")
                if val is None:
                    continue
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    continue
                raw_values.setdefault((sex, dose, hour), []).append(v)
                timepoints_seen.add(hour)

    # Aggregate to means
    concentrations: dict[str, dict[float, dict[int, float]]] = {}
    for (sex, dose, hour), vs in raw_values.items():
        if not vs:
            continue
        mean = sum(vs) / len(vs)
        concentrations.setdefault(sex, {}).setdefault(dose, {})[hour] = mean

    # Compute half-lives where we have two-timepoint monotonic decay
    half_lives: dict[str, dict[float, float]] = {}
    for sex, by_dose in concentrations.items():
        for dose, by_hour in by_dose.items():
            tps = sorted(by_hour.keys())
            if len(tps) < 2:
                continue
            # Use the first and last available timepoints
            t_early, t_late = tps[0], tps[-1]
            c_early = by_hour[t_early]
            c_late = by_hour[t_late]
            if c_early <= 0 or c_late <= 0 or c_early <= c_late:
                continue  # require monotonic decay for log-linear half-life
            try:
                t_half = math.log(2) * (t_late - t_early) / math.log(c_early / c_late)
            except (ValueError, ZeroDivisionError):
                continue
            half_lives.setdefault(sex, {})[dose] = t_half

    return concentrations, half_lives, sorted(timepoints_seen)


def _extract_genomics_assay(integrated: dict) -> tuple[str | None, str | None]:
    """
    Identify the genomics assay platform from the integrated BMDProject.

    Scans doseResponseExperiments for gene-expression experiments (those with
    a non-generic chip) and reads chip.name / chip.chipId.  Maps known chip
    identifiers to their canonical assay names:

      - "S1500", "S1500+"        → TempO-Seq
      - "BioSpyder"              → TempO-Seq
      - "HG-U133", "HT_MG_..."   → Affymetrix GeneChip
      - "Illumina"               → Illumina BeadChip / RNA-seq

    Returns (assay_name, chip_name) tuple — either may be None if not
    identifiable.  For unknown chips, returns (None, chip.name) so the
    caller can at least report the raw chip identifier.
    """
    experiments = integrated.get("doseResponseExperiments", [])
    for e in experiments:
        chip = e.get("chip")
        # Skip refs (int) and None — we need a full dict with name/chipId
        if not isinstance(chip, dict):
            continue
        chip_id = str(chip.get("chipId", "") or "")
        chip_name = str(chip.get("name", "") or "")
        # Skip placeholder "generic" chips attached to apical experiments
        if chip_id.lower() in ("generic", "") and chip_name.lower() in ("generic", ""):
            continue
        # Compare case-insensitively against known signatures
        probe = (chip_id + " " + chip_name).lower()
        if "s1500" in probe or "tempo" in probe or "biospyder" in probe:
            return ("TempO-Seq", chip_name or chip_id)
        if "affy" in probe or "hg-u133" in probe or "ht_mg" in probe:
            return ("Affymetrix GeneChip", chip_name or chip_id)
        if "illumina" in probe:
            return ("Illumina", chip_name or chip_id)
        # Unknown real chip — return its name so the caller can still report it
        return (None, chip_name or chip_id)

    return (None, None)


def _build_genomics_sample_counts(
    fingerprints: dict,
    dose_groups: list[float],
) -> dict | None:
    """
    Build the Table 1 sample-count matrix from gene_expression fingerprints.

    Each gene_expression fingerprint represents one organ × sex combination.
    We extract n_animals_by_dose from each to build:
        {organ: {sex: {dose: count}}}

    Args:
        fingerprints: Dict of {file_id: fingerprint_dict_or_object}.
        dose_groups:  Sorted list of all dose values in the study.

    Returns:
        Nested dict of sample counts, or None if no GE fingerprints found.
    """
    counts: dict[str, dict[str, dict[float, int]]] = {}

    for fid, fp in fingerprints.items():
        _get = fp.get if isinstance(fp, dict) else lambda k, d=None: getattr(fp, k, d)

        if _get("data_type") != "gene_expression":
            continue

        organ = _get("organ", "Unknown")
        sexes = _get("sexes", [])
        n_by_dose = _get("n_animals_by_dose", {})

        if not n_by_dose:
            continue

        # Each GE fingerprint is typically one sex (inferred by LLM),
        # but may have multiple sexes if the experiment combines them
        sex_label = sexes[0] if sexes else "Unknown"

        if organ not in counts:
            counts[organ] = {}
        if sex_label not in counts[organ]:
            counts[organ][sex_label] = {}

        for dose_str, count in n_by_dose.items():
            dose_val = float(dose_str)
            # Take the max if we see the same organ/sex/dose from multiple files
            existing = counts[organ][sex_label].get(dose_val, 0)
            counts[organ][sex_label][dose_val] = max(existing, count)

    return counts if counts else None

