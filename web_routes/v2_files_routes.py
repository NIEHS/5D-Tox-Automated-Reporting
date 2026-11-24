"""
web_routes/v2_files_routes.py — the new interface's "Study files" page
(module M2, docs/ui-redesign/modules/m2/).

  GET  /api/v2/studies/{id}/files   the study's files, what each one is, what
                                    the file check found, and which acts are
                                    allowed now
  POST /api/v2/studies/{id}/files   bring a batch of files in (multipart)
  POST /api/v2/studies/{id}/check   check the study's files (a stream of events)

A thin driver over ui_api.files (the read) and ui_api.files_acts (the acts).
The read changes nothing: it locates the study's folder without creating it,
re-scans nothing and writes nothing.

A published book's companion and a report over several studies are not
refused here.  Their data is not their own (R6), so the page answers with
``takes_files.allowed: false`` and the reason, and offers no act — a person
who opened the page needs to read why, and where the files belong instead.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from web_routes.v2_routes import V2Route

router = APIRouter(prefix="/api/v2", route_class=V2Route, tags=["v2"])

NDJSON = "application/x-ndjson"


@router.get("/studies/{dtxsid}/files")
def api_v2_files(dtxsid: str):
    """Everything the Study files page shows (ui_api.files.files_view): one row
    per file a person brought in with what it is taken to be, the file check's
    state and its findings in plain words, what the report would be built from,
    and each act with the reason when it is not allowed."""
    from ui_api.files import files_view
    return JSONResponse(files_view(dtxsid))


@router.post("/studies/{dtxsid}/files")
def api_v2_bring_in_files(dtxsid: str,
                          files: list[UploadFile] = File(default_factory=list),
                          answers: str | None = Form(default=None),
                          files_token: str | None = Form(default=None),
                          dry_run: bool = Form(default=False)):
    """Bring a batch of files into the study (ui_api.files_acts.bring_in).

    The batch is one act: every file is planned against the study as it stands,
    and while any of them waits on a person's answer nothing is written and the
    plan comes back (``answer_required``) with what each file would do.
    ``dry_run`` plans and carries nothing out.  ``answers`` is a JSON object of
    ``replace`` / ``copy_anyway`` / ``without_units`` to the names answered for;
    ``files_token`` is the study's files as the page last read them."""
    from ui_api.files_acts import answers_from, bring_in
    uploads = [(f.filename or "unnamed", f.file) for f in files]
    return JSONResponse(bring_in(dtxsid, uploads, answers=answers_from(answers),
                                 files_token=files_token, dry_run=dry_run))


@router.post("/studies/{dtxsid}/check")
def api_v2_check_files(dtxsid: str):
    """Check the study's files against each other and against its workbook
    (ui_api.files_acts.start_check); a stream of events, since a large
    BMDExpress project takes about half a minute the first time it is read."""
    from ui_api.files_acts import start_check
    return StreamingResponse(start_check(dtxsid), media_type=NDJSON)
