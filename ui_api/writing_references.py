"""
ui_api.writing_references — a report's citations: the check of the report as
it is presented, the reference list that check derived, the recorded sources
the report does not list, and what the writers cited (the demo path, spec §4
S4; ADR-0038).

Three things are served, and they are different things:

  * **the citation check** (rendering.citations_validate): an act on the
    report as presented, with a record. Where it stands is derived, never
    stored (``not_checked``, ``out_of_date``, ``failed``, ``passed``). The
    reference list and its numbers are not stored either: they are derived
    from what the report prints, so the list served here is the one the last
    check derived, and the answer says when it no longer holds;
  * **the recorded sources the report does not list**, each with the reason:
    the text that cites it is not part of this report, or no text cites it;
  * **the writers' check**: whether each citation a model wrote points at a
    source it was offered (the Background's own record; the gene-level
    interpretations' pools, narrative.references_builder). It is recorded
    with the texts, so it is served whether or not the report was checked.

For a paper of a knowledge base the statements the knowledge base extracted
from it are read from its ``paper_claims`` table (knowledge_base.registry
names the database). Nothing here judges whether a paper supports a sentence,
and the answer says so (``CHECK_SAYS``).

A study of a report prints no list of its own: the answer points at the
report's.

Reading has no side effects.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ui_api.writing import (
    _json, _kind, _latest, citation_check_of_background, interpretation_title, session_of,
)

logger = logging.getLogger(__name__)

# What the checks do and do not establish, in the words the page shows as
# they stand.
CHECK_SAYS = ("The check establishes that a citation points at a source. It does not judge "
              "whether the source supports the sentence.")

NUMBERING_SAY = ("Numbered as the report prints them: each source at its first citation, in "
                 "reading order. Only the sources the printed text cites are listed, each once.")

_KIND_OF_ORIGIN = {"background": "background_source", "knowledge_base": "paper",
                   "library": "boilerplate", "person": "person_source"}

_WHY_NOT_LISTED = {
    "unprinted_text": ("Cited only by text this report does not print: its definition leaves "
                       "that text out."),
    "not_cited": "No text cites it.",
}


# ---------------------------------------------------------------------------
# The check of the report as presented
# ---------------------------------------------------------------------------

def _when(record: dict) -> str:
    stamp = str(record.get("checked_at") or "")
    when = stamp[:16].replace("T", " at ") if stamp else "at an unrecorded time"
    return f"{when}{' by ' + record['checked_by'] if record.get('checked_by') else ''}"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _state_say(state: str, record: dict | None) -> str:
    if state == "not_checked" or not record:
        return ("The citations of this report have not been checked. The reference list is "
                "derived from what the report prints, so there is no list to show until they "
                "are checked.")
    counts = record.get("counts") or {}
    if state == "out_of_date":
        return (f"The report changed after its citations were checked ({_when(record)}). What "
                "is shown below is the result as it was then. Check the citations again.")
    if state == "failed":
        return (f"The check of {_when(record)} found "
                f"{_plural(counts.get('errors', 0), 'error', 'errors')}. Each is listed below. "
                "The report can't be published until they are corrected and the citations are "
                "checked again.")
    warnings = counts.get("warnings", 0)
    return (f"The citations were checked on the report as it stands ({_when(record)}): no error."
            + (f" {_plural(warnings, 'check', 'checks')} could not be made or "
               f"{'needs' if warnings == 1 else 'need'} a look; "
               f"{'it is' if warnings == 1 else 'they are'} listed below." if warnings else ""))


def _check_verdict(dtxsid: str, kind: dict) -> dict:
    """Whether the page offers "Check the citations" on this session, and why
    not (ui_api.writing_acts)."""
    from ui_api.writing_acts import citation_check_verdict
    return citation_check_verdict(dtxsid, kind)


def _printed(dtxsid: str, kind: dict) -> tuple[dict, dict | None]:
    """(where the check stands and what it found, the record)."""
    from rendering.citations_validate import NOT_JUDGED, read_record, status

    record = read_record(dtxsid)
    stand = status(dtxsid, record)
    return {
        "state": stand["state"], "say": _state_say(stand["state"], record),
        "checked_at": (record or {}).get("checked_at"),
        "checked_by": (record or {}).get("checked_by"),
        "counts": (record or {}).get("counts"),
        "tracked": (record or {}).get("tracked"),
        "findings": [{"severity": f.get("severity"), "code": f.get("code"),
                      "say": f.get("message"), "sentences": list(f.get("sentences") or [])}
                     for f in (record or {}).get("findings") or []],
        "not_judged": list((record or {}).get("not_judged") or NOT_JUDGED),
        "act": _check_verdict(dtxsid, kind),
    }, record


# ---------------------------------------------------------------------------
# The entries
# ---------------------------------------------------------------------------

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


def _statements(sources: list[dict]) -> dict[tuple[str, str], list[str] | None]:
    """{(knowledge base, paper id): the statements extracted from the paper},
    None where the knowledge base cannot be read."""
    from knowledge_base import registry

    wanted: dict[str, list[str]] = {}
    for s in sources:
        if s.get("knowledge_base") and s.get("paper_id"):
            wanted.setdefault(s["knowledge_base"], []).append(s["paper_id"])
    out: dict[tuple[str, str], list[str] | None] = {}
    for name, ids in wanted.items():
        try:
            claims = _claims(registry.db_path(name), ids)
        except Exception as exc:  # noqa: BLE001 — the list stands without the statements
            logger.warning("Statements of the papers of %s not read: %s", name, exc)
            claims = None
        for paper_id in ids:
            out[(name, paper_id)] = None if claims is None else claims.get(paper_id, [])
    return out


def _entry(dtxsid: str, source: dict, statements: dict) -> dict:
    """One source of the check's record as the page shows it."""
    kind = _KIND_OF_ORIGIN.get(source.get("origin"), "as_given")
    doi = source.get("doi") or None
    sentences = list(source.get("sentences") or [])
    return {
        "n": source.get("number"), "slug": source.get("slug"), "kind": kind,
        "listed": source.get("number") is not None,
        "why_not_listed": _WHY_NOT_LISTED.get(source.get("reason")),
        "study": None, "study_id": dtxsid,
        "entry": source.get("entry"),
        "text": None if source.get("title") else (source.get("text") or source.get("entry")),
        "url": source.get("url") or (f"https://doi.org/{doi}" if doi else None),
        "title": source.get("title"), "year": source.get("year"),
        "venue": source.get("container"), "doi": doi,
        "genes": list(source.get("genes") or []),
        "knowledge_base": source.get("knowledge_base"),
        "checked": source.get("doi_state") or source.get("address_state"),
        "cited": source.get("cited", 0),
        "cited_in": ([{"part": "", "part_title": "In the report as presented", "study": None,
                       "study_id": dtxsid, "sentences": sentences}] if sentences else []),
        "statements": (statements.get((source.get("knowledge_base"), source.get("paper_id")))
                       if kind == "paper" else None),
    }


