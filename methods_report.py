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


# Dataclasses + heading skeleton moved to methods_models.py so the upcoming
# split narrative-builder modules can import them without dragging this
# whole extractor + builder surface along.  Re-imported under their
# original names for backward compatibility with existing import sites
# (genomics_narratives, llm_routes, process_integrated, report_pdf,
# session_routes, processing_helpers).
from methods_models import (
    SUBSECTION_SKELETON,
    MethodsContext,
    MethodsSection,
    MethodsReport,
)

# Cross-cutting formatters + BMD-quality predicates moved to
# narrative_helpers.py.  Re-imported under their original names so the
# many in-file callers (and external processing_helpers._is_anomalous_bmd)
# continue to work unchanged.
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

# Methods context extractor moved to methods_extract.py.  Re-imported
# under their original names so existing call sites (llm_routes,
# process_integrated) keep working unchanged.
from methods_extract import (
    _parse_bm2_analysis_info,
    _collect_bm2_analysis_metadata,
    extract_methods_context,
    _extract_biosampling_doses,
    _extract_pk_data,
    _extract_genomics_assay,
    _build_genomics_sample_counts,
)

# LLM prompt assembly + subsection-skeleton filter moved to methods_prompt.py.
# Re-imported so external callers (llm_routes uses both together to drive
# /api/generate-methods) keep working unchanged.
from methods_prompt import (
    build_subsection_skeleton,
    build_methods_prompt,
    _build_subsection_guidelines,
)

# Table 1 builder (Final Sample Counts for BMD Analysis of Transcriptomics
# Data) moved to methods_table1.py.  Re-imported so external callers
# (llm_routes uses build_table1_data for the Preview Data path) keep
# working unchanged.
from methods_table1 import build_table1_data

# Abstract → Methods paragraph builder moved to abstract_methods.py.
# Re-imported so external callers (report_pdf assembles the Abstract
# block via this) keep working.
from abstract_methods import build_abstract_methods

# Apical BMD summary narrative + Abstract→Results apical paragraph
# moved to abstract_apical.py.  Re-imported so external callers
# (process_integrated imports build_apical_bmd_summary_narrative
# directly when assembling platform sections) keep working unchanged.
from abstract_apical import (
    _normalize_endpoint_name,
    _format_endpoint_phrase,
    _format_bmd_pair,
    build_apical_bmd_summary_narrative,
    build_abstract_results_apical,
)

# Abstract → Results genomics paragraph + its sentence builders moved
# to abstract_genomics.py.  Re-imported under their original names so
# any existing call site that imports build_abstract_results_genomics
# keeps working.
from abstract_genomics import (
    _build_gene_sets_sentence,
    _build_top_genes_sentence,
    build_abstract_results_genomics,
)


