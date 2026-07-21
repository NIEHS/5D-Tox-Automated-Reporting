r"""
docx_generator.py — Microsoft Word (.docx) rendering of the NIEHS biological
potency report.

This module is the third sibling of latex_generator.py and html_generator.py.
All three walk the same DOCUMENT_TREE with the same data dict and dispatch on the
same set of node_type values (render_common.RENDERABLE_NODE_TYPES); they differ
only in the output each per-node handler produces.  That gives a Word export a
1:1 semantic match with the Overleaf .tex and the in-app HTML preview — same
tree, same data, same dispatch, just a different emitter.

Why a third surface
-------------------
Some stakeholders' publishing workflows are Word-driven (track-changes review,
house .dotx templates).  ADR-0008 (Option B) accepted a Word emitter as a
one-way OUTPUT surface: we generate a .docx from the tree, but never treat Word
as a source of truth — the tree + data remain canonical (Architectural
Invariant #1/#2).  Round-tripping Word back INTO the tree is a separate,
existing concern (freeform_content.py ingests an authored .docx block); this
module is generation only.

Architecture mirror + the one deliberate divergence
---------------------------------------------------
The dispatch table and per-type handlers follow html_generator.py's structure.
The ONE structural difference: LaTeX and HTML emitters return markup STRINGS and
share render_common.walk_emit (which accumulates a flat list of chunks).  Word is
an object model — python-docx handlers MUTATE a Document in place — so a handler
here has signature ``_render_<type>(doc, node, data) -> None`` and this module
runs its own ``_walk_docx_tree`` rather than walk_emit.  Everything semantic
(which content source wins, table rows, captions, roster) still comes from the
shared render_common EXTRACT plans, so this surface cannot drift from the other
two on WHAT a section contains — only on how Word renders it.

Scope (v1)
----------
Full node-type parity (all 17 RENDERABLE_NODE_TYPES) + a clean typographic
cover/title page + roman→arabic two-section page numbering + booktabs-style
tables + inline genomics chart images.  NOT in v1 (deliberate, documented
follow-ups): the per-node ``layout_style`` styling the other two surfaces honour
(this surface uses the Word base styles), and a configurable-fonts binding.
"""

from __future__ import annotations

import base64
import re
from io import BytesIO

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from cover_layouts import get_cover_layout
from document_tree import DOCUMENT_TREE, DocNode, first_body_node_id, walk_tree
from freeform_content import pending_note as _freeform_pending_note
from render_common import (
    ANIMAL_ROSTER_HEADERS,
    BMD_SUMMARY_HEADERS,
    GENE_SET_TABLE_HEADERS,
    GENE_TABLE_HEADERS,
    apical_table_plan,
    appendix_roster_rows,
    assert_dispatch_covers,
    bmd_summary_plan,
    front_matter_plan,
    gene_set_table_rows,
    gene_table_rows,
    genomics_chart_caption,
    genomics_description_items,
    genomics_entries,
    genomics_intro_paragraphs,
    genomics_role,
    genomics_table_caption,
    has_paragraph_content,
    incidence_table_plan,
    methods_subsection_content,
    sample_counts_table,
    table_caption as _table_caption,
    unified_narrative_paragraphs,
)
from genomics_content import genomics_content_plan
from table_builder_common import format_display_number, format_mean_se_display


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# US-Letter page + one-inch margins (NIEHS Report 10 trim).
_PAGE_WIDTH = Inches(8.5)
_PAGE_HEIGHT = Inches(11.0)
_MARGIN = Inches(1.0)

# Brand accent for the cover bar, from the cover layout palette (sage/green).
_COVER_GREEN = RGBColor(0x78, 0xA1, 0x2E)
_COVER_TITLE_GRAY = RGBColor(0x53, 0x55, 0x57)

# DocNode.level → Word built-in heading style.  Level 0 = no heading (cover,
# leaf table nodes); levels 1-3 nest under the document title.
_HEADING_STYLE_BY_LEVEL: dict[int, str] = {
    1: "Heading 1",
    2: "Heading 2",
    3: "Heading 3",
}

# Strip C0 control chars (except tab/newline) that would make the OOXML invalid.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# Minimal HTML tag stripper for freeform html fallback (see _freeform_text).
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text) -> str:
    """Coerce a value to a control-char-free string safe for an OOXML run."""
    return _CONTROL_RE.sub("", str(text if text is not None else ""))


