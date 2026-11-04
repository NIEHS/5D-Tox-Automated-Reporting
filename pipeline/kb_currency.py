"""
pipeline/kb_currency.py — a session's genomics interpretation stays with the
knowledge base it was written from.

The interpretation of each organ × sex (narrative.genomics_llm) is grounded
in the report's knowledge base (knowledge_base.registry.kb_for) and kept in
``_cache_interpretation_*.json``, a narrative store that is never rewritten
unasked.  So when the knowledge base a report reads changes — its document
definition names another, or the default moves — the store is discarded and
the sections written from it (the catalog's knowledge-base sections:
workflow.section_catalog.is_grounded_in_knowledge_base) are marked stale with
the reason ``knowledge_base_changed``: Process writes them again from the new
knowledge base, and the publish gate waits until a person accepts them again,
as after a data change (pipeline.pool_state).

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
    """{name, sha256} of the knowledge base the session's report reads now
    ({name: None} when none can serve its genomics interpretation)."""
    from knowledge_base.registry import kb_or_none
    kb = kb_or_none(dtxsid)
    return {"name": kb["name"], "sha256": kb["sha256"]} if kb else {"name": None, "sha256": None}


def reconcile(dtxsid: str) -> dict:
    """Bring the session's genomics interpretation in line with its knowledge
    base: on a change, discard the interpretation store and stale the sections
    written from it.  Records the current one.  Returns
    ``{knowledge_base, previous, changed, deleted, marked_stale}``."""
    from pipeline.pool_state import stale_sections
    from workflow.section_catalog import is_grounded_in_knowledge_base

    session = common.paths.SESSIONS_DIR / dtxsid
    now = current(dtxsid)
    before = recorded(dtxsid)
    if before is None:
        before = _legacy() if any(session.glob(CACHE_GLOB)) else None
    changed = before is not None and (before.get("name"), before.get("sha256")) != (
        now["name"], now["sha256"])
    out = {"knowledge_base": now, "previous": before, "changed": changed,
           "deleted": [], "marked_stale": []}
    if changed:
        for cache in sorted(session.glob(CACHE_GLOB)):
            cache.unlink()
            out["deleted"].append(cache.name)
        out["marked_stale"] = stale_sections(
            dtxsid, lambda stem, _section: is_grounded_in_knowledge_base(stem),
            "knowledge_base_changed")
        logger.warning("Knowledge base of %s changed: %s → %s; genomics interpretation "
                       "discarded (%d store files), %d section(s) stale", dtxsid,
                       before.get("name"), now["name"], len(out["deleted"]),
                       len(out["marked_stale"]))
    if session.is_dir() and recorded(dtxsid) != now:
        (session / RECORD_FILE).write_text(json.dumps(now, indent=2) + "\n", encoding="utf-8")
    return out