def build_abstract_results_pk(
    chemical_name: str,
    pk_concentrations: dict | None,
    pk_half_lives: dict | None,
    pk_timepoints: list[int],
    dose_unit: str = "mg/kg",
    sexes: list[str] | None = None,
) -> str:
    """
    Build the pharmacokinetic portion of the Abstract → Results paragraph.

    Reference pattern:
      "Average {TA} plasma concentrations at {2 and 24} hours postdose
       were {lower/higher} in {sex_a} rats than in {sex_b} rats. Half-
       lives estimated using the two time points were {longer/shorter}
       in {sex_b} rats ({78.2 and 25.6} hours for the {4 and 37} {unit}
       groups, respectively) than in {sex_a} rats ({40.1 and 15.1}
       hours for the {4 and 37} {unit} groups, respectively)."

    Strategy:
      1. Compute total exposure (sum of mean concentrations across all
         timepoints and biosampling doses) per sex to decide the sentence
         polarity (which sex had lower/higher concentrations).
      2. Format the timepoint list ("at 2 and 24 hours postdose").
      3. Build the half-life comparison sentence with values aligned to
         the same dose order.

    Returns "" when there are insufficient data (no two-timepoint half-
    lives, or only one sex represented).

    Args:
        chemical_name:    The test article name (used in the concentration sentence).
        pk_concentrations: {sex: {dose: {hour: mean_value}}} from MethodsContext.
        pk_half_lives:    {sex: {dose: hours_float}} from MethodsContext.
        pk_timepoints:    Sorted list of timepoint hours seen in the data.
        dose_unit:        Display unit (default "mg/kg").
        sexes:            Sex labels (defaults to ["Male", "Female"]).

    Returns:
        A paragraph string, or empty string if data is insufficient.
    """
    if not pk_concentrations or not pk_half_lives:
        return ""
    if not pk_timepoints:
        return ""

    sexes = sexes or ["Male", "Female"]

    # Need both sexes for a comparison sentence
    sexes_present = [s for s in sexes if s in pk_concentrations and s in pk_half_lives]
    if len(sexes_present) < 2:
        return ""

    sex_a, sex_b = sexes_present[0], sexes_present[1]

    # --- Total mean concentrations per sex (sum across dose × timepoint) ---
    # Used only to decide which sex had "lower" vs "higher" concentrations.
    def _total(sex: str) -> float:
        total = 0.0
        for dose, by_hour in pk_concentrations.get(sex, {}).items():
            for v in by_hour.values():
                total += v
        return total

    total_a = _total(sex_a)
    total_b = _total(sex_b)
    if total_a < total_b:
        conc_lower, conc_higher = sex_a, sex_b
        conc_polarity = "lower"
    else:
        conc_lower, conc_higher = sex_b, sex_a
        conc_polarity = "lower"  # phrasing always uses "lower"

    # --- Timepoints sentence ("at 2 and 24 hours postdose") ---
    tp_phrase = _join_oxford([str(t) for t in pk_timepoints])

    # --- Half-life comparison ---
    # Find the union of doses where both sexes have a half-life
    common_doses = sorted(
        set(pk_half_lives[sex_a].keys()) & set(pk_half_lives[sex_b].keys())
    )
    if not common_doses:
        return ""

    # Decide polarity: which sex has the longer mean half-life?
    def _mean_half_life(sex: str) -> float:
        vals = [pk_half_lives[sex][d] for d in common_doses if d in pk_half_lives[sex]]
        return sum(vals) / len(vals) if vals else 0.0

    if _mean_half_life(sex_a) > _mean_half_life(sex_b):
        hl_longer, hl_shorter = sex_a, sex_b
    else:
        hl_longer, hl_shorter = sex_b, sex_a

    # Format dose group list and the matched half-life lists
    dose_list = _join_oxford([_format_dose_value(d) for d in common_doses])

    def _hl_list(sex: str) -> str:
        # NIEHS reference uses one decimal for half-lives (78.2, 25.6, etc.)
        vals = [pk_half_lives[sex][d] for d in common_doses]
        formatted = [f"{v:.1f}" for v in vals]
        return _join_oxford(formatted)

    hl_longer_str = _hl_list(hl_longer)
    hl_shorter_str = _hl_list(hl_shorter)

    # --- Assemble ---
    # The chemical name appears in the first sentence; subsequent sentences
    # use "rats" alone since the test article is implicit.
    return (
        f"Average {chemical_name} plasma concentrations at "
        f"{tp_phrase} hours postdose were {conc_polarity} in "
        f"{conc_lower.lower()} rats than in {conc_higher.lower()} rats. "
        f"Half-lives estimated using the two time points were longer in "
        f"{hl_longer.lower()} rats ({hl_longer_str} hours for the "
        f"{dose_list} {dose_unit} groups, respectively) than in "
        f"{hl_shorter.lower()} rats ({hl_shorter_str} hours for the "
        f"{dose_list} {dose_unit} groups, respectively)."
    )


# ---------------------------------------------------------------------------
# Body Results: Gene Set BMD Analysis prose
# ---------------------------------------------------------------------------
# The body Results section has two genomics blocks (Gene Set, Gene BMD)
# each preceded by ~2 paragraphs of boilerplate framing followed by
# per-organ paragraphs of findings.  These are deterministic — values
# come from MethodsContext + the genomics cache and the prose follows a
# fixed NIEHS-Report-10 sentence skeleton.




