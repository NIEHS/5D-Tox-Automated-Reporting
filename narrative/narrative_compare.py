"""
narrative/narrative_compare.py — run a section's prompt on several models,
several times each, and have an arbiter model compare the results.

A comparison is one study, one template (a saved version or the editor's
unsaved text), the generator models the author chose, a repetition count, and
an arbiter model that is NOT one of the generators. Each generation is an
ordinary run (narrative.summary_llm: the exact prompt is saved, the gateway's
response cache is bypassed so repetitions are real samples, numbers the model
was not given are listed). The arbiter then reviews them BLIND: each generator
becomes a letter in a shuffled order and its runs A1, A2, …; the mapping back
to model names is kept in the archived record, never shown to the arbiter.

The arbiter compares and recommends; it decides nothing. Its answer, the exact
prompt it was given and the blinding key are archived with the runs as one
numbered comparison per study (pipeline.prompt_store), final once complete.

Every model — generators and arbiter — must be allowed by
narrative.model_policy for the study's data.
"""

from __future__ import annotations

import asyncio
import logging
import random
import string
from typing import Awaitable, Callable

from common.clock import now_iso
from narrative import model_policy, prompt_templates, prompt_workshop, summary_llm
from pipeline import prompt_store
from styling_export.llm_helpers import llm_generate_json_async

logger = logging.getLogger(__name__)

SECTION = "summary"
MAX_GENERATORS = 6
MAX_REPETITIONS = 5
PARALLEL = 4  # generations in flight at once

EmitFn = Callable[[str, dict], Awaitable[None]]


class ComparisonError(ValueError):
    """A comparison request that cannot run (bad models or counts)."""


_ARBITER_SYSTEM = """\
You review drafts of one section of a NIEHS/NTP biological potency report. Several
generators each wrote the section one or more times from the same prompt and the
same facts. You do not know which model wrote which; do not guess.

Judge each draft against the FACTS: every number, endpoint, gene, gene set, sex and
species a draft states must come from them, unchanged (same decimals). The published
text, when given, shows the wording and conventions NIEHS used for this study; its
numbers may come from a different analysis method, so never treat a difference from
the published numbers as an error — only a difference from the FACTS.

Assess:
- where the drafts agree and where they differ (content, emphasis, order, wording);
- every factual problem (a stated fact or number not in the FACTS, a dropped or
  changed fact, a wrong direction or sex), naming the draft;
- each generator's consistency across its own runs, and its strengths and weaknesses
  as NIEHS report prose;
- which single draft you would recommend, and why. Recommend a draft with a factual
  problem only if every draft has one, and say so.

Return ONLY JSON:
{"overview": "2-4 sentences",
 "agreements": ["..."],
 "differences": [{"topic": "...", "detail": "...", "drafts": ["A1", "B2"]}],
 "fact_problems": [{"draft": "B1", "problem": "..."}],
 "generators": [{"generator": "A", "consistency": "...", "strengths": "...",
                 "weaknesses": "..."}],
 "recommendation": {"draft": "A2", "reasons": "..."}}"""


def _validate(dtxsid: str, generators: list[str], repetitions: int, arbiter: str) -> list[str]:
    gens = list(dict.fromkeys(g.strip() for g in generators if g and g.strip()))
    if not gens:
        raise ComparisonError("choose at least one model to generate with")
    if len(gens) > MAX_GENERATORS:
        raise ComparisonError(f"at most {MAX_GENERATORS} generating models")
    if not 1 <= int(repetitions) <= MAX_REPETITIONS:
        raise ComparisonError(f"runs per model must be 1–{MAX_REPETITIONS}")
    if not arbiter or not arbiter.strip():
        raise ComparisonError("choose an arbiter model")
    if arbiter in gens:
        raise ComparisonError("the arbiter cannot also be a generating model")
    model_policy.check(dtxsid, gens + [arbiter])
    return gens


def blind_labels(generators: list[str], rng: random.Random | None = None) -> dict[str, str]:
    """model → letter, in a shuffled order."""
    order = list(generators)
    (rng or random.Random()).shuffle(order)
    return {m: string.ascii_uppercase[i] for i, m in enumerate(order)}


def study_facts(variables: dict) -> str:
    """The study-design facts the generators' prompt states besides the draft
    (so the arbiter does not flag, say, a stated duration as invented)."""
    items = [("test article", variables.get("chemical_name")), ("species", variables.get("species")),
             ("strain", variables.get("strain")), ("route", variables.get("route")),
             ("duration", f"{variables['duration_days']} days" if variables.get("duration_days") else ""),
             ("dose unit", variables.get("dose_unit")),
             ("dose levels", ", ".join(f"{d:g}" if isinstance(d, (int, float)) else str(d)
                                       for d in variables.get("dose_groups") or []))]
    return "; ".join(f"{k}: {v}" for k, v in items if v)


def arbiter_prompt(variables: dict, published: dict | None, drafts: dict[str, dict]) -> str:
    """The arbiter's user prompt: the facts the generators were given (the
    template variables), the published text, and `drafts` — a blind label
    ("A1") → {paragraphs, unmatched_numbers}, in label order."""
    parts = ["FACTS (chosen by code from the study's results; the only source of facts)\n"
             f"Study: {study_facts(variables)}\n"
             + "\n".join(f"[{i}] {p}" for i, p in enumerate(variables["draft_paragraphs"], 1))]
    if published:
        scope = (f" — the whole report; this study is its {published['study']} study"
                 if published.get("study") else "")
        parts.append(f"PUBLISHED TEXT ({published['report']}{scope}), for wording and "
                     "conventions only\n" + "\n\n".join(published["paragraphs"]))
    for label, d in drafts.items():
        check = (f"\n(automated check: numbers not in the facts: {', '.join(d['unmatched_numbers'])})"
                 if d.get("unmatched_numbers") else "")
        parts.append(f"DRAFT {label}\n" + "\n\n".join(d["paragraphs"]) + check)
    return "\n\n".join(parts)


