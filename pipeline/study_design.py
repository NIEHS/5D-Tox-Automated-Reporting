"""pipeline/study_design.py — the study-design facts the integrated project records.

Species, strain, route of administration, vehicle and duration are study facts.  The
report states them only when the study's own metadata does: each experiment's
``experimentDescription`` (set at integration and reviewed in the metadata
step).  Nothing is defaulted — a field no experiment records, or one the
experiments disagree on, is None, and the report says it is missing rather than
assuming the NIEHS 5-day gavage protocol ([[feedback_no_hardcoded_report_facts]]).

``study_design_facts`` reads the facts; the ``*_phrase`` helpers turn them into
the wording the title, the Abstract and Materials and Methods use, returning ""
for an unknown fact so callers can drop the clause.

No fallback (user decision 2026-11-16, replacing the standard-design fallback of
2026-10-05): a fact the data does not record is None here, and Process refuses a
study whose parameters are incomplete (pipeline.study_parameters, the one
resolution of every parameter with where it came from — recorded or stated).

Facts a person states for a study whose data does not record them (``generate_report
--design``) are kept in ``sessions/<id>/study_design.json`` and put back on every
experiment at each integration (``apply_design_fields``), so re-integration, which
re-infers the metadata, does not lose them.
"""

from __future__ import annotations

_FIELDS = ("species", "strain", "articleRoute", "administrationMeans", "articleVehicle",
           "studyDuration")

# The experimentDescription fields a stated design may set: the facts above, nothing else.
DESIGN_FIELDS = _FIELDS

# The session file holding a stated design: {"fields": {...}, "recorded_at": ...}.
DESIGN_FILE = "study_design.json"

# The sexes a study's experiments record (anything else is ignored).
_SEXES = ("female", "male")

# NIEHS spelling of the controlled-vocabulary strain names.
_STRAIN_DISPLAY = {"Sprague-Dawley": "Sprague Dawley"}

_SPECIES_PLURAL = {
    "rat": "rats", "mouse": "mice", "human": "humans", "rabbit": "rabbits",
    "dog": "dogs", "monkey": "monkeys", "zebrafish": "zebrafish",
    "guinea pig": "guinea pigs", "hamster": "hamsters", "pig": "pigs",
}

# (route, means) → how the test article was given, and the title's study type.
_ADMINISTRATION = {
    "gavage": ("by gavage", "Gavage Studies"),
    "inhaled": ("by inhalation", "Inhalation Studies"),
    "transdermal": ("by dermal application", "Dermal Studies"),
    "dietary": ("in feed", "Feed Studies"),
    "drinking water": ("in drinking water", "Drinking Water Studies"),
}

# The routes a study's design states (a document node may be gated on one).
ROUTES = tuple(_ADMINISTRATION)

# How an inhalation exposure is made (administrationMeans of an inhaled study):
# the title's "(Whole-body Inhalation Studies)" (NIEHS-12, 13).
_INHALATION_METHODS = {"whole-body": "Whole-body", "nose-only": "Nose-only"}

# Vehicles that are the medium itself ("in feed") rather than a carrier.
_MEDIUM_VEHICLES = {"feed", "water", "aerosol", "gas"}


# Units that are an exposure concentration in air (inhalation studies).
_AIR_CONCENTRATION_UNITS = {"ppm", "ppb", "mg/m3", "mg/m³", "µg/m3", "µg/m³"}

_NUMBER_WORDS = ("Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
                 "Eight", "Nine", "Ten")


def is_air_concentration(dose_unit: str | None) -> bool:
    return (dose_unit or "").strip().lower() in {u.lower() for u in _AIR_CONCENTRATION_UNITS}


def design_field_errors(fields: dict, vocabularies: dict,
                        allowed: tuple = DESIGN_FIELDS) -> list[str]:
    """Why a stated design is unusable: a field outside ``allowed`` (the
    stated study parameters, pipeline.study_parameters.STATED_FIELDS), or a
    value outside its controlled vocabulary.  Empty when it is fine."""
    if not isinstance(fields, dict):
        return ["the design must be a JSON object of field: value"]
    errors = [f"unsupported field {k!r}; use {list(allowed)}"
              for k in sorted(set(fields) - set(allowed))]
    for key, value in fields.items():
        vocab = vocabularies.get(key)
        allowed = ([v for vs in vocab.values() for v in vs] if isinstance(vocab, dict)
                   else vocab or [])
        if value is not None and allowed and value not in allowed:
            errors.append(f"{key}={value!r} is not in the vocabulary {allowed}")
    return errors


