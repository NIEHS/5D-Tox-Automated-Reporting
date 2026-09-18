"""
HTTP routes for the corpus curation editor.

Exposes the literature knowledge base's organ vocabulary for per-session
curation, tracked as an append-only tweak-log against the frozen original.
The curated working corpus (corpus.duckdb) is materialized on demand from the
log — the log is the source of truth, the DB is its projection.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from knowledge_base import corpus_curation as cc

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/corpus/{dtxsid}/organs")
async def api_corpus_organs(dtxsid: str):
    """The organ inventory (term, frequencies, current mapping) + curated flag."""
    return JSONResponse({
        "inventory": cc.organ_inventory(dtxsid),
        "canonical": cc.canonical_organs(),
        "is_curated": cc.is_curated(dtxsid),
    })


@router.get("/api/corpus/{dtxsid}/history")
async def api_corpus_history(dtxsid: str):
    """The live append-only tweak-log (oldest → newest)."""
    return JSONResponse({"tweaks": cc.read_tweaks(dtxsid)})


@router.post("/api/corpus/{dtxsid}/organs/map")
async def api_corpus_map_organ(dtxsid: str, request: Request):
    """Append a map/drop tweak. 422 on invalid, nothing written. No materialize."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=422)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be an object"}, status_code=422)

    try:
        record = cc.append_tweak(dtxsid, {
            "op": "map_organ",
            "from": body.get("from"),
            "to": body.get("to"),  # null ⇒ drop
        })
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)

    return JSONResponse({
        "ok": True,
        "tweak": record,
        "net_map": cc.current_organ_map(dtxsid),
    })


@router.post("/api/corpus/{dtxsid}/materialize")
async def api_corpus_materialize(dtxsid: str):
    """Build corpus.duckdb by projecting the tweak-log onto the frozen original."""
    try:
        result = cc.materialize(dtxsid)
    except Exception as exc:  # materialization touches the filesystem + DuckDB
        logger.exception("corpus materialize failed for %s", dtxsid)
        return JSONResponse({"error": str(exc)}, status_code=500)
    return JSONResponse({"ok": True, **result})


@router.post("/api/corpus/{dtxsid}/reset")
async def api_corpus_reset(dtxsid: str):
    """Revert to the frozen original (remove log, corpus, fingerprint)."""
    return JSONResponse({"ok": True, **cc.reset(dtxsid)})
