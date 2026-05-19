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

# Abstract → Results pharmacokinetics paragraph moved to abstract_pk.py.
# Re-imported so external assemblers (report_pdf when biosampling data
# is present) keep working.
from abstract_pk import build_abstract_results_pk

# Body Results: Gene Set BMD Analysis + Gene BMD Analysis prose moved
# to gene_bodies.py.  Re-imported under their original names so
# genomics_narratives.py (which imports all four directly) keeps working.
from gene_bodies import (
    build_gene_set_body_intro,
    build_gene_set_body_findings,
    build_gene_body_intro,
    build_gene_body_findings,
)


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