def build_gene_set_body_intro(
    chemical_name: str,
    ge_organs: list[str],
    table_numbers: list[int] | None = None,
) -> list[str]:
    """
    Build the two boilerplate intro paragraphs for the Gene Set BMD
    Analysis section, matching NIEHS Report 10 page 19.

    Paragraph 1 — Methodology framing:
      "Chemical-induced alterations in {organs} gene transcript expression
       were examined to determine those gene sets most sensitive to {TA}
       exposure. To that end, BMD analysis of transcripts and gene sets
       (Gene Ontology [GO] biological process) was conducted to determine
       the potency of the chemical to elicit gene expression changes in
       the {organs}. This analysis used transcript-level BMD data to
       assess an aggregate score of gene set potency (median transcript
       BMD) and enrichment."

    Paragraph 2 — Interpretation caveat:
      "The 'active' gene sets in the {organs} with the lowest BMD median
       values are shown in {Table N} and {Table N+1}, respectively. The
       gene sets in {Tables} should be interpreted with caution from the
       standpoint of the underlying biological mechanism..."

    Args:
        chemical_name:  Test article name, used in paragraph 1.
        ge_organs:      Organ list from MethodsContext.ge_organs.
        table_numbers:  Auto-assigned table numbers for the per-organ
                        gene set tables (e.g., [9, 10] for Tables 9 & 10).
                        When omitted or short, uses generic "the tables".

    Returns:
        Two-paragraph list ready to inject into data.gene_set_narrative.
    """
    organs_phrase = _format_organ_phrase(ge_organs) or "the assayed tissues"

    # Methodology paragraph
    p1 = (
        f"Chemical-induced alterations in {organs_phrase} gene transcript "
        f"expression were examined to determine those gene sets most "
        f"sensitive to {chemical_name} exposure. To that end, BMD analysis "
        f"of transcripts and gene sets (Gene Ontology [GO] biological "
        f"process) was conducted to determine the potency of the chemical "
        f"to elicit gene expression changes in the {organs_phrase}. This "
        f"analysis used transcript-level BMD data to assess an aggregate "
        f"score of gene set potency (median transcript BMD) and enrichment."
    )

    # Interpretation caveat — table refs use the auto-assigned numbers
    # when available, else a generic "the tables below" fallback.
    if table_numbers and len(table_numbers) >= 1:
        table_refs = [f"Table {n}" for n in table_numbers]
        if len(table_refs) == 1:
            tables_str = table_refs[0]
            tables_str_repeat = table_refs[0]
        else:
            tables_str = _join_oxford(table_refs) + ", respectively"
            tables_str_repeat = _join_oxford(table_refs)
    else:
        tables_str = "the tables below"
        tables_str_repeat = "the tables"

    p2 = (
        f"The “active” gene sets in the {organs_phrase} with the "
        f"lowest BMD median values are shown in {tables_str}. The gene "
        f"sets in {tables_str_repeat} should be interpreted with caution "
        f"from the standpoint of the underlying biological mechanism and "
        f"any relationship to toxicity or toxic agents referenced in the "
        f"GO term definitions. The data primarily should be considered a "
        f"metric of potency for chemical-induced transcriptional changes "
        f"(i.e., a concerted biological change) that could serve as a "
        f"surrogate of estimated biological potency and, by extension, "
        f"toxicological potency when more definitive toxicological data "
        f"are unavailable."
    )

    return [p1, p2]