# ---------------------------------------------------------------------------
# Low-level docx helpers
# ---------------------------------------------------------------------------

def _add_heading(doc: Document, level: int, title: str) -> None:
    """Append a heading paragraph for levels 1-3; level 0/empty adds nothing."""
    style = _HEADING_STYLE_BY_LEVEL.get(level)
    if not style or not title:
        return
    doc.add_paragraph(_clean(title), style=style)


def _add_paragraphs(doc: Document, paragraphs) -> bool:
    """
    Append one body paragraph per non-empty string.  Returns True if anything
    was added (so callers can fall back to a pending line when nothing was).
    """
    added = False
    for p in paragraphs or []:
        text = _clean(p).strip()
        if not text:
            continue
        doc.add_paragraph(text)
        added = True
    return added


def _add_labeled_sections(doc: Document, parts) -> None:
    """
    Structured-abstract parts as paragraphs with a bold run-in label — the Word
    twin of html_generator._render_labeled_sections.  A "" label is unlabeled.
    """
    for label, text in parts:
        para = doc.add_paragraph()
        if label:
            run = para.add_run(f"{_clean(label)}. ")
            run.bold = True
        para.add_run(_clean(text))


def _add_pending(doc: Document, label: str) -> None:
    """Visible italic "[pending]" placeholder — the Word twin of _pending."""
    para = doc.add_paragraph()
    run = para.add_run(f"[{_clean(label)}]")
    run.italic = True


def _set_repeat_header(row) -> None:
    """Mark a table row as a header that repeats on each page (tblHeader)."""
    trPr = row._tr.get_or_add_trPr()
    tblHeader = OxmlElement("w:tblHeader")
    tblHeader.set(qn("w:val"), "true")
    trPr.append(tblHeader)


def _set_edge_border(el, edge: str, sz: str = "8") -> None:
    """
    Give a table (tblPr/tblBorders) or cell (tcPr/tcBorders) a single ``edge``
    border (top/bottom/...), leaving the others untouched.  Used to build the
    booktabs look (horizontal rules only).
    """
    if el.tag.endswith("}tbl"):
        pr = el.tblPr
        borders_tag = "w:tblBorders"
    else:  # a <w:tc> cell
        pr = el.get_or_add_tcPr()
        borders_tag = "w:tcBorders"
    borders = pr.find(qn(borders_tag))
    if borders is None:
        borders = OxmlElement(borders_tag)
        pr.append(borders)
    e = borders.find(qn(f"w:{edge}"))
    if e is None:
        e = OxmlElement(f"w:{edge}")
        borders.append(e)
    e.set(qn("w:val"), "single")
    e.set(qn("w:sz"), sz)
    e.set(qn("w:space"), "0")
    e.set(qn("w:color"), "000000")


def _booktabs_table(
    doc: Document,
    headers: list[str],
    rows: list[list[str]],
    *,
    caption: str = "",
    footnotes: list | None = None,
    merged_label_rows: bool = False,
) -> None:
    """
    Append a booktabs-style table (top rule, header rule, bottom rule; no
    vertical or inner-body rules) — the Word analogue of the ``niehstable``
    environment / HTML ``.niehstable``.

    caption:            rendered as a bold paragraph ABOVE the table (NIEHS
                        places table captions above), matching the "Table N."
                        text the shared _table_caption / genomics_table_caption
                        already built.
    footnotes:          the typed footnote dicts render as small paragraphs
                        below the table (lettered entries keep their letter).
    merged_label_rows:  when True, a body row whose first cell is wrapped in
                        ``**...**`` (the apical / sample-counts sex separator)
                        is emitted as a single bold cell merged across all
                        columns — the Word twin of the HTML colspan row.
    """
    if caption:
        cap = doc.add_paragraph()
        cap.add_run(_clean(caption)).bold = True

    ncols = max(len(headers), max((len(r) for r in rows), default=0), 1)
    table = doc.add_table(rows=0, cols=ncols)
    table.autofit = True

    if headers:
        hcells = table.add_row().cells
        for i, h in enumerate(headers):
            if i >= ncols:
                break
            para = hcells[i].paragraphs[0]
            para.add_run(_clean(h)).bold = True
        _set_repeat_header(table.rows[0])
        for c in table.rows[0]._tr.tc_lst:
            _set_edge_border(c, "bottom")

    for row in rows:
        cells = [_clean(c) for c in row]
        first = cells[0] if cells else ""
        if merged_label_rows and first.startswith("**") and first.endswith("**"):
            tr = table.add_row()
            merged = tr.cells[0]
            for other in tr.cells[1:]:
                merged = merged.merge(other)
            merged.paragraphs[0].add_run(first.strip("*").strip()).bold = True
            continue
        tr = table.add_row()
        for i in range(ncols):
            val = cells[i].strip() if i < len(cells) else ""
            tr.cells[i].paragraphs[0].add_run(val)

    # Outer top + bottom rules complete the booktabs frame.
    _set_edge_border(table._tbl, "top")
    _set_edge_border(table._tbl, "bottom")

    _add_footnotes(doc, footnotes)


