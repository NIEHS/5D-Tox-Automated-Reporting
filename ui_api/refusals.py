"""
ui_api.refusals — refusals as the new interface shows them.

Every refusal is explained by safeguards.refusals (``explain``: code, say,
details …). This module adds two things the interface needs:

* the codes of its own study acts (module M1: creating a study, recording its
  identity, deleting it), registered into the shared catalog at import, so
  ``explain`` takes them at their word like any other;
* ``fix`` in the interface's terms: the catalog names a place in the workflow
  (safeguards.refusals.PLACES); the interface names the module that clears it
  (MODULES.md §3, M1 … D6). ``explain`` here returns the module.
"""

from __future__ import annotations

from safeguards import refusals as _shared
from safeguards.refusals import Refusal, register

# The study acts' refusals (M1). ``fix``: a place, None when the screen that
# refused is where it is cleared.
STUDY_REFUSALS: dict[str, Refusal] = {
    "invalid_casrn": Refusal(400, (
        "This CASRN's check digit doesn't match; a digit is probably mistyped."), None),
    "study_exists": Refusal(409, (
        "A study of this chemical already exists ({id}). Open it instead."), "study"),
    "study_not_found": Refusal(404, (
        "There is no study {id}. It may have been deleted."), "study"),
    "study_id_has_suffix": Refusal(400, (
        "A study's id is the DTXSID alone. Ids with a suffix (…_rat, …_published) are "
        "made by the system."), None),
    "identity_changed": Refusal(409, (
        "The lookup now gives a different chemical than the one you confirmed. Look it "
        "up again."), None),
    "identity_exists": Refusal(409, (
        "This study already has its chemical's identity. Changing it is not done here."),
        None),
    "identity_incomplete": Refusal(400, (
        "The chemical's name is missing from what was confirmed. Its name comes from "
        "the lookup: look the chemical up again."), None),
    "identity_lookup_unreachable": Refusal(503, (
        "The chemical lookup service ({service}) could not be reached. Nothing was "
        "created. Try again in a minute."), None),
    "identity_not_found": Refusal(404, (
        "{service} has no chemical with the DTXSID {id}. A single mistyped digit gives "
        "another chemical or none. Check the id on the CompTox dashboard."), None),
    "identity_unconfirmed": Refusal(400, (
        "Confirm the chemical before going on: tick the box that says it is the chemical "
        "you are studying."), None),
    "member_of_report": Refusal(409, (
        "This is the {species} study of the report {parent}. Deleting it would break "
        "that report."), "study"),
    "run_in_flight": Refusal(409, (
        "Process is running on this study (since {time}). Wait for it to finish."),
        "process"),
    "confirm_mismatch": Refusal(400, (
        "The id you typed doesn't match this study's id. Nothing was deleted."), None),
    "changed_since_preview": Refusal(409, (
        "The study changed after you reviewed what would be deleted. Nothing was "
        "deleted; review the list again."), None),
    "format_changed": Refusal(409, (
        "The report format this id brings changed since you looked. Review it again."),
        None),
    "list_failed": Refusal(500, (
        "The list of studies can't be read: the folder that holds them is missing or "
        "unreadable. Tell the maintainer."), None),
    "structure_unavailable": Refusal(404, (
        "PubChem did not return a structure picture."), None),
}
register(STUDY_REFUSALS)

# The module that clears each place (MODULES.md §3).
PLACE_MODULE: dict[str, str] = {
    "study": "M1",
    "files": "M2",
    "dataset": "M3",
    "facts": "M4",
    "method_and_document": "M5",
    "data_review": "M6",
    "process": "P1",
    "sections": "D1",
    "publish": "D1",
    "handoff": "D4",
}


def module_of(fix: str | None) -> str | None:
    """The module that clears a place; None stays None."""
    return PLACE_MODULE.get(fix) if fix else None


def explain(exc: BaseException) -> dict:
    """The §4.2 envelope: safeguards.refusals.explain, ``fix`` as a module."""
    body = _shared.explain(exc)
    body["error"]["fix"] = module_of(body["error"]["fix"])
    return body


def say(code: str, **fields) -> str:
    """A code's plain words with its fields filled (a refusal shown before it
    is raised: a delete the screen will not offer, say)."""
    return _shared.REFUSALS[code].say.format_map(_shared._Fields(fields))
