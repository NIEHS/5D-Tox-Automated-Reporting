"""
methods_design.py — the Materials and Methods subsections built from the data.

Study Design, Dose Selection Rationale and Chemistry describe study facts:
the animals, how the test article was given, why these doses, where the test
article came from and how it was characterized.  An LLM asked to write them
from the study context fills every gap with plausible protocol text
("quarantined for 7 days", "purity >95% by HPLC", "doses bracket the threshold
for overt toxicity") that no input supports.  So these three are assembled here
from MethodsContext only, and every fact the data does not hold is named in one
visible "[Placeholder: …]" marker per subsection.  The marker keeps a draft
honest and blocks a strict (deliverable) build until the study team supplies
the text (render_common.scan_pending_markers).

The remaining subsections stay LLM-written from their method guides.
``assemble_methods_sections`` merges both in skeleton order for every caller.
"""

from __future__ import annotations

from narrative.methods_models import MethodsContext, MethodsSection
from narrative.narrative_helpers import _format_dose_list, _join_oxford

# Subsections written here, never requested from the LLM.
DATA_BUILT_KEYS = ("study_design", "dose_selection", "chemistry")


def _facts(ctx: MethodsContext) -> dict:
    return {"species": ctx.species, "strain": ctx.strain,
            "route": ctx.route, "vehicle": ctx.vehicle}


def _placeholder(items: list[str]) -> str:
    return (f"[Placeholder: {_join_oxford(items)} "
            f"{'is' if len(items) == 1 else 'are'} not in the study data]")


def _dose_sentence_list(ctx: MethodsContext) -> str:
    """"0 (vehicle control), 7.8, 15.6, and 31.25 mg/kg" from the dose groups."""
    doses = sorted(ctx.dose_groups or [])
    if not doses:
        return ""
    labels = [_format_dose_list([d], ctx.dose_unit) for d in doses]
    if doses[0] == 0:
        labels[0] = "0 (vehicle control)"
    return f"{_join_oxford(labels)} {ctx.dose_unit}"


def build_study_design(ctx: MethodsContext) -> list[str]:
    from pipeline.study_design import administration_phrase, subject_phrase, vehicle_phrase

    facts = _facts(ctx)
    sex_words = " and ".join(s.lower() for s in ctx.sexes) if ctx.sexes else ""
    subject = subject_phrase(facts)
    animals = f"{sex_words.capitalize()} {subject}" if sex_words else subject.capitalize()
    how = " ".join(p for p in (administration_phrase(facts), vehicle_phrase(facts)) if p)
    days = ctx.duration_days
    chem = ctx.chemical_name or "the test article"

    sentences = []
    doses = _dose_sentence_list(ctx)
    sentences.append(
        f"{animals} were administered {chem}{' ' + how if how else ''} once daily "
        f"for {days} consecutive days (study days 0–{days - 1})"
        + (f" at doses of {doses}." if doses else "."))
    if ctx.n_per_group is not None and ctx.n_control is not None:
        who = f"{sex_words} animals" if sex_words else "animals"
        sentences.append(
            f"There were {ctx.n_per_group} core {who} in each treated group and "
            f"{ctx.n_control} in the vehicle control group.")
    if ctx.biosampling_doses:
        sentences.append(
            "Additional animals in the "
            f"{_format_dose_list(ctx.biosampling_doses, ctx.dose_unit)} {ctx.dose_unit} "
            "groups were dedicated to internal dose assessment.")
    sentences.append(
        f"Core animals were euthanized on study day {days}, the day after the final dose.")

    from pipeline.study_design import missing_design_facts
    missing = [m for m in missing_design_facts(facts) if m != "species"]
    missing += ["the animal source", "age at receipt", "quarantine",
                "the randomization procedure"]
    return [" ".join(sentences) + " " + _placeholder(missing)]


def build_dose_selection(ctx: MethodsContext) -> list[str]:
    from narrative.methods_prompt import _dose_spacing_phrase

    doses = sorted(d for d in ctx.dose_groups or [] if d and d > 0)
    sentences = []
    if doses:
        top = _format_dose_list([doses[-1]], ctx.dose_unit)
        low = _format_dose_list([doses[0]], ctx.dose_unit)
        sentences.append(
            f"The study used {len(doses)} dose levels from {low} to {top} {ctx.dose_unit}, "
            f"with {_dose_spacing_phrase(ctx)}.")
    return [" ".join(sentences + [_placeholder(
        ["the rationale for the top dose, the lowest dose and the dose spacing"])])]


def build_chemistry(ctx: MethodsContext) -> list[str]:
    from pipeline.study_design import vehicle_phrase

    ids = [f"CASRN {ctx.casrn}" if ctx.casrn else "", ctx.dtxsid or ""]
    ids = [i for i in ids if i]
    chem = ctx.chemical_name or "The test article"
    sentences = [f"The test article was {chem}{' (' + '; '.join(ids) + ')' if ids else ''}."]
    vehicle = vehicle_phrase(_facts(ctx))
    if vehicle:
        sentences.append(f"Dose formulations were prepared {vehicle}.")
    missing = ["the test article source and lot", "identity and purity analyses",
               "storage conditions", "dose formulation analyses"]
    if not vehicle:
        missing.insert(3, "the vehicle")
    return [" ".join(sentences + [_placeholder(missing)])]


_BUILDERS = {
    "study_design": build_study_design,
    "dose_selection": build_dose_selection,
    "chemistry": build_chemistry,
}


def assemble_methods_sections(
    ctx: MethodsContext,
    skeleton: list[tuple[str, str, int]],
    llm_texts: dict | None,
) -> list[MethodsSection]:
    """The Methods subsections in skeleton order: the data-built ones from
    MethodsContext, the rest from the LLM's {key: text} (multi-paragraph text
    split on blank lines; a key the LLM left empty is dropped)."""
    llm_texts = llm_texts or {}
    sections = []
    for key, heading, level in skeleton:
        if key in _BUILDERS:
            paragraphs = _BUILDERS[key](ctx)
        else:
            text = llm_texts.get(key, "")
            paragraphs = [p.strip() for p in str(text).split("\n\n") if p.strip()]
        if paragraphs:
            sections.append(MethodsSection(heading=heading, level=level, key=key,
                                           paragraphs=paragraphs))
    return sections
