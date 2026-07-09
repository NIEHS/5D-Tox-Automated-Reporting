"""
html_generator.py — HTML rendering of the NIEHS biological potency report.

This module is the sibling of latex_generator.py.  Both walk the same
DOCUMENT_TREE with the same data dict and dispatch on the same set of
node_type values; they differ only in the output format each handler
emits.  That gives the in-app preview iframe a 1:1 semantic match with
what Overleaf compiles from the .tex output — same tree, same data,
same dispatch, just different rendering strings.

Why we have this
----------------
The earlier preview path generated .tex via latex_generator and then
piped it through pandoc to produce HTML for the iframe.  That worked
but was lossy (pandoc doesn't understand our niehs.cls or the custom
niehstable env), required a subprocess per preview, and pulled in
pandoc as a runtime dependency.

This module renders the same DocNode tree directly to HTML — no .tex,
no pandoc, no subprocess.  The HTML side gets its own CSS in an inline
<style> block (the iframe srcdoc is sandboxed from the parent page's
style.css), so the preview is self-contained.

Architecture mirror
-------------------
The dispatch table, helper functions, and per-type render handlers
follow latex_generator.py's structure as closely as makes sense.  A
bug in apical-table rendering, for example, will manifest in both
outputs and gets fixed in both files — drift between the two is the
risk we accept for not having one renderer with pluggable backends.

Tracer scope
------------
v1 covers every node_type latex_generator handles:
  front-matter, narrative, heading-only, appendix, tables-list,
  narrative+tables, table, incidence-table, bmd-summary,
  genomics-section.

Cover and title-page emit a header block instead of being skipped (the
LaTeX path uses \\maketitle, the HTML path emits a styled title block).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import html as _html
from typing import Optional

from document_tree import (
    DOCUMENT_TREE,
    DocNode,
    find_node,
    first_body_node_id,
    walk_tree,
)
from render_capabilities import content_item_landscape_requested
from render_common import (
    front_matter_plan,
    has_paragraph_content,
    assert_dispatch_covers,
    walk_emit,
    incidence_table_plan,
    apical_table_plan,
    unified_narrative_paragraphs,
    bmd_summary_plan,
    BMD_SUMMARY_HEADERS,
    appendix_roster_rows,
    ANIMAL_ROSTER_HEADERS,
    methods_subsection_content,
    sample_counts_table,
    genomics_role,
    genomics_intro_paragraphs,
    genomics_entries,
    gene_set_table_rows,
    gene_table_rows,
    genomics_description_items,
    genomics_chart_caption,
    genomics_table_caption,
    GENE_SET_TABLE_HEADERS,
    GENE_TABLE_HEADERS,
    find_apical_section as _find_apical_section,
    table_caption as _table_caption,
)
from genomics_content import genomics_content_plan
from freeform_content import pending_note as _freeform_pending_note
from cover_layouts import get_cover_layout
from cross_references import resolve_xrefs_html
# Shared display-precision knob (same one the LaTeX path uses), so both
# surfaces round the raw BMD/BMDL/fold-change floats identically.
from table_builder_common import format_display_number, format_mean_se_display


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Map DocNode.level to the HTML heading tag.  Level 0 means "no heading"
# (cover/title-page, individual leaf table nodes); the dispatch skips
# heading emission for those.  Levels 1-3 map to h2/h3/h4 — we reserve
# h1 for the document title at the top of the page so the section
# headings nest correctly under it for accessibility / outline order.
_HEADING_TAG_BY_LEVEL: dict[int, str] = {
    1: "h2",
    2: "h3",
    3: "h4",
}


# Inline CSS for the iframe-embedded preview.  Kept minimal:
# article-style typography, tables with NIEHS-resembling rules
# (horizontal-only borders), and a visible "pending" placeholder style
# so authors can scan for unfinished sections.  Reuses CSS variable
# names that line up with web/style.css so a future shared stylesheet
# can replace this block without semantic changes.
_PREVIEW_CSS: str = """
body {
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI",
        "Helvetica Neue", Arial, sans-serif;
  color: #1a1a1a;
  /* Paged.js (loaded below) paints each page as a white .pagedjs_page
     sheet; the <body> becomes the gutter *behind* those sheets, so we
     colour it like a document viewer's canvas rather than simulating a
     single page here.  The old max-width / margin / padding simulation is
     gone on purpose — page size and inner margins are now owned by the
     @page rule in _PAGED_MEDIA_CSS. */
  background: #525659;
  margin: 0;
  padding: 0;
}
/* Inner title page (NIEHS Report 10 p2): centered, NO horizontal rule.
   Pushed down from the top of the sheet so the title sits in the upper-
   middle, like the reference. */
