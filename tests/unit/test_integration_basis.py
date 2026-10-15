"""
C1 spec §3.2: the integration basis — whether the dataset on disk was built
from the validation on disk now, asked by file name since file ids are not
stable (the restart trap).
"""

from __future__ import annotations

from workflow.engine import WorkflowEngine
from workflow.integration_basis import (
    BASIS_FILE,
    VOLATILE_FP_FIELDS,
    compute_basis,
    integration_status,
    record_basis,
)
from workflow.phases import Phase


def _fp(fid, name, **extra):
    return {"file_id": fid, "filename": name, "platform": "Body Weight",
            "data_type": "tox_study", "n_animals_by_dose": {"0": 5},
            "ts_added": f"t-{fid}", "ts_filesystem": 1.0, "ts_internal": None, **extra}


def _report(ids=("a", "b"), names=("bw_m.csv", "bw.bm2"), **fp_extra):
    fps = {i: _fp(i, n, **fp_extra) for i, n in zip(ids, names)}
    return {"fingerprints": fps, "issues": [],
            "coverage_matrix": {"Body Weight|tox_study": {
                "xlsx": None, "txt_csv": [ids[0]], "bm2": ids[1]}}}


class Store:
    def __init__(self, docs=None, present=("integrated.json",), files=True):
        self.docs = dict(docs or {})
        self.present = set(present)
        self.files = files

    def read_json(self, dtxsid, name):
        return self.docs.get(name)

    def write_json(self, dtxsid, name, data):
        self.docs[name] = data

    def artifact_exists(self, dtxsid, name):
        return name in self.present

    def has_files(self, dtxsid):
        return self.files

    def has_stale_sections(self, dtxsid):
        return False

    def session_dir(self, dtxsid):
        import tempfile
        from pathlib import Path
        return Path(tempfile.gettempdir())


def test_volatile_fields_are_the_methods_cache_keys():
    from pipeline.cache_plumbing import _METHODS_VOLATILE_FP_FIELDS
    assert VOLATILE_FP_FIELDS == _METHODS_VOLATILE_FP_FIELDS


def test_stable_across_validations_that_mint_new_ids():
    first = compute_basis(_report(ids=("a", "b")), [])
    again = compute_basis(_report(ids=("scan-bw_m.csv", "uuid-77")), [])
    assert first == again and first is not None


def test_changes_with_the_data_and_the_files():
    base = compute_basis(_report(), [])
    assert compute_basis(_report(n_animals_by_dose={"0": 4}), []) != base
    assert compute_basis(_report(names=("bw_f.csv", "bw.bm2")), []) != base


def test_a_conflict_choice_changes_it_by_file_name():
    report = _report()
    base = compute_basis(report, [])
    chose = compute_basis(report, [{"issue_index": 0, "chosen_file_id": "a",
                                    "resolved_at": "now"}])
    assert chose != base
    # The same choice made on a re-validation with other ids, at another time.
    again = compute_basis(_report(ids=("x", "y")), [{"issue_index": 0, "chosen_file_id": "x",
                                                     "resolved_at": "later"}])
    assert again == chose


def test_no_report_no_basis():
    assert compute_basis(None, []) is None


def test_status_none_unrecorded_current_out_of_date():
    store = Store(present=())
    assert integration_status("D", store) is None
    store = Store(docs={"validation_report.json": _report()})
    assert integration_status("D", store) == "unrecorded"
    record_basis("D", store)
    assert set(store.docs[BASIS_FILE]) == {"basis", "integrated_at"}
    assert integration_status("D", store) == "current"
    store.docs["precedence.json"] = [{"issue_index": 0, "chosen_file_id": "b"}]
    assert integration_status("D", store) == "out_of_date"


def test_out_of_date_reads_validated_and_unrecorded_counts_as_current():
    store = Store(docs={"validation_report.json": _report()},
                  present=("integrated.json", "animal_report.json"))
    eng = WorkflowEngine("D", store)
    st = eng.state()
    assert (st.phase, st.artifacts["integration"]) == (Phase.APPROVED, "unrecorded")

    record_basis("D", store)
    assert eng.state().phase is Phase.APPROVED
    assert eng.state().artifacts["integration"] == "current"

    store.docs["validation_report.json"] = _report(names=("bw_f.csv", "bw.bm2"))
    st = eng.state()
    assert st.phase is Phase.VALIDATED
    assert st.artifacts["integration"] == "out_of_date"
    assert st.artifacts["hasIntegrated"] is True        # the raw flag is kept
    assert st.to_dict()["artifacts"]["integration"] == "out_of_date"


def test_the_refusal_at_an_out_of_date_integration_says_integrate_again():
    import pytest
    from workflow.engine import require_legal
    from workflow.errors import PhaseRefusal
    from workflow.refusals import explain

    store = Store(docs={"validation_report.json": _report(),
                        BASIS_FILE: {"basis": "0" * 16}})
    with pytest.raises(PhaseRefusal) as ei:
        require_legal("D", "PROCESS", store)
    assert ei.value.message.endswith(
        "Its integration was built from a different validation; integrate again.")
    body = explain(ei.value)["error"]
    assert body["say"] == (
        "Processing isn't possible yet. The study's dataset was combined from an earlier "
        "file check that no longer matches its files. Integrate the study again first.")
    assert body["fix"] == "M3"
    assert body["details"]["integration"] == "out_of_date"
