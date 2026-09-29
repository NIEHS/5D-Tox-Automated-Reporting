"""
Abstract → Results pharmacokinetics paragraph.

When biosampling animals were dedicated to internal dose assessment,
the Abstract gets an extra paragraph summarizing the plasma
concentration measurements and the calculated two-point half-lives
across the biosampling dose groups.

This module owns the single deterministic builder for that paragraph:

  build_abstract_results_pk(chemical_name, pk_concentrations,
                            pk_half_lives, pk_timepoints, dose_unit)
      Returns a single-paragraph string, or empty string when no PK
      data is available.

The data comes from MethodsContext.pk_concentrations and
.pk_half_lives, which extract_methods_context populated from the
tissue-concentration sidecars.  Half-lives use the two-point formula
t½ = ln(2) × Δt / ln(C₁/C₂).

Cross-cutting helpers (_format_dose_value, _join_oxford) come from
narrative_helpers.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

from narrative.narrative_helpers import _format_dose_value, _join_oxford


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


