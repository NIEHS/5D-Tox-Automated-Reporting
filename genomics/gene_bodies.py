"""
Body Results: Gene Set BMD Analysis + Gene BMD Analysis prose.

The body Results section has two genomics blocks — Gene Set BMD
Analysis and Gene BMD Analysis — each preceded by ~2 paragraphs of
boilerplate framing followed by per-organ paragraphs of findings.
This module builds both.

Public functions, per analysis type:

  Gene Set BMD:
    build_gene_set_body_intro(chemical_name, genomics_results,
                              ge_organs, dose_unit, bmd_stats)
    build_gene_set_body_findings(chemical_name, genomics_results,
                                 ge_organs, dose_unit, bmd_stats, lle)

  Gene BMD:
    build_gene_body_intro(chemical_name, genomics_results, ge_organs,
                          dose_unit, bmd_stats)
    build_gene_body_findings(chemical_name, genomics_results, ge_organs,
                             dose_unit, bmd_stats, lle)

Each is a deterministic builder — values come from MethodsContext and
the genomics cache; prose follows the fixed NIEHS-Report-10 sentence
skeleton.  genomics_narratives.py (the body Results section assembler)
imports all four directly.

Cross-cutting helpers (_format_dose_value, _format_rat_gene_symbol,
_stat_display_name, _picks_above_lle, _join_oxford,
_format_organ_phrase, _format_paired_bmd_pairs) come from
narrative_helpers.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

import json

from narrative.methods_models import MethodsContext
from narrative.narrative_helpers import (
    _format_dose_value,
    _format_rat_gene_symbol,
    _stat_display_name,
    _picks_above_lle,
    _join_oxford,
    _format_organ_phrase,
    _format_paired_bmd_pairs,
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

