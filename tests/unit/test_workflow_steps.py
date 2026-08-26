"""
Unit tests for workflow.steps driven by a FAKE PoolStore (ADR-0014 step 2).

These prove the payoff of the injectable-store decision (Q2): a workflow step
runs with NO FastAPI, NO disk, NO Java, NO module globals — just an in-memory
store double. If a step reaches past the store (touches disk or a global) these
tests break. That is the decoupling guarantee the web UI and a future TUI both
rely on.

The heavy compute transforms (validate_pool/integrate_pool/build_animal_report)
are patched here the same way conftest's mock_bmdx_pipe patches them for the
route tests — at their workflow.steps call site.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from workflow.errors import StepError
from workflow.steps import (
    confirm_metadata_step,
    integrate_step,
    resolve_step,
    validate_step,
)


class FakeStore:
    """In-memory PoolStore double. No disk, no globals.

    `files_exist` toggles whether session_dir()/'files' appears to exist, so we
    can exercise the not-found branches without a filesystem.
    """

    def __init__(self, *, files_exist=True, fingerprints=None, docs=None):
        self._files_exist = files_exist
        self._fps = fingerprints or {}
        self._docs = docs or {}
        self._integrated = {}
        self.sections = {}
        self._base = Path("/tmp/fake-session")

    def session_dir(self, dtxsid):
        # Return a path whose /files child exists-ness we control via a shim.
        return _FakePath(self._base / dtxsid, self._files_exist)

    def ensure_fingerprints(self, dtxsid, force=False):
        return self._fps

    def get_fingerprints(self, dtxsid):
        return self._fps

    def set_fingerprints(self, dtxsid, fps):
        self._fps = fps

    def get_integrated(self, dtxsid):
        return self._integrated.get(dtxsid)

    def set_integrated(self, dtxsid, data):
        self._integrated[dtxsid] = data

    def read_json(self, dtxsid, name):
        return self._docs.get(name)

    def write_json(self, dtxsid, name, data):
        self._docs[name] = data

    def save_section(self, dtxsid, key, data, archive=True):
        self.sections[key] = data


class _FakePath:
    """Minimal path stand-in so session_dir()/'files' .exists() is controllable
    and .glob() returns nothing (no stale caches to clean in-memory)."""

    def __init__(self, path: Path, files_exist: bool):
        self._path = path
        self._files_exist = files_exist

    def __truediv__(self, other):
        return _FakePath(self._path / other, self._files_exist)

    def exists(self):
        return self._files_exist

    def glob(self, pattern):
        return iter(())

    def unlink(self, missing_ok=False):
        # session.duckdb cleanup on re-integration — nothing real to remove.
        return None

    def __fspath__(self):
        # so shutil.rmtree(session_dir / "session_parquet", ignore_errors=True)
        # gets a path-like and no-ops on the nonexistent dir.
        return str(self._path)

    def __str__(self):
        return str(self._path)


# --- validate --------------------------------------------------------------

def test_validate_step_no_files_raises_404():
    store = FakeStore(files_exist=False)
    with pytest.raises(StepError) as ei:
        validate_step("DTX", store)
    assert ei.value.status_code == 404


def test_validate_step_persists_and_returns_report():
    class _Report:
        dtxsid = "DTX"
        run_at = "now"
        file_count = 1
        fingerprints = {"f1": {}}
        issues = []
        coverage_matrix = {"Body Weight|tox_study": {"bm2": "f2"}}
        is_complete = True

    store = FakeStore()
    with patch("workflow.steps.validate_pool", return_value=_Report()):
        report = validate_step("DTX", store)
    assert report["coverage_matrix"] == {"Body Weight|tox_study": {"bm2": "f2"}}
    # Persisted through the store, not to disk.
    assert store.read_json("DTX", "validation_report.json") == report


# --- resolve ---------------------------------------------------------------

def test_resolve_step_requires_all_three_inputs():
    store = FakeStore()
    with pytest.raises(StepError) as ei:
        resolve_step("DTX", None, "fid", store)
    assert ei.value.status_code == 400


def test_resolve_step_appends_to_precedence():
    store = FakeStore(docs={"precedence.json": [{"issue_index": 0, "chosen_file_id": "old"}]})
    result = resolve_step("DTX", 1, "new-fid", store)
    assert result == {"ok": True}
    prec = store.read_json("DTX", "precedence.json")
    assert len(prec) == 2
    assert prec[-1]["chosen_file_id"] == "new-fid"


def test_resolve_step_starts_fresh_when_no_precedence_file():
    store = FakeStore()
    resolve_step("DTX", 0, "fid", store)
    assert len(store.read_json("DTX", "precedence.json")) == 1


# --- integrate -------------------------------------------------------------

def test_integrate_step_no_fingerprints_raises_400():
    store = FakeStore(fingerprints={})  # no cache, no validation_report.json
    with pytest.raises(StepError) as ei:
        integrate_step("DTX", None, store)
    assert ei.value.status_code == 400


def test_integrate_step_no_coverage_matrix_raises_400():
    # fingerprints present, but validation_report has no coverage_matrix
    store = FakeStore(
        fingerprints={"f1": {}},
        docs={"validation_report.json": {"fingerprints": {"f1": {}}}},
    )
    with pytest.raises(StepError) as ei:
        integrate_step("DTX", None, store)
    assert ei.value.status_code == 400


def test_integrate_step_success_caches_and_summarizes():
    store = FakeStore(
        fingerprints={"f1": object()},
        docs={"validation_report.json": {"coverage_matrix": {"Body Weight|tox_study": {}}}},
    )
    integrated = {
        "doseResponseExperiments": [
            {"name": "BW_Male", "probeResponses": [{}, {}]},
        ],
        "_meta": {"source_files": {"Body Weight": {"experiment_count": 1}}},
        "bMDResult": [],
        "categoryAnalysisResults": [],
    }
    with patch("workflow.steps.integrate_pool", return_value=integrated):
        summary = integrate_step("DTX", {"name": "PFHxSAm"}, store)

    assert summary["ok"] is True
    assert summary["experiment_count"] == 1
    assert summary["experiments"][0] == {"name": "BW_Male", "probe_count": 2}
    # cached via the store, not a global
    assert store.get_integrated("DTX") is integrated
    # identity persisted for LLM metadata inference
    assert store.read_json("DTX", "identity.json") == {"name": "PFHxSAm"}


# --- confirm-metadata ------------------------------------------------------

def test_confirm_metadata_step_updates_dict_fingerprint_and_persists():
    # dict-style fingerprint that is NOT txt/csv → no header write, but the
    # correction is applied and fingerprints are re-persisted through the store.
    fps = {"f1": {"filename": "gene.bm2", "file_type": "bm2", "platform": "?"}}
    store = FakeStore(fingerprints=fps)
    result = confirm_metadata_step(
        "DTX", {"f1": {"platform": "Body Weight", "data_type": "tox_study"}}, store
    )
    assert result == {"ok": True, "updated": 0}
    assert fps["f1"]["platform"] == "Body Weight"
    assert "_fingerprints.json" in store._docs
