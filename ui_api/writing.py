"""
ui_api.writing — the written parts of a report: who wrote each, and what the
writer was given (the demo path, docs/ui-redesign/modules/demo/spec.md §4 S3).

A report's text comes from two kinds of writer. The program builds some of it
from the study's data (the results tables and their sentences, five Methods
subsections); a language model words the rest (the Background, the other
Methods subsections, the interpreting paragraphs of the benchmark dose
summary, the gene-level interpretations, a Summary run). This module reads,
for each part, what the session holds about how it was written:

  * ``writing_overview``: the parts of a report or a study, each marked built
    from the data, written by a model or both, with what is recorded about it;
  * ``writing_part``: one part in full: its text, the model, and what the
    model was given.

**The rule for everything served here: the record is shown as the record.**
What a session recorded (a run's exact prompt, the facts taken from the data,
the text handed to the model) is served as recorded and labeled so
(``record``: ``as_sent`` or ``recorded``). A text built again from recorded
inputs with the program as it stands now is labeled ``rebuilt``. What was not
recorded is ``not_recorded``, with no text: never a reconstruction passed off
as the record.

Which file is current: a session can hold several ``_cache_<unit>_<hash>.json``
of one unit; the one the report uses is the newest
(``pipeline.session_store.latest_session_cache``, as the session load, the
preview and the export resolve it).

A report over several studies (studies.json) holds the Background; the
Methods, results, interpretations and Summary are each study's. Reading has no
side effects: no folder is created (``pipeline.prompt_store.list_runs`` makes
the runs folder, so the runs are read here without it).

The reference list is in ui_api.writing_references; the acts (write the
Background, run the Summary) in ui_api.writing_acts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ui_api.studies import StudyRefusal

logger = logging.getLogger(__name__)

# How a served text relates to what the session recorded (the module docstring).
AS_SENT = "as_sent"            # recorded, and sent to the model as it stands
RECORDED = "recorded"          # recorded with the result (facts, a template)
REBUILT = "rebuilt"            # built again from recorded inputs, by today's program
NOT_RECORDED = "not_recorded"  # nothing was kept

# Who wrote a part.
DATA, MODEL, MIXED, UNRECORDED = "data", "model", "mixed", "unrecorded"

# The parts that are not one section of the catalog, in a person's words.
RESULTS_KEY = "results"
RESULTS_TITLE = "Results tables and their sentences"
BMD_NARRATIVE_TITLE = "Benchmark dose summary: the interpreting paragraphs"

# The groups of the API page (web_routes/api_guide.yaml) this page belongs to.
API_GROUPS = ("writing", "citations")


def _json(path: Path | None):
    """A session JSON document: None when absent; UnreadableSessionFile when
    it exists but cannot be parsed."""
    from common.session_files import read_json_file
    return read_json_file(path) if path is not None else None


def _latest(session: Path, unit: str) -> dict | None:
    """The current ``_cache_<unit>_<hash>.json`` of a session, as the core
    resolves it; None when there is none."""
    from pipeline.session_store import latest_session_cache
    data = _json(latest_session_cache(session, f"_cache_{unit}_*.json"))
    return data if isinstance(data, dict) else None


def session_of(dtxsid: str) -> Path:
    """The session's folder; ``study_not_found`` when there is none."""
    from ui_api.studies import session_exists, session_folder
    if not session_exists(dtxsid):
        raise StudyRefusal("study_not_found", f"no session {dtxsid}", 404, {"id": dtxsid})
    return session_folder(dtxsid)


def runs_of(session: Path, section: str, limit: int = 20) -> list[dict]:
    """The session's recorded generations of a section, newest first: what
    pipeline.prompt_store.list_runs reads, without creating the folder."""
    folder = session / "narrative_runs" / section
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("r*.json"), reverse=True)[:limit]:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def _titles(dtxsid: str) -> dict[str, str]:
    """{section key: title} from the tree the report renders from."""
    from ui_api.read_model import _node_titles, _rendering_catalog
    catalog, tree, _ = _rendering_catalog(dtxsid)
    titles = _node_titles(tree)
    return {spec.key: next((titles[n] for n in spec.node_ids if n in titles), None)
            for spec in catalog if spec.instance_of is None}


