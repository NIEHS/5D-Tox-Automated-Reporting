"""The model-worded Summary: the template renders the facts code picked, the
run record keeps the exact prompt sent, and numbers the model was not given
are reported."""

import asyncio

import pytest

from narrative import summary_llm
from narrative.prompt_templates import TemplateError
from pipeline import prompt_store

_INPUTS = {
    "apical_bmd_summary": [
        {"sex": "Male", "endpoint": "Relative Liver Weight", "platform": "Organ Weight",
         "bmd": "36.7", "bmdl": "14.2", "loel": 125.0, "noel": 62.5, "direction": "UP",
         "bmd_status": "viable"}],
    "genomics_sections": {},
    "chemical_name": "Triclosan",
    "dose_groups": [0.0, 62.5, 125.0, 250.0],
    "dose_unit": "mg/kg",
    "bmd_stat": None,
    "sexes": ["Male"],
    "abstract_background": "",
    "apical_evaluated": True,
    "design": {"species": "rat", "route": "gavage", "duration_days": 5},
}


@pytest.fixture
def session(sessions_dir, monkeypatch):
    monkeypatch.setattr(summary_llm, "session_variables",
                        lambda dtxsid: summary_llm.template_variables(dict(_INPUTS)))
    return "DTXSID5032498"


def _fake_model(reply, seen):
    async def fake(name, prompt, system, **kw):
        seen.append({"name": name, "prompt": prompt, "system": system, **kw})
        return reply
    return fake


def test_variables_carry_the_draft_and_design():
    v = summary_llm.template_variables(dict(_INPUTS))
    assert any("36.7 (14.2) mg/kg" in p for p in v["draft_paragraphs"])
    assert (v["species"], v["route"], v["duration_days"]) == ("rats", "gavage", 5)
    assert v["has_genomics"] is False and v["apical_evaluated"] is True


def test_unmatched_numbers():
    v = summary_llm.template_variables(dict(_INPUTS))
    ok = ["In this 5-day study at 62.5 to 250 mg/kg, relative liver weight rose "
          "(BMD 36.7, BMDL 14.2 mg/kg)."]
    assert summary_llm.unmatched_numbers(ok, v) == []
    bad = ["The BMD was 36.70 (14) mg/kg; 1,250 animals."]
    assert summary_llm.unmatched_numbers(bad, v) == ["36.70", "14", "1250"]


def test_run_records_the_exact_prompt(session, monkeypatch):
    seen = []
    monkeypatch.setattr(summary_llm, "llm_generate_json_async",
                        _fake_model(["Relative liver weight increased (36.7 [14.2] mg/kg).",
                                     "It was 99.9 mg/kg."], seen))
    run = asyncio.run(summary_llm.generate_summary(session))
    assert run["template_version"] == 1
    assert run["prompt"]["user"] == seen[0]["prompt"]
    assert run["prompt"]["system"] == seen[0]["system"]
    assert "36.7 (14.2) mg/kg" in run["prompt"]["user"]
    assert run["unmatched_numbers"] == ["99.9"]
    assert prompt_store.load_run(session, "summary", run["run_id"]) == run
    assert prompt_store.list_runs(session, "summary")[0]["run_id"] == run["run_id"]


def test_unsaved_template_and_object_reply(session, monkeypatch):
    seen = []
    monkeypatch.setattr(summary_llm, "llm_generate_json_async",
                        _fake_model({"paragraphs": ["A."]}, seen))
    text = "---\nsystem: S\nmodel: m-1\ntemperature: 0\n---\nFacts: {{ draft_paragraphs|length }}"
    run = asyncio.run(summary_llm.generate_summary(session, text=text))
    assert run["template_version"] is None and run["paragraphs"] == ["A."]
    assert seen[0]["model"] == "m-1" and seen[0]["temperature"] == 0.0
    assert run["prompt"]["user"].startswith("Facts: ")


def test_no_results_is_a_template_error(sessions_dir, monkeypatch):
    monkeypatch.setattr(summary_llm, "session_variables",
                        lambda dtxsid: {"draft_paragraphs": []})
    with pytest.raises(TemplateError, match="Process"):
        summary_llm.render_for_session("DTXSID5032498")
