"""The workshop chat: what it shows the model, how it vets a proposed template,
and the published text it offers as reference."""

import asyncio

from narrative import prompt_templates, prompt_workshop

_GOOD = "---\nsystem: S\n---\nRewrite: {{ draft_paragraphs|join(' ') }}"
_BAD = "---\nsystem: S\n---\nRewrite: {{ drafts }}"
_VARS = {"draft_paragraphs": ["One."]}


def _model(*replies):
    calls = []

    async def fake(name, prompt, system, **kw):
        calls.append(prompt)
        return replies[len(calls) - 1]
    return fake, calls


def test_prompt_shows_template_run_published_and_history():
    run = {"run_id": "r1", "paragraphs": ["Out."], "unmatched_numbers": ["9"],
           "prompt": {"system": "SYS", "user": "USR"}}
    text = prompt_workshop.build_prompt(
        "summary", template=_GOOD, run=run, previous_run={"paragraphs": ["Old."]},
        published={"report": "NIEHS-10", "paragraphs": ["Pub."]},
        history=[{"role": "user", "content": "too long"}, {"role": "assistant", "content": "ok"}],
        message="still too long")
    for needle in (_GOOD, "SYS", "USR", "[1] Out.", "[1] Old.", "NIEHS-10", "Pub.",
                   "AUTHOR: too long", "YOU: ok", "still too long", "9",
                   "draft_paragraphs:"):
        assert needle in text, needle


def test_a_proposal_that_does_not_render_is_retried_once(monkeypatch):
    fake, calls = _model({"reply": "r", "proposed_template": _BAD, "rationale": "x"},
                         {"reply": "fixed", "proposed_template": _GOOD, "rationale": "y"})
    monkeypatch.setattr(prompt_workshop, "llm_generate_json_async", fake)
    out = asyncio.run(prompt_workshop.workshop_turn(
        "summary", message="m", template=_GOOD, variables=_VARS))
    assert len(calls) == 2 and "does not render" in calls[1]
    assert out == {"reply": "fixed", "proposed_template": _GOOD, "rationale": "y",
                   "render_error": None}


def test_a_remaining_render_error_is_returned(monkeypatch):
    bad = {"reply": "r", "proposed_template": _BAD, "rationale": ""}
    fake, _ = _model(bad, bad)
    monkeypatch.setattr(prompt_workshop, "llm_generate_json_async", fake)
    out = asyncio.run(prompt_workshop.workshop_turn(
        "summary", message="m", template=_GOOD, variables=_VARS))
    assert out["proposed_template"] == _BAD and "drafts" in out["render_error"]


def test_no_proposal_is_fine(monkeypatch):
    fake, calls = _model({"reply": "That BMD is a data issue.", "proposed_template": None})
    monkeypatch.setattr(prompt_workshop, "llm_generate_json_async", fake)
    out = asyncio.run(prompt_workshop.workshop_turn(
        "summary", message="wrong BMD", template=_GOOD, variables=_VARS))
    assert out["proposed_template"] is None and len(calls) == 1


def test_published_summary_lookup():
    pub = prompt_workshop.published_section("DTXSID50469320", "summary")  # NIEHS-10
    if pub is None:  # the Bookshelf bundles are untracked assets
        return
    assert pub["report"] == "NIEHS-10"
    assert "<sub>" not in " ".join(pub["paragraphs"])
    assert prompt_workshop.published_section("DTXSID0000000", "summary") is None


def test_append_turn():
    thread = {"messages": []}
    prompt_workshop.append_turn(thread, message="Too wordy\nmore", dtxsid="DTXSID1",
                                run_id="r1", template_version=2,
                                result={"reply": "ok", "proposed_template": None,
                                        "rationale": "", "render_error": None})
    assert thread["title"] == "Too wordy"
    assert thread["messages"][0]["run_id"] == "r1"
    assert thread["messages"][1]["content"] == "ok"
    assert prompt_templates.SECTIONS["summary"]["label"] == "Summary"
