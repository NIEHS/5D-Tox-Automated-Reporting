"""pipeline/study_parameters.py — the study's parameters, each recorded or stated.

The report asserts a handful of study parameters: the species and strain, the
route and vehicle, the study's duration, the days and schedule of dosing, and
the dose unit.  There is no fallback for any of them (user decision 2026-11-16):
each is either RECORDED by the study's own data (the workbooks, the .bm2
metadata, the files' dose-unit column) or STATED by a person in the session's
``study_design.json`` — the one place stated values live.  A parameter neither
gives, or one the data records conflicting values for, makes the record
incomplete, and Process refuses (safeguards.inputs.require_study_parameters,
pipeline.process_integrated) naming the parameter.

``resolve`` is a pure function of the integrated project, the dose units the
files record and the stated fields; ``load`` reads the three for a session.
The engine's state carries the result (workflow.engine), so a front end can say
what is missing before anyone runs Process.

Values the metadata step inferred with an LLM (provenance "llm") are accepted
for now, labelled "inferred": whether to infer metadata at all is an open
question for the team (output/presentation/study-parameters-slides.html).
Removing "inferred" from ``ACCEPTED_SOURCES`` makes such a value missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipeline.study_design import (
    DESIGN_FIELDS,
    DESIGN_FILE,
    _duration_days,
    _INHALATION_METHODS,
    _SEXES,
)

# The parameters a report asserts, in the order a refusal lists them.
PARAMETERS = ("species", "strain", "route", "vehicle", "duration_days", "dosing_days",
              "dosing_schedule", "dose_unit")

# How a parameter is named to a person (a refusal, the state).
NAMES = {
    "species": "species",
    "strain": "strain",
    "route": "route of administration",
    "vehicle": "vehicle",
    "duration_days": "study duration (days)",
    "dosing_days": "number of dosing days",
    "dosing_schedule": "dosing schedule",
    "dose_unit": "dose unit",
}

# Parameters no deposited file records: a person states them in
# study_design.json under these keys.
STATED_ONLY = {"doseUnit": "dose_unit", "dosingDays": "dosing_days",
               "dosingSchedule": "dosing_schedule"}

# Every key study_design.json's "fields" may hold.
STATED_FIELDS = tuple(DESIGN_FIELDS) + tuple(STATED_ONLY)

# The vocabularies of the stated-only parameters (the design fields use
# bmdx_pipe.VOCABULARIES).  The schedules are the published books' wording:
# "once daily" (gavage, RR-8 … NIEHS-10), "6 hours plus T90 per day"
# (whole-body inhalation, NIEHS-12, 13).
STATED_VOCABULARIES = {
    "doseUnit": ["mg/kg", "ppm", "ppb", "mg/m3", "µg/m3"],
    "dosingSchedule": ["once daily", "6 hours plus T90 per day"],
}

# Where a recorded design value may come from and still count.
ACCEPTED_SOURCES = {"recorded", "stated", "inferred"}

# _meta.metadata_provenance values → the source a parameter reports.
_PROVENANCE = {"workbook": "recorded", "stated": "stated", "llm": "inferred"}

# The experimentDescription field(s) each design parameter is read from.
_DESIGN_SOURCES = {
    "species": ("species",),
    "strain": ("strain",),
    "route": ("administrationMeans", "articleRoute"),
    "vehicle": ("articleVehicle",),
    "duration_days": ("studyDuration",),
}


class StudyParametersIncomplete(ValueError):
    """Process refused: parameters missing or conflicting.  ``problems`` the
    plain sentences, ``parameters`` the names."""

    def __init__(self, dtxsid: str, params: "StudyParameters"):
        self.problems = params.problems()
        self.parameters = list(params.missing) + sorted(params.conflicting)
        super().__init__(
            f"{dtxsid}: the study parameters are incomplete — " + "; ".join(self.problems)
            + ".  Record them in the data, or state them in study_design.json "
            "(generate_report --design / --dose-unit, or the study's settings).")


@dataclass(frozen=True)
class StudyParameters:
    """values: {parameter: value or None}; sources: {parameter: "recorded" |
    "stated" | "inferred"}; missing: parameters nobody gives; conflicting:
    {parameter: [the values recorded]}; not_applicable: parameters the design
    has none of (an inhalation study's vehicle)."""

    values: dict
    sources: dict
    missing: tuple = ()
    conflicting: dict = field(default_factory=dict)
    not_applicable: tuple = ()
    sexes: tuple = ()
    inhalation: str | None = None

    @property
    def complete(self) -> bool:
        return not self.missing and not self.conflicting

    def problems(self) -> list[str]:
        out = [f"no {NAMES[p]} is recorded or stated" for p in self.missing]
        out += [f"the data record conflicting values for the {NAMES[p]} "
                f"({', '.join(map(str, vs))})" for p, vs in sorted(self.conflicting.items())]
        return out

    def facts(self) -> dict:
        """The design-facts shape the wording helpers read (pipeline.study_design:
        subject_phrase, administration_phrase, caption_fields, …)."""
        return {**self.values, "inhalation": self.inhalation, "sexes": list(self.sexes)}

    def to_dict(self) -> dict:
        return {"complete": self.complete, "values": self.values, "sources": self.sources,
                "missing": list(self.missing), "conflicting": self.conflicting,
                "not_applicable": list(self.not_applicable), "problems": self.problems()}


def _provenance_of(meta: dict, exp_name: str, keys: tuple) -> str:
    sources = (meta.get("metadata_provenance") or {}).get(exp_name) or {}
    for k in keys:
        if k in sources:
            return _PROVENANCE.get(sources[k], "recorded")
    return "recorded"


def _recorded_design(integrated: dict | None):
    """({parameter: {value: source}}, sexes, inhalation-methods seen) from the
    experiments' experimentDescription."""
    seen: dict[str, dict[str, str]] = {p: {} for p in _DESIGN_SOURCES}
    sexes: set[str] = set()
    meta = (integrated or {}).get("_meta") or {}
    for exp in (integrated or {}).get("doseResponseExperiments") or []:
        ed = exp.get("experimentDescription") or {}
        sex = str(ed.get("sex") or "").strip().lower()
        if sex in _SEXES:
            sexes.add(sex)
        for param, keys in _DESIGN_SOURCES.items():
            # The first key recording a value (the means before the route:
            # "gavage" says more than "oral").
            for k in keys:
                v = ed.get(k)
                if isinstance(v, str) and v.strip() and not (k == "articleRoute"
                                                             and v.strip() == "oral"):
                    src = _provenance_of(meta, exp.get("name", ""), (k,))
                    seen[param].setdefault(v.strip(), src)
                    break
    return seen, sorted(sexes)


def _dose_unit(stated: str | None, recorded_units) -> tuple[str | None, str | None, list]:
    """(unit, source, conflicting values).  A stated unit settles units the data
    disagree on only when it is one of them; one contradicting the single unit
    recorded is a conflict, never an override."""
    by_key: dict[str, str] = {}
    for u in recorded_units or []:
        if isinstance(u, str) and u.strip():
            by_key.setdefault(u.strip().lower(), u.strip())
    stated = (stated or "").strip() or None
    if stated and by_key and stated.lower() not in by_key:
        return None, None, sorted({*by_key.values(), f"{stated} (stated)"})
    if stated:
        return (by_key.get(stated.lower(), stated),
                "stated" if not by_key or len(by_key) > 1 else "recorded", [])
    if len(by_key) > 1:
        return None, None, sorted(by_key.values())
    if by_key:
        return next(iter(by_key.values())), "recorded", []
    return None, None, []


def resolve(integrated: dict | None, recorded_units, stated: dict | None) -> StudyParameters:
    """The study's parameters from the integrated project (its experiments'
    recorded design, stated design fields already applied at integration), the
    dose units the files record, and the stated fields (study_design.json)."""
    stated = stated or {}
    values: dict = {p: None for p in PARAMETERS}
    sources: dict = {}
    conflicting: dict = {}

    seen, sexes = _recorded_design(integrated)
    # A design fact stated in study_design.json that no experiment carries
    # (no integrated project yet, or one integrated before the statement):
    # the statement itself, as integration would apply it.
    for param, keys in _DESIGN_SOURCES.items():
        if not seen[param]:
            for k in keys:
                v = stated.get(k)
                if isinstance(v, str) and v.strip() and not (k == "articleRoute"
                                                             and v.strip() == "oral"):
                    seen[param][v.strip()] = "stated"
                    break
    for param, vals in seen.items():
        accepted = {v: s for v, s in vals.items() if s in ACCEPTED_SOURCES}
        if len(accepted) > 1:
            conflicting[param] = sorted(accepted)
        elif accepted:
            (value, src), = accepted.items()
            values[param], sources[param] = value, src

    # The route: an inhalation method is how the inhalation was made.
    inhalation = None
    if values["route"] in _INHALATION_METHODS:
        inhalation, values["route"] = values["route"], "inhaled"
    # The duration in days ("5d" → 5); an hour-scale one is not a day count.
    if values["duration_days"] is not None:
        days = _duration_days(values["duration_days"])
        if days is None:
            sources.pop("duration_days", None)
        values["duration_days"] = days

    unit, unit_src, unit_conflict = _dose_unit(stated.get("doseUnit"), recorded_units)
    if unit_conflict:
        conflicting["dose_unit"] = unit_conflict
    elif unit:
        values["dose_unit"], sources["dose_unit"] = unit, unit_src

    days = stated.get("dosingDays")
    if isinstance(days, int) and not isinstance(days, bool) and days > 0:
        values["dosing_days"], sources["dosing_days"] = days, "stated"
    schedule = stated.get("dosingSchedule")
    if isinstance(schedule, str) and schedule.strip():
        values["dosing_schedule"], sources["dosing_schedule"] = schedule.strip(), "stated"

    not_applicable = ("vehicle",) if values["route"] == "inhaled" else ()
    missing = tuple(p for p in PARAMETERS
                    if values[p] is None and p not in conflicting and p not in not_applicable)
    return StudyParameters(values=values, sources=sources, missing=missing,
                           conflicting=conflicting, not_applicable=not_applicable,
                           sexes=tuple(sexes), inhalation=inhalation)


def stated_fields(dtxsid: str, store=None) -> dict:
    """The session's stated fields (study_design.json "fields"; {} when none)."""
    if store is not None:
        doc = store.read_json(dtxsid, DESIGN_FILE)
    else:
        from common.session_files import read_session_json
        doc = read_session_json(dtxsid, DESIGN_FILE)
    fields = doc.get("fields") if isinstance(doc, dict) else None
    return dict(fields) if isinstance(fields, dict) else {}


def recorded_dose_units(dtxsid: str) -> list[str]:
    """The dose units the session's files record (their fingerprints)."""
    from pipeline.pool_fingerprints import ensure_fingerprints
    return [u for fp in ensure_fingerprints(dtxsid).values()
            if (u := (fp.get("dose_unit") if isinstance(fp, dict)
                      else getattr(fp, "dose_unit", None)))]


def load(dtxsid: str, store=None, integrated: dict | None = None) -> StudyParameters:
    """The session's study parameters (reads integrated.json when not given)."""
    if integrated is None:
        if store is not None:
            integrated = store.get_integrated(dtxsid)
        else:
            from pipeline.integrated_io import load_integrated
            integrated = load_integrated(dtxsid)
    return resolve(integrated, recorded_dose_units(dtxsid), stated_fields(dtxsid, store))


def require_complete(dtxsid: str, params: StudyParameters) -> StudyParameters:
    if not params.complete:
        raise StudyParametersIncomplete(dtxsid, params)
    return params


def stated_field_errors(fields: dict) -> list[str]:
    """Why stated values of the stated-only parameters are unusable (the
    design fields are checked against bmdx_pipe.VOCABULARIES elsewhere)."""
    errors = []
    for key, allowed in STATED_VOCABULARIES.items():
        v = fields.get(key)
        if v is not None and v not in allowed:
            errors.append(f"{key}={v!r} is not in the vocabulary {allowed}")
    days = fields.get("dosingDays")
    if days is not None and not (isinstance(days, int) and not isinstance(days, bool)
                                 and 0 < days <= 365):
        errors.append(f"dosingDays={days!r} must be a whole number of days (1–365)")
    return errors


def require_session_parameters(dtxsid: str, store=None) -> StudyParameters:
    """The session's complete parameters, else a StepError (422) naming what is
    missing or conflicting — for a front end that needs them (the dose unit of
    a narrative, the Methods preview) outside Process."""
    from workflow.errors import StepError

    params = load(dtxsid, store)
    if not params.complete:
        raise StepError(str(StudyParametersIncomplete(dtxsid, params)), 422)
    return params


def required_unit(value, where: str) -> str:
    """A dose unit a caller must give (a request body, a cached section): it,
    else a StepError (400) — never mg/kg assumed."""
    from workflow.errors import StepError

    if isinstance(value, str) and value.strip():
        return value.strip()
    raise StepError(f"no dose unit in {where}; give the study's dose unit "
                    "(pipeline.study_parameters) — none is assumed", 400)
