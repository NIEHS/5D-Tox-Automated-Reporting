"""
web_routes/v2_section_routes.py — a section's approval and history, for the new
interface (C2: "owned content is never overwritten by a machine").

  POST /api/v2/studies/{id}/sections/{key}/accept             {}
  POST /api/v2/studies/{id}/sections/{key}/release            {reason}
  POST /api/v2/studies/{id}/sections/{key}/restore            {version, reason}
  GET  /api/v2/studies/{id}/sections/{key}/history
  GET  /api/v2/studies/{id}/sections/{key}/history/{version}

Thin drivers over workflow.steps (accept_section_step, release_section_step,
restore_section_step) and workflow.section_writes (section_history,
read_version). Every failure answers with the MODULES.md §4.2 envelope (the
``V2Route`` of web_routes.v2_routes); a success that did nothing carries
``noop {code, say}``. After a mutating call the interface re-reads the study's
state (GET /api/v2/studies/{id}/state).

Discarding a section is not offered here (C2 D4): regenerate and restore cover
it; the step stays behind the old route and the pool reset.

A study that does not exist has no sections: its routes answer
``section_not_found`` and create nothing on disk.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from web_routes.dtxsid_param import Dtxsid
from web_routes.v2_routes import V2Route

router = APIRouter(prefix="/api/v2", route_class=V2Route, tags=["v2", "sections"])


class ReleaseBody(BaseModel):
    reason: str | None = None


class RestoreBody(BaseModel):
    version: int | None = None
    reason: str | None = None


def _store(dtxsid: str, key: str, verb: str):
    """The store for an existing study; ``section_not_found`` for a study
    that does not exist (nothing is created for it)."""
    from pipeline.session_store import session_path
    from workflow import section_writes as sw
    from workflow.store import DiskPoolStore

    sw.validate_section_key(dtxsid, key)
    if not session_path(dtxsid).is_dir():
        raise sw.not_found(key, verb)
    return DiskPoolStore()


def _reply(result: dict, fields: tuple[str, ...]) -> JSONResponse:
    body = {k: result.get(k) for k in fields}
    if result.get("noop"):
        body["noop"] = result["noop"]
    return JSONResponse(body)


@router.post("/studies/{dtxsid}/sections/{key}/accept")
def api_v2_section_accept(dtxsid: Dtxsid, key: str):
    """Accept (approve) the section as it is. Its text is never changed."""
    from workflow.steps import accept_section_step
    result = accept_section_step(dtxsid, key, _store(dtxsid, key, "approve"))
    return _reply(result, ("section_key", "approved", "version", "version_status"))


@router.post("/studies/{dtxsid}/sections/{key}/release")
def api_v2_section_release(dtxsid: Dtxsid, key: str, body: ReleaseBody | None = None):
    """Reopen an approved section, with a reason (kept in its history). It
    stays protected: Process still never replaces it."""
    from workflow.steps import release_section_step
    reason = (body.reason if body else None) or ""
    result = release_section_step(dtxsid, key, _store(dtxsid, key, "reopen"), reason=reason)
    return _reply(result, ("section_key", "approved", "version", "version_status"))


@router.post("/studies/{dtxsid}/sections/{key}/restore")
def api_v2_section_restore(dtxsid: Dtxsid, key: str, body: RestoreBody | None = None):
    """Bring a past version back as the current one: a new version, not
    approved, kept from the machine (accepting it is a separate act)."""
    from workflow.steps import restore_section_step
    body = body or RestoreBody()
    result = restore_section_step(dtxsid, key, body.version, _store(dtxsid, key, "restore"),
                                  reason=body.reason or "")
    return _reply(result, ("section_key", "version", "from_version", "approved",
                           "version_status"))


@router.get("/studies/{dtxsid}/sections/{key}/history")
def api_v2_section_history(dtxsid: Dtxsid, key: str):
    """The section's versions and its version events (the changelog's lines),
    also after a discard."""
    from workflow import section_writes as sw
    from workflow.read_model import ReadOnlyDiskPoolStore
    _store(dtxsid, key, "show")
    return JSONResponse(sw.section_history(dtxsid, key, ReadOnlyDiskPoolStore()))


@router.get("/studies/{dtxsid}/sections/{key}/history/{version}")
def api_v2_section_version(dtxsid: Dtxsid, key: str, version: str):
    """One version's section JSON (the current file, or its archive). A
    version that is not a whole number is a version that does not exist."""
    from workflow import section_writes as sw
    from workflow.read_model import ReadOnlyDiskPoolStore
    _store(dtxsid, key, "show")
    number = int(version) if version.isdigit() else version
    return JSONResponse(sw.read_version(dtxsid, key, number, ReadOnlyDiskPoolStore()))
