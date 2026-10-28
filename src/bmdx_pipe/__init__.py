"""
bmdx_pipe — BMDExpress data integration pipeline.

Extracts the core data-processing logic from the 5dToxReport web app into a
standalone, framework-free library.  Covers file fingerprinting, cross-file
validation, pool integration (merging .bm2 / .txt / .xlsx into a unified
BMDProject), NTP statistical analysis (Jonckheere, Williams, Dunnett), and
report table generation.

The library depends on a local BMDExpress 3 build for Java interop
(ExportBm2, ExportGenomics, ExportCategories, IntegrateProject, RunPrefilter).
Set the BMDX_PROJECT_ROOT environment variable to point at the BMDExpress-3
checkout if it's not at ~/Dev/Projects/BMDExpress-3.
"""

# ── File fingerprinting & validation ──────────────────────────────────────
from .file_integrator import (
    FileFingerprint,
    ValidationReport,
    fingerprint_file,
    validate_pool,
    derived_source,
    lightweight_validate,
    classify_derived_by_anchor,
    detect_platform_and_type_from_bm2,
    _BM2_PLATFORM_MAP,
)

# ── The study the workbooks describe ──────────────────────────────────────
from .study_workbook import StudyWorkbook, read_study_workbook, title_facts
from .study_structure import StudyStructure, build_study_structure, check_against_structure
from .sample_sheet import read_sample_sheet, resolve_sample

# ── Pool integration (merge files → unified BMDProject JSON) ─────────────
from .pool_integrator import (
    integrate_pool,
    export_integrated_bm2,
    subset_bm2,
    tox_study_csv_to_pivot_txt,
    long_rows_to_pivot,
    study_workbook_to_pool_files,
    WORKBOOK_STEMS,
    extract_xlsx_value_map,
    key_sheet_units,
)

# ── Statistical analysis & table generation ───────────────────────────────
from .apical_report import (
    build_table_data,
    build_table_data_from_bm2,
    build_category_lookup,
    export_bm2,
    export_genomics,
    export_categories,
    annotate_missing_animals,
    backfill_missing_doses,
    TableRow,
)

# ── NTP endpoint statistics (Jonckheere, Williams, Dunnett) ───────────────
from .apical_stats import (
    analyze_endpoint,
    run_java_prefilter,
    run_apical_bmds_java,
    EndpointStats,
)

# ── Animal traceability ──────────────────────────────────────────────────
from .animal_report import (
    AnimalReport,
    AnimalRecord,
    DomainAttrition,
    build_animal_report,
    report_to_dict,
)

# ── LLM-based experiment metadata inference ──────────────────────────────
from .experiment_metadata import (
    VOCABULARIES,
    attach_metadata,
    infer_experiment_metadata,
)

# ── Java bridge (classpath / paths) ──────────────────────────────────────
from .java_bridge import build_classpath, BMDX_PROJECT, JAVA_HELPER_DIR

# ── Clinical observation incidence tables ─────────────────────────────────
from .clinical_observations import (
    IncidenceRow,
    build_clinical_obs_tables,
)

# ── BM2 cache (optional LMDB memoisation of Java exports) ────────────────
from . import bm2_cache
