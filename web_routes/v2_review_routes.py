"""
web_routes/v2_review_routes.py — the review page (the demo path,
docs/ui-redesign/modules/demo/spec.md §4 S5).

  GET /api/v2/studies/{id}/review   the report as the review page shows it: the book's
                                    address on the Bookshelf, the downloads, and the
                                    sections by owner with where each starts in the book

A thin driver over ui_api.review (a read, free of side effects). The page's
acts are the section acts of web_routes/v2_section_routes.py (approve, reopen,
the history); the book, the Word document and the PDF are the Bookshelf's own
routes (web_routes/bookshelf_routes.py). Every failure is the §4.2 envelope.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from web_routes.v2_routes import V2Route

router = APIRouter(prefix="/api/v2", route_class=V2Route, tags=["v2", "review"])


@router.get("/studies/{dtxsid}/review")
def api_v2_review(dtxsid: str):
    """The review of a report or a single study; asked of a study of a
    report, the review of that report (ui_api.review.review)."""
    from ui_api.review import review
    return JSONResponse(review(dtxsid))
