"""
Dataclasses + heading skeleton for the Materials & Methods section.

The methods-generation pipeline operates on three concrete types — a
MethodsContext (the structured study metadata that drives both the LLM
prompt and the programmatic Table 1), MethodsSection (one heading +
its prose + optional table), and MethodsReport (an ordered list of
sections plus the context that produced them).  Plus one canonical
constant — SUBSECTION_SKELETON — listing the section keys, their
heading text, heading level, and the optional MethodsContext flag that
gates conditional inclusion.

These three types are the wire format between every step in the
pipeline: extract_methods_context produces a MethodsContext;
build_methods_prompt + the LLM produce MethodsSection prose;
MethodsReport.to_dict / from_dict mediates JSON persistence and round-
trip restore through session_routes; report_data / build_docx consume
MethodsReport when assembling the final document.

Pulled out of the original 3232-line methods_report.py so every other
module in the split can import them without dragging the whole
narrative-builder + extractor surface along with them.  Re-exported
from methods_report.py for backward compatibility with existing
import sites (genomics_narratives, llm_routes, process_integrated,
report_data, processing_helpers).
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Heading skeleton — drives section ordering and conditional inclusion
# ---------------------------------------------------------------------------
# Each tuple: (subsection_key, heading_text, heading_level, condition_field)
# condition_field is the MethodsContext bool field/property that must be
# True for the subsection to be included.  None means always included.
#
# level 2 = H2 ("Materials and Methods" — added by caller)
# level 3 = H3 (major subsections: Study Design, Chemistry, etc.)
# level 4 = H4 (sub-subsections: Clinical Observations, Body Weights, etc.)
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
# MethodsContext — the structured study metadata
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

    # --- Biosampling / pharmacokinetic context (for Abstract-Methods) ---
    # Dose groups that had biosampling animals dedicated to internal dose
    # assessment (blood/plasma collection).  Extracted from sidecar files
    # (tissue_conc or body_weight) by scanning for rows with selection
    # containing "biosampling".  Reference report writes e.g.:
    #   "Blood was collected from animals dedicated for internal dose
    #    assessment in the 4 and 37 mg/kg groups."
    biosampling_doses: list[float] = field(default_factory=list)

    # --- Pharmacokinetics (for Abstract-Results PK sentence) ---
    # Aggregated plasma concentration means per sex × dose × timepoint,
    # plus calculated half-lives per sex × dose.  Built from tissue
    # concentration sidecars (the only domain that uses biosampling
    # animals).  Half-lives use the standard two-point formula:
    #   t½ = ln(2) × Δt / ln(C₁/C₂)
    # where C₁ is the early timepoint concentration and C₂ the later one.
    # Reference report writes:
    #   "Average PFHxSAm plasma concentrations at 2 and 24 hours postdose
    #    were lower in male rats than in female rats. Half-lives ... were
    #    78.2 and 25.6 hours for the 4 and 37 mg/kg groups, respectively..."
    #
    # Schema:
    #   pk_concentrations: {sex: {dose: {hour: mean_value}}}
    #   pk_half_lives:     {sex: {dose: hours_float}}
    #   pk_timepoints:     sorted list of timepoints in hours (e.g., [2, 24])
    pk_concentrations: dict | None = None
    pk_half_lives: dict | None = None
    pk_timepoints: list[int] = field(default_factory=list)

    # --- Genomics assay identification (for Abstract-Methods) ---
    # Human-readable assay name (e.g., "TempO-Seq", "Affymetrix", "RNA-seq")
    # and the chip/probe-set name (e.g., "S1500+").  Extracted from the
    # integrated BMDProject's gene-expression experiments via chip.name
    # and chip.chipId — S1500 in the chip name implies TempO-Seq.
    # Reference report writes e.g.:
    #   "...assayed in gene expression studies using the TempO-Seq assay."
    genomics_assay: str | None = None
    genomics_chip: str | None = None

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


# ---------------------------------------------------------------------------
# MethodsSection — one heading + its prose + optional table
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# MethodsReport — the assembled output
# ---------------------------------------------------------------------------

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