def _add_footnotes(doc: Document, footnotes) -> None:
    """Render table footnotes as small paragraphs below a table."""
    for fn in footnotes or []:
        if not isinstance(fn, dict):
            continue
        text = fn.get("text") or fn.get("body") or ""
        if not text:
            continue
        para = doc.add_paragraph()
        if fn.get("kind") == "lettered" and fn.get("letter"):
            marker = para.add_run(f"{_clean(fn['letter'])} ")
            marker.font.superscript = True
            marker.font.size = Pt(8)
        run = para.add_run(_clean(text))
        run.font.size = Pt(8)


def _add_page_break(doc: Document) -> None:
    """Append an explicit page break (its own empty paragraph)."""
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


# ---------------------------------------------------------------------------
# Per-node-type render handlers — _render_<type>(doc, node, data) -> None
# ---------------------------------------------------------------------------
# Each handler appends this node's OWN content to the Document (children are
# walked separately by _walk_docx_tree).  Mirrors the html_generator handlers
# 1:1 in which shared EXTRACT plan it consumes.


def _render_front_matter(doc: Document, node: DocNode, data: dict) -> None:
    """Front-matter / narrative section: heading + labeled-sections or prose."""
    _add_heading(doc, node.level, node.title)
    plan = front_matter_plan(node, data)
    if plan.kind == "labeled":
        _add_labeled_sections(doc, plan.labeled_parts)
    elif plan.kind == "paragraphs":
        _add_paragraphs(doc, plan.paragraphs)
    else:
        _add_pending(doc, f"Section pending: {node.title}")


def _render_narrative(doc: Document, node: DocNode, data: dict) -> None:
    """Plain narrative — M&M subsections route through the methods lookup."""
    if node.methods_key:
        _render_methods_subsection(doc, node, data)
    else:
        _render_front_matter(doc, node, data)


def _render_methods_subsection(doc: Document, node: DocNode, data: dict) -> None:
    """M&M subsection — prose + optional inline table, matched by methods_key."""
    _add_heading(doc, node.level, node.title)
    paragraphs, inline = methods_subsection_content(node, data)
    added = _add_paragraphs(doc, paragraphs) if has_paragraph_content(paragraphs) else False
    if inline is not None:
        _render_inline_table(doc, inline)
        added = True
    if not added:
        _add_pending(doc, f"Section pending: {node.title}")


def _render_inline_table(doc: Document, table: dict) -> None:
    """Inline neutral {caption, headers, rows, footnotes} table."""
    headers = [str(h) for h in table.get("headers", [])]
    rows = [[str(c) for c in r] for r in table.get("rows", [])]
    if not headers and not rows:
        return
    _booktabs_table(
        doc, headers, rows,
        caption=table.get("caption", ""),
        footnotes=table.get("footnotes", []),
    )


def _render_sample_counts_table(doc: Document, node: DocNode, data: dict) -> None:
    """Methods 'Final Sample Counts' matrix (Table 1) with sex-separator rows."""
    built = sample_counts_table(node, data)
    if built is None:
        _add_pending(doc, f"Table data pending: {node.title}")
        return
    headers = [str(h) for h in built.get("headers", [])]
    rows = [[str(c) for c in r] for r in built.get("rows", [])]
    _booktabs_table(
        doc, headers, rows,
        caption=_table_caption(node, built.get("caption", "")),
        footnotes=built.get("footnotes", []),
        merged_label_rows=True,
    )


