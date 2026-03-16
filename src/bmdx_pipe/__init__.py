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
    lightweight_validate,
    detect_platform_and_type_from_bm2,
    _BM2_PLATFORM_MAP,
)

# ── Pool integration (merge files → unified BMDProject JSON) ─────────────
from .pool_integrator import integrate_pool

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
    generate_results_narrative,
    add_apical_tables_to_doc,
    add_bmd_summary_table_to_doc,
    add_gene_set_bmd_tables_to_doc,
    add_gene_bmd_tables_to_doc,
    TableRow,
)

# ── NTP endpoint statistics (Jonckheere, Williams, Dunnett) ───────────────
from .apical_stats import (
    analyze_endpoint,
    run_java_prefilter,
    EndpointStats,
)

# ── Animal traceability ──────────────────────────────────────────────────
from .animal_report import (
    build_animal_report,
    report_to_dict,
    add_animal_report_to_doc,
)

# ── LLM-based experiment metadata inference ──────────────────────────────
from .experiment_metadata import (
    attach_metadata,
    infer_experiment_metadata,
)

# ── Java bridge (classpath / paths) ──────────────────────────────────────
from .java_bridge import build_classpath, BMDX_PROJECT, JAVA_HELPER_DIR

# ── BM2 cache (optional LMDB memoisation of Java exports) ────────────────
from . import bm2_cache
