"""
safeguards.refusals — every refusal the application can give, in plain words.

A step that cannot proceed raises (``StepError``, ``GuardViolation``, a pin
error, a bad id, a damaged session file, or one of the safeguards' own
refusals below). What the person needs is not the exception but three things:
what happened, in their terms; what to do about it; and where in the workflow
it is cleared. This module is the one place that maps a refusal to those, so
the browser and the command line explain it the same way:

    {"error": {"code": "not_validated", "status": 400,
               "message": "No fingerprints found -- run validation first",
               "say": "The study's files haven't been checked yet. …",
               "fix": "files", "details": {}}}

* ``code`` comes from the closed list ``REFUSALS``; a refusal the list does not
  know is ``unexpected``, never a guess at a nearer one.
* ``message`` is the backend's own text, verbatim. ``say`` is written here,
  next to the code.
* ``fix`` names the place in the workflow where the cause is cleared
  (``PLACES``), or None when nothing a person does there clears it (tell the
  maintainer). A front end maps a place to its own screen.
* ``status`` is the backend's advisory status where it gives one (StepError),
  else the code's own.

Core refusals carry no plain words; most are recognised by their message
(``_MESSAGE_RULES``). An exception that carries a ``code`` attribute naming a
listed code is taken at its word, and so are the ``say``, ``fix`` and
``details`` it carries when it knows its own case better than the list (the
phase guard's ``PhaseRefusal`` says, per phase, what to do next).

The refusals the safeguards raise themselves are defined here too:
``PhaseRefusal`` and ``MethodNotChosen`` (C1), ``StudyRefusal`` (R6).
Ported from the UI team's ``workflow.refusals`` / ``workflow.errors``
(ui-redesign), without the codes of its study-creation module.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from workflow.errors import StepError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Refusal:
    """One kind of refusal: its default status, what to tell a person, and
    where in the workflow it is cleared (``PLACES``; None: the maintainer must)."""

    status: int
    say: str
    fix: str | None


# The places in the workflow where a refusal's cause is cleared (a refusal's
# ``fix``). A front end maps each to its own screen.
PLACES = {
    "study": "the study itself (which study, its identity)",
    "files": "the study's files and the file check",
    "dataset": "combining the files into one dataset (Integrate)",
    "data_review": "the data review (every animal accounted for)",
    "method_and_document": "the analysis method and the document definition the study is pinned to",
    "process": "Process",
    "sections": "the report's sections (accept, reopen, restore)",
    "facts": "the facts a person states about the study (design, experiment details)",
    "publish": "the report's readiness to publish",
}


# The closed list. A `say` may name a field the matching rule captures
# ({key}, {file}); everything else is fixed text.
REFUSALS: dict[str, Refusal] = {
    # ── the study and its files ──────────────────────────────────────────────
    "invalid_study_id": Refusal(400, (
        "That is not a valid study id. A study is named by its chemical's DTXSID: "
        "“DTXSID” followed by digits, for example DTXSID50469320."), "study"),
    "read_only_session": Refusal(409, (
        "This is the published book's own content, made by a tool. It can't be changed "
        "or deleted here."), None),
    "report_has_no_data": Refusal(409, (
        "This is a report over several studies: it has no files or data of its own. "
        "Its data is prepared in each of its studies; open one of them."), "study"),
    "no_files": Refusal(404, (
        "This study has no data files yet. Add the study's files first."), "files"),
    "files_not_recognised": Refusal(400, (
        "None of this study's files has been recognised yet. Add the files and run "
        "the file check, then try again."), "files"),
    "not_validated": Refusal(400, (
        "The study's files haven't been checked yet. Run the file check "
        "(validation) first, then try again."), "files"),
    "conflict_choice_missing": Refusal(400, (
        "To settle a conflict between files, choose the file to keep for that "
        "conflict."), "files"),
    # ── integration and the dataset ──────────────────────────────────────────
    "integration_failed": Refusal(500, (
        "Combining the study's files into one dataset failed. The details say "
        "which file or value it stopped at. Check that file, then integrate again; "
        "if the details don't point at a file, tell the maintainer."), "dataset"),
    "not_integrated": Refusal(400, (
        "The study's files haven't been combined into one dataset yet. Finish the "
        "Integrate step first."), "dataset"),
    "dataset_invalid": Refusal(422, (
        "The study's combined dataset doesn't have the form the report needs. "
        "Integrate the study again; if that doesn't fix it, tell the maintainer."), "dataset"),
    # ── the data review ──────────────────────────────────────────────────────
    "animal_report_failed": Refusal(500, (
        "Accounting for every animal across the files failed. The details say "
        "where it stopped. Check the files it names, then try again; if it fails "
        "again, tell the maintainer."), "data_review"),
    # ── Process ──────────────────────────────────────────────────────────────
    "bmd_divergence": Refusal(500, (
        "Some apical benchmark doses computed here differ from the values recorded "
        "in the study's .bm2 files by more than the allowed margin. This is a "
        "problem in the data, not something to fix here, and running Process again "
        "will not change it: send the list of endpoints in the details to the data "
        "team."), "process"),
    "calculation_program_failed": Refusal(500, (
        "A calculation program failed while processing (the apical BMD modelling or "
        "the genomics export). Results from earlier runs may be partly kept. Tell "
        "the maintainer, with the details below."), None),
    "processing_failed": Refusal(500, (
        "Processing stopped with an error before it finished. The details say what "
        "failed. Try again once the cause is fixed; if the cause isn't clear, tell "
        "the maintainer."), "process"),
    "content_preparation_failed": Refusal(500, (
        "Writing the report's text from the processed results failed. The details "
        "say what failed; if the cause isn't clear, tell the maintainer."), "process"),
    "server_setup_failed": Refusal(500, (
        "A program the server needs could not run (Java or the BMDExpress tools). "
        "This is a problem with the server's setup, not with your study, and "
        "nothing you change in the study will fix it. Tell the maintainer."), None),
    # ── sections, approval and the guards ────────────────────────────────────
    "section_not_found": Refusal(404, (
        "There is no saved section “{key}”, so there is nothing to {act}. Methods, "
        "the apical BMD summary and the genomics interpretations are not saved as "
        "sections yet, so they can't be approved; the other sections exist only "
        "once Process has run."), "sections"),
    "section_key_missing": Refusal(400, (
        "The request didn't say which section it is about. This is a fault in the "
        "interface, not in your study; tell the maintainer."), None),
    "release_reason_required": Refusal(409, (
        "Reopening an approved section needs a reason. Say why you are reopening "
        "it; the reason is kept in the section's history."), "sections"),
    "stale_content": Refusal(409, (
        "This section was written before the study's data changed, so it can't be "
        "marked final or published. Have it brought up to date with the current "
        "data, read it again, then approve it."), "sections"),
    "guard_refused": Refusal(409, (
        "This change to a section was refused to protect content a person owns. "
        "The details say which rule refused it."), "sections"),
    # ── owned content (C2): the section write gate and the section steps ─────
    "section_owned": Refusal(409, (
        "This section has been approved, or you chose to keep it, so it can't be "
        "replaced automatically. To replace it, reopen it and say why."), "sections"),
    "section_key_invalid": Refusal(400, (
        "There is no section by that name in this report."), "sections"),
    "reason_required": Refusal(400, (
        "Please say why. The reason is kept with the section's history."), "sections"),
    "version_not_found": Refusal(404, (
        "That version of the section doesn't exist."), "sections"),
    "version_content_missing": Refusal(409, (
        "This version is listed in the history, but its text was lost before history "
        "was kept reliably. It can't be restored."), None),
    "approve_content_retired": Refusal(409, (
        "Approving can't change the text. Accept the section as it is, or edit it in "
        "Word or Overleaf and bring that version back."), "sections"),
    "approve_via_accept": Refusal(400, (
        "Saving doesn't approve. Use Accept."), "sections"),
    # ── the pins ─────────────────────────────────────────────────────────────
    "method_profile_changed": Refusal(409, (
        "The analysis method this study is pinned to (its method profile) was "
        "edited after the study was pinned, and a pinned method must never change. "
        "Pin the study to a method again; tell the maintainer if a profile file was "
        "edited by mistake."), "method_and_document"),
    "method_profile_invalid": Refusal(422, (
        "The analysis method (method profile) named for this study is missing or "
        "not valid. Choose another method profile, and tell the maintainer about "
        "the broken one."), "method_and_document"),
    "definition_pin_changed": Refusal(409, (
        "The saved copy of the document definition this study is fixed to no "
        "longer matches its pin, and a pinned definition must never change. Pin "
        "the study's document definition again; tell the maintainer if the saved "
        "copy was edited by hand."), "method_and_document"),
    "definition_not_pinned": Refusal(409, (
        "This study's document definition is meant to stay fixed, but its saved "
        "copy is missing. Pin the document definition again."), "method_and_document"),
    "definition_pin_invalid": Refusal(400, (
        "A document definition can be pinned in two ways only: fixed (it stays as "
        "it is) or track (it follows the newest definition)."), "method_and_document"),
    # ── the legal-action guard (C1). The refusals below carry the say and
    #    fix of their own case; these are the fallbacks. ─────────────────────
    "phase_not_allowed": Refusal(409, (
        "This step isn't available at the study's current stage. The details say "
        "which stage the study is at; do the step that comes before this one first."),
        None),
    "validation_out_of_date": Refusal(409, (
        "The file check is out of date: it no longer matches the study's files as the "
        "server sees them now. This happens after the server restarts, or when files "
        "change outside the app. Nothing was combined and nothing was changed. Run the "
        "file check again, then Integrate."), "files"),
    "method_not_chosen": Refusal(409, (
        "Choose the analysis method (the method profile) this study is reported under "
        "before processing. Every statistic, benchmark dose and the Methods text depend "
        "on it, so it is never chosen for you."), "method_and_document"),
    # ── the data policy ──────────────────────────────────────────────────────
    "llm_egress_blocked": Refusal(503, (
        "The language model this needs is not one the study's data may be sent to "
        "(only the NIEHS gateway is allowed). Nothing was sent. Tell the maintainer: "
        "the server's model settings must point at the allowed gateway."), None),
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
    ("StepError", r"^No '(?P<key>[^']*)' section to (?P<act>\w+)", "section_not_found"),
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
    # The LLM egress guard (styling_export/llm_endpoints.py)
    ("LLMEgressBlocked", r"", "llm_egress_blocked"),
    # A request the route could not parse (FastAPI's own validation)
    ("RequestValidationError", r"", "bad_request"),
)


def _class_names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


def _details(exc: BaseException, code: str) -> dict:
    """What the interface may show beside the message: the damaged file's name,
    a request's field errors, or what a refusal naming its own code carries
    (``details``: the study id, the parent report …)."""
    own = getattr(exc, "details", None)
    if isinstance(own, dict) and getattr(exc, "code", None) == code:
        return dict(own)
    if code == "damaged_session_file":
        path = getattr(exc, "path", None)
        return {"file": f"{path.parent.name}/{path.name}"} if path is not None else {}
    if code == "bad_request" and hasattr(exc, "errors"):
        try:
            return {"errors": [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")}
                               for e in exc.errors()]}
        except Exception:  # noqa: BLE001 — details are a courtesy, never a second failure
            return {}
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
_FIELD_DEFAULTS = {"key": "this", "file": "the details name it", "act": "approve",
                   "id": "with this id", "service": "the lookup service", "species": "member",
                   "parent": "it belongs to", "time": "a time not recorded"}


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


# ---------------------------------------------------------------------------
# C1: the refusals of the legal-action guard. Each carries its own `code`
# (explain() takes it at its word), the plain-words `say` and the place that
# clears it (`fix`, a PLACES key), and the `details` a screen shows.
# ---------------------------------------------------------------------------

# How a refused act is named to a person ({Act} in the say).
_ACT_SAY = {
    "ADD_FILES": "Adding files",
    "REMOVE_FILE": "Removing a file",
    "RESET": "Clearing the study's files",
    "VALIDATE": "Checking the files",
    "RESOLVE": "Choosing between conflicting files",
    "CONFIRM_CLASSIFICATION": "Correcting what a file is",
    "INTEGRATE": "Combining the files into one dataset",
    "STATE_DATASET_FACTS": "Stating the study design or the experiment details",
    "APPROVE": "Approving the data",
    "PROCESS": "Processing",
}

# Per refusing state: (the message's next step, the say's second sentence, fix).
# "VALIDATED_OUT_OF_DATE" is VALIDATED with an integration built from another
# validation (workflow.integration_basis). INTEGRATED and APPROVED never refuse.
_PHASE_REFUSAL = {
    "EMPTY": (
        "Add the study's files first.",
        "This study has no data files yet. Add the study's files first.", "files"),
    "UPLOADED": (
        "Validate the files first.",
        "The study's files have changed since they were last checked, or were never "
        "checked. Run the file check first.", "files"),
    "VALIDATION_ERRORS": (
        "Fix the validation errors, then validate again.",
        "The file check found errors. Fix what it lists (remove or replace the files it "
        "names), then run the file check again.", "files"),
    "VALIDATED": (
        "Integrate first.",
        "The study's files have been checked but not yet combined into one dataset. "
        "Integrate the study first.", "dataset"),
    "VALIDATED_OUT_OF_DATE": (
        "Its integration was built from a different validation; integrate again.",
        "The study's dataset was combined from an earlier file check that no longer "
        "matches its files. Integrate the study again first.", "dataset"),
}
_NO_FILES_TO_REMOVE = "This study has no files to remove."


class PhaseRefusal(StepError):
    """An act outside the legal actions of the study's derived phase
    (workflow.phases.LEGAL_ACTIONS), raised by safeguards.acts.require before
    the step reads or writes anything."""

    code = "phase_not_allowed"

    def __init__(self, dtxsid: str, action: str, phase: str, legal_actions,
                 integration: str | None = None, next_action: str | None = None):
        self.action, self.phase = action, phase
        self.legal_actions = sorted(legal_actions)
        self.integration, self.next_action = integration, next_action
        state = ("VALIDATED_OUT_OF_DATE" if phase == "VALIDATED" and integration == "out_of_date"
                 else phase)
        nxt, phase_say, self.fix = _PHASE_REFUSAL.get(state, ("", "", None))
        if phase == "EMPTY" and action in ("REMOVE_FILE", "RESET"):
            self.say = _NO_FILES_TO_REMOVE
        else:
            self.say = f"{_ACT_SAY.get(action, action)} isn't possible yet. {phase_say}".strip()
        legal = ", ".join(self.legal_actions) or "nothing"
        super().__init__(
            f"{action} refused for {dtxsid}: the study is in phase {phase} "
            f"(allowed now: {legal}). {nxt}".strip(), status_code=409)
        self.details = {"action": action, "phase": phase, "legal_actions": self.legal_actions,
                        "integration": integration, "next_action": next_action}


class MethodNotChosen(StepError):
    """Process refused: no person has chosen the study's method profile (C1 D1,
    option B). A front end suggests one (pipeline.method_profile.suggest_profile);
    a person confirms it. Never chosen for them."""

    code = "method_not_chosen"

    def __init__(self, dtxsid: str, pin: dict | None):
        how = "absent" if not pin else "pinned by default"
        self.details = {"pin": None if not pin else {
            k: pin.get(k) for k in ("name", "pinned_by", "mode")}}
        if pin:
            # An older session whose profile was set automatically.
            self.say = (
                "Choose the analysis method (the method profile) this study is reported "
                f"under before processing. The one it has now ({pin.get('name')}) was set "
                "automatically, not chosen by a person, so it must be confirmed or changed. "
                "Every statistic, benchmark dose and the Methods text depend on it, so it "
                "is never chosen for you.")
        super().__init__(
            f"PROCESS refused for {dtxsid}: no method profile has been chosen "
            f"(method_profile.json is {how}). Pin one, then process.", status_code=409)


class StudyRefusal(StepError):
    """R6: a data act refused on a session whose data is not its own
    (``read_only_session``, ``report_has_no_data``). ``details`` fills the
    plain words."""

    def __init__(self, code: str, message: str, status_code: int, details: dict | None = None):
        super().__init__(message, status_code=status_code)
        self.code = code
        self.details = details or {}


def error_body(exc: BaseException) -> tuple[dict, int]:
    """(JSON body, HTTP status) for a refusal: the application's usual
    ``{"error": message}`` with the explanation beside it (``code``, ``say``,
    ``fix``, ``details``), so a client that reads only ``error`` keeps working."""
    e = explain(exc)["error"]
    return ({"error": e["message"], "code": e["code"], "say": e["say"], "fix": e["fix"],
             "details": e["details"]}, e["status"])