def build_gene_set_body_findings(
    genomics_sections: dict,
    dose_groups: list[float],
    dose_unit: str = "mg/kg",
    bmd_stat: str | None = None,
    n_top: int = 2,
    sexes: list[str] | None = None,
) -> dict[str, str]:
    """
    Build the per-organ "findings" paragraphs for the Gene Set BMD
    Analysis section body.

    Returns a dict keyed by lowercase organ name (e.g., "liver",
    "kidney"), with each value a single paragraph describing that
    organ's findings.  The Typst renderer uses this keyed form to
    place each organ's paragraph immediately above its table, rather
    than lumping all paragraphs at the top of the section.

    Each paragraph is composed of:
      - Lower-limit-of-extrapolation check, scoped to gene sets only:
          "No gene sets in the {organ} of male or female rats had
           estimated BMD median values <{LLE} {unit}."
      - One sub-clause per sex describing the most sensitive gene sets,
        with GO IDs in parens, BMDs and BMDLs paired:
          "In male rats, the most sensitive GO biological processes for
           which a BMD value could be reliably calculated were
           {GO term} ({GO ID}) and {GO term} ({GO ID}) with median BMDs
           (BMDLs) of {bmd1} ({bmdl1}) and {bmd2} ({bmdl2}) {unit},
           respectively."

    Differs from build_abstract_results_genomics in:
      - Single-organ scope per paragraph (vs. abstract's combined per-organ)
      - Includes GO IDs in parens after each gene set name
      - Uses paired "BMDs (BMDLs) of X (Y) and Z (W) mg/kg" format
        instead of separated "BMDs of X and Z and BMDLs of Y and W"
    """
    if not genomics_sections:
        return {}

    sexes = sexes or ["Male", "Female"]

    nonzero = [d for d in (dose_groups or []) if d and d > 0]
    if not nonzero:
        return {}
    lle = min(nonzero) / 3.0
    lle_str = _format_dose_value(lle)

    # Pick the BMD stat — same logic as abstract genomics builder
    chosen_stat = bmd_stat
    if not chosen_stat:
        for sec in genomics_sections.values():
            if sec and sec.get("gene_sets_by_stat"):
                stats = list(sec["gene_sets_by_stat"].keys())
                if stats:
                    chosen_stat = stats[0]
                    break
    if not chosen_stat:
        return {}
    stat_label = _stat_display_name(chosen_stat)

    # Walk organs alphabetically
    organs = sorted({k.split("_", 1)[0] for k in genomics_sections if "_" in k})
    by_organ: dict[str, str] = {}

    for organ in organs:
        sentences: list[str] = []

        # LLE-scoped-to-gene-sets check across both sexes for this organ
        below_lle = 0
        for sex in sexes:
            sec = genomics_sections.get(f"{organ}_{sex.lower()}", {})
            if not sec:
                continue
            sets = sec.get("gene_sets_by_stat", {}).get(chosen_stat, [])
            for s in sets:
                bmd = s.get("bmd")
                try:
                    if bmd is not None and float(bmd) < lle:
                        below_lle += 1
                except (TypeError, ValueError):
                    pass

        sex_phrase = " and ".join(s.lower() for s in sexes) + " rats"
        if below_lle == 0:
            sentences.append(
                f"No gene sets in the {organ} of {sex_phrase} had "
                f"estimated BMD {stat_label} values <{lle_str} {dose_unit}."
            )
        else:
            word = "gene set" if below_lle == 1 else "gene sets"
            sentences.append(
                f"In the {organ} of {sex_phrase}, {below_lle} {word} had "
                f"estimated BMD {stat_label} values <{lle_str} {dose_unit}."
            )

        # Per-sex findings clauses
        for sex in sexes:
            sec = genomics_sections.get(f"{organ}_{sex.lower()}", {})
            if not sec:
                continue
            sets = sec.get("gene_sets_by_stat", {}).get(chosen_stat, [])
            top = _picks_above_lle(sets, lle, n_top)
            if not top:
                sentences.append(
                    f"In {sex.lower()} rats, no GO biological processes "
                    f"had a reliable BMD estimate above the lower limit of "
                    f"extrapolation."
                )
                continue

            # "{name} ({GO ID})" descriptors, joined with Oxford.
            # Omit the parens entirely when the GO ID is missing — never
            # leave a trailing "(" or ")".
            descriptors = []
            for s in top:
                term = s.get("go_term", "(unknown)")
                go_id = (s.get("go_id") or "").strip()
                if go_id:
                    descriptors.append(f"{term} ({go_id})")
                else:
                    descriptors.append(term)
            pairs = _format_paired_bmd_pairs(top)

            plural = len(top) > 1
            sentences.append(
                f"In {sex.lower()} rats, the most sensitive GO biological "
                f"process{'es' if plural else ''} for which a BMD value "
                f"could be reliably calculated "
                f"{'were' if plural else 'was'} {_join_oxford(descriptors)} "
                f"with {stat_label} BMD{'s' if plural else ''} (BMDL"
                f"{'s' if plural else ''}) of {pairs} {dose_unit}"
                f"{', respectively' if plural else ''}."
            )

        by_organ[organ] = " ".join(sentences)

    return by_organ


# ---------------------------------------------------------------------------
# Body Results: Gene BMD Analysis prose
# ---------------------------------------------------------------------------

