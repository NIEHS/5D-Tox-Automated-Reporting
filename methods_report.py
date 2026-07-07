"""
methods_report.py — backward-compatible facade over the methods_* /
abstract_* submodules.

The original ~3200-line monolith was extracted into focused submodules
across the methods_* and abstract_* commits on this branch:

  methods_models.py        SUBSECTION_SKELETON + MethodsContext +
                           MethodsSection + MethodsReport dataclasses
  methods_extract.py       extract_methods_context + the bm2 / PK /
                           biosampling / genomics-assay / sample-count
                           extractors that feed it
  methods_prompt.py        build_methods_prompt + build_subsection_skeleton
                           + per-subsection LLM guideline composer
  methods_table1.py        build_table1_data — the only programmatic
                           table in the Methods section
  narrative_helpers.py     cross-cutting formatters used by 4+ narrative
                           sections (_join_oxford, _format_dose_value,
                           _is_reliable_bmd, _picks_above_lle, etc.)
  abstract_methods.py      Abstract → Methods paragraph (deterministic)
  abstract_apical.py       body-Results per-platform narrative +
                           Abstract → Results apical paragraph
  abstract_genomics.py     Abstract → Results genomics paragraph +
                           sentence builders
  abstract_pk.py           Abstract → Results pharmacokinetics paragraph
  gene_bodies.py           body Results: Gene Set BMD + Gene BMD analysis
                           intro/findings paragraphs
  abstract_summary.py      Abstract → Summary + Abstract → Results
                           aggregator (the only abstract_* module that
                           imports from sibling abstract_* modules)

What still lives here:

  - re-exports of every public + private name above, so existing
    importers don't need to change

External importers preserved through this shim:

  - genomics_narratives.py  build_gene_set_body_{intro,findings},
                            build_gene_body_{intro,findings}
  - llm_routes.py           extract_methods_context + build_methods_prompt
                            + build_subsection_skeleton + build_table1_data
                            + MethodsReport + MethodsSection
  - process_integrated.py   build_apical_bmd_summary_narrative,
                            same MethodsReport / extract_methods_context
                            set as llm_routes
  - report_data.py           MethodsContext + build_abstract_methods +
                            build_abstract_results + build_abstract_summary
  - processing_helpers.py   _is_anomalous_bmd (lazy import inside a
                            helper)

A future cleanup pass could point each consumer at the new modules
directly and delete this shim, but that's not part of this split.
"""

# ---------------------------------------------------------------------------
# Re-exports: dataclasses + heading skeleton
# ---------------------------------------------------------------------------
from methods_models import (
    SUBSECTION_SKELETON,
    MethodsContext,
    MethodsSection,
    MethodsReport,
)

# ---------------------------------------------------------------------------
# Re-exports: cross-cutting narrative helpers
# ---------------------------------------------------------------------------
from narrative_helpers import (
    _DIRECTION_WORDS,
    ANOMALY_RATIO_THRESHOLD,
    _is_reliable_bmd,
    _is_anomalous_bmd,
    _format_dose_value,
    _format_rat_gene_symbol,
    _stat_display_name,
    _join_oxford,
    _format_dose_list,
    _format_organ_list,
    _format_organ_phrase,
    _normalize_organ_name,
    _format_paired_bmd_pairs,
    _picks_above_lle,
)

# ---------------------------------------------------------------------------
# Re-exports: methods context extractor
# ---------------------------------------------------------------------------
from methods_extract import (
    _parse_bm2_analysis_info,
    _collect_bm2_analysis_metadata,
    extract_methods_context,
    _extract_biosampling_doses,
    _extract_pk_data,
    _extract_genomics_assay,
    _build_genomics_sample_counts,
)

# ---------------------------------------------------------------------------
# Re-exports: LLM prompt assembly
# ---------------------------------------------------------------------------
from methods_prompt import (
    build_subsection_skeleton,
    build_methods_prompt,
    _build_subsection_guidelines,
)

# ---------------------------------------------------------------------------
# Re-exports: Table 1 builder
# ---------------------------------------------------------------------------
from methods_table1 import build_table1_data

# ---------------------------------------------------------------------------
# Re-exports: narrative builders (apical, genomics, pk, gene bodies, summary)
# ---------------------------------------------------------------------------
from abstract_methods import build_abstract_methods
from abstract_apical import (
    _normalize_endpoint_name,
    _format_endpoint_phrase,
    _format_bmd_pair,
    build_apical_bmd_summary_narrative,
    build_abstract_results_apical,
)
from abstract_genomics import (
    _build_gene_sets_sentence,
    _build_top_genes_sentence,
    build_abstract_results_genomics,
)
from abstract_pk import build_abstract_results_pk
from gene_bodies import (
    build_gene_set_body_intro,
    build_gene_set_body_findings,
    build_gene_body_intro,
    build_gene_body_findings,
)
from abstract_summary import (
    build_abstract_summary,
    build_abstract_results,
)
