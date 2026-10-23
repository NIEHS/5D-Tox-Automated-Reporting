"""
narrative/prompt_workshop.py — the chat that improves a section's prompt template.

The author looks at a generated section (a run), says what is wrong with it, and
the assistant answers — and, when the fix is a change to how the section is
written, proposes a new version of the template. Nothing is saved by the
assistant: a proposal is shown as a diff, and the author accepts it into the
editor, adjusts it, or ignores it. Saving a version is the author's act
(pipeline.prompt_store.save_version).

A template is used for EVERY report, so the assistant is told to make changes
that generalize, to treat a factual complaint as a data issue rather than a
wording one, and to keep study-specific facts out of its rationale (the version
history is a record of how the prompt evolved, not of any one study).

A proposed template is test-rendered against the session before it is
returned; if it does not render, the assistant is asked once to fix it, and a
remaining error is returned with the proposal for the author to see.

For a published study, the published Summary (from the Bookshelf bundle
breakdown, assets/cebs/_bookshelf) is given as a reference — the wording NIEHS
actually printed.
"""

from __future__ import annotations

import json
import logging
import re

import common.paths as paths
from common.clock import now_iso
from common.paths import REPO_ROOT
from narrative import prompt_templates
from narrative.prompt_templates import TemplateError
from styling_export.llm_helpers import llm_generate_json_async

logger = logging.getLogger(__name__)

BOOKSHELF = REPO_ROOT / "assets" / "cebs" / "_bookshelf"
WORKSHOP_MODEL = "claude-sonnet-4-6"
MAX_HISTORY_TURNS = 12

_SYSTEM = """\
You help a toxicologist tune the PROMPT TEMPLATE that generates one section of
NIEHS/NTP biological potency reports. The same template is used for every report,
so your changes must generalize: fix the kind of problem, never one report's
wording. The author will show you the template, what it rendered to for one
study, the output it produced, and their critique.

How to answer:
- Explain briefly what in the template (or the model's behaviour under it)
  caused what the author dislikes.
- When a template change would fix it, propose the COMPLETE new template text
  (front matter included). Change only what is needed; keep the variables, the
  JSON output instruction and the front-matter keys (system, model, temperature,
  max_tokens) valid. Use only the variables listed.
- If the complaint is about a FACT (a wrong number, endpoint, gene, sex), say so:
  facts come from the data, not the template, and no template change can fix
  them. Propose nothing in that case.
- If you need more information, ask instead of proposing.
- The rationale is one or two sentences saying what the change does in general
  terms. Never put a chemical name, a number or any other study fact in it.

Return ONLY JSON: {"reply": "...", "proposed_template": "..." or null,
"rationale": "..." or ""}"""


def report_of(dtxsid: str) -> tuple[str | None, str | None]:
    """(published report, member study) for a session: ("NIEHS-10", None), or
    ("NIEHS-13", "rat") for one study of a report over several studies (the
    composed session's studies.json names its members), or (None, None) for an
    unpublished study."""
    try:
        from tooling.build_published_reports import STUDIES
    except ImportError:  # tooling absent in a slim deployment
        return None, None
    by_dtxsid = {row[0]: r for r, row in STUDIES.items()}
    if dtxsid in by_dtxsid:
        return by_dtxsid[dtxsid], None
    for parent, report in by_dtxsid.items():
        try:
            members = json.loads((paths.SESSIONS_DIR / parent / "studies.json").read_text())
        except (OSError, ValueError):
            continue
        for study, member in (members or {}).items():
            if member == dtxsid:
                return report, study
    return None, None