def _render_heading_only(doc: Document, node: DocNode, data: dict) -> None:
    """Structural heading; children rendered separately by the walker."""
    _add_heading(doc, node.level, node.title)


def _render_appendix(doc: Document, node: DocNode, data: dict) -> None:
    """Appendix — B renders the animal roster; others heading + stub/children."""
    _add_heading(doc, node.level, node.title)
    rows = appendix_roster_rows(node, data)
    if rows is not None:
        _booktabs_table(
            doc, list(ANIMAL_ROSTER_HEADERS), rows,
            caption="Table B-1. Animal Numbers and FASTQ Data File Names",
        )
        return
    if not node.children:
        _add_pending(doc, f"Appendix body pending: {node.title}")


def _render_tables_list(doc: Document, node: DocNode, data: dict) -> None:
    """Front-matter list of tables from data['table_entries']."""
    _add_heading(doc, node.level, node.title)
    entries = data.get("table_entries") or []
    if not entries:
        _add_pending(doc, "List of tables: pending.")
        return
    for entry in entries:
        n = entry.get("table_number")
        title = entry.get("title", "")
        line = f"Table {n}. {title}" if n is not None else title
        doc.add_paragraph(_clean(line), style="List Number")


def _render_toc(doc: Document, node: DocNode, data: dict) -> None:
    """
    Contents — a STATIC list built from data['toc_entries'], indented by level.

    Word can auto-generate a TOC field, but that renders as "right-click →
    update field" until the user does so; a static list is what actually shows
    on open and mirrors the HTML preview exactly (the LaTeX path uses native
    \\tableofcontents).
    """
    doc.add_paragraph(_clean(node.title), style="Heading 1")
    entries = data.get("toc_entries") or []
    if not entries:
        _add_pending(doc, "Table of contents: pending.")
        return
    for entry in entries:
        lvl = entry.get("level", 1)
        para = doc.add_paragraph(_clean(entry.get("title", "")))
        if isinstance(lvl, int) and lvl > 1:
            para.paragraph_format.left_indent = Pt((lvl - 1) * 18)


def _render_narrative_tables(doc: Document, node: DocNode, data: dict) -> None:
    """H2 group under Results: heading + unified narrative; tables walked after."""
    _add_heading(doc, node.level, node.title)
    paragraphs = unified_narrative_paragraphs(node, data)
    if has_paragraph_content(paragraphs):
        _add_paragraphs(doc, paragraphs)
    else:
        _add_pending(doc, f"Narrative pending: {node.title}")


def _render_apical_table(doc: Document, node: DocNode, data: dict) -> None:
    """Apical dose-response table (Male/Female blocks, BMD/BMDL columns)."""
    plan = apical_table_plan(node, data)
    if plan is None:
        _add_pending(doc, f"Table data pending: {node.title}")
        return
    headers = (
        [plan.first_col]
        + [_format_dose_label(d, plan.dose_unit) for d in plan.doses]
        + [f"BMD 1Std ({plan.dose_unit})", f"BMDL 1Std ({plan.dose_unit})"]
    )
    rows: list[list[str]] = []
    for block in plan.sex_blocks:
        rows.append([f"**{block.sex_label}**"])
        for row in block.rows:
            rows.append(row.cells)
    _booktabs_table(
        doc, headers, rows,
        caption=plan.caption, footnotes=plan.footnotes, merged_label_rows=True,
    )


def _render_incidence_table(doc: Document, node: DocNode, data: dict) -> None:
    """Clinical Observations incidence table (observation × dose group)."""
    plan = incidence_table_plan(node, data)
    if plan is None:
        _add_pending(doc, f"Table data pending: {node.title}")
        return
    headers = ["Observation"] + [_format_dose_label(d, plan.dose_unit) for d in plan.doses]
    _booktabs_table(
        doc, headers, plan.rows, caption=plan.caption, footnotes=plan.footnotes,
    )


def _render_bmd_summary(doc: Document, node: DocNode, data: dict) -> None:
    """Apical Endpoint BMD Summary — prose + one row per endpoint."""
    plan = bmd_summary_plan(node, data)
    _add_heading(doc, node.level, node.title)
    prose = _add_paragraphs(doc, plan.paragraphs)
    if plan.rows is None:
        if not prose:
            _add_pending(doc, f"BMD summary endpoints pending: {node.title}")
        return
    _booktabs_table(doc, list(BMD_SUMMARY_HEADERS), plan.rows, caption=plan.caption)


