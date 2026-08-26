"""
Abstract → Summary + Abstract → Results aggregator.

The report's Abstract section closes with two top-level builders that
pull together everything the upstream paragraphs produced:

  build_abstract_summary(apical_bmd_summary, genomics_sections,
                         dose_groups, dose_unit, bmd_stat)
      The "Summary" paragraph — distills the lowest reliable BMDs
      across apical platforms + gene sets + individual genes into a
      few sentences that read as the report's TL;DR.  Three private
      helpers (_lowest_apical, _lowest_geneset, _lowest_gene) pick the
      single lowest reliable BMD for each category.

  build_abstract_results(apical_bmd_summary, ctx, genomics_sections,
                         dose_unit, bmd_stat, ge_organs)
      The "Results" paragraph aggregator — concatenates the apical /
      PK / genomics Results sub-paragraphs (which the other
      abstract_X.py modules build) into a single block.  Existence
      of each sub-paragraph is conditional on having relevant data.

Imports from sibling abstract_X modules:
  - abstract_apical.build_abstract_results_apical
  - abstract_pk.build_abstract_results_pk
  - abstract_genomics.build_abstract_results_genomics

The aggregator is the only abstract_* module that imports from the
other abstract_* modules.  All other "abstract_X.py" files only depend
on narrative_helpers + methods_models.

report_data.py imports both names via the methods_report.py re-export
shim when assembling the Abstract block.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

from narrative.methods_models import MethodsContext
from narrative.narrative_helpers import (
    _format_dose_value,
    _stat_display_name,
    _picks_above_lle,
    _join_oxford,
    _is_reliable_bmd,
    _is_anomalous_bmd,
)
from narrative.abstract_apical import build_abstract_results_apical
from narrative.abstract_pk import build_abstract_results_pk
from narrative.abstract_genomics import build_abstract_results_genomics


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


