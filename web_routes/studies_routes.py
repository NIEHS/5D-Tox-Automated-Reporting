"""
web_routes/studies_routes.py — module M1 of the new interface: create, list,
open and delete a study (docs/ui-redesign/modules/m1/contract.md §2).

  GET  /api/v2/studies                            the list, grouped by chemical
  GET  /api/v2/studies/{id}                       one session, with its detail
  GET  /api/v2/studies/{dtxsid}/creation-check    is the id free; which format
  GET  /api/v2/chemicals/{dtxsid}                 the chemical a DTXSID names
  GET  /api/v2/chemicals/{dtxsid}/structure.png   its structure picture
  POST /api/v2/studies                            create, with a confirmed identity
  PUT  /api/v2/studies/{id}/identity              fill a missing identity
  GET  /api/v2/studies/{id}/delete-preview        the delete's dry run
  POST /api/v2/studies/{id}/delete                delete, with the typed id and token

Thin drivers over workflow.studies (the reads) and workflow.steps (the acts).
Every failure is the §4.2 envelope (the router's route class is the kit's
``V2Route``). The GETs have no side effects: no folder is created, nothing is
scanned or pinned.

``refuse_data_act`` is the one-line R6 check for the old upload routes: no
files are brought into a published book's content or a report over several
studies (the data steps refuse the same in the core).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from web_routes.v2_routes import V2Route, envelope_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", route_class=V2Route, tags=["v2", "studies"])


class FormatSeen(BaseModel):
    definition: str | None = None
    hash: str | None = None


class CreateStudy(BaseModel):
    dtxsid: str
    identity: dict | None = None
    confirmed: bool = False
    dtxsid_checked_by_person: bool = False
    format_seen: FormatSeen | None = None


class RecordIdentity(BaseModel):
    identity: dict | None = None
    confirmed: bool = False
    dtxsid_checked_by_person: bool = False


class DeleteStudy(BaseModel):
    confirm_id: str = ""
    preview_token: str = Field(default="")


@router.get("/studies")
def api_v2_studies():
    """Every session, grouped by chemical (workflow.studies.list_studies)."""
    import common.paths
    from workflow.studies import StudyRefusal, list_studies
    if not common.paths.SESSIONS_DIR.is_dir():
        raise StudyRefusal("list_failed", "the sessions folder is missing or not readable", 500)
    return JSONResponse(list_studies())


@router.get("/studies/{dtxsid}")
def api_v2_study(dtxsid: str):
    """One session: its row and its detail (workflow.studies.study_summary)."""
    from workflow.studies import study_summary
    return JSONResponse(study_summary(dtxsid))


@router.get("/studies/{dtxsid}/creation-check")
def api_v2_creation_check(dtxsid: str):
    """Whether a study can be created under the DTXSID, and its format."""
    from workflow.studies import creation_check
    return JSONResponse(creation_check(dtxsid))


@router.get("/chemicals/{dtxsid}")
def api_v2_chemical(dtxsid: str):
    """The chemical a DTXSID names (PubChem; a few seconds)."""
    from workflow.studies import lookup_chemical
    return JSONResponse(lookup_chemical(dtxsid))


@router.get("/chemicals/{dtxsid}/structure.png")
def api_v2_chemical_structure(dtxsid: str):
    """The compound's structure picture, or 404 ``structure_unavailable``."""
    from workflow.studies import chemical_structure
    return Response(chemical_structure(dtxsid), media_type="image/png",
                    headers={"Cache-Control": "max-age=600"})


@router.post("/studies", status_code=201)
def api_v2_create_study(body: CreateStudy):
    """Create a study with the identity and format a person confirmed."""
    from workflow.steps import create_study_step
    from workflow.studies import study_row
    create_study_step(body.dtxsid, body.identity,
                      body.format_seen.model_dump() if body.format_seen else None,
                      confirmed=body.confirmed,
                      dtxsid_checked_by_person=body.dtxsid_checked_by_person)
    return JSONResponse(study_row(body.dtxsid), status_code=201)


@router.put("/studies/{dtxsid}/identity")
def api_v2_record_identity(dtxsid: str, body: RecordIdentity):
    """Fill a session's missing chemical identity from a confirmed lookup."""
    from workflow.steps import record_identity_step
    from workflow.studies import study_row
    record_identity_step(dtxsid, body.identity, confirmed=body.confirmed,
                         dtxsid_checked_by_person=body.dtxsid_checked_by_person)
    return JSONResponse(study_row(dtxsid))


@router.get("/studies/{dtxsid}/delete-preview")
def api_v2_delete_preview(dtxsid: str):
    """What deleting the study would delete, keep and lose (the dry run)."""
    from workflow.steps import delete_study_dry_run
    return JSONResponse(delete_study_dry_run(dtxsid))


@router.post("/studies/{dtxsid}/delete")
def api_v2_delete_study(dtxsid: str, body: DeleteStudy):
    """Delete a study for good, with the typed id and the dry run's token."""
    from workflow.steps import delete_study_step
    return JSONResponse(delete_study_step(dtxsid, body.confirm_id, body.preview_token))


def refuse_data_act(dtxsid: str) -> JSONResponse | None:
    """The envelope refusing a data act on a published book's content or a
    report over several studies (workflow.studies.require_data_session, R6);
    None when the act may go on, or when no study is named."""
    if not dtxsid:
        return None
    from workflow.studies import StudyRefusal, require_data_session
    try:
        require_data_session(dtxsid)
    except StudyRefusal as exc:  # a malformed id keeps the route's own 400
        return envelope_response(exc)
    return None
