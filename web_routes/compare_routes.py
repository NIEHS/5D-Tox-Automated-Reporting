"""web_routes.compare_routes — a published report beside ours, as a page.

Like the Bookshelf facsimile, a top-level PAGE surface (not `/api/`):

  GET /Compare                       the published studies whose report is
                                     generated, each linked to its comparison
  GET /Compare/<dtxsid>              the published book and ours side by side
                                     (or unified, switched on the page) —
                                     rendering.bits_compare_page
  GET /Compare/<dtxsid>/diff         the conventional unified diff of their
                                     flat texts (text/x-diff)
  GET /Compare/<dtxsid>/published.txt, /generated.txt
                                     the flat texts the diff is taken over

Ours is rendered FRESH from the session (the `bits` surface, the bundle we
deliver), so the comparison follows the session, not the files last written to
output/.  A render takes seconds, so the latest comparison per study is kept
until any file directly in its session directory (or a member study's) changes.
The published book is the NCBI litarch bundle in assets/cebs/_bookshelf/<REPORT>
(tooling.report_compare writes the same pages for every report, offline).
"""

from __future__ import annotations

import html as _html
import json
import logging
import threading

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse

import common.paths
from web_routes.bookshelf_routes import _SHELF_CSS, _session_title, generated_reports
from web_routes.dtxsid_param import Dtxsid

logger = logging.getLogger(__name__)

router = APIRouter()

BOOKSHELF = common.paths.REPO_ROOT / "assets" / "cebs" / "_bookshelf"

_cache: dict[str, tuple[tuple, object]] = {}
_lock = threading.Lock()


def published_report(dtxsid: str) -> str | None:
    """The published report a session is the generated twin of ("NIEHS-10"),
    when its book is downloaded; None for an unpublished study, or one member
    study of a report over several (its book is the report's, not its own)."""
    from narrative.prompt_workshop import report_of
    report, study = report_of(dtxsid)
    if not report or study or not (BOOKSHELF / report / "TOC.nxml").is_file():
        return None
    return report


def _stamp(dtxsid: str) -> tuple:
    """What the comparison depends on: the times of the files directly in the
    session directory and in its member studies' (studies.json)."""
    root = common.paths.SESSIONS_DIR
    dirs = [root / dtxsid]
    try:
        members = json.loads((root / dtxsid / "studies.json").read_text())
        dirs += [root / m for m in (members or {}).values()]
    except (OSError, ValueError):
        pass
    out = []
    for d in dirs:
        try:
            out += sorted((p.name, p.stat().st_mtime_ns) for p in d.iterdir() if p.is_file())
        except OSError:
            continue
    return tuple(out)


def comparison(dtxsid: str, report: str):
    """The comparison of the published book with ours, rendered now or kept
    from an earlier request while the session is unchanged."""
    from rendering.bits_compare import compare, load_book
    from rendering.preview_surface import render_preview

    stamp = _stamp(dtxsid)
    with _lock:
        hit = _cache.get(dtxsid)
        if hit and hit[0] == stamp:
            return hit[1]
    pub_book, pub_images = load_book(BOOKSHELF / report)
    our_book, our_images = load_book(render_preview(dtxsid, surface="bits"))
    cmp = compare(pub_book, our_book, left_images=pub_images, right_images=our_images)
    with _lock:
        _cache[dtxsid] = (stamp, cmp)
    return cmp


def _report_sessions() -> list[str]:
    """Sessions that render a report: a study's own, or a report over several
    studies (studies.json names its members, which hold the data)."""
    root = common.paths.SESSIONS_DIR
    try:
        composed = [p.parent.name for p in root.glob("*/studies.json")]
    except OSError:
        composed = []
    return sorted(set(generated_reports()) | set(composed))


@router.get("/Compare", response_class=HTMLResponse)
def compare_index():
    rows = [(d, r) for d in _report_sessions() if (r := published_report(d))]
    rows.sort(key=lambda x: x[1])
    return HTMLResponse(_index_page(rows))


@router.get("/Compare/{dtxsid}", response_class=HTMLResponse)
def compare_page(dtxsid: Dtxsid):
    from rendering.bits_compare_page import render_page

    report = published_report(dtxsid)
    if report is None:
        return HTMLResponse(_message_page(
            "Nothing to compare",
            f"{dtxsid} is not the generated twin of a downloaded published report."), 404)
    try:
        cmp = comparison(dtxsid, report)
    except Exception:
        logger.exception("Comparison failed for %s", dtxsid)
        return HTMLResponse(_message_page(
            "Could not compare this report",
            f"The comparison for {dtxsid} failed. Check the server log."), 500)
    name = _session_title(dtxsid)
    page = render_page(
        cmp, title=f"{report} · {name} — published vs generated",
        left_label=f"Published — {report} (Bookshelf)", right_label=f"Generated — {dtxsid}",
        subtitle=f"{dtxsid} · ours rendered from the session",
        links=((".diff", f"/Compare/{dtxsid}/diff"),
               ("published.txt", f"/Compare/{dtxsid}/published.txt"),
               ("generated.txt", f"/Compare/{dtxsid}/generated.txt"),
               ("our facsimile", f"/Bookshelf/{dtxsid}"), ("all reports", "/Compare")))
    return HTMLResponse(page)


@router.get("/Compare/{dtxsid}/diff")
def compare_diff(dtxsid: Dtxsid):
    from rendering.bits_compare import unified_diff

    report = published_report(dtxsid)
    if report is None:
        return PlainTextResponse(f"{dtxsid}: no published report to compare with\n", 404)
    cmp = comparison(dtxsid, report)
    return PlainTextResponse(unified_diff(cmp, f"published/{report}", f"generated/{dtxsid}"),
                             media_type="text/x-diff; charset=utf-8")


@router.get("/Compare/{dtxsid}/{side}.txt")
def compare_flat_text(dtxsid: Dtxsid, side: str):
    from rendering.bits_compare import flat_lines

    report = published_report(dtxsid)
    if report is None or side not in ("published", "generated"):
        return PlainTextResponse("not found\n", 404)
    cmp = comparison(dtxsid, report)
    secs = cmp.left_order if side == "published" else cmp.right_order
    return PlainTextResponse("\n".join(flat_lines(secs)[0]) + "\n")


def _index_page(rows: list[tuple[str, str]]) -> str:
    if rows:
        items = "".join(
            f'<li class="book"><a href="/Compare/{_html.escape(d)}">'
            f'<div class="title">{_html.escape(r)} · {_html.escape(_session_title(d))}</div>'
            f'<div class="id">{_html.escape(d)}</div></a></li>' for d, r in rows)
        body = f'<ul class="shelf">{items}</ul>'
    else:
        body = '<p class="empty">No published study has a generated report yet.</p>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Published vs generated</title><style>{_SHELF_CSS}</style></head>
<body><div class="wrap">
<h1>Published vs generated</h1>
<p class="sub">Each published report beside the one generated from its data, section by section — side by side, unified, or as a .diff. <a class="home" href="/Bookshelf">Bookshelf</a> · <a class="home" href="/">app home</a></p>
{body}
</div></body></html>"""


def _message_page(title: str, text: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(title)}</title><style>{_SHELF_CSS}</style></head>
<body><div class="wrap"><h1>{_html.escape(title)}</h1>
<p class="sub">{_html.escape(text)} <a class="home" href="/Compare">← all comparisons</a></p></div></body></html>"""
