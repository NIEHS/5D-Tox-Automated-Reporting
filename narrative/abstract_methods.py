"""
Abstract → Methods paragraph builder.

The report's Abstract section has four labelled paragraphs:
Background, Methods, Results, and Summary.  This module owns the
**Methods** paragraph.

Unlike the body Materials & Methods (which is LLM-written from a
prompt), the Abstract → Methods paragraph is deterministic: every
fact it reports (compound name, dose groups, vehicle, route, duration,
species, sex, organ list, BMR) is already present in the
MethodsContext, so we generate it template-style.  This keeps the
Abstract faithful to the actual data and avoids paying for an LLM call
on a paragraph that has no creative latitude.

Single public function:

  build_abstract_methods(ctx) -> str

methods_report.py re-exports the name; report_data.py imports it via
the shim to assemble the Abstract block.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

from narrative.methods_models import MethodsContext
from narrative.narrative_helpers import _format_dose_list, _format_organ_list, _join_oxford


# ---------------------------------------------------------------------------
# Abstract → Methods paragraph builder
# ---------------------------------------------------------------------------
# The Abstract section has 4 labeled paragraphs (Background, Methods, Results,
# Summary).  The Methods paragraph is deterministic — every fact it reports is
# already in MethodsContext, so we can generate it from a template without an
# LLM call.  This keeps the abstract methods faithful to the data and fast.



_FACTOR_WORDS = {1.0: "one", 2.0: "two", 0.5: "one half of"}
# An apical domain as the BMR sentence names its endpoints.
_DOMAIN_WORDS = {"Body Weight": "body weight", "Organ Weight": "organ weight",
                 "Clinical Chemistry": "clinical chemistry", "Hematology": "hematology",
                 "Hormones": "hormone", "Tissue Concentration": "tissue concentration"}


def _bmr_words(bmr_type, factor) -> str | None:
    """A BMR as the books word it: ("Standard Deviation", 1.0) → "one standard
    deviation"; a relative deviation as a percentage change, ("Relative
    Deviation", 0.25) → "a 25% relative deviation".  None when unknown."""
    if not bmr_type or factor is None:
        return None
    kind = str(bmr_type).strip().lower().replace("std. dev.", "standard deviation")
    if kind in ("sd", "standard deviation", "std"):
        word = _FACTOR_WORDS.get(float(factor), f"{float(factor):g}")
        return f"{word} standard deviation"
    if kind in ("rel_dev", "relative deviation"):
        return f"a {float(factor) * 100:g}% relative deviation"
    return f"{float(factor):g} {kind}"


