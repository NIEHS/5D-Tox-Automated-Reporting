"""
C1: legal actions are enforced (docs/ui-redesign/modules/c1/spec.md).

Every guarded act (safeguards.guarded) derives the study's phase first and
refuses an act its phase does not allow (`safeguards.acts.require_legal` →
`PhaseRefusal`, 409 ``phase_not_allowed``), before it reads or writes anything
else. These tests pin the guard with an in-memory store: the refusal's fields
per phase, its plain words through the error envelope (safeguards.refusals),
and, over the inventory of every mutating entry point (spec §2.2), that each
guarded one refuses out of phase and writes nothing — while the core step the
notebook calls does not refuse (the workflow without the guarding).
"""

from __future__ import annotations

import pytest

from safeguards.acts import require_legal
from workflow.engine import WorkflowEngine
from safeguards.refusals import PhaseRefusal
from workflow.errors import StepError
from workflow.phases import LEGAL_ACTIONS, Action, Phase
from safeguards.refusals import explain


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
    st = require_legal("DTX", Action.PROCESS, PhaseStore("APPROVED"))
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
     "study's files first.", "files"),
    ("EMPTY", "RESET", "This study has no files to remove.", "files"),
    ("EMPTY", "REMOVE_FILE", "This study has no files to remove.", "files"),
    ("UPLOADED", "INTEGRATE",
     "Combining the files into one dataset isn't possible yet. The study's files have "
     "changed since they were last checked, or were never checked. Run the file check "
     "first.", "files"),
    ("VALIDATION_ERRORS", "PROCESS",
     "Processing isn't possible yet. The file check found errors. Fix what it lists "
     "(remove or replace the files it names), then run the file check again.", "files"),
    ("VALIDATED", "APPROVE",
     "Approving the data isn't possible yet. The study's files have been checked but not "
     "yet combined into one dataset. Integrate the study first.", "dataset"),
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


# ---------------------------------------------------------------------------
# The inventory: every mutating entry point refuses out of phase (spec §2.2).
# Each is driven at a phase where its act is illegal, on a real scratch
# session, and must raise PhaseRefusal and leave the session exactly as it was.
# Adding a mutating entry point means adding it here.
# ---------------------------------------------------------------------------

def _seed(sessions_dir, phase):
    """A real session at `phase` (VALIDATED or earlier: no dataset)."""
    import json
    d = sessions_dir / "DTXSID_LEGAL"
    d.mkdir(parents=True)
    if phase != "EMPTY":
        (d / "files").mkdir()
        (d / "files" / "bw.csv").write_text("x")
    if phase == "VALIDATION_ERRORS":
        (d / "validation_report.json").write_text(json.dumps(
            {"issues": [{"severity": "error"}], "coverage_matrix": {}}))
    elif phase == "VALIDATED":
        (d / "validation_report.json").write_text(json.dumps(
            {"issues": [], "coverage_matrix": {}}))
    return d


def _run(coro_or_value):
    import asyncio
    import inspect
    return asyncio.run(coro_or_value) if inspect.iscoroutine(coro_or_value) else coro_or_value


def _disk():
    from workflow.store import DiskPoolStore
    return DiskPoolStore()


_ENTRY_POINTS = [
    # (name, phase where it is refused, call(dtxsid))
    ("remove_pool_file", "EMPTY",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).remove_pool_file(d, "bw.csv")),
    ("validate_step", "EMPTY",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).validate_step(d, _disk())),
    ("resolve_step", "UPLOADED",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).resolve_step(d, 0, "fid", _disk())),
    ("confirm_metadata_step", "UPLOADED",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).confirm_metadata_step(d, {}, _disk())),
    ("integrate_step", "VALIDATION_ERRORS",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).integrate_step(d, None, _disk())),
    ("approve_experiment_metadata", "VALIDATED",
     lambda d: __import__("safeguards.guarded", fromlist=["x"])
     .approve_experiment_metadata(d, {"x": {"organ": "liver"}})),
    ("state_dataset_facts", "VALIDATED",
     lambda d: __import__("safeguards.guarded", fromlist=["x"])
     .require_state_dataset_facts(d, _disk())),
    ("generate_animal_report_step", "VALIDATED",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).generate_animal_report_step(d, _disk())),
    ("run_process", "VALIDATED",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).run_process(d, {}, _disk())),
    ("run_document", "VALIDATED",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).run_document(d, {}, _disk())),
    ("process_step", "UPLOADED",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).process_step(d, {}, _disk())),
    ("document_step", "UPLOADED",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).document_step(d, {}, _disk())),
    ("materialize_result_sections", "VALIDATED",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).materialize_result_sections(d, _disk())),
    ("materialize_summary", "VALIDATED",
     lambda d: __import__("safeguards.guarded", fromlist=["x"]).materialize_summary(d, _disk())),
]


def _snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*"))}


@pytest.mark.parametrize("name,phase,call", _ENTRY_POINTS, ids=[e[0] for e in _ENTRY_POINTS])
def test_every_mutating_entry_point_refuses_out_of_phase(name, phase, call, sessions_dir):
    d = _seed(sessions_dir, phase)
    before = _snapshot(d)
    with pytest.raises(PhaseRefusal) as ei:
        _run(call("DTXSID_LEGAL"))
    assert ei.value.details["phase"] == phase
    assert _snapshot(d) == before, f"{name} wrote before refusing"


def test_add_files_is_refused_nowhere(sessions_dir):
    from tooling.generate_report import import_files
    for phase in ("EMPTY", "VALIDATED"):
        d = sessions_dir / f"DTXSID_ADD_{phase}"
        d.mkdir(parents=True)
        src = sessions_dir.parent / f"in_{phase}.csv"
        src.write_text("x")
        import_files(d.name, [src], _disk())
        assert (d / "files" / src.name).exists()


def test_a_stale_section_is_no_dead_end(sessions_dir):
    """C1 D2: a stale genomics section no longer holds the phase at UPLOADED,
    so integration is not refused until a person re-accepts prose about the
    old data (spec §4). Staleness stays a section matter (the publish gate)."""
    import json
    from workflow.store import DiskPoolStore
    d = _seed(sessions_dir, "VALIDATED")
    (d / "genomics_liver_male.json").write_text(json.dumps({"approved": True, "stale": True}))
    st = WorkflowEngine("DTXSID_LEGAL", DiskPoolStore()).state()
    assert st.artifacts["hasStale"] is True
    assert st.phase is Phase.VALIDATED and Action.INTEGRATE in st.legal_actions


# The core steps (what the notebook calls) do not refuse an act out of phase:
# the guarding is the safeguards' (ADR-0031). Validating an un-checked study
# from the core simply runs.
def test_the_core_step_is_not_guarded(sessions_dir, monkeypatch):
    from workflow import steps
    d = _seed(sessions_dir, "VALIDATED")
    called = []
    monkeypatch.setattr(steps, "validate_pool", lambda *a, **k: called.append(a) or {
        "issues": [], "coverage_matrix": {}, "file_count": 1}, raising=False)
    try:
        steps.generate_animal_report_step(d.name, _disk())
    except PhaseRefusal:  # pragma: no cover - the failure this test exists for
        raise AssertionError("the core step refused: the guard belongs to the safeguards")
    except Exception:
        pass  # anything else (no data to account for) is the step's own business
