"""
methods_report.py — Structured Materials & Methods section for NIEHS 5dTox reports.

Replicates the exact structure from NIEHS Report 10 (PFHxSAm study):
  Materials and Methods
  ├── Study Design
  ├── Dose Selection Rationale
  ├── Chemistry
  ├── Clinical Examinations and Sample Collection
  │   ├── Clinical Observations
  │   ├── Body and Organ Weights
  │   ├── Clinical Pathology
  │   └── Internal Dose Assessment       (conditional: tissue_conc in pool)
  ├── Transcriptomics                     (conditional: gene_expression in pool)
  │   ├── Sample Collection for Transcriptomics
  │   ├── RNA Isolation, Library Creation, and Sequencing
  │   ├── Sequence Data Processing
  │   ├── Sequencing Quality Checks and Outlier Removal
  │   └── Data Normalization
  ├── Data Analysis
  │   ├── Statistical Analysis of Body Weights, Organ Weights, and Clinical Pathology
  │   ├── Benchmark Dose Analysis of Body Weights, Organ Weights, and Clinical Pathology
  │   ├── Benchmark Dose Analysis of Transcriptomics Data
  │   ├── Empirical False Discovery Rate Determination for Genomic Dose-response Modeling
  │   └── Data Accessibility
  └── [Table 1: Final Sample Counts for BMD Analysis of Transcriptomics Data]

Approach: Hybrid data + LLM.
  - Programmatically extract study metadata (doses, sample counts, domains,
    BMDExpress analysis parameters) from fingerprints, animal_report, and .bm2
    analysisInfo.notes.
  - Feed the structured context to an LLM prompt that generates prose for
    each subsection.
  - Subsections are CONDITIONAL — only included when the file pool has the
    relevant data domain.

This module is imported by background_server.py for the /api/generate-methods
endpoint and the /api/export-docx DOCX builder.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

# base_domain is no longer needed — platform strings are used directly.
# Kept as a no-op import guard in case downstream code still references it.


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — heading hierarchy and subsection keys
# ---------------------------------------------------------------------------

# The canonical subsection ordering and heading levels.
# level 2 = H2 ("Materials and Methods" — added by caller)
# level 3 = H3 (major subsections: Study Design, Chemistry, etc.)
# level 4 = H4 (sub-subsections: Clinical Observations, Body Weights, etc.)
#
# Each tuple: (subsection_key, heading_text, heading_level, condition_field)
# condition_field is the MethodsContext bool field that must be True for the
# subsection to be included.  None means always included.
SUBSECTION_SKELETON: list[tuple[str, str, int, str | None]] = [
    ("study_design",            "Study Design",                                                  3, None),
    ("dose_selection",          "Dose Selection Rationale",                                      3, None),
    ("chemistry",               "Chemistry",                                                     3, None),
    ("clinical_exams",          "Clinical Examinations and Sample Collection",                   3, None),
    ("clinical_obs",            "Clinical Observations",                                         4, None),
    ("body_organ_weights",      "Body and Organ Weights",                                        4, "has_body_weight"),
    ("clinical_pathology",      "Clinical Pathology",                                            4, "has_clin_path"),
    ("internal_dose",           "Internal Dose Assessment",                                      4, "has_tissue_conc"),
    ("transcriptomics",         "Transcriptomics",                                               3, "has_gene_expression"),
    ("txomics_sample",          "Sample Collection for Transcriptomics",                         4, "has_gene_expression"),
    ("txomics_rna",             "RNA Isolation, Library Creation, and Sequencing",               4, "has_gene_expression"),
    ("txomics_seq_processing",  "Sequence Data Processing",                                      4, "has_gene_expression"),
    ("txomics_qc",              "Sequencing Quality Checks and Outlier Removal",                 4, "has_gene_expression"),
    ("txomics_normalization",   "Data Normalization",                                            4, "has_gene_expression"),
    ("data_analysis",           "Data Analysis",                                                 3, None),
    ("stat_analysis",           "Statistical Analysis of Body Weights, Organ Weights, and Clinical Pathology",  4, None),
    ("bmd_apical",              "Benchmark Dose Analysis of Body Weights, Organ Weights, and Clinical Pathology", 4, None),
    ("bmd_genomics",            "Benchmark Dose Analysis of Transcriptomics Data",               4, "has_gene_expression"),
    ("efdr",                    "Empirical False Discovery Rate Determination for Genomic Dose-response Modeling", 4, "has_gene_expression"),
    ("data_accessibility",      "Data Accessibility",                                            4, None),
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MethodsContext:
    """
    All study metadata extracted from the file pool.

    Used to:
      1. Inform the LLM prompt with actual study parameters.
      2. Decide which conditional subsections to include.
      3. Build Table 1 (genomics sample counts) programmatically.
    """
    # --- Chemical identity ---
    chemical_name: str = ""
    casrn: str = ""
    dtxsid: str = ""

    # --- Study design (from fingerprints + animal_report) ---
    # species includes strain when available, e.g. "Hsd:Sprague Dawley® SD®"
    species: str = "Sprague Dawley"
    dose_groups: list[float] = field(default_factory=list)
    dose_unit: str = "mg/kg"
    n_per_group: int = 5
    n_control: int = 10
    # How many animals per sex per dose for internal dose assessment (biosampling)
    n_biosampling: int = 0
    sexes: list[str] = field(default_factory=list)
    vehicle: str = "corn oil"
    route: str = "gavage"
    duration_days: int = 5

    # --- Domain presence flags (drive conditional subsections) ---
    has_body_weight: bool = False
    has_organ_weights: bool = False
    has_clin_chem: bool = False
    has_hematology: bool = False
    has_hormones: bool = False
    has_tissue_conc: bool = False
    has_gene_expression: bool = False

    @property
    def has_clin_path(self) -> bool:
        """True if any clinical pathology domain exists (clin_chem, hematology, or hormones)."""
        return self.has_clin_chem or self.has_hematology or self.has_hormones

    # --- Endpoint names by domain (from fingerprints) ---
    organ_weight_endpoints: list[str] = field(default_factory=list)
    clin_chem_endpoints: list[str] = field(default_factory=list)
    hematology_endpoints: list[str] = field(default_factory=list)
    hormone_endpoints: list[str] = field(default_factory=list)
    # Organs with gene expression data (e.g. ["Liver", "Kidney"])
    ge_organs: list[str] = field(default_factory=list)

    # --- BMDExpress / BMDS metadata (from .bm2 analysisInfo.notes) ---
    bmdexpress_version: str | None = None
    bmds_version: str | None = None
    bmr_type: str | None = None
    bmr_factor: float | None = None
    models_fit: list[str] | None = None
    constant_variance: bool | None = None
    # Pre-filter method for transcriptomics (Williams or CurveFit)
    prefilter_method: str | None = None
    prefilter_pvalue: float | None = None
    fold_change_filter: float | None = None

    # --- Table 1: sample counts for genomics BMD analysis ---
    # Structure: {organ: {sex: {dose_float: count}}}
    # Built from animal_report or gene_expression fingerprints
    genomics_sample_counts: dict | None = None

    def to_dict(self) -> dict:
        """Serialize for JSON persistence.  Converts dataclass to a plain dict."""
        d = {}
        for f in self.__dataclass_fields__:
            d[f] = getattr(self, f)
        # Include the computed property too
        d["has_clin_path"] = self.has_clin_path
        return d

    @classmethod
    def from_dict(cls, d: dict) -> MethodsContext:
        """Reconstruct from a JSON-serialized dict."""
        # Filter to only fields that exist on the dataclass
        valid_fields = set(cls.__dataclass_fields__)
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class MethodsSection:
    """
    A single M&M subsection with heading and content.

    heading:    The subsection heading text (e.g. "Study Design").
    level:      Heading depth — 3 = H3, 4 = H4 in the DOCX.
    key:        Subsection key matching SUBSECTION_SKELETON (e.g. "study_design").
    paragraphs: Prose paragraphs (user-editable in the frontend).
    table:      Optional table data for programmatic tables like Table 1.
                Format: {"caption": str, "headers": [...], "rows": [[...]], "footnotes": [...]}
    """
    heading: str
    level: int
    key: str
    paragraphs: list[str] = field(default_factory=list)
    table: dict | None = None

    def to_dict(self) -> dict:
        return {
            "heading": self.heading,
            "level": self.level,
            "key": self.key,
            "paragraphs": self.paragraphs,
            "table": self.table,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MethodsSection:
        return cls(
            heading=d["heading"],
            level=d["level"],
            key=d["key"],
            paragraphs=d.get("paragraphs", []),
            table=d.get("table"),
        )


@dataclass
class MethodsReport:
    """
    Complete structured M&M output.

    sections:  Ordered list of MethodsSection objects (heading hierarchy preserved).
    context:   The MethodsContext used to generate this report — retained so the
               DOCX builder can access study parameters for Table 1 generation.
    """
    sections: list[MethodsSection] = field(default_factory=list)
    context: MethodsContext = field(default_factory=MethodsContext)

    def to_dict(self) -> dict:
        return {
            "sections": [s.to_dict() for s in self.sections],
            "context": self.context.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> MethodsReport:
        return cls(
            sections=[MethodsSection.from_dict(s) for s in d.get("sections", [])],
            context=MethodsContext.from_dict(d.get("context", {})),
        )


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

    return ctx


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


# ---------------------------------------------------------------------------
# Subsection skeleton: which subsections to include given the context
# ---------------------------------------------------------------------------

def build_subsection_skeleton(ctx: MethodsContext) -> list[tuple[str, str, int]]:
    """
    Determine which M&M subsections to include based on domain presence.

    Returns a list of (subsection_key, heading_text, heading_level) tuples
    in the correct order for both the LLM prompt and the DOCX output.

    Args:
        ctx: MethodsContext with domain presence flags set.

    Returns:
        Filtered list of subsections that apply to this study.
    """
    skeleton = []
    for key, heading, level, condition in SUBSECTION_SKELETON:
        if condition is None:
            # Always included
            skeleton.append((key, heading, level))
        else:
            # Check the condition field on MethodsContext
            if getattr(ctx, condition, False):
                skeleton.append((key, heading, level))
    return skeleton


# ---------------------------------------------------------------------------
# LLM prompt builder
# ---------------------------------------------------------------------------

def build_methods_prompt(ctx: MethodsContext) -> tuple[str, str]:
    """
    Build the structured LLM prompt for M&M generation.

    Returns (system_prompt, user_prompt) strings.

    The user prompt includes all extracted study context and asks the LLM
    to return a JSON object keyed by subsection key.  Only keys for
    present domains are requested.

    Args:
        ctx: Populated MethodsContext.

    Returns:
        Tuple of (system_prompt, user_prompt).
    """
    system = (
        "You are a toxicology report writer specializing in NTP/NIEHS-style "
        "technical reports for 5-day genomic dose-response studies. "
        "Write precise, formal scientific text. "
        "Return ONLY valid JSON with no markdown formatting."
    )

    # Build the study context block with actual data
    dose_str = ", ".join(str(d) for d in ctx.dose_groups) if ctx.dose_groups else "not specified"
    sexes_str = " and ".join(ctx.sexes) if ctx.sexes else "male and female"

    context_block = f"""## Study Context
