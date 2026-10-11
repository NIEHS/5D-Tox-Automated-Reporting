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

Fallback (decided by the user, 2026-10-05): a fact the metadata does not record
takes the program's standard design — Sprague Dawley rats, by gavage in corn
oil, for five days — and the facts list it under ``fallback`` so callers can
log it.  The
route and vehicle fallback follows the dose unit: a concentration in air (ppm)
means inhalation, never gavage or corn oil; an oral dose (mg/kg) means gavage
in corn oil; any other unit gets no route fallback.  The dose unit itself is
resolved by ``resolve_dose_unit``: stated > recorded > mg/kg.

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

# Vehicles that are the medium itself ("in feed") rather than a carrier.
_MEDIUM_VEHICLES = {"feed", "water", "aerosol", "gas"}


# Units that are an exposure concentration in air (inhalation studies) and
# units that are an oral dose per body weight.
_AIR_CONCENTRATION_UNITS = {"ppm", "ppb", "mg/m3", "mg/m³", "µg/m3", "µg/m³"}
_ORAL_DOSE_UNITS = {"mg/kg", "mg/kg/day", "mg/kg bw", "mg/kg body weight"}

# The program's standard design, used only for facts the metadata lacks.
FALLBACK_STRAIN = {"rat": "Sprague-Dawley"}
FALLBACK_ORAL = {"route": "gavage", "vehicle": "corn oil"}
FALLBACK_AIR = {"route": "inhaled"}
FALLBACK_DURATION_DAYS = 5

# What a caller with no integrated project at all (no design to read) assumes:
# the standard design, so its wording matches the fallback.
STANDARD_DESIGN = {"species": "rat", "strain": "Sprague-Dawley", "route": "gavage",
                   "vehicle": "corn oil", "duration_days": FALLBACK_DURATION_DAYS}

_NUMBER_WORDS = ("Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
                 "Eight", "Nine", "Ten")


def is_air_concentration(dose_unit: str | None) -> bool:
    return (dose_unit or "").strip().lower() in {u.lower() for u in _AIR_CONCENTRATION_UNITS}


def resolve_dose_unit(stated: str | None, recorded: list[str] | None = None) -> tuple[str, str]:
    """(unit, source): the unit the user stated (--dose-unit / the UI), else the
    one unit the data records, else "mg/kg" — source is "stated", "recorded" or
    "fallback"."""
    if stated and stated.strip():
        return stated.strip(), "stated"
    units = sorted({u.strip() for u in recorded or [] if u and u.strip()})
    if len(units) == 1:
        return units[0], "recorded"
    return "mg/kg", "fallback"


def design_field_errors(fields: dict, vocabularies: dict) -> list[str]:
    """Why a stated design is unusable: a field outside DESIGN_FIELDS, or a value
    outside its controlled vocabulary.  Empty when it is fine."""
    if not isinstance(fields, dict):
        return ["the design must be a JSON object of field: value"]
    errors = [f"unsupported field {k!r}; use {list(DESIGN_FIELDS)}"
              for k in sorted(set(fields) - set(DESIGN_FIELDS))]
    for key, value in fields.items():
        vocab = vocabularies.get(key)
        allowed = ([v for vs in vocab.values() for v in vs] if isinstance(vocab, dict)
                   else vocab or [])
        if value is not None and allowed and value not in allowed:
            errors.append(f"{key}={value!r} is not in the vocabulary {allowed}")
    return errors


def apply_design_fields(integrated: dict, fields: dict) -> int:
    """Put stated design facts on every experiment's experimentDescription, in
    place; returns how many experiments were updated."""
    experiments = integrated.get("doseResponseExperiments") or []
    for exp in experiments:
        if not isinstance(exp.get("experimentDescription"), dict):
            exp["experimentDescription"] = {}
        exp["experimentDescription"].update(fields)
    return len(experiments)


