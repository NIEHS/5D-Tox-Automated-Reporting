"""
ui_api.vocabularies — the controlled vocabularies and identifier formats a
front-end binds its fields to (MODULES.md §4.5, ``GET /api/v2/vocabularies``).

A field that takes a study fact (species, strain, route, …) offers the
controlled vocabulary of ADR-0019 (``bmdx_pipe.VOCABULARIES``) and nothing
else: no free text. A field that takes an identifier checks it as it is typed,
with the same pattern the backend checks. Both are served from here, so the
browser keeps no copy of either, and the command line and the notebook read the
same lists.

Each vocabulary is served as one self-describing entry, so a field needs
nothing else to work:

    {"label": "Species", "values": ["rat", "mouse", …]}
    {"label": "Strain", "depends_on": "species", "by": {"rat": […], "mouse": […]}}

Only the dependencies the vocabulary itself declares are served (strains are
listed per species); the vocabulary declares no mapping from the route to the
vehicle or the means of administration, so none is served (the study-design
check does not hold one either).

The labels are not written here: they are the names BMDExpress 3 gives these
fields in a data file's metadata header (``ExperimentDescriptionParser``, the
same vocabulary bmdx_pipe mirrors), so a person sees a field under the name
their files use. A vocabulary with no such name is labelled by its key.
"""

from __future__ import annotations

import re

from common.dtxsid import DTXSID_RE

# The id of a study a person creates: the chemical's DTXSID, digits only
# (Gate 0 decision Q7). The suffixed sessions (``_published``, ``_rat``,
# ``_mouse``) are made by the system and are not offered to a person.
STUDY_ID_RE = re.compile(r"^DTXSID\d+$")

# A DOI as a report states it: bare (no https://doi.org/), ``10.<registrant>/
# <suffix>``. pipeline.deposit checks only the ``10.`` prefix; this is the
# stricter form a field checks while a person types.
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def _casrn_re() -> re.Pattern:
    """The CASRN pattern the chemical resolver uses (one definition)."""
    from narrative.chem_resolver import CASRN_PATTERN
    return CASRN_PATTERN


def id_patterns() -> dict[str, dict]:
    """{kind: {pattern, example, say}} for every identifier a person types.

    ``pattern`` is a regular expression a browser can use as is (anchored, no
    flags). ``say`` is what a field shows when the value does not match.
    """
    return {
        "study_id": {
            "pattern": STUDY_ID_RE.pattern,
            "example": "DTXSID50469320",
            "say": "A study is named by its chemical's DTXSID: “DTXSID” followed by digits only.",
        },
        "session_id": {
            "pattern": DTXSID_RE.pattern,
            "example": "DTXSID1020431_rat",
            "say": ("Any study the application holds, including the ones it makes itself "
                    "(for example a species' part of a report over several studies)."),
        },
        "dtxsid": {
            "pattern": STUDY_ID_RE.pattern,
            "example": "DTXSID50469320",
            "say": "A DTXSID is “DTXSID” followed by digits.",
        },
        "casrn": {
            "pattern": _casrn_re().pattern,
            "example": "41997-13-1",
            "say": "A CAS registry number is three groups of digits: 2–7, then 2, then 1 (e.g. 41997-13-1).",
        },
        "doi": {
            "pattern": DOI_RE.pattern,
            "example": "10.22427/NIEHS-DATA-NIEHS-10",
            "say": "A DOI starts with “10.”, then the registrant, a slash and the rest (no https://doi.org/).",
        },
    }


# The field names of a BMDExpress 3 metadata header (BMDExpress-3
# src/main/java/com/sciome/bmdexpress2/util/ExperimentDescriptionParser.java:
# the names parseVocabularyField reports a field under; "Strain" from its
# STRAIN_KEYS). Keyed by the bmdx_pipe.VOCABULARIES field.
LABELS: dict[str, str] = {
    "sex": "Sex",
    "organ": "Organ",
    "species": "Species",
    "strain": "Strain",
    "platform": "Platform",
    "provider": "Provider",
    "subjectType": "Subject Type",
    "articleRoute": "Article Route",
    "articleVehicle": "Article Vehicle",
    "administrationMeans": "Administration Means",
    "studyDuration": "Study Duration",
    "articleType": "Article Type",
    "dataType": "Data Type",
}


def vocabularies() -> dict:
    """The controlled vocabularies (ADR-0019), one entry per field:

    ``{"vocabularies": {field: {"label", "values"}
                               | {"label", "depends_on", "by": {parent value: [values]}}}}``
    """
    from bmdx_pipe import VOCABULARIES

    out: dict[str, dict] = {}
    for key, values in VOCABULARIES.items():
        entry: dict = {"label": LABELS.get(key, key)}
        if isinstance(values, dict):
            # The one kind of dependency the vocabulary declares: a list per
            # value of another field (strains per species).
            parent = next((p for p, pv in VOCABULARIES.items()
                           if isinstance(pv, (list, tuple)) and set(values) <= set(pv)), None)
            if parent is None:
                raise ValueError(f"vocabulary {key!r} is keyed by values of no other vocabulary")
            entry["depends_on"] = parent
            entry["by"] = {k: list(v) for k, v in values.items()}
        else:
            entry["values"] = list(values)
        out[key] = entry
    return {"vocabularies": out}


def vocabularies_payload() -> dict:
    """What ``GET /api/v2/vocabularies`` serves: the vocabularies and the id patterns."""
    return {**vocabularies(), "patterns": id_patterns()}
