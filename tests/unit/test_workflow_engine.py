"""
Unit tests for workflow.engine.WorkflowEngine (ADR-0014 step 3).

Driven by an in-memory FakeStore — no disk, no FastAPI. The headline case is the
DE-CONFLATION the JS caller couldn't express: with integrated.json present but
animal_report.json absent, phase must be INTEGRATED (not APPROVED). The pure
derive_phase always supported this; the engine feeds the two flags separately
because on disk they are separate files.
"""

import pytest

from workflow.engine import WorkflowEngine, WorkflowState
from workflow.phases import Action, Phase


class FakeStore:
    """In-memory PoolStore double for engine tests. Presence is controlled by the
    `present` set of artifact names + `files`/`stale` toggles + a `docs` map."""

    def __init__(self, *, files=False, stale=False, present=None, docs=None,
                 section_states=None, section_dicts=None, processed=False):
        self._files = files
        self._stale = stale
        self._present = set(present or ())
        self._docs = docs or {}
        self._section_states = section_states or {}
        self._processed = processed
        # Full section dicts for publish_readiness; defaults to deriving trivial
        # {approved} dicts from section_states so existing tests need no change.
        self._section_dicts = section_dicts or {
            k: {"approved": v} for k, v in self._section_states.items()
        }

    # session_dir backs the engine's `processed` resource check (_is_processed
    # globs `_cache_ntp_*.json`). Return a real temp dir, seeding the NTP cache
    # marker when this store is flagged processed.
    def session_dir(self, dtxsid):
        import tempfile
        from pathlib import Path
        if not hasattr(self, "_sdir"):
            self._sdir = Path(tempfile.mkdtemp(prefix="fakestore_"))
            if self._processed:
                (self._sdir / "_cache_ntp_deadbeef.json").write_text("{}")
        return self._sdir

    # presence checks used by gather_artifacts
    def has_files(self, dtxsid):
        return self._files

    def has_stale_sections(self, dtxsid):
        return self._stale

    def artifact_exists(self, dtxsid, name):
        return name in self._present

    def read_json(self, dtxsid, name):
        return self._docs.get(name)

    def read_section_states(self, dtxsid):
        return dict(self._section_states)

    def read_section_dicts(self, dtxsid):
        return dict(self._section_dicts)

    # unused-by-engine store surface (present so it satisfies duck typing)
    def write_json(self, dtxsid, name, data):
        self._docs[name] = data


def _clean_report(coverage=None):
    return {"issues": [], "coverage_matrix": coverage or {}}


def test_empty_when_no_files():
    st = WorkflowEngine("DTX", FakeStore(files=False)).state()
    assert st.phase is Phase.EMPTY
    assert st.legal_actions == frozenset()


def test_uploaded_when_files_but_no_validation():
    st = WorkflowEngine("DTX", FakeStore(files=True)).state()
    assert st.phase is Phase.UPLOADED
    assert Action.VALIDATE in st.legal_actions


def test_validated_when_clean_report_no_integration():
    store = FakeStore(files=True, docs={"validation_report.json": _clean_report()})
    st = WorkflowEngine("DTX", store).state()
    assert st.phase is Phase.VALIDATED
    assert Action.INTEGRATE in st.legal_actions


def test_integrated_not_approved_is_the_deconfliction():
    # integrated.json present, animal_report.json ABSENT → INTEGRATED.
    # The JS caller (chemical.js) collapsed both flags to !!animal_report and
    # could never represent this state; deriving from disk does.
    store = FakeStore(
        files=True,
        present={"integrated.json"},
        docs={"validation_report.json": _clean_report()},
    )
    st = WorkflowEngine("DTX", store).state()
    assert st.phase is Phase.INTEGRATED
    assert st.artifacts["hasIntegrated"] is True
    assert st.artifacts["hasAnimalReport"] is False
    assert Action.APPROVE in st.legal_actions


def test_approved_when_both_present():
    store = FakeStore(
        files=True,
        present={"integrated.json", "animal_report.json"},
        docs={"validation_report.json": _clean_report()},
    )
    st = WorkflowEngine("DTX", store).state()
    assert st.phase is Phase.APPROVED


def test_stale_regresses_over_everything():
    # A stale approved artifact set must fall back to UPLOADED (pool mutated).
    store = FakeStore(
        files=True,
        stale=True,
        present={"integrated.json", "animal_report.json"},
        docs={"validation_report.json": _clean_report()},
    )
    st = WorkflowEngine("DTX", store).state()
    assert st.phase is Phase.UPLOADED


def test_validation_errors_phase():
    store = FakeStore(
        files=True,
        docs={"validation_report.json": {"issues": [{"severity": "error"}], "coverage_matrix": {}}},
    )
    st = WorkflowEngine("DTX", store).state()
    assert st.phase is Phase.VALIDATION_ERRORS


