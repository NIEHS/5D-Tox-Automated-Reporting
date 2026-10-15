"""
workflow.errors — HTTP-free failure signalling for workflow steps.

Step functions in `workflow/steps.py` must not know about FastAPI. When a step
cannot proceed (missing files, un-validated pool, etc.) it raises `StepError`
carrying a human-readable message and the HTTP status a web front-end should use.
Route handlers catch it and translate; a TUI or test would inspect the same
fields. The `status_code` is advisory metadata, not an HTTP dependency.
"""

from __future__ import annotations


class StepError(Exception):
    """A step could not complete. Carries a message + advisory HTTP status.

    status_code convention mirrors the pre-unwrap handlers:
      400 — caller must do something first (validate, upload)
      404 — the session/resource does not exist
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class GuardViolation(Exception):
    """A label transition was refused because it moves against the guard without
    the deliberate release the ratchet requires (ADR-0015):

      * demoting a fact without a DemoteReason (against-guard, unrecorded), or
      * advancing stale content to final/published (currency BLOCK — kind #6).

    This is the enforcement half of "enforce against actors that can't reason":
    the mechanism refuses; a human-with-rights uses the recorded override path
    (a demote with reason) instead.
    """



# ---------------------------------------------------------------------------
# C1: the refusals of the legal-action guard. Each carries its own `code`
# (workflow.refusals takes it at its word), the plain-words `say` and the
# interface module that clears it (`fix`), and the `details` a screen shows.
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
        "This study has no data files yet. Add the study's files first.", "M2"),
    "UPLOADED": (
        "Validate the files first.",
        "The study's files have changed since they were last checked, or were never "
        "checked. Run the file check first.", "M2"),
    "VALIDATION_ERRORS": (
        "Fix the validation errors, then validate again.",
        "The file check found errors. Fix what it lists (remove or replace the files it "
        "names), then run the file check again.", "M2"),
    "VALIDATED": (
        "Integrate first.",
        "The study's files have been checked but not yet combined into one dataset. "
        "Integrate the study first.", "M3"),
    "VALIDATED_OUT_OF_DATE": (
        "Its integration was built from a different validation; integrate again.",
        "The study's dataset was combined from an earlier file check that no longer "
        "matches its files. Integrate the study again first.", "M3"),
}
_NO_FILES_TO_REMOVE = "This study has no files to remove."


class PhaseRefusal(StepError):
    """An action outside the legal actions of the study's derived phase
    (workflow.phases.LEGAL_ACTIONS), raised by workflow.engine.require_legal
    before the step reads or writes anything."""

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


class ValidationOutOfDate(StepError):
    """Integration refused: the validation report it would pair with the
    fingerprints no longer matches the files the server holds (the restart
    trap: file ids re-minted by a cold re-scan). Nothing is combined."""

    code = "validation_out_of_date"

    def __init__(self, dtxsid: str, missing_ids: int, added: list, missing: list):
        self.details = {"missing_ids": missing_ids, "added": sorted(added),
                        "missing": sorted(missing)}
        parts = []
        if missing_ids:
            parts.append(f"{missing_ids} file id(s) in its coverage matrix are not among "
                         f"the current fingerprints")
        if added:
            parts.append(f"files added since validation: {', '.join(sorted(added))}")
        if missing:
            parts.append(f"files missing since validation: {', '.join(sorted(missing))}")
        super().__init__(
            f"INTEGRATE refused for {dtxsid}: the validation report no longer matches the "
            f"files the server holds ({'; '.join(parts)}). Validate again, then integrate.",
            status_code=409)


class MethodNotChosen(StepError):
    """Process refused: no person has chosen the study's method profile (C1 D1,
    option B). The interface suggests one (pipeline.method_profile.suggest_profile);
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