def _render_genomics_section(doc: Document, node: DocNode, data: dict) -> None:
    """Gene Set / Gene BMD section — per-(organ, sex) subsections."""
    role = genomics_role(node)
    _add_heading(doc, node.level, node.title)
    intro = _add_paragraphs(doc, genomics_intro_paragraphs(node, data))

    entries = genomics_entries(node, data)
    if not entries:
        if not intro:
            _add_pending(doc, f"Genomics data pending: {node.title}")
        return

    for entry in entries:
        organ = (entry.get("organ") or "").capitalize()
        sex = (entry.get("sex") or "").capitalize()
        doc.add_paragraph(_clean(f"{organ}, {sex}"), style="Heading 4")
        for item in genomics_content_plan(entry, role):
            _render_genomics_item(doc, entry, role, item)


def _render_genomics_item(doc: Document, entry: dict, role: str, item: dict) -> None:
    """One content item of a genomics (organ, sex) block."""
    part = item.get("part")
    if part == "narrative":
        _add_paragraphs(doc, entry.get("narrative") or [])
    elif part == "table":
        if role == "gene_set":
            _render_gene_set_table(doc, entry)
        else:
            _render_gene_table(doc, entry)
    elif part == "chart":
        chart = next(
            (c for c in (entry.get("charts") or []) if c.get("key") == item.get("chart_key")),
            None,
        )
        if chart:
            _add_chart_image(doc, chart)
    elif part == "descriptions":
        descriptions = (
            entry.get("go_descriptions") if role == "gene_set"
            else entry.get("gene_descriptions")
        ) or []
        _add_description_list(doc, descriptions)


def _render_gene_set_table(doc: Document, entry: dict) -> None:
    """Top-gene-sets table for one (organ, sex)."""
    rows = gene_set_table_rows(entry)
    if rows is None:
        _add_pending(doc, f"Top gene sets pending: {entry.get('organ','')}, {entry.get('sex','')}")
        return
    _booktabs_table(doc, list(GENE_SET_TABLE_HEADERS), rows, caption=genomics_table_caption(entry))


def _render_gene_table(doc: Document, entry: dict) -> None:
    """Top-genes table for one (organ, sex)."""
    rows = gene_table_rows(entry)
    if rows is None:
        _add_pending(doc, f"Top genes pending: {entry.get('organ','')}, {entry.get('sex','')}")
        return
    _booktabs_table(doc, list(GENE_TABLE_HEADERS), rows, caption=genomics_table_caption(entry))


def _add_description_list(doc: Document, descriptions) -> None:
    """A definition list of go-term / gene descriptions (bold term + text)."""
    for label, text in genomics_description_items(descriptions):
        para = doc.add_paragraph()
        if label:
            para.add_run(f"{_clean(label)}: ").bold = True
        para.add_run(_clean(text))


def _add_chart_image(doc: Document, chart: dict) -> None:
    """Embed a genomics chart PNG inline (decoded from its base64 payload)."""
    png = chart.get("png_b64", "")
    if not png:
        return
    if png.startswith("data:"):
        png = png.split(",", 1)[1]
    try:
        raw = base64.b64decode(png)
        doc.add_picture(BytesIO(raw), width=Inches(5.5))
    except Exception:
        return
    caption = genomics_chart_caption(chart)
    if caption:
        cap = doc.add_paragraph()
        run = cap.add_run(_clean(caption))
        run.italic = True
        run.font.size = Pt(9)
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _render_cover(doc: Document, node: DocNode, data: dict) -> None:
    """
    Cover / inner title page — a clean typographic block (no image-backed cover;
    Word can't embed a PDF page, and the branded-cover pixel work is a LaTeX/HTML
    concern).  Title + report number/date + publisher, centered, over a green
    accent bar drawn as a shaded one-cell table (the brand nod).  Title/publisher
    text come from the SAME cover_layouts builders the other surfaces use.
    """
    layout = get_cover_layout(node.subtype)

    _add_cover_bar(doc)

    for line in layout.title_builder(data):
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(_clean(line))
        run.bold = True
        run.font.size = Pt(20)
        run.font.color.rgb = _COVER_TITLE_GRAY

    for meta in (data.get("report_number", ""), data.get("report_date", "")):
        if not meta:
            continue
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.add_run(_clean(meta)).font.size = Pt(12)

    doc.add_paragraph()
    for line in layout.publisher_builder(data):
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.add_run(_clean(line)).font.size = Pt(11)


