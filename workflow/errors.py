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


# A core refusal, raised for every caller (the notebook included): combining
# files under a validation that no longer matches them would build a wrong
# dataset. It carries its `code`; safeguards.refusals explains it.
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
