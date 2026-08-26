"""
Abstract → Results genomics paragraph and its sentence builders.

The Abstract's Results paragraph has a genomics section that describes
the most sensitive gene sets (GO BP categories) and the most sensitive
individual genes for each (organ × sex) combination, ordered by BMD.
This module assembles that prose from the genomics extract result and
the MethodsContext, deterministically — no LLM call.

Public:

  build_abstract_results_genomics(chemical_name, dose_unit,
                                  genomics_results, ge_organs,
                                  bmd_stats, lle)
      Top-level builder.  Walks (organ × sex) combinations, picks the
      top gene sets / genes via _picks_above_lle, and threads them
      through the two sentence builders below.

Private sentence builders (this module only):

  _build_gene_sets_sentence(sets, sex, stat_label, dose_unit)
      "X gene sets in male rats had BMDs of..." prose
  _build_top_genes_sentence(genes, sex, stat_label, dose_unit)
      "The most sensitive genes in male rats were..." prose

Cross-cutting helpers (_format_dose_value, _format_rat_gene_symbol,
_stat_display_name, _picks_above_lle, _join_oxford) come from
narrative_helpers — single source of truth for those.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

from narrative.narrative_helpers import (
    _format_dose_value,
    _format_rat_gene_symbol,
    _stat_display_name,
    _picks_above_lle,
    _join_oxford,
)


# ---------------------------------------------------------------------------
# Genomics: most sensitive gene sets and genes per organ × sex
# ---------------------------------------------------------------------------





def _build_gene_sets_sentence(
    sets: list[dict], sex: str, stat_label: str, dose_unit: str,
) -> str:
    """
    Build one "most sensitive gene sets" sentence for a given sex.

    Reference pattern:
      "The most sensitive gene sets in {sex} rats for which a reliable
       estimate of the BMD could be made were {GO terms with Oxford
       comma} with {stat} BMDs of {values} {unit} and {stat} BMDLs of
       {values} {unit}, respectively."

    Returns "" when the input list is empty (caller decides whether to
    emit a "no reliable BMD" fallback).
    """
    if not sets:
        return ""

    terms = [s.get("go_term", s.get("go_id", "(unknown)")) for s in sets]
    bmds = [_format_dose_value(s.get("bmd")) for s in sets]
    bmdls = [_format_dose_value(s.get("bmdl")) for s in sets]

    plural = len(sets) > 1
    return (
        f"The most sensitive gene set{'s' if plural else ''} in "
        f"{sex.lower()} rats for which a reliable estimate of the "
        f"BMD could be made {'were' if plural else 'was'} "
        f"{_join_oxford(terms)} with {stat_label} BMD"
        f"{'s' if plural else ''} of {_join_oxford(bmds)} {dose_unit} "
        f"and {stat_label} BMDL{'s' if plural else ''} of "
        f"{_join_oxford(bmdls)} {dose_unit}, respectively."
    )


def _build_top_genes_sentence(
    genes: list[dict], sex: str, direction: str, dose_unit: str,
) -> str:
    """
    Build one "most sensitive up/down-regulated genes" sentence.

    Reference pattern:
      "The most sensitive {up/down}regulated genes in {sex} rats with
       reliable BMD estimates included {gene symbols} with BMDs (BMDLs)
       of {pairs}, respectively."

    Returns "" when no genes match the direction filter.
    """
    if not genes:
        return ""

    symbols = [_format_rat_gene_symbol(g.get("gene_symbol", "")) for g in genes]
    pairs = [
        f"{_format_dose_value(g.get('bmd'))} ({_format_dose_value(g.get('bmdl'))})"
        for g in genes
    ]

    plural = len(genes) > 1
    return (
        f"The most sensitive {direction}regulated gene"
        f"{'s' if plural else ''} in {sex.lower()} rats with reliable "
        f"BMD estimate{'s' if plural else ''} "
        f"{'included' if plural else 'was'} {_join_oxford(symbols)} "
        f"with BMD{'s' if plural else ''} (BMDL{'s' if plural else ''}) "
        f"of {_join_oxford(pairs)} {dose_unit}, respectively."
    )


def build_abstract_results_genomics(
    genomics_sections: dict,
    dose_groups: list[float],
    dose_unit: str = "mg/kg",
    bmd_stat: str | None = None,
    n_top_sets: int = 3,
    n_top_genes: int = 8,
    sexes: list[str] | None = None,
) -> str:
    """
    Build the genomics portion of the Abstract → Results paragraph.

    For each organ (alphabetical order, matching reference convention),
    emits:
      1. A lower-limit-of-extrapolation summary sentence: either "no GO
         process or individual genes had BMD median values below
         <{LLE} {unit}>" or a count of items below.
      2. Per sex: the most sensitive gene sets sentence (up to n_top_sets).
      3. Per sex: the most sensitive up-regulated genes sentence
         (up to n_top_genes).
      4. Per sex: the most sensitive down-regulated genes sentence
         (up to n_top_genes).

    Empty sentences are omitted (e.g., a sex with no reliable gene sets
    silently drops that sentence).

    Args:
        genomics_sections: dict keyed by "{organ}_{sex}" (e.g., "liver_male"),
                           each value with gene_sets_by_stat and top_genes.
        dose_groups:       The full study dose list — used to compute the
                           lower limit of extrapolation (lowest non-zero / 3).
        dose_unit:         Display unit (default "mg/kg").
        bmd_stat:          Which stat to use ("median", "fifth_pct", etc.).
                           Defaults to whichever stat is present in the data.
        n_top_sets:        How many top gene sets to list per sex.
        n_top_genes:       How many top up/down-regulated genes per sex.
        sexes:             Sex order (defaults to ["Male", "Female"]).

    Returns:
        Paragraph string, or empty string if no genomics data is present.
    """
    if not genomics_sections:
        return ""

    sexes = sexes or ["Male", "Female"]

    # Lower limit of extrapolation = lowest non-zero dose / 3 (BMDExpress convention)
    nonzero_doses = [d for d in dose_groups if d and d > 0]
    if not nonzero_doses:
        return ""
    lle = min(nonzero_doses) / 3.0
    lle_str = _format_dose_value(lle)

    # Identify all organs from the section keys (e.g. "liver_male" → "liver")
    organs: set[str] = set()
    for key in genomics_sections:
        if "_" in key:
            organs.add(key.split("_", 1)[0])
    organs_sorted = sorted(organs)

    sentences: list[str] = []

    for organ in organs_sorted:
        # --- Pick which BMD stat to read (default to whatever exists) ---
        sample_section = None
        for sex in sexes:
            sec = genomics_sections.get(f"{organ}_{sex.lower()}")
            if sec and sec.get("gene_sets_by_stat"):
                sample_section = sec
                break
        if not sample_section:
            continue

        available_stats = list(sample_section["gene_sets_by_stat"].keys())
        chosen_stat = bmd_stat if bmd_stat in available_stats else (available_stats[0] if available_stats else None)
        if not chosen_stat:
            continue
        stat_label = _stat_display_name(chosen_stat)

        # --- Lower-limit-of-extrapolation summary across both sexes ---
        # Count how many gene sets and individual genes have BMD < LLE
        # across all sexes for this organ.
        below_lle_sets = 0
        below_lle_genes = 0
        for sex in sexes:
            sec = genomics_sections.get(f"{organ}_{sex.lower()}", {})
            if not sec:
                continue
            sets = sec.get("gene_sets_by_stat", {}).get(chosen_stat, [])
            for s in sets:
                bmd = s.get("bmd")
                try:
                    if bmd is not None and float(bmd) < lle:
                        below_lle_sets += 1
                except (TypeError, ValueError):
                    pass
            for g in sec.get("top_genes", []):
                bmd = g.get("bmd")
                try:
                    if bmd is not None and float(bmd) < lle:
                        below_lle_genes += 1
                except (TypeError, ValueError):
                    pass

        sex_phrase = " and ".join(s.lower() for s in sexes) + " rats"
        if below_lle_sets == 0 and below_lle_genes == 0:
            sentences.append(
                f"In the {organ} of {sex_phrase}, no Gene Ontology "
                f"biological process or individual genes had BMD "
                f"{stat_label} values below the lower limit of "
                f"extrapolation (<{lle_str} {dose_unit})."
            )
        else:
            # Plural-aware count phrase
            sets_word = "gene set" if below_lle_sets == 1 else "gene sets"
            genes_word = "gene" if below_lle_genes == 1 else "genes"
            sentences.append(
                f"In the {organ} of {sex_phrase}, "
                f"{below_lle_sets} Gene Ontology biological process "
                f"{sets_word} and {below_lle_genes} individual "
                f"{genes_word} had BMD {stat_label} values below the "
                f"lower limit of extrapolation (<{lle_str} {dose_unit})."
            )

        # --- Per-sex gene sets and top genes ---
        for sex in sexes:
            sec = genomics_sections.get(f"{organ}_{sex.lower()}", {})
            if not sec:
                continue

            # Top gene sets (above LLE, sorted by BMD ascending)
            sets = sec.get("gene_sets_by_stat", {}).get(chosen_stat, [])
            top_sets = _picks_above_lle(sets, lle, n_top_sets)
            sets_sentence = _build_gene_sets_sentence(top_sets, sex, stat_label, dose_unit)
            if sets_sentence:
                sentences.append(sets_sentence)

            # Top up-regulated and down-regulated genes
            top_genes = sec.get("top_genes", [])
            up_genes = [g for g in top_genes if str(g.get("direction", "")).lower() == "up"]
            down_genes = [g for g in top_genes if str(g.get("direction", "")).lower() == "down"]
            up_top = _picks_above_lle(up_genes, lle, n_top_genes)
            down_top = _picks_above_lle(down_genes, lle, n_top_genes)

            up_sentence = _build_top_genes_sentence(up_top, sex, "up", dose_unit)
            if up_sentence:
                sentences.append(up_sentence)
            down_sentence = _build_top_genes_sentence(down_top, sex, "down", dose_unit)
            if down_sentence:
                sentences.append(down_sentence)

    return " ".join(sentences)


