"""
The safeguards on what a person states, where a Background comes from, and
when the report ships (safeguards.inputs, .sources, .publish), and that the
core under them (what the notebook calls) writes as given.
"""

import json

import pytest

from safeguards.refusals import Refused, explain

ID = "DTXSID_SGP5"

_INTEGRATED = {"doseResponseExperiments": [
    {"name": "BodyWeightMale", "experimentDescription": {"sex": "male", "organ": "Whole"}},
]}
_VOCAB = {"sex": ["male", "female"], "organ": ["liver"],
          "strain": {"rat": ["Sprague Dawley"], "mouse": ["B6C3F1/N"]}}


# --- inputs --------------------------------------------------------------------

def test_experiment_metadata_errors_name_every_problem():
    from safeguards.inputs import experiment_metadata_errors
    errors = experiment_metadata_errors(
        {"Nope": {}, "BodyWeightMale": {"sex": "Male", "organ": "kidney"}},
        _INTEGRATED, _VOCAB)
    assert errors == ["unknown experiment 'Nope'",
                      "BodyWeightMale: sex='Male' is not in the vocabulary",
                      "BodyWeightMale: organ='kidney' is not in the vocabulary"]


def test_experiment_metadata_values_already_on_the_dataset_or_unstated_pass():
    from safeguards.inputs import experiment_metadata_errors
    # "Whole" is not the vocabulary's, but the dataset already carries it.
    assert experiment_metadata_errors(
        {"BodyWeightMale": {"organ": "Whole", "sex": None, "species": ""}},
        _INTEGRATED, _VOCAB) == []


def test_a_strain_is_checked_against_every_species_strains():
    # strain's vocabulary is by species: a strain name passes, a species name not.
    from safeguards.inputs import experiment_metadata_errors
    assert experiment_metadata_errors({"BodyWeightMale": {"strain": "Sprague Dawley"}},
                                      _INTEGRATED, _VOCAB) == []
    assert experiment_metadata_errors({"BodyWeightMale": {"strain": "rat"}},
                                      _INTEGRATED, _VOCAB)


def test_the_shape_is_checked():
    from safeguards.inputs import experiment_metadata_errors
    assert experiment_metadata_errors({"BodyWeightMale": "male"}, _INTEGRATED, _VOCAB) == [
        "expected {experiment name: {field: value}}"]


def test_a_design_outside_the_vocabulary_is_refused_and_explained():
    from safeguards.inputs import require_valid_design
    with pytest.raises(Refused) as e:
        require_valid_design(ID, {"articleRoute": "teleported", "colour": "blue"})
    body = explain(e.value)["error"]
    assert body["code"] == "facts_invalid" and body["fix"] == "facts"
    assert body["status"] == 422 and "the study design" in body["say"]
    assert len(body["details"]["errors"]) == 2


def test_guarded_design_refuses_and_writes_nothing(sessions_dir, monkeypatch):
    import safeguards.guarded as guarded
    from workflow.store import DiskPoolStore
    monkeypatch.setattr(guarded, "require", lambda *a, **k: None)   # the phase: legal
    (sessions_dir / ID).mkdir()
    with pytest.raises(Refused):
        guarded.record_study_design(ID, {"articleRoute": "teleported"}, DiskPoolStore())
    assert not (sessions_dir / ID / "study_design.json").exists()


def test_the_core_records_a_design_as_given(sessions_dir):
    # The notebook's path: no vocabulary check (the safeguards' only).
    from tooling import generate_report as gr
    from workflow.store import DiskPoolStore
    (sessions_dir / ID).mkdir()
    gr.apply_design(ID, {"articleRoute": "teleported"}, DiskPoolStore())
    saved = json.loads((sessions_dir / ID / "study_design.json").read_text())
    assert saved["fields"] == {"articleRoute": "teleported"}


def test_the_web_approval_refuses_values_outside_the_vocabulary(client, sessions_dir,
                                                                monkeypatch):
    import pipeline.metadata_approval  # noqa: F401 — bound to the real loader first
    import safeguards.guarded as guarded
    monkeypatch.setattr(guarded, "require", lambda *a, **k: None)
    monkeypatch.setattr("pipeline.integrated_io.load_integrated", lambda d: _INTEGRATED)
    called = []
    monkeypatch.setattr("pipeline.metadata_approval.approve_experiment_metadata",
                        lambda *a, **k: called.append(a) or {"updated": 1, "bm2_exported": True})
    (sessions_dir / ID).mkdir()
    r = client.post(f"/api/experiment-metadata/{ID}",
                    json={"metadata": {"BodyWeightMale": {"sex": "Male"}}})
    assert r.status_code == 422 and r.json()["code"] == "facts_invalid"
    assert called == []


