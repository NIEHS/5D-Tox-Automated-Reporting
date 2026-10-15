"""
workflow.refusals — every refusal the backend can give, in plain words
(MODULES.md §4.2, the error envelope).

A step that cannot proceed raises (``StepError``, ``GuardViolation``, a pin
error, a bad id, a damaged session file). What the person needs is not the
exception but three things: what happened, in their terms; what to do about it;
and where in the interface it is fixed. This module is the one place that maps
the backend's refusals to those, so the browser, the command line and the
notebook explain a refusal the same way:

    {"error": {"code": "not_validated", "status": 400,
               "message": "No fingerprints found -- run validation first",
               "say": "The study's files haven't been checked yet. …",
               "fix": "M2", "details": {}}}

* ``code`` comes from the closed list ``REFUSALS``; a refusal the list does not
  know is ``unexpected``, never a guess at a nearer one.
* ``message`` is the backend's own text, verbatim (the interface shows it behind
  a toggle). ``say`` is written here, next to the code.
* ``fix`` names the interface module where the cause is cleared (MODULES.md §3),
  or None when nothing in the interface clears it (tell the maintainer).
* ``status`` is the backend's advisory status where it gives one (StepError),
  else the code's own.

The refusals the backend raises today carry no code, so most are recognised by
their message (``_MESSAGE_RULES``, quoted from the Gate 0 analyses: data §3.1,
Process §6.1, document §9.1). An exception that carries a ``code`` attribute
naming a listed code (the phase guard of C1, say) is taken at its word, and so
are the ``say``, ``fix`` and ``details`` it carries when it knows its own case
better than the list (``workflow.errors.PhaseRefusal`` says, per phase, what to
do next).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Refusal:
    """One kind of refusal: its default status, what to tell a person, and
    which interface module clears it (None: the maintainer must)."""

    status: int
    say: str
    fix: str | None


# The closed list. A `say` may name a field the matching rule captures
# ({key}, {file}); everything else is fixed text.
REFUSALS: dict[str, Refusal] = {
    # ── the study and its files (M1, M2) ─────────────────────────────────────
    "invalid_study_id": Refusal(400, (
        "That is not a valid study id. A study is named by its chemical's DTXSID: "
        "“DTXSID” followed by digits, for example DTXSID50469320."), "M1"),
    "no_files": Refusal(404, (
        "This study has no data files yet. Add the study's files first."), "M2"),
    "files_not_recognised": Refusal(400, (
        "None of this study's files has been recognised yet. Add the files and run "
        "the file check, then try again."), "M2"),
    "not_validated": Refusal(400, (
        "The study's files haven't been checked yet. Run the file check "
        "(validation) first, then try again."), "M2"),
    "conflict_choice_missing": Refusal(400, (
        "To settle a conflict between files, choose the file to keep for that "
        "conflict."), "M2"),
    # ── integration and the dataset (M3) ─────────────────────────────────────
    "integration_failed": Refusal(500, (
        "Combining the study's files into one dataset failed. The details say "
        "which file or value it stopped at. Check that file, then integrate again; "
        "if the details don't point at a file, tell the maintainer."), "M3"),
    "not_integrated": Refusal(400, (
        "The study's files haven't been combined into one dataset yet. Finish the "
        "Integrate step first."), "M3"),
    "dataset_invalid": Refusal(422, (
        "The study's combined dataset doesn't have the form the report needs. "
        "Integrate the study again; if that doesn't fix it, tell the maintainer."), "M3"),
    # ── the data review (M6) ─────────────────────────────────────────────────
    "animal_report_failed": Refusal(500, (
        "Accounting for every animal across the files failed. The details say "
        "where it stopped. Check the files it names, then try again; if it fails "
        "again, tell the maintainer."), "M6"),
    # ── Process (P1) ─────────────────────────────────────────────────────────
    "bmd_divergence": Refusal(500, (
        "Some apical benchmark doses computed here differ from the values recorded "
        "in the study's .bm2 files by more than the allowed margin. This is a "
        "problem in the data, not something to fix here, and running Process again "
        "will not change it: send the list of endpoints in the details to the data "
        "team."), "P1"),
    "calculation_program_failed": Refusal(500, (
        "A calculation program failed while processing (the apical BMD modelling or "
        "the genomics export). Results from earlier runs may be partly kept. Tell "
        "the maintainer, with the details below."), None),
    "processing_failed": Refusal(500, (
        "Processing stopped with an error before it finished. The details say what "
        "failed. Try again once the cause is fixed; if the cause isn't clear, tell "
        "the maintainer."), "P1"),
    "content_preparation_failed": Refusal(500, (
        "Writing the report's text from the processed results failed. The details "
        "say what failed; if the cause isn't clear, tell the maintainer."), "P1"),
    "server_setup_failed": Refusal(500, (
        "A program the server needs could not run (Java or the BMDExpress tools). "
        "This is a problem with the server's setup, not with your study, and "
        "nothing you change in the study will fix it. Tell the maintainer."), None),
    # ── sections, approval and the guards (D1) ───────────────────────────────
    "section_not_found": Refusal(404, (
        "There is no saved section “{key}” to approve. Methods, the apical BMD "
        "summary and the genomics interpretations can't be approved at all yet; "
        "the other sections exist only once Process has run."), "D1"),
    "section_key_missing": Refusal(400, (
        "The request didn't say which section it is about. This is a fault in the "
        "interface, not in your study; tell the maintainer."), None),
    "release_reason_required": Refusal(409, (
        "Reopening an approved section needs a reason. Say why you are reopening "
        "it; the reason is kept in the section's history."), "D1"),
    "stale_content": Refusal(409, (
        "This section was written before the study's data changed, so it can't be "
        "marked final or published. Have it brought up to date with the current "
        "data, read it again, then approve it."), "D1"),
    "guard_refused": Refusal(409, (
        "This change to a section was refused to protect content a person owns. "
        "The details say which rule refused it."), "D1"),
    # ── the pins (M5) ────────────────────────────────────────────────────────
    "method_profile_changed": Refusal(409, (
        "The analysis method this study is pinned to (its method profile) was "
        "edited after the study was pinned, and a pinned method must never change. "
        "Pin the study to a method again; tell the maintainer if a profile file was "
        "edited by mistake."), "M5"),
    "method_profile_invalid": Refusal(422, (
        "The analysis method (method profile) named for this study is missing or "
        "not valid. Choose another method profile, and tell the maintainer about "
        "the broken one."), "M5"),
    "definition_pin_changed": Refusal(409, (
        "The saved copy of the document definition this study is fixed to no "
        "longer matches its pin, and a pinned definition must never change. Pin "
        "the study's document definition again; tell the maintainer if the saved "
        "copy was edited by hand."), "M5"),
    "definition_not_pinned": Refusal(409, (
        "This study's document definition is meant to stay fixed, but its saved "
        "copy is missing. Pin the document definition again."), "M5"),
    "definition_pin_invalid": Refusal(400, (
        "A document definition can be pinned in two ways only: fixed (it stays as "
        "it is) or track (it follows the newest definition)."), "M5"),
    # ── the legal-action guard (C1). The exceptions (workflow.errors) carry
    #    the say and fix of their own case; these are the fallbacks. ─────────
    "phase_not_allowed": Refusal(409, (
        "This step isn't available at the study's current stage. The details say "
        "which stage the study is at; do the step that comes before this one first."),
        None),
    "validation_out_of_date": Refusal(409, (
        "The file check is out of date: it no longer matches the study's files as the "
        "server sees them now. This happens after the server restarts, or when files "
        "change outside the app. Nothing was combined and nothing was changed. Run the "
        "file check again, then Integrate."), "M2"),
    "method_not_chosen": Refusal(409, (
        "Choose the analysis method (the method profile) this study is reported under "
        "before processing. Every statistic, benchmark dose and the Methods text depend "
        "on it, so it is never chosen for you."), "M5"),
    # ── anything else ────────────────────────────────────────────────────────
    "damaged_session_file": Refusal(422, (
        "One of this study's saved files is damaged and can't be read ({file}). "
        "Nothing was changed. Tell the maintainer: the file must be repaired or "
        "restored before work on this study can go on."), None),
    "bad_request": Refusal(422, (
        "The request was malformed. This is a fault in the interface, not in your "
        "study; tell the maintainer."), None),
    "unexpected": Refusal(500, (
        "The application hit an error it has no explanation for. Tell the "
        "maintainer, with the details below."), None),
}


# (exception class name, message pattern, code), first match wins. Class names,
# not classes, so this module imports nothing heavy; a subclass matches by any
# name in its MRO. Patterns are searched, not anchored, and quote the backend's
# messages (workflow/steps.py, pipeline/process_integrated.py, workflow/labels.py,
# workflow/currency.py, pipeline/method_profile.py, document_model/definition_pin.py).
_SETUP_PATTERN = (r"UnsupportedClassVersionError|BMDX_PROJECT_ROOT|JAVA_HOME|"
                  r"No such file or directory: '?java|java: (?:command )?not found|"
                  r"Could not find or load main class")
_MESSAGE_RULES: tuple[tuple[str, str, str], ...] = (
    # StepError (data §3.1, Process §6.1, document §9.1)
    ("StepError", r"apical BMD endpoint\(s\) diverge", "bmd_divergence"),
    ("StepError", r"^(?:Integration|Processing|Animal report generation) failed: .*(?:"
     + _SETUP_PATTERN + ")", "server_setup_failed"),
    ("StepError", r"^No files directory found", "no_files"),
    ("StepError", r"^dtxsid, issue_index, and chosen_file_id are required", "conflict_choice_missing"),
    ("StepError", r"^No fingerprints found", "not_validated"),
    ("StepError", r"^No coverage matrix found", "not_validated"),
    ("StepError", r"^Integration failed:", "integration_failed"),
    ("StepError", r"^No fingerprinted files found", "files_not_recognised"),
    ("StepError", r"^Animal report generation failed:", "animal_report_failed"),
    ("StepError", r"^No integrated data found", "not_integrated"),
    ("StepError", r"^Processing failed: .*(?:RunApicalBmds|ExportGenomics)", "calculation_program_failed"),
    ("StepError", r"^Processing failed:", "processing_failed"),
    ("StepError", r"^Content preparation failed:", "content_preparation_failed"),
    ("StepError", r"^No '(?P<key>[^']*)' section to approve", "section_not_found"),
    ("StepError", r"^dtxsid and section_key are required", "section_key_missing"),
    # GuardViolation (workflow/labels.py, workflow/currency.py)
    ("GuardViolation", r"requires a recorded reason", "release_reason_required"),
    ("GuardViolation", r"currency BLOCK", "stale_content"),
    ("GuardViolation", r"", "guard_refused"),
    # MethodProfileError (pipeline/method_profile.py)
    ("MethodProfileError", r"changed since it was pinned", "method_profile_changed"),
    ("MethodProfileError", r"", "method_profile_invalid"),
    # DefinitionPinError (document_model/definition_pin.py)
    ("DefinitionPinError", r"no longer matches its pin", "definition_pin_changed"),
    ("DefinitionPinError", r"no pinned document definition", "definition_not_pinned"),
    ("DefinitionPinError", r"^mode must be one of", "definition_pin_invalid"),
    ("DefinitionPinError", r"", "unexpected"),
    # The id gate, the damaged file and the dataset barrier
    ("InvalidDtxsid", r"", "invalid_study_id"),
    ("UnreadableSessionFile", r"", "damaged_session_file"),
    ("BMDProjectValidationError", r"", "dataset_invalid"),
    # A request the route could not parse (FastAPI's own validation)
    ("RequestValidationError", r"", "bad_request"),
)


def _class_names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


def _details(exc: BaseException, code: str) -> dict:
    """What the interface may show beside the message: the damaged file's name,
    a request's field errors."""
    if code == "damaged_session_file":
        path = getattr(exc, "path", None)
        return {"file": f"{path.parent.name}/{path.name}"} if path is not None else {}
    if code == "bad_request" and hasattr(exc, "errors"):
        try:
            return {"errors": [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")}
                               for e in exc.errors()]}
        except Exception:  # noqa: BLE001 — details are a courtesy, never a second failure
            return {}
    own = getattr(exc, "details", None)
    if getattr(exc, "code", None) == code and isinstance(own, dict):
        return dict(own)  # a refusal of the workflow's own says what to show
    if code == "phase_not_allowed":
        return {k: getattr(exc, k) for k in ("phase", "legal_actions") if hasattr(exc, k)}
    return {}


