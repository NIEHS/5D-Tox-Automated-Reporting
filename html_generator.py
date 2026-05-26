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
    FRONT_MATTER_NODE_TYPES,
    DocNode,
    find_node,
)


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
/* Invisible per-section scroll target for TOC navigation — see _walk. */
.sec-anchor { display: block; height: 0; margin: 0; padding: 0; }
em.pending {
  color: #b7791f;
  background: #fff7ed;
  padding: 1px 6px;
  border-radius: 3px;
  font-style: normal;
  font-size: 12.5px;
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
    return _html.escape(str(text), quote=True)


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


def _table_caption(node: DocNode, base_caption: str) -> str:
    """
    Prefix the caption with "Table N. " from the auto-assigned
    table_number, mirroring latex_generator's behavior.  Strips any
    leftover {compound} / {sex} placeholder tokens.
    """
    cleaned = (base_caption or "")
    cleaned = cleaned.replace("{sex}", "Male and Female").replace("{compound}", "")
    cleaned = cleaned.strip()
    if node.table_number is not None:
        return f"Table {node.table_number}. {cleaned}" if cleaned else f"Table {node.table_number}"
    return cleaned


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
    """
    body = ""
    if node.data_key:
        content = data.get(node.data_key)
        if isinstance(content, dict):
            paragraphs = content.get("paragraphs", [])
            body = _render_paragraphs(paragraphs)
    if not body:
        body = _pending(f"Section pending: {node.title}")
    return f"{_heading(node.level, node.title)}\n{body}"


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
    M&M subsection — content lives in data["methods"]["sections"] as a
    flat list keyed by heading (title-match).  Mirrors the LaTeX
    handler's lookup strategy.
    """
    body = ""
    methods = data.get("methods", {})
    if isinstance(methods, dict):
        for section in methods.get("sections", []):
            if section.get("heading") == node.title:
                body = _render_paragraphs(section.get("paragraphs", []))
                table_inline = section.get("table")
                if isinstance(table_inline, dict):
                    body = (body + "\n" + _render_inline_table(table_inline)).strip()
                break
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


def _render_heading_only(node: DocNode, data: dict) -> str:
    """Structural heading; children rendered separately by the walker."""
    return _heading(node.level, node.title)


def _render_appendix(node: DocNode, data: dict) -> str:
    """Appendix node — heading + visible body-pending placeholder."""
    body = f'<div class="appendix-stub">Appendix body pending: {_esc(node.title)}</div>'
    return f"{_heading(node.level, node.title)}\n{body}"


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


# ---------------------------------------------------------------------------
# Results-section handlers (narrative+tables, tables, bmd-summary,
# incidence-table, genomics-section)
# ---------------------------------------------------------------------------

def _find_apical_section(node: DocNode, data: dict) -> Optional[dict]:
    """Same platform-match lookup the LaTeX handler uses."""
    sections = data.get("apical_sections", []) or []
    for sec in sections:
        if sec.get("platform") and sec["platform"] == node.platform:
            return sec
    for sec in sections:
        if sec.get("title") and node.platform in sec.get("title", ""):
            return sec
    return None


def _render_apical_table(node: DocNode, data: dict) -> str:
    """
    Apical dose-response table — HTML mirror of latex_generator's
    _render_apical_table.  Identical row-iteration logic so the LaTeX
    and HTML views show the same data shape.

    Reads from the same apical_sections entry, uses the same n-row /
    data-row / sex-separator structure, formats values the same way.
    """
    section = _find_apical_section(node, data)
    if not section or not section.get("table_data"):
        return _emit_table_placeholder(node)

    table_data = section.get("table_data", {})
    male_rows = table_data.get("Male", []) or []
    female_rows = table_data.get("Female", []) or []
    if not male_rows and not female_rows:
        return _emit_table_placeholder(node)

    dose_unit = section.get("dose_unit", "mg/kg")
    first_col = section.get("first_col_header", "Endpoint")

    ref_row = (male_rows or female_rows)[0]
    doses = ref_row.get("doses", []) or []

    headers = (
        [first_col]
        + [_format_dose_label(d, dose_unit) for d in doses]
        + [f"BMD₁Std ({dose_unit})", f"BMDL₁Std ({dose_unit})"]
    )
    ncols = len(headers)

    body_rows: list[str] = []
    for sex_label, rows in (("Male", male_rows), ("Female", female_rows)):
        if not rows:
            continue
        # Sex separator row spanning all columns.
        body_rows.append(
            f'<tr class="sex-separator"><td colspan="{ncols}">'
            f"<strong>{_esc(sex_label)}</strong></td></tr>"
        )
        for row in rows:
            label = row.get("endpoint") or row.get("day_label") or row.get("label") or ""
            values = row.get("values", []) or []
            bmd = row.get("bmd", "—") or "—"
            bmdl = row.get("bmdl", "—") or "—"
            cells = [str(label), *[str(v) for v in values], str(bmd), str(bmdl)]
            while len(cells) < ncols:
                cells.append("—")
            tr_class = "n-row" if row.get("is_n_row") else ""
            body_rows.append(_emit_table_row(cells, tr_class=tr_class))

    head = _emit_table_header(headers)
    notes = _emit_table_footnotes(section.get("footnotes", []))
    caption = _table_caption(node, section.get("caption", ""))
    return (
        '<table class="niehstable">'
        f"<caption>{_esc(caption)}</caption>"
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
    are walked separately by _walk.
    """
    paragraphs: list = []
    if node.narrative_key:
        unified = data.get("unified_narratives", {})
        if isinstance(unified, dict):
            entry = unified.get(node.narrative_key)
            if isinstance(entry, list):
                paragraphs = entry
            elif isinstance(entry, dict):
                paragraphs = entry.get("paragraphs", []) or []
    body = _render_paragraphs(paragraphs)
    if not body:
        body = _pending(f"Narrative pending: {node.title}")
    return f"{_heading(node.level, node.title)}\n{body}"


def _render_bmd_summary(node: DocNode, data: dict) -> str:
    """Apical Endpoint Benchmark Dose Summary table."""
    summary = data.get("bmd_summary", {}) or {}
    endpoints = summary.get("endpoints", []) or []
    paragraphs = summary.get("paragraphs", []) or []

    heading = _heading(node.level, node.title)
    prose = _render_paragraphs(paragraphs)

    if not endpoints:
        body = prose or _pending(f"BMD summary endpoints pending: {node.title}")
        return f"{heading}\n{body}"

    headers = ["Sex", "Endpoint", "BMD", "BMDL", "LOEL", "NOEL", "Direction"]
    body_rows = []
    for ep in endpoints:
        cells = [
            ep.get("sex", ""),
            ep.get("endpoint", ""),
            ep.get("bmd", "—") or "—",
            ep.get("bmdl", "—") or "—",
            ep.get("loel", "—") or "—",
            ep.get("noel", "—") or "—",
            ep.get("direction", ""),
        ]
        body_rows.append(_emit_table_row([str(c) for c in cells]))

    caption = _table_caption(node, node.title)
    table = (
        '<table class="niehstable">'
        f"<caption>{_esc(caption)}</caption>"
        f"{_emit_table_header(headers)}"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )
    chunks = [c for c in (heading, prose, table) if c]
    return "\n".join(chunks)


def _render_incidence_table(node: DocNode, data: dict) -> str:
    """Clinical Observations incidence table — observation × dose group."""
    section = _find_apical_section(node, data)
    if not section:
        return _emit_table_placeholder(node)
    rows = section.get("incidence_rows", []) or section.get("rows", []) or []
    if not rows:
        return _emit_table_placeholder(node)

    doses = section.get("doses", []) or []
    dose_unit = section.get("dose_unit", "mg/kg")
    headers = ["Observation"] + [_format_dose_label(d, dose_unit) for d in doses]
    ncols = len(headers)

    body_rows = []
    for row in rows:
        label = row.get("observation") or row.get("label") or ""
        counts = row.get("counts") or row.get("values") or []
        cells = [str(label), *[str(c) for c in counts]]
        while len(cells) < ncols:
            cells.append("0")
        body_rows.append(_emit_table_row(cells))

    caption = _table_caption(node, section.get("caption", "") or node.title)
    notes = _emit_table_footnotes(section.get("footnotes", []))
    return (
        '<table class="niehstable">'
        f"<caption>{_esc(caption)}</caption>"
        f"{_emit_table_header(headers)}"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        f"{notes}"
    )


def _render_genomics_section(node: DocNode, data: dict) -> str:
    """Gene Set or Gene BMD section — per-(organ, sex) subsections."""
    role = "gene_set" if node.id == "gene-sets" else "gene"
    heading = _heading(node.level, node.title)
    top_narrative_key = "gene_set_narrative" if role == "gene_set" else "gene_narrative"
    top_nar = data.get(top_narrative_key)
    intro_paragraphs: list = []
    if isinstance(top_nar, list):
        intro_paragraphs = top_nar
    elif isinstance(top_nar, dict) and isinstance(top_nar.get("paragraphs"), list):
        intro_paragraphs = top_nar["paragraphs"]
    intro = _render_paragraphs(intro_paragraphs)

    entries = [
        s for s in (data.get("genomics_sections", []) or [])
        if s.get("type") == role
    ]
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
        narrative = entry.get("narrative") or []
        if narrative:
            blocks.append(_render_paragraphs(narrative))
        if role == "gene_set":
            blocks.append(_render_gene_set_table(entry))
        else:
            blocks.append(_render_gene_table(entry))
        descriptions = (
            entry.get("go_descriptions") if role == "gene_set"
            else entry.get("gene_descriptions")
        ) or []
        if descriptions:
            blocks.append(_render_description_list(descriptions))

    return "\n".join(b for b in blocks if b)


def _render_gene_set_table(entry: dict) -> str:
    """Top-gene-sets table for one (organ, sex)."""
    rows = entry.get("gene_sets", []) or []
    if not rows:
        return _pending(
            f"Top gene sets pending: {entry.get('organ', '')}, {entry.get('sex', '')}"
        )
    headers = ["Rank", "GO ID", "Term", "BMD", "BMDL", "Genes", "Direction"]
    body_rows = []
    for r in rows:
        cells = [
            r.get("rank", ""),
            r.get("go_id", ""),
            r.get("go_term", ""),
            r.get("bmd", "—"),
            r.get("bmdl", "—"),
            r.get("n_genes", ""),
            r.get("direction", ""),
        ]
        body_rows.append(_emit_table_row([str(c) for c in cells]))
    return (
        '<table class="niehstable">'
        f"{_emit_table_header(headers)}"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


def _render_gene_table(entry: dict) -> str:
    """Top-genes table for one (organ, sex)."""
    rows = entry.get("top_genes", []) or []
    if not rows:
        return _pending(
            f"Top genes pending: {entry.get('organ', '')}, {entry.get('sex', '')}"
        )
    headers = ["Rank", "Gene", "BMD", "BMDL", "Direction", "Fold Change"]
    body_rows = []
    for r in rows:
        cells = [
            r.get("rank", ""),
            r.get("gene") or r.get("gene_symbol", ""),
            r.get("bmd", "—"),
            r.get("bmdl", "—"),
            r.get("direction", ""),
            r.get("fold_change", "—"),
        ]
        body_rows.append(_emit_table_row([str(c) for c in cells]))
    return (
        '<table class="niehstable">'
        f"{_emit_table_header(headers)}"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


def _render_description_list(descriptions: list) -> str:
    """A <dl> of go-term or gene definitions for the genomics section."""
    items: list[str] = []
    for d in descriptions:
        if not isinstance(d, dict):
            continue
        label = (
            d.get("label")
            or d.get("go_term")
            or d.get("gene")
            or d.get("go_id")
            or ""
        )
        text = d.get("text") or d.get("description") or ""
        if not (label or text):
            continue
        items.append(f"<dt>{_esc(label)}</dt><dd>{_esc(text)}</dd>")
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
    chemical = data.get("chemical_name", "")
    casrn = data.get("casrn", "")
    strain = data.get("strain", "(Hsd:Sprague Dawley® SD®)")
    report_number = data.get("report_number", "")
    report_date = data.get("report_date", "")
    issn = data.get("issn", "")

    # "title-name" — the most formal identifier: chemical plus CASRN
    # (matches the Typst ta-form("title")).
    title_name = chemical + (f" (CASRN {casrn})" if casrn else "")

    # Bold title block.  Hard line breaks at the same semantic points as the
    # reference; long chemical/strain lines wrap naturally when centered.
    title_lines = [
        "NIEHS Report on the",
        "In Vivo Repeat Dose Biological Potency Study of",
        title_name,
        f"in Sprague Dawley {strain} Rats",
        "(Gavage Studies)",
    ]
    title_html = "<br>".join(_esc(line) for line in title_lines if line)

    # Report number + date, each on its own line; omitted when absent.
    report_html = "<br>".join(
        _esc(line) for line in (report_number, report_date) if line
    )

    # Publisher block — static institutional lines, with the ISSN inserted
    # when present.
    pub_lines = [
        "National Institute of Environmental Health Sciences",
        "Public Health Service",
        "U.S. Department of Health and Human Services",
    ]
    if issn:
        pub_lines.append(f"ISSN: {issn}")
    pub_lines.append("Research Triangle Park, North Carolina, USA")
    pub_html = "<br>".join(_esc(line) for line in pub_lines)

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
    "narrative+tables": _render_narrative_tables,
    "table":            _render_apical_table,
    "incidence-table":  _render_incidence_table,
    "bmd-summary":      _render_bmd_summary,
    "genomics-section": _render_genomics_section,
}


# ---------------------------------------------------------------------------
# Tree walk
# ---------------------------------------------------------------------------

def _walk(node: DocNode, data: dict) -> list[str]:
    """
    Render one node, then recurse into its children.  Same flow as
    latex_generator._walk; only the handlers differ.
    """
    handler = _DISPATCH.get(node.node_type, _render_unimplemented)
    chunks: list[str] = []
    chunk = handler(node, data)
    if chunk:
        # Zero-height anchor before each node so the TOC can scroll the
        # full preview to this section (frame.contentDocument
        # .getElementById("sec-<id>").scrollIntoView()).  Paged.js moves
        # the actual DOM nodes into page boxes, preserving these ids, so
        # the scroll target survives pagination.
        chunks.append(f'<span id="sec-{_esc(node.id)}" class="sec-anchor"></span>')
        chunks.append(chunk)
    for child in node.children:
        chunks.extend(_walk(child, data))
    return chunks


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
) -> str:
    """
    Walk DOCUMENT_TREE + data and produce a complete HTML document.

    Args:
        data:           The data dict marshal_export_data builds (same
                        shape generate_latex consumes).
        section_filter: For the fragment-compile preview path.  When set,
                        only the subtree at that DocNode id renders.

    Returns:
        A self-contained HTML string suitable for iframe srcdoc.
    """
    # Fragment path — only emit the requested subtree.  The running header
    # for a fragment is the section's own title.
    if section_filter:
        node = find_node(section_filter)
        if node is None:
            body = (
                f"<p><em>No section found for id "
                f"<code>{_esc(section_filter)}</code></em></p>"
            )
            return _fragment_skeleton(body)
        body = "\n".join(_walk(node, data))
        return _fragment_skeleton(body, running_header=node.title or "")

    # Full-document path — walk every top-level node in tree order, split at
    # the front-matter/body boundary so the page numbering can switch from
    # roman (front matter) to arabic (body).  The body (Background onward) is
    # wrapped in .report-mainmatter, which the CSS assigns to the arabic
    # "mainmatter" page, restarts the page counter at 1, and breaks onto a
    # fresh page — matching NIEHS Report 10 (Background = arabic page 1).
    # The running header is the report title (same source as the cover
    # block's <h1>, so preview header and title block stay in sync).
    front_chunks: list[str] = []
    body_chunks: list[str] = []
    in_body = False
    for top in DOCUMENT_TREE:
        if not in_body and top.node_type not in FRONT_MATTER_NODE_TYPES:
            in_body = True
        (body_chunks if in_body else front_chunks).extend(_walk(top, data))
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
