"""Model comparisons: models × repetitions, a blind arbiter that is never a
generator, the model policy for unpublished data, and the archive."""

import asyncio
import json
import random

import pytest

from narrative import model_policy, narrative_compare, prompt_workshop, summary_llm
from narrative.model_policy import ModelNotAllowed
from narrative.narrative_compare import ComparisonError
from pipeline import prompt_store

_PUB = "DTXSID50469320"     # NIEHS-10
_UNPUB = "DTXSID5032498"    # Triclosan
_VARS = {"draft_paragraphs": ["Liver weight rose at 36.7 (14.2) mg/kg."], "chemical_name": "X",
         "species": "rats", "strain": "", "route": "", "duration_days": 5, "sexes": ["Male"],
         "dose_unit": "mg/kg", "dose_groups": [0, 10], "abstract_background": "",
         "apical_evaluated": True, "has_genomics": False}


@pytest.fixture
def models(sessions_dir, monkeypatch):
    """Stub generation (each call a distinct sample) and the arbiter."""
    calls = []
    monkeypatch.setattr(summary_llm, "session_variables", lambda d: dict(_VARS))

    async def generate(name, prompt, system, **kw):
        calls.append({"name": name, **kw})
        n = sum(1 for c in calls if c["name"] == name)
        if kw["model"] == "broken-model":
            raise RuntimeError("boom")
        return [f"{kw['model']} sample {n}: liver weight rose (36.7, BMDL 14.2 mg/kg)."]
    monkeypatch.setattr(summary_llm, "llm_generate_json_async", generate)

    async def arbiter(name, prompt, system, **kw):
        calls.append({"name": name, "prompt": prompt, **kw})
        return {"overview": "ok", "agreements": [], "differences": [], "fact_problems": [],
                "generators": [], "recommendation": {"draft": "A2", "reasons": "clearest"}}
    monkeypatch.setattr(narrative_compare, "llm_generate_json_async", arbiter)
    monkeypatch.setattr(prompt_workshop, "published_section", lambda d, s: None)
    return calls


def test_policy_published_vs_unpublished(monkeypatch):
    assert model_policy.allowed(_PUB, "gemini-2.5-pro")
    assert model_policy.allowed(_UNPUB, "claude-sonnet-4.6")
    assert model_policy.allowed(_UNPUB, "azure-gpt-5")
    assert not model_policy.allowed(_UNPUB, "gemini-2.5-pro")
    with pytest.raises(ModelNotAllowed, match="gemini-2.5-pro"):
        model_policy.check(_UNPUB, ["claude-sonnet-4.6", "gemini-2.5-pro"])


def test_requests_that_cannot_run(models):
    def run(**kw):
        args = dict(generators=["claude-sonnet-4.6"], repetitions=1, arbiter="azure-gpt-5")
        args.update(kw)
        return asyncio.run(narrative_compare.run_comparison(_PUB, **args))
    with pytest.raises(ComparisonError, match="cannot also be"):
        run(arbiter="claude-sonnet-4.6")
    with pytest.raises(ComparisonError, match="at least one"):
        run(generators=[])
    with pytest.raises(ComparisonError, match="1–5"):
        run(repetitions=9)
    with pytest.raises(ModelNotAllowed):
        asyncio.run(narrative_compare.run_comparison(
            _UNPUB, generators=["gemini-2.5-pro"], repetitions=1, arbiter="azure-gpt-5"))
    assert models == []  # nothing was sent


