"""
safeguards.knowledge — a report reads only a knowledge base that can ground
its genomics interpretation; a crawl sends no unpublished study's results to a
public service unasked.

A knowledge base holds what its crawl query asked for (knowledge_base.registry
capabilities): a query that extracts no genes makes one that cannot answer the
genomics interpretation's questions.  Assigning such a knowledge base to a
report, or making it the default every report falls back to, is refused, with
what it lacks; so is one that is unknown or unfinished, and an assignment a
report would not see (its document definition is fixed).  The core steps
(document_model.knowledge_base_assignment, registry.set_default) assign what
they are given: the notebook may.

A crawl query's searches go to Semantic Scholar when it runs, so running one
(``require_crawl_may_run``) whose searches name genes of an unpublished study's
results, that no crawl has sent before, waits for the person to confirm: the
run is when they leave, however the text was written (the query agent, the
editor, the file itself).  Saving such a text through the application
(``require_query_may_be_saved``) asks the same, earlier, against the text it
was edited from.
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


def _named(words: set[str]) -> list[dict]:
    if not words:
        return []
    out = []
    for session in _unpublished_sessions():
        named = sorted(words & _responsive_genes(session))
        if named:
            out.append({"session": session, "genes": named})
    return out


def unpublished_results_named(query: dict, previous: dict | None = None) -> list[dict]:
    """The genes of unpublished studies' results that the query would send to
    Semantic Scholar and ``previous`` (the text it was edited from) did not,
    ``[{session, genes}]``."""
    return _named(_words(query) - _words(previous))


def _already_sent() -> set[str]:
    """The words every crawl run so far has sent (the query text each knowledge
    base's manifest records): sending them again exposes nothing new."""
    import yaml
    from knowledge_base import registry
    words: set[str] = set()
    for m in registry.list_knowledge_bases():
        try:
            query = yaml.safe_load((m.get("query") or {}).get("text") or "")
            words |= _words(query if isinstance(query, dict) else None)
        except (yaml.YAMLError, AttributeError, TypeError):
            continue
    return words


def unpublished_results_to_send(query: dict) -> list[dict]:
    """The genes of unpublished studies' results that running ``query`` would
    send to Semantic Scholar and no crawl has sent before, ``[{session, genes}]``."""
    return _named(_words(query) - _already_sent())


def _exposure_details(exposed: list[dict]) -> dict:
    return {"unpublished_results": exposed, "needs_confirmation": True,
            "genes": "; ".join(f"{', '.join(e['genes'])} ({e['session']})" for e in exposed)}


def require_query_may_be_saved(name: str, query: dict, previous: dict | None,
                               confirm: bool) -> list[dict]:
    """Before saving ``query`` as ``name``: refused while it newly names an
    unpublished study's genes (against ``previous``, the text it was edited
    from) and the person has not confirmed.  Returns what it names."""
    exposed = unpublished_results_named(query, previous)
    if exposed and not confirm:
        raise Refused("crawl_query_names_unpublished_results",
                      f"crawl query {name!r} newly names genes of unpublished results",
                      409, _exposure_details(exposed))
    return exposed


def _require_usable(name: str) -> None:
    from knowledge_base import registry
    try:
        registry.usable(name)
    except registry.KnowledgeBaseError as e:
        try:
            m = registry.manifest(name)
        except registry.KnowledgeBaseError:
            raise Refused("knowledge_base_unknown", str(e), 404, {"name": name}) from None
        missing = [s["stage"] for s in m.get("stages", [])
                   if s.get("status") not in ("ran", "skipped")]
        raise Refused("knowledge_base_unfinished", str(e), 409,
                      {"name": name, "missing": ", ".join(missing) or "the database"}) from None


def require_crawl_may_run(query_name: str, kb_name: str, resume: bool,
                          confirm: bool) -> list[dict]:
    """Before running the query ``query_name`` into ``kb_name``: the names
    are names, the query reads, the knowledge base its relevance floor reads
    is usable, ``kb_name`` can take the run (not finished; an unfinished one
    resumed from the same text), and — unless the person confirms — it sends
    no unpublished study's genes no crawl has sent before.  Returns what it
    sends of them."""
    from knowledge_base import crawl_queries, registry
    from knowledge_base.run_crawl import Run
    for check in (crawl_queries.check_name, registry.check_name):
        try:
            check(query_name if check is crawl_queries.check_name else kb_name)
        except ValueError as e:
            raise Refused("bad_request", str(e), 422) from None
    try:
        run = Run(query_name, kb_name, resume)
    except crawl_queries.QueryError as e:
        raise Refused("crawl_query_invalid", str(e), 422, {"problem": str(e)}) from None
    floor = (run.query.get("relevance") or {}).get("floor") or {}
    if floor.get("entities_from"):
        _require_usable(floor["entities_from"])
    try:
        run.check()
    except registry.KnowledgeBaseError as e:
        raise Refused("knowledge_base_name_taken", str(e), 409, {"name": kb_name}) from None
    exposed = unpublished_results_to_send(run.query)
    if exposed and not confirm:
        raise Refused("crawl_names_unpublished_results",
                      f"crawl query {query_name!r} would send genes of unpublished results",
                      409, _exposure_details(exposed))
    return exposed