- Chemical: {ctx.chemical_name} (CASRN: {ctx.casrn}, DTXSID: {ctx.dtxsid})
- Species: {ctx.species} rats
- Sexes: {sexes_str}
- Route of administration: oral {ctx.route}
- Vehicle: {ctx.vehicle}
- Duration: {ctx.duration_days} days
- Dose groups ({ctx.dose_unit}): {dose_str}
- Animals per treatment group: {ctx.n_per_group} {sexes_str} per dose
- Animals in vehicle control: {ctx.n_control} {sexes_str}"""

    if ctx.n_biosampling > 0:
        context_block += f"\n- Biosampling animals: {ctx.n_biosampling} total"

    # Domain-specific context
    if ctx.has_organ_weights and ctx.organ_weight_endpoints:
        context_block += f"\n- Organs weighed: {', '.join(ctx.organ_weight_endpoints)}"
    if ctx.has_clin_chem and ctx.clin_chem_endpoints:
        context_block += f"\n- Clinical chemistry parameters: {', '.join(ctx.clin_chem_endpoints)}"
    if ctx.has_hematology and ctx.hematology_endpoints:
        context_block += f"\n- Hematology parameters: {', '.join(ctx.hematology_endpoints)}"
    if ctx.has_hormones and ctx.hormone_endpoints:
        context_block += f"\n- Hormone parameters: {', '.join(ctx.hormone_endpoints)}"
    if ctx.has_gene_expression and ctx.ge_organs:
        context_block += f"\n- Transcriptomics organs: {', '.join(ctx.ge_organs)}"
    if ctx.has_tissue_conc:
        context_block += "\n- Internal dose assessment: tissue concentration data available"

    # BMDExpress metadata
    if ctx.bmdexpress_version:
        context_block += f"\n- BMDExpress version: {ctx.bmdexpress_version}"
    if ctx.bmds_version:
        context_block += f"\n- BMDS version: {ctx.bmds_version}"
    if ctx.models_fit:
        context_block += f"\n- BMD models fit: {', '.join(ctx.models_fit)}"
    if ctx.bmr_type:
        context_block += f"\n- BMR type: {ctx.bmr_type}"
    if ctx.bmr_factor is not None:
        context_block += f"\n- BMR factor: {ctx.bmr_factor}"
    if ctx.prefilter_method:
        context_block += f"\n- Pre-filter method: {ctx.prefilter_method}"
    if ctx.prefilter_pvalue is not None:
        context_block += f"\n- Pre-filter p-value cutoff: {ctx.prefilter_pvalue}"
    if ctx.constant_variance is not None:
        context_block += f"\n- Constant variance: {'yes' if ctx.constant_variance else 'no'}"

    # Build subsection requirements
    skeleton = build_subsection_skeleton(ctx)
    subsection_keys = [key for key, _, _ in skeleton]

    # Per-subsection guidance for the LLM
    guidelines = _build_subsection_guidelines(ctx, skeleton)

    user_prompt = f"""Generate the Materials and Methods section for a {ctx.duration_days}-day genomic dose-response study report.

