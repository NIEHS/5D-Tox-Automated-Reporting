"""
ui_api.writing_references — a report's reference list, what cites each entry,
and what the knowledge base holds of each paper (the demo path, spec §4 S4).

The printed list has two sources:

  * the **Background's sources**: the public sources gathered about the
    chemical, kept with the Background (background.json ``references``); its
    citations are checked against them (``citation_report``);
  * the **papers the gene-level interpretations cite**: each interpretation
    is offered a pool of papers from the study's knowledge base and cites them
    by token; the tokens become the list's numbers
    (narrative.references_builder.build_session_references, the assembly the
    report itself runs), and a token that names no offered paper is removed
    from the printed text and reported.

A report over several studies prints one list: the Background's sources, then
each study's papers numbered on from them (rendering.report_compose). The
numbers served here are the printed ones.

For a knowledge-base paper the statements the knowledge base extracted from it
are read from its ``paper_claims`` table (knowledge_base.registry.kb_for names
the database). Nothing here judges whether a paper supports a sentence, and
the answer says so (``CHECK_SAYS``).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ui_api.writing import (
    _json, _kind, _latest, citation_check_of_background, interpretation_title, session_of,
)

logger = logging.getLogger(__name__)

# What the citation check does and does not establish, in the words the page
# shows as they stand.
CHECK_SAYS = ("The check establishes that a citation points at a source. It does not judge "
              "whether the source supports the sentence.")

_URL = re.compile(r"https?://\S+")
_LEADING_NUMBER = re.compile(r"^\[(\d+)\]\s*")


def _sentences_citing(paragraphs: list[str]) -> dict[int, list[str]]:
    """{reference number: the sentences that cite it}, in the text's order.
    Citations are read as the Background's check reads them."""
    from narrative.background_writer import _INLINE_CITE_RE, _expand_bracket
    from narrative.citation_check import _SENTENCE_SPLIT
    out: dict[int, list[str]] = {}
    for paragraph in paragraphs:
        if not isinstance(paragraph, str):
            continue
        for sentence in _SENTENCE_SPLIT.split(paragraph):
            for match in _INLINE_CITE_RE.finditer(sentence):
                for n in _expand_bracket(match.group(1)):
                    found = out.setdefault(n, [])
                    if sentence.strip() not in found:
                        found.append(sentence.strip())
    return out


def _shifted(text: str, shift: int) -> str:
    """A text with every citation number moved on by ``shift``, as a report
    over several studies renumbers a study's citations."""
    if not shift:
        return text
    from rendering.report_compose import _CITATION
    return _CITATION.sub(lambda m: "[" + re.sub(
        r"\d+", lambda n: str(int(n.group()) + shift), m.group(1)) + "]", text)


def _background_entries(dtxsid: str, session: Path) -> tuple[list[dict], dict | None]:
    """(the Background's sources as entries, its citation check)."""
    section = _json(session / "background.json")
    if not isinstance(section, dict):
        return [], None
    citing = _sentences_citing(section.get("paragraphs") or [])
    entries = []
    for position, line in enumerate(section.get("references") or [], start=1):
        if not isinstance(line, str):
            continue
        numbered = _LEADING_NUMBER.match(line)
        n = int(numbered.group(1)) if numbered else position
        text = line[numbered.end():] if numbered else line
        url = _URL.search(text)
        sentences = citing.get(n, [])
        entries.append({
            "n": n, "kind": "background_source", "study": None, "study_id": dtxsid,
            "text": _URL.sub("", text).strip() if url else text,
            "url": url.group(0).rstrip(".,;") if url else None,
            "title": None, "year": None, "venue": None, "doi": None, "genes": [],
            "cited_in": ([{"part": "background", "part_title": "Background",
                           "study": None, "study_id": dtxsid, "sentences": sentences}]
                         if sentences else []),
            "statements": None,
        })
    return entries, citation_check_of_background(section)