def unblind(review: dict, key: dict[str, dict]) -> dict:
    """The arbiter's review with each draft label resolved to its model and run
    ({label: {model, repetition, run_id}}); an unknown recommended label is
    recorded, not guessed."""
    out = dict(review)
    rec = dict(out.get("recommendation") or {})
    label = str(rec.get("draft") or "").strip()
    if label in key:
        rec.update({"model": key[label]["model"], "repetition": key[label]["repetition"],
                    "run_id": key[label]["run_id"]})
    elif label:
        rec["unknown_draft"] = True
    out["recommendation"] = rec
    return out


async def run_comparison(dtxsid: str, *, generators: list[str], repetitions: int, arbiter: str,
                         text: str | None = None, version: int | None = None,
                         emit: EmitFn | None = None, rng: random.Random | None = None) -> dict:
    """Run the comparison and archive it; return the final record. Raises
    ComparisonError / ModelNotAllowed / TemplateError before anything runs."""
    async def say(event: str, data: dict) -> None:
        if emit:
            await emit(event, data)

    gens = _validate(dtxsid, generators, repetitions, arbiter)
    if text is None:
        text, label = prompt_templates.template_text(SECTION, version)
    else:
        label = None
    _, variables = summary_llm.render_for_session(dtxsid, text)  # fail early on the template

    record = prompt_store.new_comparison(dtxsid, SECTION, {
        "section": SECTION, "dtxsid": dtxsid, "template_version": label, "template": text,
        "generators": gens, "repetitions": int(repetitions), "arbiter_model": arbiter,
        "outputs": [], "review": None,
    })
    cid = record["comparison_id"]
    total = len(gens) * int(repetitions)
    await say("started", {"comparison_id": cid, "number": record["number"], "total": total})

    sem = asyncio.Semaphore(PARALLEL)
    lock = asyncio.Lock()

    async def one(model: str, rep: int) -> None:
        async with sem:
            try:
                run = await summary_llm.generate_summary(
                    dtxsid, text=text if label is None else None, version=label,
                    model=model, comparison_id=cid, repetition=rep)
                out = {"model": model, "repetition": rep, "run_id": run["run_id"],
                       "paragraphs": run["paragraphs"],
                       "unmatched_numbers": run["unmatched_numbers"], "error": None}
            except Exception as e:  # one model failing must not sink the others
                logger.warning("comparison %s: %s run %d failed: %s", cid, model, rep, e)
                out = {"model": model, "repetition": rep, "run_id": None, "paragraphs": [],
                       "unmatched_numbers": [], "error": str(e)[:500]}
        async with lock:
            record["outputs"].append(out)
            record["outputs"].sort(key=lambda o: (gens.index(o["model"]), o["repetition"]))
            prompt_store.save_comparison(dtxsid, SECTION, record)
        await say("output", out)

    await asyncio.gather(*(one(m, r) for m in gens for r in range(1, int(repetitions) + 1)))

    ok = [o for o in record["outputs"] if not o["error"] and o["paragraphs"]]
    if not ok:
        record.update(status="failed", completed_at=now_iso(),
                      review_error="every generation failed; nothing to review")
        prompt_store.save_comparison(dtxsid, SECTION, record)
        await say("complete", record)
        return record

    # Letters only for generators with something to review: no gaps for the
    # arbiter to wonder about (a failed generator is in the record, not the review).
    letters = blind_labels([m for m in gens if any(o["model"] == m for o in ok)], rng)
    key: dict[str, dict] = {}
    drafts: dict[str, dict] = {}
    for o in sorted(ok, key=lambda o: (letters[o["model"]], o["repetition"])):
        lab = f"{letters[o['model']]}{o['repetition']}"
        key[lab] = {"model": o["model"], "repetition": o["repetition"], "run_id": o["run_id"]}
        drafts[lab] = o
    published = prompt_workshop.published_section(dtxsid, SECTION)
    user = arbiter_prompt(variables, published, drafts)
    record["blinding"] = {"generators": {lt: m for m, lt in letters.items()}, "drafts": key}
    record["arbiter_prompt"] = {"system": _ARBITER_SYSTEM, "user": user, "model": arbiter}
    await say("arbiter", {"model": arbiter, "drafts": len(drafts)})
    try:
        review = await llm_generate_json_async(
            "narrative-arbiter", user, _ARBITER_SYSTEM, model=arbiter,
            temperature=0.2, max_tokens=8192, no_cache=True)
        if not isinstance(review, dict):
            raise ValueError("the arbiter did not return a JSON object")
        record["review"] = unblind(review, key)
    except Exception as e:
        logger.warning("comparison %s: arbiter %s failed: %s", cid, arbiter, e)
        record["review_error"] = str(e)[:500]
    record.update(status="complete", completed_at=now_iso())
    prompt_store.save_comparison(dtxsid, SECTION, record)
    await say("complete", record)
    return record


__all__ = ["ComparisonError", "run_comparison", "blind_labels", "arbiter_prompt", "unblind",
           "MAX_GENERATORS", "MAX_REPETITIONS"]