def _sections(dtxsid: str) -> dict[str, dict]:
    from ui_api.read_model import ReadOnlyDiskPoolStore
    return ReadOnlyDiskPoolStore().read_section_dicts(dtxsid)


def _prompt_text(prompt: dict) -> str:
    """A recorded prompt's two texts as one, each under its name."""
    return (f"SYSTEM INSTRUCTIONS\n\n{prompt.get('system') or ''}\n\n"
            f"PROMPT\n\n{prompt.get('user') or ''}")


def _given(ident: str, title: str, record: str, say: str, text: str | None = None) -> dict:
    return {"id": ident, "title": title, "record": record, "say": say,
            "text": text if record != NOT_RECORDED else None,
            "chars": len(text) if text and record != NOT_RECORDED else 0}


# ---------------------------------------------------------------------------
# The Background (a report's, or a single study's)
# ---------------------------------------------------------------------------

def _background_run(session: Path, section: dict) -> dict | None:
    """The recorded run whose text is the section's text, or None."""
    for run in runs_of(session, "background"):
        if run.get("paragraphs") == section.get("paragraphs") and isinstance(run.get("prompt"), dict):
            return run
    return None


def citation_check_of_background(section: dict | None) -> dict | None:
    """The Background's citation check as recorded with it (citation_report)."""
    report = (section or {}).get("citation_report")
    if not isinstance(report, dict):
        return None
    issues = [i for i in report.get("issues") or [] if isinstance(i, dict)]
    return {
        "sources_supplied": report.get("inventory_size"),
        "sources_cited": len(report.get("cited") or []),
        "untraced": len(issues),
        "removed": False,
        "say": ("Every citation in this text points at a source that was supplied."
                if not issues else
                f"{len(issues)} citation{'' if len(issues) == 1 else 's'} could not be traced "
                "to a supplied source. The text is left as written; each is listed."),
        "items": [{"token": i.get("token"), "sentence": i.get("sentence"),
                   "what": _ISSUE_SAY.get(i.get("issue"), i.get("issue"))} for i in issues],
    }


_ISSUE_SAY = {
    "unresolved_citation": "A citation in the text that points at no supplied source.",
    "unresolved_reference_line": "A reference the model listed that is not a supplied source.",
    "reference_line_mismatch": ("A reference the model listed under a number that belongs to "
                                "another supplied source."),
}


def _background_summary(dtxsid: str, session: Path, title: str | None) -> dict:
    section = _json(session / "background.json")
    section = section if isinstance(section, dict) else None
    run = _background_run(session, section) if section else None
    if section is None:
        recorded = None
    elif run:
        recorded = {"prompt": AS_SENT, "inputs": RECORDED,
                    "say": "The exact prompt sent to the model is recorded."}
    else:
        recorded = {"prompt": NOT_RECORDED, "inputs": NOT_RECORDED,
                    "say": "The prompt and the sources gathered for it were not recorded."}
    return {"key": "background", "study": dtxsid, "title": title or "Background",
            "written_by": MODEL,
            "written_by_say": "Written by a language model from public sources gathered "
                              "about the chemical.",
            "model": (section or {}).get("model_used"),
            "exists": section is not None, "approved": bool((section or {}).get("approved")),
            "recorded": recorded}