def apply_design_fields(integrated: dict, fields: dict) -> int:
    """Put stated design facts on every experiment's experimentDescription, in
    place; returns how many experiments were updated.

    A field the study workbooks state (``_meta.metadata_provenance`` says
    "workbook") keeps the workbook's value: a stated fact never overrides the
    study's own record (ADR-0032; safeguards.inputs refuses a statement that
    contradicts it).  A field set here is recorded as "stated"."""
    import logging

    experiments = integrated.get("doseResponseExperiments") or []
    meta = integrated.setdefault("_meta", {}) if isinstance(integrated.get("_meta"), dict) else {}
    provenance = meta.setdefault("metadata_provenance", {})
    for exp in experiments:
        if not isinstance(exp.get("experimentDescription"), dict):
            exp["experimentDescription"] = {}
        ed = exp["experimentDescription"]
        sources = provenance.setdefault(exp.get("name", ""), {})
        for key, value in fields.items():
            # The stated-only parameters (the dose unit, the dosing days and
            # schedule) are not experiment metadata: they stay in
            # study_design.json (pipeline.study_parameters).
            if key not in DESIGN_FIELDS:
                continue
            if sources.get(key) == "workbook":
                if value not in (None, ed.get(key)):
                    logging.getLogger(__name__).warning(
                        "%s: stated %s %r not applied; the study workbook states %r",
                        exp.get("name"), key, value, ed.get(key))
                continue
            ed[key] = value
            sources[key] = "stated"
    return len(experiments)


def workbook_facts(integrated: dict | None) -> dict[str, dict]:
    """{experiment: {field: value}} the study workbooks state for the dataset
    (the fields ``_meta.metadata_provenance`` marks "workbook")."""
    meta = (integrated or {}).get("_meta") or {}
    provenance = meta.get("metadata_provenance") or {}
    out: dict[str, dict] = {}
    for exp in (integrated or {}).get("doseResponseExperiments") or []:
        name = exp.get("name", "")
        ed = exp.get("experimentDescription") or {}
        fixed = {k: ed.get(k) for k, src in (provenance.get(name) or {}).items()
                 if src == "workbook" and ed.get(k) is not None}
        if fixed:
            out[name] = fixed
    return out


def _duration_days(value: str | None) -> int | None:
    """Days from a controlled-vocabulary studyDuration ("5d" -> 5); None for an
    hour-scale or unparseable value."""
    import re

    m = re.fullmatch(r"\s*(\d+)\s*d(?:ays?)?\s*", value or "", re.I)
    return int(m.group(1)) if m else None


def study_design_facts(integrated: dict | None) -> dict:
    """{species, strain, route, vehicle, duration_days, inhalation, sexes,
    conflicts} from the experiments' recorded metadata (stated facts are on it
    since integration; ``sexes``: the sexes the experiments record, sorted).  A
    field is the value every experiment that records it agrees on
    (disagreements are listed under ``conflicts``); one none records is None.
    The wording helpers below read this shape; Process takes its facts from
    pipeline.study_parameters, which refuses what is missing."""
    seen: dict[str, set[str]] = {f: set() for f in _FIELDS}
    sexes: set[str] = set()
    for exp in (integrated or {}).get("doseResponseExperiments") or []:
        ed = exp.get("experimentDescription") or {}
        sex = str(ed.get("sex") or "").strip().lower()
        if sex in _SEXES:
            sexes.add(sex)
        for f in _FIELDS:
            v = ed.get(f)
            if isinstance(v, str) and v.strip():
                seen[f].add(v.strip())
    conflicts = sorted(f for f, vals in seen.items() if len(vals) > 1)
    one = {f: (next(iter(vals)) if len(vals) == 1 else None) for f, vals in seen.items()}
    # Route: the specific means (gavage, feed, drinking water) when recorded,
    # else the route itself.  "oral" alone does not say how.
    route = one["administrationMeans"] or one["articleRoute"]
    if route == "oral":
        route = None
    # An inhalation method is how the inhalation was made, not another route.
    inhalation = route if route in _INHALATION_METHODS else None
    if inhalation:
        route = "inhaled"
    return {
        "species": one["species"],
        "strain": one["strain"],
        "route": route,
        "vehicle": one["articleVehicle"],
        "duration_days": _duration_days(one["studyDuration"]),
        "inhalation": inhalation,
        "sexes": sorted(sexes),
        "conflicts": conflicts,
    }