def _duration_days(value: str | None) -> int | None:
    """Days from a controlled-vocabulary studyDuration ("5d" -> 5); None for an
    hour-scale or unparseable value."""
    import re

    m = re.fullmatch(r"\s*(\d+)\s*d(?:ays?)?\s*", value or "", re.I)
    return int(m.group(1)) if m else None


def study_design_facts(integrated: dict | None, dose_unit: str | None = None) -> dict:
    """{species, strain, route, vehicle, duration_days, conflicts, fallback} from the
    experiments' recorded metadata.  A field is the value every experiment
    that records it agrees on (disagreements are listed under ``conflicts``);
    a field none records takes the standard-design fallback for ``dose_unit``
    (see the module docstring), listed under ``fallback``."""
    seen: dict[str, set[str]] = {f: set() for f in _FIELDS}
    for exp in (integrated or {}).get("doseResponseExperiments") or []:
        ed = exp.get("experimentDescription") or {}
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
    facts = {
        "species": one["species"],
        "strain": one["strain"],
        "route": route,
        "vehicle": one["articleVehicle"],
        "duration_days": _duration_days(one["studyDuration"]),
        "conflicts": conflicts,
        "fallback": [],
    }
    unit = (dose_unit or "").strip().lower()
    if is_air_concentration(unit):
        standard = dict(FALLBACK_AIR)
    elif unit in _ORAL_DOSE_UNITS or not unit:
        standard = dict(FALLBACK_ORAL)
    else:
        standard = {}
    strain = FALLBACK_STRAIN.get(facts["species"] or "")
    if strain:
        standard["strain"] = strain
    # A recorded duration that is not in days (an hour-scale study) stays
    # unstated rather than replaced by five days.
    if not one["studyDuration"]:
        standard["duration_days"] = FALLBACK_DURATION_DAYS
    for key, value in standard.items():
        if not facts[key] and key not in _conflicting_keys(conflicts):
            facts[key] = value
            facts["fallback"].append(key)
    return facts


def _conflicting_keys(conflicts: list[str]) -> set[str]:
    """The design keys whose recorded values disagree (no fallback over a
    disagreement: that needs a person)."""
    by_field = {"strain": "strain", "articleRoute": "route",
                "administrationMeans": "route", "articleVehicle": "vehicle",
                "studyDuration": "duration_days"}
    return {by_field[c] for c in conflicts if c in by_field}


def missing_design_facts(facts: dict) -> list[str]:
    """Plain names of the design facts the data does not record (an
    inhalation study has no vehicle to record)."""
    names = {"species": "species", "strain": "strain",
             "route": "route of administration", "vehicle": "vehicle"}
    if facts.get("route") == "inhaled":
        names.pop("vehicle")
    return [label for key, label in names.items() if not facts.get(key)]


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


def strain_display(facts: dict) -> str:
    strain = facts.get("strain") or ""
    return _STRAIN_DISPLAY.get(strain, strain)


def design_or_standard(design: dict | None) -> dict:
    """The design a caller was given, or the standard design when it has none
    (a caller with no integrated project — its wording matches the fallback)."""
    return STANDARD_DESIGN if design is None else design


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


def administration_phrase(facts: dict) -> str:
    """"by gavage" / "by inhalation" / "in feed" — or "" when unrecorded."""
    return _ADMINISTRATION.get(facts.get("route") or "", ("", ""))[0]


def vehicle_phrase(facts: dict) -> str:
    """"in corn oil" — "" when unrecorded or when the vehicle is the medium
    itself (feed, water), which the administration phrase already names."""
    vehicle = facts.get("vehicle")
    if not vehicle or vehicle in _MEDIUM_VEHICLES:
        return ""
    return f"in {vehicle}"


def study_type_label(facts: dict) -> str:
    """The title's parenthetical, e.g. "Gavage Studies"; "" when unrecorded."""
    return _ADMINISTRATION.get(facts.get("route") or "", ("", ""))[1]
