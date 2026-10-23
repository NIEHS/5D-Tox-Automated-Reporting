"""
web_routes/v2_routes.py — the new interface's shared routes (MODULES.md §4).

  GET /api/v2/studies/{id}/state   one study's derived state (ui_api.read_model)
  GET /api/v2/vocabularies         the controlled vocabularies and id patterns
                                   (ui_api.vocabularies)

Every route here, and every route a module adds under /api/v2/ through
``V2Route``, answers a failure with the error envelope of MODULES.md §4.2
(ui_api.refusals: the safeguards' explanation, ``fix`` naming the module that
clears it): ``{"error": {code, status, message, say, fix, details}}``.
The routes are thin: parse, call the core, serialize. The routes of the old
front-ends keep their own error shapes.

The handlers are plain ``def``: FastAPI runs them in its thread pool, so a read
that parses a large dataset (the method mismatches read integrated.json once per
change) does not hold up the event loop.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from ui_api.refusals import explain

logger = logging.getLogger(__name__)


def envelope_response(exc: BaseException) -> JSONResponse:
    """The §4.2 envelope for an exception, as a response with its status."""
    body = explain(exc)
    if body["error"]["code"] == "unexpected":
        logger.error("Unexpected error under /api/v2/: %s", exc, exc_info=exc)
    return JSONResponse(body, status_code=body["error"]["status"])


class V2Route(APIRoute):
    """An APIRoute whose every failure, including the path checks FastAPI runs
    before the handler (a malformed study id, an unparsable request), is
    answered with the error envelope. Applied per router, so the old routes'
    error shapes are untouched."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def envelope_handler(request: Request):
            try:
                return await handler(request)
            except Exception as exc:  # noqa: BLE001 — every failure gets the envelope
                return envelope_response(exc)

        return envelope_handler


router = APIRouter(prefix="/api/v2", route_class=V2Route, tags=["v2"])


@router.get("/studies/{dtxsid}/state")
def api_v2_study_state(dtxsid: str):
    """One study's derived state (ui_api.read_model.study_state): phase,
    legal actions, identity, pins, sections, publish readiness, member studies.
    Free of side effects; a study that does not exist answers
    ``{"id": …, "exists": false}``. A malformed id is a 400 envelope
    (``invalid_study_id``)."""
    from ui_api.read_model import study_state
    return JSONResponse(study_state(dtxsid))


@router.get("/vocabularies")
def api_v2_vocabularies():
    """The controlled vocabularies (bmdx_pipe.VOCABULARIES, ADR-0019) with the
    dependent ones as mappings, and the identifier patterns a field checks."""
    from ui_api.vocabularies import vocabularies_payload
    return JSONResponse(vocabularies_payload())