def _background_part(dtxsid: str, session: Path, title: str | None) -> dict:
    out = _background_summary(dtxsid, session, title)
    section = _json(session / "background.json")
    if not isinstance(section, dict):
        return {**out, "text": [], "given": [], "say": "No Background has been written yet."}
    run = _background_run(session, section)
    blocks = [{"heading": None, "paragraphs": list(section.get("paragraphs") or [])}]
    if section.get("abstract_background"):
        blocks.append({"heading": "The sentences distilled from it for the Abstract",
                       "paragraphs": [section["abstract_background"]]})
    if run:
        given = [_given("prompt", "The prompt", AS_SENT,
                        "Recorded with the run that wrote this text. It holds the fixed "
                        "instructions and every source gathered about the chemical.",
                        _prompt_text(run["prompt"]))]
    else:
        given = [_given("prompt", "The prompt", NOT_RECORDED,
                        "The prompt this text was written under was not recorded, and neither "
                        "were the sources gathered for it. Prompts are kept with a Background "
                        "written from now on.")]
    return {**out, "text": blocks, "given": given,
            "references": list(section.get("references") or []),
            "citation_check": citation_check_of_background(section),
            "run": ({"run_id": run.get("run_id"), "at": run.get("at")} if run else None)}


# ---------------------------------------------------------------------------
# Materials and Methods
# ---------------------------------------------------------------------------

def _facts_text(context: dict) -> str:
    """The recorded Methods facts, one per line."""
    lines = []
    for key, value in context.items():
        shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        lines.append(f"{key}: {shown}")
    return "\n".join(lines)


def _methods_as_printed(dtxsid: str, session: Path, cache: dict, definition_of: str) -> tuple[list, bool]:
    """(the Methods subsections as the report prints them, whether that was
    possible): the subsections built from the data are built again from the
    recorded facts each time the report is made (narrative.methods_design.
    refresh_data_built, as rendering.latex_export does); the model's are as
    recorded. The recorded subsections alone when they cannot be rebuilt."""
    sections = [s for s in cache.get("sections") or [] if isinstance(s, dict)]
    context = cache.get("context")
    if not isinstance(context, dict):
        return sections, False
    try:
        from narrative.methods_design import refresh_data_built
        from narrative.test_article import abbreviation_of
        from rendering.latex_export import _methods_key_order
        # The abbreviation is the study's as recorded now (rendering.latex_export).
        context = {**context, "abbreviation": abbreviation_of(_json(session / "identity.json") or {})}
        return refresh_data_built(sections, context, _methods_key_order(definition_of, None)), True
    except Exception as exc:  # noqa: BLE001 — the recorded text stands, and the page says so
        logger.warning("Methods of %s not rebuilt from the recorded facts: %s", dtxsid, exc)
        return sections, False


def _methods_subsections(dtxsid: str, session: Path, cache: dict, definition_of: str) -> tuple[list, bool]:
    from narrative.methods_design import DATA_BUILT_KEYS
    sections, rebuilt = _methods_as_printed(dtxsid, session, cache, definition_of)
    return [{"key": s.get("key"), "heading": s.get("heading"), "level": s.get("level"),
             "written_by": DATA if s.get("key") in DATA_BUILT_KEYS else MODEL,
             "paragraphs": list(s.get("paragraphs") or [])} for s in sections], rebuilt


def _methods_summary(dtxsid: str, session: Path, title: str | None, definition_of: str) -> dict:
    cache = _latest(session, "methods")
    subsections = _methods_subsections(dtxsid, session, cache, definition_of)[0] if cache else []
    return {"key": "methods", "study": dtxsid, "title": title or "Materials and Methods",
            "written_by": MIXED if cache else UNRECORDED,
            "written_by_say": "Some subsections are built from the study's data; a language "
                              "model words the others from facts taken from the data.",
            "model": (cache or {}).get("model_used"),
            "exists": bool(subsections), "approved": False,
            "subsections": [{k: s[k] for k in ("key", "heading", "written_by")} for s in subsections],
            "recorded": ({"prompt": REBUILT, "inputs": RECORDED,
                          "say": "The facts given to the model are recorded. The prompt is not; "
                                 "it can be rebuilt from the recorded facts."}
                         if cache and isinstance(cache.get("context"), dict) else
                         {"prompt": NOT_RECORDED, "inputs": NOT_RECORDED,
                          "say": "Nothing is recorded about how this text was written."}
                         if cache else None)}