def _add_cover_bar(doc: Document) -> None:
    """A slim full-width green bar (shaded one-cell table) atop the cover."""
    table = doc.add_table(rows=1, cols=1)
    cell = table.rows[0].cells[0]
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), "78A12E")
    cell._tc.get_or_add_tcPr().append(shd)
    cell.paragraphs[0].add_run("")


def _render_title_page(doc: Document, node: DocNode, data: dict) -> None:
    """Suppressed — the cover handler already emitted the title block."""
    return


def _freeform_text(node: DocNode) -> str:
    """
    Plain text for a freeform node on the Word surface.  There is no docx entry
    in resolved_content ({latex, html}); fall back to the html body with tags
    stripped (readable prose), else a pending note naming the authored surface.
    """
    resolved = node.resolved_content or {}
    html = resolved.get("html")
    if html:
        text = _TAG_RE.sub("", html)
        return re.sub(r"\s+\n", "\n", text).strip()
    rep = node.representation or "latex"
    return _freeform_pending_note(rep, "html")


def _render_freeform_page(doc: Document, node: DocNode, data: dict) -> None:
    """Freeform authored page — forces its own page, then heading + body text."""
    _add_page_break(doc)
    if node.title:
        _add_heading(doc, node.level, node.title)
    _add_paragraphs(doc, _freeform_text(node).split("\n\n"))


def _render_freeform_block(doc: Document, node: DocNode, data: dict) -> None:
    """Freeform authored block — inline, no forced page break."""
    if node.title:
        _add_heading(doc, node.level, node.title)
    _add_paragraphs(doc, _freeform_text(node).split("\n\n"))


def _render_page_break(doc: Document, node: DocNode, data: dict) -> None:
    """An explicit author-placed page break."""
    _add_page_break(doc)


def _render_unimplemented(doc: Document, node: DocNode, data: dict) -> None:
    """Catch-all — heading (if any) + a visible pending placeholder."""
    _add_heading(doc, node.level, node.title)
    _add_pending(doc, f"Section pending: {node.node_type} rendering not yet implemented")


def _format_dose_label(dose, unit: str) -> str:
    """Format a dose value with its unit (the Word/plain-space form)."""
    if dose == 0 or dose == 0.0:
        return f"0 {unit}"
    if isinstance(dose, float) and dose.is_integer():
        return f"{int(dose)} {unit}"
    return f"{dose} {unit}"


# ---------------------------------------------------------------------------
# Dispatch registry — validated against the canonical set at import (ADR-0006 #3)
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, object] = {
    "cover":               _render_cover,
    "title-page":          _render_title_page,
    "front-matter":        _render_front_matter,
    "narrative":           _render_narrative,
    "heading-only":        _render_heading_only,
    "appendix":            _render_appendix,
    "tables-list":         _render_tables_list,
    "toc":                 _render_toc,
    "narrative+tables":    _render_narrative_tables,
    "table":               _render_apical_table,
    "incidence-table":     _render_incidence_table,
    "sample-counts-table": _render_sample_counts_table,
    "bmd-summary":         _render_bmd_summary,
    "genomics-section":    _render_genomics_section,
    "freeform-page":       _render_freeform_page,
    "freeform-block":      _render_freeform_block,
    "page-break":          _render_page_break,
}

# Fail loudly at import if this table drifts from the canonical registry — the
# same guarantee the HTML and LaTeX surfaces get (ADR-0006 #3).  Word implements
# every renderable type, so no omissions are allowed.
assert_dispatch_covers(_DISPATCH, renderer="Word/OOXML")


# ---------------------------------------------------------------------------
# Tree walk + document skeleton
# ---------------------------------------------------------------------------

def _walk_docx_tree(doc: Document, node: DocNode, data: dict) -> None:
    """
    Render a node and its descendants into the Document in document order.

    The Word analogue of html_generator._walk_html / latex_generator._walk_latex,
    but it can't reuse render_common.walk_emit: that skeleton accumulates markup
    STRINGS, whereas Word handlers mutate the Document.  So this runs the shared
    walk_tree primitive directly with a _visit callback that dispatches to the
    (doc, node, data) handlers — same pre-order traversal, object-model emit.
    """
    def _visit(n: DocNode) -> None:
        handler = _DISPATCH.get(n.node_type, _render_unimplemented)
        handler(doc, n, data)

    walk_tree([node], _visit)


