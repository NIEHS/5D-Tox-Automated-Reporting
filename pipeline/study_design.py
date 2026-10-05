"""pipeline/study_design.py — the study-design facts the integrated project records.

Species, strain, route of administration and vehicle are study facts.  The
report states them only when the study's own metadata does: each experiment's
``experimentDescription`` (set at integration and reviewed in the metadata
step).  Nothing is defaulted — a field no experiment records, or one the
experiments disagree on, is None, and the report says it is missing rather than
assuming the NIEHS 5-day gavage protocol ([[feedback_no_hardcoded_report_facts]]).

``study_design_facts`` reads the facts; the ``*_phrase`` helpers turn them into
the wording the title, the Abstract and Materials and Methods use, returning ""
for an unknown fact so callers can drop the clause.
"""

from __future__ import annotations

_FIELDS = ("species", "strain", "articleRoute", "administrationMeans", "articleVehicle")

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


def study_design_facts(integrated: dict | None) -> dict:
    """{species, strain, route, vehicle, conflicts} from the experiments'
    recorded metadata.  A field is the value every experiment that records it
    agrees on; None when none records it or they disagree (listed under
    ``conflicts``)."""
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
    return {
        "species": one["species"],
        "strain": one["strain"],
        "route": route,
        "vehicle": one["articleVehicle"],
        "conflicts": conflicts,
    }


def missing_design_facts(facts: dict) -> list[str]:
    """Plain names of the design facts the data does not record."""
    names = {"species": "species", "strain": "strain",
             "route": "route of administration", "vehicle": "vehicle"}
    return [label for key, label in names.items() if not facts.get(key)]


def strain_display(facts: dict) -> str:
    strain = facts.get("strain") or ""
    return _STRAIN_DISPLAY.get(strain, strain)


def subject_phrase(facts: dict, capitalize: bool = False) -> str:
    """"Sprague Dawley rats" / "rats" / "animals" — the study animals, plural."""
    species = facts.get("species")
    noun = _SPECIES_PLURAL.get(species, f"{species}s") if species else "animals"
    if capitalize:
        noun = noun.title()
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
