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
    """"0 (vehicle control), 7.8, 15.6, and 31.25 mg/kg" from the dose groups
    ("0 (chamber control), … ppm" for an inhalation study)."""
    from pipeline.study_design import control_group

    doses = sorted(ctx.dose_groups or [])
    if not doses:
        return ""
    labels = [_format_dose_list([d], ctx.dose_unit) for d in doses]
    if doses[0] == 0:
        labels[0] = f"0 ({control_group(ctx.dose_unit)})"
    return f"{_join_oxford(labels)} {ctx.dose_unit}"


def build_study_design(ctx: MethodsContext, introduce: bool = True) -> list[str]:
    """``introduce``: the test article's first mention in the Materials and
    Methods (its name and abbreviation; else the abbreviation alone)."""
    from pipeline.study_design import (
        administration_phrase, control_group, dose_noun, exposure_verb, internal_assessment,
        subject_phrase,
        vehicle_phrase,
    )

    facts = _facts(ctx)
    sex_words = " and ".join(s.lower() for s in ctx.sexes) if ctx.sexes else ""
    subject = subject_phrase(facts)
    animals = f"{sex_words.capitalize()} {subject}" if sex_words else subject.capitalize()
    how = " ".join(p for p in (administration_phrase(facts), vehicle_phrase(facts)) if p)
    days = ctx.duration_days
    chem = ((_introduced(ctx) if introduce or not ctx.abbreviation else ctx.abbreviation)
            or "the test article")

    sentences = []
    doses = _dose_sentence_list(ctx)
    sentences.append(
        f"{animals} were {exposure_verb(facts)} {chem}{' ' + how if how else ''} once daily "
        f"for {days} consecutive days (study days 0–{days - 1})"
        + (f" at {dose_noun(ctx.dose_unit)} of {doses}." if doses else "."))
    if ctx.n_per_group is not None and ctx.n_control is not None:
        who = f"{sex_words} animals" if sex_words else "animals"
        sentences.append(
            f"There were {ctx.n_per_group} core {who} in each treated group and "
            f"{ctx.n_control} in the {control_group(ctx.dose_unit)} group.")
    if ctx.biosampling_doses:
        sentences.append(
            "Additional animals in the "
            f"{_format_dose_list(ctx.biosampling_doses, ctx.dose_unit)} {ctx.dose_unit} "
            f"groups were dedicated to {internal_assessment(ctx.dose_unit)}.")
    sentences.append(
        f"Core animals were euthanized on study day {days}, the day after the final "
        f"{'exposure' if facts.get('route') == 'inhaled' else 'dose'}.")

    from pipeline.study_design import missing_design_facts
    missing = [m for m in missing_design_facts(facts) if m != "species"]
    missing += ["the animal source", "age at receipt", "quarantine",
                "the randomization procedure"]
    return [" ".join(sentences) + " " + _placeholder(missing)]


def build_dose_selection(ctx: MethodsContext, introduce: bool = True) -> list[str]:
    from narrative.methods_prompt import _dose_spacing_phrase
    from pipeline.study_design import is_air_concentration

    doses = sorted(d for d in ctx.dose_groups or [] if d and d > 0)
    sentences = []
    if doses:
        top = _format_dose_list([doses[-1]], ctx.dose_unit)
        low = _format_dose_list([doses[0]], ctx.dose_unit)
        sentences.append(
            f"The study used {len(doses)} "
            f"{'exposure concentrations' if is_air_concentration(ctx.dose_unit) else 'dose levels'} "
            f"from {low} to {top} {ctx.dose_unit}, "
            f"with {_dose_spacing_phrase(ctx)}.")
    return [" ".join(sentences + [_placeholder(
        ["the rationale for the top dose, the lowest dose and the dose spacing"])])]


