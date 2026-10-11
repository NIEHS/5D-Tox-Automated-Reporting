"""
web_routes/prompt_routes.py — HTTP transport for the prompt workshop: a
model-written section's prompt template, its versions, the runs it produced,
and the chat that improves it.

Routes (`{section}` is a registered template section — "summary" for now):
  GET  /api/prompts/{section}                         current template + versions + variables
  GET  /api/prompts/{section}/versions/{n}            one version's text
  POST /api/prompts/{section}                         save a new version {template, rationale, thread_id}
  POST /api/prompts/{section}/current                 make a version current {version, rationale}
  POST /api/prompts/{section}/render                  {dtxsid, template?} → the exact prompt, or the error
  POST /api/prompts/{section}/run                     {dtxsid, template? | version?} → a run record
  GET  /api/prompts/{section}/runs/{dtxsid}           the session's runs, newest first
  POST /api/prompts/{section}/runs/{dtxsid}/{run_id}/use   save that run's text as the section
  GET  /api/prompts/{section}/published/{dtxsid}      the published text, or 404
  GET  /api/prompts/{section}/threads                 workshop threads
  POST /api/prompts/{section}/threads                 new thread
  GET  /api/prompts/{section}/threads/{id}            one thread
  POST /api/prompts/{section}/threads/{id}/messages   {dtxsid, message, template, run_id?} → a turn

Thin by design: templates and rendering live in narrative.prompt_templates,
generation in narrative.summary_llm, the chat in narrative.prompt_workshop,
persistence in pipeline.prompt_store.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from common.dtxsid import validate_dtxsid
from narrative import prompt_templates, prompt_workshop, summary_llm
from narrative.prompt_templates import TemplateError, UnknownSection
from pipeline import prompt_store
from pipeline.prompt_store import InvalidThreadId, UnknownVersion
from web_routes.dtxsid_param import Dtxsid

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_MESSAGE_CHARS = 4000
MAX_TEMPLATE_CHARS = 40_000

# The generator for each templated section (one entry per SECTIONS entry).
_GENERATORS = {"summary": summary_llm}


def _err(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _section(section: str) -> str:
    prompt_templates.validate_section(section)
    return section


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _template_arg(body: dict) -> str | None:
    t = body.get("template")
    if t is None:
        return None
    t = str(t)
    if len(t) > MAX_TEMPLATE_CHARS:
        raise TemplateError(f"template too long (max {MAX_TEMPLATE_CHARS} characters)")
    return t


def _guard(fn):
    """Map the module's errors to HTTP statuses."""
    import functools

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except UnknownSection as e:
            return _err(str(e), 404)
        except UnknownVersion as e:
            return _err(str(e), 404)
        except InvalidThreadId as e:
            return _err(str(e), 400)
        except TemplateError as e:
            return _err(str(e), 422)
    return wrapper


@router.get("/api/prompts/{section}")
@_guard
async def api_prompt(section: str):
    _section(section)
    text, version = prompt_templates.template_text(section)
    return JSONResponse({
        "section": section,
        "label": prompt_templates.SECTIONS[section]["label"],
        "current_version": version,
        "template": text,
        "versions": prompt_store.versions(section),
        "variables": prompt_templates.SECTIONS[section]["variables"],
    })


@router.get("/api/prompts/{section}/versions/{version}")
@_guard
async def api_prompt_version(section: str, version: int):
    _section(section)
    text, v = prompt_templates.template_text(section, version)
    return JSONResponse({"version": v, "template": text})


@router.post("/api/prompts/{section}")
@_guard
async def api_prompt_save(section: str, request: Request):
    _section(section)
    body = await _body(request)
    text = _template_arg(body)
    if not text:
        return _err("template is required", 400)
    prompt_templates.parse(text)  # the front matter must be valid before it is kept
    dtxsid = body.get("dtxsid")
    if dtxsid:  # a render against the session the author is looking at
        _GENERATORS[section].render_for_session(validate_dtxsid(dtxsid), text)
    thread_id = body.get("thread_id")
    if thread_id:
        prompt_store.validate_thread_id(thread_id)
    n = prompt_store.save_version(section, text, rationale=str(body.get("rationale") or ""),
                                  thread_id=thread_id or None)
    return JSONResponse({"version": n, "versions": prompt_store.versions(section)})


@router.post("/api/prompts/{section}/current")
@_guard
async def api_prompt_current(section: str, request: Request):
    _section(section)
    body = await _body(request)
    try:
        version = int(body.get("version"))
    except (TypeError, ValueError):
        return _err("version is required", 400)
    prompt_store.make_current(section, version, rationale=str(body.get("rationale") or ""))
    return JSONResponse({"current_version": prompt_store.current_version(section)})