def test_completeness_surfaced_from_coverage_matrix():
    store = FakeStore(
        files=True,
        docs={"validation_report.json": _clean_report(
            coverage={"Body Weight|tox_study": {"xlsx": None, "txt_csv": ["f1"], "bm2": "f2"}}
        )},
    )
    st = WorkflowEngine("DTX", store).state()
    assert st.completeness["Body Weight"]["complete"] is True


def test_to_dict_is_json_shaped():
    store = FakeStore(files=True, present={"integrated.json"},
                      docs={"validation_report.json": _clean_report()})
    d = WorkflowEngine("DTX", store).state().to_dict()
    assert d["phase"] == "INTEGRATED"
    assert isinstance(d["legal_actions"], list)
    assert all(isinstance(a, str) for a in d["legal_actions"])
    assert d["artifacts"]["hasIntegrated"] is True
    # validationReport (a potentially large blob) is excluded from the wire form
    assert "validationReport" not in d["artifacts"]


def test_state_is_rederived_not_cached():
    store = FakeStore(files=True, docs={"validation_report.json": _clean_report()})
    eng = WorkflowEngine("DTX", store)
    assert eng.state().phase is Phase.VALIDATED
    # Mutate the world; the engine must reflect it without any explicit refresh.
    store._present.add("integrated.json")
    assert eng.state().phase is Phase.INTEGRATED


# --- section readiness (Phase 1) -------------------------------------------

def test_summary_locked_until_background_or_result_approved():
    # Summary synthesizes approved content → approval-gated.
    store = FakeStore(files=True, section_states={})
    r = WorkflowEngine("DTX", store).derive_section_readiness()
    assert r["summary"]["enabled"] is False


def test_summary_unlocks_on_background_approval():
    store = FakeStore(files=True, section_states={"background": True})
    r = WorkflowEngine("DTX", store).derive_section_readiness()
    assert r["summary"]["enabled"] is True


def test_summary_unlocks_on_result_approval():
    store = FakeStore(files=True, section_states={"bm2_liver": True})
    r = WorkflowEngine("DTX", store).derive_section_readiness()
    assert r["summary"]["enabled"] is True


def test_methods_gated_on_processed_not_approval():
    # ★ M&M unlocks on the `processed` resource (study metadata exists post-Process),
    # NOT on approval (ADR-0018). Unprocessed → blocked even with background approved.
    unprocessed = FakeStore(files=True, section_states={"background": True}, processed=False)
    assert WorkflowEngine("DTX", unprocessed).derive_section_readiness()["methods"]["enabled"] is False
    # Processed → enabled even with nothing approved.
    processed = FakeStore(files=True, section_states={}, processed=True)
    assert WorkflowEngine("DTX", processed).derive_section_readiness()["methods"]["enabled"] is True


def test_section_readiness_is_rederived_not_cached():
    # Summary flips live when background is approved out-of-band.
    store = FakeStore(files=True, section_states={})
    eng = WorkflowEngine("DTX", store)
    assert eng.derive_section_readiness()["summary"]["enabled"] is False
    store._section_states["background"] = True
    assert eng.derive_section_readiness()["summary"]["enabled"] is True


# --- publish readiness (Phase 3a currency BLOCK) ---------------------------

def test_publish_readiness_ok_when_no_stale_llm():
    store = FakeStore(files=True, section_dicts={
        "genomics_liver_male": {"approved": True},
        "bm2_liver": {"approved": True},
    })
    r = WorkflowEngine("DTX", store).publish_readiness()
    assert r["can_publish"] is True
    assert r["blocking"] == []


def test_publish_readiness_blocks_on_stale_llm_with_reason():
    store = FakeStore(files=True, section_dicts={
        "genomics_liver_male": {
            "approved": True, "stale": True,
            "regenerated": {"reason": "data_changed"},
        },
        "bm2_liver": {"approved": True, "stale": True},  # programmatic — must NOT block
    })
    r = WorkflowEngine("DTX", store).publish_readiness()
    assert r["can_publish"] is False
    assert r["blocking"] == [
        {"section_key": "genomics_liver_male", "reason": "data_changed"}
    ]


def test_publish_readiness_clears_after_reaccept():
    store = FakeStore(files=True, section_dicts={
        "genomics_liver_male": {"approved": True, "stale": True},
    })
    eng = WorkflowEngine("DTX", store)
    assert eng.publish_readiness()["can_publish"] is False
    # Re-accept clears stale (Phase 1 accept_section_step) — live re-derive.
    store._section_dicts["genomics_liver_male"] = {"approved": True, "stale": False}
    assert eng.publish_readiness()["can_publish"] is True
