"""
web_routes/demo_routes.py — a finished report and its live copy (ui_api.demo).

  POST /api/v2/demo/{report}/reset    put the report's live copy back to its start state

The copy is made and removed from the command line (tooling.demo_copy); the
reset is here because a running server holds part of a session in memory, and
because whoever is presenting should not need a terminal for it.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from web_routes.v2_routes import V2Route

router = APIRouter(prefix="/api/v2", route_class=V2Route)


@router.post("/demo/{report}/reset")
def api_v2_demo_reset(report: str):
    """Delete the live copy of ``report`` and build it again from the finished
    report: files checked, facts stated, nothing combined or computed. Refused
    while a long act runs on the copy, and when the report has no live copy."""
    from ui_api.demo import reset_live_copy
    return JSONResponse(reset_live_copy(report))