# --- sources -------------------------------------------------------------------

class _Data:
    def __init__(self, unreachable):
        self.unreachable_sources = unreachable


def test_no_background_without_its_hazard_sources():
    from safeguards.sources import require_sources
    require_sources(ID, _Data(["CTX"]))                   # another source: fine
    with pytest.raises(Refused) as e:
        require_sources(ID, _Data(["ATSDR", "IRIS"]))
    body = explain(e.value)["error"]
    assert body["code"] == "background_sources_unreachable" and "ATSDR, IRIS" in body["say"]


def test_no_background_without_references():
    from safeguards.sources import require_references
    require_references(ID, {"paragraphs": ["p"], "references": [{"n": 1}]})
    with pytest.raises(Refused, match="no paragraphs"):
        require_references(ID, {"paragraphs": [], "references": [{"n": 1}]})
    with pytest.raises(Refused) as e:
        require_references(ID, {"paragraphs": ["p"], "references": []})
    assert e.value.code == "background_no_references"


@pytest.fixture
def gen(monkeypatch):
    import narrative.background_writer as bw
    import narrative.data_gatherer as dg
    import narrative.chem_resolver as cr
    from tooling import generate_report
    monkeypatch.setattr(dg, "gather_all", lambda ident, log: _Data(["ATSDR"]))
    calls = []
    monkeypatch.setattr(bw, "generate_background", lambda data, model: calls.append(model) or {
        "paragraphs": ["p"], "references": [{"n": 1}], "model_used": "m"})
    monkeypatch.setattr(cr.ChemicalIdentity, "from_dict", staticmethod(lambda d: d))
    generate_report.calls = calls
    return generate_report


def test_the_command_line_refuses_a_background_without_atsdr(gen, sessions_dir, capsys):
    from workflow.store import DiskPoolStore
    (sessions_dir / ID).mkdir()
    gen.background(ID, {"pubchem_cid": 1}, "m", DiskPoolStore(), guarded=True)
    assert gen.calls == [] and not (sessions_dir / ID / "background.json").exists()
    assert "background_sources_unreachable" in capsys.readouterr().out


def test_the_notebook_may_draft_a_background_without_atsdr(gen, sessions_dir):
    from workflow.store import DiskPoolStore
    (sessions_dir / ID).mkdir()
    gen.background(ID, {"pubchem_cid": 1}, "m", DiskPoolStore())
    assert gen.calls == ["m"] and (sessions_dir / ID / "background.json").exists()


# --- the publish gate ----------------------------------------------------------

def _stale(sessions_dir):
    d = sessions_dir / ID
    d.mkdir(exist_ok=True)
    (d / "genomics_liver_male.json").write_text(json.dumps(
        {"approved": True, "stale": True, "regenerated": {"reason": "data_changed"}}))


def test_the_publish_gate_refuses_and_draft_overrides(sessions_dir, caplog):
    from safeguards.publish import require_publishable
    from workflow.store import DiskPoolStore
    assert require_publishable(ID, DiskPoolStore())["can_publish"] is True
    _stale(sessions_dir)
    with pytest.raises(Refused) as e:
        require_publishable(ID, DiskPoolStore())
    body = explain(e.value)["error"]
    assert body["code"] == "publish_blocked" and "genomics_liver_male" in body["say"]
    assert body["fix"] == "sections"
    with caplog.at_level("WARNING", logger="safeguards.publish"):
        r = require_publishable(ID, DiskPoolStore(), draft=True)
    assert r["can_publish"] is False and "as a draft" in caplog.text


def test_the_download_is_gated_with_an_explanation(client, sessions_dir):
    _stale(sessions_dir)
    r = client.get(f"/api/preview/{ID}/download")
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "publish_blocked" and body["say"]
    assert body["blocking"] == [{"section_key": "genomics_liver_male",
                                 "reason": "data_changed"}]
    assert body["error"].startswith("Report is not publishable")