.title-block {
  text-align: center;
  padding-top: 1.4in;
}
.title-block .tp-title {
  font-size: 21px;
  font-weight: 700;
  line-height: 1.35;
  margin: 0 0 40px;
  color: #1a1a1a;
  /* Override the global heading look — this is a centered title block,
     not a section heading (no rule, no left alignment). */
  border: none;
  padding: 0;
  text-align: center;
}
.title-block .tp-report {
  font-size: 13px;
  line-height: 1.7;
  margin: 0 0 56px;
}
.title-block .tp-publisher {
  font-size: 13px;
  line-height: 1.7;
}
h2 { font-size: 19px; margin: 28px 0 10px; border-bottom: 1px solid #e2e0db; padding-bottom: 4px; }
h3 { font-size: 16px; margin: 22px 0 8px; color: #2c5282; }
h4 { font-size: 14px; margin: 16px 0 6px; color: #4a5568; font-weight: 600; }
p { margin: 0 0 10px; }
/* Invisible per-section scroll target for navigation-panel scrolling — see _walk_html. */
.sec-anchor { display: block; height: 0; margin: 0; padding: 0; }
em.pending {
  color: #b7791f;
  background: #fff7ed;
  padding: 1px 6px;
  border-radius: 3px;
  font-style: normal;
  font-size: 12.5px;
}
/* ADR-0005 round-trip overrides in the preview (divergence #2).  A region a
   human edited in Overleaf either shows the faithful edit (.override-edited)
   or, when no HTML rendering of the edit is stored yet, the regenerated
   content flagged as possibly stale (.override-stale).  Amber palette matches
   the .stale-badge convention elsewhere in the app. */
.override-stale {
  border-left: 3px solid #d97706;
  background: #fffbeb;
  padding: 2px 8px;
}
.override-stale::before {
  content: "Edited in Overleaf — preview may be stale";
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: #92400e;
  margin-bottom: 4px;
}
.override-edited {
  border-left: 3px solid #2563eb;
}
table.niehstable {
  border-collapse: collapse;
  margin: 12px 0 8px;
  font-size: 13px;
  width: 100%;
}
table.niehstable caption {
  caption-side: top;
  text-align: left;
  font-weight: 600;
  margin-bottom: 4px;
  color: #1a202c;
}
table.niehstable thead th {
  border-top: 1.5px solid #1a202c;
  border-bottom: 1px solid #1a202c;
  text-align: right;
  padding: 4px 8px;
  font-weight: 600;
}
table.niehstable thead th:first-child { text-align: left; }
table.niehstable tbody td {
  padding: 3px 8px;
  border: none;
  text-align: right;
}
table.niehstable tbody td:first-child { text-align: left; }
table.niehstable tbody tr.sex-separator td {
  border-top: 1px solid #d6d3cd;
  font-weight: 700;
  padding-top: 6px;
}
table.niehstable tbody tr.n-row td { color: #4a5568; }
table.niehstable tfoot,
table.niehstable .tablenotes {
  font-size: 12px;
  color: #4a5568;
  margin-top: 4px;
}
table.niehstable .tablenotes ol { margin: 4px 0 0; padding-left: 18px; }
table.niehstable tbody tr:last-child td { border-bottom: 1.5px solid #1a202c; }
.description-list dt {
  font-weight: 600;
  margin-top: 6px;
}
.description-list dd { margin: 0 0 4px 0; }
.appendix-stub, .placeholder-block {
  background: #fff7ed;
  border-left: 3px solid #f59e0b;
  padding: 8px 12px;
  margin: 8px 0;
  color: #92400e;
  font-size: 13px;
}
"""


# Paged.js is a CSS Paged Media polyfill.  Plain @page CSS only affects the
# browser's *print* path; it does nothing for on-screen rendering inside the
# preview iframe.  Paged.js reads the @page rules in _PAGED_MEDIA_CSS and
# chunks the otherwise-continuous report body into discrete .pagedjs_page
# sheets — discrete printed-page sheets on screen, the rendering counterpart
# to how Overleaf paginates the .tex export (our only two output surfaces are
# this HTML preview and the .tex; there is no PDF anywhere in our system).
#
# Pinned CDN, mirroring how the parent page loads Alpine / oboe / plotly.  It
# runs *inside* the sandboxed srcdoc iframe (which has no sandbox attribute
# and the app sets no CSP), auto-initialising on DOMContentLoaded.
#
# HTML-PREVIEW ONLY.  latex_generator.py must never gain this — the LaTeX
# path paginates at Overleaf compile time, not via a browser polyfill.
_PAGEDJS_POLYFILL_URL: str = (
    "https://unpkg.com/pagedjs@0.4.3/dist/paged.polyfill.js"
)

# The <script> element that pulls in the polyfill.  Emitted just before
# </body> in both skeletons so the DOM is fully parsed before Paged.js runs.
_PAGEDJS_SCRIPT: str = f'<script src="{_PAGEDJS_POLYFILL_URL}"></script>'

# Static paged-media CSS: page geometry, the page-number margin box, the
# white-sheet-on-grey-gutter chrome, and break-control rules that mirror
# LaTeX float / longtable behaviour.  The *dynamic* running-header text is
# appended separately by _running_header_css() because it varies per report.
#
# Cover-page rule rationale (kept here, NOT in the CSS string, so it doesn't
# ship to the browser on every preview): in the reference (NIEHS Report 10)
# the running header and the page numbering both begin at the Foreword
# (p3) — the cover (p1) and title (p2) pages carry neither.  So the title
# block is assigned its own named "cover" @page that blanks both margin
# boxes and forces a page break after itself; the header therefore starts
# on the first content page, not page 1.  (The reference also uses roman
# numerals for front matter and arabic for the body — that split is a
# separate, not-yet-done rendering item.)  Section names are deliberately
# kept OUT of the CSS comments below: those strings ship inside <style> and
# a bare "Foreword" there would trip the fragment-isolation test.
_PAGED_MEDIA_CSS: str = """
/* Page geometry — US Letter, 1in margins.  Matches niehs.cls
   (\\geometry{letterpaper, margin=1in}) so the preview's page breaks land
   roughly where Overleaf's will. */
@page {
  size: letter;
  margin: 1in;
  /* Front-matter page numbers are lower-roman (ii, iii, iv...), per NIEHS
     Report 10.  The body switches to arabic via @page mainmatter below.
     This default @page covers the front-matter sections; the cover page
     blanks it (@page cover), and a fragment preview overrides it back to
     arabic (fragments have no front-matter/body split). */
  @bottom-center {
    content: counter(page, lower-roman);
    font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    color: #4a5568;
  }
}
/* Cover page: no running header, no page number (rationale in the Python
   comment above — header + numbering begin on the first content page). */
@page cover {
  @top-center { content: none; }
  @bottom-center { content: none; }
}
/* Body pages: arabic numerals restarted at 1 (front matter is roman).  The
   .report-mainmatter wrapper around the body content (Background onward)
   assigns this named page, resets the page counter, and forces the body
   onto a fresh page — matching NIEHS Report 10, where Background is arabic
   page 1. */
@page mainmatter {
  @bottom-center {
    content: counter(page);
    font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    color: #4a5568;
  }
}
.report-mainmatter { page: mainmatter; counter-reset: page 1; break-before: page; }
/* Landscape pages — wide tables / charts / figures the user flipped to
   landscape (see _walk_html + the orientations map).  A .landscape-block is
   assigned this named landscape page and forced onto its own page(s);
   content after it returns to the default portrait page.  Keeps the
   preview's rotated pages in sync with pdflscape on the LaTeX side.  Arabic
   page number (landscape only happens in the body).

   ORIENTATION vs PAGINATION are separate axes (per the capability dictionary:
   orientable vs breakable).  The break-before/break-after here are NOT the
   "pagination" axis — they're intrinsic to rotation: a single physical page
   can't be half portrait and half landscape, so entering/leaving landscape
   forces a page boundary (exactly what pdflscape does on the LaTeX side).  A
   future per-node "breaks" overlay (the breakable capability) is the real
   pagination axis and stays independent of this. */
@page report-landscape {
  size: letter landscape;
  margin: 1in;
  @bottom-center {
    content: counter(page);
    font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    color: #4a5568;
  }
}
.landscape-block { page: report-landscape; break-before: page; break-after: page; }
/* Paged.js BUG WORKAROUND (the "page stays portrait" symptom): a named
   landscape @page only updates the inner page-box vars (--pagedjs-pagebox-*),
   NOT the visible SHEET, which Paged.js sizes from the root --pagedjs-width/
   --pagedjs-height (set once to 8.5x11 portrait).  Result without this rule:
   the 11in pagebox renders inside an 8.5in portrait sheet and overflows/clips,
   so the white page never looks rotated.  Paged.js tags every landscape page
   with the class pagedjs_<pagename>_page (here pagedjs_report-landscape_page);
   that element is an ancestor of .pagedjs_sheet, so re-pointing the sheet vars
   on it cascades down and makes the sheet itself render 11x8.5.  The -left/
   -right variants cover the page landing on either side of a print spread.
   Verified headlessly: landscape sheet measures 11.00x8.50in, portrait
   neighbours stay 8.50x11.00in. */
.pagedjs_report-landscape_page {
  --pagedjs-width: 11in;        --pagedjs-height: 8.5in;
  --pagedjs-width-left: 11in;   --pagedjs-height-left: 8.5in;
  --pagedjs-width-right: 11in;  --pagedjs-height-right: 8.5in;
}
/* White sheet floating on the grey gutter, with a soft drop shadow so it
   reads as a physical printed page in the preview. */
.pagedjs_page {
  background: #fff;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.35);
  margin: 14px auto;
}
/* Break control — keep tables, rows, and headings from splitting awkwardly,
   mirroring how LaTeX floats and longtable behave. */
table.niehstable thead { display: table-header-group; } /* repeat header when a table spans pages */
table.niehstable tr { break-inside: avoid; }            /* never split one row across a page */
table.niehstable caption { break-after: avoid; }        /* caption stays with its table */
h2, h3, h4 { break-after: avoid; }                      /* don't strand a heading at a page foot */
/* Title block → its own header-less "cover" page; content starts after it. */
.title-block { page: cover; break-inside: avoid; break-after: page; }
"""


# Fragment previews render a single section, so there is no front-matter/body
# split and no roman numbering — force the default page number back to arabic.
# Appended after _PAGED_MEDIA_CSS in the fragment skeleton so it wins over the
# roman default that _PAGED_MEDIA_CSS sets for the full document's front matter.
_FRAGMENT_ARABIC_PAGE_NUMBER: str = (
    "@page { @bottom-center { content: counter(page); } }"
)


# ---------------------------------------------------------------------------
# Helper functions (private)
# ---------------------------------------------------------------------------

def _esc(text) -> str:
    """
    HTML-escape a value, coercing None and non-strings to "".

    Used wherever we splice arbitrary strings (chemical names, narrative
    paragraphs, section titles, footnote bodies) into the HTML output.
    Without this, an ampersand or angle bracket from user prose would
    corrupt the document structure.
    """
    if text is None:
        return ""
    # Resolve semantic cross-references AFTER HTML escaping (ADR-0004
    # amendment c): [[xref:id]] tokens survive _html.escape (brackets are not
    # HTML-special), and the <a> we insert is therefore not re-escaped.
    return resolve_xrefs_html(_html.escape(str(text), quote=True))


def _heading(level: int, title: str) -> str:
    """
    Emit an HTML heading tag for the given level + title.

    Level 0 returns "" so callers can unconditionally splice the result.
    Title text is escaped before splicing.
    """
    if level <= 0:
        return ""
    tag = _HEADING_TAG_BY_LEVEL.get(level, "h5")
    return f"<{tag}>{_esc(title)}</{tag}>"


def _render_paragraphs(paragraphs: list) -> str:
    """
    Render a flat list of paragraph strings as a sequence of <p> blocks.

    Each paragraph is escaped individually.  Returns "" for empty input
    so callers can detect "no content" and substitute a placeholder.
    """
    if not paragraphs:
        return ""
    return "\n".join(f"<p>{_esc(p)}</p>" for p in paragraphs)


def _pending(label: str) -> str:
    """
    Emit the visible "pending" placeholder used for unimplemented or
    data-missing sections.  Mirrors the LaTeX \\emph{[Section pending: ...]}
    convention so the same scan-for-gaps workflow works in either view.
    """
    return f'<em class="pending">[{_esc(label)}]</em>'


# ---------------------------------------------------------------------------
# Table helpers (shared shape across all the table-rendering handlers)
# ---------------------------------------------------------------------------

def _emit_table_row(cells: list, *, td_class: str = "", tr_class: str = "") -> str:
    """
    Format a single <tr> from a list of cell strings.

    Cells are HTML-escaped.  Optional CSS classes go on the row and/or
    individual cells (used to mark sex-separator rows, n-rows, header
    rows differently in the rendered preview).
    """
    td_attr = f' class="{td_class}"' if td_class else ""
    tr_attr = f' class="{tr_class}"' if tr_class else ""
    tds = "".join(f"<td{td_attr}>{_esc(c)}</td>" for c in cells)
    return f"<tr{tr_attr}>{tds}</tr>"


def _emit_table_header(headers: list) -> str:
    """Emit the <thead> with one <th> per header cell (each escaped)."""
    ths = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    return f"<thead><tr>{ths}</tr></thead>"


def _emit_table_footnotes(footnotes: list) -> str:
    """
    Emit a footnote block beneath a table.

    footnotes is the typed list table_builder_common produces: each
    entry is a dict with kind ("lettered", "legend", "definition"),
    letter (for lettered records), and text.  Lettered entries render
    as <li> in an ordered list with the letter as the marker; other
    kinds render as a flat <p>.
    """
    if not footnotes:
        return ""
    items: list[str] = []
    for fn in footnotes:
        if not isinstance(fn, dict):
            continue
        text = fn.get("text") or fn.get("body") or ""
        if not text:
            continue
        if fn.get("kind") == "lettered" and fn.get("letter"):
            items.append(
                f'<li><span class="letter">{_esc(fn["letter"])}</span> {_esc(text)}</li>'
            )
        else:
            items.append(f"<li>{_esc(text)}</li>")
    if not items:
        return ""
    return (
        '<div class="tablenotes"><ol>'
        + "".join(items)
        + "</ol></div>"
    )


def _format_dose_label(dose, unit: str) -> str:
    """
    Format a dose value with its unit using a non-breaking space so the
    column header doesn't wrap mid-label.  Mirrors latex_generator's
    _format_dose_label byte-for-byte (modulo the LaTeX vs HTML escape).
    """
    if dose == 0 or dose == 0.0:
        return f"0 {unit}"
    if isinstance(dose, float) and dose.is_integer():
        return f"{int(dose)} {unit}"
    return f"{dose} {unit}"


# _table_caption / _find_apical_section now live in render_common (ADR-0006 #4)
# and are imported above under their old private names, so every handler that
# calls them is unchanged.


# ---------------------------------------------------------------------------
# Per-node-type render handlers
# ---------------------------------------------------------------------------
# Each handler takes (node, data) and returns the HTML for that node
# alone (not its children — the walker handles children separately).
# Returning "" means "this node contributes no output."
#
# Mirrors latex_generator.py's per-handler shape.  Adding a new
# node_type means: write a _render_<type> function here AND in
# latex_generator.py, and register it in both _DISPATCH tables.


def _render_front_matter(node: DocNode, data: dict) -> str:
    """
    Front matter section (foreword, about, peer review, publication
    details, acknowledgments, abstract).  Heading + paragraphs.

    ADR-0006: the content-source decision (labeled-sections vs paragraphs vs
    nothing) is the shared render_common.front_matter_plan EXTRACT; only the
    HTML markup below — and the format-dependent "empty body → pending"
    fallback — is EMIT and lives here.
    """
    plan = front_matter_plan(node, data)
    if plan.kind == "labeled":
        body = _render_labeled_sections(plan.labeled_parts)
    else:
        # "paragraphs" carries the flat list; "none" carries [] → "" → pending.
        body = _render_paragraphs(plan.paragraphs)
    if not body:
        body = _pending(f"Section pending: {node.title}")
    return f"{_heading(node.level, node.title)}\n{body}"


def _render_labeled_sections(parts: list[tuple[str, str]]) -> str:
    """
    EMIT normalised labeled-section parts as <p> blocks with a bold run-in
    label.  Input is the (label, text) list from render_common.front_matter_plan
    (already filtered to non-empty text); a "" label renders an unlabeled
    paragraph.
    """
    out: list[str] = []
    for label, text in parts:
        if label:
            out.append(f"<p><strong>{_esc(label)}.</strong> {_esc(text)}</p>")
        else:
            out.append(f"<p>{_esc(text)}</p>")
    return "".join(out)


def _render_narrative(node: DocNode, data: dict) -> str:
    """
    Plain narrative section.  M&M subsections route through the
    methods-specific lookup because their content lives in a flat
    sections list, not at data[data_key]["paragraphs"].
    """
    if node.methods_key:
        return _render_methods_subsection(node, data)
    return _render_front_matter(node, data)


def _render_methods_subsection(node: DocNode, data: dict) -> str:
    """
    M&M subsection — content lives in data["methods"]["sections"], matched
    to this node by the stable methods_key (see methods_subsection_content).
    Mirrors the LaTeX handler's lookup strategy.
    """
    # ADR-0006 Amendment 1: the key-match lookup and content-present
    # decision are shared; the markup is HTML emit.  A section with no real
    # paragraph text and no inline table is "pending" on both surfaces.
    paragraphs, inline = methods_subsection_content(node, data)
    body = _render_paragraphs(paragraphs) if has_paragraph_content(paragraphs) else ""
    if inline is not None:
        body = (body + "\n" + _render_inline_table(inline)).strip()
    if not body:
        body = _pending(f"Section pending: {node.title}")
    return f"{_heading(node.level, node.title)}\n{body}"


def _render_inline_table(table: dict) -> str:
    """Inline table inside an M&M subsection (e.g., Sample Counts)."""
    caption = table.get("caption", "")
    headers = table.get("headers", [])
    rows = table.get("rows", [])
    if not headers and not rows:
        return ""
    head = _emit_table_header([str(h) for h in headers]) if headers else ""
    body_rows = [_emit_table_row([str(c) for c in r]) for r in rows]
    notes = _emit_table_footnotes(table.get("footnotes", []))
    return (
        '<table class="niehstable">'
        f"<caption>{_esc(caption)}</caption>"
        f"{head}"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        f"{notes}"
    )


def _render_sample_counts_table(node: DocNode, data: dict) -> str:
    """
    Render the Methods "Final Sample Counts" matrix (Table 1) as an HTML table.

    Mirrors the LaTeX emitter: the built {caption, headers, rows, footnotes}
    matrix comes from the shared sample_counts_table EXTRACT; sex-header rows
    (first cell "**...**") render as a bold full-width separator, organ rows keep
    their label.  The "Table N." caption comes from the shared _table_caption
    (node.caption wins — authored in the YAML).
    """
    built = sample_counts_table(node, data)
    if built is None:
        caption = _table_caption(node, node.title or "")
        return (
            '<table class="niehstable">'
            f"<caption>{_esc(caption)}</caption></table>"
            f"{_pending(f'Table data pending: {node.title}')}"
        )

    headers = [str(h) for h in built.get("headers", [])]
    ncols = max(len(headers),
                max((len(r) for r in built.get("rows", [])), default=0))
    head = _emit_table_header(headers) if headers else ""

    body_rows: list[str] = []
    for row in built.get("rows", []):
        cells = [str(c) for c in row]
        first = cells[0] if cells else ""
        if first.startswith("**") and first.endswith("**"):
            label = first.strip("*").strip()
            body_rows.append(
                f'<tr class="sex-row"><td colspan="{ncols}"><strong>'
                f"{_esc(label)}</strong></td></tr>"
            )
        else:
            if cells:
                cells[0] = cells[0].strip()
            body_rows.append(_emit_table_row(cells))

    notes = _emit_table_footnotes(built.get("footnotes", []))
    caption = _table_caption(node, built.get("caption", ""))
    return (
        '<table class="niehstable">'
        f"<caption>{_esc(caption)}</caption>"
        f"{head}"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        f"{notes}"
    )


def _render_heading_only(node: DocNode, data: dict) -> str:
    """Structural heading; children rendered separately by the walker."""
    return _heading(node.level, node.title)


def _render_appendix(node: DocNode, data: dict) -> str:
    """
    Appendix node — Appendix B renders the animal roster; A/D/E/F carry authored
    freeform child nodes (heading only here, walker renders the child body);
    Appendix C (no roster, no children) still stubs out.

    ADR-0006 Amendment 1: the "which appendix carries the roster" decision and
    the roster rows are the shared appendix_roster_rows EXTRACT; only the HTML
    table markup (and the stub) are emit here.  The HTML roster scrolls — no
    pagination — unlike the LaTeX longtable.  The children guard mirrors the
    LaTeX renderer so both surfaces agree on when the stub shows.
    """
    heading = _heading(node.level, node.title)
    rows = appendix_roster_rows(node, data)
    if rows is not None:
        body_rows = "".join(_emit_table_row(r) for r in rows)
        roster = (
            '<table class="niehstable">'
            + "<caption><strong>Table B-1. Animal Numbers and FASTQ Data "
            + "File Names</strong></caption>"
            + _emit_table_header(list(ANIMAL_ROSTER_HEADERS))
            + f"<tbody>{body_rows}</tbody></table>"
        )
        return f"{heading}\n{roster}"
    if node.children:
        return heading
    body = f'<div class="appendix-stub">Appendix body pending: {_esc(node.title)}</div>'
    return f"{heading}\n{body}"


def _render_tables_list(node: DocNode, data: dict) -> str:
    """
    Tables list in the front matter.

    In the LaTeX path this becomes \\listoftables (auto-populated from
    the table floats).  In HTML we emit a manual list from
    data["table_entries"] when marshal_export_data has populated it;
    otherwise fall back to a stub message.
    """
    heading = _heading(node.level, node.title)
    entries = data.get("table_entries") or []
    if not entries:
        return f"{heading}\n{_pending('List of tables: pending.')}"
    items: list[str] = []
    for entry in entries:
        title = entry.get("title", "")
        n = entry.get("table_number")
        ready = entry.get("ready", False)
        line = f"Table {n}. {title}" if n is not None else title
        cls = "" if ready else 'class="pending-item"'
        items.append(f"<li {cls}>{_esc(line)}</li>")
    return f"{heading}\n<ol class=\"tables-list\">{''.join(items)}</ol>"


def _render_toc(node: DocNode, data: dict) -> str:
    """
    Table of Contents — a generated front-matter component (ADR-0003), distinct
    from the navigation panel.  Built from data["toc_entries"] (walked from the
    document tree by marshal_export_data) and indented by heading level.  In the
    LaTeX export this is native \\tableofcontents.

    The component self-heads (its own "Contents" heading), so the catalog marks
    `toc` headingless and we emit the heading explicitly here rather than via
    the generic _heading() machinery.
    """
    entries = data.get("toc_entries") or []
    heading = f'<h2 class="toc-heading">{_esc(node.title)}</h2>'
    if not entries:
        return f"{heading}\n{_pending('Table of contents: pending.')}"
    items: list[str] = []
    for entry in entries:
        lvl = entry.get("level", 1)
        ready = entry.get("ready", False)
        pad = (lvl - 1) * 16 if isinstance(lvl, int) and lvl > 1 else 0
        cls = "toc-entry" if ready else "toc-entry pending-item"
        items.append(
            f'<li class="{cls}" style="padding-left:{pad}px">{_esc(entry.get("title", ""))}</li>'
        )
    body = "".join(items)
    return f'{heading}\n<ol class="toc">{body}</ol>'


# ---------------------------------------------------------------------------
# Results-section handlers (narrative+tables, tables, bmd-summary,
# incidence-table, genomics-section)
# ---------------------------------------------------------------------------

def _render_apical_table(node: DocNode, data: dict) -> str:
    """
    Apical dose-response table.

    ADR-0006 #4: the section lookup, dose grid, and Male/Female cell rows are
    the shared render_common.apical_table_plan EXTRACT; this function only EMITs
    the HTML — the dose-column + BMD/BMDL headers (HTML uses the unicode ₁Std
    subscript and a plain space), the sex-separator rows, and the n-row CSS hook.
    """
    plan = apical_table_plan(node, data)
    if plan is None:
        return _emit_table_placeholder(node)

    headers = (
        [plan.first_col]
        + [_format_dose_label(d, plan.dose_unit) for d in plan.doses]
        + [f"BMD₁Std ({plan.dose_unit})", f"BMDL₁Std ({plan.dose_unit})"]
    )

    body_rows: list[str] = []
    for block in plan.sex_blocks:
        # Sex separator row spanning all columns.
        body_rows.append(
            f'<tr class="sex-separator"><td colspan="{plan.ncols}">'
            f"<strong>{_esc(block.sex_label)}</strong></td></tr>"
        )
        for row in block.rows:
            tr_class = "n-row" if row.is_n_row else ""
            body_rows.append(_emit_table_row(row.cells, tr_class=tr_class))

    head = _emit_table_header(headers)
    notes = _emit_table_footnotes(plan.footnotes)
    return (
        '<table class="niehstable">'
        f"<caption>{_esc(plan.caption)}</caption>"
        f"{head}"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        f"{notes}"
    )


def _emit_table_placeholder(node: DocNode) -> str:
    """Visible "[Table data pending: ...]" stub keeping the slot's caption."""
    caption = _table_caption(node, node.title or "")
    return (
        '<table class="niehstable"><caption>'
        f"{_esc(caption)}</caption><tbody><tr><td>"
        f'<em class="pending">[Table data pending: {_esc(node.title)}]</em>'
        "</td></tr></tbody></table>"
    )


def _render_narrative_tables(node: DocNode, data: dict) -> str:
    """
    H2 group under Results (Animal Condition, Clinical Pathology, etc.).
    Emits the heading + unified narrative paragraphs.  Child table nodes
    are walked separately by _walk_html.
    """
    # ADR-0006 Amendment 1: the narrative-paragraph selection AND the
    # content-present decision are shared; only the markup is HTML emit.
    paragraphs = unified_narrative_paragraphs(node, data)
    if has_paragraph_content(paragraphs):
        body = _render_paragraphs(paragraphs)
    else:
        body = _pending(f"Narrative pending: {node.title}")
    return f"{_heading(node.level, node.title)}\n{body}"


def _render_bmd_summary(node: DocNode, data: dict) -> str:
    """
    Apical Endpoint Benchmark Dose Summary table.

    ADR-0006 Amendment 1: prose, per-endpoint rows, and caption are the shared
    render_common.bmd_summary_plan EXTRACT; this only EMITs the HTML.
    """
    plan = bmd_summary_plan(node, data)
    heading = _heading(node.level, node.title)
    prose = _render_paragraphs(plan.paragraphs)

    if plan.rows is None:
        body = prose or _pending(f"BMD summary endpoints pending: {node.title}")
        return f"{heading}\n{body}"

    body_rows = "".join(_emit_table_row(cells) for cells in plan.rows)
    table = (
        '<table class="niehstable">'
        f"<caption>{_esc(plan.caption)}</caption>"
        f"{_emit_table_header(list(BMD_SUMMARY_HEADERS))}"
        f"<tbody>{body_rows}</tbody>"
        "</table>"
    )
    chunks = [c for c in (heading, prose, table) if c]
    return "\n".join(chunks)


def _render_incidence_table(node: DocNode, data: dict) -> str:
    """
    Clinical Observations incidence table — observation × dose group.

    ADR-0006 #4: the section lookup, row assembly, and caption are the shared
    render_common.incidence_table_plan EXTRACT; this function only EMITs the
    HTML (and formats the dose-column labels with the HTML _format_dose_label).
    """
    plan = incidence_table_plan(node, data)
    if plan is None:
        return _emit_table_placeholder(node)

    headers = ["Observation"] + [_format_dose_label(d, plan.dose_unit) for d in plan.doses]
    body_rows = "".join(_emit_table_row(cells) for cells in plan.rows)
    notes = _emit_table_footnotes(plan.footnotes)
    return (
        '<table class="niehstable">'
        f"<caption>{_esc(plan.caption)}</caption>"
        f"{_emit_table_header(headers)}"
        f"<tbody>{body_rows}</tbody>"
        "</table>"
        f"{notes}"
    )


def _render_genomics_section(node: DocNode, data: dict) -> str:
    """
    Gene Set or Gene BMD section — per-(organ, sex) subsections.

    ADR-0006 Amendment 1: role / intro / entries selection and the table rows
    are the shared EXTRACT; the <h4> markup, the per-item loop, the inline
    base64 chart figure, and the landscape wrap are HTML emit.
    """
    role = genomics_role(node)
    heading = _heading(node.level, node.title)
    intro = _render_paragraphs(genomics_intro_paragraphs(node, data))

    entries = genomics_entries(node, data)
    if not entries:
        body = intro or _pending(f"Genomics data pending: {node.title}")
        return f"{heading}\n{body}"

    blocks: list[str] = [heading]
    if intro:
        blocks.append(intro)

    for entry in entries:
        organ = (entry.get("organ") or "").capitalize()
        sex = (entry.get("sex") or "").capitalize()
        blocks.append(f"<h4>{_esc(f'{organ}, {sex}')}</h4>")
        # Ordered, sub-addressable content items (ADR-0003 Phase 4); the table
        # is independently orientable via the composite "(component, item)" key.
        for item in genomics_content_plan(entry, role):
            chunk = _render_genomics_item(entry, role, item)
            if not chunk:
                continue
            if item["orientable"] and content_item_landscape_requested(
                node.id, item["item_id"], data.get("orientations")
            ):
                chunk = f'<div class="landscape-block">{chunk}</div>'
            # ADR-0005 item-grain override: a single genomics narrative/table
            # can be edited + attributed on its own via the composite
            # "<node-id>::<item-id>" key (mirrors latex_generator).  Applied
            # here rather than in walk_post because the item grain only exists
            # inside this handler.
            item_key = f"{node.id}::{item['item_id']}"
            chunk = _apply_override_html(chunk, item_key, data)
            blocks.append(chunk)

    return "\n".join(b for b in blocks if b)


def _render_genomics_item(entry: dict, role: str, item: dict) -> str:
    """
    Render one content item of a genomics (organ, sex) block (see
    genomics_content.genomics_content_plan for the item shape).  Charts embed
    the cached PNG inline as a data URI — no separate file, unlike the LaTeX
    path which references figures/<filename>.
    """
    part = item.get("part")
    if part == "narrative":
        return _render_paragraphs(entry.get("narrative") or [])
    if part == "table":
        return (
            _render_gene_set_table(entry) if role == "gene_set"
            else _render_gene_table(entry)
        )
    if part == "chart":
        chart = next(
            (c for c in (entry.get("charts") or []) if c.get("key") == item.get("chart_key")),
            None,
        )
        if not chart:
            return ""
        png = chart.get("png_b64", "")
        src = png if png.startswith("data:") else f"data:image/png;base64,{png}"
        # ADR-0004 amendment (e) — visible figcaption gets the "Figure N."
        # prefix (shared genomics_chart_caption); the <img alt> stays the
        # descriptive caption alone, the accessibility/BITS <alt-text> role.
        descriptive = chart.get("caption", "")
        display = genomics_chart_caption(chart)
        return (
            f'<figure class="genomics-chart">'
            f'<img src="{src}" alt="{_esc(descriptive)}">'
            f"<figcaption>{_esc(display)}</figcaption></figure>"
        )
    if part == "descriptions":
        descriptions = (
            entry.get("go_descriptions") if role == "gene_set"
            else entry.get("gene_descriptions")
        ) or []
        return _render_description_list(descriptions)
    return ""


def _render_gene_set_table(entry: dict) -> str:
    """Top-gene-sets table for one (organ, sex). Rows from the shared EXTRACT."""
    rows = gene_set_table_rows(entry)
    if rows is None:
        return _pending(
            f"Top gene sets pending: {entry.get('organ', '')}, {entry.get('sex', '')}"
        )
    body_rows = "".join(_emit_table_row(r) for r in rows)
    caption = genomics_table_caption(entry)
    cap = f"<caption>{_esc(caption)}</caption>" if caption else ""
    return (
        '<table class="niehstable">'
        f"{cap}"
        f"{_emit_table_header(list(GENE_SET_TABLE_HEADERS))}"
        f"<tbody>{body_rows}</tbody>"
        "</table>"
    )


def _render_gene_table(entry: dict) -> str:
    """Top-genes table for one (organ, sex). Rows from the shared EXTRACT."""
    rows = gene_table_rows(entry)
    if rows is None:
        return _pending(
            f"Top genes pending: {entry.get('organ', '')}, {entry.get('sex', '')}"
        )
    body_rows = "".join(_emit_table_row(r) for r in rows)
    caption = genomics_table_caption(entry)
    cap = f"<caption>{_esc(caption)}</caption>" if caption else ""
    return (
        '<table class="niehstable">'
        f"{cap}"
        f"{_emit_table_header(list(GENE_TABLE_HEADERS))}"
        f"<tbody>{body_rows}</tbody>"
        "</table>"
    )


def _render_description_list(descriptions: list) -> str:
    """A <dl> of go-term or gene definitions for the genomics section."""
    items = [
        f"<dt>{_esc(label)}</dt><dd>{_esc(text)}</dd>"
        for label, text in genomics_description_items(descriptions)
    ]
    if not items:
        return ""
    return f'<dl class="description-list">{"".join(items)}</dl>'


def _render_cover(node: DocNode, data: dict) -> str:
    """
    Inner title page (NIEHS Report 10, page 2) — centered, no horizontal
    rule.  Replicates the approved Typst inner-title-page layout:

        NIEHS Report on the
        In Vivo Repeat Dose Biological Potency Study of
        <chemical> (CASRN <casrn>)
        in Sprague Dawley <strain> Rats
        (Gavage Studies)

        <report number>
        <report date>

        National Institute of Environmental Health Sciences
        Public Health Service
        U.S. Department of Health and Human Services
        ISSN: <issn>
        Research Triangle Park, North Carolina, USA

    The image-backed cover (page 1 of the reference) is a separate,
    deferred concern; for now this title page stands alone as the report's
    first page.  The title-page node stays suppressed (_render_title_page)
    — this one handler emits the front page.
    """
    report_number = data.get("report_number", "")
    report_date = data.get("report_date", "")

    # Title + publisher text come from the node's cover layout (cover_layouts) —
    # the SAME builders the LaTeX cover uses, so the two surfaces can't drift.
    # The builders return unescaped lines; escape them for HTML here.
    layout = get_cover_layout(node.subtype)
    title_html = "<br>".join(_esc(line) for line in layout.title_builder(data))

    # Report number + date, each on its own line; omitted when absent.
    report_html = "<br>".join(
        _esc(line) for line in (report_number, report_date) if line
    )

    pub_html = "<br>".join(_esc(line) for line in layout.publisher_builder(data))

    # The title is the document <h1> (so sections nest under it for the
    # accessibility outline); .tp-title styling makes it a centered title
    # block, not a section heading.
    report_block = (
        f'<div class="tp-report">{report_html}</div>' if report_html else ""
    )
    return (
        '<section class="title-block">'
        f'<h1 class="tp-title">{title_html}</h1>'
        f"{report_block}"
        f'<div class="tp-publisher">{pub_html}</div>'
        "</section>"
    )


def _render_title_page(node: DocNode, data: dict) -> str:
    """Suppressed — the cover handler already emitted the title block."""
    return ""


def _freeform_body_html(node: DocNode) -> str:
    """
    The HTML body for a freeform node: the author's resolved HTML markup when
    this surface is native (or a dual-source mapping supplied one), else a
    pending note saying which surface the content was authored for.  Authored
    HTML is emitted VERBATIM (same trust model as injected genomics SVG).
    """
    resolved = node.resolved_content or {}
    html = resolved.get("html")
    if html:
        return html
    rep = node.representation or "latex"
    # pending_note already brackets its text (matching the LaTeX side), so wrap
    # in the .pending span directly rather than via _pending (which re-brackets).
    return f'<em class="pending">{_esc(_freeform_pending_note(rep, "html"))}</em>'


def _render_freeform_page(node: DocNode, data: dict) -> str:
    """
    Freeform authored page — forces its own page (break-before:page) and
    carries an optional heading plus the authored HTML body.
    """
    heading = _heading(node.level, node.title) if node.title else ""
    body = _freeform_body_html(node)
    inner = f"{heading}\n{body}" if heading else body
    return f'<section class="freeform-page" style="break-before:page">{inner}</section>'


def _render_freeform_block(node: DocNode, data: dict) -> str:
    """
    Freeform authored block — inline insert with NO forced page break.
    """
    heading = _heading(node.level, node.title) if node.title else ""
    body = _freeform_body_html(node)
    inner = f"{heading}\n{body}" if heading else body
    return f'<section class="freeform-block">{inner}</section>'


def _render_page_break(node: DocNode, data: dict) -> str:
    """
    An explicit author-placed page break.  Empty element carrying only a
    break-before:page — the same print-CSS mechanism freeform-page uses to
    start a new page.  Renders as nothing on screen; a page boundary in print
    and in the PDF preview.
    """
    return '<div class="page-break" style="break-before:page"></div>'


def _render_unimplemented(node: DocNode, data: dict) -> str:
    """
    Catch-all for node_types we haven't ported.  Emits this node's
    heading (if any) plus a visible pending placeholder.
    """
    heading = _heading(node.level, node.title) if node.level > 0 else ""
    placeholder = _pending(
        f"Section pending: {node.node_type} rendering not yet implemented"
    )
    return f"{heading}\n{placeholder}" if heading else f"<!-- {node.node_type} {node.id} -->{placeholder}"


# Dispatch table — one entry per DocNode.node_type value.  Mirrors
# latex_generator.py:_DISPATCH so the two stay in lock-step.  Anything
# not listed falls through to _render_unimplemented.
_DISPATCH: dict[str, object] = {
    "cover":            _render_cover,
    "title-page":       _render_title_page,
    "front-matter":     _render_front_matter,
    "narrative":        _render_narrative,
    "heading-only":     _render_heading_only,
    "appendix":         _render_appendix,
    "tables-list":      _render_tables_list,
    "toc":              _render_toc,
    "narrative+tables": _render_narrative_tables,
    "table":            _render_apical_table,
    "incidence-table":  _render_incidence_table,
    "sample-counts-table": _render_sample_counts_table,
    "bmd-summary":      _render_bmd_summary,
    "genomics-section": _render_genomics_section,
    "freeform-page":    _render_freeform_page,
    "freeform-block":   _render_freeform_block,
    "page-break":       _render_page_break,
}

# ADR-0006 #3: fail loudly at import if this table drifts from the canonical
# registry.  HTML implements every renderable type (it builds its own cover and
# title page), so no omissions are allowed.
assert_dispatch_covers(_DISPATCH, renderer="HTML")


# ---------------------------------------------------------------------------
# Round-trip overrides (ADR-0005) — preview side
# ---------------------------------------------------------------------------

def _apply_override_html(chunk: str, anchor_id: str, data: dict) -> str:
    """
    Reflect a human's ADR-0005 round-trip override in the HTML preview.

    The override store keys regions by anchor id (node.id or "<node>::<item>");
    a record carries the user's edited LaTeX (`latex_region`) and, once Phase B
    is in place, an `html_region` derived from it.  This is the preview-side
    counterpart of latex_generator._apply_override, but the surfaces differ:

      - LaTeX is the round-trip surface — it emits the override verbatim AND
        wraps it in begin/end sentinels so the reconciler can attribute later
        edits.  The preview is never edited and re-imported, so it needs only
        the SUBSTITUTION half, never the anchor half.
      - HTML can't emit raw LaTeX.  When the record has an `html_region` we emit
        it faithfully; otherwise we keep the generated chunk but mark it so the
        reviewer knows the on-screen version may be stale relative to the .tex.

    Either way the overridden id is recorded under data["_override_stale"] for
    parity with the LaTeX drift bookkeeping.  No override → chunk unchanged.
    """
    override = (data.get("overrides") or {}).get(anchor_id)
    if not override:
        return chunk
    data.setdefault("_override_stale", []).append(anchor_id)
    html_region = override.get("html_region")
    if html_region:
        return (
            '<div class="override-edited" '
            'title="Edited in Overleaf">'
            f"{html_region}</div>"
        )
    return (
        '<div class="override-stale" '
        'title="Edited in Overleaf — preview may be stale">'
        f"{chunk}</div>"
    )


# ---------------------------------------------------------------------------
# Tree walk
# ---------------------------------------------------------------------------

def _walk_html(node: DocNode, data: dict) -> list[str]:
    """
    Render a node and its descendants to a flat, document-ordered list of
    HTML chunks.

    Thin wrapper over the shared render_common.walk_emit skeleton (ADR-0006):
    the traversal + accumulator are common, only the HTML-specific emit below
    is passed in.  Same skeleton as latex_generator._walk_latex.

    The wrap_post differs from LaTeX by design (divergence #2): LaTeX applies
    the override substitution AND wraps each node in round-trip anchor sentinels
    (it is the Overleaf round-trip surface); HTML applies only the override
    SUBSTITUTION/marker (the preview is never edited and re-imported, so the
    sentinels would be meaningless).  See _apply_override_html.  Genomics
    content items carry a second, composite-key override grain applied inside
    _render_genomics_section, mirroring latex_generator.
    """
    return walk_emit(
        node, data,
        walk=walk_tree,
        dispatch=_DISPATCH,
        fallback=_render_unimplemented,
        # Zero-height anchor before each node so the navigation panel can scroll
        # the full preview to this section (frame.contentDocument
        # .getElementById("sec-<id>").scrollIntoView()).  Paged.js moves the
        # actual DOM nodes into page boxes, preserving these ids, so the scroll
        # target survives pagination.
        emit_pre=lambda n: f'<span id="sec-{_esc(n.id)}" class="sec-anchor"></span>',
        # Wrap in a .landscape-block (assigned to the landscape @page) when the
        # user flipped it AND the node's semantic type is orientable.
        wrap_landscape=lambda chunk: f'<div class="landscape-block">{chunk}</div>',
        # ADR-0005 node-grain override: mark/render a region a human edited in
        # Overleaf instead of silently showing the regenerated content.
        wrap_post=lambda n, chunk: _apply_override_html(chunk, n.id, data),
    )


# ---------------------------------------------------------------------------
# Document skeleton
# ---------------------------------------------------------------------------

def _running_header_css(running_header: str) -> str:
    """
    Build the @page top-center margin-box rule that carries the running
    header text.

    Paged.js renders this in the top margin of every page after the first
    (page 1 suppresses it — see _PAGED_MEDIA_CSS).  The text is dynamic —
    the report title for the full document, the section title for a
    fragment preview — so it can't live in the static _PAGED_MEDIA_CSS
    constant and is built here instead.

    NOTE — this header MATCHES the reference (NIEHS Report 10): the full
    title runs across the top of every page from Foreword onward (the
    cover/title pages before it carry none — see the @page cover rule).
    Our niehs.cls does NOT yet set it (article default = page number
    only), so the .tex Overleaf export is currently MISSING the header the
    reference has.  That's a parity GAP to close by adding fancyhdr to
    niehs.cls — not a deliberate divergence.

    Args:
        running_header: plain text for the header; "" suppresses it.

    Returns:
        A CSS snippet (one @page block), or "" when there's no header text.
    """
    if not running_header:
        return ""
    # CSS string escaping: backslash first (so the quote-escapes we add next
    # aren't themselves double-escaped), then the double-quote that delimits
    # the content string.
    escaped = running_header.replace("\\", "\\\\").replace('"', '\\"')
    # We're injecting into a <style> raw-text element.  CSS quote-escaping
    # does NOT stop an HTML "</style>" breakout — the HTML parser closes the
    # element on that literal regardless of CSS quoting.  Neutralise it by
    # rewriting "<" as its CSS unicode escape (the trailing space terminates
    # the hex escape); the browser still renders a literal "<" in the header.
    escaped = escaped.replace("<", "\\00003c ")
    return (
        "@page { @top-center {"
        f' content: "{escaped}";'
        ' font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;'
        " color: #4a5568; } }"
    )


def _document_skeleton(body: str, running_header: str = "") -> str:
    """
    Wrap the rendered body in a self-contained HTML5 document with inline
    CSS plus the Paged.js polyfill.  Self-contained because the iframe
    srcdoc is sandboxed from the parent page's stylesheet.

    The polyfill paginates the continuous body into printed-page sheets;
    see _PAGED_MEDIA_CSS / _PAGEDJS_SCRIPT for why and how.

    Args:
        body:           the rendered report body HTML.
        running_header: text for the per-page running header (the report
                        title for the full document); "" omits it.
    """
    return (
        "<!DOCTYPE html>"
        '<html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>NIEHS Report Preview</title>'
        f"<style>{_PREVIEW_CSS}{_PAGED_MEDIA_CSS}{_running_header_css(running_header)}</style>"
        "</head><body>"
        f"{body}"
        f"{_PAGEDJS_SCRIPT}"
        "</body></html>"
    )


def _fragment_skeleton(body: str, running_header: str = "") -> str:
    """
    Minimal HTML wrapper for fragment-compile previews.

    Stripped down: no title block (the cover/title-page nodes are outside
    the requested subtree), but still self-contained so the iframe srcdoc
    renders standalone.  Same CSS *and* the same Paged.js pagination as the
    full document, so a single-section card preview also renders as printed
    page sheets (per the chosen scope).

    Args:
        body:           the rendered fragment HTML.
        running_header: text for the per-page running header (the section
                        title for a fragment); "" omits it.
    """
    return (
        "<!DOCTYPE html>"
        '<html lang="en"><head>'
        '<meta charset="utf-8">'
        f"<style>{_PREVIEW_CSS}{_PAGED_MEDIA_CSS}{_FRAGMENT_ARABIC_PAGE_NUMBER}{_running_header_css(running_header)}</style>"
        "</head><body>"
        f"{body}"
        f"{_PAGEDJS_SCRIPT}"
        "</body></html>"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_html(
    data: dict,
    section_filter: Optional[str] = None,
    tree: "list | None" = None,
) -> str:
    """
    Walk the document tree + data and produce a complete HTML document.

    Args:
        data:           The data dict marshal_export_data builds (same
                        shape generate_latex consumes).
        section_filter: For the fragment-compile preview path.  When set,
                        only the subtree at that DocNode id renders.
        tree:           Optional per-session document tree.  When None (the
                        default), the global DOCUMENT_TREE is used, so existing
                        callers are unchanged.  A per-session structure override
                        is passed so the preview reflects the edited structure
                        (ADR-0007 follow-on) — the twin latex_generator threads
                        the same param for surface parity (ADR-0006).

    Returns:
        A self-contained HTML string suitable for iframe srcdoc.
    """
    nodes = tree if tree is not None else DOCUMENT_TREE
    # Fragment path — only emit the requested subtree.  The running header
    # for a fragment is the section's own title.
    if section_filter:
        node = find_node(section_filter, tree)
        if node is None:
            body = (
                f"<p><em>No section found for id "
                f"<code>{_esc(section_filter)}</code></em></p>"
            )
            return _fragment_skeleton(body)
        body = "\n".join(_walk_html(node, data))
        return _fragment_skeleton(body, running_header=node.title or "")

    # Full-document path — walk every top-level node in tree order, split at
    # the front-matter/body boundary so the page numbering can switch from
    # roman (front matter) to arabic (body).  The body (Background onward) is
    # wrapped in .report-mainmatter, which the CSS assigns to the arabic
    # "mainmatter" page, restarts the page counter at 1, and breaks onto a
    # fresh page — matching NIEHS Report 10 (Background = arabic page 1).
    # The split is driven by the body's first top-level node, which the tree
    # owns via first_body_node_id() (the first node with region == "body",
    # ADR-0004 amendment d).  We ask the tree for that boundary id rather than
    # re-deriving "region == body" here, so the HTML and LaTeX renderers stay
    # in lockstep on where front matter ends.  Once we reach it, every
    # subsequent top-level node goes into the body bucket.
    # The running header is the report title (same source as the cover
    # block's <h1>, so preview header and title block stay in sync).
    body_first_id = first_body_node_id(nodes)
    front_chunks: list[str] = []
    body_chunks: list[str] = []
    in_body = False
    for top in nodes:
        if top.id == body_first_id:
            in_body = True
        (body_chunks if in_body else front_chunks).extend(_walk_html(top, data))
    body = "\n".join(front_chunks)
    if body_chunks:
        body += (
            '\n<div class="report-mainmatter">\n'
            + "\n".join(body_chunks)
            + "\n</div>"
        )
    # Prefer the dedicated "running_header" metadata field (report_data.py
    # sets it to the full, never-abbreviated title form); fall back to the
    # plain title, then a placeholder, so a sparse data dict still renders.
    running_header = (
        data.get("running_header") or data.get("title") or "5dToxReport"
    )
    return _document_skeleton(body, running_header=running_header)