{context_block}

## Required Subsections
Generate content for ONLY the following subsections (in order).
Return your response as a JSON object where each key is a subsection identifier
and the value is a string containing 1-3 paragraphs of prose.

Keys to generate: {subsection_keys}

{guidelines}

## Important formatting notes:
- Do NOT include section headers in the text — they will be added by the template.
- Write in past tense, third person, formal NIEHS/NTP technical report style.
- Reference exact study parameters from the context above (dose groups, species, etc.).
- Each value should be a single string. Use \\n\\n to separate multiple paragraphs within a subsection.
- Return ONLY the JSON object, no markdown code fences."""

    return system, user_prompt


def _build_subsection_guidelines(
    ctx: MethodsContext,
    skeleton: list[tuple[str, str, int]],
) -> str:
    """
    Build per-subsection prose guidelines for the LLM prompt.

    Each guideline tells the LLM exactly what to cover in that subsection
    and references the actual study parameters from the context.

    Args:
        ctx:      MethodsContext with study parameters.
        skeleton: The filtered subsection skeleton.

    Returns:
        Formatted string of guidelines.
    """
    dose_str = ", ".join(str(d) for d in ctx.dose_groups) if ctx.dose_groups else "not specified"
    sexes_str = " and ".join(ctx.sexes) if ctx.sexes else "male and female"

    guides: dict[str, str] = {
        "study_design": (
            f"One paragraph covering: animal source and quarantine (7 days), "
            f"randomization by body weight, dose groups ({dose_str} {ctx.dose_unit}), "
            f"dosing schedule ({ctx.duration_days} consecutive days by oral {ctx.route}), "
            f"sample sizes ({ctx.n_per_group} {sexes_str} per treatment group, "
            f"{ctx.n_control} {sexes_str} vehicle control), "
            f"{'biosampling animals for internal dose assessment, ' if ctx.n_biosampling > 0 else ''}"
            f"necropsy timing (approximately 24 hours after the final dose)."
        ),
        "dose_selection": (
            "One paragraph. Reference LD50 predictions if available, "
            "explain the dose spacing rationale (half-log dose spacing), "
            "rationale for top dose selection, and target of no overt systemic toxicity."
        ),
        "chemistry": (
            f"First paragraph: {ctx.chemical_name} source (typically synthesized by contract lab or obtained from commercial supplier), "
            f"lot number (state that lot details are in the full study protocol), "
            f"identity confirmation methods (IR, NMR, or mass spectrometry), purity (typically >95%%), storage conditions. "
            f"Second paragraph: dose formulation preparation in {ctx.vehicle}, "
            f"concentration verification by analytical chemistry, formulation QC analysis."
        ),
        "clinical_exams": (
            "Brief introductory paragraph describing the scope of clinical examinations "
            "performed during the study: clinical observations, body/organ weight collection, "
            "clinical pathology sampling, and (if applicable) tissue collection for internal dose assessment."
        ),
        "clinical_obs": (
            "One paragraph. Standard boilerplate: animals were observed twice daily for morbidity/mortality, "
            "clinical observations were recorded once daily, "
            "cage-side observations included assessment of general appearance, behavior, and respiratory patterns."
        ),
        "body_organ_weights": (
            f"One paragraph. Body weights recorded on study day 0 and at necropsy. "
            f"{'Organ weights: ' + ', '.join(ctx.organ_weight_endpoints[:10]) + '.' if ctx.organ_weight_endpoints else 'Organs were weighed at necropsy.'} "
            f"Absolute and relative (organ-to-body-weight ratio) weights calculated."
        ),
        "clinical_pathology": (
            f"One paragraph covering blood collection method (retroorbital or cardiac puncture under anesthesia), "
            f"sample processing. "
            f"{'Clinical chemistry parameters: ' + ', '.join(ctx.clin_chem_endpoints[:10]) + '. ' if ctx.clin_chem_endpoints else ''}"
            f"{'Hematology parameters: ' + ', '.join(ctx.hematology_endpoints[:10]) + '. ' if ctx.hematology_endpoints else ''}"
            f"{'Hormone parameters: ' + ', '.join(ctx.hormone_endpoints[:5]) + '. ' if ctx.hormone_endpoints else ''}"
            f"Reference the analyzer instruments (e.g., Advia 120 for hematology, AU680 for clinical chemistry)."
        ),
        "internal_dose": (
            "One paragraph. Describe tissue collection for internal dose assessment: "
            "blood/serum and tissue samples collected at necropsy, stored at -80°C, "
            "analyzed by LC-MS/MS for parent compound and/or metabolite concentrations."
        ),
        "transcriptomics": (
            f"Brief introductory paragraph: transcriptomic profiling was performed on "
            f"{', '.join(ctx.ge_organs) if ctx.ge_organs else 'target organs'} "
            f"using the TempO-Seq targeted RNA sequencing platform (BioSpyder Technologies)."
        ),
        "txomics_sample": (
            "One paragraph. RNA was isolated from flash-frozen tissue samples. "
            "Describe tissue homogenization, RNA extraction method (e.g., RNeasy), "
            "RNA quality assessment (RIN values)."
        ),
        "txomics_rna": (
            "One paragraph. TempO-Seq S1500+ platform (BioSpyder Technologies), "
            "library preparation with detector oligos, ligation, amplification, "
            "multiplexed sequencing on Illumina platform."
        ),
        "txomics_seq_processing": (
            "One paragraph. Demultiplexing, alignment to probe reference sequences, "
            "count table generation using the TempO-SeqR pipeline."
        ),
        "txomics_qc": (
            "One paragraph. Outlier detection by principal component analysis and "
            "total read count thresholds. Samples below quality thresholds were excluded "
            "from downstream analysis."
        ),
        "txomics_normalization": (
            "One paragraph. DESeq2 median-of-ratios normalization or TMM normalization. "
            "Describe the normalization method used for count data."
        ),
        "data_analysis": (
            "Brief introductory paragraph: overview of the statistical and dose-response "
            "modeling approaches applied to both apical and transcriptomic endpoints."
        ),
        "stat_analysis": (
            "One paragraph. Standard NIEHS statistical pipeline: "
            "Jonckheere trend test for monotonic dose-response, followed by "
            "Williams test (if monotonic) or Dunnett test (if non-monotonic) for pairwise comparisons. "
            "Shirley nonparametric test used when data did not meet normality/homogeneity assumptions. "
            "Dunn test for non-parametric pairwise comparisons. "
            "Significance threshold: p < 0.05."
        ),
        "bmd_apical": (
            f"One paragraph. Benchmark dose modeling of apical endpoints using "
            f"{'BMDS ' + ctx.bmds_version if ctx.bmds_version else 'EPA BMDS software'}. "
            f"{'Models fit: ' + ', '.join(ctx.models_fit) + '. ' if ctx.models_fit else ''}"
            f"{'BMR: ' + str(ctx.bmr_factor) + ' ' + (ctx.bmr_type or 'standard deviation') + ' from the control mean. ' if ctx.bmr_factor is not None else ''}"
            f"{'Constant variance assumed. ' if ctx.constant_variance else ''}"
            f"Model selection by lowest AIC or Laplace model averaging."
        ),
        "bmd_genomics": (
            f"One paragraph. Benchmark dose modeling of transcriptomic data using "
            f"{ctx.bmdexpress_version or 'BMDExpress'} with "
            f"{'BMDS ' + ctx.bmds_version if ctx.bmds_version else 'EPA BMDS'}. "
            f"{'Pre-filter: ' + ctx.prefilter_method + ' (p < ' + str(ctx.prefilter_pvalue) + ')' if ctx.prefilter_method and ctx.prefilter_pvalue else ''}"
            f"{'Models fit: ' + ', '.join(ctx.models_fit) + '. ' if ctx.models_fit else ''}"
            f"Describe gene-level BMD derivation, GO term / pathway enrichment using "
            f"category analysis, and filtering criteria (goodness-of-fit p > 0.1, "
            f"BMDU/BMDL ratio ≤ 40, minimum 5%% gene set coverage)."
        ),
        "efdr": (
            "One paragraph. Empirical false discovery rate estimation by permutation: "
            "dose labels are randomly shuffled to create null datasets, "
            "the full BMD analysis pipeline is run on permuted data, "
            "and the fraction of false positives at each BMD threshold is estimated. "
            "Reference the number of permutations used."
        ),
        "data_accessibility": (
            "One paragraph. Data availability statement: "
            "all raw and processed data are available through the NIEHS Chemical Effects "
            "in Biological Systems (CEBS) database or the study's data repository. "
            "Provide placeholder for DOI or accession number."
        ),
    }

    lines = ["## Guidelines per subsection:"]
    for key, heading, level in skeleton:
        if key in guides:
            lines.append(f"- {key}: {guides[key]}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Table 1 builder
# ---------------------------------------------------------------------------

def build_table1_data(ctx: MethodsContext) -> dict | None:
    """
    Build Table 1: Final Sample Counts for BMD Analysis of Transcriptomics Data.

    This table shows the number of samples per organ × sex × dose group
    that passed QC and were included in the BMD analysis.

    Args:
        ctx: MethodsContext with genomics_sample_counts populated.

    Returns:
        Dict with keys: caption, headers, rows, footnotes.
        Or None if no genomics data.
    """
    if not ctx.genomics_sample_counts:
        return None

    # Headers: empty corner cell + dose group columns
    dose_headers = []
    for d in ctx.dose_groups:
        # Format: "0 mg/kg", "0.15 mg/kg", etc.
        if d == int(d):
            dose_headers.append(f"{int(d)} {ctx.dose_unit}")
        else:
            dose_headers.append(f"{d} {ctx.dose_unit}")

    headers = [""] + dose_headers

    # Rows: grouped by sex, then by organ
    rows = []
    all_sexes = sorted({
        sex
        for organ_data in ctx.genomics_sample_counts.values()
        for sex in organ_data
    })
    all_organs = sorted(ctx.genomics_sample_counts.keys())

    for sex in all_sexes:
        # Sex header row (bold — indicated by leading **)
        rows.append([f"**{sex}**"] + [""] * len(ctx.dose_groups))

        for organ in all_organs:
            sex_data = ctx.genomics_sample_counts.get(organ, {}).get(sex, {})
            row = [f"  {organ}"]
            for dose in ctx.dose_groups:
                count = sex_data.get(dose, 0)
                if count > 0:
                    row.append(str(count))
                else:
                    # Dash indicates no samples (mortality, exclusion, etc.)
                    row.append("–")
            rows.append(row)

    return {
        "caption": "Final Sample Counts for BMD Analysis of Transcriptomics Data",
        "headers": headers,
        "rows": rows,
        "footnotes": [],
    }


# ---------------------------------------------------------------------------
# DOCX generation: add structured M&M to a python-docx Document
# ---------------------------------------------------------------------------

def add_methods_to_doc(
    doc,
    methods_report: MethodsReport,
    start_table_num: int = 1,
) -> int:
    """
    Add the structured Materials and Methods section to a python-docx Document.

    Generates the full NIEHS-style M&M with hierarchical headings (H2, H3, H4),
    prose paragraphs per subsection, and Table 1 (genomics sample counts).

    Follows the same DOCX formatting conventions as add_animal_report_to_doc():
    - Calibri 11pt for body text
    - Calibri 9pt for table cells and captions
    - "Light Shading Accent 1" table style
    - Sequential table numbering

    Args:
        doc:             python-docx Document object.
        methods_report:  MethodsReport with sections and context populated.
        start_table_num: Table number to start from (for sequential numbering).

    Returns:
        Next table number (for subsequent sections to continue from).
    """
    from docx.shared import Pt
    from docx.enum.table import WD_TABLE_ALIGNMENT

    table_num = start_table_num

    # --- Top-level heading ---
    doc.add_heading("Materials and Methods", level=2)

    # --- Render each subsection ---
    for section in methods_report.sections:
        # Add heading at the appropriate level
        doc.add_heading(section.heading, level=section.level)

        # Add prose paragraphs
        for para_text in section.paragraphs:
            if not para_text.strip():
                continue
            p = doc.add_paragraph()
            run = p.add_run(para_text)
            run.font.size = Pt(11)
            run.font.name = "Calibri"
            p.paragraph_format.space_after = Pt(6)

        # Add table if present (e.g. Table 1)
        if section.table:
            table_num = _add_methods_table(
                doc, section.table, table_num,
            )

    # --- Add Table 1 at the end if genomics data exists ---
    # Table 1 is appended after all prose subsections, matching the
    # NIEHS report layout where it follows the Data Analysis section.
    table1_data = build_table1_data(methods_report.context)
    if table1_data:
        table_num = _add_methods_table(doc, table1_data, table_num)

    return table_num


def _add_methods_table(doc, table_data: dict, table_num: int) -> int:
    """
    Add a formatted table to the DOCX document.

    Handles the caption-above-table pattern, bold sex-header rows,
    and footnotes below the table.

    Args:
        doc:        python-docx Document.
        table_data: Dict with caption, headers, rows, footnotes.
        table_num:  Current table number for caption.

    Returns:
        Next table number.
    """
    from docx.shared import Pt
    from docx.enum.table import WD_TABLE_ALIGNMENT

    headers = table_data["headers"]
    rows = table_data["rows"]
    caption_text = table_data.get("caption", "")
    footnotes = table_data.get("footnotes", [])

    n_cols = len(headers)
    n_rows = len(rows)

    # Create the table
    table = doc.add_table(rows=1 + n_rows, cols=n_cols)
    table.style = "Light Shading Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Caption paragraph (inserted before the table)
    caption = doc.add_paragraph()
    run = caption.add_run(f"Table {table_num}. {caption_text}")
    run.font.size = Pt(9)
    run.font.name = "Calibri"
    run.italic = True
    caption.paragraph_format.space_after = Pt(4)
    # Move caption before the table element in the document XML
    table._element.addprevious(caption._element)

    # Header row
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for para in cell.paragraphs:
            for r in para.runs:
                r.bold = True
                r.font.size = Pt(9)
                r.font.name = "Calibri"

    # Data rows
    for row_idx, row_data in enumerate(rows):
        row = table.rows[1 + row_idx]
        for col_idx, val in enumerate(row_data):
            cell = row.cells[col_idx]
            # Check for bold marker (sex header rows: "**Male**")
            is_bold = val.startswith("**") and val.endswith("**")
            clean_val = val.strip("*").strip() if is_bold else val.strip()
            cell.text = clean_val
            for para in cell.paragraphs:
                for r in para.runs:
                    r.font.size = Pt(9)
                    r.font.name = "Calibri"
                    if is_bold:
                        r.bold = True

    # Footnotes below the table
    for fn in footnotes:
        p = doc.add_paragraph()
        run = p.add_run(fn)
        run.font.size = Pt(8)
        run.font.name = "Calibri"
        run.italic = True
        p.paragraph_format.space_after = Pt(2)

    return table_num + 1