def published_date(report: str | None) -> str | None:
    """When a published report came out ("2023-03"), from its Bookshelf bundle
    breakdown; None for no report, or a bundle that is absent or undated."""
    if not report:
        return None
    try:
        meta = json.loads((BOOKSHELF / report / "breakdown" / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta.get("published") or None


def published_section(dtxsid: str, section: str) -> dict | None:
    """The published text of a section for a published study:
    {report, study, paragraphs}, or None (unpublished study, or the book has
    no such section — RR-8 has a Discussion, not a Summary). For one study of
    a report over several, it is the whole report's text (`study` says which
    study the session is)."""
    report, study = report_of(dtxsid)
    if not report:
        return None
    hits = sorted((BOOKSHELF / report / "breakdown" / "sections").glob(f"*_{section}.md"))
    if not hits:
        return None
    raw = hits[0].read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    raw = re.sub(r"^#.*$", "", raw, flags=re.M)
    raw = re.sub(r"<[^>]+>", "", raw)  # BMD<sub>L</sub> → BMDL
    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
    return {"report": report, "study": study, "paragraphs": paragraphs}


def _variable_list(section: str) -> str:
    return "\n".join(f"- {k}: {v}"
                     for k, v in prompt_templates.SECTIONS[section]["variables"].items())


def _paragraphs(run: dict | None) -> str:
    if not run:
        return "(none)"
    return "\n\n".join(f"[{i}] {p}" for i, p in enumerate(run.get("paragraphs") or [], 1))


def build_prompt(section: str, *, template: str, run: dict | None,
                 previous_run: dict | None, published: dict | None,
                 history: list[dict], message: str) -> str:
    """The user-turn text for one workshop turn."""
    parts = [
        f"SECTION: {prompt_templates.SECTIONS[section]['label']}",
        f"TEMPLATE VARIABLES:\n{_variable_list(section)}",
        f"CURRENT TEMPLATE (as in the author's editor):\n<<<\n{template}\n>>>",
    ]
    if run:
        prompt = run.get("prompt") or {}
        parts.append("WHAT THE TEMPLATE RENDERED TO FOR THIS STUDY:\n"
                     f"<<< system\n{prompt.get('system', '')}\n>>>\n"
                     f"<<< user\n{prompt.get('user', '')}\n>>>")
        parts.append(f"LATEST OUTPUT:\n{_paragraphs(run)}")
        if run.get("unmatched_numbers"):
            parts.append("NUMBERS IN THE OUTPUT THE MODEL WAS NOT GIVEN: "
                         + ", ".join(run["unmatched_numbers"]))
    if previous_run:
        parts.append(f"PREVIOUS OUTPUT (the run before):\n{_paragraphs(previous_run)}")
    if published:
        scope = (f" — the whole report; this session is its {published['study']} study"
                 if published.get("study") else "")
        parts.append(f"PUBLISHED TEXT ({published['report']}{scope}), for reference — the "
                     "wording NIEHS printed for this study:\n"
                     + "\n\n".join(published["paragraphs"]))
    if history:
        convo = []
        for m in history[-2 * MAX_HISTORY_TURNS:]:
            who = "AUTHOR" if m.get("role") == "user" else "YOU"
            convo.append(f"{who}: {m.get('content', '')}")
        parts.append("CONVERSATION SO FAR:\n" + "\n".join(convo))
    parts.append(f"AUTHOR NOW SAYS:\n{message}")
    return "\n\n".join(parts)


def _check(proposed: str | None, variables: dict) -> str | None:
    """The render error of a proposal, or None."""
    if not proposed:
        return None
    try:
        prompt_templates.render(proposed, variables)
        return None
    except TemplateError as e:
        return str(e)


async def workshop_turn(section: str, *, message: str, template: str, variables: dict,
                        run: dict | None = None, previous_run: dict | None = None,
                        published: dict | None = None, history: list[dict] | None = None,
                        model: str = WORKSHOP_MODEL, dtxsid: str | None = None) -> dict:
    """One workshop turn: {reply, proposed_template, rationale, render_error}.
    `dtxsid` is the study whose output is discussed: the model must be one
    narrative.model_policy allows for its data."""
    prompt_templates.validate_section(section)
    if dtxsid:
        from narrative import model_policy
        model_policy.check(dtxsid, [model])
    user = build_prompt(section, template=template, run=run, previous_run=previous_run,
                        published=published, history=history or [], message=message)
    result = await llm_generate_json_async("prompt-workshop", user, _SYSTEM,
                                           model=model, temperature=0.2, max_tokens=8192)
    if not isinstance(result, dict):
        result = {"reply": str(result)}
    proposed = result.get("proposed_template") or None
    error = _check(proposed, variables)
    if error:
        logger.info("workshop proposal did not render (%s) — asking once to fix", error)
        retry = (f"{user}\n\nYour proposed template does not render: {error}\n"
                 "Reply again with the corrected complete template.")
        again = await llm_generate_json_async("prompt-workshop", retry, _SYSTEM,
                                              model=model, temperature=0.2, max_tokens=8192)
        if isinstance(again, dict) and again.get("proposed_template"):
            result, proposed = again, again["proposed_template"]
            error = _check(proposed, variables)
    return {
        "reply": str(result.get("reply") or "").strip(),
        "proposed_template": proposed,
        "rationale": str(result.get("rationale") or "").strip(),
        "render_error": error,
    }


def append_turn(thread: dict, *, message: str, dtxsid: str, run_id: str | None,
                template_version: int | None, result: dict) -> None:
    """Record one turn on a workshop thread (pipeline.prompt_store saves it)."""
    now = now_iso()
    thread.setdefault("messages", []).append({
        "role": "user", "content": message, "at": now, "dtxsid": dtxsid,
        "run_id": run_id, "template_version": template_version,
    })
    thread["messages"].append({"role": "assistant", "content": result["reply"], "at": now,
                               **{k: result[k] for k in
                                  ("proposed_template", "rationale", "render_error")}})
    if not thread.get("title"):
        thread["title"] = message.strip().splitlines()[0][:80] if message.strip() else ""