def build_gene_body_intro(
    ge_organs: list[str],
    table_numbers: list[int] | None = None,
    fold_change_filter: float | None = None,
    bmdu_bmdl_ratio: float | None = 40.0,
    fit_pvalue_threshold: float | None = 0.1,
) -> list[str]:
    """
    Build the two boilerplate intro paragraphs for the Gene BMD Analysis
    section body, matching NIEHS Report 10 page 26.

    Paragraph 1 — Methodology + filter values:
      "The top 10 genes based on BMD potency in the {organs} (fold change
       >|{fc}|, significant Williams trend test, global goodness-of-fit p
       value >{p}, and BMDU/BMDL ≤{ratio}) are shown in {Table N} and
       {Table N+1}."

    Paragraph 2 — Interpretation caveat:
      "As with the GO analysis, the biological or toxicological
       significance of the changes in gene expression shown in {Tables}
       should be interpreted with caution. The data primarily should be
       considered a metric of potency..."

    Filter values default to the NIEHS Report 10 reference settings
    (|2|, p > 0.1, BMDU/BMDL ≤ 40) when not provided by MethodsContext.
    """
    organs_phrase = _format_organ_phrase(ge_organs) or "the assayed tissues"

    fc = fold_change_filter if fold_change_filter is not None else 2
    p = fit_pvalue_threshold if fit_pvalue_threshold is not None else 0.1
    ratio = bmdu_bmdl_ratio if bmdu_bmdl_ratio is not None else 40

    # Format filter values: drop unnecessary decimals
    def _fmt(v: float) -> str:
        if v == int(v):
            return str(int(v))
        return f"{v:g}"

    if table_numbers and len(table_numbers) >= 1:
        table_refs = [f"Table {n}" for n in table_numbers]
        tables_str = _join_oxford(table_refs)
    else:
        tables_str = "the tables below"

    p1 = (
        f"The top 10 genes based on BMD potency in the {organs_phrase} "
        f"(fold change >|{_fmt(fc)}|, significant Williams trend test, "
        f"global goodness-of-fit p value >{_fmt(p)}, and BMDU/BMDL "
        f"≤{_fmt(ratio)}) are shown in {tables_str}."
    )

    p2 = (
        f"As with the GO analysis, the biological or toxicological "
        f"significance of the changes in gene expression shown in "
        f"{tables_str} should be interpreted with caution. The data "
        f"primarily should be considered a metric of potency for "
        f"chemical-induced transcriptional changes that could serve as a "
        f"conservative surrogate of estimated biological potency, and by "
        f"extension toxicological potency, when more definitive "
        f"toxicological data are unavailable."
    )

    return [p1, p2]


