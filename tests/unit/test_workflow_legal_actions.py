"""
Unit test for the settled-phase Action model (ADR-0014, step 1; C1).

Pins the LEGAL_ACTIONS table that UIs consume instead of re-deriving button
enablement. Since C1 the table is the workflow's own declared table of acts
(C1 spec §1), typed directly in workflow/phases.py and enforced by every
mutating step; it is no longer a transcription of the old screen's buttons.
Transient phases (VALIDATING/INTEGRATING/APPROVING) must NOT appear — they are
per-UI async presentation states.
"""

import pytest

from workflow.phases import (
    LEGAL_ACTIONS,
    Action,
    Phase,
    derive_phase,
    is_legal,
)

# Expected legal actions per settled phase (C1 spec §1, signed 2026-10-15).
_FILES = {Action.ADD_FILES, Action.REMOVE_FILE, Action.RESET, Action.VALIDATE}
_CHOICES = {Action.RESOLVE, Action.CONFIRM_CLASSIFICATION}
_EXPECTED = {
    Phase.EMPTY: {Action.ADD_FILES},
    Phase.UPLOADED: _FILES,
    Phase.VALIDATION_ERRORS: _FILES | _CHOICES,
    Phase.VALIDATED: _FILES | _CHOICES | {Action.INTEGRATE},
    Phase.INTEGRATED: set(Action),
    Phase.APPROVED: set(Action),
}


def test_the_ten_acts_by_their_wire_values():
    # D3: REPROCESS is PROCESS (it is also the first Process); CLEAR_FILES is RESET.
    assert {a.value for a in Action} == {
        "ADD_FILES", "REMOVE_FILE", "RESET", "VALIDATE", "RESOLVE",
        "CONFIRM_CLASSIFICATION", "INTEGRATE", "STATE_DATASET_FACTS", "APPROVE", "PROCESS"}


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
    assert is_legal("APPROVED", "PROCESS") is True
    assert is_legal("INTEGRATED", "PROCESS") is True
    assert is_legal("VALIDATED", "PROCESS") is False


def test_unknown_phase_or_action_raises():
    with pytest.raises(ValueError):
        is_legal("NOPE", "VALIDATE")
    with pytest.raises(ValueError):
        is_legal("UPLOADED", "NOPE")
    with pytest.raises(ValueError):           # the retired wire values
        is_legal("APPROVED", "REPROCESS")
    with pytest.raises(ValueError):
        is_legal("UPLOADED", "CLEAR_FILES")


def test_next_step_names_a_legal_act_for_every_refusing_phase():
    from workflow.phases import NEXT_STEP
    assert set(NEXT_STEP) == {Phase.EMPTY, Phase.UPLOADED, Phase.VALIDATION_ERRORS,
                              Phase.VALIDATED}
    for phase, action in NEXT_STEP.items():
        assert action in LEGAL_ACTIONS[phase], phase
