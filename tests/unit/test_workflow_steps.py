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

    def __init__(self, *, files_exist=True, fingerprints=None, docs=None, present=(),
                 real_dir=None):
        self._files_exist = files_exist
        self._fps = fingerprints or {}
        self._docs = docs or {}
        self._present = set(present)
        self._integrated = {}
        self.sections = {}
        self._base = Path("/tmp/fake-session")
        self._real_dir = real_dir

    def session_dir(self, dtxsid):
        if self._real_dir is not None:      # a step that moves real files (the approval)
            return self._real_dir
        # Return a path whose /files child exists-ness we control via a shim.
        return _FakePath(self._base / dtxsid, self._files_exist)

    # --- what the phase guard reads (PoolStore protocol). The phase follows
    # the docs: files → a report → integrated.json → animal_report.json.
    def has_files(self, dtxsid):
        return self._files_exist

    def has_stale_sections(self, dtxsid):
        return False

    def artifact_exists(self, dtxsid, name):
        return name in self._present or name in self._docs

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


_CLEAN = {"issues": [], "coverage_matrix": {}}


def _validated(**docs):
    """Docs of a VALIDATED study (a clean report), plus any given."""
    return {"validation_report.json": dict(_CLEAN), **docs}


# --- validate --------------------------------------------------------------

def test_validate_step_no_files_is_refused_409():
    # C1: no files → EMPTY, where only ADD_FILES is legal (it was a 404).
    from workflow.errors import PhaseRefusal
    store = FakeStore(files_exist=False)
    with pytest.raises(PhaseRefusal) as ei:
        validate_step("DTXSID_VC", store)
    assert ei.value.status_code == 409
    assert ei.value.details["phase"] == "EMPTY"


def test_validate_step_persists_and_returns_report():
    class _Report:
        dtxsid = "DTXSID_VC"
        run_at = "now"
        file_count = 1
        fingerprints = {"f1": {}}
        issues = []
        coverage_matrix = {"Body Weight|tox_study": {"bm2": "f2"}}
        is_complete = True

    store = FakeStore()
    with patch("workflow.steps.validate_pool", return_value=_Report()):
        report = validate_step("DTXSID_VC", store)
    assert report["coverage_matrix"] == {"Body Weight|tox_study": {"bm2": "f2"}}
    # Persisted through the store, not to disk.
    assert store.read_json("DTXSID_VC", "validation_report.json") == report


# --- resolve ---------------------------------------------------------------

def test_resolve_step_requires_all_three_inputs():
    store = FakeStore()
    with pytest.raises(StepError) as ei:
        resolve_step("DTXSID_VC", None, "fid", store)
    assert ei.value.status_code == 400


def test_resolve_step_appends_to_precedence():
    store = FakeStore(docs=_validated(**{"precedence.json": [{"issue_index": 0,
                                                              "chosen_file_id": "old"}]}))
    result = resolve_step("DTXSID_VC", 1, "new-fid", store)
    assert result == {"ok": True}
    prec = store.read_json("DTXSID_VC", "precedence.json")
    assert len(prec) == 2
    assert prec[-1]["chosen_file_id"] == "new-fid"


def test_resolve_step_starts_fresh_when_no_precedence_file():
    store = FakeStore(docs=_validated())
    resolve_step("DTXSID_VC", 0, "fid", store)
    assert len(store.read_json("DTXSID_VC", "precedence.json")) == 1


# --- integrate -------------------------------------------------------------

def test_integrate_step_never_validated_is_refused_409():
    # C1: files but no validation report → UPLOADED, where INTEGRATE is refused
    # before anything is read (it was a 400 "no fingerprints").
    from workflow.errors import PhaseRefusal
    store = FakeStore(fingerprints={})
    with pytest.raises(PhaseRefusal) as ei:
        integrate_step("DTXSID_VC", None, store)
    assert ei.value.status_code == 409
    assert ei.value.details["phase"] == "UPLOADED"


def test_integrate_step_no_fingerprints_raises_400():
    # VALIDATED, but the report carries no fingerprints and none are cached:
    # the 400 stays reachable as a fallback.
    store = FakeStore(fingerprints={}, docs=_validated())
    with pytest.raises(StepError) as ei:
        integrate_step("DTXSID_VC", None, store)
    assert ei.value.status_code == 400


