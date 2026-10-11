"""
Unit test for the settled-phase Action model (ADR-0014, step 1).

Pins the LEGAL_ACTIONS table that UIs consume instead of re-deriving button
enablement. The table is DERIVED from _PHASE_BUTTON_STATE (a faithful
transcription of POOL_PHASES visible+enabled flags), so this test guards both
the transcription and the derivation. Transient phases (VALIDATING/INTEGRATING/
APPROVING) must NOT appear — they are per-UI async presentation states.
"""

import pytest

from workflow.phases import (
    LEGAL_ACTIONS,
    Action,
    Phase,
    derive_phase,
    is_legal,
)

# Expected legal actions per settled phase, read straight off POOL_PHASES
# (web/js/pool_state.js): an action is legal iff its button is visible AND enabled.
_EXPECTED = {
    Phase.EMPTY: set(),
    Phase.UPLOADED: {Action.VALIDATE, Action.CLEAR_FILES},
    Phase.VALIDATION_ERRORS: {Action.VALIDATE, Action.RESET},
    Phase.VALIDATED: {Action.INTEGRATE, Action.RESET},
    Phase.INTEGRATED: {Action.VALIDATE, Action.APPROVE, Action.REPROCESS, Action.RESET},
    Phase.APPROVED: {Action.REPROCESS, Action.RESET},
}


def test_legal_actions_derivation():
    assert {p: set(a) for p, a in LEGAL_ACTIONS.items()} == _EXPECTED


def test_no_transient_phases_leak_into_core():
    # The six settled phases only — the JS transient trio must be absent.
    assert set(LEGAL_ACTIONS) == set(Phase)
    for forbidden in ("VALIDATING", "INTEGRATING", "APPROVING"):
        assert forbidden not in {p.value for p in Phase}


def test_derive_phase_only_returns_settled_phases():
    # Every phase derive_phase can emit must be a member of the Phase enum.
    settled = {p.value for p in Phase}
    samples = [
        {"hasFiles": False},
        {"hasFiles": True},
        {"hasFiles": True, "hasStale": True},
        {"hasFiles": True, "validationReport": {"issues": [{"severity": "error"}]},
         "hasValidationErrors": True},
        {"hasFiles": True, "validationReport": {"issues": []}},
        {"hasFiles": True, "validationReport": {"issues": []}, "hasIntegrated": True},
        {"hasFiles": True, "validationReport": {"issues": []}, "hasIntegrated": True,
         "hasAnimalReport": True},
    ]
    for artifacts in samples:
        assert derive_phase(artifacts) in settled


def test_is_legal_accepts_enums_and_strings():
    assert is_legal(Phase.UPLOADED, Action.VALIDATE) is True
    assert is_legal("UPLOADED", "VALIDATE") is True
    assert is_legal("EMPTY", "VALIDATE") is False
    assert is_legal("APPROVED", "REPROCESS") is True


def test_unknown_phase_or_action_raises():
    with pytest.raises(ValueError):
        is_legal("NOPE", "VALIDATE")
    with pytest.raises(ValueError):
        is_legal("UPLOADED", "NOPE")
