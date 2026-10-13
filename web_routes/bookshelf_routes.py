"""web_routes.bookshelf_routes — the Bookshelf facsimile pages.

A top-level PAGE surface (not `/api/`): the report served as a visually faithful
NCBI-Bookshelf reader-view facsimile, the way a real Bookshelf book has its own
standalone URL.

  GET /Bookshelf/<dtxsid>  → that session's report rendered through the `bookshelf`
                             preview surface (rendering.bookshelf_preview), as a
                             self-contained HTML page.
  GET /Bookshelf           → the shelf: each generated report, linked to its
                             facsimile — the published ones in the order they
                             were published, labelled with the date, then the
                             unpublished ones.

The facsimile is rendered FRESH per request via preview_surface.render_preview
(no archive/persist side effect), so it always reflects the current report.  Only
`/api/` paths are gated by the user-gate / provenance middleware, so these page
routes are served openly, exactly like `/` and `/workflow`.
"""

from __future__ import annotations

import html as _html
import logging
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, Response

import common.paths
from rendering.latex_export import _load_json
from rendering.preview_surface import render_preview
from web_routes.dtxsid_param import Dtxsid

logger = logging.getLogger(__name__)

router = APIRouter()

# How long a docx→pdf (LibreOffice) conversion may run before we give up.
_PDF_TIMEOUT_S = 180


def _download_links(dtxsid: str) -> list[dict]:
    """The right-rail download links for a session's facsimile — the PDF and DOCX
    previews, each an on-demand GET route below — and, for a published study,
    its comparison with the published book (web_routes.compare_routes)."""
    from web_routes.compare_routes import published_report

    links = [
        {"label": "PDF (preview)", "href": f"/Bookshelf/{dtxsid}/report.pdf"},
        {"label": "Word (.docx)", "href": f"/Bookshelf/{dtxsid}/report.docx"},
    ]
    report = published_report(dtxsid)
    if report:
        links.append({"label": f"Compare with {report}", "href": f"/Compare/{dtxsid}"})
    return links


def _sessions_root() -> Path:
    # Read at call time, so a redirected SESSIONS_DIR (tests) is honoured.
    return common.paths.SESSIONS_DIR


def _holds_report(dtxsid: str) -> bool:
    """Whether the session's own data was integrated and processed
    (integrated.json plus a processed-sections cache)."""
    sess = _sessions_root() / dtxsid
    return (sess / "integrated.json").is_file() and any(sess.glob("_cache_sections_*.json"))


def _members(dtxsid: str) -> dict[str, str]:
    """{study key: member session} of a report over several studies
    (studies.json, rendering.report_compose); {} for a single study."""
    data = _load_json(_sessions_root() / dtxsid / "studies.json")
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def has_generated_report(dtxsid: str) -> bool:
    """Whether the session holds a generated report: it was integrated and
    processed, or it is a report over several studies each of which was.  An
    empty, abandoned or test-made session directory is not a report, so it is
    neither shelved nor served."""
    if _holds_report(dtxsid):
        return True
    members = _members(dtxsid)
    return bool(members) and all(_holds_report(m) for m in members.values())


def generated_reports() -> list[str]:
    """The sessions on disk whose own data makes a generated report, sorted
    (a report over several studies is composed from these; shelf_books)."""
    try:
        return sorted(p.name for p in _sessions_root().iterdir()
                      if p.is_dir() and not p.name.startswith(".")
                      and _holds_report(p.name))
    except OSError:
        return []


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _date_label(published: str | None) -> str:
    """"2023-03" as Bookshelf prints a publication date, "2023 Mar"."""
    if not published:
        return "date not recorded"
    year, _, month = published.partition("-")
    return f"{year} {_MONTHS[int(month) - 1]}" if month.isdigit() and 1 <= int(month) <= 12 \
        else year


def _report_order(report: str) -> tuple:
    """"NIEHS-02" before "NIEHS-10": the series, then the number."""
    import re
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", report))


