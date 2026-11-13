"""
web_routes/chat_routes.py — HTTP transport for the per-session interpretation
chat (ADR-0022).

Routes:
  GET    /api/chat/{dtxsid}/threads                      list threads
  POST   /api/chat/{dtxsid}/threads                      create a thread
  GET    /api/chat/{dtxsid}/threads/{thread_id}          full transcript
  DELETE /api/chat/{dtxsid}/threads/{thread_id}          delete a thread
  POST   /api/chat/{dtxsid}/threads/{thread_id}/messages ask; streams SSE

The message route streams Server-Sent Events while the agent works —
`thinking`, `tool_call`, `tool_result` — then `complete` with the answer and
its grounding (references, unresolved citations, tool trace), or `error`.
The completed turn is persisted to the thread before `complete` is sent.

Thin by design: parse → narrative.chat_agent.run_turn → serialise. All
grounding, safety and persistence live in narrative/chat_tools,
narrative/chat_agent and pipeline/chat_store.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from common.dtxsid import validate_dtxsid
from common.paths import SESSIONS_DIR
from narrative.chat_agent import run_turn
from narrative.chat_tools import ChatToolbox, SourceRegistry
from pipeline import chat_store
from pipeline.chat_store import InvalidThreadId, validate_thread_id
from web_routes.dtxsid_param import Dtxsid

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_MESSAGE_CHARS = 4000


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _identity(dtxsid: str) -> dict:
    """The session's chemical identity (name/casrn) for the prompt and the
    report-data loader; empty when not yet confirmed."""
    p = SESSIONS_DIR / validate_dtxsid(dtxsid) / "identity.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        return {}


@router.get("/api/chat/{dtxsid}/threads")
async def api_chat_threads(dtxsid: Dtxsid):
    return JSONResponse({"threads": chat_store.list_threads(dtxsid)})


@router.post("/api/chat/{dtxsid}/threads")
async def api_chat_new_thread(dtxsid: Dtxsid, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    title = str((body or {}).get("title") or "") if isinstance(body, dict) else ""
    return JSONResponse(chat_store.new_thread(dtxsid, title))


@router.get("/api/chat/{dtxsid}/threads/{thread_id}")
async def api_chat_thread(dtxsid: Dtxsid, thread_id: str):
    try:
        thread = chat_store.load_thread(dtxsid, validate_thread_id(thread_id))
    except InvalidThreadId as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if thread is None:
        return JSONResponse({"error": "no such thread"}, status_code=404)
    return JSONResponse(thread)


@router.delete("/api/chat/{dtxsid}/threads/{thread_id}")
async def api_chat_delete_thread(dtxsid: Dtxsid, thread_id: str):
    try:
        ok = chat_store.delete_thread(dtxsid, validate_thread_id(thread_id))
    except InvalidThreadId as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not ok:
        return JSONResponse({"error": "no such thread"}, status_code=404)
    return JSONResponse({"ok": True})


@router.post("/api/chat/{dtxsid}/threads/{thread_id}/messages")
async def api_chat_message(dtxsid: Dtxsid, thread_id: str, request: Request):
    try:
        validate_thread_id(thread_id)
    except InvalidThreadId as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON body required"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON object body required"}, status_code=400)
    message = str(body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)
    if len(message) > MAX_MESSAGE_CHARS:
        return JSONResponse(
            {"error": f"message too long (max {MAX_MESSAGE_CHARS} characters)"},
            status_code=400,
        )
    model = str(body.get("model") or "") or None

    thread = chat_store.load_thread(dtxsid, thread_id)
    if thread is None:
        return JSONResponse({"error": "no such thread"}, status_code=404)

    identity = _identity(dtxsid)
    chemical_name = identity.get("name") or identity.get("preferredName") or "the test article"
    registry = SourceRegistry.from_json(thread.get("sources"))
    toolbox = ChatToolbox(
        dtxsid, registry,
        chemical_name=chemical_name, casrn=identity.get("casrn") or "",
    )

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: str, data: dict) -> None:
        # Progress events only; the final answer goes out as `complete` after
        # persistence so the client never sees an answer that was not saved.
        if event != "answer":
            await queue.put((event, data))

    async def work() -> None:
        try:
            result = await run_turn(
                history=thread.get("messages") or [],
                user_message=message,
                toolbox=toolbox,
                chemical_name=chemical_name,
                model=model,
                emit=emit,
            )
            chat_store.append_turn(thread, message, result, registry.to_json())
            chat_store.save_thread(dtxsid, thread)
            await queue.put(("complete", {**result, "thread_id": thread["id"]}))
        except Exception as e:
            logger.exception("chat turn failed for %s/%s", dtxsid, thread_id)
            await queue.put(("error", {"error": f"chat failed: {e}"}))
        finally:
            await queue.put((None, {}))

    async def stream():
        task = asyncio.create_task(work())
        try:
            while True:
                event, data = await queue.get()
                if event is None:
                    break
                yield _sse(event, data)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream")