def build_gene_body_findings(
    genomics_sections: dict,
    dose_groups: list[float],
    dose_unit: str = "mg/kg",
    n_top: int = 8,
    sexes: list[str] | None = None,
) -> dict[str, str]:
    """
    Build the per-organ × per-sex "findings" paragraphs for the Gene BMD
    Analysis section body.

    Returns a dict keyed by lowercase organ name (e.g., "liver",
    "kidney"), with each value a single paragraph describing that
    organ's findings.  The Typst renderer uses this keyed form to
    place each organ's paragraph immediately above its table.

    Each paragraph is composed of:
      - Lower-limit-of-extrapolation check, scoped to genes only.
      - For each sex, separate clauses for upregulated and downregulated
        most-sensitive genes:
          "In male rats, the most sensitive upregulated genes with a
           calculated BMD were {Gsta2}, {Gsta5}, ... with BMDs (BMDLs) of
           {x} ({y}), {x} ({y}), ... {unit}, respectively."
          "The most sensitive genes exhibiting a decrease in expression
           were {Egr1}, ... with BMDs (BMDLs) of {x} ({y}), ..."

    Gene name expansions ("Gsta2 (glutathione S-transferase alpha 2)")
    require an external annotation source not present in the genomics
    cache, so this function emits bare gene symbols.  Future enhancement:
    look up gene names from integrated.json's referenceGeneAnnotations
    or from bmdx.duckdb.
    """
    if not genomics_sections:
        return {}

    sexes = sexes or ["Male", "Female"]

    nonzero = [d for d in (dose_groups or []) if d and d > 0]
    if not nonzero:
        return {}
    lle = min(nonzero) / 3.0
    lle_str = _format_dose_value(lle)

    organs = sorted({k.split("_", 1)[0] for k in genomics_sections if "_" in k})
    by_organ: dict[str, str] = {}

    for organ in organs:
        sentences: list[str] = []

        # LLE-scoped-to-genes check across both sexes
        below_lle = 0
        for sex in sexes:
            sec = genomics_sections.get(f"{organ}_{sex.lower()}", {})
            if not sec:
                continue
            for g in sec.get("top_genes", []):
                bmd = g.get("bmd")
                try:
                    if bmd is not None and float(bmd) < lle:
                        below_lle += 1
                except (TypeError, ValueError):
                    pass

        sex_phrase = " and ".join(s.lower() for s in sexes) + " rats"
        if below_lle == 0:
            sentences.append(
                f"No {organ} genes in {sex_phrase} had estimated BMD "
                f"median values <{lle_str} {dose_unit}."
            )
        else:
            word = "gene" if below_lle == 1 else "genes"
            sentences.append(
                f"In the {organ} of {sex_phrase}, {below_lle} {word} had "
                f"estimated BMD median values <{lle_str} {dose_unit}."
            )

        # Per-sex up/down clauses
        for sex in sexes:
            sec = genomics_sections.get(f"{organ}_{sex.lower()}", {})
            if not sec:
                continue
            top_all = sec.get("top_genes", [])
            up = [g for g in top_all if str(g.get("direction", "")).lower() == "up"]
            down = [g for g in top_all if str(g.get("direction", "")).lower() == "down"]
            up_top = _picks_above_lle(up, lle, n_top)
            down_top = _picks_above_lle(down, lle, n_top)

            for direction_kind, items in (("upregulated", up_top), ("decrease in expression", down_top)):
                if not items:
                    continue
                symbols = [_format_rat_gene_symbol(g.get("gene_symbol", "")) for g in items]
                pairs = _format_paired_bmd_pairs(items)
                plural = len(items) > 1

                if direction_kind == "upregulated":
                    sentences.append(
                        f"In {sex.lower()} rats, the most sensitive "
                        f"upregulated gene{'s' if plural else ''} with a "
                        f"calculated BMD "
                        f"{'were' if plural else 'was'} "
                        f"{_join_oxford(symbols)} with BMD"
                        f"{'s' if plural else ''} (BMDL"
                        f"{'s' if plural else ''}) of {pairs} {dose_unit}"
                        f"{', respectively' if plural else ''}."
                    )
                else:
                    sentences.append(
                        f"The most sensitive gene{'s' if plural else ''} "
                        f"exhibiting a decrease in expression in "
                        f"{sex.lower()} rats "
                        f"{'were' if plural else 'was'} "
                        f"{_join_oxford(symbols)} with BMD"
                        f"{'s' if plural else ''} (BMDL"
                        f"{'s' if plural else ''}) of {pairs} {dose_unit}"
                        f"{', respectively' if plural else ''}."
                    )

        by_organ[organ] = " ".join(sentences)

    return by_organ