def schedule_phrase(schedule: str) -> str:
    """The dosing schedule as the Methods print it after the route: "once
    daily"; "for 6 hours plus T90 per day" (NIEHS-12, 13)."""
    schedule = schedule.strip()
    return f"for {schedule}" if schedule[:1].isdigit() else schedule


def exposure_verb(facts: dict) -> str:
    """"exposed to" for inhalation, else "administered"."""
    return "exposed to" if facts.get("route") == "inhaled" else "administered"


def control_group(dose_unit: str | None) -> str:
    """"chamber control" for an air concentration (the controls breathe clean
    air; there is no vehicle), else "vehicle control"."""
    return "chamber control" if is_air_concentration(dose_unit) else "vehicle control"


def after_administration(facts: dict) -> str:
    """"postexposure" for an inhalation study, else "postdose" — the word NTP
    puts after a sampling time ("2 hours postdose")."""
    return "postexposure" if facts.get("route") == "inhaled" else "postdose"


def dose_noun(dose_unit: str | None) -> str:
    """"exposure concentrations" for an air concentration, else "doses"."""
    return "exposure concentrations" if is_air_concentration(dose_unit) else "doses"


def internal_assessment(dose_unit: str | None) -> str:
    """The internal-dose cohort's name in prose: "internal concentration
    assessment" for an air concentration (NIEHS-12, 13), else "internal dose
    assessment" (NIEHS-07 … 10)."""
    return ("internal concentration assessment" if is_air_concentration(dose_unit)
            else "internal dose assessment")


def strain_display(facts: dict) -> str:
    strain = facts.get("strain") or ""
    return _STRAIN_DISPLAY.get(strain, strain)


def require_design(design: dict | None) -> dict:
    """The design a caller was given; None is refused — there is no standard
    design to assume (the study parameters, pipeline.study_parameters, are
    complete before anything is written)."""
    if design is None:
        raise ValueError("no study design given; the wording needs the study's "
                         "parameters (pipeline.study_parameters) — none is assumed")
    return design


def species_singular(facts: dict) -> str:
    """"rat" / "mouse" / "animal" (species unrecorded)."""
    return facts.get("species") or "animal"


def species_plural(facts: dict, capitalize: bool = False) -> str:
    """"rats" / "mice" / "animals" (species unrecorded); "rats and mice" for a
    report over several studies (facts["studies"], rendering.report_compose)."""
    if facts.get("studies"):
        return " and ".join(species_plural(f, capitalize) for f in facts["studies"])
    species = facts.get("species")
    noun = _SPECIES_PLURAL.get(species, f"{species}s") if species else "animals"
    return noun.title() if capitalize else noun


def duration_phrase(days: int | None) -> str:
    """"Five Days" / "One Day" / "28 Days" (numbers to ten in words, as NIEHS
    captions print them); "" when the duration is unknown."""
    if not days:
        return ""
    count = _NUMBER_WORDS[days] if days < len(_NUMBER_WORDS) else str(days)
    return f"{count} {'Day' if days == 1 else 'Days'}"


def caption_treatment(facts: dict, compound: str) -> str:
    """The table-caption treatment clause, as NIEHS prints it: "Administered
    Triclosan for Five Days", or "Exposed to 1,4-Dichlorobenzene for Five Days"
    for an inhalation study (NIEHS-13); no "for …" clause when the duration is
    unknown."""
    verb = "Exposed to" if facts.get("route") == "inhaled" else "Administered"
    duration = duration_phrase(facts.get("duration_days"))
    return f"{verb} {compound}" + (f" for {duration}" if duration else "")