def _methods_part(dtxsid: str, session: Path, title: str | None, definition_of: str) -> dict:
    out = _methods_summary(dtxsid, session, title, definition_of)
    cache = _latest(session, "methods")
    if not cache:
        return {**out, "text": [], "given": [],
                "say": "The Materials and Methods have not been written yet: they are "
                       "written when the study is processed."}
    subsections, rebuilt = _methods_subsections(dtxsid, session, cache, definition_of)
    context = cache.get("context") if isinstance(cache.get("context"), dict) else None
    given = []
    if context:
        given.append(_given(
            "facts", "The facts taken from the study's data", RECORDED,
            "Recorded with the result. The subsections built from the data are assembled "
            "from these facts; the prompt for the others states them to the model.",
            _facts_text(context)))
        try:
            from narrative.methods_models import MethodsContext
            from narrative.methods_prompt import build_methods_prompt
            system, user = build_methods_prompt(MethodsContext.from_dict(context))
            given.append(_given(
                "prompt", "The prompt", REBUILT,
                "The prompt itself was not recorded. This one is built again from the "
                "recorded facts by the program as it stands now; it differs from what was "
                "sent wherever the program has changed since.",
                _prompt_text({"system": system, "user": user})))
        except Exception as exc:  # noqa: BLE001 — said, never guessed
            logger.warning("Methods prompt of %s not rebuilt: %s", dtxsid, exc)
            given.append(_given("prompt", "The prompt", NOT_RECORDED,
                                "The prompt was not recorded, and it could not be rebuilt "
                                "from the recorded facts."))
    else:
        given.append(_given("prompt", "The prompt", NOT_RECORDED,
                            "Neither the prompt nor the facts given to the model were recorded."))
    return {**out,
            "text": [{"key": s["key"], "heading": s["heading"], "written_by": s["written_by"],
                      "paragraphs": s["paragraphs"]} for s in subsections],
            "text_say": ("The subsections built from the data are shown as the report prints "
                         "them: built from the recorded facts each time the report is made."
                         if rebuilt else
                         "The subsections are shown as recorded when the study was processed."),
            "given": given}


# ---------------------------------------------------------------------------
# The results tables and their sentences
# ---------------------------------------------------------------------------

def _result_sections(dtxsid: str) -> list[tuple[str, dict]]:
    return sorted((k, v) for k, v in _sections(dtxsid).items() if k.startswith("bm2_"))


def _results_summary(dtxsid: str) -> dict:
    tables = _result_sections(dtxsid)
    return {"key": RESULTS_KEY, "study": dtxsid, "title": RESULTS_TITLE, "written_by": DATA,
            "written_by_say": "The tables, their footnotes and the sentences under them are "
                              "built from the study's data by the program. No language model "
                              "is involved.",
            "model": None, "exists": bool(tables),
            "approved": bool(tables) and all(bool(v.get("approved")) for _, v in tables),
            "subsections": [{"key": k, "heading": v.get("title") or k, "written_by": DATA}
                            for k, v in tables],
            "recorded": None}


def _results_part(dtxsid: str) -> dict:
    out = _results_summary(dtxsid)
    tables = _result_sections(dtxsid)
    blocks = []
    for key, section in tables:
        narrative = section.get("narrative")
        paragraphs = ([narrative] if isinstance(narrative, str) else
                      [p for p in narrative or [] if isinstance(p, str)])
        blocks.append({"key": key, "heading": section.get("title") or key, "written_by": DATA,
                       "caption": section.get("caption"), "paragraphs": paragraphs})
    return {**out, "text": blocks, "given": [],
            "say": None if tables else "No results tables yet: they are built when the "
                                       "study is processed."}


# ---------------------------------------------------------------------------
# The benchmark dose summary's interpreting paragraphs
# ---------------------------------------------------------------------------