def classify(exc: BaseException) -> tuple[str, dict]:
    """(code, captured fields) for an exception: its own ``code`` when it
    carries a listed one, else the first matching rule, else ``unexpected``."""
    own = getattr(exc, "code", None)
    if isinstance(own, str) and own in REFUSALS:
        return own, {}
    names = _class_names(exc)
    message = _message(exc)
    for cls_name, pattern, code in _MESSAGE_RULES:
        if cls_name in names:
            m = re.search(pattern, message, re.S)
            if m:
                return code, m.groupdict()
    return "unexpected", {}


def _message(exc: BaseException) -> str:
    """The backend's own text, verbatim (StepError keeps it on ``message``)."""
    message = getattr(exc, "message", None)
    if isinstance(message, str):
        return message
    if "RequestValidationError" in _class_names(exc):
        return "The request did not match what this endpoint takes."
    return str(exc) or type(exc).__name__


# What a `say` shows when its rule captured nothing for a field (a refusal that
# named its own code, say).
_FIELD_DEFAULTS = {"key": "this", "file": "the details name it"}


class _Fields(dict):
    def __missing__(self, name: str) -> str:
        return _FIELD_DEFAULTS.get(name, "")


def explain(exc: BaseException) -> dict:
    """The error envelope for an exception (see the module docstring)."""
    code, fields = classify(exc)
    refusal = REFUSALS[code]
    names = _class_names(exc)
    # Only a refusal of the workflow's own carries a status meant for the
    # client; any other exception's `status_code` (an upstream HTTP client's,
    # say) is not this request's.
    status = getattr(exc, "status_code", None) if ("StepError" in names or
                                                   getattr(exc, "code", None) == code) else None
    if not isinstance(status, int) or not 400 <= status <= 599:
        status = refusal.status
    details = _details(exc, code)
    say = refusal.say.format_map(_Fields({**details, **{k: v for k, v in fields.items() if v}}))
    fix = refusal.fix
    if getattr(exc, "code", None) == code:
        # A refusal that knows its own case (C1's phase guard: per phase) says so.
        own_say, own_fix = getattr(exc, "say", None), getattr(exc, "fix", None)
        say = own_say if isinstance(own_say, str) and own_say else say
        fix = own_fix if isinstance(own_fix, str) and own_fix else fix
    message = _message(exc)
    if code == "unexpected" and not isinstance(getattr(exc, "message", None), str):
        message = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return {"error": {"code": code, "status": status, "message": message,
                      "say": say, "fix": fix, "details": details}}