def test_comparison_runs_reviews_blind_and_archives(models):
    events = []

    async def emit(e, d):
        events.append(e)
    rec = asyncio.run(narrative_compare.run_comparison(
        _PUB, generators=["claude-sonnet-4.6", "azure-gpt-5", "broken-model"], repetitions=2,
        arbiter="claude-opus-4.8", emit=emit, rng=random.Random(0)))

    assert rec["status"] == "complete" and rec["number"] == 1
    assert len(rec["outputs"]) == 6
    assert sum(1 for o in rec["outputs"] if o["error"]) == 2
    gens = [c for c in models if c["name"] == "summary-generator"]
    assert all(c["no_cache"] for c in gens)  # repetitions are real samples
    # Blind: the arbiter sees letters, never model names; the key is archived.
    arb = next(c for c in models if c["name"] == "narrative-arbiter")
    assert arb["model"] == "claude-opus-4.8"
    assert "duration: 5 days" in arb["prompt"]  # the facts the generators had
    drafts_text = arb["prompt"][arb["prompt"].index("DRAFT"):]
    assert "DRAFT A1" in drafts_text and "DRAFT B2" in drafts_text and "DRAFT C" not in drafts_text
    key = rec["blinding"]["drafts"]
    assert set(key) == {"A1", "A2", "B1", "B2"}
    rec_model = rec["review"]["recommendation"]
    assert rec_model["model"] == key["A2"]["model"] and rec_model["run_id"] == key["A2"]["run_id"]
    assert events[0] == "started" and events[-1] == "complete" and "arbiter" in events

    # Archived, final, listed; each output is also an ordinary run.
    stored = prompt_store.load_comparison(_PUB, "summary", rec["comparison_id"])
    assert stored == json.loads(json.dumps(rec))
    with pytest.raises(ValueError, match="final"):
        prompt_store.save_comparison(_PUB, "summary", stored)
    [summary] = prompt_store.list_comparisons(_PUB, "summary")
    assert summary["recommended_model"] == rec_model["model"]
    run = prompt_store.load_run(_PUB, "summary", key["A1"]["run_id"])
    assert run["comparison_id"] == rec["comparison_id"] and run["repetition"] == 1


def test_comparisons_are_numbered_per_study(models):
    for _ in range(2):
        asyncio.run(narrative_compare.run_comparison(
            _PUB, generators=["claude-sonnet-4.6"], repetitions=1, arbiter="azure-gpt-5"))
    assert [c["number"] for c in prompt_store.list_comparisons(_PUB, "summary")] == [2, 1]


def test_routes(models, client, monkeypatch):
    import web_routes.llm_routes as llm_routes
    monkeypatch.setattr(llm_routes, "model_catalog", lambda: {"degraded": False, "categories": [
        {"name": "Google (Gemini)", "models": ["gemini-2.5-pro", "gemini-3.1-flash-tts-preview"]}]})
    m = client.get(f"/api/prompts/summary/models/{_UNPUB}").json()
    assert m["published"] is False and "claude-*" in m["unpublished_allowed"]
    assert m["categories"] == [{"name": "Google (Gemini)",
                                "models": [{"id": "gemini-2.5-pro", "allowed": False}]}]
    assert client.post("/api/prompts/summary/compare", json={
        "dtxsid": _UNPUB, "generators": ["gemini-2.5-pro"], "repetitions": 1,
        "arbiter": "azure-gpt-5"}).status_code == 403
    assert client.post("/api/prompts/summary/compare", json={
        "dtxsid": _PUB, "generators": ["azure-gpt-5"], "repetitions": 1,
        "arbiter": "azure-gpt-5"}).status_code == 400
    r = client.post("/api/prompts/summary/compare", json={
        "dtxsid": _PUB, "generators": ["claude-sonnet-4.6"], "repetitions": 2,
        "arbiter": "azure-gpt-5"})
    assert r.status_code == 200 and "event: complete" in r.text
    [c] = client.get(f"/api/prompts/summary/comparisons/{_PUB}").json()["comparisons"]
    full = client.get(f"/api/prompts/summary/comparisons/{_PUB}/{c['comparison_id']}").json()
    assert full["status"] == "complete" and len(full["outputs"]) == 2
    assert client.get(f"/api/prompts/summary/comparisons/{_PUB}/c999").status_code == 404