def build_chemistry(ctx: MethodsContext, introduce: bool = True) -> list[str]:
    """The test article identified: its name, then its abbreviation and
    identifiers ("Perfluorohexanesulfonamide (PFHxSAm; CASRN …; DTXSID …)"),
    wherever the section falls."""
    from pipeline.study_design import is_air_concentration, vehicle_phrase

    from common.dtxsid import substance_dtxsid
    ids = [ctx.abbreviation, f"CASRN {ctx.casrn}" if ctx.casrn else "",
           substance_dtxsid(ctx.dtxsid)]
    ids = [i for i in ids if i]
    chem = ctx.chemical_name or "The test article"
    sentences = [f"The test article was {chem}{' (' + '; '.join(ids) + ')' if ids else ''}."]
    vehicle = vehicle_phrase(_facts(ctx))
    if vehicle:
        sentences.append(f"Dose formulations were prepared {vehicle}.")
    missing = ["the test article source and lot", "identity and purity analyses",
               "storage conditions"]
    if is_air_concentration(ctx.dose_unit):
        # Inhalation: no vehicle or formulations; the atmosphere is generated
        # and its concentration monitored instead.
        missing.append("exposure generation and chamber concentration monitoring")
    else:
        if not vehicle:
            missing.append("the vehicle")
        missing.append("dose formulation analyses")
    return [" ".join(sentences + [_placeholder(missing)])]


_BUILDERS = {
    "study_design": build_study_design,
    "dose_selection": build_dose_selection,
    "chemistry": build_chemistry,
}
# The data-built subsections that name the test article, and whether one
# introduces its abbreviation (Chemistry always does, with its identifiers).
_NAMES_IT = {"study_design", "chemistry"}


def _introduced(ctx: MethodsContext) -> str:
    """The test article at its first mention: "Name (ABBR)", or the name."""
    name = ctx.chemical_name or ""
    return f"{name} ({ctx.abbreviation})" if name and ctx.abbreviation else name


def _built(ctx: MethodsContext, keys: list[str]) -> dict[str, list[str]]:
    """Each data-built subsection of ``keys`` (in the order the document
    places them), the first that names the test article introducing its
    abbreviation and the later ones using it — as the books do in each
    section (NIEHS-10: Study Design first; the 2026 books: Chemistry)."""
    out, named = {}, False
    for key in keys:
        if key in _BUILDERS and key not in out:
            out[key] = _BUILDERS[key](ctx, introduce=not named)
            named = named or key in _NAMES_IT
    return out


def assemble_methods_sections(
    ctx: MethodsContext,
    skeleton: list[tuple[str, str, int]],
    llm_texts: dict | None,
) -> list[MethodsSection]:
    """The Methods subsections in skeleton order: the data-built ones from
    MethodsContext, the rest from the LLM's {key: text} (multi-paragraph text
    split on blank lines; a key the LLM left empty is dropped)."""
    llm_texts = llm_texts or {}
    built = _built(ctx, [key for key, _, _ in skeleton])
    sections = []
    for key, heading, level in skeleton:
        if key in _BUILDERS:
            paragraphs = built[key]
        else:
            text = llm_texts.get(key, "")
            paragraphs = [p.strip() for p in str(text).split("\n\n") if p.strip()]
        if paragraphs:
            sections.append(MethodsSection(heading=heading, level=level, key=key,
                                           paragraphs=paragraphs))
    return sections


def refresh_data_built(sections: list[dict], context: dict | None,
                       order: list[str] | None = None) -> list[dict]:
    """Cached Methods ``sections`` with each data-built subsection rebuilt from
    the cached ``context``: they are deterministic, so a render picks up a
    change to their wording without the Process run that wrote the cache (and
    its LLM-written subsections).  ``order``: the subsection keys in the order
    the document places them (which one introduces the test article's
    abbreviation); else the sections' order.  The sections as given without
    a context."""
    if not isinstance(context, dict) or not context:
        return sections
    ctx = MethodsContext.from_dict(context)
    keys = [s.get("key") for s in sections if isinstance(s, dict)]
    built = _built(ctx, [k for k in (order or []) if k in keys] + keys)
    out = []
    for section in sections:
        key = section.get("key") if isinstance(section, dict) else None
        if key in built:
            section = {**section, "paragraphs": built[key]}
        out.append(section)
    return out