def shelf_books() -> tuple[list[dict], list[dict]]:
    """The shelf's books, (published, unpublished): each {dtxsid, title,
    report, published, studies}.  A report over several studies is one book,
    its member studies not shelved apart.  Published books are in the order
    they were published (the published book's date; reports of one date by
    their number), unpublished ones by title."""
    from narrative.prompt_workshop import published_date
    from pipeline.deposit import SPECIES_TITLES
    from web_routes.compare_routes import published_report

    try:
        composed = [p.name for p in _sessions_root().iterdir()
                    if p.is_dir() and _members(p.name) and has_generated_report(p.name)]
    except OSError:
        composed = []
    members = {m for c in composed for m in _members(c).values()}
    published, unpublished = [], []
    for d in sorted((set(generated_reports()) - members) | set(composed)):
        report = published_report(d)
        book = {"dtxsid": d, "title": _session_title(d), "report": report,
                "published": published_date(report),
                "studies": [SPECIES_TITLES.get(k, k.title()) for k in _members(d)]}
        (published if report else unpublished).append(book)
    published.sort(key=lambda b: (b["published"] is None, b["published"] or "",
                                  _report_order(b["report"])))
    unpublished.sort(key=lambda b: (b["title"].lower(), b["dtxsid"]))
    return published, unpublished


def _session_title(dtxsid: str) -> str:
    """A display title for a session's shelf card: the chemical name from
    identity.json / meta.json when present, else the dtxsid itself."""
    sess = _sessions_root() / dtxsid
    for name in ("identity.json", "meta.json"):
        data = _load_json(sess / name)
        if isinstance(data, dict):
            chem = (data.get("name") or "").strip()
            if chem:
                return chem
    return dtxsid


# Sync `def` handlers: rendering (generate_bits + skin) and docx→pdf conversion
# are blocking CPU/subprocess work; FastAPI runs sync handlers in a threadpool, so
# they don't stall the event loop.

@router.get("/Bookshelf/{dtxsid}", response_class=HTMLResponse)
def bookshelf_facsimile(dtxsid: Dtxsid):
    """Render one session's report as a Bookshelf reader-view facsimile page, with
    a right-rail Download panel (PDF + DOCX previews)."""
    if not has_generated_report(dtxsid):
        return HTMLResponse(_not_found_page(dtxsid), status_code=404)
    try:
        page = render_preview(dtxsid, surface="bookshelf", downloads=_download_links(dtxsid))
    except Exception:
        logger.exception("Bookshelf facsimile render failed for %s", dtxsid)
        return HTMLResponse(_error_page(dtxsid), status_code=500)
    assert isinstance(page, str)  # the bookshelf surface returns HTML text
    return HTMLResponse(page)


@router.get("/Bookshelf/{dtxsid}/report.docx")
def bookshelf_docx(dtxsid: Dtxsid):
    """Download the DOCX preview — the actual Word deliverable, rendered on demand
    (no prior materialize needed; not the gated final export)."""
    if not has_generated_report(dtxsid):
        return JSONResponse({"error": f"No generated report for {dtxsid}"}, status_code=404)
    try:
        docx = render_preview(dtxsid, surface="docx")
    except Exception:
        logger.exception("Bookshelf docx render failed for %s", dtxsid)
        return JSONResponse({"error": "Could not render the DOCX preview."}, status_code=500)
    assert isinstance(docx, bytes)
    return Response(
        docx,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{dtxsid}-report.docx"'},
    )


@router.get("/Bookshelf/{dtxsid}/report.pdf")
def bookshelf_pdf(dtxsid: Dtxsid):
    """Download the PDF preview — the DOCX deliverable converted to PDF on demand
    (LibreOffice/docx2pdf, offline).  503 if the conversion tool fails."""
    if not has_generated_report(dtxsid):
        return JSONResponse({"error": f"No generated report for {dtxsid}"}, status_code=404)
    try:
        docx = render_preview(dtxsid, surface="docx")
        assert isinstance(docx, bytes)
        pdf = _docx_to_pdf(docx)
    except Exception:
        logger.exception("Bookshelf pdf render failed for %s", dtxsid)
        return JSONResponse({"error": "Could not render the PDF preview."}, status_code=500)
    if pdf is None:
        return JSONResponse(
            {"error": "PDF conversion (docx2pdf) failed on the server. The DOCX "
                      "preview and the facsimile page are unaffected."},
            status_code=503,
        )
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{dtxsid}-report.pdf"'},
    )


