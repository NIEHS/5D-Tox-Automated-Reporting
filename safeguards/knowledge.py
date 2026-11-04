"""
safeguards.knowledge — a report reads only a knowledge base that can ground
its genomics interpretation.

A knowledge base holds what its crawl query asked for (knowledge_base.registry
capabilities): a query that extracts no genes makes one that cannot answer the
genomics interpretation's questions.  Assigning such a knowledge base to a
report, or making it the default every report falls back to, is refused, with
what it lacks; so is one that is unknown or unfinished, and an assignment a
report would not see (its document definition is fixed).  The core steps
(document_model.knowledge_base_assignment, registry.set_default) assign what
they are given: the notebook may.
"""

from __future__ import annotations

from safeguards.refusals import Refused


def require_serves_genomics(name: str) -> dict:
    """The manifest of ``name``, refused unless it is finished and holds what
    the genomics interpretation reads."""
    from knowledge_base import registry
    try:
        m = registry.manifest(name)
    except registry.KnowledgeBaseError as e:
        raise Refused("knowledge_base_unknown", str(e), 404, {"name": name}) from None
    if not m.get("complete") or not (registry.kb_dir(name) / registry.DB_FILE).exists():
        missing = [s["stage"] for s in m.get("stages", []) if s.get("status") != "ran"
                   and s.get("status") != "skipped"]
        raise Refused("knowledge_base_unfinished",
                      f"knowledge base {name!r} is unfinished: stage(s) {missing} did not run",
                      409, {"name": name, "missing": ", ".join(missing) or "the database"})
    lacking = sorted(registry.GENOMICS_NEEDS - set(m.get("capabilities") or []))
    if lacking:
        raise Refused("knowledge_base_cannot_serve",
                      f"knowledge base {name!r} cannot answer {lacking} "
                      f"(it holds {m.get('capabilities') or []})",
                      409, {"name": name, "lacking": ", ".join(lacking),
                            "holds": m.get("capabilities") or []})
    return m


def require_assignable(dtxsid: str, name: str | None) -> None:
    """Before naming ``name`` in the report's definition (None: back to the
    default): the definition is not fixed, and the knowledge base serves."""
    import common.paths
    from document_model.definition_pin import FIXED, read_pin
    from document_model.knowledge_base_assignment import report_id
    from rendering.published_clone import CLONE_FILE
    from safeguards.refusals import StudyRefusal
    if (common.paths.SESSIONS_DIR / dtxsid / CLONE_FILE).is_file():
        raise StudyRefusal("read_only_session",
                           f"{dtxsid} is a published book's companion ({CLONE_FILE}); "
                           "its knowledge base is not assigned here", 409, {"id": dtxsid})
    report = report_id(dtxsid)
    for session in dict.fromkeys([dtxsid, report]):
        pin = read_pin(session)
        if pin and pin.get("mode") == FIXED:
            raise Refused("knowledge_base_definition_fixed",
                          f"{session} renders from its fixed document definition; "
                          "re-pin it to track before assigning a knowledge base",
                          409, {"id": session})
    if name is not None:
        require_serves_genomics(name)


# ---------------------------------------------------------------------------
# A query that would send a study's results to a public service
# ---------------------------------------------------------------------------

def _sent_text(query: dict) -> list[str]:
    """The strings of a query that its run sends to Semantic Scholar: the
    crawls' searches, the follow-on crawls' stated entities, focus, search
    templates and tag terms."""
    out: list[str] = []
    for crawl in query.get("crawls") or []:
        out += [str(s.get("query", "")) for s in crawl.get("searches") or []
                if isinstance(s, dict)]
    for fo in query.get("follow_on") or []:
        if isinstance(fo.get("entities"), list):
            for e in fo["entities"]:
                out += [str(e.get("entity", "")), str(e.get("focus", ""))]
        out += [str(t).replace("{entity}", " ").replace("{tag_term}", " ")
                for t in fo.get("templates") or []]
        for terms in (fo.get("tag_terms") or {}).values():
            out += [str(t) for t in terms or []]
    return out


def _unpublished_sessions() -> list[str]:
    """Sessions whose study has no published book here: no ``<id>_published``
    companion, and not a companion themselves."""
    import common.paths
    from rendering.published_clone import CLONE_FILE
    root = common.paths.SESSIONS_DIR
    names = {p.name for p in root.iterdir() if p.is_dir()} if root.exists() else set()
    from common.dtxsid import is_valid_dtxsid
    return sorted(n for n in names
                  if is_valid_dtxsid(n) and not (root / n / CLONE_FILE).is_file()
                  and f"{n.split('_', 1)[0]}_published" not in names)


def _responsive_genes(session: str) -> set[str]:
    import json
    import common.paths
    genes: set[str] = set()
    for path in (common.paths.SESSIONS_DIR / session).glob("_cache_genomics_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for stratum in data.values() if isinstance(data, dict) else []:
            for g in (stratum or {}).get("all_genes") or [] if isinstance(stratum, dict) else []:
                if isinstance(g, dict) and g.get("gene_symbol"):
                    genes.add(str(g["gene_symbol"]).upper())
    return genes


def _words(query: dict | None) -> set[str]:
    import re
    return {w.upper() for s in _sent_text(query or {}) for w in re.findall(r"[A-Za-z0-9-]+", s)}


def unpublished_results_named(query: dict, previous: dict | None = None) -> list[dict]:
    """A warning, not a refusal: the genes of unpublished studies' results that
    the query would send to Semantic Scholar and ``previous`` (the text it was
    edited from) did not, ``[{session, genes}]``.  Whether a query naming them
    may be saved is the person's call (the maintainer may make it a refusal)."""
    words = _words(query) - _words(previous)
    if not words:
        return []
    out = []
    for session in _unpublished_sessions():
        named = sorted(words & _responsive_genes(session))
        if named:
            out.append({"session": session, "genes": named})
    return out
