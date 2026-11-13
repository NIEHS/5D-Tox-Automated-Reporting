"""
common/dispositions.py — how each animal left the study.

A study's Removal Reasons workbook (``*_Individual_Animal_Removal_Reasons_Data``,
NIEHS-12 and 13) records each animal's Disposition and Removal Day.  bmdx-pipe
puts them on the study structure's animals (``integrated._meta.study_structure``
``animals[id].disposition`` / ``removal_day``).  Two dispositions are the
schedule — the terminal sacrifice and the internal-dose cohort's sampling; any
other is an unscheduled removal, which the body weight footnotes and the
Animal Condition paragraph report in the reports' words ("was euthanized
moribund on study day 4", "one accidental death").  A study without the
workbook has no dispositions, and its early removals are read from the body
weight terminal days as before.  Kept in the dependency-free `common` package
so tables/ and narrative/ share one vocabulary.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

SCHEDULED = frozenset({"scheduled removal (terminal)", "biological sampling"})

# The reports' verb phrases, singular and plural (NIEHS-12, 13).
_PHRASES = {
    "found dead": ("was found dead", "were found dead"),
    "euthanized moribund": ("was euthanized moribund", "were euthanized moribund"),
    "accidental death": ("died accidentally", "died accidentally"),
}


def dispositions(structure: dict | None) -> dict[str, dict]:
    """``{animal id: {"disposition", "day"}}`` for the animals the study
    structure records a disposition for; {} when the study has no Removal
    Reasons workbook.  ``day`` is the study day number (None when unrecorded)."""
    out = {}
    for aid, rec in ((structure or {}).get("animals") or {}).items():
        if rec.get("disposition"):
            out[str(aid)] = {"disposition": rec["disposition"],
                             "day": day_number(rec.get("removal_day"))}
    return out


def day_number(label) -> int | None:
    """``"SD4"`` → 4; None when the label has no number."""
    m = re.search(r"\d+", str(label or ""))
    return int(m.group()) if m else None


def is_scheduled(disposition: str | None) -> bool:
    return str(disposition or "").strip().lower() in SCHEDULED


def unscheduled(structure: dict | None) -> list[dict]:
    """The animals removed off schedule: ``{id, sex, dose, selection,
    disposition, day}`` each, in (dose, day, id) order."""
    out = []
    for aid, rec in ((structure or {}).get("animals") or {}).items():
        if rec.get("disposition") and not is_scheduled(rec["disposition"]):
            out.append({"id": str(aid), "sex": rec.get("sex"), "dose": rec.get("dose"),
                        "selection": rec.get("selection"), "disposition": rec["disposition"],
                        "day": day_number(rec.get("removal_day"))})
    return sorted(out, key=lambda r: (r["dose"] or 0.0, r["day"] or 0, r["id"]))


def removal_phrase(disposition: str, count: int = 1) -> str:
    """The reports' verb phrase for an unscheduled removal: "was euthanized
    moribund" / "were found dead".  A disposition outside the vocabulary is
    logged and printed as recorded ("was removed (Natural Death)")."""
    phrases = _PHRASES.get(str(disposition).strip().lower())
    if phrases is None:
        logger.warning("Unknown disposition %r: printed as recorded", disposition)
        return f"{'was' if count == 1 else 'were'} removed ({disposition})"
    return phrases[0 if count == 1 else 1]