def subject_phrase(facts: dict, capitalize: bool = False) -> str:
    """"Sprague Dawley rats" / "rats" / "animals" — the study animals, plural;
    "Sprague Dawley rats and B6D2F1 mice" over several studies."""
    if facts.get("studies"):
        return " and ".join(subject_phrase(f, capitalize) for f in facts["studies"])
    noun = species_plural(facts, capitalize)
    strain = strain_display(facts)
    return f"{strain} {noun}" if strain else noun


def sex_word(facts: dict) -> str:
    """"Male" / "Female" when the study's experiments record one sex only — over
    several studies, when every study is of that one sex — else ""."""
    if facts.get("studies"):
        words = {sex_word(f) for f in facts["studies"]}
        return words.pop() if len(words) == 1 else ""
    sexes = facts.get("sexes") or []
    return sexes[0].title() if len(sexes) == 1 else ""


def title_subjects(facts: dict, animals) -> str:
    """The study animals as a title names them, ``animals(study_facts)`` giving
    one study's ("Sprague Dawley Rats"), led by the sex when the study used one
    only, as the published books do: "Male Sprague Dawley … Rats" (NIEHS-02 …
    06); "Female Sprague Dawley … Rats and B6D2F1/Crl Mice" (NIEHS-12, 13,
    the shared sex named once); "Sprague Dawley … Rats" for both sexes
    (NIEHS-07 … 10).  Studies of different sexes each lead with their own."""
    studies = facts.get("studies")
    if not studies:
        return " ".join(x for x in (sex_word(facts), animals(facts)) if x)
    shared = sex_word(facts)
    each = [animals(f) if shared else " ".join(x for x in (sex_word(f), animals(f)) if x)
            for f in studies]
    return " ".join(x for x in (shared, " and ".join(each)) if x)


def caption_subject(facts: dict) -> str:
    """The animals a table caption names, with their sexes: "Female Rats",
    "Male and Female Rats", "Rats" (sexes unrecorded); over several studies
    "Female Rats and Mice" when they share their sexes, else each study's
    ("Male Rats and Female Mice")."""
    def sexes(f):
        return " and ".join(s.title() for s in _SEXES[::-1] if s in (f.get("sexes") or []))

    studies = facts.get("studies") or [facts]
    each = [sexes(f) for f in studies]
    if len(set(each)) == 1:
        return " ".join(x for x in (each[0], species_plural(facts, capitalize=True)) if x)
    return " and ".join(" ".join(x for x in (sx, species_plural(f, capitalize=True)) if x)
                        for sx, f in zip(each, studies))


def caption_fields(facts: dict, compound: str) -> dict:
    """A document's caption fields for these animals: ``subject`` ("Female Rats
    and Mice") and ``treatment`` ("Exposed to 1,4-Dichlorobenzene for Five
    Days"), as a definition writes them (``${subject} ${treatment}``)."""
    return {"subject": caption_subject(facts), "treatment": caption_treatment(facts, compound)}


def administration_phrase(facts: dict) -> str:
    """"by gavage" / "by inhalation" / "by whole-body inhalation" (the method
    recorded) / "in feed" — or "" when unrecorded."""
    phrase = _ADMINISTRATION.get(facts.get("route") or "", ("", ""))[0]
    if phrase and facts.get("route") == "inhaled" and facts.get("inhalation"):
        phrase = f"by {facts['inhalation']} inhalation"
    return phrase


def vehicle_phrase(facts: dict) -> str:
    """"in corn oil" — "" when unrecorded or when the vehicle is the medium
    itself (feed, water), which the administration phrase already names."""
    vehicle = facts.get("vehicle")
    if not vehicle or vehicle in _MEDIUM_VEHICLES:
        return ""
    return f"in {vehicle}"


def study_type_label(facts: dict) -> str:
    """The title's parenthetical, e.g. "Gavage Studies", "Whole-body Inhalation
    Studies" (the inhalation method recorded, NIEHS-12, 13); "" when unrecorded."""
    label = _ADMINISTRATION.get(facts.get("route") or "", ("", ""))[1]
    method = _INHALATION_METHODS.get(facts.get("inhalation") or "")
    if label and facts.get("route") == "inhaled" and method:
        label = f"{method} {label}"
    return label