def test_integrate_step_no_coverage_matrix_raises_400():
    # fingerprints present, but validation_report has no coverage_matrix
    store = FakeStore(
        fingerprints={"f1": {}},
        docs={"validation_report.json": {"issues": [], "fingerprints": {"f1": {}}}},
    )
    with pytest.raises(StepError) as ei:
        integrate_step("DTXSID_VC", None, store)
    assert ei.value.status_code == 400


def test_integrate_step_success_caches_and_summarizes(sessions_dir):
    # sessions_dir: the method profile is read from disk (ADR-0027); nothing
    # must land in the real sessions/.
    store = FakeStore(
        fingerprints={"f1": object()},
        docs={"validation_report.json": {"issues": [],
                                         "coverage_matrix": {"Body Weight|tox_study": {}}}},
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
        summary = integrate_step("DTXSID_VC", {"name": "PFHxSAm"}, store)

    assert summary["ok"] is True
    assert summary["experiment_count"] == 1
    assert summary["experiments"][0] == {"name": "BW_Male", "probe_count": 2}
    # cached via the store, not a global
    assert store.get_integrated("DTXSID_VC") is integrated
    # identity persisted for LLM metadata inference
    assert store.read_json("DTXSID_VC", "identity.json") == {"name": "PFHxSAm"}
    # C1: integration pins no method profile, and says so plainly.
    assert not (sessions_dir / "DTXSID_VC" / "method_profile.json").exists()
    assert summary["method"] == {"profile": None, "pinned_by": None, "mode": None,
                                 "deviations": [], "mismatches": []}
    assert summary["approval_withdrawn"] is False
    # The basis it was built from is recorded.
    assert store.read_json("DTXSID_VC", "integration_basis.json")["basis"]


def _integrated_min():
    return {"doseResponseExperiments": [], "_meta": {}, "bMDResult": [],
            "categoryAnalysisResults": []}


def test_reintegration_withdraws_and_archives_the_data_approval(tmp_path, sessions_dir):
    import json
    sdir = tmp_path / "DTXSID_VC"
    (sdir / "files").mkdir(parents=True)
    (sdir / "animal_report.json").write_text(json.dumps({"total_animals": 40}))
    store = FakeStore(fingerprints={"f1": object()}, real_dir=sdir,
                      present={"integrated.json", "animal_report.json"},
                      docs=_validated())
    store._docs["validation_report.json"]["coverage_matrix"] = {"Body Weight|tox_study": {}}
    with patch("workflow.steps.integrate_pool", return_value=_integrated_min()):
        summary = integrate_step("DTXSID_VC", None, store)
    assert summary["approval_withdrawn"] is True
    assert not (sdir / "animal_report.json").exists()
    archived = list((sdir / "history" / "_data_approval").glob("*-animal_report.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text()) == {"total_animals": 40}


def test_a_failed_merge_keeps_the_data_approval(tmp_path):
    sdir = tmp_path / "DTXSID_VC"
    (sdir / "files").mkdir(parents=True)
    (sdir / "animal_report.json").write_text("{}")
    store = FakeStore(fingerprints={"f1": object()}, real_dir=sdir,
                      present={"integrated.json", "animal_report.json"},
                      docs=_validated())
    store._docs["validation_report.json"]["coverage_matrix"] = {"Body Weight|tox_study": {}}
    with patch("workflow.steps.integrate_pool", side_effect=RuntimeError("java")):
        with pytest.raises(StepError) as ei:
            integrate_step("DTXSID_VC", None, store)
    assert ei.value.status_code == 500
    assert (sdir / "animal_report.json").exists()
    assert "integration_basis.json" not in store._docs


def test_integration_refuses_when_validation_is_out_of_date():
    # The restart trap: a cold re-scan minted new ids, so the coverage matrix
    # names files the fingerprints integration would use do not hold.
    from workflow.errors import ValidationOutOfDate
    from workflow.refusals import explain

    report = {"issues": [], "fingerprints": {"old-1": {"filename": "bw.csv"},
                                              "old-2": {"filename": "bw.bm2"}},
              "coverage_matrix": {"Body Weight|tox_study": {
                  "xlsx": None, "txt_csv": ["old-1"], "bm2": "old-2"}}}
    fps = {"new-1": {"filename": "bw.csv"}, "new-2": {"filename": "bw.bm2"},
           "new-3": {"filename": "late.csv"}}
    store = FakeStore(fingerprints=fps, docs={"validation_report.json": report})
    with patch("workflow.steps.integrate_pool") as merge:
        with pytest.raises(ValidationOutOfDate) as ei:
            integrate_step("DTXSID_VC", None, store)
    merge.assert_not_called()
    assert ei.value.status_code == 409
    assert ei.value.details == {"missing_ids": 2, "added": ["late.csv"], "missing": []}
    assert ei.value.message == (
        "INTEGRATE refused for DTXSID_VC: the validation report no longer matches the files "
        "the server holds (2 file id(s) in its coverage matrix are not among the current "
        "fingerprints; files added since validation: late.csv). Validate again, then "
        "integrate.")
    body = explain(ei.value)["error"]
    assert (body["code"], body["fix"]) == ("validation_out_of_date", "M2")
    assert body["say"].startswith("The file check is out of date")


def test_integration_passes_on_the_report_fingerprint_fallback():
    # A cold server with nothing re-scanned: no cached fingerprints, so the
    # report's own are used, and they match its matrix by construction.
    report = {"issues": [], "fingerprints": {"a": {"filename": "bw.csv"}},
              "coverage_matrix": {"Body Weight|tox_study": {"txt_csv": ["a"]}}}
    store = FakeStore(fingerprints={}, docs={"validation_report.json": report})
    with patch("workflow.steps.integrate_pool", return_value=_integrated_min()) as merge:
        integrate_step("DTXSID_VC", None, store)
    merge.assert_called_once()


def test_integration_refused_at_validation_errors():
    from workflow.errors import PhaseRefusal
    store = FakeStore(fingerprints={"f1": {}}, present={"integrated.json"},
                      docs={"validation_report.json": {
                          "issues": [{"severity": "error"}], "coverage_matrix": {"x": {}}}})
    with patch("workflow.steps.integrate_pool") as merge:
        with pytest.raises(PhaseRefusal) as ei:
            integrate_step("DTXSID_VC", None, store)
    merge.assert_not_called()
    assert ei.value.details["phase"] == "VALIDATION_ERRORS"


def test_resolve_and_confirm_are_refused_before_validation():
    from workflow.errors import PhaseRefusal
    for call in (lambda st: resolve_step("DTXSID_VC", 0, "fid", st),
                 lambda st: confirm_metadata_step("DTXSID_VC", {}, st)):
        store = FakeStore()                      # files, never validated: UPLOADED
        with pytest.raises(PhaseRefusal):
            call(store)
        assert store._docs == {}                 # nothing written


# --- confirm-metadata ------------------------------------------------------

def test_confirm_metadata_step_updates_dict_fingerprint_and_persists():
    # dict-style fingerprint that is NOT txt/csv → no header write, but the
    # correction is applied and fingerprints are re-persisted through the store.
    fps = {"f1": {"filename": "gene.bm2", "file_type": "bm2", "platform": "?"}}
    store = FakeStore(fingerprints=fps, docs=_validated())
    result = confirm_metadata_step(
        "DTXSID_VC", {"f1": {"platform": "Body Weight", "data_type": "tox_study"}}, store
    )
    assert result == {"ok": True, "updated": 0}
    assert fps["f1"]["platform"] == "Body Weight"
    assert "_fingerprints.json" in store._docs


# --- materialize result sections (ADR-0018 Phase 1) ------------------------
# These use a REAL tmp session (the sessions_dir fixture) because the transform
# reads the _cache_sections file and writes bm2_*.json via save_section, both of
# which resolve through the patched SESSIONS_DIR. Materializing is part of
# Process (C1), so each session is seeded INTEGRATED first (_integrated_session).

def _integrated_session(sessions_dir, dtxsid="DTXSID_VC"):
    """A real session the phase derives INTEGRATED: a file, a clean validation
    report and integrated.json."""
    import json
    d = sessions_dir / dtxsid
    (d / "files").mkdir(parents=True)
    (d / "files" / ".keep").write_text("")
    (d / "validation_report.json").write_text(json.dumps(_CLEAN))
    (d / "integrated.json").write_text("{}")
    return d


def test_materialize_is_refused_before_integration(sessions_dir):
    from workflow.errors import PhaseRefusal
    from workflow.steps import materialize_result_sections, materialize_summary
    from workflow.store import DiskPoolStore
    d = sessions_dir / "DTXSID_VC"
    (d / "files").mkdir(parents=True)
    (d / "files" / "bw.csv").write_text("x")
    for step in (materialize_result_sections, materialize_summary):
        with pytest.raises(PhaseRefusal):
            step("DTXSID_VC", DiskPoolStore())

def test_materialize_result_sections_writes_bm2_files(sessions_dir):
    import json
    from workflow.steps import materialize_result_sections
    from workflow.store import DiskPoolStore

    d = _integrated_session(sessions_dir)
    # Seed a sections cache the way Process would (two apical sections; one has a
    # narrative, one is table-only — both legitimate).
    (d / "_cache_sections_abc123.json").write_text(json.dumps({"sections": [
        {"platform": "Body Weight", "title": "Body Weight", "tables_json": {"rows": []},
         "narrative": [], "first_col_header": "Study Day", "caption": "BW", "footnotes": []},
        {"platform": "Organ Weight", "title": "Organ Weight", "tables_json": {"rows": []},
         "narrative": ["Liver weight increased."], "caption": "OW", "footnotes": ["(a)"]},
    ]}))

    result = materialize_result_sections("DTXSID_VC", DiskPoolStore())
    assert result["ok"] is True
    assert set(result["materialized"]) == {"bm2_body-weight", "bm2_organ-weight"}

    # Files written, provisional (unapproved), narrative preserved verbatim.
    bw = json.loads((d / "bm2_body-weight.json").read_text())
    ow = json.loads((d / "bm2_organ-weight.json").read_text())
    assert bw["approved"] is False and bw["source"] == "generated"
    assert bw["narrative"] == []            # table-only section stays empty
    assert bw["tables_json"] == {"rows": []}
    assert ow["narrative"] == ["Liver weight increased."]
    assert ow["footnotes"] == ["(a)"]


def test_materialize_result_sections_no_cache_is_noop(sessions_dir):
    from workflow.steps import materialize_result_sections
    from workflow.store import DiskPoolStore
    _integrated_session(sessions_dir)
    result = materialize_result_sections("DTXSID_VC", DiskPoolStore())
    assert result == {"ok": True, "materialized": [], "unchanged": [], "needs_review": [],
                      "held": []}


# --- Phase 3b: wording_review flip detection at materialize -----------------
# The section carries a `cat_signature` (categorical slot values per finding). On a
# reprocess that FLIPS one against a section the human had APPROVED, materialize
# stamps a non-blocking `wording_review` marker. Gate: prior-approved AND flipped.

def _seed_cache(d, cat_signature):
    import json

    # Evict any prior sections cache (mimics _save_cache) so _latest_cache is
    # unambiguous regardless of mtime granularity, then write the new superset.
    for old in d.glob("_cache_sections_*.json"):
        old.unlink()
    (d / "_cache_sections_seed.json").write_text(json.dumps({"sections": [
        {"platform": "Body Weight", "title": "Body Weight",
         "tables_json": {"rows": []}, "narrative": ["Body weight decreased."],
         "cat_signature": cat_signature},
    ]}))


def test_wording_review_stamped_on_flip_against_approved(sessions_dir):
    import json
    from workflow.steps import materialize_result_sections
    from workflow.store import DiskPoolStore

    d = _integrated_session(sessions_dir)
    # First materialize with direction "decreased", then the human approves it.
    _seed_cache(d, {"Male|Terminal Body Wt.": {"direction": "decreased", "trend": "negative"}})
    materialize_result_sections("DTXSID_VC", DiskPoolStore())
    bw_path = d / "bm2_body-weight.json"
    approved = json.loads(bw_path.read_text())
    approved["approved"] = True
    bw_path.write_text(json.dumps(approved))

    # Reprocess flips the direction; materialize again.
    _seed_cache(d, {"Male|Terminal Body Wt.": {"direction": "increased", "trend": "positive"}})
    materialize_result_sections("DTXSID_VC", DiskPoolStore())

    bw = json.loads(bw_path.read_text())
    assert bw["wording_review"] == [
        "Male|Terminal Body Wt..direction", "Male|Terminal Body Wt..trend"
    ]
    # C2 D2/A1: knocked down WITH a record — the approved version archived, a
    # review marker, a needs-re-bless event. Never `stale` (that would send the
    # phase back to UPLOADED).
    assert bw["approved"] is False
    assert bw["review"]["why"] == "wording_changed"
    assert bw["review"]["flips"] == bw["wording_review"]
    assert "stale" not in bw
    from pipeline.session_store import list_archived, read_version_history
    assert [a["approved"] for _n, a in list_archived("DTXSID_VC", "bm2_body-weight")] == [True]
    assert read_version_history("DTXSID_VC", "bm2_body-weight")[-1]["status"] == "needs-re-bless"


def test_no_wording_review_when_never_approved(sessions_dir):
    import json
    from workflow.steps import materialize_result_sections
    from workflow.store import DiskPoolStore

    d = _integrated_session(sessions_dir)
    _seed_cache(d, {"Male|Terminal Body Wt.": {"direction": "decreased", "trend": "negative"}})
    materialize_result_sections("DTXSID_VC", DiskPoolStore())
    # NOT approved — just re-materialize with a flipped signature.
    _seed_cache(d, {"Male|Terminal Body Wt.": {"direction": "increased", "trend": "positive"}})
    materialize_result_sections("DTXSID_VC", DiskPoolStore())

    bw = json.loads((d / "bm2_body-weight.json").read_text())
    assert "wording_review" not in bw  # provisional wording regenerates freely


def test_no_wording_review_when_signature_unchanged(sessions_dir):
    import json
    from workflow.steps import materialize_result_sections
    from workflow.store import DiskPoolStore

    d = _integrated_session(sessions_dir)
    sig = {"Male|Terminal Body Wt.": {"direction": "decreased", "trend": "negative"}}
    _seed_cache(d, sig)
    materialize_result_sections("DTXSID_VC", DiskPoolStore())
    bw_path = d / "bm2_body-weight.json"
    approved = json.loads(bw_path.read_text())
    approved["approved"] = True
    bw_path.write_text(json.dumps(approved))

    # Reprocess with the SAME signature (numbers may have refreshed, words did not).
    _seed_cache(d, sig)
    materialize_result_sections("DTXSID_VC", DiskPoolStore())

    bw = json.loads(bw_path.read_text())
    assert "wording_review" not in bw


# --- C2: Process never overwrites owned content (I1, I5, T1, T2, T4) --------

def _seed_two(d, weight_rows):
    import json
    for old in d.glob("_cache_sections_*.json"):
        old.unlink()
    (d / "_cache_sections_seed.json").write_text(json.dumps({"sections": [
        {"platform": "Body Weight", "title": "Body Weight", "tables_json": {"rows": weight_rows},
         "narrative": [], "cat_signature": {}},
        {"platform": "Organ Weight", "title": "Organ Weight", "tables_json": {"rows": []},
         "narrative": ["Liver weight increased."], "cat_signature": {}},
    ]}))


def test_i5_a_warm_materialize_with_nothing_changed_touches_no_file(sessions_dir):
    # T1 regression: an approved apical section stays approved, and every
    # bm2_*.json is byte-identical (mtime too).
    import json
    import os
    from workflow.steps import accept_section_step, materialize_result_sections
    from workflow.store import DiskPoolStore

    d = _integrated_session(sessions_dir, "DTXSID_I5")
    _seed_two(d, [1])
    store = DiskPoolStore()
    first = materialize_result_sections("DTXSID_I5", store)
    assert first["materialized"] == ["bm2_body-weight", "bm2_organ-weight"]
    accept_section_step("DTXSID_I5", "bm2_body-weight", store)
    before = {p.name: (p.read_bytes(), os.stat(p).st_mtime_ns) for p in d.glob("bm2_*.json")}
    events_before = (d / "history" / "bm2_body-weight" / "index.jsonl").read_text()

    again = materialize_result_sections("DTXSID_I5", store)

    assert again["materialized"] == [] and again["needs_review"] == []
    assert again["unchanged"] == ["bm2_body-weight", "bm2_organ-weight"]
    after = {p.name: (p.read_bytes(), os.stat(p).st_mtime_ns) for p in d.glob("bm2_*.json")}
    assert after == before
    assert json.loads((d / "bm2_body-weight.json").read_text())["approved"] is True
    # I4: no event for an unchanged materialize.
    assert (d / "history" / "bm2_body-weight" / "index.jsonl").read_text() == events_before


def test_t2_changed_numbers_under_an_approval_are_knocked_down_with_a_record(sessions_dir):
    import json
    from pipeline.session_store import current_version_status, list_archived
    from workflow.steps import accept_section_step, materialize_result_sections
    from workflow.store import DiskPoolStore

    d = _integrated_session(sessions_dir, "DTXSID_T2")
    _seed_two(d, [1])
    store = DiskPoolStore()
    materialize_result_sections("DTXSID_T2", store)
    accept_section_step("DTXSID_T2", "bm2_body-weight", store)
    _seed_two(d, [2])

    out = materialize_result_sections("DTXSID_T2", store)

    assert out["needs_review"] == [{"key": "bm2_body-weight", "why": "numbers_changed",
                                    "prior_version": 1, "version": 2, "flips": []}]
    assert out["materialized"] == ["bm2_body-weight"]
    assert out["unchanged"] == ["bm2_organ-weight"]
    bw = json.loads((d / "bm2_body-weight.json").read_text())
    assert bw["tables_json"] == {"rows": [2]} and bw["version"] == 2
    assert bw["approved"] is False and bw["facts"] == ["protected"]
    assert bw["review"] == {"why": "numbers_changed", "since_version": 1, "flips": []}
    archived = list_archived("DTXSID_T2", "bm2_body-weight")
    assert [(a["version"], a["approved"], a["tables_json"]) for _n, a in archived] == [
        (1, True, {"rows": [1]})]
    assert current_version_status("DTXSID_T2", "bm2_body-weight") == "needs-re-bless"


def test_an_unowned_section_whose_numbers_changed_is_archived_and_rewritten(sessions_dir):
    import json
    from pipeline.session_store import list_archived, read_version_history
    from workflow.steps import materialize_result_sections
    from workflow.store import DiskPoolStore

    d = _integrated_session(sessions_dir, "DTXSID_UN")
    _seed_two(d, [1])
    materialize_result_sections("DTXSID_UN", DiskPoolStore())
    _seed_two(d, [2])
    out = materialize_result_sections("DTXSID_UN", DiskPoolStore())
    assert out["materialized"] == ["bm2_body-weight"] and out["needs_review"] == []
    assert json.loads((d / "bm2_body-weight.json").read_text())["version"] == 2
    assert [a["tables_json"] for _n, a in list_archived("DTXSID_UN", "bm2_body-weight")] == [
        {"rows": [1]}]
    assert [(e["cause"], e["status"], e["act"]) for e in
            read_version_history("DTXSID_UN", "bm2_body-weight")] == [
        ("generate", "draft", "materialize"), ("generate", "draft", "materialize")]


def _summary_inputs_patch(monkeypatch, paragraphs):
    import narrative.report_summary as rs
    import narrative.summary_llm as sl
    monkeypatch.setattr(sl, "summary_inputs", lambda sdir: {})
    monkeypatch.setattr(rs, "build_report_summary", lambda **kw: list(paragraphs))


def test_t4_materialize_summary_holds_a_released_protected_summary(sessions_dir, monkeypatch):
    import json
    from pipeline.session_store import read_version_history
    from workflow.steps import (
        accept_section_step, materialize_summary, release_section_step,
    )
    from workflow.store import DiskPoolStore

    _integrated_session(sessions_dir, "DTXSID_T4")
    store = DiskPoolStore()
    _summary_inputs_patch(monkeypatch, ["first"])
    assert materialize_summary("DTXSID_T4", store)["written"] is True
    accept_section_step("DTXSID_T4", "summary", store)
    release_section_step("DTXSID_T4", "summary", store, reason="check the wording")
    _summary_inputs_patch(monkeypatch, ["second"])

    out = materialize_summary("DTXSID_T4", store)

    assert out["written"] is False and out["held"] == {"why": "owned", "version": 1}
    s = json.loads((sessions_dir / "DTXSID_T4" / "summary.json").read_text())
    assert s["paragraphs"] == ["first"] and s["facts"] == ["protected"]
    hold = read_version_history("DTXSID_T4", "summary")[-1]
    assert hold["cause"] == "hold" and hold["applied"] is False and hold["act"] == "summary"


def test_materialize_summary_with_nothing_new_writes_nothing(sessions_dir, monkeypatch):
    import os
    from pipeline.session_store import read_version_history
    from workflow.steps import materialize_summary
    from workflow.store import DiskPoolStore

    _integrated_session(sessions_dir, "DTXSID_SU")
    _summary_inputs_patch(monkeypatch, ["same"])
    materialize_summary("DTXSID_SU", DiskPoolStore())
    p = sessions_dir / "DTXSID_SU" / "summary.json"
    before = (p.read_bytes(), os.stat(p).st_mtime_ns)
    out = materialize_summary("DTXSID_SU", DiskPoolStore())
    assert out == {"ok": True, "written": False, "paragraphs": 0}
    assert (p.read_bytes(), os.stat(p).st_mtime_ns) == before
    assert len(read_version_history("DTXSID_SU", "summary")) == 1


def test_materialize_summary_leaves_a_summary_it_did_not_write(sessions_dir, monkeypatch):
    import json
    from workflow.steps import materialize_summary
    from workflow.store import DiskPoolStore

    d = _integrated_session(sessions_dir, "DTXSID_SM")
    (d / "summary.json").write_text(json.dumps({"paragraphs": ["model"], "source": "model",
                                                "version": 1}))
    _summary_inputs_patch(monkeypatch, ["generated"])
    out = materialize_summary("DTXSID_SM", DiskPoolStore())
    assert out["written"] is False and out["held"]["why"] == "not_generated_here"
    assert json.loads((d / "summary.json").read_text())["paragraphs"] == ["model"]


@pytest.mark.parametrize("owned", [
    {"approved": True, "facts": ["final", "protected"]},
    {"approved": False, "facts": ["protected"]},           # released (D1)
    {"user_edited": True},
])
def test_i1_materialize_with_the_fake_store_never_overwrites_owned_text(monkeypatch, owned):
    # I1, with no disk at all: an owned apical section's text is archived
    # before the machine's replaces it (D2/A1), and the summary is held.
    import pipeline.session_db as session_db
    from tests.unit.section_store_fake import FakeSectionStore
    from workflow.steps import materialize_result_sections

    monkeypatch.setattr(session_db, "_latest_cache", lambda sdir, unit: {"sections": [
        {"platform": "Body Weight", "title": "Body Weight", "tables_json": {"rows": [2]},
         "narrative": [], "cat_signature": {}}]})
    prior = {"platform": "Body Weight", "title": "Body Weight", "tables_json": {"rows": [1]},
             "narrative": [], "cat_signature": {}, "source": "generated", "version": 1, **owned}
    store = FakeSectionStore({"bm2_body-weight": prior})
    out = materialize_result_sections("DTXSID_FK", store)
    assert [r["key"] for r in out["needs_review"]] == ["bm2_body-weight"]
    assert store.archives["bm2_body-weight"][0][1] == prior    # the owned text, kept
    now = store.sections["bm2_body-weight"]
    assert now["approved"] is False and now["review"]["since_version"] == 1
    assert now.get("facts", []) == ([] if owned.get("user_edited") else ["protected"])

    # A further change keeps the marker until a person re-accepts.
    monkeypatch.setattr(session_db, "_latest_cache", lambda sdir, unit: {"sections": [
        {"platform": "Body Weight", "title": "Body Weight", "tables_json": {"rows": [3]},
         "narrative": [], "cat_signature": {}}]})
    materialize_result_sections("DTXSID_FK", store)
    assert store.sections["bm2_body-weight"]["review"]["since_version"] == 1