def _bmd_summary(dtxsid: str, session: Path) -> dict:
    cache = _latest(session, "apical_narrative")
    return {"key": "bmd_summary", "study": dtxsid, "title": BMD_NARRATIVE_TITLE,
            "written_by": MODEL if cache else UNRECORDED,
            "written_by_say": "The summary's table and its describing sentences are built "
                              "from the data. These paragraphs, which interpret the pattern "
                              "of benchmark doses, are written by a language model.",
            "model": (cache or {}).get("model_used"),
            "exists": bool((cache or {}).get("paragraphs")), "approved": False,
            "recorded": ({"prompt": NOT_RECORDED, "inputs": NOT_RECORDED,
                          "say": "Neither the prompt nor the findings given to the model "
                                 "were recorded."} if cache else None)}


def _bmd_part(dtxsid: str, session: Path) -> dict:
    out = _bmd_summary(dtxsid, session)
    cache = _latest(session, "apical_narrative")
    if not cache:
        return {**out, "text": [], "given": [],
                "say": "These paragraphs have not been written yet: they are written when "
                       "the study is processed."}
    return {**out,
            "text": [{"heading": None, "paragraphs": list(cache.get("paragraphs") or [])}],
            "given": [_given("prompt", "The prompt", NOT_RECORDED,
                             "Only the text and the model's name were recorded. The prompt, "
                             "and the list of findings it stated, were not.")]}


# ---------------------------------------------------------------------------
# The gene-level interpretations (one per organ and sex)
# ---------------------------------------------------------------------------

def interpretation_keys(session: Path) -> list[tuple[str, str, str]]:
    """[(part key, organ, sex)] of the interpretations a session holds, from
    the genomics results (their organ and sex) and the interpretation files."""
    from genomics.genomics_narratives import interpretation_cache_prefix
    from pipeline.session_store import latest_session_cache
    out = []
    for key in sorted(_latest(session, "genomics") or {}):
        if "_" not in key:
            continue
        organ, sex = (p.lower() for p in key.split("_", 1))
        if latest_session_cache(session, f"{interpretation_cache_prefix(organ, sex)}*.json"):
            out.append((f"genomics_{organ}_{sex}", organ, sex))
    return out


def interpretation_of(session: Path, organ: str, sex: str) -> dict | None:
    """The current interpretation of an organ and sex, or None."""
    from genomics.genomics_narratives import interpretation_cache_prefix
    from pipeline.session_store import latest_session_cache
    data = _json(latest_session_cache(session, f"{interpretation_cache_prefix(organ, sex)}*.json"))
    return data if isinstance(data, dict) else None


def interpretation_title(organ: str, sex: str) -> str:
    return f"Gene-level interpretation: {organ.replace('_', ' ')}, {sex}"