@router.get("/Bookshelf", response_class=HTMLResponse)
def bookshelf_shelf():
    """The shelf: the generated reports on disk, each linked to its facsimile."""
    return HTMLResponse(_shelf_page(*shelf_books()))


def _docx_to_pdf(docx_bytes: bytes) -> bytes | None:
    """Convert DOCX bytes to PDF bytes with the offline `docx2pdf` (LibreOffice)
    CLI, in a scratch dir.  Returns None on any failure (missing tool, non-zero
    exit, no output) so the caller can 503 rather than 500.  A preview-fidelity
    render — the higher-fidelity docx path (OnlyOffice x2t) is host-only."""
    with tempfile.TemporaryDirectory(prefix="bookshelf_pdf_") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "report.docx"
        src.write_bytes(docx_bytes)
        try:
            subprocess.run(
                ["docx2pdf", str(src), str(tmp_path)],
                capture_output=True, text=True, timeout=_PDF_TIMEOUT_S, check=True,
            )
        except (subprocess.SubprocessError, OSError):
            logger.exception("docx2pdf conversion failed")
            return None
        pdf = tmp_path / "report.pdf"
        return pdf.read_bytes() if pdf.exists() else None


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
.book .when{font-size:.8rem;font-weight:600;color:var(--link);margin-bottom:4px;}
.book.unpublished a{border-left-color:#8a96a3;}
.book.unpublished .when{color:var(--muted);font-weight:400;}
h2.group{font-size:1.05rem;color:#12263a;margin:30px 0 4px;}
p.group{color:var(--muted);font-size:.85rem;margin:0 0 12px;}
.empty{color:var(--muted);}
a.home{color:var(--link);text-decoration:none;font-size:.85rem;}
"""


def _card(book: dict, when: str, cls: str = "book") -> str:
    d = book["dtxsid"]
    studies = f' · {", ".join(book["studies"])}' if book["studies"] else ""
    return (f'<li class="{cls}"><a href="/Bookshelf/{_html.escape(d)}">'
            f'<div class="when">{_html.escape(when)}</div>'
            f'<div class="title">{_html.escape(book["title"])}</div>'
            f'<div class="id">{_html.escape(d + studies)}</div></a></li>')


def _shelf_page(published: list[dict], unpublished: list[dict]) -> str:
    """The shelf: the published reports in the order they were published (left
    to right, top to bottom), each labelled with its date; the unpublished
    ones in a grid of their own below."""
    parts = []
    if published:
        cards = "".join(_card(b, f"{_date_label(b['published'])} · {b['report']}")
                        for b in published)
        parts.append('<h2 class="group">Published</h2><p class="group">In order of '
                     f'publication.</p><ul class="shelf">{cards}</ul>')
    if unpublished:
        cards = "".join(_card(b, "Unpublished", "book unpublished") for b in unpublished)
        parts.append('<h2 class="group">Unpublished</h2><p class="group">Not yet '
                     f'published, by title.</p><ul class="shelf">{cards}</ul>')
    body = "".join(parts) or '<p class="empty">No generated reports yet.</p>'
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
<body><div class="wrap"><h1>No report</h1>
<p class="sub">There is no generated report for <code>{_html.escape(dtxsid)}</code>.
<a class="home" href="/Bookshelf">← back to the shelf</a></p></div></body></html>"""


def _error_page(dtxsid: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Render error — Bookshelf</title><style>{_SHELF_CSS}</style></head>
<body><div class="wrap"><h1>Could not render this report</h1>
<p class="sub">The facsimile for <code>{_html.escape(dtxsid)}</code> failed to render.
Check the server log. <a class="home" href="/Bookshelf">← back to the shelf</a></p></div></body></html>"""