def build_abstract_summary(
    apical_bmd_summary: list[dict] | None = None,
    genomics_sections: dict | None = None,
    dose_groups: list[float] | None = None,
    dose_unit: str = "mg/kg",
    bmd_stat: str | None = None,
    sexes: list[str] | None = None,
) -> str:
    """
    Build the Abstract → Summary paragraph.

    Reference pattern (NIEHS Report 10):
      "Taken together, in male rats, the most sensitive gene set BMD
       (BMDL) median, individual gene BMD (BMDL), and apical endpoint
       BMD (BMDL) values that could be reliably determined occurred at
       0.520 (0.160), 0.510 (0.212), and 7.264 (5.024) mg/kg,
       respectively. In female rats, the most sensitive gene set BMD
       (BMDL) median and individual gene BMD (BMDL) values that could
       be reliably determined occurred at 10.324 (7.461) and 1.163
       (0.179) mg/kg, respectively. There were no apical endpoints in
       female rats for which a BMD value could be reliably estimated."

    Strategy: for each sex, find the lowest reliable BMD across all
    organs in three categories — gene sets, individual genes, apical
    endpoints — and assemble a sentence whose category list is gated
    on availability.  When apical fails entirely for a sex, we add the
    "no apical endpoints" fallback sentence.

    Args:
        apical_bmd_summary: list of BMD summary entry dicts.
        genomics_sections:  dict keyed by "{organ}_{sex}" with gene_sets and top_genes.
        dose_groups:        Full study dose list (for lower-limit-of-extrapolation).
        dose_unit:          Display unit (default "mg/kg").
        bmd_stat:           Which stat to use for gene sets ("median", "fifth_pct").
        sexes:              Optional sex order (defaults to ["Male", "Female"]).

    Returns:
        Paragraph string, or empty string if no reliable BMDs exist anywhere.
    """
    sexes = sexes or ["Male", "Female"]

    # Lower limit of extrapolation (LLE) — reuse same convention as Results
    nonzero_doses = [d for d in (dose_groups or []) if d and d > 0]
    lle = (min(nonzero_doses) / 3.0) if nonzero_doses else 0.0

    # Determine which BMD stat to read from gene_sets_by_stat.  Default
    # to whatever the data carries (matches the Results paragraph logic).
    chosen_stat = bmd_stat
    if not chosen_stat and genomics_sections:
        for sec in genomics_sections.values():
            if sec and sec.get("gene_sets_by_stat"):
                stats = list(sec["gene_sets_by_stat"].keys())
                if stats:
                    chosen_stat = stats[0]
                    break
    stat_label = _stat_display_name(chosen_stat) if chosen_stat else ""

    # --- Per-sex lowest-BMD lookups ---
    # Each helper returns {bmd_str, bmdl_str} or None if no reliable
    # value exists for the sex × category combination.
    def _lowest_geneset(sex: str) -> dict | None:
        if not genomics_sections or not chosen_stat:
            return None
        candidates: list[dict] = []
        for key, sec in genomics_sections.items():
            if not key.endswith(f"_{sex.lower()}"):
                continue
            sets = sec.get("gene_sets_by_stat", {}).get(chosen_stat, [])
            candidates.extend(_picks_above_lle(sets, lle, n=1))
        if not candidates:
            return None
        # Among per-organ winners, pick the one with the lowest BMD overall
        candidates.sort(key=lambda x: x["_bmd_float"])
        winner = candidates[0]
        return {
            "bmd": _format_dose_value(winner.get("bmd")),
            "bmdl": _format_dose_value(winner.get("bmdl")),
        }

    def _lowest_gene(sex: str) -> dict | None:
        if not genomics_sections:
            return None
        candidates: list[dict] = []
        for key, sec in genomics_sections.items():
            if not key.endswith(f"_{sex.lower()}"):
                continue
            genes = sec.get("top_genes", [])
            candidates.extend(_picks_above_lle(genes, lle, n=1))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x["_bmd_float"])
        winner = candidates[0]
        return {
            "bmd": _format_dose_value(winner.get("bmd")),
            "bmdl": _format_dose_value(winner.get("bmdl")),
        }

    def _lowest_apical(sex: str) -> dict | None:
        if not apical_bmd_summary:
            return None
        # Apply same reliability + anomaly filters as the Results paragraph
        reliable = [
            e for e in apical_bmd_summary
            if e.get("sex") == sex
            and _is_reliable_bmd(e)
            and not _is_anomalous_bmd(e)
            and e.get("direction")
        ]
        if not reliable:
            return None
        reliable.sort(key=lambda e: float(e["bmd"]))
        winner = reliable[0]
        return {
            "bmd": _format_dose_value(winner.get("bmd")),
            "bmdl": _format_dose_value(winner.get("bmdl")),
        }

    # --- Build per-sex sentences ---
    # Each sex gets one main sentence listing all available categories,
    # plus an optional fallback sentence when apical is missing.
    sentences: list[str] = []
    has_any_content = False

    for sex in sexes:
        gs = _lowest_geneset(sex)
        gene = _lowest_gene(sex)
        apical = _lowest_apical(sex)

        # Build the (label, value_string) pairs in NIEHS reference order:
        # gene set → individual gene → apical endpoint.
        category_phrases: list[tuple[str, str]] = []
        if gs:
            label = (
                f"the most sensitive gene set BMD (BMDL) {stat_label}"
                if stat_label else
                "the most sensitive gene set BMD (BMDL)"
            )
            category_phrases.append((label, f"{gs['bmd']} ({gs['bmdl']})"))
        if gene:
            category_phrases.append((
                "individual gene BMD (BMDL)",
                f"{gene['bmd']} ({gene['bmdl']})",
            ))
        if apical:
            category_phrases.append((
                "apical endpoint BMD (BMDL)",
                f"{apical['bmd']} ({apical['bmdl']})",
            ))

        if not category_phrases:
            # Nothing reliable for this sex at all — skip the sentence,
            # but still emit the apical-missing fallback if relevant.
            if apical_bmd_summary:
                sentences.append(
                    f"There were no apical endpoints in {sex.lower()} rats "
                    f"for which a BMD value could be reliably estimated."
                )
            continue

        has_any_content = True
        labels = [p[0] for p in category_phrases]
        values = [p[1] for p in category_phrases]
        plural = len(category_phrases) > 1

        # Sentence start: the very first sex sentence is preceded by
        # the "Taken together, " connective (which uses lowercase "in"
        # because it comes after a comma); subsequent sex sentences are
        # standalone and start with capital "In".
        if not sentences:
            opener = f"Taken together, in {sex.lower()} rats,"
        else:
            opener = f"In {sex.lower()} rats,"

        sentences.append(
            f"{opener} "
            f"{_join_oxford(labels)} value{'s' if plural else ''} that could "
            f"be reliably determined occurred at {_join_oxford(values)} "
            f"{dose_unit}{', respectively' if plural else ''}."
        )

        # If apical was missing for this sex but genomics existed, add
        # the standard fallback sentence about apical specifically.
        if apical_bmd_summary and not apical:
            sentences.append(
                f"There were no apical endpoints in {sex.lower()} rats "
                f"for which a BMD value could be reliably estimated."
            )

    if not has_any_content:
        return ""

    return " ".join(sentences)