def _set_section_page_numbering(section, fmt: str, start: int) -> None:
    """
    Set a section's <w:pgNumType> format (lowerRoman / decimal) + start.

    <w:pgNumType> must sit at its schema-mandated position in CT_SectPr (after
    pgSz/pgMar, before cols) — a bare append lands it after docGrid, which is
    out of sequence and gets silently dropped on save.  We insert it before the
    first of the elements the schema says follow it, so the ordering is valid
    regardless of which of those a given section happens to carry.
    """
    sectPr = section._sectPr
    pgNumType = sectPr.find(qn("w:pgNumType"))
    if pgNumType is None:
        pgNumType = OxmlElement("w:pgNumType")
        _insert_in_schema_order(
            sectPr, pgNumType,
            successors=("w:cols", "w:formProt", "w:vAlign", "w:noEndnote",
                        "w:titlePg", "w:textDirection", "w:bidi", "w:rtlGutter",
                        "w:docGrid", "w:printerSettings", "w:sectPrChange"),
        )
    pgNumType.set(qn("w:fmt"), fmt)
    pgNumType.set(qn("w:start"), str(start))


def _insert_in_schema_order(parent, element, *, successors: tuple[str, ...]) -> None:
    """
    Insert ``element`` before the first existing child whose tag is in
    ``successors`` (the elements the schema requires to come AFTER it), else
    append.  Keeps a hand-built element valid against the OOXML sequence.
    """
    for tag in successors:
        found = parent.find(qn(tag))
        if found is not None:
            found.addprevious(element)
            return
    parent.append(element)


def _add_page_number_field(paragraph) -> None:
    """Insert a PAGE field into a (footer) paragraph, centered by the caller."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def _configure_section(section, running_header: str) -> None:
    """US-Letter geometry + a running header + a centered page-number footer."""
    section.page_width = _PAGE_WIDTH
    section.page_height = _PAGE_HEIGHT
    for attr in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, attr, _MARGIN)

    header_para = section.header.paragraphs[0]
    header_para.text = _clean(running_header)
    header_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    footer_para = section.footer.paragraphs[0]
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_page_number_field(footer_para)


def generate_docx(data: dict, tree: "list | None" = None) -> bytes:
    """
    Walk the document tree + data and produce a complete .docx as bytes.

    Same data dict the other two surfaces consume (report_data.marshal_export_data
    / latex_export.load_session_data).  Front matter is roman-numbered and the
    body restarts at arabic 1 at first_body_node_id — the same boundary the
    HTML/LaTeX surfaces switch on, so the three agree on where front matter ends.

    Args:
        data: the render-ready data dict.
        tree: optional per-session DocNode forest; None uses DOCUMENT_TREE.

    Returns:
        The .docx file contents as bytes (ready to write to disk or stream).
    """
    nodes = tree if tree is not None else DOCUMENT_TREE
    running_header = data.get("running_header") or data.get("title") or "5dToxReport"

    doc = Document()
    front_section = doc.sections[0]
    _configure_section(front_section, running_header)
    # No page number on the cover page itself (front matter numbering still
    # counts it as page i, matching the reference's unnumbered cover).
    front_section.different_first_page_header_footer = True

    body_first_id = first_body_node_id(nodes)
    added_body_section = False
    in_body = False

    for top in nodes:
        if body_first_id is not None and top.id == body_first_id and not in_body:
            # Section break → the body restarts page numbering at arabic 1.
            doc.add_section(WD_SECTION.NEW_PAGE)
            _configure_section(doc.sections[-1], running_header)
            added_body_section = True
            in_body = True
        _walk_docx_tree(doc, top, data)

    # Page-number formats: front matter lower-roman, body decimal-from-1.
    # add_section() relocates the FIRST section's <w:sectPr> into the last
    # body paragraph, so a reference captured before that call goes stale —
    # re-fetch both sections from doc.sections here, after all breaks are in.
    _set_section_page_numbering(doc.sections[0], "lowerRoman", 1)
    if added_body_section:
        _set_section_page_numbering(doc.sections[-1], "decimal", 1)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
