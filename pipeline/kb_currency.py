"""
pipeline/kb_currency.py — a session's genomics interpretation stays with the
knowledge base it was written from.

The interpretation of each organ × sex (narrative.genomics_llm) is grounded
in the report's knowledge base (knowledge_base.registry.kb_for) and kept in
``_cache_interpretation_*.json``, a narrative store that is never rewritten
unasked.  So when the knowledge base a report reads changes — its document
definition names another, or the default moves — the store is set aside
(archived under ``history/_knowledge_base/``, never deleted) and the sections
written from it (the catalog's knowledge-base sections:
workflow.section_catalog.is_grounded_in_knowledge_base) are marked stale with
the reason ``knowledge_base_changed``: Process writes them again from the new
knowledge base, and the publish gate waits until a person accepts them again,
as after a data change (pipeline.pool_state).

A report whose knowledge base cannot be resolved (none assigned, or the one
named is missing or unfinished: a store moved, a mistyped name) has not
changed knowledge base: nothing is set aside and nothing recorded, and the
interpretation is not written again until it resolves (narrative.genomics_llm
keeps the store it has).

The session records the knowledge base it last processed with in
``knowledge_base.json`` ({name, sha256}).  A session processed before
knowledge bases were named has no record; it read the database the
registry's ``replaces: bmdx.duckdb`` knowledge base was registered from.
"""

from __future__ import annotations

import json
import logging

import common.paths

logger = logging.getLogger(__name__)

RECORD_FILE = "knowledge_base.json"
CACHE_GLOB = "_cache_interpretation_*.json"
# Where a set-aside interpretation store goes (beside the sections' history).
ARCHIVE_DIR = "history/_knowledge_base"
# What a session processed before named knowledge bases read.
LEGACY_DATABASE = "bmdx.duckdb"


def _legacy() -> dict | None:
    """{name, sha256} of the knowledge base registered from the database every
    session read before knowledge bases were named."""
    from knowledge_base.registry import list_knowledge_bases
    for m in list_knowledge_bases():
        if m.get("replaces") == LEGACY_DATABASE:
            return {"name": m.get("name"), "sha256": m.get("sha256")}
    return None


def recorded(dtxsid: str) -> dict | None:
    path = common.paths.SESSIONS_DIR / dtxsid / RECORD_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def current(dtxsid: str) -> dict:
    """{name, sha256} of the knowledge base the session's report reads now;
    ``{name: None, sha256: None, problem}`` when none can serve its genomics
    interpretation."""
    from knowledge_base.registry import KnowledgeBaseError, kb_for
    try:
        kb = kb_for(dtxsid)
    except KnowledgeBaseError as e:
        return {"name": None, "sha256": None, "problem": str(e)}
    return {"name": kb["name"], "sha256": kb["sha256"]}


def _archive(session, before: dict) -> list[str]:
    """Move the interpretation store aside: ``history/_knowledge_base/<stamp>-
    <previous name>/``.  Returns the files moved."""
    from common.clock import now_iso
    caches = sorted(session.glob(CACHE_GLOB))
    if not caches:
        return []
    dest = session / ARCHIVE_DIR / f"{now_iso().replace(':', '')}-{before.get('name') or 'unknown'}"
    dest.mkdir(parents=True, exist_ok=True)
    for cache in caches:
        cache.replace(dest / cache.name)
    return [c.name for c in caches]


def reconcile(dtxsid: str) -> dict:
    """Bring the session's genomics interpretation in line with its knowledge
    base: on a change, archive the interpretation store and stale the sections
    written from it.  Records the current one.  Returns ``{knowledge_base,
    previous, changed, archived, marked_stale}`` (``knowledge_base.problem``
    when none resolves: then nothing is changed)."""
    from pipeline.pool_state import stale_sections
    from workflow.section_catalog import is_grounded_in_knowledge_base

    session = common.paths.SESSIONS_DIR / dtxsid
    now = current(dtxsid)
    before = recorded(dtxsid)
    if before is None:
        before = _legacy() if any(session.glob(CACHE_GLOB)) else None
    out = {"knowledge_base": now, "previous": before, "changed": False,
           "archived": [], "marked_stale": []}
    if now["name"] is None:
        logger.warning("No usable knowledge base for %s (%s): its genomics interpretation "
                       "is kept as it is", dtxsid, now["problem"])
        return out
    out["changed"] = before is not None and (before.get("name"), before.get("sha256")) != (
        now["name"], now["sha256"])
    if out["changed"]:
        out["archived"] = _archive(session, before)
        out["marked_stale"] = stale_sections(
            dtxsid, lambda stem, _section: is_grounded_in_knowledge_base(stem),
            "knowledge_base_changed")
        logger.warning("Knowledge base of %s changed: %s → %s; genomics interpretation "
                       "archived (%d store files), %d section(s) stale", dtxsid,
                       before.get("name"), now["name"], len(out["archived"]),
                       len(out["marked_stale"]))
    if session.is_dir() and recorded(dtxsid) != now:
        (session / RECORD_FILE).write_text(json.dumps(now, indent=2) + "\n", encoding="utf-8")
    return out
