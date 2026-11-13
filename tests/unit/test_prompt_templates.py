"""Section prompt templates: parsing, strict rendering, and the version store
(immutable versions, append-only index, rollback as a new entry)."""

import pytest

from narrative import prompt_templates
from narrative.prompt_templates import TemplateError, UnknownSection
from pipeline import prompt_store
from pipeline.prompt_store import UnknownVersion

_T = """---
system: |
  Write about {{ chemical_name }}.
temperature: 0.1
---
Draft: {% for p in draft_paragraphs %}{{ p }} {% endfor %}
"""


def test_render_fills_system_and_body():
    r = prompt_templates.render(_T, {"chemical_name": "X", "draft_paragraphs": ["a", "b"]})
    assert r.system == "Write about X."
    assert r.user == "Draft: a b"
    assert r.temperature == 0.1 and r.model == prompt_templates.DEFAULT_MODEL


def test_undefined_variable_is_an_error_naming_it():
    with pytest.raises(TemplateError, match="draft_paragraphs"):
        prompt_templates.render(_T, {"chemical_name": "X"})


@pytest.mark.parametrize("text, match", [
    ("no front matter", "front-matter"),
    ("---\nsystem: x\nbody without closing", "closing"),
    ("---\nmodel: m\n---\nbody", "system"),
    ("---\nsystem: x\ncolour: red\n---\nbody", "colour"),
    ("---\nsystem: x\n---\n{% for %}", "body, line"),
])
def test_bad_templates_say_why(text, match):
    with pytest.raises(TemplateError, match=match):
        prompt_templates.render(text, {})


def test_unknown_section():
    with pytest.raises(UnknownSection):
        prompt_templates.template_text("nope")


def test_shipped_summary_default_renders():
    text = prompt_templates.default_text("summary")
    variables = {k: "" for k in prompt_templates.SECTIONS["summary"]["variables"]}
    variables.update(draft_paragraphs=["One.", "Two."], sexes=["Male"], dose_groups=[0, 1],
                     apical_evaluated=True, has_genomics=False)
    r = prompt_templates.render(text, variables)
    assert "[1] One." in r.user and "[2] Two." in r.user
    assert "no transcriptomic results" in r.user and "no apical endpoints" not in r.user


def test_versions_are_immutable_and_rollback_appends(sessions_dir):
    assert prompt_store.current_version("summary") == 1
    assert prompt_templates.template_text("summary") == (
        prompt_templates.default_text("summary"), 1)

    v2 = prompt_store.save_version("summary", _T, rationale="shorter")
    v3 = prompt_store.save_version("summary", _T + "more", rationale="longer")
    assert (v2, v3) == (2, 3)
    assert prompt_store.current_version("summary") == 3
    assert [v["parent"] for v in prompt_store.versions("summary")] == [None, 1, 2]

    prompt_store.make_current("summary", 2, rationale="back")
    assert prompt_store.current_version("summary") == 2
    assert prompt_templates.template_text("summary") == (_T, 2)
    # Rolling back deleted nothing: v3 is still there, and a new save follows it.
    assert prompt_templates.template_text("summary", 3)[0].endswith("more")
    assert prompt_store.save_version("summary", _T) == 4
    assert prompt_store.versions("summary")[-1]["parent"] == 2

    with pytest.raises(UnknownVersion):
        prompt_store.make_current("summary", 9)
    with pytest.raises(UnknownVersion):
        prompt_templates.template_text("summary", 9)
