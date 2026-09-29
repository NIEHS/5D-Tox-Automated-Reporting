"""web_routes.bookshelf_routes — the Bookshelf facsimile pages.

A top-level PAGE surface (not `/api/`): the report served as a visually faithful
NCBI-Bookshelf reader-view facsimile, the way a real Bookshelf book has its own
standalone URL.

  GET /Bookshelf/<dtxsid>  → that session's report rendered through the `bookshelf`
                             preview surface (rendering.bookshelf_preview), as a
                             self-contained HTML page.
  GET /Bookshelf           → the shelf: the sessions on disk, each linked to its
                             facsimile.

The facsimile is rendered FRESH per request via preview_surface.render_preview
(no archive/persist side effect), so it always reflects the current report.  Only
`/api/` paths are gated by the user-gate / provenance middleware, so these page
routes are served openly, exactly like `/` and `/workflow`.
"""

from __future__ import annotations

import html as _html
import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from common.paths import SESSIONS_DIR
from rendering.latex_export import _load_json
from rendering.preview_surface import render_preview
from web_routes.dtxsid_param import Dtxsid

logger = logging.getLogger(__name__)

router = APIRouter()


def _session_title(dtxsid: str) -> str:
    """A display title for a session's shelf card: the chemical name from
    identity.json / meta.json when present, else the dtxsid itself."""
    sess = SESSIONS_DIR / dtxsid
    for name in ("identity.json", "meta.json"):
        data = _load_json(sess / name)
        if isinstance(data, dict):
            chem = (data.get("name") or "").strip()
            if chem:
                return chem
    return dtxsid


@router.get("/Bookshelf/{dtxsid}", response_class=HTMLResponse)
async def bookshelf_facsimile(dtxsid: Dtxsid):
    """Render one session's report as a Bookshelf reader-view facsimile page."""
    sess = SESSIONS_DIR / dtxsid
    if not sess.exists():
        return HTMLResponse(_not_found_page(dtxsid), status_code=404)
    try:
        page = render_preview(dtxsid, surface="bookshelf")
    except Exception:
        logger.exception("Bookshelf facsimile render failed for %s", dtxsid)
        return HTMLResponse(_error_page(dtxsid), status_code=500)
    assert isinstance(page, str)  # the bookshelf surface returns HTML text
    return HTMLResponse(page)


@router.get("/Bookshelf", response_class=HTMLResponse)
async def bookshelf_shelf():
    """The shelf: list the sessions on disk, each linked to its facsimile."""
    try:
        dtxsids = sorted(
            p.name for p in SESSIONS_DIR.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
    except OSError:
        dtxsids = []
    return HTMLResponse(_shelf_page(dtxsids))


# ---------------------------------------------------------------------------
# Small self-contained HTML for the shelf + the error/404 pages.  The facsimile
# itself is a full page from bookshelf_preview; these are only the wrappers.
# ---------------------------------------------------------------------------

_SHELF_CSS = """
:root{--ink:#1a1a1a;--muted:#5c6670;--rule:#d5dbe0;--link:#205493;--bg:#fff;--card:#f5f7f9;}
*{box-sizing:border-box;}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  color:var(--ink);background:var(--bg);line-height:1.5;}
.wrap{max-width:900px;margin:0 auto;padding:32px 20px 80px;}
h1{font-size:1.6rem;color:#12263a;margin:0 0 4px;}
.sub{color:var(--muted);font-size:.9rem;margin:0 0 26px;}
ul.shelf{list-style:none;margin:0;padding:0;display:grid;gap:12px;
  grid-template-columns:repeat(auto-fill,minmax(240px,1fr));}
li.book a{display:block;text-decoration:none;color:inherit;background:var(--card);
  border:1px solid var(--rule);border-left:5px solid var(--link);border-radius:5px;
  padding:14px 16px;height:100%;}
li.book a:hover{border-left-color:#12263a;background:#eef2f5;}
.book .title{font-weight:700;color:#12263a;}
.book .id{font-size:.78rem;color:var(--muted);margin-top:4px;font-family:ui-monospace,monospace;}
.empty{color:var(--muted);}
a.home{color:var(--link);text-decoration:none;font-size:.85rem;}
"""


def _shelf_page(dtxsids: list[str]) -> str:
    if dtxsids:
        cards = "".join(
            f'<li class="book"><a href="/Bookshelf/{_html.escape(d)}">'
            f'<div class="title">{_html.escape(_session_title(d))}</div>'
            f'<div class="id">{_html.escape(d)}</div></a></li>'
            for d in dtxsids
        )
        body = f'<ul class="shelf">{cards}</ul>'
    else:
        body = '<p class="empty">No sessions on disk yet.</p>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bookshelf</title><style>{_SHELF_CSS}</style></head>
<body><div class="wrap">
<h1>Bookshelf</h1>
<p class="sub">Reader-view facsimiles of each session's report — the way it will read on NCBI Bookshelf. <a class="home" href="/">← app home</a></p>
{body}
</div></body></html>"""


def _not_found_page(dtxsid: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not found — Bookshelf</title><style>{_SHELF_CSS}</style></head>
<body><div class="wrap"><h1>No such session</h1>
<p class="sub">No session <code>{_html.escape(dtxsid)}</code> exists on disk.
<a class="home" href="/Bookshelf">← back to the shelf</a></p></div></body></html>"""


def _error_page(dtxsid: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Render error — Bookshelf</title><style>{_SHELF_CSS}</style></head>
<body><div class="wrap"><h1>Could not render this report</h1>
<p class="sub">The facsimile for <code>{_html.escape(dtxsid)}</code> failed to render.
Check the server log. <a class="home" href="/Bookshelf">← back to the shelf</a></p></div></body></html>"""