def build_abstract_results(
    apical_bmd_summary: list[dict] | None = None,
    genomics_sections: dict | None = None,
    dose_groups: list[float] | None = None,
    dose_unit: str = "mg/kg",
    bmd_stat: str | None = None,
    sexes: list[str] | None = None,
    methods_ctx: dict | None = None,
) -> str:
    """
    Build the full Abstract → Results paragraph.

    Combines, in NIEHS Report 10 order:
      1. Apical findings per sex (build_abstract_results_apical)
      2. Pharmacokinetic findings — plasma concentrations + half-lives
         (build_abstract_results_pk), driven by methods_ctx.pk_*
      3. Genomics findings per organ × sex (build_abstract_results_genomics)

    Args:
        apical_bmd_summary: list of BMD summary entry dicts.
        genomics_sections:  dict keyed by "{organ}_{sex}" with gene_sets and top_genes.
        dose_groups:        Full study dose list (for lower-limit-of-extrapolation).
        dose_unit:          Display unit (default "mg/kg").
        bmd_stat:           Which stat to use for gene sets ("median", "fifth_pct", ...).
        sexes:              Optional sex order (defaults to ["Male", "Female"]).
        methods_ctx:        Optional MethodsContext-as-dict.  When present, its
                            pk_concentrations / pk_half_lives / pk_timepoints fields
                            drive the pharmacokinetics sentence.

    Returns:
        A single paragraph string for the Abstract Results section.
    """
    parts: list[str] = []

    if apical_bmd_summary:
        ap = build_abstract_results_apical(apical_bmd_summary, sexes=sexes)
        if ap:
            parts.append(ap)

    # PK paragraph: only when MethodsContext carries pk_* aggregates
    if methods_ctx:
        pk = build_abstract_results_pk(
            chemical_name=methods_ctx.get("chemical_name", "the test article"),
            pk_concentrations=methods_ctx.get("pk_concentrations"),
            pk_half_lives=methods_ctx.get("pk_half_lives"),
            pk_timepoints=methods_ctx.get("pk_timepoints", []),
            dose_unit=methods_ctx.get("dose_unit", dose_unit),
            sexes=sexes,
        )
        if pk:
            parts.append(pk)

    if genomics_sections and dose_groups:
        gn = build_abstract_results_genomics(
            genomics_sections=genomics_sections,
            dose_groups=dose_groups,
            dose_unit=dose_unit,
            bmd_stat=bmd_stat,
            sexes=sexes,
        )
        if gn:
            parts.append(gn)

    return " ".join(parts)


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