@router.post("/api/prompts/{section}/render")
@_guard
async def api_prompt_render(section: str, request: Request):
    _section(section)
    body = await _body(request)
    dtxsid = validate_dtxsid(str(body.get("dtxsid") or ""))
    try:
        rendered, _ = _GENERATORS[section].render_for_session(dtxsid, _template_arg(body))
    except TemplateError as e:  # an editor state, not a failed request
        return JSONResponse({"ok": False, "error": str(e)})
    return JSONResponse({"ok": True, "prompt": rendered.to_dict()})


@router.post("/api/prompts/{section}/run")
@_guard
async def api_prompt_run(section: str, request: Request):
    _section(section)
    body = await _body(request)
    dtxsid = validate_dtxsid(str(body.get("dtxsid") or ""))
    text = _template_arg(body)
    version = body.get("version")
    try:
        record = await _GENERATORS[section].generate(
            dtxsid, text=text, version=int(version) if version is not None else None)
    except (TemplateError, UnknownVersion):
        raise
    except Exception as e:
        logger.exception("prompt run failed for %s/%s", section, dtxsid)
        return _err(f"generation failed: {e}", 502)
    return JSONResponse(record)


@router.get("/api/prompts/{section}/runs/{dtxsid}")
@_guard
async def api_prompt_runs(section: str, dtxsid: Dtxsid):
    _section(section)
    return JSONResponse({"runs": prompt_store.list_runs(dtxsid, section)})


@router.post("/api/prompts/{section}/runs/{dtxsid}/{run_id}/use")
@_guard
async def api_prompt_use_run(section: str, dtxsid: Dtxsid, run_id: str):
    """Save a run's text as the section — a new, unapproved version of it."""
    from pipeline.session_store import save_section
    _section(section)
    run = prompt_store.load_run(dtxsid, section, run_id)
    if run is None:
        return _err("no such run", 404)
    save_section(dtxsid, section, {
        "paragraphs": run.get("paragraphs") or [],
        "source": "model",
        "approved": False,
        "run_id": run["run_id"],
        "template_version": run.get("template_version"),
        "model_used": (run.get("prompt") or {}).get("model", ""),
    })
    return JSONResponse({"ok": True})


@router.get("/api/prompts/{section}/published/{dtxsid}")
@_guard
async def api_prompt_published(section: str, dtxsid: Dtxsid):
    _section(section)
    published = prompt_workshop.published_section(dtxsid, section)
    if published is None:
        return _err("no published text for this study", 404)
    return JSONResponse(published)


@router.get("/api/prompts/{section}/threads")
@_guard
async def api_prompt_threads(section: str):
    _section(section)
    return JSONResponse({"threads": prompt_store.list_threads(section)})


@router.post("/api/prompts/{section}/threads")
@_guard
async def api_prompt_new_thread(section: str):
    _section(section)
    return JSONResponse(prompt_store.new_thread(section))


@router.get("/api/prompts/{section}/threads/{thread_id}")
@_guard
async def api_prompt_thread(section: str, thread_id: str):
    _section(section)
    thread = prompt_store.load_thread(section, thread_id)
    if thread is None:
        return _err("no such thread", 404)
    return JSONResponse(thread)


@router.post("/api/prompts/{section}/threads/{thread_id}/messages")
@_guard
async def api_prompt_message(section: str, thread_id: str, request: Request):
    _section(section)
    thread = prompt_store.load_thread(section, thread_id)
    if thread is None:
        return _err("no such thread", 404)
    body = await _body(request)
    dtxsid = validate_dtxsid(str(body.get("dtxsid") or ""))
    message = str(body.get("message") or "").strip()
    if not message:
        return _err("message is required", 400)
    if len(message) > MAX_MESSAGE_CHARS:
        return _err(f"message too long (max {MAX_MESSAGE_CHARS} characters)", 400)
    template = _template_arg(body)
    if template is None:
        template, _ = prompt_templates.template_text(section)

    runs = prompt_store.list_runs(dtxsid, section, limit=50)
    run_id = body.get("run_id")
    run = next((r for r in runs if r.get("run_id") == run_id), runs[0] if runs else None)
    previous = None
    if run:
        later = [r for r in runs if r.get("run_id", "") < run["run_id"]]
        previous = later[0] if later else None

    generator = _GENERATORS[section]
    variables = generator.session_variables(dtxsid)
    try:
        result = await prompt_workshop.workshop_turn(
            section, message=message, template=template, variables=variables,
            run=run, previous_run=previous,
            published=prompt_workshop.published_section(dtxsid, section),
            history=thread.get("messages") or [],
        )
    except Exception as e:
        logger.exception("workshop turn failed for %s/%s", section, thread_id)
        return _err(f"chat failed: {e}", 502)
    prompt_workshop.append_turn(thread, message=message, dtxsid=dtxsid,
                                run_id=run["run_id"] if run else None,
                                template_version=(run or {}).get("template_version"),
                                result=result)
    prompt_store.save_thread(section, thread)
    return JSONResponse({**result, "thread": thread})
