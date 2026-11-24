"""
web_routes/v2_files_routes.py — the new interface's "Study files" page
(module M2, docs/ui-redesign/modules/m2/).

  GET /api/v2/studies/{id}/files   the study's files, what each one is, what
                                   the file check found, and which acts are
                                   allowed now

A thin driver over ui_api.files.  The read changes nothing: it locates the
study's folder without creating it, re-scans nothing and writes nothing.

A published book's companion and a report over several studies are not
refused here.  Their data is not their own (R6), so the page answers with
``takes_files.allowed: false`` and the reason, and offers no act — a person
who opened the page needs to read why, and where the files belong instead.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from web_routes.v2_routes import V2Route

router = APIRouter(prefix="/api/v2", route_class=V2Route, tags=["v2"])


@router.get("/studies/{dtxsid}/files")
def api_v2_files(dtxsid: str):
    """Everything the Study files page shows (ui_api.files.files_view): one row
    per file a person brought in with what it is taken to be, the file check's
    state and its findings in plain words, what the report would be built from,
    and each act with the reason when it is not allowed."""
    from ui_api.files import files_view
    return JSONResponse(files_view(dtxsid))
