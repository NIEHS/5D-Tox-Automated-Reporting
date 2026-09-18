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

