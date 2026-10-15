"""
C1: legal actions are enforced (docs/ui-redesign/modules/c1/spec.md).

Every mutating step derives the study's phase first and refuses an act its
phase does not allow (`workflow.engine.require_legal` → `PhaseRefusal`, 409
``phase_not_allowed``), before it reads or writes anything else. These tests
pin the guard with an in-memory store: the refusal's fields per phase, its
plain words through the error envelope (workflow.refusals), and, over the
inventory of every mutating entry point (spec §2.2), that each one refuses out
of phase and writes nothing.
"""

from __future__ import annotations

import pytest

from workflow.engine import WorkflowEngine, require_legal
from workflow.errors import PhaseRefusal, StepError
from workflow.phases import LEGAL_ACTIONS, Action, Phase
from workflow.refusals import explain


class PhaseStore:
    """A PoolStore double seeded at a phase: only what `gather_artifacts`
    reads. Records every write so a refusal can be shown to write nothing."""

    def __init__(self, phase: str, tmp_path=None, *, docs=None):
        self.phase = phase
        self._docs = dict(docs or {})
        self.writes: list = []
        self._dir = tmp_path
        flags = {
            "EMPTY": (False, None, set()),
            "UPLOADED": (True, None, set()),
            "VALIDATION_ERRORS": (True, {"issues": [{"severity": "error"}], "coverage_matrix": {}}, set()),
            "VALIDATED": (True, {"issues": [], "coverage_matrix": {}}, set()),
            "INTEGRATED": (True, {"issues": [], "coverage_matrix": {}}, {"integrated.json"}),
            "APPROVED": (True, {"issues": [], "coverage_matrix": {}},
                         {"integrated.json", "animal_report.json"}),
        }[phase]
        self._files, report, self._present = flags
        if report is not None:
            self._docs.setdefault("validation_report.json", report)

    def session_dir(self, dtxsid):
        return self._dir

    def has_files(self, dtxsid):
        return self._files

    def has_stale_sections(self, dtxsid):
        return False

    def artifact_exists(self, dtxsid, name):
        return name in self._present

    def read_json(self, dtxsid, name):
        return self._docs.get(name)

    def write_json(self, dtxsid, name, data):
        self.writes.append(name)
        self._docs[name] = data

    def save_section(self, dtxsid, key, data, archive=True):
        self.writes.append(key)

    def get_fingerprints(self, dtxsid):
        return {}

    def ensure_fingerprints(self, dtxsid, force=False):
        self.writes.append("_fingerprints(scan)")
        return {}

    def set_fingerprints(self, dtxsid, fps):
        self.writes.append("_fingerprints(set)")

    def get_integrated(self, dtxsid):
        return None

    def set_integrated(self, dtxsid, data):
        self.writes.append("integrated(set)")


_PHASES = [p.value for p in Phase]


# ---------------------------------------------------------------------------
# The guard and its refusal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phase", _PHASES)
@pytest.mark.parametrize("action", [a.value for a in Action])
def test_require_refuses_exactly_what_the_table_refuses(phase, action):
    store = PhaseStore(phase)
    legal = Action(action) in LEGAL_ACTIONS[Phase(phase)]
    if legal:
        assert require_legal("DTX", action, store).phase.value == phase
    else:
        with pytest.raises(PhaseRefusal):
            require_legal("DTX", action, store)


def test_require_returns_the_state_it_derived():
    st = WorkflowEngine("DTX", PhaseStore("APPROVED")).require(Action.PROCESS)
    assert st.phase is Phase.APPROVED
    assert Action.PROCESS in st.legal_actions


def test_the_refusal_names_the_phase_the_legal_acts_and_the_next_step():
    with pytest.raises(PhaseRefusal) as ei:
        require_legal("DTXSID1", "PROCESS", PhaseStore("VALIDATED"))
    exc = ei.value
    assert isinstance(exc, StepError) and exc.status_code == 409
    assert exc.message == (
        "PROCESS refused for DTXSID1: the study is in phase VALIDATED (allowed now: "
        "ADD_FILES, CONFIRM_CLASSIFICATION, INTEGRATE, REMOVE_FILE, RESET, RESOLVE, "
        "VALIDATE). Integrate first.")
    assert exc.details == {
        "action": "PROCESS", "phase": "VALIDATED",
        "legal_actions": ["ADD_FILES", "CONFIRM_CLASSIFICATION", "INTEGRATE", "REMOVE_FILE",
                          "RESET", "RESOLVE", "VALIDATE"],
        "integration": None, "next_action": "INTEGRATE"}


# (phase, action) → the envelope's say and fix (contract §1.1).
_SAYS = [
    ("EMPTY", "VALIDATE",
     "Checking the files isn't possible yet. This study has no data files yet. Add the "
     "study's files first.", "M2"),
    ("EMPTY", "RESET", "This study has no files to remove.", "M2"),
    ("EMPTY", "REMOVE_FILE", "This study has no files to remove.", "M2"),
    ("UPLOADED", "INTEGRATE",
     "Combining the files into one dataset isn't possible yet. The study's files have "
     "changed since they were last checked, or were never checked. Run the file check "
     "first.", "M2"),
    ("VALIDATION_ERRORS", "PROCESS",
     "Processing isn't possible yet. The file check found errors. Fix what it lists "
     "(remove or replace the files it names), then run the file check again.", "M2"),
    ("VALIDATED", "APPROVE",
     "Approving the data isn't possible yet. The study's files have been checked but not "
     "yet combined into one dataset. Integrate the study first.", "M3"),
]


@pytest.mark.parametrize("phase,action,say,fix", _SAYS)
def test_the_envelope_says_per_phase_what_to_do(phase, action, say, fix):
    with pytest.raises(PhaseRefusal) as ei:
        require_legal("DTX", action, PhaseStore(phase))
    body = explain(ei.value)["error"]
    assert body["code"] == "phase_not_allowed" and body["status"] == 409
    assert body["say"] == say
    assert body["fix"] == fix
    assert body["message"] == ei.value.message
    assert body["details"]["phase"] == phase and body["details"]["action"] == action


def test_next_step_per_phase_in_the_message():
    for phase, tail in (("EMPTY", "Add the study's files first."),
                        ("UPLOADED", "Validate the files first."),
                        ("VALIDATION_ERRORS", "Fix the validation errors, then validate again."),
                        ("VALIDATED", "Integrate first.")):
        with pytest.raises(PhaseRefusal) as ei:
            require_legal("DTX", "PROCESS", PhaseStore(phase))
        assert ei.value.message.endswith(tail), phase


def test_empty_allows_nothing_but_adding_files():
    with pytest.raises(PhaseRefusal) as ei:
        require_legal("DTX", "VALIDATE", PhaseStore("EMPTY"))
    assert "(allowed now: ADD_FILES)" in ei.value.message
