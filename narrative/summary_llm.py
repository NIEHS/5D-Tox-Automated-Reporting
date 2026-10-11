"""
narrative/summary_llm.py — the Summary, worded by a model from facts code chose.

The facts come from narrative.report_summary: the Summary built from the study's
results with fixed wording (the "draft"). A section prompt template
(narrative.prompt_templates, section "summary") asks the model to rewrite that
draft as prose; it may not add or change a fact. Every number in the output is
then checked against the numbers the model was given, and any it was not given
is reported as unmatched — shown to the author, never silently dropped.

Each generation is saved as a run record (pipeline.prompt_store) holding the
exact system and user prompt sent, so the author can see what produced a
paragraph and how the prompt has changed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from narrative import prompt_templates
from narrative.prompt_templates import RenderedPrompt, TemplateError
from pipeline import prompt_store
from styling_export.llm_helpers import llm_generate_json_async

SECTION = "summary"

# A number as prose writes it: 7.264, 0.510, 1,250, 10. Thousands separators
# are dropped before comparison; decimals are kept, so a rounded BMD differs.
_NUMBER_RE = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?")


def summary_inputs(session_dir: Path) -> dict:
    """The keyword arguments of report_summary.build_report_summary for a
    session, read from its Process caches — the same inputs as the Abstract."""
    from pipeline.session_db import _latest_cache
    from pipeline.study_design import study_design_facts
    from rendering.render_common import derive_study_sexes

    def _read(name: str) -> dict:
        try:
            return json.loads((session_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    bmd = _latest_cache(session_dir, "bmd_summary") or {}
    genomics = _latest_cache(session_dir, "genomics") or {}
    methods = (_latest_cache(session_dir, "methods") or {}).get("context") or {}
    sections = (_latest_cache(session_dir, "sections") or {}).get("sections") or []
    integrated = _read("integrated.json")
    identity = _read("identity.json")
    stat_order = next((v.get("stat_order") for v in genomics.values()
                       if isinstance(v, dict) and v.get("stat_order")), None)
    return {
        "apical_bmd_summary": bmd.get("apical") or [],
        "genomics_sections": {k: v for k, v in genomics.items() if isinstance(v, dict)},
        "chemical_name": methods.get("chemical_name") or identity.get("name")
                         or session_dir.name,
        "dose_groups": methods.get("dose_groups") or [],
        "dose_unit": methods.get("dose_unit") or "mg/kg",
        "bmd_stat": (stat_order or [None])[0],
        "sexes": derive_study_sexes(integrated),
        "abstract_background": _read("background.json").get("abstract_background", "") or "",
        "apical_evaluated": bool(sections),
        "design": study_design_facts(integrated, methods.get("dose_unit")),
    }


def template_variables(inputs: dict) -> dict:
    """The summary template's variables (prompt_templates.SECTIONS["summary"])."""
    from narrative.report_summary import build_report_summary
    from pipeline.study_design import design_or_standard, species_plural

    design = design_or_standard(inputs.get("design"))
    return {
        "draft_paragraphs": build_report_summary(**inputs),
        "chemical_name": inputs["chemical_name"],
        "species": species_plural(design),
        "strain": design.get("strain") or "",
        "route": design.get("route") or "",
        "duration_days": design.get("duration_days") or "",
        "sexes": list(inputs.get("sexes") or []),
        "dose_unit": inputs.get("dose_unit") or "",
        "dose_groups": list(inputs.get("dose_groups") or []),
        "abstract_background": inputs.get("abstract_background") or "",
        "apical_evaluated": bool(inputs.get("apical_evaluated")),
        "has_genomics": bool(inputs.get("genomics_sections")),
    }


def session_variables(dtxsid: str) -> dict:
    from pipeline.session_store import session_dir
    return template_variables(summary_inputs(session_dir(dtxsid)))


def _numbers(text: str) -> list[str]:
    return [m.group(0).replace(",", "") for m in _NUMBER_RE.finditer(text or "")]


def _dose_tokens(dose: object) -> set[str]:
    try:
        f = float(dose)
    except (TypeError, ValueError):
        return set()
    return {str(dose), f"{f:g}", str(int(f)) if f.is_integer() else f"{f:g}"}


def unmatched_numbers(paragraphs: list[str], variables: dict) -> list[str]:
    """Numbers in the output that the model was not given (in order, once
    each). The draft, the abstract background, the dose levels and the
    duration are what it was given."""
    given: set[str] = set()
    for p in variables.get("draft_paragraphs") or []:
        given.update(_numbers(p))
    given.update(_numbers(variables.get("abstract_background") or ""))
    for d in variables.get("dose_groups") or []:
        given.update(_dose_tokens(d))
    if variables.get("duration_days"):
        given.add(str(variables["duration_days"]))
    out: list[str] = []
    for n in _numbers(" ".join(paragraphs)):
        if n not in given and n not in out:
            out.append(n)
    return out


def render_for_session(dtxsid: str, text: str | None = None) -> tuple[RenderedPrompt, dict]:
    """(rendered prompt, variables) for a session — `text` is an unsaved
    template, else the current version. Raises TemplateError."""
    if text is None:
        text, _ = prompt_templates.template_text(SECTION)
    variables = session_variables(dtxsid)
    if not variables["draft_paragraphs"]:
        raise TemplateError("This session has no results to summarize yet "
                            "(run Process first).")
    return prompt_templates.render(text, variables), variables


async def generate_summary(dtxsid: str, *, text: str | None = None,
                           version: int | None = None) -> dict:
    """Generate the Summary for a session and save the run; return the run
    record. `text` runs an unsaved edit; `version` a saved version; neither,
    the current version. Raises TemplateError (template) or the model call's
    exception."""
    if text is None:
        text, version = prompt_templates.template_text(SECTION, version)
        label = version
    else:
        label = None  # an unsaved edit
    rendered, variables = render_for_session(dtxsid, text)
    result = await llm_generate_json_async(
        "summary-generator", rendered.user, rendered.system,
        model=rendered.model, temperature=rendered.temperature,
        max_tokens=rendered.max_tokens,
    )
    if isinstance(result, dict):  # {"paragraphs": [...]} is accepted too
        result = result.get("paragraphs", [])
    paragraphs = [str(p).strip() for p in (result if isinstance(result, list) else [result])
                  if str(p).strip()]
    record = {
        "section": SECTION,
        "dtxsid": dtxsid,
        "template_version": label,
        "template": text,
        "prompt": rendered.to_dict(),
        "draft_paragraphs": variables["draft_paragraphs"],
        "paragraphs": paragraphs,
        "unmatched_numbers": unmatched_numbers(paragraphs, variables),
    }
    return prompt_store.save_run(dtxsid, SECTION, record)


# The name web_routes.prompt_routes calls for every templated section.
generate = generate_summary
