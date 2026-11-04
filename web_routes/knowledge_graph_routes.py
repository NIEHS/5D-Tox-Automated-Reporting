"""
HTTP routes for the crawl queries and the knowledge bases made from them.

A crawl query is named YAML text (knowledge_base.crawl_queries): read it, save
an edit (the old text archived), or ask the query agent for a proposed edit
(knowledge_base.query_agent — it saves nothing).  A named crawl runs a query
into a named knowledge base in the background (knowledge_base.run_crawl); its
progress is its manifest.  A report reads the knowledge base its document
definition names, else the default (knowledge_base.registry): assigning one
and setting the default go through the safeguards (safeguards.knowledge),
which refuse a knowledge base that cannot ground a report's genomics
interpretation.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from knowledge_base import crawl_queries, registry
from safeguards.refusals import Refused
from web_routes.dtxsid_param import Dtxsid
from web_routes.refusal_response import refusal_response

logger = logging.getLogger(__name__)

router = APIRouter()

# Knowledge bases a crawl is running into (this process): one run per name.
_running: set[str] = set()
_running_lock = threading.Lock()


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise Refused("bad_request", "body must be a JSON object", 422)
    return body


def _invalid(e: Exception) -> Refused:
    return Refused("crawl_query_invalid", str(e), 422, {"problem": str(e)})


def _kb_refusal(e: registry.KnowledgeBaseError, name: str) -> Refused:
    return Refused("knowledge_base_name_taken", str(e), 409, {"name": name})


# ---------------------------------------------------------------------------
# Crawl queries
# ---------------------------------------------------------------------------

@router.get("/api/crawl-queries")
async def api_list_queries():
    return JSONResponse({"queries": crawl_queries.list_queries(), "format": crawl_queries.FORMAT})


@router.get("/api/crawl-queries/{name}")
async def api_get_query(name: str):
    try:
        text = crawl_queries.read(name)
    except crawl_queries.QueryError as e:
        return refusal_response(_invalid(e))
    return JSONResponse({"name": name, "text": text, "hash": crawl_queries.text_hash(text),
                         "history": crawl_queries.history(name)})


@router.post("/api/crawl-queries/check")
async def api_check_query(request: Request):
    """Whether a text is a query the crawl can read (nothing saved)."""
    try:
        body = await _body(request)
        crawl_queries.parse(str(body.get("text") or ""))
    except Refused as e:
        return refusal_response(e)
    except crawl_queries.QueryError as e:
        return JSONResponse({"valid": False, "problem": str(e)})
    return JSONResponse({"valid": True, "problem": None})


@router.post("/api/crawl-queries/{name}")
async def api_save_query(name: str, request: Request):
    """Save ``{text}`` as the query ``name`` (an existing text archived first).

    A text whose searches would send genes of an unpublished study's results
    to Semantic Scholar, that the text it was edited from (``from``: a query's
    name; else the saved text of ``name``) did not, is not saved until the
    person confirms (``confirm: true``): the reply names them."""
    from safeguards.knowledge import unpublished_results_named
    try:
        body = await _body(request)
        text = str(body.get("text") or "")
        query = crawl_queries.parse(text)
        source = body.get("from") or name
        try:
            previous = crawl_queries.parse(crawl_queries.read(source))
        except crawl_queries.QueryError:
            previous = None
        exposed = unpublished_results_named(query, previous)
        if exposed and not body.get("confirm"):
            return JSONResponse({"saved": False, "needs_confirmation": True,
                                 "unpublished_results": exposed}, status_code=409)
        saved = crawl_queries.save(name, text)
    except Refused as e:
        return refusal_response(e)
    except crawl_queries.QueryError as e:
        return refusal_response(_invalid(e))
    if exposed:
        logger.warning("Crawl query %s saved naming unpublished results (confirmed): %s",
                       name, exposed)
    return JSONResponse({"saved": True, **saved, "unpublished_results": exposed})


@router.get("/api/crawl-queries/{name}/history/{entry}")
async def api_query_history_entry(name: str, entry: str):
    """One archived text of a query (an entry of its ``history``)."""
    if entry not in crawl_queries.history(name):
        return JSONResponse({"error": f"no archived text {entry!r} of {name!r}"}, status_code=404)
    path = crawl_queries.QUERIES_DIR / crawl_queries.HISTORY_DIR / name / entry
    return JSONResponse({"name": name, "entry": entry, "text": path.read_text(encoding="utf-8")})


@router.post("/api/crawl-queries/{name}/propose")
async def api_propose_query_edit(name: str, request: Request):
    """The query agent's proposed edit: ``{request, text?, earlier?}`` →
    ``{text, explanation, diff, changed, valid, problem}``.  ``text`` is the
    text being edited (default: the saved one).  Nothing is saved."""
    from knowledge_base.query_agent import propose
    try:
        body = await _body(request)
        text = body.get("text")
        if text is None:
            text = crawl_queries.read(name)
        result = await asyncio.to_thread(propose, str(text), str(body.get("request") or ""),
                                         earlier=body.get("earlier") or [])
    except Refused as e:
        return refusal_response(e)
    except crawl_queries.QueryError as e:
        return refusal_response(_invalid(e))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    except Exception as e:  # the gateway: LLMEgressBlocked and the like
        return refusal_response(e)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Knowledge bases
# ---------------------------------------------------------------------------

@router.get("/api/knowledge-bases")
async def api_list_knowledge_bases():
    """Every knowledge base (its manifest, without the query text), and the default."""
    out = []
    for m in registry.list_knowledge_bases():
        m = dict(m)
        m["query"] = {k: v for k, v in (m.get("query") or {}).items() if k != "text"}
        m["running"] = m.get("name") in _running
        out.append(m)
    return JSONResponse({"knowledge_bases": out, "default": registry.default_name()})


@router.get("/api/knowledge-bases/{name}")
async def api_get_knowledge_base(name: str):
    try:
        m = registry.manifest(name)
    except registry.KnowledgeBaseError as e:
        return refusal_response(Refused("knowledge_base_unknown", str(e), 404, {"name": name}))
    return JSONResponse({**m, "running": name in _running})


def _run_in_background(query: str, name: str, resume: bool) -> None:
    from knowledge_base.run_crawl import run
    try:
        m = run(query, name, resume)
        logger.info("Crawl %s → %s finished: complete=%s", query, name, m.get("complete"))
    except Exception:
        logger.exception("Crawl %s → %s failed", query, name)
    finally:
        with _running_lock:
            _running.discard(name)


@router.post("/api/knowledge-bases/run")
async def api_run_crawl(request: Request):
    """Run ``{query, name, resume?}`` into the knowledge base ``name``, in the
    background.  Its progress is its manifest (GET /api/knowledge-bases/{name})."""
    from knowledge_base.run_crawl import Run
    try:
        body = await _body(request)
        query, name = str(body.get("query") or ""), str(body.get("name") or "")
        resume = bool(body.get("resume"))
        try:
            registry.check_name(name)
        except registry.KnowledgeBaseError as e:
            raise Refused("bad_request", str(e), 422) from None
        try:
            Run(query, name, resume).check()     # refuses a taken name before starting
        except registry.KnowledgeBaseError as e:
            raise _kb_refusal(e, name) from None
        with _running_lock:
            if name in _running:
                raise Refused("crawl_running", f"a crawl into {name!r} is running", 409,
                              {"name": name})
            _running.add(name)
    except Refused as e:
        return refusal_response(e)
    except crawl_queries.QueryError as e:
        return refusal_response(_invalid(e))
    threading.Thread(target=_run_in_background, args=(query, name, resume),
                     name=f"crawl-{name}", daemon=True).start()
    return JSONResponse({"started": True, "query": query, "name": name}, status_code=202)


@router.post("/api/knowledge-bases/default")
async def api_set_default_knowledge_base(request: Request):
    """Make ``{name}`` the knowledge base of every report that names none."""
    from safeguards.guarded import set_default_knowledge_base
    try:
        body = await _body(request)
        name = str(body.get("name") or "")
        set_default_knowledge_base(name)
    except Refused as e:
        return refusal_response(e)
    return JSONResponse({"default": name})


@router.get("/api/session/{dtxsid}/knowledge-base")
async def api_session_knowledge_base(dtxsid: Dtxsid):
    """The knowledge base the session's report reads: its definition's, else
    the default; ``usable`` false when it cannot ground the genomics
    interpretation (the reason in ``problem``)."""
    from pipeline.kb_currency import recorded
    name, source = registry.assigned_name(dtxsid)
    try:
        kb = registry.kb_for(dtxsid)
        problem = None
    except registry.KnowledgeBaseError as e:
        kb, problem = None, str(e)
    return JSONResponse({"name": name, "source": source, "usable": kb is not None,
                         "problem": problem, "capabilities": (kb or {}).get("capabilities"),
                         "processed_with": recorded(dtxsid)})


@router.post("/api/session/{dtxsid}/knowledge-base")
async def api_assign_knowledge_base(dtxsid: Dtxsid, request: Request):
    """Name ``{name}`` in the report's document definition (``null``: read the
    default again).  The next Process takes it up."""
    from safeguards.guarded import assign_knowledge_base
    try:
        body = await _body(request)
        name = body.get("name")
        result = assign_knowledge_base(dtxsid, str(name) if name is not None else None)
    except Refused as e:
        return refusal_response(e)
    except registry.KnowledgeBaseError as e:
        return refusal_response(Refused("knowledge_base_unknown", str(e), 404, {"name": name}))
    return JSONResponse(result)