# ---------------------------------------------------------------------------
# The writers' check
# ---------------------------------------------------------------------------

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
    return {"name": (kb or {}).get("name"), "recorded_name": recorded.get("name"),
            "same": bool(kb) and (not recorded.get("sha256") or kb.get("sha256") == recorded.get("sha256")),
            "usable": kb is not None}


def _study_check(dtxsid: str, session: Path, key: str | None) -> tuple[dict, dict]:
    """(what a study's gene-level interpretations cited outside the papers
    offered to them, its knowledge base)."""
    from narrative.references_builder import build_session_references

    # The writers' own assembly reports what they cited outside their pools
    # and the citations in text a person edited; its numbering is not used.
    genomics = _latest(session, "genomics") or {}
    warnings = build_session_references(session, genomics, dtxsid=dtxsid)["warnings"]
    unresolved = [w for w in warnings if w.get("issue") == "unresolved_citation"]
    edited = [w for w in warnings if w.get("issue") != "unresolved_citation"]
    untraced = sum(len(w.get("tokens") or []) for w in unresolved)
    kb = _knowledge_base(dtxsid, session)
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
        # Citations in text a person edited, which no record ties to a source.
        "edited_text_warnings": len(edited),
    }
    return check, {"study": key, "study_id": dtxsid, **kb}


# ---------------------------------------------------------------------------
# The read
# ---------------------------------------------------------------------------

def references(dtxsid: str) -> dict:
    """The check of the report's citations, the reference list it derived
    (with what cites each entry and what the knowledge base holds of a paper),
    the recorded sources not listed, and the writers' check."""
    from ui_api.studies import session_exists, session_folder

    session = session_of(dtxsid)
    kind = _kind(dtxsid)
    checks: list[dict] = []
    knowledge_bases: list[dict] = []
    out: dict = {"id": dtxsid, "kind": kind["kind"], "check_says": CHECK_SAYS,
                 "numbering_say": NUMBERING_SAY}

    if kind["kind"] != "member":
        check = citation_check_of_background(_json(session / "background.json"))
        if check is not None:
            checks.append({"where": "background", "study": None, "study_id": dtxsid,
                           "untraced": check["untraced"], "removed": False,
                           "say": check["say"], "items": check["items"],
                           "edited_text_warnings": 0})
    if kind["kind"] == "report":
        for member in kind["relations"]["members"]:
            if not session_exists(member["id"]):
                continue
            check, kb = _study_check(member["id"], session_folder(member["id"]), member["key"])
            checks.append(check)
            knowledge_bases.append(kb)
    else:
        check, kb = _study_check(dtxsid, session, None)
        checks.append(check)
        knowledge_bases.append(kb)

    entries: list[dict] = []
    not_listed: list[dict] = []
    if kind["kind"] == "member":
        # The report prints the list; a study of it has none of its own.
        out["report"] = {"id": kind["relations"]["parent"]}
        out["printed"] = None
    else:
        out["printed"], record = _printed(dtxsid, kind)
        listed = list((record or {}).get("references") or [])
        idle = list((record or {}).get("not_listed") or [])
        statements = _statements(listed + idle)
        entries = [_entry(dtxsid, s, statements) for s in listed]
        not_listed = [_entry(dtxsid, s, statements) for s in idle]

    untraced = sum(c["untraced"] for c in checks)
    out.update({
        "entries": entries,
        "not_listed": not_listed,
        "check": {"untraced": untraced,
                  "removed": sum(c["untraced"] for c in checks if c["removed"]),
                  "say": ("Every citation a model wrote points at a source that was supplied "
                          "to it." if not untraced
                          else f"{untraced} citation{'' if untraced == 1 else 's'} a model "
                               "wrote could not be traced to a supplied source."),
                  "parts": checks},
        "knowledge_bases": knowledge_bases,
    })
    return out