def _paragraphs(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [p for p in value or [] if isinstance(p, str)]


def _interpretation_summary(dtxsid: str, session: Path, key: str, organ: str, sex: str) -> dict:
    cache = interpretation_of(session, organ, sex) or {}
    has_inputs = bool(cache.get("context_text"))
    return {"key": key, "study": dtxsid, "title": interpretation_title(organ, sex),
            "written_by": MODEL,
            "written_by_say": "Written by a language model from the study's gene-level "
                              "results and the literature in the knowledge base.",
            "model": cache.get("model_used"),
            "exists": bool(cache.get("gene_set_narrative") or cache.get("gene_narrative")),
            "approved": False,
            "recorded": {"prompt": NOT_RECORDED,
                         "inputs": RECORDED if has_inputs else NOT_RECORDED,
                         "say": ("The text given to the model and the papers offered to it "
                                 "are recorded. The fixed instructions around them are not."
                                 if has_inputs else
                                 "Nothing is recorded about what the model was given.")}}


def _interpretation_part(dtxsid: str, session: Path, key: str, organ: str, sex: str) -> dict:
    from narrative.references_builder import cited_tokens_in_order
    out = _interpretation_summary(dtxsid, session, key, organ, sex)
    cache = interpretation_of(session, organ, sex) or {}
    gene_sets, genes = _paragraphs(cache.get("gene_set_narrative")), _paragraphs(cache.get("gene_narrative"))
    cited = set(cited_tokens_in_order(gene_sets, genes))
    pool = [p for p in cache.get("reference_pool") or [] if isinstance(p, dict)]
    given = []
    if cache.get("context_text"):
        given.append(_given(
            "context", "The study's results and the literature evidence", AS_SENT,
            "Recorded with the result. The program placed this text inside the prompt, "
            "between a fixed opening and fixed closing instructions, followed by the list "
            "of papers offered (below).", cache["context_text"]))
    given.append(_given(
        "prompt", "The whole prompt", NOT_RECORDED,
        "The fixed instructions around the recorded text were not kept with the result. "
        "They are in the program (narrative/genomics_llm.py), which may have changed since."))
    unresolved = [w for w in cache.get("unresolved_citations") or [] if isinstance(w, dict)]
    untraced = sum(len(w.get("tokens") or []) for w in unresolved)
    kb = cache.get("knowledge_base") if isinstance(cache.get("knowledge_base"), dict) else None
    return {**out,
            "text": [{"heading": "Gene set benchmark dose analysis", "paragraphs": gene_sets},
                     {"heading": "Gene benchmark dose analysis", "paragraphs": genes}],
            "text_say": ("The text is shown as the model wrote it: a citation is the token of "
                         "a paper offered, such as [P3]. In the report each token is replaced "
                         "by the paper's number in the reference list."),
            "given": given,
            "knowledge_base": ({"name": kb.get("name"), "sha256": kb.get("sha256")} if kb else None),
            "papers_offered": [{"token": p.get("token"), "title": p.get("title"),
                                "year": p.get("year"), "venue": p.get("venue"),
                                "doi": p.get("doi"), "citation_count": p.get("citation_count"),
                                "genes": list(p.get("genes") or []),
                                "cited": p.get("token") in cited} for p in pool],
            "citation_check": {
                "sources_supplied": len(pool), "sources_cited": len(cited & {p.get("token") for p in pool}),
                "untraced": untraced, "removed": True,
                "say": ("Every citation in this text points at a paper that was offered."
                        if not untraced else
                        f"{untraced} citation{'' if untraced == 1 else 's'} could not be traced "
                        "to a paper that was offered. Each is removed from the printed text "
                        "and listed here."),
                "items": [{"token": ", ".join(f"[{t}]" for t in w.get("tokens") or []),
                           "sentence": s, "what": _ISSUE_SAY["unresolved_citation"]}
                          for w in unresolved for s in w.get("sentences") or []]}}


# ---------------------------------------------------------------------------
# The Summary
# ---------------------------------------------------------------------------

_SUMMARY_DESIGN_SAY = ("The facts are picked from the study's results by rule. A language "
                       "model words them only when a run is made under the Summary's prompt "
                       "template and its text is taken into the report.")


def _summary_writer(section: dict | None) -> tuple[str, str]:
    source = (section or {}).get("source")
    if section is None:
        return UNRECORDED, _SUMMARY_DESIGN_SAY
    if source == "generated":
        return DATA, ("The text now in the report is the facts picked by rule, in the "
                      "program's fixed wording. No language model has worded it. "
                      + _SUMMARY_DESIGN_SAY)
    if source == "model":
        return MODEL, ("The text now in the report was worded by a language model from the "
                       "facts picked by rule.")
    return UNRECORDED, "The record does not say how the text now in the report was written."


def _run_view(run: dict, in_use: bool) -> dict:
    prompt = run.get("prompt") if isinstance(run.get("prompt"), dict) else {}
    return {"run_id": run.get("run_id"), "at": run.get("at"),
            "template_version": run.get("template_version"), "model": prompt.get("model"),
            "prompt": _prompt_text(prompt) if prompt else None,
            "paragraphs": list(run.get("paragraphs") or []),
            "unmatched_numbers": list(run.get("unmatched_numbers") or []),
            "in_use": in_use}


def _summary_summary(dtxsid: str, session: Path, title: str | None) -> dict:
    section = _json(session / "summary.json")
    section = section if isinstance(section, dict) else None
    written_by, say = _summary_writer(section)
    run_id = (section or {}).get("run_id")
    run = next((r for r in runs_of(session, "summary") if r.get("run_id") == run_id), None) if run_id else None
    if written_by == MODEL:
        recorded = ({"prompt": AS_SENT, "inputs": RECORDED,
                     "say": "The exact prompt sent to the model is recorded with its run."}
                    if run else
                    {"prompt": NOT_RECORDED, "inputs": NOT_RECORDED,
                     "say": "The run that wrote this text is not among the recorded runs."})
    else:
        recorded = None
    return {"key": "summary", "study": dtxsid, "title": title or "Summary",
            "written_by": written_by, "written_by_say": say,
            "model": (section or {}).get("model_used"),
            "exists": section is not None, "approved": bool((section or {}).get("approved")),
            "recorded": recorded, "run_count": len(runs_of(session, "summary"))}


def _summary_part(dtxsid: str, session: Path, title: str | None) -> dict:
    from narrative import prompt_templates
    out = _summary_summary(dtxsid, session, title)
    section = _json(session / "summary.json")
    section = section if isinstance(section, dict) else None
    runs = runs_of(session, "summary")
    run_id = (section or {}).get("run_id")
    in_use = next((r for r in runs if r.get("run_id") == run_id), None) if run_id else None

    template_text, version = prompt_templates.template_text("summary")
    given = []
    if in_use and isinstance(in_use.get("prompt"), dict):
        given.append(_given("prompt", "The prompt", AS_SENT,
                            "Recorded with the run whose text is now in the report.",
                            _prompt_text(in_use["prompt"])))
    elif out["written_by"] == MODEL:
        given.append(_given("prompt", "The prompt", NOT_RECORDED,
                            "The run that wrote this text is not among the recorded runs."))
    else:
        given.append(_given("prompt", "The prompt", NOT_RECORDED,
                            "No prompt was sent for the text now in the report: no language "
                            "model has worded it."))
    try:
        from narrative.summary_llm import render_for_session
        rendered, _ = render_for_session(dtxsid)
        given.append(_given(
            "prompt_now", "The prompt a run would send now", REBUILT,
            f"Built now from the current template (version {version}) and the study's "
            "results. It is not the record of a run.",
            _prompt_text({"system": rendered.system, "user": rendered.user})))
    except Exception as exc:  # noqa: BLE001 — a study with no results has no prompt to show
        logger.info("Summary prompt of %s not rendered: %s", dtxsid, exc)
    given.append(_given("template", f"The prompt template, version {version}", RECORDED,
                        "The template in use: the fixed wording of the prompt, with places "
                        "for the study's facts. Each change to it is kept as a new version.",
                        template_text))
    unmatched = (list(in_use.get("unmatched_numbers") or []) if in_use else None)
    return {**out,
            "text": ([{"heading": None, "paragraphs": list(section.get("paragraphs") or [])}]
                     if section else []),
            "say": None if section else "No Summary has been written yet.",
            "given": given,
            "template": {"version": version,
                         "in_use_version": (section or {}).get("template_version")},
            "unmatched_numbers": unmatched,
            "unmatched_say": (
                "The text now in the report was not worded by a model, so there is nothing "
                "to compare: every number in it is one the program picked."
                if out["written_by"] == DATA else
                "Not recorded for the text now in the report." if unmatched is None else
                "Every number in the text is among the facts the model was given."
                if not unmatched else
                "Numbers in the text that are not among the facts the model was given."),
            "runs": [_run_view(r, r.get("run_id") == run_id) for r in runs]}


# ---------------------------------------------------------------------------
# The overview and one part
# ---------------------------------------------------------------------------

def _study_parts(dtxsid: str, session: Path, titles: dict, definition_of: str) -> list[dict]:
    """A study's own written parts, in the report's order."""
    parts = [_methods_summary(dtxsid, session, titles.get("methods"), definition_of),
             _results_summary(dtxsid), _bmd_summary(dtxsid, session)]
    parts += [_interpretation_summary(dtxsid, session, key, organ, sex)
              for key, organ, sex in interpretation_keys(session)]
    parts.append(_summary_summary(dtxsid, session, titles.get("summary")))
    return parts


def api_page_links() -> list[dict]:
    """Where this step is on the API page (/docs): its two groups, by the
    numbered titles the page prints."""
    from urllib.parse import quote
    from web_routes import api_guide
    guide = api_guide.load_guide()
    numbered = guide.numbered()
    titles = {g.key: g.title for g in guide.groups}
    return [{"group": key, "title": titles[key], "href": f"/docs#/{quote(numbered[key])}"}
            for key in API_GROUPS if key in numbered]


def _kind(dtxsid: str) -> dict:
    from ui_api.studies import session_kind
    return session_kind(dtxsid)


def writing_overview(dtxsid: str) -> dict:
    """The written parts of a report or a study.

    A report over several studies: its own parts (the Background) and, per
    study, that study's parts. A study of a report: its parts and a pointer to
    the report for the Background. A study on its own: all of them."""
    from ui_api.writing_acts import act_verdicts

    session = session_of(dtxsid)
    kind = _kind(dtxsid)
    titles = _titles(dtxsid)
    from ui_api.writing_references import CHECK_SAYS
    out: dict = {"id": dtxsid, "kind": kind["kind"], "check_says": CHECK_SAYS,
                 "api_page": api_page_links(), "acts": act_verdicts(dtxsid, kind)}
    if kind["kind"] == "report":
        out["parts"] = [_background_summary(dtxsid, session, titles.get("background"))]
        out["studies"] = []
        for member in kind["relations"]["members"]:
            from ui_api.studies import session_exists, session_folder
            exists = session_exists(member["id"])
            out["studies"].append({
                "key": member["key"], "id": member["id"], "exists": exists,
                "parts": (_study_parts(member["id"], session_folder(member["id"]), titles, dtxsid)
                          if exists else [])})
    elif kind["kind"] == "member":
        parent = kind["relations"]["parent"]
        out["parts"] = _study_parts(dtxsid, session, titles, parent or dtxsid)
        out["report"] = {"id": parent, "part": {
            "key": "background", "title": titles.get("background") or "Background"}}
    else:
        out["parts"] = [_background_summary(dtxsid, session, titles.get("background")),
                        *_study_parts(dtxsid, session, titles, dtxsid)]
    return out


def writing_part(dtxsid: str, part: str) -> dict:
    """One written part in full, read from the session that holds it (a
    report for its Background, a study for the rest).
    ``writing_part_not_found`` when the session has no such part."""
    session = session_of(dtxsid)
    kind = _kind(dtxsid)
    titles = _titles(dtxsid)
    is_report, is_member = kind["kind"] == "report", kind["kind"] == "member"
    definition_of = (kind["relations"]["parent"] or dtxsid) if is_member else dtxsid

    def missing(why: str):
        return StudyRefusal("writing_part_not_found", f"{dtxsid} has no written part "
                            f"{part!r}: {why}", 404, {"id": dtxsid, "part": part})

    if part == "background":
        if is_member:
            raise missing("the Background is the report's")
        return _background_part(dtxsid, session, titles.get("background"))
    if is_report:
        raise missing("a report's other parts are its studies'")
    if part == "methods":
        return _methods_part(dtxsid, session, titles.get("methods"), definition_of)
    if part == RESULTS_KEY:
        return _results_part(dtxsid)
    if part == "bmd_summary":
        return _bmd_part(dtxsid, session)
    if part == "summary":
        return _summary_part(dtxsid, session, titles.get("summary"))
    for key, organ, sex in interpretation_keys(session):
        if key == part:
            return _interpretation_part(dtxsid, session, key, organ, sex)
    raise missing("no such part")
