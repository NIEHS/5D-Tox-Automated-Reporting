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

from methods_models import MethodsContext
from narrative_helpers import _format_dose_list, _format_organ_list


# ---------------------------------------------------------------------------
# Abstract → Methods paragraph builder
# ---------------------------------------------------------------------------
# The Abstract section has 4 labeled paragraphs (Background, Methods, Results,
# Summary).  The Methods paragraph is deterministic — every fact it reports is
# already in MethodsContext, so we can generate it from a template without an
# LLM call.  This keeps the abstract methods faithful to the data and fast.



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
    # Use abbreviation if present, else full name
    ta_name = ctx.chemical_name or "the test article"

    # --- Sexes ("adult male and female") ---
    sexes = [s.lower() for s in ctx.sexes] if ctx.sexes else ["male", "female"]
    sexes_str = " and ".join(sexes)

    # --- Species ("Sprague Dawley (Hsd:Sprague Dawley® SD®)") ---
    # If the species string contains the strain in parens, use as-is;
    # otherwise fall back to "Sprague Dawley".
    species = ctx.species or "Sprague Dawley"

    # --- Vehicle ---
    vehicle = ctx.vehicle or "corn oil"

    # --- Duration + study days range ---
    duration = ctx.duration_days or 5
    last_day = duration - 1
    sacrifice_day = duration

    # --- Route ---
    route = ctx.route or "gavage"

    # --- Dose list ---
    n_doses = len(ctx.dose_groups)
    dose_list = _format_dose_list(ctx.dose_groups, ctx.dose_unit)
    # NIEHS convention: "mg/kg body weight [mg/kg]" on first mention
    dose_unit_full = f"{ctx.dose_unit} body weight [{ctx.dose_unit}]"

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

    # --- BMR description ---
    # Default to NIEHS protocol: "one standard deviation"
    bmr_desc = "one standard deviation"
    if ctx.bmr_factor is not None and ctx.bmr_type:
        # e.g., bmr_factor=1.0, bmr_type="Std. Dev." → "one standard deviation"
        factor_words = {1.0: "one", 2.0: "two", 0.5: "one half of"}
        word = factor_words.get(ctx.bmr_factor, str(ctx.bmr_factor))
        type_clean = ctx.bmr_type.lower().replace("std. dev.", "standard deviation").strip()
        bmr_desc = f"{word} {type_clean}" if word else type_clean

    # --- Assemble the paragraph ---
    paragraph = (
        f"A short-term in vivo biological potency study on {ta_name} in "
        f"adult {sexes_str} {species} rats was conducted. "
        f"{ta_name} was formulated in {vehicle} and administered once "
        f"daily for {duration} consecutive days by {route} (study days "
        f"0–{last_day}). "
        f"{ta_name} was administered at {n_doses} doses "
        f"({dose_list} {dose_unit_full})."
        f"{biosampling_sentence}"
        f" On study day {sacrifice_day}, the day after the final dose "
        f"was administered, animals were euthanized, standard "
        f"toxicological measures were assessed{assay_clause}."
        f"{bmd_clause}"
        f" A benchmark response of {bmr_desc} was used to model all "
        f"endpoints."
    )

    return paragraph