def _claims(db_path, paper_ids: list[str]) -> dict[str, list[str]]:
    """{paper id: the statements the knowledge base extracted from it}."""
    ids = [p for p in dict.fromkeys(paper_ids) if p]
    if not ids:
        return {}
    from knowledge_base.toxkb import ToxKBQuerier
    with ToxKBQuerier(str(db_path)) as kb:
        rows = kb.con.execute(
            "SELECT paper_id, claim FROM paper_claims "
            f"WHERE paper_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    out: dict[str, list[str]] = {}
    for paper_id, claim in rows:
        if claim and claim not in out.setdefault(paper_id, []):
            out[paper_id].append(claim)
    return out


def _knowledge_base(dtxsid: str, session: Path) -> dict:
    """The knowledge base a study reads now, and the one recorded with its
    results (knowledge_base.json): ``{name, recorded_name, same, usable}``."""
    from knowledge_base.registry import kb_or_none
    recorded = _json(session / "knowledge_base.json")
    recorded = recorded if isinstance(recorded, dict) else {}
    try:
        kb = kb_or_none(dtxsid)
    except Exception as exc:  # noqa: BLE001 — reported as not usable
        logger.warning("Knowledge base of %s not resolved: %s", dtxsid, exc)
        kb = None
    return {"name": (kb or {}).get("name"), "path": (kb or {}).get("path"),
            "recorded_name": recorded.get("name"),
            "same": bool(kb) and (not recorded.get("sha256") or kb.get("sha256") == recorded.get("sha256")),
            "usable": kb is not None}


def _study_entries(dtxsid: str, session: Path, key: str | None, shift: int) -> tuple[list[dict], dict, dict]:
    """(a study's papers as entries with their printed numbers, its citation
    check, its knowledge base). ``shift``: how many references the report
    prints before this study's."""
    from narrative.references_builder import background_reference_count, build_session_references

    genomics = _latest(session, "genomics") or {}
    assembled = build_session_references(session, genomics, dtxsid=dtxsid,
                                         offset=background_reference_count(session))
    citing: dict[int, list[dict]] = {}
    for (organ, sex), narratives in assembled["rewritten"].items():
        for field, what in (("gene_set_narrative", "gene sets"), ("gene_narrative", "genes")):
            for n, sentences in _sentences_citing(narratives.get(field) or []).items():
                citing.setdefault(n, []).append({
                    "part": f"genomics_{organ}_{sex}",
                    "part_title": f"{interpretation_title(organ, sex)} ({what})",
                    "study": key, "study_id": dtxsid,
                    "sentences": [_shifted(s, shift) for s in sentences]})

    kb = _knowledge_base(dtxsid, session)
    claims: dict[str, list[str]] = {}
    if kb["usable"]:
        try:
            claims = _claims(kb["path"], [r.get("paper_id") for r in assembled["references"]])
        except Exception as exc:  # noqa: BLE001 — the list stands without the statements
            logger.warning("Statements of %s's papers not read: %s", dtxsid, exc)
            kb["usable"] = False
    entries = [{
        "n": r["n"] + shift, "kind": "paper", "study": key, "study_id": dtxsid,
        "text": None, "url": f"https://doi.org/{r['doi']}" if r.get("doi") else None,
        "title": r.get("title"), "year": r.get("year"), "venue": r.get("venue"),
        "doi": r.get("doi") or None, "genes": list(r.get("genes") or []),
        "cited_in": citing.get(r["n"], []),
        "statements": claims.get(r.get("paper_id"), []) if kb["usable"] else None,
    } for r in assembled["references"]]

    unresolved = [w for w in assembled["warnings"] if w.get("issue") == "unresolved_citation"]
    other = [w for w in assembled["warnings"] if w.get("issue") != "unresolved_citation"]
    untraced = sum(len(w.get("tokens") or []) for w in unresolved)
    check = {
        "where": "interpretations", "study": key, "study_id": dtxsid,
        "untraced": untraced, "removed": True,
        "say": ("Every citation in the gene-level interpretations points at a paper that "
                "was offered." if not untraced else
                f"{untraced} citation{'' if untraced == 1 else 's'} in the gene-level "
                "interpretations could not be traced to a paper that was offered. Each was "
                "removed from the printed text."),
        "items": [{"token": ", ".join(f"[{t}]" for t in w.get("tokens") or []), "sentence": s,
                   "what": f"{interpretation_title(w.get('organ', ''), w.get('sex', ''))}"}
                  for w in unresolved for s in w.get("sentences") or []],
        # Citations in text a person edited, which the assembly cannot reconcile.
        "edited_text_warnings": len(other),
    }
    return entries, check, {"study": key, "study_id": dtxsid, "name": kb["name"],
                            "recorded_name": kb["recorded_name"], "same": kb["same"],
                            "usable": kb["usable"]}


def references(dtxsid: str) -> dict:
    """The reference list as printed, with what cites each entry, the genes a
    paper was offered for, the knowledge base's statements from it, and the
    citation check's result."""
    from ui_api.studies import session_exists, session_folder

    session = session_of(dtxsid)
    kind = _kind(dtxsid)
    entries: list[dict] = []
    checks: list[dict] = []
    knowledge_bases: list[dict] = []
    out: dict = {"id": dtxsid, "kind": kind["kind"], "check_says": CHECK_SAYS}

    if kind["kind"] != "member":
        own, check = _background_entries(dtxsid, session)
        entries += own
        if check is not None:
            checks.append({"where": "background", "study": None, "study_id": dtxsid,
                           "untraced": check["untraced"], "removed": False,
                           "say": check["say"], "items": check["items"],
                           "edited_text_warnings": 0})
    if kind["kind"] == "report":
        shift = len(entries)
        for member in kind["relations"]["members"]:
            if not session_exists(member["id"]):
                continue
            papers, check, kb = _study_entries(member["id"], session_folder(member["id"]),
                                               member["key"], shift)
            entries += papers
            checks.append(check)
            knowledge_bases.append(kb)
            shift += len(papers)
        out["numbering_say"] = ("Numbered as the report prints them: the Background's sources "
                                "first, then each study's papers in turn.")
    else:
        papers, check, kb = _study_entries(dtxsid, session, None, 0)
        entries += papers
        checks.append(check)
        knowledge_bases.append(kb)
        if kind["kind"] == "member":
            out["report"] = {"id": kind["relations"]["parent"]}
            out["numbering_say"] = ("Numbered as this study's own list. The report prints them "
                                    "after its Background's sources and the papers of the "
                                    "studies before this one, so its numbers are higher.")
        else:
            out["numbering_say"] = ("Numbered as the report prints them: the Background's "
                                    "sources first, then the papers the interpretations cite.")

    untraced = sum(c["untraced"] for c in checks)
    out.update({
        "entries": entries,
        "check": {"untraced": untraced,
                  "removed": sum(c["untraced"] for c in checks if c["removed"]),
                  "say": ("Every citation points at a source that was supplied." if not untraced
                          else f"{untraced} citation{'' if untraced == 1 else 's'} could not "
                               "be traced to a supplied source."),
                  "parts": checks},
        "knowledge_bases": knowledge_bases,
    })
    return out
