"""
web_routes/v2_data_routes.py — the new interface's "Combined data" and
"Process" pages (docs/ui-redesign/modules/demo/spec.md §4 S1, S2).

  GET  /api/v2/studies/{id}/dataset               the files, and the dataset combined from them
  POST /api/v2/studies/{id}/integrate             combine the files, then account for the animals
  GET  /api/v2/studies/{id}/tables                the report's results tables
  GET  /api/v2/studies/{id}/tables/{key}/sources  one table followed back to its files
  POST /api/v2/studies/{id}/process               run the analysis, write its sections

Thin drivers over ui_api.dataset and ui_api.process_run.  The reads change
nothing.  The two acts answer as a stream of events, one JSON object per line
(MODULES.md §4.4): ``step`` lines while the act runs, then one ``result`` or
one ``error``.  A refusal before the act starts (the finished side of a demo
pair, the wrong phase, another act under way) is an ordinary error envelope
with its status, like every route of the kit's ``V2Route``.

A report over several studies has no data of its own: every route here
answers for a study, and refuses a report (``report_has_no_data``).
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from web_routes.v2_routes import V2Route

router = APIRouter(prefix="/api/v2", route_class=V2Route, tags=["v2"])

NDJSON = "application/x-ndjson"


@router.get("/studies/{dtxsid}/dataset")
def api_v2_dataset(dtxsid: str):
    """The study's files as the file check recorded them and, once they are
    combined, the dataset's experiments with the file each came from
    (ui_api.dataset.study_dataset)."""
    from ui_api.dataset import study_dataset
    return JSONResponse(study_dataset(dtxsid))


@router.post("/studies/{dtxsid}/integrate")
def api_v2_integrate(dtxsid: str):
    """Combine the study's files into one dataset, then account for every
    animal (ui_api.dataset.start_integrate); a stream of events."""
    from ui_api.dataset import start_integrate
    return StreamingResponse(start_integrate(dtxsid), media_type=NDJSON)


@router.get("/studies/{dtxsid}/tables")
def api_v2_tables(dtxsid: str):
    """The results tables of the study's report (ui_api.dataset.result_tables)."""
    from ui_api.dataset import result_tables
    return JSONResponse(result_tables(dtxsid))


@router.get("/studies/{dtxsid}/tables/{key}/sources")
def api_v2_table_sources(dtxsid: str, key: str):
    """One results table followed back: rows, experiments, files, workbooks,
    and where its benchmark doses come from (ui_api.dataset.table_sources)."""
    from ui_api.dataset import table_sources
    return JSONResponse(table_sources(dtxsid, key))


@router.post("/studies/{dtxsid}/process")
def api_v2_process(dtxsid: str):
    """Run the analysis on the study, then write its results sections and its
    Summary (ui_api.process_run.start_process); a stream of events."""
    from ui_api.process_run import start_process
    return StreamingResponse(start_process(dtxsid), media_type=NDJSON)
