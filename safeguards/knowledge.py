"""
safeguards.knowledge — a report reads only a knowledge base that can ground
its genomics interpretation; a crawl never ties a test article to genes in what
it sends to a public service.

A knowledge base holds what its crawl query asked for (knowledge_base.registry
capabilities): a query that extracts no genes makes one that cannot answer the
genomics interpretation's questions.  Assigning such a knowledge base to a
report, or making it the default every report falls back to, is refused, with
what it lacks; so is one that is unknown or unfinished, and an assignment a
report would not see (its document definition is fixed).  The core steps
(document_model.knowledge_base_assignment, registry.set_default) assign what
they are given: the notebook may.

A crawl query's searches go to Semantic Scholar, a public service, when it
runs.  A search about a gene or an organ says nothing of a study; a search
that names a test article (its name, abbreviation, CASRN or DTXSID, from any
session's identity.json) beside genes would tie them to it.  So the
maintainer's rule (2026-11-06): a crawl is broadly scoped and names no test
article; a test-article crawl is kept separate and names no gene — no gene
symbol in what it sends, and no follow-on crawl seeded from extracted
entities.  ``require_query_allowed`` refuses a query that breaks it, at save
(``require_query_may_be_saved``) and at run (``require_crawl_may_run``),
however the text was written.
"""

from __future__ import annotations

import re

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


def _test_articles() -> dict[str, str]:
    """{term: session} — every study's test-article identity on this machine:
    its name, abbreviation, CASRN and DTXSID (identity.json, and the session
    id itself)."""
    import json
    import common.paths
    from common.dtxsid import is_valid_dtxsid
    root = common.paths.SESSIONS_DIR
    terms: dict[str, str] = {}
    for d in sorted(root.iterdir()) if root.exists() else []:
        if not (d.is_dir() and is_valid_dtxsid(d.name)):
            continue
        study = d.name.split("_", 1)[0]
        try:
            ident = json.loads((d / "identity.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ident = {}
        for key in ("name", "abbreviation", "casrn", "dtxsid"):
            value = str((ident or {}).get(key) or "").split("_", 1)[0].strip()
            if len(value) >= 3:
                terms.setdefault(value.lower(), study)
        terms.setdefault(study.lower(), study)
    return terms


def test_articles_named(query: dict) -> list[dict]:
    """``[{study, term}]``: the test articles the query's sent text names."""
    text = " ".join(_sent_text(query)).lower()
    found = []
    for term, study in _test_articles().items():
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text):
            found.append({"study": study, "term": term})
    return found


def _gene_symbols() -> set[str]:
    """The gene symbols the finished knowledge bases know (their genes tables)."""
    import duckdb
    from knowledge_base import registry
    symbols: set[str] = set()
    for m in registry.list_knowledge_bases():
        if not m.get("complete") or "genes" not in (m.get("capabilities") or []):
            continue
        db = registry.kb_dir(m["name"]) / registry.DB_FILE
        try:
            con = duckdb.connect(str(db), read_only=True)
            try:
                symbols |= {r[0].upper() for r in con.execute(
                    "SELECT gene_symbol FROM genes").fetchall() if r[0]}
            finally:
                con.close()
        except (duckdb.Error, OSError):
            continue
    return symbols


def genes_named(query: dict) -> list[str]:
    """The gene symbols the query's sent text names: a word written as a symbol
    (with a capital or a digit after its first letter: NFE2L2, Nrf2, TNF — not
    "rest" or "cat") that a knowledge base knows as a gene."""
    words = {w for s in _sent_text(query) for w in re.findall(r"[A-Za-z0-9-]{2,}", s)
             if re.search(r"[A-Z0-9]", w[1:])}
    if not words:
        return []
    symbols = _gene_symbols()
    return sorted({w.upper() for w in words if w.upper() in symbols})


def require_query_allowed(name: str, query: dict) -> None:
    """Refuse a query that would send a test article's identity with genes:
    a crawl names no test article, or names no gene (and seeds no follow-on
    crawl from extracted entities)."""
    articles = test_articles_named(query)
    if not articles:
        return
    genes = genes_named(query)
    seeded = [fo.get("name") for fo in query.get("follow_on") or []
              if fo.get("entities") == "consensus"]
    if genes or seeded:
        named = ", ".join(sorted({a["term"] for a in articles}))
        why = (f"genes ({', '.join(genes[:12])}{' …' if len(genes) > 12 else ''})" if genes
               else f"follow-on crawls seeded from extracted entities ({', '.join(seeded)})")
        raise Refused("crawl_query_ties_article_to_genes",
                      f"crawl query {name!r} names a test article ({named}) and {why}", 422,
                      {"articles": named, "genes": ", ".join(genes) or "none named",
                       "follow_on": ", ".join(seeded) or "none", "why": why})


def require_query_may_be_saved(name: str, query: dict) -> None:
    """Before saving ``query`` as ``name`` (require_query_allowed)."""
    require_query_allowed(name, query)


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


def require_crawl_may_run(query_name: str, kb_name: str, resume: bool) -> None:
    """Before running the query ``query_name`` into ``kb_name``: the names
    are names, the query reads, the knowledge base its relevance floor reads
    is usable, ``kb_name`` can take the run (not finished; an unfinished one
    resumed from the same text), and the query does not tie a test article to
    genes (require_query_allowed)."""
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
    require_query_allowed(query_name, run.query)