def build_abstract_methods(ctx: MethodsContext) -> str:
    """
    Build the Abstract → Methods paragraph from a MethodsContext.

    Mirrors the structure of NIEHS Report 10's Abstract-Methods paragraph:

      A short-term in vivo biological potency study on {TA} in adult {sexes}
      {Species} (Strain) rats was conducted.  {TA} was formulated in
      {vehicle} and administered once daily for {duration} consecutive days
      by {route} (study days 0–{duration-1}).  {TA} was administered at
      {N_doses} doses ({dose_list} {dose_unit}).  Blood was collected from
      animals dedicated for internal dose assessment in the
      {biosampling_doses} {dose_unit} groups.  On study day {duration}, the
      day after the final dose was administered, animals were euthanized,
      standard toxicological measures were assessed, and the {ge_organs}
      were assayed in gene expression studies using the {assay} assay.
      Modeling was conducted to identify the benchmark doses (BMDs)
      associated with apical toxicological endpoints and transcriptional
      changes in the {ge_organs}.  A benchmark response of {bmr} was used
      to model all endpoints.

    All data comes from MethodsContext — no LLM call.  Conditional clauses
    are omitted when the corresponding data isn't present (e.g., no
    biosampling animals → skip the blood collection sentence; no gene
    expression → skip the transcriptomics clauses).
    """
    # --- Test article display name ---
    # The abbreviation when the study records one (the abstract's Background
    # introduced it), else the full name.
    ta_name = ctx.abbreviation or ctx.chemical_name or "the test article"

    # --- Sexes ("adult male and female") ---
    sexes = [s.lower() for s in ctx.sexes] if ctx.sexes else ["male", "female"]
    sexes_str = " and ".join(sexes)

    # --- Animals, route and vehicle: as the study records them ---
    # (pipeline.study_design via MethodsContext).  An unrecorded fact drops
    # its clause rather than defaulting to the gavage/corn oil protocol;
    # Materials and Methods flags it.
    from pipeline.study_design import administration_phrase, subject_phrase, vehicle_phrase
    facts = {"species": ctx.species, "strain": ctx.strain,
             "route": ctx.route, "vehicle": ctx.vehicle}
    subject = subject_phrase(facts)
    vehicle = vehicle_phrase(facts)
    given = f"formulated {vehicle} and" if vehicle else ""
    route_clause = administration_phrase(facts)

    # --- Duration + study days range ---
    duration = ctx.duration_days or 5
    last_day = duration - 1
    sacrifice_day = duration

    # --- Dose list ---
    n_doses = len(ctx.dose_groups)
    dose_list = _format_dose_list(ctx.dose_groups, ctx.dose_unit)
    # NIEHS convention: "mg/kg body weight [mg/kg]" on first mention of a dose
    # per body weight; an exposure concentration (ppm) is written as is.
    from pipeline.study_design import dose_noun, is_air_concentration
    inhaled = is_air_concentration(ctx.dose_unit)
    dose_unit_full = (ctx.dose_unit if inhaled
                      else f"{ctx.dose_unit} body weight [{ctx.dose_unit}]")
    noun = dose_noun(ctx.dose_unit)

    # --- Biosampling sentence (conditional) ---
    biosampling_sentence = ""
    if ctx.biosampling_doses:
        bio_list = _format_dose_list(ctx.biosampling_doses, ctx.dose_unit)
        biosampling_sentence = (
            f" Blood was collected from animals dedicated for internal "
            f"dose assessment in the {bio_list} {ctx.dose_unit} groups."
        )

    # --- Transcriptomics clauses (conditional) ---
    assay_clause = ""
    bmd_clause = (
        " Modeling was conducted to identify the benchmark doses (BMDs) "
        "associated with apical toxicological endpoints"
    )
    if ctx.has_gene_expression and ctx.ge_organs:
        organs_str = _format_organ_list(ctx.ge_organs)
        assay_name = ctx.genomics_assay or "gene expression"
        assay_clause = (
            f", and the {organs_str} were assayed in gene expression "
            f"studies using the {assay_name} assay"
        )
        bmd_clause += f" and transcriptional changes in the {organs_str}"
    bmd_clause += "."

    # --- BMR sentence ---
    # Each BMR as it was used: the apical BMDs' (``ctx.apical_bmr``, from the
    # BMD summary) and the transcriptomic analyses' (the .bm2's, bmr_type /
    # bmr_factor).  One sentence for all endpoints when they agree (NIEHS-02 …
    # 10: "A benchmark response of one standard deviation was used to model
    # all endpoints."); else each named (NIEHS-12, 13: "… 1 standard deviation
    # from the mean was used to model all apical endpoints, whereas a benchmark
    # response set to a 25% change in the median response was used to model
    # the gene expression data.").
    genomic = (_bmr_words(ctx.bmr_type, ctx.bmr_factor)
               if ctx.has_gene_expression and ctx.ge_organs else None)
    # The apical projects' own BMRs, by domain (ctx.apical_bmrs): when they
    # differ, each BMR names what it modeled ("A benchmark response of one
    # standard deviation was used to model the body weight, … endpoints, and a
    # benchmark response of a 25% relative deviation was used to model the
    # clinical chemistry endpoints and the gene expression data.").
    by_domain: dict[str, list[str]] = {}
    for platform, bmr in (ctx.apical_bmrs or {}).items():
        words = _bmr_words(*bmr) if isinstance(bmr, (list, tuple)) and len(bmr) == 2 else None
        if words:
            by_domain.setdefault(words, []).append(_DOMAIN_WORDS.get(platform, platform.lower()))
    if len(by_domain) == 1:
        apical = next(iter(by_domain))
    else:
        apical = _bmr_words(*(ctx.apical_bmr or (None, None))) or (
            None if genomic else _bmr_words(ctx.bmr_type, ctx.bmr_factor))
    if len(by_domain) > 1:
        groups = {w: [f"the {_join_oxford(sorted(d))} endpoints"] for w, d in by_domain.items()}
        if genomic:
            groups.setdefault(genomic, []).append("the gene expression data")
        bmr_sentence = " " + ", and ".join(
            f"{'A' if i == 0 else 'a'} benchmark response of {w} was used to model "
            f"{' and '.join(what)}" for i, (w, what) in enumerate(groups.items())) + "."
    elif apical and genomic and apical != genomic:
        bmr_sentence = (f" A benchmark response of {apical} was used to model all apical "
                        f"endpoints, whereas a benchmark response of {genomic} was used to "
                        f"model the gene expression data.")
    elif apical or genomic:
        bmr_sentence = f" A benchmark response of {apical or genomic} was used to model all endpoints."
    else:
        # Never the protocol's usual BMR assumed: say it is missing.
        bmr_sentence = (" [Placeholder: the benchmark response used to model the "
                        "endpoints is not in the study data]")

    # --- Assemble the paragraph ---
    paragraph = (
        f"A short-term in vivo biological potency study on {ta_name} in "
        f"adult {sexes_str} {subject} was conducted. "
        + (f"Animals were exposed to {ta_name}{' ' + route_clause if route_clause else ''} "
           f"once daily for {duration} consecutive days (study days 0–{last_day}) "
           f"at {n_doses} {noun} ({dose_list} {dose_unit_full})."
           if inhaled else
           f"{ta_name} was {given + ' ' if given else ''}administered once "
           f"daily for {duration} consecutive days{' ' + route_clause if route_clause else ''} "
           f"(study days 0–{last_day}). "
           f"{ta_name} was administered at {n_doses} {noun} "
           f"({dose_list} {dose_unit_full}).")
        + f"{biosampling_sentence}"
        f" On study day {sacrifice_day}, the day after the final "
        f"{'exposure' if inhaled else 'dose was administered'}, animals were euthanized, standard "
        f"toxicological measures were assessed{assay_clause}."
        f"{bmd_clause}"
        f"{bmr_sentence}"
    )

    return paragraph


