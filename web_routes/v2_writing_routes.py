"""
web_routes/v2_writing_routes.py — the Written sections page and its Citations
tab (the demo path, docs/ui-redesign/modules/demo/spec.md §4 S3 and S4).

  GET  /api/v2/studies/{id}/writing                    the written parts, each marked built from
                                                       the data or written by a model
  GET  /api/v2/studies/{id}/writing/{part}             one part: its text and what the model was given
  GET  /api/v2/studies/{id}/references                 the reference list, what cites each entry,
                                                       the citation check's result
  POST /api/v2/studies/{id}/writing/background         write the Background (a run's event stream)
  POST /api/v2/studies/{id}/writing/summary            have the model word the Summary (event stream)
  POST /api/v2/studies/{id}/writing/summary/runs/{run_id}/use
                                                       take a Summary run's text into the report

Thin drivers over ui_api.writing, ui_api.writing_references (the reads, free
of side effects) and ui_api.writing_acts (the acts). Every failure is the
§4.2 envelope. The two long acts answer NDJSON (MODULES.md §4.4): a refusal
known before the work starts is an ordinary error answer; after that the
stream ends with ``result`` or ``error``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from web_routes.v2_routes import V2Route

router = APIRouter(prefix="/api/v2", route_class=V2Route, tags=["v2", "writing"])


def _ndjson(events: Iterator[dict]) -> StreamingResponse:
    """A run's events, one JSON object per line."""
    def lines():
        for event in events:
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"
    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/studies/{dtxsid}/writing")
def api_v2_writing(dtxsid: str):
    """The written parts of a report or a study (ui_api.writing.writing_overview)."""
    from ui_api.writing import writing_overview
    return JSONResponse(writing_overview(dtxsid))


@router.get("/studies/{dtxsid}/writing/{part}")
def api_v2_writing_part(dtxsid: str, part: str):
    """One written part in full (ui_api.writing.writing_part)."""
    from ui_api.writing import writing_part
    return JSONResponse(writing_part(dtxsid, part))


@router.get("/studies/{dtxsid}/references")
def api_v2_references(dtxsid: str):
    """The reference list as printed (ui_api.writing_references.references)."""
    from ui_api.writing_references import references
    return JSONResponse(references(dtxsid))


@router.post("/studies/{dtxsid}/writing/background")
def api_v2_write_background(dtxsid: str):
    """Write the Background and save it as a draft; answers a run's events."""
    from ui_api.writing_acts import write_background
    return _ndjson(write_background(dtxsid))


@router.post("/studies/{dtxsid}/writing/summary")
def api_v2_run_summary(dtxsid: str):
    """Have the model word the Summary; the run is kept, the report's Summary
    is not changed. Answers a run's events."""
    from ui_api.writing_acts import run_summary
    return _ndjson(run_summary(dtxsid))


@router.post("/studies/{dtxsid}/writing/summary/runs/{run_id}/use")
def api_v2_use_summary_run(dtxsid: str, run_id: str):
    """Make a recorded Summary run's text the report's Summary section."""
    from ui_api.writing_acts import use_summary_run
    return JSONResponse(use_summary_run(dtxsid, run_id))
